from django.shortcuts import render
from django.contrib import messages

from results import models
from .views_common import group_required

@group_required('admins')
def replace_in_event_names(request):
	if request.method != 'POST':
		return util(request)
	replace_what = request.POST.get('replace_what', '')
	if replace_what and len(replace_what) >= 3:
		replace_to = request.POST.get('replace_to', '')
	else:
		messages.warning(request, 'Можно заменять строку длиной хотя бы 3 символа')
		return util(request)

	to_replace = ('btnReplace' in request.POST)

	events = models.Event.objects.filter(name__icontains=replace_what)
	messages.success(request, 'Всего {} забегов на замену'.format(events.count()))
	n_events_to_change = 0
	for event in events:
		new_name = event.name.replace(replace_what, replace_to)
		if new_name != event.name:
			messages.warning(request, 'Забег {}: {} -> {}'.format(event.id, event.name, new_name))
			n_events_to_change += 1
			if to_replace:
				event.name = new_name
				event.save()
				models.log_obj_create(request.user, event, models.ACTION_UPDATE, field_list=['name'], comment='Массовое переименование')


	seria = models.Series.objects.filter(name__icontains=replace_what)
	messages.success(request, 'Всего {} серий на замену'.format(seria.count()))
	n_series_to_change = 0
	for series in seria:
		new_name = series.name.replace(replace_what, replace_to)
		if new_name != series.name:
			messages.warning(request, 'Серия {}: {} -> {}'.format(series.id, series.name, series.name.replace(replace_what, replace_to)))
			n_series_to_change += 1
			if to_replace:
				series.name = new_name
				series.save()
				models.log_obj_create(request.user, series, models.ACTION_UPDATE, field_list=['name'], comment='Массовое переименование')

	messages.success(request, 'Всего изменяем {} забегов, {} серий'.format(n_events_to_change, n_series_to_change))

	context = {}
	context['replace_what'] = replace_what
	context['replace_to'] = replace_to
	return util(request, context)

@group_required('admins')
def scrape_athlinks_protocol(request):
	# if request.method != 'POST':
		return util(request)
	# url = request.POST.get('url', '')
	# if url == '':
	# 	messages.warning(request, 'Вы не указали URL')
	# 	return util(request)
	# result, response = athlinks.athlinks_protocol_response(url)
	# if result:
	# 	return response
	# else:
	# 	messages.warning(request, f'Не получилось загрузить протокол: {response}')
	# 	return util(request)

@group_required('admins')
def util(request, context={}):
	context['page_title'] = 'Разные мелкие штуки'
	return render(request, "editor/util.html", context)
