from django.db.models import Q, F, ExpressionWrapper, IntegerField
from django.shortcuts import get_object_or_404, render, redirect
from django.db.models.functions import ExtractYear
from django.forms import modelformset_factory
from django.contrib import messages
from collections import OrderedDict
from django.http import Http404
from django.urls import reverse
import datetime

from results import models, results_util
from results.views import views_age_group_record
from editor import stat
from editor.forms import RecordResultForm
from editor.views.views_common import group_required
from editor.views.views_user_actions import log_form_change

from typing import Dict, List, Optional, Set, Tuple

N_EXTRA_RECORDS = 3
EARLIEST_RECORD_DATE = datetime.date(1991, 1, 1)

EVENT_IDS_NOT_FOR_RECORDS = {
	# ЧР-2013 среди ветеранов. Хронометраж ручной, потом ко временам добавили 0.24 секунды. shvsm_rm1@mail.ru
	34251: 'Хронометраж был ручной, но перед занесением в протокол ко всем результатам добавили 0.24 секунды',
}

def getRecordResultFormSet(request, user, country=None, gender=None, age_group=None, distance=None, surface_type=None,
		add_remaining_cur_leaders=False, data=None):
	queryset = models.Record_result.objects.all()
	initial = {}
	initial['created_by'] = user
	# initial['is_from_shatilo'] = True
	initial['was_record_ever'] = True
	initial['cur_place'] = 1
	if country:
		queryset = queryset.filter(country=country)
		initial['country'] = country
	if gender:
		queryset = queryset.filter(gender=gender)
		initial['gender'] = gender
	if age_group:
		queryset = queryset.filter(age_group=age_group)
		initial['age_group'] = age_group
	if distance:
		queryset = queryset.filter(distance=distance)
		initial['distance'] = distance
	if surface_type is not None:
		queryset = queryset.filter(surface_type=surface_type)
		initial['surface_type'] = surface_type
	if add_remaining_cur_leaders:
		if age_group: # So the forms must be different only by distance
			existing_distances = set(queryset.values_list('distance_id', flat=True))
			remaining_distances = list(models.Distance.objects.filter(
				pk__in=set([x[0] for x in results_util.DISTANCES_FOR_COUNTRY_OUTDOOR_RECORDS]) - existing_distances).order_by(
				'distance_type', '-length'))
			initials = [dict(initial) for _ in range(len(remaining_distances))]
			for i, distance in enumerate(remaining_distances):
				initials[i]['distance'] = distance
		else: # So the forms must be different only by age group
			existing_age_groups = set(queryset.values_list('age_group__id', flat=True))
			remaining_age_groups = list(models.Record_age_group.objects.exclude(pk__in=existing_age_groups))
			initials = [dict(initial) for _ in range(len(remaining_age_groups))]
			for i, age_group in enumerate(remaining_age_groups):
				initials[i]['age_group'] = age_group
	else:
		initials = [initial] * N_EXTRA_RECORDS
	RaceFormSet = modelformset_factory(models.Record_result, form=RecordResultForm, can_delete=True, extra=len(initials))
	return RaceFormSet(
		data=data,
		queryset=queryset,
		initial=initials,
		form_kwargs={'distance_type': models.TYPE_MINUTES_RUN if (distance and (distance.distance_type == models.TYPE_MINUTES_RUN))
			else models.TYPE_METERS},
	)

@group_required('age_records_editors')
def age_group_records_edit(request, country_id=None, gender_code=None, distance_code=None, surface_code=None, age=None):
	context = {}
	user = request.user

	country = get_object_or_404(models.Country, pk=(country_id if country_id else 'RU'))
	surface_type = results_util.SURFACE_CODES_INV.get(surface_code)
	gender = results_util.GENDER_CODES_INV.get(gender_code) if gender_code else results_util.GENDER_MALE
	if not gender:
		raise Http404()

	formset_params = {}
	formset_params['country'] = country
	formset_params['surface_type'] = surface_type
	formset_params['gender'] = gender

	distance = None
	if distance_code:
		distance_id = results_util.DISTANCE_CODES_INV.get(distance_code)
		if surface_type == results_util.SURFACE_INDOOR:
			if distance_id not in results_util.DISTANCES_FOR_COUNTRY_INDOOR_RECORDS:
				raise Http404(f'Мы не считаем рекорды для дистанции {distance} и типа покрытия {results_util.SURFACE_TYPES[surface_type][1]}')
		else:
			if (distance_id, surface_type) not in results_util.DISTANCES_FOR_COUNTRY_OUTDOOR_RECORDS:
				raise Http404(f'Мы не считаем рекорды для дистанции {distance} и типа покрытия {results_util.SURFACE_TYPES[surface_type][1]}')
		distance = get_object_or_404(models.Distance, pk=distance_id)
		formset_params['distance'] = distance
	if age is not None:
		age = results_util.int_safe(age)
		age_group = get_object_or_404(models.Record_age_group, age_min=age if age else None)
		formset_params['age_group'] = age_group
	formset_params['add_remaining_cur_leaders'] = (distance is not None) or (age is not None)

	if 'btnSubmitRecords' in request.POST:
		formset = getRecordResultFormSet(request, user, data=request.POST, **formset_params)
		if formset.is_valid():
			formset.save()
			for record in formset.new_objects:
				record.fill_and_save_if_needed()
			for record, changed_data in formset.changed_objects:
				record.fill_and_save_if_needed()

			messages.success(request, ('{} рекордов добавлено, {} обновлено, {} удалено').format(
				len(formset.new_objects), len(formset.changed_objects), len(formset.deleted_objects)))
			return redirect('results:age_group_records')
		else:
			messages.warning(request, 'Рекорды не сохранены. Пожалуйста, исправьте ошибки в форме')
			context['errors'] = str(formset.errors) # TODO: REMOVE
	else:
		formset = getRecordResultFormSet(request, user, **formset_params)

	if age == 0:
		context['page_title'] = 'Редактирование абсолютных рекордов {} на покрытии {} у {}'.format(
			formset_params['country'].prep_case,
			results_util.SURFACE_TYPES[surface_type][1],
			'мужчин' if (gender == results_util.GENDER_MALE) else 'женщин')
	else:
		context['page_title'] = 'Редактирование рекордов в возрастных группах'
	context['formset'] = formset
	return render(request, 'editor/age_groups/age_group_records_edit.html', context)

