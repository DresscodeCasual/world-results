from django.shortcuts import get_object_or_404, render, redirect
from django.forms import modelformset_factory
from django.contrib import messages
from django.db.models import Sum
from django.db import transaction

import datetime
import logging
from typing import Tuple

from results import models, results_util
from editor import forms, generators, runner_stat, stat
from .views_user_actions import log_form_change, log_document_formset, log_change_event_series
from .views_common import group_required, update_event, process_document_formset, check_rights, changes_history
from . import views_klb, views_klb_stat, views_parkrun, views_stat

from tools.flock_mutex import Flock_mutex
from starrating.constants import LOCK_FILE_FOR_RATED_TREE_MODIFICATIONS
from starrating.aggr.rated_tree_modifications import change_parent, transfer_children_before_node_deletion
from starrating.exceptions import UpdatedRecordExistsError

N_EXTRA_RACES = 3

def getRaceFormSet(user, event, data=None):
	RaceFormSet = modelformset_factory(models.Race, form=forms.RaceForm, can_delete=True, extra=N_EXTRA_RACES)
	return RaceFormSet(
		data=data,
		queryset=event.race_set.select_related('distance').order_by('distance__distance_type', '-distance__length', 'precise_name'),
		initial=[{'event': event, 'created_by': user}] * N_EXTRA_RACES,
	)

def make_event_news_text(event):
	races = event.race_set.filter(loaded=models.RESULTS_LOADED).select_related('distance').order_by(
		'distance__distance_type', '-distance__length', 'precise_name')
	races_count = races.count()
	if races_count == 0:
		return ''
	if races_count > 1:
		total_participants = races.aggregate(Sum('n_participants'), Sum('n_participants_finished'),
			Sum('n_participants_finished_male'))
		total = total_participants['n_participants__sum']
		total_finished = total_participants['n_participants_finished__sum']
		total_finished_men = total_participants['n_participants_finished_male__sum']
		total_finished_women = total_participants['n_participants_finished__sum'] - total_finished_men
	else:
		race = races[0]
	res = '<p>{} в {} прошёл {}'.format(event.dateFull(), event.strCityCountry(), event.name)
	if races_count == 1:
		res += ' на дистанцию {}'.format(race.distance_with_heights())
	res += '.</p>\n'
	if races_count > 1:
		res += '<p>Всего в нём приняли участие {} человек{}'.format(total, results_util.ending(total, 9))
		if 0 < total_finished < total:
			res += f', финишировали {total_finished} человек{results_util.ending(total_finished, 9)}'
		if 0 < total_finished_men < total_finished:
			res += f' ({total_finished_men} мужчин и {total_finished_women} женщин)'
		res += '.</p>\n'
		for race in races:
			if race.n_participants_finished == 1:
				if race.n_participants_finished_male:
					finished_ending = ''
				else:
					finished_ending = 'и'
			else:
				finished_ending = 'о'
			res += f'<p>На дистанции {race.distance_with_heights()} (финишировал{finished_ending} '
			if race.n_participants_finished_male:
				res += f'{race.n_participants_finished_male}'
				res += f' мужчин{results_util.ending(race.n_participants_finished_male, 13)}'
				if race.n_participants_finished_female:
					res += f' и {race.n_participants_finished_female} женщин{results_util.ending(race.n_participants_finished_female, 2)}'
			else:
				res += f'{race.n_participants_finished} человек{results_util.ending(race.n_participants_finished, 9)}'
			res += ') победил'
			if race.n_participants_finished_male < race.n_participants_finished:
				res += 'и'
			res += f' {race.winner_male_fname} {race.winner_male_lname} '
			if race.winner_male_city:
				res += f'({race.winner_male_city}) '
			res += f'— {race.winner_male_result}'
			if race.n_participants_finished_male < race.n_participants_finished:
				res += ' и'
				res += f' {race.winner_female_fname} {race.winner_female_lname} '
				if race.winner_female_city:
					res += f'({race.winner_female_city}) '
				res += f'— {race.winner_female_result}'
			res += '.</p>\n'
	else:
		res += f'<p>В нём приняли участие {race.n_participants} человек{results_util.ending(race.n_participants, 9)}'
		if 0 < race.n_participants_finished < race.n_participants:
			res += f', финишировали {race.n_participants_finished}'
			res += f' человек{results_util.ending(race.n_participants_finished, 9)}'
		if 0 < race.n_participants_finished_male < race.n_participants_finished:
			res += f' ({race.n_participants_finished_male} мужчин{results_util.ending(race.n_participants_finished_male, 13)} '
			res += f'и {race.n_participants_finished_female} женщин{results_util.ending(race.n_participants_finished_female, 2)})'
		res += '.</p>\n'
		res += '<p>Победил'
		if race.n_participants_finished_male < race.n_participants_finished:
			res += 'и'
		res += f' {race.winner_male_fname} {race.winner_male_lname} '
		if race.winner_male_city:
			res += f'({race.winner_male_city}) '
		res += f'— {race.winner_male_result}'
		if race.n_participants_finished_male < race.n_participants_finished:
			res += f' и {race.winner_female_fname} {race.winner_female_lname} '
			if race.winner_female_city:
				res += f'({race.winner_female_city}) '
			res += f'— {race.winner_female_result}'
		res += '.</p>\n'
	return res

