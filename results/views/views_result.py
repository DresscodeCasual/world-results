from django.conf import settings
from django.shortcuts import get_object_or_404, render, redirect
from django.contrib.auth.decorators import login_required
from django.urls import reverse
from django.http import HttpResponse
from django.contrib import messages

import datetime
import json
from typing import Any

from results import models, forms, models_klb, results_util
from .views_common import user_edit_vars, paginate_and_render, get_first_form_error
from editor import runner_stat
from editor.views.views_klb import create_klb_result
from . import views_race

def claim_results(request):
	results_claimed = 0
	results_errors = 0
	runner_id = results_util.int_safe(request.POST.get('select_runner', 0))
	runner = models.Runner.objects.filter(pk=runner_id).first()
	if runner is None:
		return 0, None
	for key, val in list(request.POST.items()):
		if key.startswith("claim_"):
			result_id = results_util.int_safe(key[len("claim_"):])
			result = models.Result.objects.filter(id=result_id, runner=None).first()
			if result:
				res, msgError = result.claim_for_runner(request.user, runner, comment='Со страницы всех результатов')
				if res:
					results_claimed += 1
					if result.place_gender == 1:
						result.race.fill_winners_info()
				else:
					results_errors += 1
					if msgError:
						messages.warning(request, msgError)
	if results_claimed:
		runner_stat.update_runner_and_user_stat(runner)
	return results_claimed, runner

@login_required
def claim_result(request, result_id):
	result = get_object_or_404(models.Result, pk=result_id)
	race = result.race
	event = race.event
	user = request.user
	will_be_counted_for_klb = False
	reason = ''
	if result.status == models.STATUS_FINISHED:
		is_klb_participant, can_be_counted_for_klb, _ = check_event_for_klb(user, event)
		if is_klb_participant and can_be_counted_for_klb:
			klb_status = result.race.get_klb_status()
			will_be_counted_for_klb = (klb_status == models.KLB_STATUS_OK)
			reason = models.KLB_STATUSES[klb_status][1]
	res, message = result.claim_for_runner(user, user.runner, comment=request.GET.get('comment', ''), is_for_klb=will_be_counted_for_klb)
	if res:
		result.unclaimed_result_set.filter(user=user).delete()
		messages.success(request, f'Результат {result} на забеге «{race}» успешно Вам засчитан.')
		if will_be_counted_for_klb:
			if models.is_admin(user):
				create_klb_result(result, user.runner.klb_person, user, comment='При добавлении себе результата со страницы забега')
				messages.success(request, 'Он засчитан Вам в КЛБМатч.')
			else:
				messages.success(request, 'Он будет засчитан Вам в КЛБМатч после одобрения модератором.')
		elif reason:
			messages.warning(request, f'Он не будет учтён в КЛБМатче. Причина: {reason}')
		runner_stat.update_runner_and_user_stat(result.runner)
		if result.place_gender == 1:
			race.fill_winners_info()
	else:
		messages.warning(request, f'Результат {result} на забеге «{race}» не засчитан Вам. Причина: {message}')
	return redirect(race)