@group_required('age_records_editors')
def age_group_record_details(request, record_result_id=None, country_id=None, gender_code=None, age=None, distance_code=None, surface_code=None):
	context = {}

	if record_result_id:
		record = get_object_or_404(models.Record_result, pk=record_result_id)
		if record.result_id:
			messages.warning(request, 'Рекорд {} привязан к результату с id {}. Такие редактировать незачем'.format(record, record.result_id))
			return redirect(record.get_group_url())
		create_new = False
	else:
		country = get_object_or_404(models.Country, pk=(country_id if country_id else 'RU'))
		gender = results_util.GENDER_CODES_INV.get(gender_code) if gender_code else results_util.GENDER_MALE
		distance_id = surface_type = None
		if surface_code:
			distance_id = results_util.DISTANCE_CODES_INV.get(distance_code)
			surface_type = results_util.SURFACE_CODES_INV.get(surface_code)
		age_min = None if (age == 0) else age
		age_group = get_object_or_404(models.Record_age_group, age_min=age_min)
		record = models.Record_result(
			created_by=request.user,
			country=country,
			gender=gender,
			age_group=age_group,
			distance_id=distance_id,
			surface_type=surface_type,
			is_from_hinchuk=True,
		)
		create_new = True

	frmRecord = None
	if 'btnSubmitRecord' in request.POST:
		frmRecord = RecordResultForm(request.POST, instance=record)
		if frmRecord.is_valid():
			record = frmRecord.save()
			log_form_change(request.user, frmRecord, action=models.ACTION_CREATE if create_new else models.ACTION_UPDATE)
			record.fill_and_save_if_needed()
			messages.success(request, 'Рекорд «{}» успешно {}'.format(record, 'создан' if create_new else 'обновлён'))
			return redirect(record.get_group_url())
		else:
			messages.warning(request, 'Рекорд не {}. Пожалуйста, исправьте ошибки в форме.'.format('создан' if create_new else 'обновлён'))

	if frmRecord is None:
		frmRecord = RecordResultForm(instance=record)
	context['record'] = record
	context['form'] = frmRecord
	context['page_title'] = 'Рекорд {} (id {})'.format(record, record.id) if record.id else 'Добавление нового рекорда'
	return render(request, 'editor/age_groups/age_group_record_details.html', context)

@group_required('age_records_editors')
def age_group_record_delete(request, record_result_id):
	if 'btnDeleteRecord' in request.POST:
		record_result = get_object_or_404(models.Record_result, pk=record_result_id)
		result_id = record_result.result_id
		country = record_result.country
		gender = record_result.gender
		age_group = record_result.age_group
		distance = record_result.distance
		surface_type = record_result.surface_type
		if record_result.cur_place or record_result.was_record_ever or record_result.cur_place_electronic:
			models.Result_not_for_age_group_record.objects.get_or_create(country=country, gender=gender, age_group=age_group,
				distance=distance, surface_type=surface_type, result_id=result_id, defaults={'created_by': request.user})
		record_result.delete()
		update_records_for_tuple(country, gender, age_group, distance, surface_type)
		messages.success(request, 'Результат с id {} удалён из рекордов'.format(result_id))
		if distance.id in results_util.DISTANCES_FOR_COUNTRY_ULTRA_RECORDS:
			return redirect('results:ultra_record_details',
				country_id=record_result.country_id if record_result.country_id else 'RU',
				gender_code=results_util.GENDER_CODES[record_result.gender],
				distance_code=results_util.DISTANCE_CODES[record_result.distance_id],
			)
		return redirect('results:age_group_record_details',
			country_id=record_result.country_id if record_result.country_id else 'RU',
			gender_code=results_util.GENDER_CODES[record_result.gender],
			age=record_result.age_group.age_min if record_result.age_group.age_min else 0,
			distance_code=results_util.DISTANCE_CODES[record_result.distance_id],
			surface_code=results_util.SURFACE_CODES[record_result.surface_type],
		)
	return redirect('results:age_group_records')

def try_add_to_cur_session(request, record_result: models.Record_result):
	if record_result.session_id:
		messages.warning(request, f'Рекорд {record_result} уже и так учтён в сессии номер {record_result.session.get_number()}. Ничего не делаем')
		return
	cur_session = models.Masters_commission_session.get_current_session()
	if not cur_session:
		messages.warning(request, f'Сейчас нет активных сессий комиссии. Ничего не делаем')
		return
	record_result.session = cur_session
	record_result.save()
	messages.success(request, f'Рекорд {record_result} успешно добавлен к сессии номер {record_result.session.get_number()}')

@group_required('age_records_editors')
def add_to_cur_session(request, record_result_id):
	if 'btnAddToSession' not in request.POST:
		return redirect('results:age_group_records')
	record_result = get_object_or_404(models.Record_result, pk=record_result_id)
	try_add_to_cur_session(request, record_result)
	return redirect(record_result.get_group_url())

@group_required('age_records_editors')
def record_mark_good(request, bad_record_id):
	if 'next_url' in request.POST:
		bad_record = get_object_or_404(models.Result_not_for_age_group_record, pk=bad_record_id)
		bad_record.delete()
		check_electronic_records = update_records_for_tuple(bad_record.country, bad_record.gender, bad_record.age_group, bad_record.distance,
			bad_record.surface_type)
		n_results_deleted, n_results_created = find_better_age_group_results_for_tuple(bad_record.country, bad_record.gender,
			bad_record.age_group, bad_record.distance, bad_record.surface_type,
			to_delete_old=True, check_electronic_records=check_electronic_records, request=request)
		messages.success(request, 'Результат удалён из негодных в рекорды')
		messages.success(request, f'Удалено возможных рекордов: {n_results_deleted}, найдено возможных рекордов: {n_results_created}')
		return redirect(request.POST['next_url'])
	return redirect('results:age_group_records')