def getNewsFormSet(user, event, is_admin, data=None, files=None, make_news_from_event=False):
	initial = {'event': event, 'created_by': user, 'author': user.get_full_name()}
	if make_news_from_event:
		initial['content'] = make_event_news_text(event)
	NewsFormSet = modelformset_factory(models.News, form=forms.NewsForm, can_delete=True)
	return NewsFormSet(
		data=data,
		files=files,
		queryset=models.News.objects.filter(event=event).order_by('-date_posted'),
		initial=[initial],
		form_kwargs={'is_admin': is_admin},
	)

def getDocumentFormSet(user, event, data=None, files=None):
	DocumentFormSet = modelformset_factory(models.Document, form=forms.DocumentForm, can_delete=True, extra=N_EXTRA_RACES)
	return DocumentFormSet(
		data=data,
		files=files,
		queryset=models.Document.objects.filter(event=event).order_by('document_type', 'comment'),
		initial=[{'event': event, 'created_by': user}] * N_EXTRA_RACES,
	)

@group_required('editors', 'admins')
def event_details(request, event_id=None, event=None, frmDocuments=None, frmNews=None, cloned_event=None, frmEvent=None,
		frmForEvent=forms.ForEventForm(auto_id='frmForEvent_%s'), frmForSeries=None, frmRaces=None, news_id=None,
		make_news_from_event=False):
	if not event: # False if we are creating new event
		event = get_object_or_404(models.Event, pk=event_id)
	context, has_rights, target = check_rights(request, event=event)
	if not has_rights:
		return target
	if not frmEvent:
		initial = {}
		if event.city:
			initial['city'] = event.city
			initial['region'] = event.city.region.id
		frmEvent = forms.EventForm(instance=event, initial=initial, user=request.user)

	context['event'] = event
	context['frmEvent'] = frmEvent
	context['frmForEvent'] = frmForEvent
	context['cloned_event'] = cloned_event

	if cloned_event:
		context['page_title'] = 'Клонирование забега'
	elif event.id is None:
		context['page_title'] = 'Создание нового забега'
	else:
		context['page_title'] = '{}, {}'.format(event, event.dateFull())
		context['n_documents'] = event.document_set.count()
		context['n_news'] = event.news_set.count()
		context['n_races'] = event.race_set.count()
		if frmRaces is None:
			frmRaces = getRaceFormSet(request.user, event)
		context['frmRaces'] = frmRaces
		if frmDocuments is None:
			frmDocuments = getDocumentFormSet(request.user, event)
		context['frmDocuments'] = frmDocuments
		if frmNews is None:
			frmNews = getNewsFormSet(request.user, event, is_admin=context['is_admin'], make_news_from_event=make_news_from_event)
			if make_news_from_event:
				context['races'] = [{'distance': str(race.distance), 'race': race}
					for race in models.Race.objects.filter(event__series=event.series,
						event__start_date__lte=datetime.date.today()).order_by(
						'distance__distance_type', '-distance__length', '-event__start_date').select_related(
						'distance', 'distance_real', 'event')
				]
		context['frmNews'] = frmNews
		if frmForSeries is None:
			frmForSeries = forms.ForSeriesForm(auto_id='frmForSeries_%s')
		context['frmForSeries'] = frmForSeries
		context['news_id'] = results_util.int_safe(news_id)

	return render(request, "editor/event_details.html", context)

