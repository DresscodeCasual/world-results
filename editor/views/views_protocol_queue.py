from django.contrib import messages
from django.db.models.query import Prefetch
from django.shortcuts import get_object_or_404, render, redirect
from django.utils import timezone

import os
import re
from typing import Optional

from results import models, results_util
from editor import forms
from editor.scrape import athlinks, main, util
from editor.views import views_common

@views_common.group_required('admins')
def queue(request):
	context = {}
	context['page_title'] = 'Очередь протоколов на загрузку'
	queue = models.Scraped_event.objects.select_related('protocol__event').prefetch_related(
			Prefetch('download_attempt_set', queryset=models.Download_attempt.objects.all().order_by('-start_time'))
		).order_by('id') #.order_by('-added_time')
	context['queues'] = [
		('Ошибки и загружающиеся сейчас', queue.filter(result__in=(models.DOWNLOAD_SUCCESS_WITH_WARNINGS, models.DOWNLOAD_ERROR, models.DOWNLOAD_IN_PROGRESS))),
	]
	for platform_id in util.ACTIVE_PLATFORM_IDS:
		if count := models.Scraped_event.objects.filter(platform_id=platform_id, result=models.DOWNLOAD_NOT_STARTED).count():
			context['queues'].append((
				f'Ждущие очереди из {platform_id} (всего: {count})',
				util.EventQueue(platform_id)[:5],
			))
	context['queues'].append(('Успешно загруженные (последние 100)', queue.filter(result=models.DOWNLOAD_SUCCESS).order_by('-last_attempt_finished')[:100]))
	context['formEvent'] = forms.ProtocolQueueAddEventForm()
	context['formSeries'] = forms.ProtocolQueueAddSeriesForm()
	return render(request, 'editor/protocol_queue.html', context)

# When any admin presses a button near a link to a protocol: protocol_id is present.
# When a form at /editor/protocol_queue/ is submitted, that field is empty.
@views_common.group_required('admins')
def add_to_queue(request, protocol_id: Optional[int]=None):
	url = event = protocol = None
	target = 'editor:protocol_queue'
	if protocol_id:
		protocol = get_object_or_404(models.Document, pk=protocol_id)
		event = protocol.event
		if not event:
			messages.warning(request, f'Протокол с ID {protocol_id} не привязан ни к какому забегу')
			return redirect('results:main_page')
		url = protocol.url_source
		if not protocol.is_eligible_for_queue():
			messages.warning(request, f'Протокол с ID {protocol_id} и адресом {url} не умеем добавлять в очередь')
			return redirect(target)
		target = event
	else:
		if 'frmProtocol_submit' not in request.POST:
			return redirect(target)
		form = forms.ProtocolQueueAddEventForm(request.POST)
		if not form.is_valid():
			messages.warning(request, 'Что-то не так с полями формы')
			return redirect(target)
		url = form.cleaned_data['url']
	if models.Scraped_event.objects.filter(url=url).exists():
		messages.warning(request, f'URL {url} уже есть в очереди')
		return redirect(target)
	models.Scraped_event.objects.create(url=url, protocol=protocol)
	messages.success(request, f'URL {url} добавлен в очередь')
	return redirect(target)

@views_common.group_required('admins')
def add_series_to_queue(request):
	url = event = protocol = None
	target = 'editor:scraped_event'
	if 'frmProtocol_submit' not in request.POST:
		return redirect(target)
	form = forms.ProtocolQueueAddSeriesForm(request.POST)
	if not form.is_valid():
		messages.warning(request, 'Что-то не так с полями формы')
		return redirect(target)
	url = form.cleaned_data['url']
	match = re.match(r'https://www.athlinks.com/event/(\d+)/', url)
	if not match:
		messages.warning(request, f'Мы не поняли ID серии из адреса {url}')
		return redirect(target)
	ath_series_id = results_util.int_safe(match.group(1))
	success, message = athlinks.add_series_events_to_queue(ath_series_id, form.cleaned_data['series_id'])
	if success:
		messages.success(request, message)
	else:
		messages.warning(request, message)
	return redirect(target)

@views_common.group_required('admins')
def mark_item_not_failed(request, row_id: int):
	row = get_object_or_404(models.Scraped_event, pk=row_id)
	if row.result not in (models.DOWNLOAD_SUCCESS, models.DOWNLOAD_ERROR):
		messages.warning(request, f'У URL {row.url_site} и так всё в порядке')
		return redirect('editor:protocol_queue')
	if request.GET.get('delete_event_file'):
		scraper = main.Scraper(row, row.download_attempt_set.first())
		path = scraper.StandardFormPath()
		if os.path.isfile(path):
			os.remove(path)
			messages.success(request, 'Файл забега в стандартной форме удалён')
		else:
			messages.warning(request, f'Файл {path} не существует')
	row.result = models.DOWNLOAD_NOT_STARTED
	row.save()
	messages.success(request, f'URL {row.url_site} возвращён в очередь')
	return redirect('editor:protocol_queue')

@views_common.group_required('admins')
def mark_item_stopped(request, row_id: int):
	row = get_object_or_404(models.Scraped_event, pk=row_id)
	if row.result != models.DOWNLOAD_IN_PROGRESS:
		messages.warning(request, f'URL {row.url_site} и так сейчас не обрабатывается')
		return redirect('editor:protocol_queue')
	row.result = models.DOWNLOAD_NOT_STARTED
	row.save()
	n_attempts = row.download_attempt_set.filter(result=models.DOWNLOAD_IN_PROGRESS).update(
		result=models.DOWNLOAD_ERROR,
		finish_time=timezone.now(),
		error='Помечен как остановленный администратором')
	messages.success(request, f'Все текущие попытки с URL {row.url_site} помечены как завершённые')
	return redirect('editor:protocol_queue')