def get_appropriate_results(country, gender, age_group, distance, surface_type):
	other_gender = 3 - gender
	results = models.Result.objects.filter(
			Q(race__distance_real=None) | Q(race__distance_real__length__gte=distance.length),
			Q(runner=None) | Q(runner__city=None) | Q(runner__city__region__country=country),
			race__distance=distance,
			status=models.STATUS_FINISHED,
			race__is_for_handicapped=False,
		).exclude(runner__gender=other_gender).exclude(gender=other_gender).annotate(
		res_diff=ExpressionWrapper(ExtractYear(F('race__event__start_date'))-ExtractYear(F('birthday')), output_field=IntegerField())).annotate(
		runner_diff=ExpressionWrapper(ExtractYear(F('race__event__start_date'))-ExtractYear(F('runner__birthday')), output_field=IntegerField()))
	if country.id != 'RU': # For other countries, either runner or event must belong to the country
		results = results.filter(
			Q(runner__city__region__country=country)
			| Q(race__event__city__region__country=country)
			| Q(race__event__series__city__region__country=country)
		)

	if age_group.age_group_type == models.RECORD_AGE_GROUP_TYPE_SENIOR:
		age_min = age_group.age_min
		age_max = age_min + models.AGE_GROUP_RECORDS_AGE_GAP
		results = results.exclude(
			Q(age__lt=age_min) | Q(age__gt=age_max)).exclude(
			Q(res_diff__lt=age_min) | Q(res_diff__gt=age_max), birthday__isnull=False, runner__birthday=None).exclude(
			Q(runner_diff__lt=age_min) | Q(runner_diff__gt=age_max), runner__isnull=False, runner__birthday__isnull=False).exclude(
			Q(runner=None) | Q(runner__birthday=None), age=None, birthday=None)
	elif age_group.age_group_type == models.RECORD_AGE_GROUP_TYPE_YOUNG:
		results = results.exclude(age__gt=age_group.age_min).exclude(birthday__isnull=False, res_diff__gte=age_group.age_min).exclude(
			runner__isnull=False, runner__birthday__isnull=False, runner_diff__gte=age_group.age_min).exclude(
			Q(runner=None) | Q(runner__birthday=None), age=None, birthday=None)

	other_countries_codes = set(models.Country_conversion.objects.exclude(country=None).exclude(country=country).values_list('country_raw', flat=True))
	results = results.exclude(Q(runner=None) | Q(runner__city=None), country_name__in=other_countries_codes)

	if surface_type == models.SURFACE_DEFAULT:
		# For ultra records we don't check the surface
		return results
	if surface_type == models.SURFACE_INDOOR:
		surface_types = [models.SURFACE_INDOOR, models.SURFACE_INDOOR_NONSTANDARD]
		surface_types_for_series = surface_types
	else:
		if surface_type == models.SURFACE_ROAD:
			surface_types = [models.SURFACE_ROAD, models.SURFACE_HARD]
		elif surface_type == models.SURFACE_STADIUM:
			surface_types = [models.SURFACE_STADIUM, models.SURFACE_HARD]
		else: # models.SURFACE_HARD
			surface_types = [models.SURFACE_ROAD, models.SURFACE_STADIUM, models.SURFACE_HARD]
		# For indoor records we don't look at the races with not specified surface type
		surface_types_for_series = surface_types + [models.SURFACE_DEFAULT]

	return results.filter(Q(race__surface_type__in=surface_types)
			| Q(race__surface_type=models.SURFACE_DEFAULT, race__event__surface_type__in=surface_types)
			| Q(race__surface_type=models.SURFACE_DEFAULT, race__event__surface_type=models.SURFACE_DEFAULT,
				race__event__series__surface_type__in=surface_types_for_series)
		)

# Returns <=N_TOP_RESULTS pairs: (result, age_on_event_date if known else None), and <were all suitable results checked?>
def filter_by_age_on_event_date(results, age_group: models.Record_age_group, debug=False) -> Tuple[List[Tuple[models.Result, Optional[int]]], bool]:
	filtered_results = []
	age_min = age_group.age_min
	n_top_results = get_n_top_results_by_age_group(age_group)
	all_checked = True
	# for result in results[:100]: # To avoid errors 502
	for i, result in enumerate(results):
		if i == 100:
			all_checked = False
			break
		if result.runner and result.runner.birthday_known:
			result_is_good = False
			age_on_event_date = result.race.get_age_on_event_date(result.runner.birthday)
			if age_group.age_group_type == models.RECORD_AGE_GROUP_TYPE_ABSOLUTE:
				result_is_good = True
			elif age_group.age_group_type == models.RECORD_AGE_GROUP_TYPE_SENIOR:
				result_is_good = (age_min <= age_on_event_date < (age_min + models.AGE_GROUP_RECORDS_AGE_GAP))
			else: # age_group.age_group_type == models.RECORD_AGE_GROUP_TYPE_YOUNG
				# We can check this even only if result.runner.birthday.year is known, but we have very few runners with only birthyear
				result_is_good = ((result.race.event.start_date.year - result.runner.birthday.year) < age_min)
			if result_is_good:
				filtered_results.append((result, age_on_event_date))
		else:
			filtered_results.append((result, None))
		if len(filtered_results) >= n_top_results:
			break
	return filtered_results, all_checked

def get_bad_result_ids_by_tuple(country: models.Country, age_groups) -> Dict[Tuple[int, int, int, int], Set[int]]:
	all_bad_results = country.result_not_for_age_group_record_set
	bad_result_ids_by_tuple = {}
	for bad_result in country.result_not_for_age_group_record_set.filter(age_group__in=age_groups):
		tup = (bad_result.gender, bad_result.age_group_id, bad_result.distance_id, bad_result.surface_type)
		if tup not in bad_result_ids_by_tuple:
			bad_result_ids_by_tuple[tup] = set()
		bad_result_ids_by_tuple[tup].add(bad_result.result_id)
	return bad_result_ids_by_tuple

def get_n_top_results_by_age_group(age_group: models.Record_age_group) -> int:
	return 10 if (age_group.age_group_type == models.RECORD_AGE_GROUP_TYPE_ABSOLUTE) else 3

# Check if result is bad due to strange timing, wrong indoor stadium size, strong wind, etc.
# Returns <is aligible?>, <reason if not eligible>
def check_record_eligibility(distance: models.Distance, surface_type: int, result: models.Result) -> Tuple[bool, str]:
	if result.do_not_count_in_stat:
		return False, 'Результат не учитывается в статистике бегуна — значит, есть равный этому на другой дистанции.'
	if result.race.event_id in EVENT_IDS_NOT_FOR_RECORDS:
		return False, EVENT_IDS_NOT_FOR_RECORDS[result.race.event_id]
	if (distance.id in (results_util.DIST_100M_ID, results_util.DIST_200M_ID)) and result.wind and (result.wind > 2):
		return False, f'Скорость ветра: {result.wind} м/с'
	if (surface_type == results_util.SURFACE_INDOOR) and (distance.id != results_util.DIST_60M_ID) \
			and (result.race.get_surface_type() == results_util.SURFACE_INDOOR_NONSTANDARD):
		return False, 'Длина круга в манеже отлична от 200 м'
	if (distance.distance_type == models.TYPE_METERS) and (distance.length <= results_util.MAX_DISTANCE_FOR_ELECTRONIC_RECORDS) \
		and (result.race.timing != models.TIMING_ELECTRONIC) and (result.race.event.start_date > results_util.LAST_DAY_CHECK_HAND_TIMING):
		return False, 'Результаты с ручным хронометражем на дистанциях до 800 м не учитываюся с 1 января 2022 г.'
	return True, ''