@group_required('editors', 'admins')
def event_details_make_news(request, event_id):
	return event_details(request, event_id=event_id, make_news_from_event=True)

@group_required('editors', 'admins')
def event_changes_history(request, event_id):
	event = get_object_or_404(models.Event, pk=event_id)
	_, has_rights, target = check_rights(request, event=event)
	if not has_rights:
		return target
	return changes_history(request, event, event.get_absolute_url())

@group_required('editors', 'admins')
def event_update(request, event_id):
	event = get_object_or_404(models.Event, pk=event_id)
	context, has_rights, target = check_rights(request, event=event)
	if not has_rights:
		return target
	if 'frmEvent_submit' in request.POST:
		form = forms.EventForm(request.POST, instance=event, user=request.user)
		if form.is_valid():
			event = form.save()
			log_form_change(request.user, form, action=models.ACTION_UPDATE, exclude=['country', 'region'])
			messages.success(request, 'Пробег «{}» успешно обновлён. Проверьте, всё ли правильно.'.format(event))
			if ('not_in_klb' in form.changed_data) and event.not_in_klb:
				klb_result_actions = models.Table_update.objects.filter(
					model_name=event.__class__.__name__,
					row_id=event.id,
					action_type__in=models.RESULT_ACTIONS,
					is_verified=False,
					is_for_klb=True
				)
				if klb_result_actions.exists():
					n_klb_result_actions = klb_result_actions.count()
					klb_result_actions.update(is_for_klb=False)
					messages.success(request,
						f'Запросов на модерацию в КЛБМатч отменено, поскольку забег помечен как негодный: {n_klb_result_actions}')
			return redirect(event.get_editor_url())
		else:
			messages.warning(request, 'Пробег не обновлён. Пожалуйста, исправьте ошибки в форме.')
	else:
		form = forms.EventForm(instance=event, user=request.user)
	return event_details(request, event_id=event_id, event=event, frmEvent=form)