def results(request, lname='', fname='', disconnected=False):
	context = user_edit_vars(request.user)
	context['list_title'] = "Все результаты на забегах"
	today = datetime.date.today()
	conditions = []
	form_params = {}
	initial = {}
	form = None
	use_default_params = True
	make_simple_search = False

	if 'frmSearch_claim' in request.POST:
		if context['is_admin']:
			results_claimed, runner = claim_results(request)
			if results_claimed:
				messages.success(request, 'К бегуну {} успешно привязано результатов: {}'.format(runner, results_claimed))
		else:
			messages.warning(request, 'Привязывать результаты к бегуну могут только администраторы')

	if lname:
		use_default_params = False
		make_simple_search = True
		form_params['lname'] = lname.strip()
		initial['lname'] = form_params['lname']
	if fname:
		use_default_params = False
		make_simple_search = True
		form_params['fname'] = fname.strip()
		initial['fname'] = form_params['fname']
	if disconnected:
		form_params['disconnected'] = True
		initial['disconnected'] = True
	if ('btnSearchSubmit' in request.POST) or ('frmSearch_claim' in request.POST) or ('page' in request.POST):
		form = forms.ResultForm(request.POST)
		if form.is_valid():
			use_default_params = False
			form_params = {key: val for (key, val) in form.cleaned_data.items() if val}
		else:
			form = None
	if not form_params:
		form = None
	if use_default_params:
		month_before = today - datetime.timedelta(days=8)
		form_params['date_from'] = month_before

	if not results_util.anyin(form_params, ['city', 'region', 'country', 'race_name', 'date_from', 'date_to', 'distance', 'distance_from', 'distance_to', ]):
		make_simple_search = True

	if make_simple_search:
		results = models.Result.objects
	else:
		races = models.Race.objects.filter(event__invisible=False, event__cancelled=False, event__start_date__lte=today)
		if 'city' in form_params:
			context['city'] = form_params['city']
			races = views_race.filterRacesByCity(races, conditions, form_params['city'])
		elif 'region' in form_params:
			races = views_race.filterRacesByRegion(races, conditions, form_params['region'])
		elif 'country' in form_params:
			races = views_race.filterRacesByCountry(races, conditions, form_params['country'])
		if 'race_name' in form_params:
			races = views_race.filterRacesByName(races, conditions, form_params['race_name'])
		if 'date_from' in form_params:
			races = views_race.filterRacesByDateFrom(races, conditions, form_params['date_from'])
		if 'date_to' in form_params:
			races = views_race.filterRacesByDateTo(races, conditions, form_params['date_to'])
		if 'distance' in form_params:
			races = views_race.filterRacesByDistance(races, conditions, form_params['distance'])
		if 'distance_from' in form_params:
			races = views_race.filterRacesByDistanceFrom(races, conditions, form_params['distance_from'])
		if 'distance_to' in form_params:
			races = views_race.filterRacesByDistanceTo(races, conditions, form_params['distance_to'])
		if ('result_from' in form_params) or ('result_to' in form_params):
			races = races.exclude(distance__distance_type__in=models.TYPES_MINUTES)

		results = models.Result.objects.filter(race__in=set(races.values_list('id', flat=True)))
	result_args = {}
	if 'lname' in form_params:
		result_args['lname__istartswith'] = form_params['lname']
		conditions.append("с фамилией спортсмена «{}*»".format(form_params['lname']))
	if 'fname' in form_params:
		result_args['fname__istartswith'] = form_params['fname']
		conditions.append("с именем спортсмена «{}*»".format(form_params['fname']))
	if 'midname' in form_params:
		result_args['midname__istartswith'] = form_params['midname']
		conditions.append("с отчеством спортсмена «{}*»".format(form_params['midname']))
	if 'club' in form_params:
		result_args['club_name__istartswith'] = form_params['club']
		conditions.append("из клуба «{}*»".format(form_params['club']))
	if 'result_from' in form_params:
		result_args['result__gte'] = results_util.int_safe(form_params['result_from']) * 100
		conditions.append('с результатом не меньше {} секунд'.format(form_params['result_from']))
	if 'result_to' in form_params:
		result_args['result__lte'] = results_util.int_safe(form_params['result_to']) * 100
		result_args['status'] = models.STATUS_FINISHED
		conditions.append('с результатом не больше {} секунд'.format(form_params['result_to']))
	if 'disconnected' in form_params:
		result_args['runner'] = None
		conditions.append("не привязанные к людям")
	if result_args:
		results = results.filter(**result_args)
	results = results.select_related('race__event', 'city__region', 'race__distance', 'runner').order_by('-race__event__start_date',
			'race__event__name', 'race__distance__distance_type', '-race__distance__length', 'race__id', 'status', 'place')
	if form is None:
		form = forms.ResultForm(initial=initial)
	context['list_title'] = context['list_title'] + " " + ", ".join(conditions)
	context['form'] = form
	context['page_title'] = context['list_title']
	return paginate_and_render(request, 'results/results.html', context, results, add_results_with_splits=True)

@login_required
def unclaim_result(request, result_id, race_id=None):
	result = get_object_or_404(models.Result, pk=result_id)
	race = result.race
	if result.user != request.user:
		messages.warning(request, 'Результат {} на забеге «{}» — и так не Ваш.'.format(result, race.name_with_event()))
	result_str = str(result)
	was_deleted = result.unclaim_from_user()
	messages.success(request, 'Результат {} на забеге «{}» больше к Вам не относится.'.format(result_str, race.name_with_event()))
	runner_stat.update_runner_stat(user=request.user)
	return redirect(race)