# Returns the amounts of deleted candidates and created candidates
def find_better_age_group_results_for_tuple(country: models.Country, gender: int, age_group: models.Record_age_group, distance: models.Distance, surface_type: int,
		result_not_for_record_ids=None, debug=False,
		to_delete_old=False, check_electronic_records=True, request=None) -> Tuple[int, int]:
	n_deleted = 0
	if to_delete_old:
		n_deleted = age_group.possible_record_result_set.filter(
			country=country, gender=gender, distance_id=distance.id, surface_type=surface_type).delete()[0]

	if result_not_for_record_ids is None:
		result_not_for_record_ids = set(age_group.result_not_for_age_group_record_set.filter(
			country=country, gender=gender, distance=distance, surface_type=surface_type).values_list('result_id', flat=True))

	n_results_created = 0
	distance_is_minutes = (distance.distance_type in models.TYPES_MINUTES)
	result_order = '-result' if distance_is_minutes else 'result'
	check_electronic_results = check_electronic_records and (not distance_is_minutes) \
		and (distance.length <= results_util.MAX_DISTANCE_FOR_ELECTRONIC_RECORDS)
	new_electronic_result_found = False

	existing_record_results = age_group.record_result_set.filter(country=country, gender=gender, distance=distance, surface_type=surface_type)
	existing_record_result_ids = set(existing_record_results.exclude(result=None).values_list('result_id', flat=True)) | result_not_for_record_ids
	# Runners that already have at least one top result
	runners_with_records = set(existing_record_results.exclude(runner=None).exclude(cur_place=None).values_list('runner_id', flat=True))

	all_appropriate_results = get_appropriate_results(country, gender, age_group, distance, surface_type)
	results_number, _ = models.Record_candidate_results_number.objects.get_or_create(
		country=country, gender=gender, age_group=age_group, distance=distance, surface_type=surface_type)
	results_number.number = all_appropriate_results.count()
	results_number.save()

	appropriate_results_with_existing_records = all_appropriate_results.exclude(pk__in=result_not_for_record_ids).select_related('race__event__series', 'runner')
	appropriate_results = appropriate_results_with_existing_records.exclude(pk__in=existing_record_result_ids)
	# For some distances, there are too many results in absolute category, so the request results don't fit in RAM. We leave only fast enough results then
	if (age_group.age_group_type == models.RECORD_AGE_GROUP_TYPE_ABSOLUTE) and (not distance_is_minutes):
		cur_record = existing_record_results.filter(cur_place=1).first()
		if cur_record and cur_record.value:
			appropriate_results = appropriate_results.filter(result__lt=1.5*cur_record.value)

	
	n_top_results = get_n_top_results_by_age_group(age_group)
	# We take n_top_results-th result ever (with max cur_place) if it exists
	worst_record_result = existing_record_results.exclude(cur_place=None).order_by('-cur_place').first()
	if worst_record_result:
		# E.g., if we already have two saved results, we need only one result slower than current with cur_place=2
		n_slower_results_needed = n_top_results - worst_record_result.cur_place
		if debug >= 3:
			print('Worst record result: {} (id {}, place {})'.format(worst_record_result,
				worst_record_result.result.id if worst_record_result.result else 'None', worst_record_result.cur_place))

	if debug >= 2:
		print(country, gender, age_group, distance, surface_type)
		if age_group.age_min is None:
			print(appropriate_results.order_by(result_order).query)
	best_results_with_ages, all_checked = filter_by_age_on_event_date(appropriate_results.order_by(result_order), age_group, debug)
	if (not all_checked) and request:
		messages.warning(request, f'{country}, {age_group}, {gender}, {distance}, {surface_type}: проверены не все результаты, лишь лучшие 100')
	n_slower_results_found = 0
	n_results_wo_runner_found = 0
	set_runner_places = distance.id in results_util.DISTANCES_FOR_COUNTRY_ULTRA_RECORDS
	for result, age_on_event_date in best_results_with_ages:
		is_eligible, reason = check_record_eligibility(distance, surface_type, result)
		if not is_eligible:
			models.Result_not_for_age_group_record.objects.create(
				country=country,
				age_group=age_group,
				gender=gender,
				distance=distance,
				surface_type=surface_type,
				result=result,
				comment=reason,
				created_by=models.USER_ROBOT_CONNECTOR,
			)
			existing_record_result_ids.add(result.id)
			continue
		if worst_record_result:
			result_is_slower_than_worst = (result.result < worst_record_result.value) if distance_is_minutes else \
				(result.result > worst_record_result.value)
			if result_is_slower_than_worst:
				n_slower_results_found += 1
				if n_slower_results_found > n_slower_results_needed:
					if not set_runner_places:
						# We stop when there are enough results worse than worst current found.
						break
					if (len(runners_with_records) + n_results_wo_runner_found >= n_top_results) and (result.runner not in runners_with_records):
						# We stop if there already are enough distinct runners and the new result comes from some new runner.
						break
		is_electro = False
		if check_electronic_results and result.is_electronic():
			is_electro = True
			new_electronic_result_found = True
		models.Possible_record_result.objects.create(
				country=country,
				gender=gender,
				age_group=age_group,
				age_on_event_date=age_on_event_date,
				distance=distance,
				surface_type=surface_type,
				result=result,
				is_electronic=is_electro,
			)
		existing_record_result_ids.add(result.id)
		n_results_created += 1
		if set_runner_places:
			# We stop when there are enough distinct runners found, including existing records with non-null cur_place.
			# We treat all results with no runner as distinct runners.
			if result.runner_id:
				runners_with_records.add(result.runner_id)
			else: 
				n_results_wo_runner_found += 1
			if len(runners_with_records) + n_results_wo_runner_found >= n_top_results:
				break

	# Also we find possible previous records
	for ever_record_result in age_group.record_result_set.filter(country=country, gender=gender, distance=distance, surface_type=surface_type,
			was_record_ever=True).exclude(race=None).select_related('race__event'):
		results = appropriate_results_with_existing_records.filter(race__event__start_date__lt=ever_record_result.race.event.start_date)

		if surface_type != results_util.SURFACE_DEFAULT:
			# For non-ultra distances we don't check too low results.
			if distance_is_minutes:
				results = results.filter(result__gte=int(round(ever_record_result.value * 0.8)))
			else:
				results = results.filter(result__lte=int(round(ever_record_result.value * 1.2)))

		best_results_with_ages, all_checked = filter_by_age_on_event_date(results.order_by(result_order), age_group, debug)
		if (not all_checked) and request:
			messages.warning(request, f'{country}, {age_group}, {gender}, {distance}, {surface_type}: для бывших рекордов проверены не все результаты, лишь лучшие 100')
		if best_results_with_ages:
			result, age_on_event_date = best_results_with_ages[0]
			if result.id in existing_record_result_ids:
				continue
			is_eligible, reason = check_record_eligibility(distance, surface_type, result)
			if not is_eligible:
				models.Result_not_for_age_group_record.objects.create(
					country=country,
					age_group=age_group,
					gender=gender,
					distance=distance,
					surface_type=surface_type,
					result=result,
					comment=reason,
					created_by=models.USER_ROBOT_CONNECTOR,
				)
				existing_record_result_ids.add(result.id)
				continue
			is_electro = False
			if check_electronic_results and result.is_electronic():
				is_electro = True
				new_electronic_result_found = True
			models.Possible_record_result.objects.create(
					country=country,
					gender=gender,
					age_group=age_group,
					age_on_event_date=age_on_event_date,
					distance=distance,
					surface_type=surface_type,
					result=result,
					can_be_prev_record=True,
					is_electronic=is_electro,
				)
			existing_record_result_ids.add(result.id)
			n_results_created += 1

	# And electronic results
	if check_electronic_results and not new_electronic_result_found:
		worst_electronic_record = existing_record_results.exclude(cur_place_electronic=None).order_by('-cur_place_electronic').first()
		best_electronic_results = appropriate_results_with_existing_records.exclude(pk__in=existing_record_result_ids).filter(
			race__timing__in=(models.TIMING_UNKNOWN, models.TIMING_ELECTRONIC))
		best_electronic_results_with_ages, all_checked = filter_by_age_on_event_date(best_electronic_results.order_by(result_order), age_group, debug)
		if (not all_checked) and request:
			messages.warning(request, f'{country}, {age_group}, {gender}, {distance}, {surface_type}: для электронных рекордов проверены не все результаты, лишь лучшие 100')
		if best_electronic_results_with_ages:
			result, age_on_event_date = best_electronic_results_with_ages[0]
			is_eligible, reason = check_record_eligibility(distance, surface_type, result)
			if not is_eligible:
				models.Result_not_for_age_group_record.objects.create(
					country=country,
					age_group=age_group,
					gender=gender,
					distance=distance,
					surface_type=surface_type,
					result=result,
					comment=reason,
					created_by=models.USER_ROBOT_CONNECTOR,
				)
			elif (worst_electronic_record is None) or (worst_electronic_record.value > result.result) or \
					(worst_electronic_record.cur_place_electronic < n_top_results):
				models.Possible_record_result.objects.create(
						country=country,
						gender=gender,
						age_group=age_group,
						age_on_event_date=age_on_event_date,
						distance=distance,
						surface_type=surface_type,
						result=result,
						is_electronic=True,
					)
				existing_record_result_ids.add(result.id)
				n_results_created += 1

	return n_deleted, n_results_created