@group_required('editors', 'admins')
def event_distances_update(request, event_id):
	event = get_object_or_404(models.Event, pk=event_id)
	context, has_rights, target = check_rights(request, event=event)
	user = request.user
	if not has_rights:
		return target
	if 'frmRaces_submit' in request.POST:
		formset = getRaceFormSet(request.user, event, request.POST)
		if formset.is_valid():
			formset.save()
			log_document_formset(request.user, event, formset)
			touched_teams_all_races = set()
			for race in formset.new_objects:
				race.refresh_from_db()
				race.created_by = request.user
				race.save()
			for race, changed_data in formset.changed_objects:
			# 	if any(x in changed_data for x in ['distance', 'distance_real', 'itra_score']) \
			# 			and (race.get_klb_status() == models.KLB_STATUS_OK):
			# 		comments = []
			# 		if 'distance' in changed_data:
			# 			comments.append('официальной дистанции на {}'.format(race.distance))
			# 		if 'distance_real' in changed_data:
			# 			comments.append('фактической дистанции на {}'.format(race.distance_real))
			# 		if 'itra_score' in changed_data:
			# 			comments.append('баллов ITRA у дистанции {} на {}'.format(race.distance, race.itra_score))
			# 		comment = 'Пересчёт результатов при изменении ' + ', '.join(comments)
			# 		touched_persons = set()
			# 		touched_persons_by_team = {}
			# 		distance, was_real_distance_used = race.get_distance_and_flag_for_klb()
			# 		for klb_result in list(race.klb_result_set.exclude(result=None)):
			# 			# That's why we have to check all KLBresults before the year ends
			# 			person = klb_result.klb_person
			# 			old_score = klb_result.total_score()
			# 			result = klb_result.result
			# 			participant = klb_result.klb_participant
			# 			only_bonus_score = klb_result.only_bonus_score
			# 			team = klb_result.get_team()
			# 			klb_result.delete()
			# 			new_klb_result = views_klb.create_klb_result(result, person, user, distance, was_real_distance_used,
			# 				only_bonus_score=only_bonus_score, participant=participant,
			# 				comment='При изменении параметров дистанции на странице забега')
			# 			if new_klb_result:
			# 				new_score = new_klb_result.total_score()
			# 				touched_persons.add(person)
			# 				if team:
			# 					if team not in touched_persons_by_team:
			# 						touched_persons_by_team[team] = []
			# 					touched_persons_by_team[team].append((person, old_score, new_score))
			# 					touched_teams_all_races.add(team)
			# 		if touched_persons:
			# 			messages.success(request,
			# 				f'Для дистанции «{race}» были пересчитаны {len(touched_persons)} результатов в КЛБМатч.')
			# 			views_klb_stat.update_persons_score(year=event.start_date.year, persons_to_update=touched_persons,
			# 				update_runners=True)
			# 		views_klb.log_teams_score_changes(race, touched_persons_by_team, comment, user)
				
				if any(x in changed_data for x in ['distance', 'distance_real']):
					n_runners_touched = runner_stat.update_race_runners_stat(race)
					if n_runners_touched:
						messages.success(request, 'У {} бегунов пересчитана статистика'.format(n_runners_touched))
			if touched_teams_all_races:
				messages.success(request, 'Затронуты команды: {}'.format(', '.join(team.name for team in touched_teams_all_races)))
			views_stat.update_course_records(event.series)
			messages.success(request, ('Дистанции забега «{}» успешно обновлены: {} дистанций добавлено, {} обновлено, '
				+ '{} удалено. Проверьте, всё ли правильно.').format(
				event, len(formset.new_objects), len(formset.changed_objects), len(formset.deleted_objects)))
			return redirect(event.get_editor_url())
		else:
			messages.warning(request, "Дистанции забега «{}» не обновлены. Пожалуйста, исправьте ошибки в форме.".format(event))
	else:
		formset = None
	return event_details(request, event_id=event_id, event=event, frmRaces=formset)

@group_required('editors', 'admins')
def event_news_update(request, event_id):
	event = get_object_or_404(models.Event, pk=event_id)
	context, has_rights, target = check_rights(request, event=event)
	if not has_rights:
		return target
	if 'frmNews_submit' in request.POST:
		formset = getNewsFormSet(request.user, event, is_admin=context['is_admin'], data=request.POST, files=request.FILES)
		if formset.is_valid():
			formset.save()
			log_document_formset(request.user, event, formset)
			for news, field_list in formset.changed_objects:
				if 'image' in field_list:
					news.refresh_from_db()
					if news.image:
						if not news.make_thumbnail():
							messages.warning(request, "Не получилось уменьшить фото для новости с id {}.".format(news.id))
					else:
						news.delete_images()
					news.clean_image_align()
					news.save()
			for news in formset.new_objects:
				news.refresh_from_db()
				if news.image:
					if not news.make_thumbnail():
						messages.warning(request, "Не получилось уменьшить фото для новости с id {}.".format(news.id))
				news.created_by = request.user
				news.clean_image_align()
				news.save()
			messages.success(request, ('Новости забега «{}» успешно обновлены: {} новостей добавлено, {} обновлено, '
				+ '{} удалено. Проверьте, всё ли правильно.').format(
				event, len(formset.new_objects), len(formset.changed_objects), len(formset.deleted_objects)))
			return redirect(event.get_editor_url())
		else:
			messages.warning(request, "Новости забега «{}» не обновлены. Пожалуйста, исправьте ошибки в форме.".format(event))
	else:
		formset = None
	return event_details(request, event_id=event_id, event=event, frmNews=formset)

