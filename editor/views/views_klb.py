from django.shortcuts import render, redirect
from django.db.models import Count, Q
from django.db.models.query import Prefetch
from django.contrib.auth.models import User
from django.contrib import messages
from django.db import connection

from collections import Counter
import datetime
import decimal
import math
from typing import Dict, List, Optional, Tuple

from results import models, models_klb, results_util
from editor import runner_stat
from . import views_common
from .views_klb_stat import length2bonus, roundup_centiseconds, distance2meters
from .views_klb_stat import get_klb_score_for_result, update_participants_score, update_match

def meters2distance_raw(length):
	if length == 42195:
		return 'марафон'
	if length == 21098:
		return 'полумарафон'
	if length == 10000:
		return '10 км'
	if length == 15000:
		return '15 км'
	if length == 20000:
		return '20 км'
	if length == 30000:
		return '30 км'
	if length == 100000:
		return '100 км'
	kilometers = length // 1000
	meters = length % 1000
	return f'{kilometers}.{str(meters).zfill(3)}'

# Call this only if all tests are passed, including: person is participant at the day of race and result.runner is in (person.runner, None)
def create_klb_result(result, person, user, distance=None, was_real_distance_used=None, only_bonus_score=False, comment='', participant=None) -> Optional[models.Klb_result]:
	result_updated_fields = []
	runner = person.runner
	if result.runner != runner:
		result_updated_fields.append('runner')
	result.runner = runner
	if runner.user:
		old_user = result.user
		if old_user != runner.user:
			result_updated_fields.append('user')
		result.user = runner.user
		result.add_for_mail(old_user=old_user)
	if result_updated_fields:
		result.save()
		models.log_obj_create(user, result.race.event, models.ACTION_RESULT_UPDATE, child_object=result, field_list=result_updated_fields, comment='При зачёте результата в КЛБМатч')

	if distance is None:
		distance, was_real_distance_used = result.race.get_distance_and_flag_for_klb()
	meters = result.result if (distance.distance_type == models.TYPE_MINUTES_RUN) else distance.length
	year = result.race.event.start_date.year
	if participant is None:
		participant = person.get_participant(year)

	existing_results = models.Klb_result.objects.filter(klb_person=person, race=result.race)
	if existing_results:
		models.send_panic_email(
			'Problem in create_klb_result',
			'Problem occured when trying to create a KLB result for person {} (id {}), race {}, comment "{}": such KLB result already exists.'.format(
				person.runner.name(), person.id, result.race.id, comment),
			to_all=True
		)
		return None

	klb_result = models.Klb_result(
		klb_person=person,
		klb_participant=participant,
		result=result,
		race=result.race,
		distance_raw=meters2distance_raw(meters),
		time_seconds_raw=(distance.length * 60) if (distance.distance_type == models.TYPE_MINUTES_RUN) else roundup_centiseconds(result.result),
		was_real_distance_used=was_real_distance_used,
		only_bonus_score=only_bonus_score,
		added_by=user,
	)
	klb_result.klb_score = 0 if only_bonus_score else get_klb_score_for_result(klb_result)
	if klb_result.klb_score > models_klb.MAX_CLEAN_SCORE:
		klb_result.klb_score = 0
	klb_result.bonus_score = length2bonus(meters, year)
	klb_result.clean()
	klb_result.save()
	models.log_obj_create(user, result.race.event, models.ACTION_KLB_RESULT_CREATE, child_object=klb_result, comment=comment)
	klb_result.refresh_from_db()
	connection.cursor().execute("UPDATE KLBresults SET FinTime = %s WHERE IDres = %s",
		[models.secs2time(klb_result.time_seconds_raw, fill_hours=False), klb_result.id])
	return klb_result

def update_klb_result_time(klb_result, user): # When race type is TYPE_METERS and only time was changed
	result = klb_result.result
	klb_result.time_seconds_raw = roundup_centiseconds(result.result)
	klb_result.klb_score = get_klb_score_for_result(klb_result)
	klb_result.save()
	connection.cursor().execute("UPDATE KLBresults SET FinTime = %s WHERE IDres = %s",
		[models.secs2time(klb_result.time_seconds_raw, fill_hours=False), klb_result.id])
	models.log_obj_create(user, result.race.event, models.ACTION_KLB_RESULT_UPDATE, field_list=['time_seconds_raw', 'klb_score'], child_object=klb_result)

def update_klb_result_meters(klb_result, user, year=None): # When race type is TYPE_MINUTES_RUN and only distance was changed
	result = klb_result.result
	if year is None:
		year = result.race.event.start_date.year
	klb_result.distance_raw = meters2distance_raw(result.result)
	klb_result.klb_score = get_klb_score_for_result(klb_result)
	klb_result.bonus_score = length2bonus(result.result, year)
	klb_result.save()
	models.log_obj_create(user, result.race.event, models.ACTION_KLB_RESULT_UPDATE, field_list=['distance_raw', 'klb_score'], child_object=klb_result)