@group_required('age_records_editors')
def delete_other_saved_results(request, country_id, gender_code, age, distance_code, surface_code):
	country, gender, age_group, distance, surface_type = views_age_group_record.decode_record_group_fields(country_id, gender_code, age, distance_code, surface_code, request)

	records = age_group.record_result_set.filter(country=country, gender=gender, distance=distance, surface_type=surface_type,
		was_record_ever=False, cur_place=None, cur_place_electronic=None, ignore_for_country_records=False)

	n_results_deleted = records.delete()

	messages.success(request, f'Удалено {n_results_deleted[0]} других сохранённых результатов')

	kwargs = {
		'country_id':country_id,
		'gender_code': gender_code,
		'distance_code': distance_code,
	}
	if surface_type == results_util.SURFACE_DEFAULT:
		return redirect('results:ultra_record_details', **kwargs)
	return redirect('results:age_group_record_details', age=age, surface_code=surface_code, **kwargs)

@group_required('age_records_editors')
def generate_better_age_group_results_for_tuple(request, country_id, gender_code, age, distance_code, surface_code):
	country, gender, age_group, distance, surface_type = views_age_group_record.decode_record_group_fields(country_id, gender_code, age, distance_code, surface_code, request)

	check_electronic_records = update_records_for_tuple(country, gender, age_group, distance, surface_type)
	
	n_results_deleted, n_results_created = find_better_age_group_results_for_tuple(country, gender, age_group, distance, surface_type,
		to_delete_old=True, check_electronic_records=check_electronic_records, request=request)

	messages.success(request, f'Удалено возможных рекордов: {n_results_deleted}, найдено возможных рекордов: {n_results_created}')

	kwargs = {
		'country_id':country_id,
		'gender_code': gender_code,
		'distance_code': distance_code,
	}
	if surface_type == results_util.SURFACE_DEFAULT:
		return redirect('results:ultra_record_details', **kwargs)
	return redirect('results:age_group_record_details', age=age, surface_code=surface_code, **kwargs)

def generate_better_age_group_results(country_id, generate_outdoor=True, generate_indoor=True, generate_ultra=True, debug=False):
	if debug:
		print(f'{datetime.datetime.now()} generate_better_age_group_results for country {country_id} started')
	country = models.Country.objects.get(pk=country_id)
	if generate_outdoor:
		models.Possible_record_result.objects.filter(country=country).exclude(surface_type=results_util.SURFACE_INDOOR).delete()
	if generate_indoor:
		models.Possible_record_result.objects.filter(country=country, surface_type=results_util.SURFACE_INDOOR).delete()
	if generate_ultra:
		models.Possible_record_result.objects.filter(country=country, surface_type=results_util.SURFACE_DEFAULT).delete()

	# age_groups = models.Record_age_group.objects.exclude(age_group_type=models.RECORD_AGE_GROUP_TYPE_YOUNG).order_by('age_min')
	age_groups = models.Record_age_group.objects.order_by('age_min')
	bad_result_ids_by_tuple = get_bad_result_ids_by_tuple(country, age_groups)
	n_results_created = 0

	distance_surface_pairs = []
	if generate_outdoor:
		distance_surface_pairs += list(results_util.DISTANCES_FOR_COUNTRY_OUTDOOR_RECORDS)
	if generate_indoor:
		distance_surface_pairs += [(distance_id, results_util.SURFACE_INDOOR) for distance_id in results_util.DISTANCES_FOR_COUNTRY_INDOOR_RECORDS]
	if generate_ultra:
		distance_surface_pairs += [(distance_id, results_util.SURFACE_DEFAULT) for distance_id in results_util.DISTANCES_FOR_COUNTRY_ULTRA_RECORDS]

	for distance_id, surface_type in distance_surface_pairs:
		distance = models.Distance.objects.get(pk=distance_id)
		for gender in (results_util.GENDER_MALE, results_util.GENDER_FEMALE):
			distance_is_minutes = (distance.distance_type in models.TYPES_MINUTES)
			for age_group in age_groups:
				if (surface_type == results_util.SURFACE_DEFAULT) and (age_group.age_group_type != models.RECORD_AGE_GROUP_TYPE_ABSOLUTE):
					# We now search only for absolute records in ultra distances
					continue
				check_electronic_records = update_records_for_tuple(country, gender, age_group, distance, surface_type)
				n_just_deleted, n_just_created = find_better_age_group_results_for_tuple(
					country, gender, age_group, distance, surface_type,
					result_not_for_record_ids=bad_result_ids_by_tuple.get((gender, age_group.id, distance.id, surface_type), set()),
					debug=debug, check_electronic_records=check_electronic_records)
				n_results_created += n_just_created

	stat.set_stat_value(f'possible_age_records_gen_{country_id}', 0, datetime.date.today())
	if debug:
		print(f'{datetime.datetime.now()} generate_better_age_group_results for country {country_id} finished')
	print('Results created:', n_results_created)