@group_required('editors', 'admins')
def event_documents_update(request, event_id):
	event = get_object_or_404(models.Event, pk=event_id)
	context, has_rights, target = check_rights(request, event=event)
	if not has_rights:
		return target
	if 'frmDocuments_submit' in request.POST:
		formset = getDocumentFormSet(request.user, event, data=request.POST, files=request.FILES)
		if formset.is_valid():
			process_document_formset(request, formset)
			instances = formset.save()
			log_document_formset(request.user, event, formset, exclude=['try_to_load'])

			to_update_last_added_reviews = False
			for document in instances:
				if document.document_type in (models.DOC_TYPE_PHOTOS, models.DOC_TYPE_IMPRESSIONS):
					to_update_last_added_reviews = True

			if to_update_last_added_reviews:
				generators.generate_last_added_reviews()

			messages.success(request, ('Документы пробега «{}» успешно обновлены: {} документов добавлено, {} обновлено, '
				+ '{} удалено. Проверьте, всё ли правильно.').format(
				event, len(formset.new_objects), len(formset.changed_objects), len(formset.deleted_objects)))
			return redirect(event.get_editor_url())
		else:
			messages.warning(request, "Документы пробега «{}» не обновлены. Пожалуйста, исправьте ошибки в форме.".format(event))
	else:
		formset = None
	return event_details(request, event_id=event_id, event=event, frmDocuments=formset)

def _refresh_default_calendar(request):
	generators.generate_default_calendars()
	messages.success(request, 'Календарь забегов на ближайший месяц обновлён')
	results_util.restart_django()

@group_required('admins')
def refresh_default_calendar(request):
	_refresh_default_calendar(request)
	return redirect('results:races')

