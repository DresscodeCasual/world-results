from django.contrib.auth.decorators import user_passes_test
from django.shortcuts import get_object_or_404, redirect
from django.core.files.temp import NamedTemporaryFile
from django.shortcuts import render, redirect
from django.db.models.query import Prefetch
from django.contrib import messages
from django.core.files import File
from django.db.models import Count

import os
import re
from typing import Any, List, Optional, TextIO, Tuple
import urllib.parse

from results import models, models_klb, results_util
from results.views.views_common import user_edit_vars
from editor import parse_protocols

def group_required(*group_names):
	"""Requires user membership in at least one of the groups passed in."""
	def in_groups(user):
		if user.is_authenticated:
			if user.groups.filter(name__in=group_names).exists() | user.is_superuser:
				return True
		return False
	return user_passes_test(in_groups)

# Update field_name in model from value_old to value_new and update args_to_update
def update_fields(request, model, field_name, old_value, new_value, args_to_update):
	kwargs = {field_name: old_value}
	query = model.objects.filter(**kwargs)
	if old_value != new_value:
		user_is_admin = models.is_admin(request.user)
		for row in query:
			table_update = models.Table_update.objects.create(model_name=model.__name__, row_id=row.id,
				action_type=models.ACTION_UPDATE, user=request.user, is_verified=user_is_admin)
			for key, val in list(args_to_update.items()):
				if getattr(row, key) != val:
					models.Field_update.objects.create(table_update=table_update, field_name=key, new_value=val)
	n_rows = query.update(**args_to_update)
	if n_rows > 0:
		messages.success(request, 'Пол{} {} в таблице {} исправлен{} у {} записей.'.format(
			'я' if len(args_to_update) else 'е',
			", ".join([field_name] + [key for key, val in list(args_to_update.items())]),
			model._meta.db_table,
			'ы' if len(args_to_update) else 'о',
			n_rows))

def update_city(request, city_old, city_new=None):
	if city_new is None:
		city_new = city_old
	args = {}
	if city_old != city_new:
		args['city'] = city_new
		update_fields(request, models.Series, 'city_finish', city_old, city_new, {'city_finish': city_new})
		update_fields(request, models.Event, 'city_finish', city_old, city_new, {'city_finish': city_new})
		update_fields(request, models.User_profile, 'city', city_old, city_new, args)
		update_fields(request, models.City_conversion, 'city', city_old, city_new, args)
		update_fields(request, models.Runner, 'city', city_old, city_new, args)
		update_fields(request, models.Klb_participant, 'city', city_old, city_new, args)
		# update_fields(request, models.Result, 'city', city_old, city_new, args) Not used yet
	update_fields(request, models.Club, 'city', city_old, city_new, args)

	update_fields(request, models.Series, 'city', city_old, city_new, args)
	update_fields(request, models.Event, 'city', city_old, city_new, args)
	update_fields(request, models.Klb_person, 'city', city_old, city_new, args)

def update_distance(request, distance_old, distance_new=None):
	if distance_new is None:
		distance_new = distance_old
	args = {}
	if distance_old != distance_new:
		args['distance'] = distance_new
	update_fields(request, models.Race, 'distance', distance_old, distance_new, args)
	update_fields(request, models.Race, 'distance_real', distance_old, distance_new, {'distance_real': distance_new})
	update_fields(request, models.Split, 'distance', distance_old, distance_new, {'distance': distance_new})

def update_series(request, series_old, series_new):
	args = {'series': series_new}
	update_fields(request, models.Event, 'series', series_old, series_new, args)
	update_fields(request, models.Series_editor, 'series', series_old, series_new, args)
	update_fields(request, models.Document, 'series', series_old, series_new, args)
	update_fields(request, models.Series_name, 'series', series_old, series_new, args)

def update_event(request, event_old, event_new):
	args = {'event': event_new}
	update_fields(request, models.Race, 'event', event_old, event_new, args)
	update_fields(request, models.News, 'event', event_old, event_new, args)
	update_fields(request, models.Document, 'event', event_old, event_new, args)

def update_organizer(request, organizer_old, organizer_new):
	args = {'organizer': organizer_new}
	update_fields(request, models.Series, 'organizer', organizer_old, organizer_new, args)