@group_required('age_records_editors')
def better_age_group_results(request, country_id='RU', is_indoor=0):
	country = models.Country.objects.get(pk=country_id)

	context = {}
	context['is_admin'] = True
	context['last_update'] = models.Statistics.objects.filter(name='possible_age_records_gen_{}'.format(country_id)).order_by(
		'-date_added').first().date_added
	context['page_title'] = 'Возможные результаты в возрастных группах лучше официальных рекордов {}'.format(country.prep_case)
	if is_indoor:
		context['page_title'] += ' в помещении'
	context['country'] = country
	context['is_indoor'] = is_indoor
	context['to_show_buttons'] = True

	age_groups = models.Record_age_group.objects.order_by('age_min')
	# age_groups = models.Record_age_group.objects.exclude(age_group_type=models.RECORD_AGE_GROUP_TYPE_SENIOR).order_by('age_min')
	# age_groups = models.Record_age_group.objects.filter(age_min__range=(40, 80)).order_by('age_min')
	bad_result_ids_by_tuple = get_bad_result_ids_by_tuple(country, age_groups)
	
	if is_indoor:
		dist_id_surface_pairs = [(distance_id, results_util.SURFACE_INDOOR) for distance_id in results_util.DISTANCES_FOR_COUNTRY_INDOOR_RECORDS]
	else:
		dist_id_surface_pairs = results_util.DISTANCES_FOR_COUNTRY_OUTDOOR_RECORDS \
			+ [(distance_id, results_util.SURFACE_DEFAULT) for distance_id in results_util.DISTANCES_FOR_COUNTRY_ULTRA_RECORDS]
	distance_surface_pairs = [(models.Distance.objects.get(pk=dist_id), surface_type) for dist_id, surface_type in dist_id_surface_pairs]

	context['items'] = []
	context['n_results_found'] = 0
	contents = {results_util.GENDER_FEMALE: set(), results_util.GENDER_MALE: set()}
	for gender in (results_util.GENDER_MALE, results_util.GENDER_FEMALE):
		for distance, surface_type in distance_surface_pairs:
			for age_group in age_groups:
				if (distance.id in results_util.DISTANCES_FOR_COUNTRY_ULTRA_RECORDS) and (age_group.age_group_type != models.RECORD_AGE_GROUP_TYPE_ABSOLUTE):
					continue
				data = {}
				ordering = '-result__result' if (distance.distance_type in models.TYPES_MINUTES) else 'result__result'
				data['best_results'] = age_group.possible_record_result_set.filter(country=country, gender=gender, distance=distance,
					surface_type=surface_type).select_related('result__race__event__series__city__region__country',
					'result__race__event__city__region__country','result__runner__user__user_profile', 'result__runner__city__region__country',
					'result__result_on_strava', 'result__category_size').order_by(ordering)
				data['bad_results'] = bad_result_ids_by_tuple.get((gender, age_group.id, distance.id, surface_type), set())
				if data['bad_results']:
					data['best_results'] = data['best_results'].exclude(result_id__in=data['bad_results'])

				n_results_found = data['best_results'].count()
				if n_results_found > 0:
					context['n_results_found'] += n_results_found
					data['record_results'] = age_group.record_result_set.filter(
						country=country, gender=gender, distance=distance, surface_type=surface_type).exclude(cur_place=None).select_related(
						'result__race__event__series', 'result__runner__user__user_profile').order_by('cur_place')

					data['gender_name'] = models.GENDER_CHOICES[gender][1]
					data['gender_code'] = results_util.GENDER_CODES[gender]
					data['age_group'] = age_group
					data['distance'] = distance
					data['distance_code'] = results_util.DISTANCE_CODES[distance.id]
					data['surface_code'] = results_util.SURFACE_CODES[surface_type]

					data['anchor_id'] = f"{data['gender_code']}_{data['distance_code']}"
					# Three first items are for correct ordering of distances
					contents[gender].add(
						(1 if (surface_type == results_util.SURFACE_DEFAULT) else 0,
						distance.distance_type,
						-distance.length,
						data['anchor_id'],
						distance.name)
					)

					if surface_type not in (results_util.SURFACE_INDOOR, results_util.SURFACE_DEFAULT):
						data['surface_desc'] = results_util.SURFACE_TYPES_DICT[surface_type]

					if surface_type == results_util.SURFACE_DEFAULT:
						data['age_group_url'] = reverse('results:ultra_record_details', kwargs = {
							'country_id': country.id,
							'gender_code': data['gender_code'],
							'distance_code': data['distance_code'],
							})
					else:
						data['age_group_url'] = reverse('results:age_group_record_details', kwargs = {
							'country_id': country.id,
							'gender_code': data['gender_code'],
							'age': data['age_group'].get_int_value(),
							'distance_code': data['distance_code'],
							'surface_code': data['surface_code'],
							})

					context['items'].append(data)
	context['contents'] = OrderedDict([(key, sorted(val)) for key, val in contents.items()])
	return render(request, 'editor/age_groups/better_age_group_results.html', context)

def get_record_before_given_if_exists(records, value_order, given_record):
	return records.filter(date__lt=given_record.date).order_by(value_order, 'date').first()

# Mark current top-<n_top_results> results and results that were records ever.
# Returns <Do we need to look for more electronic records?>
def update_records_for_tuple(country: models.Country, gender: int, age_group: models.Record_age_group, distance: models.Distance, surface_type: int) -> bool:
	age_group.result_not_for_age_group_record_set.filter(country=country, gender=gender, distance=distance, surface_type=surface_type).exclude(
		result__status=models.STATUS_FINISHED).delete()

	records = age_group.record_result_set.filter(country=country, gender=gender, distance=distance, surface_type=surface_type)
	records.update(cur_place=None, cur_place_electronic=None, was_record_ever=False, runner_place=None)
	records = records.filter(ignore_for_country_records=False)

	distance_is_minutes = (distance.distance_type in models.TYPES_MINUTES)
	value_order = '-value' if distance_is_minutes else 'value'
	cur_record = None
	n_top_results = get_n_top_results_by_age_group(age_group)
	mentioned_runners = set() # To mark the best result for each runner

	all_records_are_electronic = True
	to_find_electronic_records = (not distance_is_minutes) and (distance.length <= results_util.MAX_DISTANCE_FOR_ELECTRONIC_RECORDS)
	set_runner_places = distance.id in results_util.DISTANCES_FOR_COUNTRY_ULTRA_RECORDS

	for i, record in enumerate(records.order_by(value_order, 'date')):
		record.cur_place = i + 1
		if i == 0:
			record.was_record_ever = True
			cur_record = record
		if record.runner:
			if record.runner not in mentioned_runners:
				mentioned_runners.add(record.runner)
				record.runner_place = len(mentioned_runners)
		record.save()
		if all_records_are_electronic and to_find_electronic_records and not record.is_electronic():
			all_records_are_electronic = False
		if set_runner_places: # We enumerate best results until we have n_top_results distinct runners.
			if len(mentioned_runners) == n_top_results:
				break
		else: # We enumerate only n_top_results best results.
			if i == n_top_results - 1:
				break
	if cur_record: # So we have at least one record result
		prev_record = get_record_before_given_if_exists(records, value_order, cur_record)
		while prev_record:
			prev_record.was_record_ever = True
			prev_record.save()
			prev_record = get_record_before_given_if_exists(records, value_order, prev_record)

	if not all_records_are_electronic: # Then we mark best results with electronic timing
		i = 1
		for record in records.exclude(race__timing=models.TIMING_HAND).select_related('race').order_by(value_order, 'date'):
			if record.is_electronic():
				record.cur_place_electronic = i
				record.save()
				i += 1
				if i > n_top_results:
					break
	return not all_records_are_electronic