def recalc_klb_result(klb_result, user, comment): # E.g. when age or gender of runner has changed. Returns True if result was changed
	result = klb_result.result
	score_old = klb_result.klb_score
	score_new = get_klb_score_for_result(klb_result) if (klb_result.klb_score > 0) else 0
	if abs(score_new - score_old) > 0.0005:
		klb_result.klb_score = get_klb_score_for_result(klb_result) if (klb_result.klb_score > 0) else 0
		klb_result.save()
		models.log_obj_create(user, result.race.event, models.ACTION_KLB_RESULT_UPDATE, field_list=['klb_score'],
			child_object=klb_result, comment=comment)
		return True
	return False

def attach_klb_results(request, year, debug=False):
	"""We look at all klb_results with result=None and try to find official or unofficial result for them"""
	results_absent = {}
	n_results_found_with_runner = 0
	n_results_found_wo_runner = 0
	race_w_unlinked_klb_results_ids = set(models.Klb_result.objects.filter(
		result=None,
		race__event__start_date__year__gte=year,
		is_error=False,
	).values_list('race', flat=True))
	if debug:
		print(race_w_unlinked_klb_results_ids)
	races = models.Race.objects.filter(id__in=race_w_unlinked_klb_results_ids).select_related('distance').order_by('id')
	for race in races:
		race_year = race.event.start_date.year
		race_results = race.result_set
		is_active_klb_year = models.is_active_klb_year(race_year)
		klb_results = race.klb_result_set.filter(result=None, is_error=False).select_related('klb_person__runner')
		for klb_result in klb_results:
			result_found = False
			person = klb_result.klb_person
			appropriate_race_results = race_results.filter(status=models.STATUS_FINISHED)
			if race.distance.distance_type != models.TYPE_MINUTES_RUN:
				appropriate_race_results = appropriate_race_results.filter(
					result__range=(klb_result.time_seconds_raw * 100 - 99, klb_result.time_seconds_raw * 100))

			result = appropriate_race_results.filter(runner=person.runner).first()
			if not result:
				result = appropriate_race_results.filter(Q(lname=person.lname, fname=person.fname) | Q(lname=person.fname, fname=person.lname)).first()

			if result:
				results_are_equal = False
				if race.distance.distance_type == models.TYPE_MINUTES_RUN:
					parsed, meters = distance2meters(klb_result.distance_raw)
					if parsed and (result.result == meters):
						results_are_equal = True
				else: # Distance type is meters
					seconds = int(math.ceil(result.result / 100))
					if seconds == klb_result.time_seconds_raw:
						results_are_equal = True
					# elif (abs(seconds - klb_result.time_seconds_raw) < 60) and not is_active_klb_year:
					# 	# If year is not KLB-active, we connect more results
					# 	results_are_equal = True
				if results_are_equal:
					if hasattr(result, 'klb_result'):
						messages.warning(request, f'Пытаемся привязать КЛБ-результат {klb_result.id} к результату {result.id}, но у того уже есть КЛБ-результат. Ничего не делаем')
					elif result.runner and (result.runner != person.runner):
						messages.warning(request, f'Пытаемся привязать КЛБ-результат {klb_result.id} к результату {result.id}, но у них разные бегуны: {result.runner.id}, {person.runner.id}. Ничего не делаем')
					else:
						# if klb_result.result: # Now this result with source=RESULT_SOURCE_KLB isn't needed
						# 	klb_result.result.delete()
						klb_result.result = result
						klb_result.save()
						if result.runner is None:
							runner = person.runner
							result.runner = runner
							result.user = runner.user
							result.save()
							n_results_found_wo_runner += 1
						else:
							n_results_found_with_runner += 1
						result_found = True
			if not result_found:
				if race.id in results_absent:
					results_absent[race.id].add((klb_result, result, is_active_klb_year))
				else:
					results_absent[race.id] = set([(klb_result, result, is_active_klb_year)])
	return results_absent, n_results_found_wo_runner, n_results_found_with_runner

def restore_strava_link_if_needed(user, result, lost_result):
	if lost_result.strava_link and not hasattr(result, 'result_on_strava'):
		result_on_strava = models.Result_on_strava.objects.create(
			result=result,
			link=lost_result.strava_link,
			added_by=user,
		)
		models.log_obj_create(user, result_on_strava, models.ACTION_CREATE, comment='При восстановлении потерянного результата')