def update_runner(request, creator, runner_old, runner_new):
	results = runner_old.result_set.select_related('race__event')
	for result in results:
		table_update = models.Table_update.objects.create(model_name='Event', row_id=result.race.event.id, child_id=result.id,
			action_type=models.ACTION_UPDATE, user=creator, is_verified=models.is_admin(creator))
		models.Field_update.objects.create(table_update=table_update, field_name='runner', new_value=runner_new.get_name_and_id())
	n_rows = results.update(runner=runner_new)
	if request and (n_rows > 0):
		messages.success(request, f'Поле runner в таблице dj_result исправлено у {n_rows} записей.')
	n_extra_names = runner_old.extra_name_set.update(runner=runner_new)
	if request and (n_extra_names > 0):
		messages.success(request, f'Перенесено дополнительных имён у старого бегуна к новому: {n_extra_names}')
	n_records = runner_old.record_result_set.update(runner=runner_new)
	if request and (n_records > 0):
		messages.success(request, f'Исправлено записей о рекордах в возрастных группах: {n_records}')

def srcrepl(match, hostname):
	return "<" + match.group(1) + match.group(2) + "=\"" + hostname + "/" + match.group(3) + "\"" + match.group(4) + ">"

def get_hostname(url: str) -> str:
	parsed_uri = urllib.parse.urlparse(url)
	return f'{parsed_uri.scheme}://{parsed_uri.netloc}'

# Replace relative links with absolute ones in HTML files that we download
def fix_relative_links(content: bytes, url: str, headers: Optional[Any] = None) -> bytes:
	if headers and (headers.get_content_maintype() != 'text'):
		return content
	try:
		decoded = content.decode(results_util.get_encoding(headers))
		if '<body' not in decoded.lower():
			return decoded.encode()
		hostname = get_hostname(url)
		p = re.compile(r"<(.*?)(src|action|href)=[\'\"]/(?!/)(.*?)[\'\"](.*?)>")
		return p.sub(lambda match: srcrepl(match, hostname), decoded).encode()
	except Exception as e:
		models.send_panic_email(
			'We could not decode an HTML page',
			f'Мы пытались декодировать страницу с адреса {url}, но это не удалось.\n\n'
			+ f'Возникшая ошибка: {repr(e)}',
			to_all=False,
		)
		return content

# https://www.instagram.com/a.jpg?hl=en&taken-by=nike -> a.jpg
def get_maybe_filename(url: str) -> str:
	path = urllib.parse.urlparse(url).path.split('/')
	if len(path) == 1:
		return ''
	return path[-1]

# Returns three parameters.
# If succeeded: 1, NamedTemporaryFile object, file name (only extension is important), list of tuples with errors
# Otherwise:    0, None, error message, []
def try_load_document(url, is_protocol) -> Tuple[bool, Optional[TextIO], str, List[Tuple[str, str]]]:
	doc_temp = NamedTemporaryFile(delete=False)
	if is_protocol:
		is_rr_url, succeeded, dists_with_errors = parse_protocols.try_load_russiarunning_protocol(url, doc_temp.name)
		if is_rr_url:
			if succeeded:
				return True, doc_temp, '1.xlsx', dists_with_errors
			else:
				return False, None, '', dists_with_errors

	result, content, _, headers, error = results_util.read_url(url, to_decode=False)
	if not result:
		return False, None, error, []
	doc_temp.write(fix_relative_links(content, url, headers))
	doc_temp.flush()
	return True, doc_temp, get_maybe_filename(url), []