def update_all_tuples():
	tuples = set()
	for record_result in models.Record_result.objects.all().select_related('age_group', 'country', 'distance'):
		tuples.add((record_result.country, record_result.gender, record_result.age_group, record_result.distance, record_result.is_indoor))
	print(len(tuples), 'tuples')
	for t in tuples:
		update_records_for_tuple(*t)
	print(models.Record_result.objects.filter(was_record_ever=True).count())

@group_required('age_records_editors')
def add_possible_age_group_records(request):
	country_id = 'RU'
	redirect_to_indoor_page = False
	if request.method == 'POST':
		n_records_added = 0
		n_results_marked_good = 0
		n_results_marked_bad = 0
		tuples_with_changed_records = set()

		for key, val in list(request.POST.items()):
			if key.startswith("add_record_"):
				possible_record_result_id = results_util.int_safe(key[len("add_record_"):])
				prr = models.Possible_record_result.objects.filter(pk=possible_record_result_id).first()
				if prr is None:
					messages.warning(request, 'Возможный рекорд с id {} не найден'.format(possible_record_result_id))
					continue
				if models.Result_not_for_age_group_record.objects.filter(country_id=prr.country_id,
						age_group_id=prr.age_group_id, result_id=prr.result_id).exists():
					messages.warning(request, 'Возможный рекорд с id {} помечен как плохой. Не добавляем в рекорды'.format(prr.id))
					continue
				if models.Record_result.objects.filter(country_id=prr.country_id,
						age_group_id=prr.age_group_id, result_id=prr.result_id).exists():
					messages.warning(request, 'Возможный рекорд с id {} уже и так числится в рекордах. Удаляем с этой страницы'.format(prr.id))
					prr.delete()
					continue
				record_result = models.Record_result.objects.create(
						country_id=prr.country_id,
						gender=prr.gender,
						age_group_id=prr.age_group_id,
						age_on_event_date=prr.age_on_event_date,
						distance_id=prr.distance_id,
						surface_type=prr.surface_type,
						value=prr.result.result,
						runner=prr.result.runner,
						result=prr.result,
						race=prr.result.race,
						created_by=request.user,
					)
				record_result.fill_and_save_if_needed()
				n_records_added += 1
				tuples_with_changed_records.add((record_result.country, record_result.gender, record_result.age_group, record_result.distance,
					record_result.surface_type))
				prr.delete()
				redirect_to_indoor_page = prr.surface_type == results_util.SURFACE_INDOOR
				country_id = prr.country_id

			elif key.startswith("mark_as_good_"):
				possible_record_result_id = results_util.int_safe(key[len("mark_as_good_"):])
				prr = models.Possible_record_result.objects.filter(pk=possible_record_result_id).first()
				if prr is None:
					messages.warning(request, 'Возможный рекорд с id {} не найден'.format(possible_record_result_id))
					continue
				result_not_for_age_group_record = models.Result_not_for_age_group_record.objects.filter(
					country=prr.country, age_group=prr.age_group, result=prr.result).first()
				if result_not_for_age_group_record is None:
					messages.warning(request, 'Результат с id {} и так считается хорошим для страны {} и возрастной группы {}'.format(
						prr.result.id, prr.country, prr.age_group))
					continue
				result_not_for_age_group_record.delete()
				n_results_marked_good += 1
				tuples_with_changed_records.add((prr.country, prr.gender, prr.age_group, prr.distance, prr.surface_type))
				redirect_to_indoor_page = prr.surface_type == results_util.SURFACE_INDOOR
				country_id = prr.country_id

			elif key.startswith("mark_as_bad_"):
				possible_record_result_id = results_util.int_safe(key[len("mark_as_bad_"):])
				prr = models.Possible_record_result.objects.filter(pk=possible_record_result_id).first()
				if prr is None:
					messages.warning(request, 'Возможный рекорд с id {} не найден'.format(possible_record_result_id))
					continue
				if models.Result_not_for_age_group_record.objects.filter(
						country=prr.country, age_group=prr.age_group, result=prr.result).exists():
					messages.warning(request, 'Результат с id {} уже был помечен как негодный для страны {} и возрастной группы {}'.format(
						prr.result.id, prr.country, prr.age_group))
					continue
				models.Result_not_for_age_group_record.objects.create(
					country=prr.country,
					age_group=prr.age_group,
					gender=prr.gender,
					distance=prr.distance,
					surface_type=prr.surface_type,
					result=prr.result,
					created_by=request.user,
				)
				n_results_marked_bad += 1
				tuples_with_changed_records.add((prr.country, prr.gender, prr.age_group, prr.distance, prr.surface_type))
				redirect_to_indoor_page = prr.surface_type == results_util.SURFACE_INDOOR
				country_id = prr.country_id

		if n_records_added > 0:
			messages.success(request, 'Добавлено результатов в рекорды в возрастных группах: {}'.format(n_records_added))
		if n_results_marked_good > 0:
			messages.success(request, 'Ранее помеченных как негодные для рекордов результаты исправлено: {}'.format(n_results_marked_good))
		if n_results_marked_bad > 0:
			messages.success(request, 'Результатов помечено как негодные для рекордов: {}'.format(n_results_marked_bad))
		if tuples_with_changed_records:
			for tup in tuples_with_changed_records:
				check_electronic_records = update_records_for_tuple(*tup)
				find_better_age_group_results_for_tuple(*tup, debug=False, to_delete_old=True, check_electronic_records=check_electronic_records, request=request)
			messages.success(request, f'Групп, в которых заново поискали возможные рекорды: {len(tuples_with_changed_records)}')
	if 'next_url' in request.POST:
		return redirect(request.POST['next_url'])
	return redirect('editor:better_age_group_results', country_id=country_id, is_indoor=1 if redirect_to_indoor_page else 0)