@group_required('editors', 'admins')
def event_create(request, series_id=None, event_id=None):
	cloned_event = None
	initial = {}
	if series_id: # Create new event in selected series
		series = get_object_or_404(models.Series, pk=series_id)
		event = models.Event(series=series, name=series.name, url_site=series.url_site,
			url_vk=series.url_vk, url_facebook=series.url_facebook, contacts=series.contacts)
	else: # Clone event with id=event_id
		cloned_event = get_object_or_404(models.Event, pk=event_id)
		event = get_object_or_404(models.Event, pk=event_id)
		series = event.series
		event.id = None
		event.start_date = None
		event.finish_date = None
		event.date_added = None
		event.last_update = None
		event.not_for_klb = False
		event.cancelled = False

		event.url_announcement = ''
		event.url_poster = ''
		event.url_course = ''
		event.url_logo = ''
		event.url_regulation = ''
		event.url_regulation_stamped = ''
		event.url_protocol = ''
		event.comment = ''
		event.comment_private = ''
		event.source = ''
		event.url_registration = ''
		event.url_itra = ''
		event.platform = None
		event.id_on_platform = ''

		if (event.email == '') and (event.contacts == '') and (series.contacts != ''):
			event.contacts = series.contacts
			messages.warning(request, 'У клонируемого забега не указаны контакты организаторов, так что они скопированы у серии. Посмотрите, как распределить их между полями E-mail и «Другие контакты»')

		if event.city:
			initial['city'] = event.city
			initial['region'] = event.city.region.id

	context, has_rights, target = check_rights(request, event=event)
	if not has_rights:
		return target
	if 'frmEvent_submit' in request.POST:
		form = forms.EventForm(request.POST, instance=event, initial=initial, user=request.user)
		if form.is_valid():
			event = form.instance
			if not series.event_set.filter(start_date=event.start_date, start_time=event.start_time, city=event.city).exists():
				form.instance.created_by = request.user
				event = form.save()
				stat.update_events_count()
				log_form_change(request.user, form, action=models.ACTION_CREATE, exclude=['country', 'region'])
				messages.success(request, f'Пробег «{event.name}» успешно создан. Проверьте, всё ли правильно.')
				if cloned_event:
					races_added = 0
					for old_race in list(cloned_event.race_set.select_related('distance')):
						race = models.Race(
							event=event,
							distance=old_race.distance,
							distance_real=old_race.distance_real,
							surface_type=old_race.surface_type,
							elevation_meters=old_race.elevation_meters,
							descent_meters=old_race.descent_meters,
							precise_name=old_race.precise_name,
							created_by=request.user,
						)
						race.clean()
						race.save()
						models.log_obj_create(request.user, event, models.ACTION_RACE_CREATE, child_object=race,
							comment='При клонировании забега')
						races_added += 1
					messages.success(request, f'Добавлено {races_added} новых дистанций по образцу пробега {cloned_event}.')
				elif series.is_russian_parkrun() and series.event_set.count() == 1 and series.create_weekly:
					n_created = views_parkrun.create_future_events(series, models.USER_ROBOT_CONNECTOR)
					messages.success(request, f'Создано {n_created} новых стартов у паркрана.')

				today = datetime.date.today()
				if today <= event.start_date <= (today + datetime.timedelta(days=generators.DAYS_IN_DEFAULT_CALENDAR)):
					_refresh_default_calendar(request)
				return redirect(event.get_editor_url())
			else:
				messages.warning(request,
					'Пробег с такими датой, временем старта, городом уже есть. В одной серии не может быть двух пробегов '
					+ 'в одном городе со стартом в одно время')
		else:
			messages.warning(request, 'Пробег не создан. Пожалуйста, исправьте ошибки в форме.')
	else:
		form = forms.EventForm(instance=event, initial=initial, user=request.user)

	return event_details(request, event=event, frmEvent=form, cloned_event=cloned_event)

@group_required('editors', 'admins')
def event_change_series(request, event_id):
	event = get_object_or_404(models.Event, pk=event_id)
	context, has_rights, target = check_rights(request, event=event)
	if not has_rights:
		return target
	ok_to_move = False
	if 'frmForSeries_submit' in request.POST:
		form = forms.ForSeriesForm(request.POST, auto_id='frmForSeries_%s')
		if form.is_valid():
			new_series_id = results_util.int_safe(request.POST.get('new_series_id', 0))
			if new_series_id:
				if new_series_id != event.series.id:
					new_series = models.Series.objects.filter(pk=new_series_id).first()
					if new_series:
						if not new_series.event_set.filter(start_date=event.start_date, city=event.city).exists():
							ok_to_move = True
						else:
							messages.warning(request,
								f'В серии, в которую нужно переместить забег, уже есть забег с датой начала {event.start_date}.')
					else:
						messages.warning(request, 'Серия, в которую нужно переместить забег, не найдена.')
				else:
					messages.warning(request, 'Забег уже находится в этой серии.')
			else:
				messages.warning(request, 'Серия, на которую нужно заменить текущую, не указана.')
		else:
			messages.warning(request, "Серия не заменена. Пожалуйста, исправьте ошибки в форме.")
	else:
		form = None
		messages.warning(request, "Вы не указали новую серию.")
	if ok_to_move:
		old_series = event.series
		log = logging.getLogger('structure_modification')
		log_prefix = 'event_change_series: event {}, series {}->{}, by user {}.'.format(
			event_id, old_series.id, new_series.id, request.user.id)
		log.debug('{} before flock'.format(log_prefix))
		log_exc_info = False
		with Flock_mutex(LOCK_FILE_FOR_RATED_TREE_MODIFICATIONS):
			log.debug('{} trnsctn start'.format(log_prefix))
			try:
				with transaction.atomic():
					change_parent(event, new_series)  # to adapt the starrating data
					event.series = new_series
					event.save()
					for race in event.race_set.all():
						race.clean()
						race.save()
					log_change_event_series(request.user, event)
					views_stat.update_course_records(old_series)
					views_stat.update_course_records(event.series)
				log.debug('{} trnsctn end'.format(log_prefix))
			except (UpdatedRecordExistsError, AssertionError) as e:
				error_msg = repr(e)
				if isinstance(e, AssertionError):
					log_exc_info = True
			else:
				error_msg = None
		if error_msg is None:
			log.info('{} OK'.format(log_prefix))
			messages.success(request, f'Забег «{event}» успешно перемещён из серии «{old_series}» в серию «{event.series}».')
		else:
			log.error('{} {}'.format(log_prefix, error_msg), exc_info=log_exc_info)
			messages.warning(request, 'Не удалось переместить забег «{}» из серии «{}» в серию «{}»<br />({}).'.format(
				event, old_series, event.series, error_msg))

		return redirect(event.get_editor_url())

	return event_details(request, event_id=event_id, event=event, frmForSeries=form)