@login_required
def unclaim_results(request):
	comment = request.POST.get('comment', "")
	results_unclaimed = 0
	results_errors = 0
	for key, val in list(request.POST.items()):
		if key.startswith("unclaim_"):
			result_id = results_util.int_safe(key[8:])
			result = request.user.result_set.filter(id=result_id).first()
			if result and (result.user == request.user):
				result.unclaim_from_user(comment=comment)
				results_unclaimed += 1
			else:
				results_errors += 1
	if results_unclaimed > 0:
		messages.success(request, 'Отсоединено результатов: {}.'.format(results_unclaimed))
		runner_stat.update_runner_stat(user=request.user)
	if results_errors > 0:
		messages.warning(request, 'Возникли ошибки c {} результатами. Редакторы уже знают о проблеме.'.format(results_errors))
	return redirect('results:home')

 # Returns <is this user a participant of current KLBMatch?>, <can result be counted for Match?>, <reason if can't>
def check_event_for_klb(user, event):
	event_date = event.start_date
	is_klb_participant = False
	if hasattr(user, 'runner') and user.runner.klb_person and models.is_active_klb_year(event_date.year):
		person = user.runner.klb_person
		participant = person.klb_participant_set.filter(year=models_klb.first_match_year(event_date.year)).first()
		if participant:
			is_klb_participant = ((participant.date_registered is None) or (participant.date_registered <= event_date)) \
				and ((participant.date_removed is None) or (participant.date_removed >= event_date))
	if not is_klb_participant:
		return False, False, ''
	if person.klb_result_set.filter(race__event=event).exists():
		return True, False, 'у Вас уже есть результат в КЛБМатч на этом забеге'
	klb_status = event.get_klb_status()
	if klb_status == models.KLB_STATUS_OK:
		return True, True, ''
	return True, False, models.KLB_STATUSES[klb_status][1]

@login_required
def get_add_result_page(request, event_id):
	event = get_object_or_404(models.Event, pk=event_id)
	user = request.user
	context = {}
	context['is_klb_participant'], context['will_be_counted_for_klb'], context['reason'] = check_event_for_klb(user, event)
	# context['is_klb_participant'], context['will_be_counted_for_klb'], context['reason'] = (1, 1, '') 
	context['event'] = event
	context['frmResult'] = forms.UnofficialResultForm(event=event)
	context['min_distance_for_klb'] = models_klb.get_min_distance_for_bonus(event.start_date.year)
	return render(request, "results/modal_add_result.html", context)