@group_required('age_records_editors')
def update_age_group_records(request, country_id, gender_code, age, distance_code, surface_code):
	gender = results_util.GENDER_CODES_INV.get(gender_code)
	if not gender:
		raise Http404()
	age_min = None if (age == 0) else age
	age_group = get_object_or_404(models.Record_age_group, age_min=age_min)
	distance_id = results_util.DISTANCE_CODES_INV.get(distance_code)
	surface_type = results_util.SURFACE_CODES_INV.get(surface_code)

	n_updated = 0
	for record in age_group.record_result_set.filter(country_id=country_id, gender=gender, distance_id=distance_id, surface_type=surface_type):
		n_updated += record.fill_and_save_if_needed(force=True)
	messages.success(request, 'Уточнена информация о рекордах: {}'.format(n_updated))
	if distance_id in results_util.DISTANCES_FOR_COUNTRY_ULTRA_RECORDS:
		return redirect('results:ultra_record_details',
			country_id=country_id,
			gender_code=gender_code,
			distance_code=distance_code,
		)
	return redirect('results:age_group_record_details', country_id=country_id, gender_code=gender_code, age=age, distance_code=distance_code,
		surface_code=surface_code)

def update_all_age_group_records():
	print('Deleted records:', models.Record_result.objects.filter(was_record_ever=False, cur_place=None, cur_place_electronic=None, ignore_for_country_records=False).delete())
	n_updated = 0
	for record in models.Record_result.objects.all():
		n_updated += record.fill_and_save_if_needed(force=True)
	print('Updated records:', n_updated)

def best_results_by_year(country, gender, age_group, distance, surface_type, year_start, year_end):
	distance_is_minutes = (distance.distance_type in models.TYPES_MINUTES)
	result_order = '-result' if distance_is_minutes else 'result'
	result_not_for_record_ids = set(age_group.result_not_for_age_group_record_set.filter(
			country=country, gender=gender, distance=distance, surface_type=surface_type).values_list('result_id', flat=True))
	return get_appropriate_results(country, gender, age_group, distance, surface_type).exclude(pk__in=result_not_for_record_ids).filter(
		race__event__start_date__year__gte=year_start, race__event__start_date__year__lte=year_end).select_related(
		'race__event', 'runner').order_by(result_order)

def print_best_results_by_year():
	country=models.Country.objects.get(pk='RU')
	gender=2
	age_group=models.Record_age_group.objects.get(age_group_type=models.RECORD_AGE_GROUP_TYPE_ABSOLUTE)
	distance=models.Distance.objects.get(pk=results_util.DIST_10KM_ID)
	surface_type = results_util.SURFACE_STADIUM
	for result in best_results_by_year(country, gender, age_group, distance, surface_type, 2019, 2021)[:20]:
		print(
			result,
			result.runner.name() if result.runner else f'{result.fname} {result.lname}',
			f'https://probeg.org{result.runner.get_absolute_url()}' if result.runner else '',
			result.race.event.name,
			result.race.id,
			result.race.event.start_date)

def best_results_after_2000(distance_id=results_util.DIST_24HOURS_ID):
	country=models.Country.objects.get(pk='RU')
	gender=2
	age_group=models.Record_age_group.objects.get(age_group_type=models.RECORD_AGE_GROUP_TYPE_ABSOLUTE)
	distance=models.Distance.objects.get(pk=distance_id)
	surface_type = results_util.SURFACE_DEFAULT
	for i, result in enumerate(get_appropriate_results(country, gender, age_group, distance, surface_type).filter(result__gte=255000, race__event__start_date__year__gte=2001).order_by('-result')):
		print(i + 1, result.lname, result.fname, result.race.event.start_date, result.result)

def fill_record_protocols():
	n_filled = 0
	events = set()
	for record_result in list(models.Record_result.objects.filter(protocol=None).exclude(result=None).select_related('result__race')):
		protocols = models.Document.objects.filter(event_id=record_result.result.race.event_id, document_type=models.DOC_TYPE_PROTOCOL).exclude(url_source='', hide_local_link=models.DOC_HIDE_ALWAYS)
		count = protocols.count()
		if count > 1:
			events.add(record_result.result.race.event_id)
		elif count == 1:
			record_result.protocol = protocols[0]
			record_result.save()
			n_filled += 1
	print(n_filled)
	print(sorted(events))

def get_record_group_redirect(country_id, gender_code, age, distance_code, surface_code):
	kwargs = {
		'country_id':country_id,
		'gender_code': gender_code,
		'distance_code': distance_code,
	}
	surface_type = results_util.SURFACE_CODES_INV.get(surface_code)
	if surface_type == results_util.SURFACE_DEFAULT:
		return redirect('results:ultra_record_details', **kwargs)
	return redirect('results:age_group_record_details', age=age, surface_code=surface_code, **kwargs)

@group_required('age_records_editors')
def add_comment(request, country_id, gender_code, age, distance_code, surface_code):
	country, gender, age_group, distance, surface_type = views_age_group_record.decode_record_group_fields(country_id, gender_code, age, distance_code, surface_code)
	redirect_link = get_record_group_redirect(country_id, gender_code, age, distance_code, surface_code)

	if 'btnAddComment' not in request.POST:
		return redirect_link

	content = request.POST.get('content', '').strip()
	if not content:
		messages.warning(request, 'Вы указали пустой комментарий. Не добавляем')
		return redirect_link

	if models.Record_category_comment.objects.filter(country=country, gender=gender, age_group=age_group, distance=distance, surface_type=surface_type, content=content).exists():
		messages.warning(request, f'Комментарий {content} для этой группы рекордов уже и так есть. Ничего не делаем')
		return redirect_link

	models.Record_category_comment.objects.create(country=country, gender=gender, age_group=age_group, distance=distance, surface_type=surface_type, content=content, created_by=request.user)
	messages.success(request, f'Комментарий к этой группе рекордов успешно добавлен')
	return redirect_link

@group_required('age_records_editors')
def mark_cur_session_complete(request):
	session = models.Masters_commission_session.objects.order_by('-pk').first()
	if session.date:
		messages.warning(request, f'У заседания № {session.get_number()} уже указана дата {session.date}. Ничего не делаем')
		return redirect('results:age_group_records', country_id='RU')
	n_records_marked_ex = 0
	for record in session.record_result_set.all():
		n_records_marked_ex += views_age_group_record.current_records(record, session.id).update(is_approved_record_now=False)
	n_new_records = session.record_result_set.all().update(is_approved_record_now=True)
	messages.success(request, f'Утверждено новых рекордов: {n_new_records}, помечено как бывшие рекорды: {n_records_marked_ex}')
	session.date = datetime.date.today() - datetime.timedelta(days=1)
	session.is_complete = True
	session.save()
	messages.success(request, f'Заседанию № {session.get_number()} поставлена дата {session.date}')
	return r