def attach_lost_results(year, user, request=None):
	# We try to connect each lost result to new result from the same race
	n_deleted_lost_results = 0
	lost_results = []
	touched_runners = set()
	for lost_result in list(models.Lost_result.objects.filter(
			race__event__start_date__year__gte=year).select_related('race').order_by('race_id')):
		race = lost_result.race
		# TODO check: is there any command in POST?
		result_from = lost_result.result - 100
		result_to = lost_result.result + 100
		result_to_connect = race.result_set.filter(
			Q(lname__iexact=lost_result.lname, fname__iexact=lost_result.fname)
			| Q(lname__iexact=lost_result.fname, fname__iexact=lost_result.lname),
			Q(result__range=(result_from, result_to)) | Q(result=lost_result.result // 60),
			status=lost_result.status).first()
		if (result_to_connect is None) and request:
			select_name = 'result_for_lost_{}'.format(lost_result.id)
			if select_name in request.POST:
				result_to_connect = models.Result.objects.filter(pk=request.POST[select_name]).first()
		if (result_to_connect is None) and request:
			if 'delete_lost_result_{}'.format(lost_result.id) in request.POST:
				lost_result.delete()
				n_deleted_lost_results += 1
				continue
		if result_to_connect:
			result_is_restored = False
			if (result_to_connect.runner == lost_result.runner) and (result_to_connect.user == lost_result.user):
				result_is_restored = True
			elif (result_to_connect.runner is None) and (result_to_connect.user is None):
				result_to_connect.runner = lost_result.runner
				result_to_connect.user = lost_result.user
				result_to_connect.save()
				models.log_obj_create(user, race.event, models.ACTION_RESULT_UPDATE,
					field_list=['user', 'runner'], child_object=result_to_connect, comment='При восстановлении привязки')
				result_is_restored = True
			
			if result_is_restored:
				restore_strava_link_if_needed(user, result_to_connect, lost_result)
				lost_result.delete()
				n_deleted_lost_results += 1
				if result_to_connect.runner:
					touched_runners.add(result_to_connect.runner)
			else:
				if request:
					messages.warning(request, 'Возникла проблема с привязками у результата с id {}'.format(result_to_connect.id))
				lost_results.append(lost_result)
		else:
			lost_results.append(lost_result)
	if touched_runners:
		runner_stat.update_runners_and_users_stat(touched_runners)
		messages.success(request, 'При привязке старых результатов затронуто бегунов: {}. Их статистика пересчитана.'.format(len(touched_runners)))
	return lost_results, n_deleted_lost_results

@views_common.group_required('admins')
def klb_status(request, year=0):
	year = results_util.int_safe(year)
	context = {}
	context['oldest_year'] = 1950
	if (year > models_klb.CUR_KLB_YEAR) or (year < context['oldest_year']):
		year = models_klb.CUR_KLB_YEAR - 1
	context['year'] = year
	context['last_active_year'] = models_klb.match_year_range(max(models_klb.CUR_KLB_YEAR, models_klb.NEXT_KLB_YEAR))[1]
	context['page_title'] = 'Статус КЛБМатча'

	if (request.user.id == 1):
		step_start = datetime.datetime.now()
	# Part 2. We look at all klb_results with result=None and try to find official or unofficial result for them
	# models.write_log(u'{} KLB Status: Step 2'.format(datetime.datetime.now()))
	klb_results_absent, n_results_found_wo_runner, n_results_found_with_runner = attach_klb_results(request, year)
	if n_results_found_wo_runner or n_results_found_with_runner:
		messages.success(request, 'Только что мы привязали к БД результатов {} результатов, у которых не было бегуна, и {} — у которых был'.format(
			n_results_found_wo_runner, n_results_found_with_runner))
	context['klb_results_absent'] = [(models.Race.objects.get(pk=race_id), results) for race_id, results in list(klb_results_absent.items())]
	if (request.user.id == 1):
		step_end = datetime.datetime.now()
		results_util.write_log(f'klb_status: step 2 took {step_end - step_start}')
		step_start = step_end

	# Part 4. For each result entered by user or created from KLB-result but whose race results are already loaded
	# we look for results with same lname&fname.
	# If admin has just asked to replace such result with similar one, we replace it and delete unofficial result
	if year > 2015:
		context['unoff_results_in_loaded_races'] = []
		results_connected = 0
		results_deleted = 0
		n_updates_made_official = 0
		touched_runners = set()
		if (request.user.id == 1):
			results_util.write_log(f'starting step 4')
		for unoff_result in models.Result.objects.filter(race__event__start_date__year__gte=year,
				race__loaded__in=models.RESULTS_SOME_OR_ALL_OFFICIAL).exclude(
				source=models.RESULT_SOURCE_DEFAULT).select_related('race__event').order_by('race__event__start_date')[:20]:
			if (request.user.id == 1):
				step_end = datetime.datetime.now()
				results_util.write_log(f'result {unoff_result} is being processed')
			race = unoff_result.race
			was_deleted = False
			if unoff_result.runner:
				runner = unoff_result.runner
				similar_results = race.get_official_results().filter(
					Q(lname=runner.lname, fname=runner.fname) | Q(lname=runner.fname, fname=runner.lname))
				if similar_results.count() == 1:
					result = similar_results[0]
					# if (result.result == unoff_result.result) and (result.status == unoff_result.status):
					if (abs(result.result - unoff_result.result) < 200) and (result.status == unoff_result.status):
						results_connected, results_deleted, n_updates_made_official, was_deleted = try_replace_unoff_result_by_official(
							request, unoff_result, result, touched_runners, results_connected, results_deleted, n_updates_made_official,
							is_made_automatically=True)
			else:
				similar_results = []
			if not was_deleted:
				context['unoff_results_in_loaded_races'].append({'result': unoff_result, 'similar_results': similar_results})
		if (request.user.id == 1):
			step_end = datetime.datetime.now()
			results_util.write_log(f'klb_status: step 4 part 1 took {step_end - step_start}')
		report_changes_with_unoff_results(request, touched_runners, results_connected, results_deleted, n_updates_made_official)
		if (request.user.id == 1):
			step_end = datetime.datetime.now()
			results_util.write_log(f'klb_status: step 4 took {step_end - step_start}')
			step_start = step_end

	# Part 5. We try to connect each lost result to new result from the same race
	# models.write_log(u'{} KLB Status: Step 6'.format(datetime.datetime.now()))
	context['lost_results'], n_deleted_lost_results = attach_lost_results(year, request.user, request)
	if n_deleted_lost_results:
		messages.success(request, 'Только что мы привязали ранее потерянных привязок к результатам: {}'.format(n_deleted_lost_results))
	if (request.user.id == 1):
		step_end = datetime.datetime.now()
		results_util.write_log(f'klb_status: step 5 took {step_end - step_start}')
		step_start = step_end

	# Part 6. Most recent races with loaded results that weren't processed for KLBMatch
	# models.write_log(u'{} KLB Status: Step 7'.format(datetime.datetime.now()))
	context['races_for_klb'] = []
	context['MAX_RACES_FOR_KLB'] = 15
	races_for_klb = models.Race.objects.filter(
			Q(distance__distance_type=models.TYPE_MINUTES_RUN)
			| Q(distance__distance_type=models.TYPE_METERS, distance__length__gte=models_klb.get_min_distance_for_score(models_klb.CUR_KLB_YEAR)), 
			event__start_date__year__gte=models_klb.CUR_KLB_YEAR, # Something strange can happen near end of year if min_distance_for_score changes
			was_checked_for_klb=False,
			loaded=models.RESULTS_LOADED
		).select_related('event__city__region__country', 'event__series__city__region__country', 'distance').order_by('event__start_date')
	for race in races_for_klb:
		if (race.get_klb_status() == models.KLB_STATUS_OK) and not race.klb_result_set.filter(result=None).exists():
			context['races_for_klb'].append(race)
			if len(context['races_for_klb']) >= context['MAX_RACES_FOR_KLB']:
				break
	if (request.user.id == 1):
		step_end = datetime.datetime.now()
		results_util.write_log(f'klb_status: step 6 took {step_end - step_start}')
		step_start = step_end

	today = datetime.date.today()
	WEEK_AGO = today - datetime.timedelta(days=7)
	
	# Part 7. Preliminary protocols
	prel_ids = set(models.Document.objects.filter(document_type=models.DOC_TYPE_PRELIMINARY_PROTOCOL).values_list('event_id', flat=True))
	context['events_with_preliminary_protocols'] = models.Event.objects.filter(pk__in=prel_ids).order_by('-start_date').select_related(
		'city__region__country', 'series__city__region__country').prefetch_related(
			Prefetch('document_set', queryset=models.Document.objects.filter(document_type__in=models.DOC_PROTOCOL_TYPES)))
	if (request.user.id == 1):
		step_end = datetime.datetime.now()
		results_util.write_log(f'klb_status: step 7 took {step_end - step_start}')
		step_start = step_end

	if year > context['oldest_year']:
		# Part 8. Most recent events with not processed protocols and with distances without results
		protocols = models.Document.objects.filter(
			document_type=models.DOC_TYPE_PROTOCOL,
			event__start_date__lte=WEEK_AGO,
		).exclude(url_source__startswith='https://5verst.ru')
		event_with_good_protocol_ids = set(protocols.filter(is_processed=False).values_list('event_id', flat=True))
		races_wo_results = models.Race.objects.filter(
			Q(event__city__region__country_id__in=('BY', 'RU')) | Q(event__series__city__region__country_id__in=('BY', 'RU')) | Q(event__series__country_id__in=('BY', 'RU')),
			event__start_date__lte=WEEK_AGO,
			has_no_results=False,
		).exclude(load_status=models.RESULTS_LOADED)
		event_with_not_loaded_races_ids = set(races_wo_results.values_list('event_id', flat=True))

		context['events_with_protocol'] = models.Event.objects.filter(id__in=event_with_good_protocol_ids & event_with_not_loaded_races_ids
			).prefetch_related(
				Prefetch('race_set', queryset=models.Race.objects.select_related('distance').order_by(
					'distance__distance_type', '-distance__length')),
				Prefetch('document_set', queryset=models.Document.objects.filter(document_type__in=models.DOC_PROTOCOL_TYPES))
			).order_by('-start_date')[:context['MAX_RACES_FOR_KLB']]
		if (request.user.id == 1):
			step_end = datetime.datetime.now()
			results_util.write_log(f'klb_status: step 8 took {step_end - step_start}')
			step_start = step_end

		# Part 9. Most recent events in RU/BY/UA with distances without results
		# if year == models_klb.CUR_KLB_YEAR:
		# models.write_log(u'{} KLB Status: Step 8'.format(datetime.datetime.now()))
		country_ids = ('BY', 'RU', 'UA')
		distance_types = (models.TYPE_METERS, models.TYPE_MINUTES_RUN)
		year_from = today.year
		if today.month <= 6:
			year_from -= 1

		context['races_wo_results'] = models.Race.objects.filter(
				Q(event__city__region__country_id__in=country_ids) | Q(event__series__city__region__country_id__in=country_ids),
				Q(distance__distance_type=models.TYPE_METERS, distance__length__gte=9500) | Q(distance__distance_type=models.TYPE_MINUTES_RUN),
				event__cancelled=False,
				event__invisible=False,
				has_no_results=False,
				event__start_date__range=(datetime.date(year_from, 1, 1), WEEK_AGO),
			).exclude(load_status=models.RESULTS_LOADED).order_by('-event__start_date', 'event_id', 'distance__distance_type', '-distance__length').select_related(
			'event__city__region__country', 'event__series__city__region__country')
		if (request.user.id == 1):
			step_end = datetime.datetime.now()
			results_util.write_log(f'klb_status: step 9 took {step_end - step_start}')
			step_start = step_end
	return render(request, 'editor/klb/status.html', context)

def step4():
	# Part 4. For each result entered by user or created from KLB-result but whose race results are already loaded
	# we look for results with same lname&fname.
	# If admin has just asked to replace such result with similar one, we replace it and delete unofficial result
	year = 1950
	request = None
	context = {}
	context['unoff_results_in_loaded_races'] = []
	results_connected = 0
	results_deleted = 0
	n_updates_made_official = 0
	touched_runners = set()
	results_util.write_log(f'starting step4')
	step_start = step_end = datetime.datetime.now()
	for unoff_result in models.Result.objects.filter(race__event__start_date__year__gte=year,
			race__loaded__in=models.RESULTS_SOME_OR_ALL_OFFICIAL).exclude(
			source=models.RESULT_SOURCE_DEFAULT).select_related('race__event').order_by('race__event__start_date')[:20]:
		print(f'result {unoff_result} is being processed')
		race = unoff_result.race
		was_deleted = False
		if unoff_result.runner:
			runner = unoff_result.runner
			similar_results = race.get_official_results().filter(
				Q(lname=runner.lname, fname=runner.fname) | Q(lname=runner.fname, fname=runner.lname))
			if similar_results.count() == 1:
				result = similar_results[0]
				# if (result.result == unoff_result.result) and (result.status == unoff_result.status):
				if (abs(result.result - unoff_result.result) < 200) and (result.status == unoff_result.status):
					results_connected, results_deleted, n_updates_made_official, was_deleted = try_replace_unoff_result_by_official(
						request, unoff_result, result, touched_runners, results_connected, results_deleted, n_updates_made_official,
						is_made_automatically=True)
		else:
			similar_results = []
		if not was_deleted:
			context['unoff_results_in_loaded_races'].append({'result': unoff_result, 'similar_results': similar_results})
	step_end = datetime.datetime.now()
	print(f'klb_status: step 4 part 1 took {step_end - step_start}')
	print(len(touched_runners), results_connected, results_deleted, n_updates_made_official)
	if touched_runners:
		runner_stat.update_runners_and_users_stat(touched_runners)
	step_end = datetime.datetime.now()
	print(f'klb_status: step 4 took {step_end - step_start}')

@views_common.group_required('admins')
def connect_klb_results(request):
	year = results_util.int_safe(request.POST.get('year', models_klb.CUR_KLB_YEAR))
	if request.method == 'POST':
		results_connected = 0
		results_deleted = 0
		touched_active_participants = set()
		touched_inactive_participants = set()
		teams_by_race_deleting = {}
		teams_by_race_connecting = {}
		for key, val in list(request.POST.items()):
			if key.startswith("to_connect_klb_"):
				klb_result_id = results_util.int_safe(key[len("to_connect_klb_"):])
				klb_result = models.Klb_result.objects.filter(pk=klb_result_id).select_related('race__event').first()
				if not klb_result:
					messages.warning(request, 'Результат в КЛБМатче с id {} не найден. Пропускаем'.format(klb_result_id))
					continue
				if klb_result.result:
					messages.warning(request, 'Результат в КЛБМатче с id {} уже привязан к результату с id {}. Пропускаем'.format(
						klb_result_id, klb_result.result.id))
					continue
				person = klb_result.klb_person
				race = klb_result.race
				event = race.event
				race_year = event.start_date.year
				participant = person.get_participant(race_year)
				team = participant.team
				if val == "delete":
					if models.is_active_klb_year(race_year):
						touched_active_participants.add(participant)
						models.log_obj_delete(request.user, event, child_object=klb_result, action_type=models.ACTION_KLB_RESULT_DELETE)
						if team:
							if race not in teams_by_race_deleting:
								teams_by_race_deleting[race] = Counter()
							teams_by_race_deleting[race][team] += 1
						klb_result.delete()
						results_deleted += 1
					else:
						messages.warning(request,
							'КЛБ-результат бегуна {} на забеге {} не может быть удалён — тот матч уже завершён'.format(person, event))
				elif val == "connect": # So we should connect klb_result with selected result
					result_id = results_util.int_safe(request.POST.get("result_for_klb_{}".format(klb_result_id), 0))
					result = models.Result.objects.filter(pk=result_id).first()
					if not result:
						messages.warning(request, 'Результат с id {} не найден. Пропускаем'.format(result_id))
						continue
					runner = person.runner
					result.runner = runner
					result.user = runner.user
					result.save()
					if models.is_active_klb_year(race_year):
						touched_active_participants.add(participant)
						if result.status == models.STATUS_FINISHED:
							if hasattr(result, 'klb_result'):
								messages.warning(request, f'Пытаемся привязать КЛБ-результат {klb_result.id} к результату {result.id}, но у того уже есть КЛБ-результат. Ничего не делаем с КЛБ-результатом')
							else:
								klb_result.result = result
								klb_result.save()
								if result.race.distance.distance_type == models.TYPE_MINUTES_RUN:
									update_klb_result_meters(klb_result, request.user, race_year)
								else:
									update_klb_result_time(klb_result, request.user)
								if team:
									if race not in teams_by_race_connecting:
										teams_by_race_connecting[race] = Counter()
									teams_by_race_connecting[race][team] += 1
								results_connected += 1
						else: # he didn't finish, so we delete this klb_result
							models.log_obj_delete(request.user, event, child_object=klb_result, action_type=models.ACTION_KLB_RESULT_DELETE)
							if team:
								if race not in teams_by_race_deleting:
									teams_by_race_deleting[race] = Counter()
								teams_by_race_deleting[race][team] += 1
							klb_result.delete()
							results_deleted += 1
					else:
						touched_inactive_participants.add(participant)
						if result.status == models.STATUS_FINISHED:
							klb_result.result = result
							klb_result.save()
		if results_connected:
			messages.success(request, 'Привязано результатов из КЛБМатча: {}'.format(results_connected))
		if results_deleted:
			messages.success(request, 'Удалено результатов из КЛБМатча: {}'.format(results_deleted))
		if touched_active_participants:
			update_participants_score(touched_active_participants)
			messages.success(request, f'Затронуто участников активных Матчей: {len(touched_active_participants)}. Их результаты пересчитаны.')
			for comment, teams_by_race in (('Удаление', teams_by_race_deleting), ('Пересчёт', teams_by_race_connecting)):
				for race, touched_teams in list(teams_by_race.items()):
					for team in touched_teams:
						prev_score = team.score
						team.refresh_from_db()
						models.Klb_team_score_change.objects.create(
							team=team,
							race=race,
							clean_sum=team.score - team.bonus_score,
							bonus_sum=team.bonus_score,
							delta=team.score - prev_score,
							n_persons_touched=touched_teams[team],
							comment='{} КЛБ-результатов при замене неофициальных результатов на официальные'.format(comment),
							added_by=request.user,
						)
		if touched_inactive_participants:
			messages.success(request, f'Затронуто участников старых Матчей: {len(touched_inactive_participants)}. Их результаты не трогаем.')
	return redirect('editor:klb_status', year=year)

def try_replace_unoff_result_by_official(request, unoff_result, result, touched_runners, results_connected, results_deleted, n_updates_made_official,
		is_made_automatically):
	res = 0
	user = models.USER_ROBOT_CONNECTOR if is_made_automatically else request.user
	verified_by = user if is_made_automatically else None
	if result.runner and (result.runner != unoff_result.runner):
		messages.warning(request, f'Официальный результат {result} ( id {result.id}) уже привязан к бегуну {result.runner}. Пропускаем')
		return 0, 0, 0, False
	field_list = []
	runner = unoff_result.runner
	if runner:
		if result.runner != runner:
			result.runner = runner
			field_list.append('runner')
			if runner.user:
				result.user = runner.user
				field_list.append('user')
	else:
		messages.warning(request,
			'Неофициальный результат с id {} не имеет бегуна. Мы пытались привязать его к официальному результату с id {}. Пропускаем'.format(
			unoff_result.id, result.id))
		return 0, 0, 0, False
	result.save()
	event = unoff_result.race.event
	comment = 'При замене неофициального результата {} (id {}) на официальный {}'.format(unoff_result, unoff_result.id, result)

	models.log_obj_create(user, event, models.ACTION_RESULT_UPDATE, field_list=field_list, child_object=result,
		comment=comment, verified_by=verified_by)
	touched_runners.add(runner)
	results_connected += 1

	# Was this result waiting for moderation for Match?
	table_update = models.Table_update.objects.filter(model_name=models.Event.__name__, row_id=event.id, child_id=unoff_result.id,
		action_type=models.ACTION_UNOFF_RESULT_CREATE, is_verified=False, is_for_klb=True).first()
	if table_update:
		table_update.child_id = result.id
		table_update.action_type = models.ACTION_RESULT_UPDATE
		table_update.save()
		table_update.append_comment('сделан из неофициального результата')
		n_updates_made_official += 1

	if hasattr(unoff_result, 'result_on_strava') and not hasattr(result, 'result_on_strava'):
		result_on_strava = unoff_result.result_on_strava
		result_on_strava.result = result
		result_on_strava.save()
		models.log_obj_create(user, result_on_strava, models.ACTION_UPDATE, field_list=['result'], comment=comment)

	models.log_obj_delete(user, event, child_object=unoff_result, action_type=models.ACTION_RESULT_DELETE, verified_by=verified_by,
		comment='При замене неофициального результата {} бегуна {} на официальный результат {} (id {})'.format(
			unoff_result, runner.get_name_and_id(), result, result.id))
	unoff_result.delete()
	results_deleted += 1
	return results_connected, results_deleted, n_updates_made_official, True

def report_changes_with_unoff_results(request, touched_runners, results_connected, results_deleted, n_updates_made_official):
	if results_connected:
		messages.success(request, 'Заменено неоф. результатов на официальные: {}'.format(results_connected))
	if results_deleted:
		messages.success(request, 'Удалено неоф. результатов: {}'.format(results_deleted))
	if touched_runners:
		runner_stat.update_runners_and_users_stat(touched_runners)
		messages.success(request, 'Затронуто бегунов: {}. Их статистика пересчитана.'.format(len(touched_runners)))
	if n_updates_made_official:
		messages.success(request,
			f'Заявок на добавление неофициальных результатов в КЛБМатч переделано в заявки с официальными результатами: {n_updates_made_official}')

@views_common.group_required('admins')
def connect_unoff_results(request):
	year = results_util.int_safe(request.POST.get('year', models_klb.CUR_KLB_YEAR))
	user = request.user
	if request.method == 'POST':
		results_connected = 0
		results_deleted = 0
		n_updates_made_official = 0
		touched_runners = set()
		for key, val in list(request.POST.items()):
			if key.startswith("to_connect_unoff_"):
				unoff_result_id = results_util.int_safe(key[len("to_connect_unoff_"):])
				unoff_result = models.Result.objects.filter(pk=unoff_result_id).select_related('race__event').first()
				if unoff_result is None:
					messages.warning(request, 'Неофициальный результат с id {} не найден. Пропускаем'.format(unoff_result_id))
					continue
				event = unoff_result.race.event
				# if val == "delete":
				# 	if unoff_result.runner:
				# 		touched_runners.add(unoff_result.runner)
				# 	models.log_obj_delete(user, event, child_object=unoff_result, action_type=models.ACTION_RESULT_DELETE,
				# 		comment=u'Со страницы статуса матча')
				# 	unoff_result.delete()
				# 	results_deleted += 1
				if val == "connect": # So we should connect unoff_result with selected result
					result_id = results_util.int_safe(request.POST.get(f'result_for_unoff_{unoff_result_id}', 0))
					result = models.Result.objects.filter(pk=result_id).first()
					if result is None:
						messages.warning(request, f'Официальный результат с id {result_id} не найден. Пропускаем')
						continue
					results_connected, results_deleted, n_updates_made_official, _ = try_replace_unoff_result_by_official(
						request, unoff_result, result, touched_runners,
						results_connected, results_deleted, n_updates_made_official, is_made_automatically=False)
		report_changes_with_unoff_results(request, touched_runners, results_connected, results_deleted, n_updates_made_official)
	return redirect('editor:klb_status', year=year)

@views_common.group_required('admins')
def klb_update_match(request, year):
	year = results_util.int_safe(year)
	if not models.is_active_klb_year(year):
		messages.warning(request, f'Результаты КЛБМатча–{models_klb.year_string(year)} сейчас не могут быть пересчитаны: матч неактивен')
	else:
		update_match(year)
		messages.success(request, f'Результаты КЛБМатча–{models_klb.year_string(year)} успешно обновлены')
	return redirect('results:klb_match_summary', year=year)

# Used just once. Can be used to check whether there are mistakes with results in current year
def fill_klb_result_participants(year):
	all_participants = models.Klb_participant.objects.filter(year=year)
	person_ids = set(all_participants.values_list('klb_person_id', flat=True))
	n_done = 0
	for klb_result in models.Klb_result.objects.filter(event_raw__start_date__year=year, klb_participant=None).select_related(
			'klb_person', 'event_raw'):
		if klb_result.klb_person_id not in person_ids:
			print('Klb_result {}, result {}, race {}, person {}: participant not found'.format(
				klb_result.id, klb_result.result_id, klb_result.race_id, klb_result.klb_person_id))
			continue
		person = klb_result.klb_person
		participant = all_participants.get(klb_person_id=klb_result.klb_person_id)
		event_date = klb_result.event_raw.start_date
		if year >= 2017:
			if participant.date_registered and (participant.date_registered > event_date):
				print('{} {} был включён в команду только {}. Его результат на забеге {} не годится'.format(
					person.fname, person.lname, participant.date_registered, klb_result.event_raw))
				continue
			elif participant.date_removed and (participant.date_removed < event_date):
				print('{} {} был исключён из команды уже {}. Его результат на забеге {} не годится'.format(
					person.fname, person.lname, participant.date_removed, klb_result.event_raw))
				continue
		klb_result.klb_participant = participant
		klb_result.save()
		n_done += 1
	print('Done! Year:', year, '. Participants filled:', n_done)

N_EMAILS_IN_GROUP = 90

@views_common.group_required('admins')
def klb_team_leaders_emails(request, year=models_klb.CUR_KLB_YEAR):
	emails = set()
	club_ids = set(models.Klb_team.objects.filter(year=year).values_list('club_id', flat=True))
	for club in models.Club.objects.filter(pk__in=club_ids):
		emails.add(club.head_email)
		emails.add(club.speaker_email)
	user_ids = set(models.Club_editor.objects.filter(club_id__in=club_ids).values_list('user_id', flat=True))
	for user in User.objects.filter(pk__in=user_ids):
		emails.add(user.email)

	context = {}
	correct_emails = []
	incorrect_emails = []
	for email in sorted(emails):
		email = email.strip()
		if email == '':
			continue
		if models.is_email_correct(email):
			correct_emails.append(email)
		else:
			incorrect_emails.append(email)

	n_hundreds = ((len(correct_emails) - 1) // N_EMAILS_IN_GROUP) + 1
	context['correct_emails'] = []
	for i in range(n_hundreds):
		context['correct_emails'].append(', '.join(correct_emails[i * N_EMAILS_IN_GROUP:(i + 1) * N_EMAILS_IN_GROUP]))
	context['incorrect_emails'] = ', '.join(incorrect_emails)
	context['individuals_emails'] = ', '.join(sorted(models.Klb_participant.objects.filter(year=year, team=None).values_list('email', flat=True)))
	context['page_title'] = 'Адреса всех имеющих права на клубы, участвующие в КЛБМатче–{}'.format(year)
	context['year'] = year
	return render(request, 'editor/klb/club_emails_by_year.html', context)

@views_common.group_required('admins')
def klb_who_did_not_pay(request, year=models_klb.CUR_KLB_YEAR):
	year = max(2019, int(year))
	context = {}
	context['year'] = year
	context['page_title'] = 'КЛБМатч-{}: кто не заплатил за участие'.format(year)

	members = models.Klb_participant.objects.filter(year=year)
	team_members_not_paid = members.filter(paid_status=models.PAID_STATUS_NO).exclude(team=None)
	team_ids = set(team_members_not_paid.values_list('team_id', flat=True))

	context['n_teams_with_members'] = models.Klb_team.objects.filter(year=year, n_members__gt=0).count()
	context['n_teams_paid'] = context['n_teams_with_members'] - len(team_ids)
	context['n_teams_not_paid'] = len(team_ids)
	context['n_team_members_not_paid'] = team_members_not_paid.count()

	Q_senior_or_disabled = Q(is_senior=True) | Q(klb_person__disability_group__gt=0)
	context['n_members'] = members.count()
	context['n_members_paid'] = members.filter(paid_status=models.PAID_STATUS_FULL).count()
	context['n_seniors_paid'] = members.filter(paid_status=models.PAID_STATUS_FULL).filter(Q_senior_or_disabled).count()
	context['n_members_paid_zero'] = members.filter(paid_status=models.PAID_STATUS_FREE).count()

	context['teams'] = []
	teams_not_paid_emails = set()
	for team in models.Klb_team.objects.filter(pk__in=team_ids).prefetch_related('club__editors').annotate(Count('klb_participant')).order_by('name'):
		data = {}
		data['team'] = team
		data['participants_not_paid'] = team.klb_participant_set.filter(paid_status=models.PAID_STATUS_NO).select_related(
			'klb_person', 'added_by__user_profile').order_by('date_registered', 'klb_person__lname', 'klb_person__fname')
		data['n_seniors_not_paid'] = data['participants_not_paid'].filter(Q_senior_or_disabled).count()
		data['team_admins'] = team.club.editors.all()
		for editor in team.club.editors.all():
			teams_not_paid_emails.add(editor.email)
		context['teams'].append(data)
	context['teams_not_paid_emails'] = ', '.join(sorted(teams_not_paid_emails))

	context['individuals_not_paid'] = members.filter(paid_status=models.PAID_STATUS_NO, team=None).select_related(
		'klb_person__runner__user__user_profile').order_by('klb_person__lname', 'klb_person__fname')
	individuals_not_paid_emails = set(context['individuals_not_paid'].values_list('email', flat=True))
	context['individuals_not_paid_emails'] = ', '.join(sorted(individuals_not_paid_emails))

	context['n_individuals_paid'] = members.filter(paid_status=models.PAID_STATUS_FULL, team=None).count()
	context['n_individuals_for_free'] = members.filter(paid_status=models.PAID_STATUS_FREE, team=None).count()
	return render(request, 'editor/klb/did_not_pay.html', context)

@views_common.group_required('admins')
def klb_repeating_contact_data(request, year=models_klb.CUR_KLB_YEAR):
	year = max(2019, int(year))
	context = {}
	context['year'] = year
	context['page_title'] = 'КЛБМатч-{}: повторяющиеся личные данные'.format(year)

	participants_by_email = {}
	participants_by_phone = {}
	for participant in models.Klb_participant.objects.filter(year=year).select_related('klb_person', 'team', 'added_by__user_profile').order_by(
			'added_time'):
		if participant.email:
			if participant.email not in participants_by_email:
				participants_by_email[participant.email] = []
			participants_by_email[participant.email].append(participant)
		if participant.phone_number_clean:
			if participant.phone_number_clean not in participants_by_phone:
				participants_by_phone[participant.phone_number_clean] = []
			participants_by_phone[participant.phone_number_clean].append(participant)

	context['same_emails'] = sorted((k, v) for k, v in list(participants_by_email.items()) if (len(v) > 1))
	context['same_phones'] = sorted((k, v) for k, v in list(participants_by_phone.items()) if (len(v) > 1))

	return render(request, 'editor/klb/repeating_contact_data.html', context)

def log_teams_score_changes(race: models.Race,
							touched_persons_by_team: Dict[models.Klb_team, List[Tuple[models.Klb_person, decimal.Decimal, decimal.Decimal]]],
							comment: str,
							user: User,
		):
	for team, persons in touched_persons_by_team.items():
		prev_score = team.score
		team.refresh_from_db()
		score_change = models.Klb_team_score_change.objects.create(
			team=team,
			race=race,
			clean_sum=team.score - team.bonus_score,
			bonus_sum=team.bonus_score,
			delta=team.score - prev_score,
			n_persons_touched=len(persons),
			comment=comment,
			added_by=user,
		)
		for person, old_score, new_score in persons:
			models.Klb_team_score_change_person.objects.create(
				score_change=score_change,
				old_score=old_score,
				new_score=new_score,
				klb_person=person,
			)