def has_same_distances(event_to_delete: models.Event, new_event: models.Event) -> Tuple[bool, str]:
	for race_to_move in event_to_delete.race_set.all():
		if new_event.race_set.filter(distance_id=race_to_move.distance_id, precise_name=race_to_move.precise_name).exists():
			return True, f'У забега с id {new_event.id} уже есть дистанция {race_to_move.distance} с уточнением названия «{race_to_move.precise_name}»'
	return False, ''

@group_required('editors', 'admins')
def event_delete(request, event_id):
	event = get_object_or_404(models.Event, pk=event_id)
	context, has_rights, target = check_rights(request, event=event)
	if not has_rights:
		return target
	has_dependent_objects = event.has_dependent_objects()
	ok_to_delete = False
	if 'frmForEvent_submit' in request.POST:
		form = forms.ForEventForm(request.POST, auto_id='frmForEvent_%s')
		if form.is_valid():
			if has_dependent_objects:
				new_event_id = results_util.int_safe(request.POST.get('new_event_id', 0))
				if new_event_id:
					if new_event_id != event.id:
						new_event = models.Event.objects.filter(pk=new_event_id).first()
						if new_event:
							has_bad_distance, message = has_same_distances(event, new_event)
							if not has_bad_distance:
								ok_to_delete = True
							else:
								messages.warning(request, message)
						else:
							messages.warning(request, 'Забег, на который нужно заменить текущий, не найден.')
					else:
						messages.warning(request, 'Нельзя заменить забег на себя же.')
				else:
					messages.warning(request, 'Забег, на который нужно заменить текущий, не указан.')
			else: # There are no races in the event, so we just delete it
				ok_to_delete = True
		else:
			messages.warning(request, "Забег не удалён. Пожалуйста, исправьте ошибки в форме.")
	else:
		form = None
		messages.warning(request, "Вы не указали забег для удаления.")
	if ok_to_delete:
		if not has_dependent_objects:
			new_event_id = 0
			new_event = None
		event_name = event.name
		series = event.series
		event_date = event.start_date

		log = logging.getLogger('structure_modification')
		log_prefix = 'event_delete: event {}->{}, by user {}.'.format(event_id, new_event_id, request.user.id)
		log.debug('{} before flock'.format(log_prefix))
		log_exc_info = False
		with Flock_mutex(LOCK_FILE_FOR_RATED_TREE_MODIFICATIONS):
			log.debug('{} trnsctn start'.format(log_prefix))
			try:
				with transaction.atomic():
					if has_dependent_objects:
						update_event(request, event, new_event)
					log.debug('{} 1'.format(log_prefix))
					transfer_children_before_node_deletion(event, new_event)
					log.debug('{} 2'.format(log_prefix))
					models.log_obj_delete(request.user, event)
					log.debug('{} 3'.format(log_prefix))
					start_date = event.start_date
					event.delete()
					log.debug('{} 4'.format(log_prefix))
					stat.update_events_count()
					log.debug('{} 5'.format(log_prefix))
					views_stat.update_course_records(series)
					if event.series.is_russian_parkrun():
						log.debug('{} 6'.format(log_prefix))
						prev_event = series.event_set.filter(start_date__lt=start_date).order_by('-start_date').first()
						if prev_event:
							_, n_fixed_parkruns = views_parkrun.fix_parkrun_numbers(correct_event=prev_event)
							messages.success(request, 'Исправлена нумерация у {} паркран{} после удалённого'.format(n_fixed_parkruns,
								results_util.ending(n_fixed_parkruns, 1)))
				log.debug('{} trnsctn end'.format(log_prefix))
			except (UpdatedRecordExistsError, AssertionError) as e:
				error_msg = repr(e)
				if isinstance(e, AssertionError):
					log_exc_info = True
			except Exception as e:
				log.error('{} Unexpected error: {}'.format(log_prefix, repr(e)), exc_info=True)
				raise
			else:
				error_msg = None
		if error_msg is None:
			log.info('{} OK'.format(log_prefix))
			today = datetime.date.today()
			if today <= event_date <= (today + datetime.timedelta(days=generators.DAYS_IN_DEFAULT_CALENDAR)):
				_refresh_default_calendar(request)
			messages.success(request, 'Забег «{}» из серии «{}» успешно удалён.'.format(event_name, series))
		else:
			log.error('{} {}'.format(log_prefix, error_msg), exc_info=log_exc_info)
			messages.warning(
				request, 'Не удалось удалить забег «{}» из серии «{}»<br />({}).'.format(
					event_name, series, error_msg
				)
			)
		return redirect(event.series)

	return event_details(request, event_id=event_id, event=event, frmForEvent=form)