@login_required
def add_unofficial_result(request, event_id):
	event = get_object_or_404(models.Event, pk=event_id)
	context = {}
	message_text = ''
	res = {}
	res['success'] = 0
	user = request.user
	profile = user.user_profile if hasattr(user, 'user_profile') else None
	if (user.last_name.strip() == '') or (user.first_name.strip() == '') or (profile is None) or (profile.gender == models.GENDER_UNKNOWN):
		res['error'] = 'Для добавления результатов Вам нужно указать в профиле свои имя, фамилию и пол.'
	elif not profile.email_is_verified:
		res['error'] = 'Для добавления результатов Вам нужно подтвердить свой электронный адрес на странице «Личные данные», ' \
			+ 'чтобы мы могли связаться с Вами.'
	elif request.method == 'POST':
		if hasattr(user, 'runner'):
			runner = user.runner
		else:
			runner = None
		result = models.Result(
			runner=runner,
			user=user,
			loaded_by=user,
			source=models.RESULT_SOURCE_USER,
			gender=profile.gender,
		)
		form = forms.UnofficialResultForm(request.POST, instance=result, event=event)
		if form.is_valid():
			if models.Result.objects.filter(user=user, race=form.instance.race).exists():
				res['error'] = 'Вы уже вводили свой неофициальный результат на этой дистанции.'
			else:
				result = form.save()
				if runner is None:
					runner = models.Runner.objects.create(
						user=user,
						lname=user.last_name,
						fname=user.first_name,
						birthday=profile.birthday,
						birthday_known=(profile.birthday is not None),
						city=profile.city,
						gender=profile.gender,
					)
					result.runner = runner
					result.save()
				runner_stat.update_runner_and_user_stat(runner)
				will_be_counted_for_klb = False
				is_klb_participant, can_be_counted_for_klb, _ = check_event_for_klb(user, event)
				res['can_be_counted_for_klb'] = 1 if can_be_counted_for_klb else 0
				if is_klb_participant and can_be_counted_for_klb:
					klb_status = result.race.get_klb_status()
					will_be_counted_for_klb = (klb_status == models.KLB_STATUS_OK)
					res['will_be_counted_for_klb'] = 1 if will_be_counted_for_klb else 0
					res['reason'] = models.KLB_STATUSES[klb_status][1]
					res['url_my_results'] = reverse('results:home')
				models.log_obj_create(user, event, models.ACTION_UNOFF_RESULT_CREATE, child_object=result, is_for_klb=will_be_counted_for_klb)
				if result.race.load_status == models.RESULTS_NOT_LOADED:
					result.race.load_status = models.RESULTS_SOME_UNOFFICIAL
					result.race.save()

				strava_number = form.cleaned_data.get('strava_number')
				if strava_number:
					result_on_strava = models.Result_on_strava.objects.create(
						result=result,
						link=strava_number,
						tracker=form.cleaned_data['tracker'],
						added_by=user,
					)
					models.log_obj_create(user, result_on_strava, models.ACTION_CREATE, comment='При создании неофициального результата')
				res['success'] = 1
		else:
			res['error'] = get_first_form_error(form)
	else:
		res['error'] = 'Запрос не получен.'
	return HttpResponse(json.dumps(res), content_type='application/json')

@login_required
def delete_unofficial_result(request, result_id):
	result = get_object_or_404(models.Result, pk=result_id)
	result_user = result.user
	race = result.race
	user = request.user
	if hasattr(result, 'klb_result'):
		messages.warning(request, f'Вы не можете удалить результат, учтённый в КЛБМатче. Если это не Ваш результат, пожалуйста, напишите нам на {settings.EMAIL_INFO_USER}')
	elif (result_user != user) and (not models.is_admin(user)) and (result.runner not in user.user_profile.get_runners_to_add_results()):
		messages.warning(request, 'Вы не можете удалить чужой результат.')
	elif result.source == models.RESULT_SOURCE_DEFAULT:
		messages.warning(request, 'Вы не можете удалить этот результат – он взят из протокола соревнований.')
	else:
		runner = result.runner
		models.log_obj_create(user, race.event, models.ACTION_RESULT_DELETE, child_object=result)
		result.delete()
		runner_stat.update_runner_and_user_stat(runner)
			
		if result_user == user:
			messages.success(request, 'Ваш неофициальный результат на забеге {} успешно удалён.'.format(race.name_with_event()))
		else:
			runner_name = ''
			if result_user:
				runner_name = result_user.get_full_name()
			elif runner:
				runner_name = runner.name()				
			messages.success(request, 'Неофициальный результат бегуна {} на забеге {} успешно удалён.'.format(runner_name, race.name_with_event()))
	return redirect(race)

def result_details(request, result_id=None):
	result = get_object_or_404(models.Result, pk=result_id)
	race = result.race
	event = race.event
	user = request.user
	context: dict[str, Any] = user_edit_vars(user, series=event.series)
	context['page_title'] = '{}: {} на забеге {}, {}'.format(result.strName(), result, event.name, event.dateFull())
	context['result'] = result
	context['race'] = race
	context['event'] = event
	context['series'] = event.series
	context['splits'] = result.split_set.select_related('distance').order_by('distance__length')
	context['splits_exist'] = context['splits'].exists()
	context['races'] = views_race.event_races_for_context(event)

	if result.runner and result.runner.user:
		documents = models.Document.objects.filter(event=event, created_by=result.runner.user)
		context['reviews'] = documents.filter(document_type=models.DOC_TYPE_IMPRESSIONS).order_by('date_posted')
		context['photos'] = documents.filter(document_type=models.DOC_TYPE_PHOTOS).order_by('date_posted')
	return render(request, 'results/result_details.html', context)