def process_document_formset(request, formset): # Load files to disk if needed. Formset must already be checked as valid
	for form in formset:
		url = form.cleaned_data.get('url_source')
		if form.cleaned_data.get('try_to_load') and url and not form.cleaned_data.get('DELETE', False):
			if url.startswith(('https://vk.com', 'https://facebook.com', 'https://www.dropbox.com', 'https://docviewer.yandex.ru')):
				messages.warning(request, f'Не пытаемся загружать на диск страницу {url}: из соцсетей так толком ничего не сохранить.')
				continue
			result, file_or_error, maybe_filename, dists_with_errors = try_load_document(url,
				is_protocol=(form.cleaned_data.get('document_type') in models.DOC_PROTOCOL_TYPES))
			if result:
				form.instance.upload.save(maybe_filename, File(file_or_error), save=False)
				form.instance.loaded_type = models.LOAD_TYPE_LOADED
				for dist, error in dists_with_errors:
					messages.warning(request, f'Ошибка при загрузке протокола на дистанцию {dist}: {error}')
					models.send_panic_email(
						'Problem with a protocol on russiarunning.com',
						f'Мы пытались загрузить результаты с адреса {url}.\n\n'
						+ f'Возникла ошибка при загрузке протокола на дистанцию {dist}: {error}',
						to_all=True,
					)
				messages.success(request, f'Файл {url} успешно загружен на сервер')
				os.remove(file_or_error.name)
			else:
				messages.warning(request, f'Не получилось загрузить файл по адресу {url}. Ошибка: {file_or_error}')

# Returns context, has_rights, where-to-redirect-if-false
def check_rights(request, event=None, series=None, club=None, show_warning=True):
# def check_rights(request, event=None, series=None, club=None) -> Tuple[dict[str, Any], bool, Optional[str]]:
	if (series is None) and event:
		series = event.series
	context = user_edit_vars(request.user, series=series, club=club)
	if context['is_admin']:
		return context, True, None
	if series:
		if (event is None) and context['is_editor']:
			return context, True, None
		if event and context['is_editor'] and (context['is_extended_editor'] or (event.start_date is None) or event.can_be_edited()):
			return context, True, None
		if show_warning:
			messages.warning(request, 'У Вас нет прав на это действие.')
		if event and event.id:
			target = redirect(event)
		else:
			target = redirect(series)
		return context, False, target
	elif club:
		if context['is_editor']:
			return context, True, None
		if club.id:
			if show_warning:
				messages.warning(request, 'У Вас нет прав на это действие.')
			return context, False, redirect(club)
		else: # If we are creating new club
			if request.user.is_authenticated:
				return context, True, None
			else:
				if show_warning:
					messages.warning(request, 'У Вас нет прав на это действие.')
				return context, False, redirect('results:clubs')
	if show_warning:
		messages.warning(request, 'У Вас нет прав на это действие.')
	return context, False, redirect('results:home')

# For payments: is user paying for team or club? Does he have rights for that now?
def get_team_club_year_context_target(request, team_id, club_id):
	team = club = target = participants = None
	if team_id:
		team = get_object_or_404(models.Klb_team, pk=team_id)
		club = team.club
		year = team.year
		team_or_club = team
	else:
		club = get_object_or_404(models.Club, pk=club_id)
		year = models_klb.CUR_KLB_YEAR
		team_or_club = club

	context, _, target = check_rights(request, club=club)
	if target is None:
		if team and (not models.is_active_klb_year(year, context['is_admin'])) and (not models.PAYMENTS_FOR_OLD_MATCHES_ALLOWED):
			messages.warning(request, 'Вы уже не можете оплачивать участие в матче за {} год'.format(year))
			target = redirect(team)
		else:
			if team:
				participants = team.klb_participant_set
			else:
				team_ids = set(club.klb_team_set.filter(year=year).values_list('pk', flat=True))
				participants = models.Klb_participant.objects.filter(team_id__in=team_ids)

	return team, club, team_or_club, year, context, target, participants

def changes_history(request, obj, obj_link, context=None, obj_id=None):
	if context is None:
		context = {}
		context['is_editor'] = models.is_admin(request.user)
	context['changes'] = models.Table_update.objects.filter(model_name=obj.__class__.__name__, row_id=obj.id).select_related(
		'user', 'verified_by').prefetch_related(Prefetch('field_update_set',
		queryset=models.Field_update.objects.order_by('field_name'))).annotate(n_messages=Count('message_from_site')).order_by('-added_time')
	context['obj_link'] = obj_link
	# When obj is User_profile, we need user id instead of User_profile id
	context['page_title'] = f'{obj} (id {obj_id if obj_id else obj.id}): история изменений'
	return render(request, "editor/changes_history.html", context)