@group_required('admins')
def remove_races_with_no_results(request, event_id):
	event = get_object_or_404(models.Event, pk=event_id)

	if not event.is_in_past():
		messages.warning(request, 'Этот забег ещё не прошёл. Ничего не удаляем')
		return redirect(event)

	if not models.Result.objects.filter(race__event=event).exists():
		messages.warning(request,
			'У этого забега вообще нет ни одного результат. Возможно, протокол ещё не загружен? Ничего не удаляем')
		return redirect(event)

	n_deleted = n_marked_for_reg_only = 0
	for race in list(event.race_set.all()):
		if (not race.result_set.exists()) and (not race.klb_result_set.exists()):
			if race.registrant_set.exists():
				if not race.kept_for_reg_history_only:
					race.kept_for_reg_history_only = True
					race.save()
					models.log_obj_create(request.user, event, models.ACTION_RACE_UPDATE, child_object=race, field_list='kept_for_reg_history_only',
						comment='При удалении дистанций без единого результата')
					n_marked_for_reg_only += 1
			else:
				models.log_obj_delete(request.user, event, race, models.ACTION_RACE_DELETE,
					comment='При удалении дистанций без единого результата')
				race.delete()
				n_deleted += 1

	if n_deleted:
		messages.success(request, f'Удалено дистанций без результатов у забега: {n_deleted}')
	if n_marked_for_reg_only:
		messages.success(request, f'Помечено дистанций как хранимые только ради истории регистрации через наш сайт: {n_marked_for_reg_only}')
	if n_deleted + n_marked_for_reg_only == 0:
		messages.warning(request, 'Дистанций без результатов не найдено. Ничего не удаляем')
	return redirect(event)
