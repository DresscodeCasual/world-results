from django.shortcuts import get_object_or_404, render, redirect, reverse
from django.forms import formset_factory
from django.db.models import Q, QuerySet
from django.http import Http404

from collections import OrderedDict
import datetime
from typing import Any, Optional, Tuple

from results import models, forms, forms_age_groups, results_util
from results.views.views_common import user_edit_vars

def get_records_dict(country, age_groups, is_indoor):
	res = {}
	res['is_indoor'] = 1 if is_indoor else 0

	if is_indoor:
		dist_id_surface_pairs = [(distance_id, results_util.SURFACE_INDOOR) for distance_id in results_util.DISTANCES_FOR_COUNTRY_INDOOR_RECORDS]
	else:
		dist_id_surface_pairs = results_util.DISTANCES_FOR_COUNTRY_OUTDOOR_RECORDS
	distance_surface_pairs = [(models.Distance.objects.get(pk=dist_id), surface_type) for dist_id, surface_type in dist_id_surface_pairs]

	res['distances_and_surfaces'] = [
			(
				distance.get_name(surface_type),
				results_util.DISTANCE_CODES[distance.id],
				results_util.SURFACE_TYPES_DICT[surface_type],
				results_util.SURFACE_CODES[surface_type],
			)
			for distance, surface_type in distance_surface_pairs
		]

	suffix = ' в помещении (таблица в разработке. Данные пока неточные)' if (is_indoor or (country.id == 'BY')) else ' (таблица в разработке. Данные пока неточные)'
	data = OrderedDict([
			(results_util.GENDER_MALE, {'name': 'Мужчины' + suffix, 'gender_code': results_util.GENDER_CODES[results_util.GENDER_MALE],
				'age_groups': OrderedDict()}),
			(results_util.GENDER_FEMALE, {'name': 'Женщины' + suffix, 'gender_code': results_util.GENDER_CODES[results_util.GENDER_FEMALE],
				'age_groups': OrderedDict()})
		])
	for age_group in age_groups:
		for gender in [results_util.GENDER_MALE, results_util.GENDER_FEMALE]:
			data[gender]['age_groups'][age_group] = {
				'distances': OrderedDict([((distance, surface_type), [None, None]) for distance, surface_type in distance_surface_pairs]),
				'show_hand_records_row': False
			}

	record_results = models.Record_result.objects.filter(
				Q(cur_place=1) | Q(cur_place_electronic=1),
				country_id=country.id,
				age_group__in=age_groups,
			# For manual 100m Russian "record"
			).exclude(age_group__age_group_type=models.RECORD_AGE_GROUP_TYPE_ABSOLUTE, timing=models.TIMING_HAND, distance_id=results_util.DIST_100M_ID).select_related(
			'age_group', 'distance', 'runner__user__user_profile', 'runner__city__region__country', 'result__race__distance', 'session')
	if is_indoor:
		record_results = record_results.filter(surface_type=results_util.SURFACE_INDOOR)
	else:
		record_results = record_results.exclude(surface_type=results_util.SURFACE_INDOOR)

	for record_result in record_results:
		distance = record_result.distance
		surface_type = record_result.surface_type
		if (distance, surface_type) not in distance_surface_pairs:
			continue
		prefer_electronic_results = (distance.distance_type not in models.TYPES_MINUTES) \
			and (distance.length <= results_util.MAX_DISTANCE_FOR_ELECTRONIC_RECORDS)

		row = 1 if prefer_electronic_results and (not record_result.is_electronic()) else 0
		data[record_result.gender]['age_groups'][record_result.age_group]['distances'][(distance, surface_type)][row] = record_result
		if row == 1:
			data[record_result.gender]['age_groups'][record_result.age_group]['show_hand_records_row'] = True

	res['data'] = data
	return res

def age_group_records(request, country_id='RU'):
	context: dict[str, Any] = user_edit_vars(request.user)
	context['country'] = get_object_or_404(models.Country, pk=country_id, pk__in=results_util.THREE_COUNTRY_IDS)
	context['page_title'] = f'Рекорды {context["country"].prep_case} в беге в возрастных группах'
	context['skip_adsense'] = True
	
	age_groups = models.Record_age_group.objects.all()
	if not context['is_admin']:
		age_groups = age_groups.exclude(age_group_type=models.RECORD_AGE_GROUP_TYPE_YOUNG)

	context['tables'] = [get_records_dict(context['country'], age_groups, is_indoor=is_indoor) for is_indoor in (False, True)]

	if context['country'].id == 'RU':
		context['commission_sessions'] = models.Masters_commission_session.objects.filter(is_complete=True).order_by('-pk')
		if request.user.groups.filter(name='age_records_editors').exists():
			context['cur_active_session'] = models.Masters_commission_session.objects.filter(date=None).order_by('pk').first()

	return render(request, 'age_group_records/age_group_records.html', context)

def get_ultra_records_dict(country):
	res = {}
	distances = [models.Distance.objects.get(pk=dist_id) for dist_id in results_util.DISTANCES_FOR_COUNTRY_ULTRA_RECORDS]
	res['distances'] = [(distance, results_util.DISTANCE_CODES[distance.id]) for distance in distances]
	distance_indices = {distances[i].id: i for i in range(len(distances))}

	data = OrderedDict([
			(results_util.GENDER_MALE,
				{
					'name': 'Мужчины',
					'gender_code': results_util.GENDER_CODES[results_util.GENDER_MALE],
					'results': [[None] * len(distances) for _ in range(results_util.N_TOP_RESULTS_FOR_ULTRA_MAIN_PAGE)],
				}
			),
			(results_util.GENDER_FEMALE,
				{
					'name': 'Женщины',
					'gender_code': results_util.GENDER_CODES[results_util.GENDER_FEMALE],
					'results': [[None] * len(distances) for _ in range(results_util.N_TOP_RESULTS_FOR_ULTRA_MAIN_PAGE)],
				}
			),
		])

	record_results = models.Record_result.objects.filter(
				country_id=country.id,
				distance_id__in=results_util.DISTANCES_FOR_COUNTRY_ULTRA_RECORDS,
				cur_place__lte=results_util.N_TOP_RESULTS_FOR_ULTRA_MAIN_PAGE,
			).select_related(
			'age_group', 'distance', 'runner__user__user_profile', 'runner__city__region__country', 'result__race__distance')
	for record_result in record_results:
		distance = record_result.distance
		data[record_result.gender]['results'][record_result.cur_place - 1][distance_indices[record_result.distance.id]] = record_result
	res['data'] = data
	return res

def ultra_records(request, country_id='RU'):
	context: dict[str, Any] = user_edit_vars(request.user)
	context['country'] = get_object_or_404(models.Country, pk=country_id, pk__in=results_util.THREE_COUNTRY_IDS)
	context['page_title'] = 'Рекорды {} на ультрамарафонских дистанциях'.format(context['country'].prep_case)
	context['table'] = get_ultra_records_dict(context['country'])
	return render(request, 'age_group_records/ultra_records.html', context)

def ultra_records_extra(request, country_id='RU'):
	context: dict[str, Any] = user_edit_vars(request.user)
	context['country'] = get_object_or_404(models.Country, pk=country_id, pk__in=results_util.THREE_COUNTRY_IDS)
	context['page_title'] = 'Рекорды {} на ультрамарафонских дистанциях'.format(context['country'].prep_case)
	context['table'] = get_ultra_records_dict(context['country'])
	return render(request, 'age_group_records/ultra_records.html', context)

def decode_record_group_fields(country_id: str, gender_code: str, age: int, distance_code: str, surface_code: str, request=None) -> Tuple[models.Country, int, models.Record_age_group, models.Distance, int]:
	country = models.Country.objects.get(pk=country_id)
	gender = results_util.GENDER_CODES_INV.get(gender_code)
	if (not gender) or (gender == results_util.GENDER_UNKNOWN):
		raise Http404(f'Недопустимый номер пола бегунов: {gender_code}')
	age_min = None if (age == 0) else age
	age_group = get_object_or_404(models.Record_age_group, age_min=age_min)

	distance_id = results_util.DISTANCE_CODES_INV.get(distance_code)
	distance = get_object_or_404(models.Distance, pk=distance_id)

	surface_type = results_util.SURFACE_CODES_INV.get(surface_code)
	if surface_type is None:
		raise Http404(f'Недопустимый тип покрытия {surface_code}')

	if surface_type == results_util.SURFACE_INDOOR:
		if distance_id not in results_util.DISTANCES_FOR_COUNTRY_INDOOR_RECORDS:
			raise Http404(f'Мы не считаем рекорды для дистанции {distance} и типа покрытия {results_util.SURFACE_TYPES[surface_type][1]}')
	elif surface_type == results_util.SURFACE_DEFAULT:
		if distance_id not in results_util.DISTANCES_FOR_COUNTRY_ULTRA_RECORDS:
			raise Http404(f'Мы не считаем рекорды для дистанции {distance} и типа покрытия {results_util.SURFACE_TYPES[surface_type][1]}')
	else:
		if (distance_id, surface_type) not in results_util.DISTANCES_FOR_COUNTRY_OUTDOOR_RECORDS:
			raise Http404(f'Мы не считаем рекорды для дистанции {distance} и типа покрытия {results_util.SURFACE_TYPES[surface_type][1]}')
	return country, gender, age_group, distance, surface_type

def age_group_details(request, country_id=None, gender_code=None, age=None, distance_code=None, surface_code=None):
	if request.method == 'POST':
		distance_id, surface_type = request.POST['distance_surface'].split('_')
		return redirect('results:age_group_record_details',
			country_id=request.POST['country_id'],
			gender_code=results_util.GENDER_CODES[results_util.int_safe(request.POST['gender'])],
			age=request.POST['age'],
			distance_code=results_util.DISTANCE_CODES[results_util.int_safe(distance_id)],
			surface_code=results_util.SURFACE_CODES[results_util.int_safe(surface_type)],
		)

	country = get_object_or_404(models.Country, pk=country_id, pk__in=results_util.THREE_COUNTRY_IDS)
	gender = results_util.GENDER_CODES_INV.get(gender_code)
	if not gender:
		raise Http404()
	age_min = None if (age == 0) else age
	age_group = get_object_or_404(models.Record_age_group, age_min=age_min)

	distance_id = results_util.DISTANCE_CODES_INV.get(distance_code)
	surface_type = results_util.SURFACE_CODES_INV.get(surface_code)
	if surface_type == results_util.SURFACE_INDOOR:
		if distance_id not in results_util.DISTANCES_FOR_COUNTRY_INDOOR_RECORDS:
			return redirect('results:age_group_records')
	else:
		if (distance_id, surface_type) not in results_util.DISTANCES_FOR_COUNTRY_OUTDOOR_RECORDS:
			return redirect('results:age_group_records')
	distance = get_object_or_404(models.Distance, pk=distance_id)

	context = user_edit_vars(request.user)
	context['country'] = country
	context['form'] = forms.AgeGroupRecordForm(is_admin=context['is_admin'], initial={
			'country_id': country.id,
			'distance_id': distance.id,
			'surface_type': surface_type,
			'gender': gender,
			'age': age_group.age_min if age_group.age_min else 0,
		})

	all_countries_records = age_group.record_result_set.filter(gender=gender, distance=distance, surface_type=surface_type).select_related(
		'result__race__event__series__city__region__country', 'result__race__event__city__region__country', 'result__race__distance',
		'result__runner__user__user_profile', 'race__event__series', 'result__runner__city__region__country', 'result__result_on_strava', 'protocol', 'session')
	records = all_countries_records.filter(country=country)
	context['results_best_overall'] = records.exclude(cur_place=None).order_by('cur_place')
	context['old_records'] = records.filter(was_record_ever=True).exclude(cur_place=1).order_by('-date')
	context['world_record'] = all_countries_records.filter(is_world_record=True).first()
	context['europe_record'] = all_countries_records.filter(is_europe_record=True).first()

	if (distance.distance_type == models.TYPE_METERS) and (distance.length <= results_util.MAX_DISTANCE_FOR_ELECTRONIC_RECORDS):
		context['electronic_records'] = records.exclude(cur_place_electronic=None).order_by('cur_place_electronic')

	ordering = '-result__result' if (distance.distance_type in models.TYPES_MINUTES) else 'result__result'
	context['results_not_for_records'] = age_group.result_not_for_age_group_record_set.filter(
			country=country, gender=gender, distance=distance, surface_type=surface_type).select_related(
		'result__race__event__series__city__region__country', 'result__race__event__city__region__country', 'result__race__distance',
		'result__runner__user__user_profile', 'result__runner__city__region__country', 'result__result_on_strava').order_by(ordering)

	if context['is_admin']:
		context['other_results'] = records.filter(was_record_ever=False, cur_place=None, cur_place_electronic=None, ignore_for_country_records=False).order_by(ordering)
		links_kwargs={'country_id': country_id, 'gender_code': gender_code, 'age': age, 'distance_code': distance_code, 'surface_code': surface_code}
		context['update_records_link'] = reverse('editor:update_age_group_records', kwargs=links_kwargs)
		context['generate_records_link'] = reverse('editor:generate_better_age_group_results_for_tuple', kwargs=links_kwargs)
		context['delete_other_saved_results_link'] = reverse('editor:delete_other_saved_results', kwargs=links_kwargs)
		context['add_record_link'] = reverse('editor:age_group_record_add', kwargs=links_kwargs)
		context['add_comment_link'] = reverse('editor:age_group_add_comment', kwargs=links_kwargs)

		ordering = '-result__result' if (distance.distance_type in models.TYPES_MINUTES) else 'result__result'
		context['bad_results'] = set(country.result_not_for_age_group_record_set.filter(age_group=age_group).values_list('pk', flat=True))
		context['candidate_results'] = age_group.possible_record_result_set.filter(country=country, gender=gender, distance=distance,
			surface_type=surface_type).select_related('result__race__event__series__city__region__country',
			'result__race__event__city__region__country','result__runner__user__user_profile', 'result__runner__city__region__country',
			'result__result_on_strava', 'result__category_size').exclude(result_id__in=context['bad_results']).order_by(ordering)

	context['page_title_first'] = f'Лучшие результаты в истории {country.prep_case}'
	context['page_title_second'] = f' {age_group.get_full_name_in_prep_case(gender)} на дистанции {distance.get_name(surface_type)} ' \
			+ ('в помещении' if (surface_type == results_util.SURFACE_INDOOR) else f'({results_util.SURFACE_TYPES_DICT[surface_type]})')
	context['page_title'] = context['page_title_first'] + context['page_title_second']
	context['main_records_link_name'] = 'results:age_group_records'
	context['n_appropriate_results'] = models.Record_candidate_results_number.objects.filter(
		country=country, gender=gender, age_group=age_group, distance=distance, surface_type=surface_type).first()
	context['comments'] = models.Record_category_comment.objects.filter(
		country=country, gender=gender, age_group=age_group, distance=distance, surface_type=surface_type).order_by('pk')

	if context['is_admin'] and (country.id == 'RU'):
		context['commission_session'] = models.Masters_commission_session.get_current_session()
	return render(request, 'age_group_records/age_group_details.html', context)

def ultra_record_details(request, country_id=None, gender_code=None, distance_code=None):
	if request.method == 'POST':
		return redirect('results:ultra_record_details',
			country_id=request.POST['country_id'],
			gender_code=results_util.GENDER_CODES[results_util.int_safe(request.POST['gender'])],
			distance_code=results_util.DISTANCE_CODES[results_util.int_safe(request.POST['distance_id'])],
		)

	country = get_object_or_404(models.Country, pk=country_id, pk__in=results_util.THREE_COUNTRY_IDS)
	gender = results_util.GENDER_CODES_INV.get(gender_code)
	if not gender:
		raise Http404()
	distance_id = results_util.DISTANCE_CODES_INV.get(distance_code)
	if distance_id not in results_util.DISTANCES_FOR_COUNTRY_ULTRA_RECORDS:
		return redirect('results:age_group_records')
	distance = get_object_or_404(models.Distance, pk=distance_id)

	context = user_edit_vars(request.user)
	context['country'] = country
	context['form'] = forms.UltraRecordsForDistanceForm(initial={
			'country_id': country.id,
			'distance_id': distance.id,
			'gender': gender,
		})

	records = models.Record_result.objects.filter(country=country, gender=gender, distance=distance).select_related(
		'result__race__event__series__city__region__country', 'result__race__event__city__region__country', 'result__race__distance',
		'result__runner__user__user_profile', 'race__event__series', 'result__runner__city__region__country', 'result__result_on_strava')
	context['results_best_overall'] = records.exclude(cur_place=None).order_by('cur_place')
	context['old_records'] = records.filter(was_record_ever=True).exclude(cur_place=1).order_by('-date')

	ordering = '-result__result' if (distance.distance_type in models.TYPES_MINUTES) else 'result__result'
	results_not_for_records = models.Result_not_for_age_group_record.objects.filter(country=country, gender=gender, distance=distance)
	context['results_not_for_records'] = results_not_for_records.select_related(
		'result__race__event__series__city__region__country', 'result__race__event__city__region__country', 'result__race__distance',
		'result__runner__user__user_profile', 'result__runner__city__region__country', 'result__result_on_strava').order_by(ordering)

	if context['is_admin']:
		context['other_results'] = records.filter(was_record_ever=False, cur_place=None, cur_place_electronic=None).order_by(ordering)
		links_kwargs = {
			'country_id': country_id,
			'gender_code': gender_code,
			'age': 0,
			'distance_code': distance_code,
			'surface_code': results_util.SURFACE_CODES[results_util.SURFACE_DEFAULT],
		}
		context['update_records_link'] = reverse('editor:update_age_group_records', kwargs=links_kwargs)
		context['generate_records_link'] = reverse('editor:generate_better_age_group_results_for_tuple', kwargs=links_kwargs)
		context['add_record_link'] = reverse('editor:age_group_record_add', kwargs=links_kwargs)
		context['add_comment_link'] = reverse('editor:age_group_add_comment', kwargs=links_kwargs)

		ordering = '-result__result' if (distance.distance_type in models.TYPES_MINUTES) else 'result__result'
		results_not_for_records_ids = set(results_not_for_records.values_list('result_id', flat=True))
		context['candidate_results'] = models.Possible_record_result.objects.filter(country=country, gender=gender, distance=distance).select_related(
			'result__race__event__series__city__region__country',
			'result__race__event__city__region__country','result__runner__user__user_profile', 'result__runner__city__region__country',
			'result__result_on_strava', 'result__category_size').exclude(result_id__in=results_not_for_records_ids).order_by(ordering)

	context['page_title_first'] = 'Лучшие результаты в истории {}'.format(country.prep_case)
	context['page_title_second'] = f' на дистанции {distance.name}'
	context['page_title'] = context['page_title_first'] + context['page_title_second']
	context['page_subtitle'] = 'Проект сайта «ПроБЕГ»'
	if country.id == 'RU':
		context['page_subtitle'] += ' и Игоря Агишева'
	context['main_records_link_name'] = 'results:ultra_records'
	context['n_appropriate_results'] = models.Record_candidate_results_number.objects.filter(
		country=country, gender=gender, distance=distance).first()
	context['comments'] = models.Record_category_comment.objects.filter(country=country, gender=gender, distance=distance).order_by('pk')
	context['show_runner_places'] = context['show_runner_places_column'] = True
	return render(request, 'age_group_records/age_group_details.html', context)

def records_for_distance(request, country_id, distance_code, surface_code):
	if request.method == 'POST':
		distance_id, surface_type = request.POST['distance_surface'].split('_')
		return redirect('results:age_group_records_for_distance',
			country_id=request.POST['country_id'],
			distance_code=results_util.DISTANCE_CODES[results_util.int_safe(distance_id)],
			surface_code=results_util.SURFACE_CODES[results_util.int_safe(surface_type)],
		)

	country = get_object_or_404(models.Country, pk=country_id, pk__in=results_util.THREE_COUNTRY_IDS)
	distance_id = results_util.DISTANCE_CODES_INV.get(distance_code)
	surface_type = results_util.SURFACE_CODES_INV.get(surface_code)
	if surface_type == results_util.SURFACE_INDOOR:
		if distance_id not in results_util.DISTANCES_FOR_COUNTRY_INDOOR_RECORDS:
			return redirect('results:age_group_records')
	else:
		if (distance_id, surface_type) not in results_util.DISTANCES_FOR_COUNTRY_OUTDOOR_RECORDS:
			return redirect('results:age_group_records')
	distance = get_object_or_404(models.Distance, pk=distance_id)

	context = user_edit_vars(request.user)
	context['page_title_first'] = f'Рекорды в возрастных группах в {country.prep_case}'
	context['page_title_second'] = f': {distance.get_name(surface_type)} ({results_util.SURFACE_TYPES_DICT[surface_type]})'
	context['page_title'] = context['page_title_first'] + context['page_title_second']
	context['country'] = country

	context['form'] = forms.AgeGroupRecordsForDistanceForm(initial={
			'country_id': country.id,
			'distance_id': distance.id,
			'surface_type': surface_type,
		})

	data = OrderedDict()
	for age_group in models.Record_age_group.objects.all():
		data[age_group] = {}

	records = country.record_result_set.filter(distance=distance, surface_type=surface_type, cur_place=1).select_related(
		'result__race__event__series__city__region__country', 'result__race__event__city__region__country',
		'result__runner__user__user_profile', 'result__runner__city__region__country').order_by('age_group__age_min')
	for record in records:
		data[record.age_group][record.gender] = record
	context['records_by_age_group'] = data
	return render(request, 'age_group_records/records_for_distance.html', context)

def records_for_marathon(request, gender_code):
	gender = results_util.GENDER_CODES_INV.get(gender_code)
	if not gender:
		raise Http404()
	country = models.Country.objects.get(pk='RU')
	distance = models.Distance.objects.get(pk=results_util.DIST_MARATHON_ID)
	is_indoor = False

	context = user_edit_vars(request.user)
	context['page_title'] = 'Рекорды России на марафоне в возрастных группах. {}'.format(
		'Мужчины' if gender == results_util.GENDER_MALE else 'Женщины')

	data = OrderedDict()
	records = country.record_result_set.filter(distance=distance, is_indoor=is_indoor, gender=gender, cur_place=1).exclude(
		age_group__age_group_type=models.RECORD_AGE_GROUP_TYPE_YOUNG).select_related(
		'result__race__event__series__city__region__country', 'result__race__event__city__region__country',
		'result__runner__user__user_profile', 'result__runner__city__region__country').order_by('age_group__age_min')
	for record in records:
		data[record.age_group] = record
	context['records_by_age_group'] = data
	context['gender'] = gender
	context['today'] = results_util.date2str(datetime.date.today())
	return render(request, 'age_group_records/records_for_marathon.html', context)

def age_group_records_by_month(request, country_id, year=None, month=None):
	if request.method == 'POST':
		return redirect('results:age_group_records_by_month',
			country_id=country_id,
			year=request.POST['year'],
			month=request.POST['month'],
		)

	country = get_object_or_404(models.Country, pk=country_id.upper(), pk__in=results_util.THREE_COUNTRY_IDS)
	today = datetime.date.today()
	if (not year) or not (1992 <= year <= today.year):
		year = today.year
	if (not month):
		month = today.month

	context = {}
	context['country'] = country
	context['records'] = models.Record_result.objects.exclude(cur_place=None, cur_place_electronic=None, was_record_ever=False).filter(
		date__year=year, date__month=month, is_date_known=True).select_related(
		'country', 'runner__user__user_profile', 'race__distance', 'age_group').order_by(
		'race__event__start_date',
		'race__distance__distance_type', '-race__distance__length', 'runner__lname', 'runner__fname')
	context['page_title_first'] = 'Лучшие результаты в истории {}'.format(country.prep_case)
	context['page_title_second'] = ', показанные в {} {} года'.format(results_util.months_dative_case[month], year)
	context['page_title'] = context['page_title_first'] + context['page_title_second']
	context['form'] = forms.MonthYearForm(initial={'month': month, 'year': year})
	return render(request, 'age_group_records/by_month.html', context)

def get_age(form: forms_age_groups.AgeGroupResultForm, event_date: datetime.date) -> int:
	birthday = None
	runner = form.cleaned_data.get('runner')
	if runner:
		return results_util.get_age_on_date(event_date, runner.birthday)
	return results_util.get_age_on_date(event_date, form.cleaned_data.get('birthday'))

def results_with_age_group_coefs(request):
	N_EXTRA_ROWS = 20
	FormsetResult = formset_factory(form=forms_age_groups.AgeGroupResultForm, extra=N_EXTRA_ROWS)
	context = {}
	context['page_title'] = 'Результаты с учётом возрастного коэффициента'
	if 'btnCalcCoefs' not in request.POST:
		context['formDayDistance'] = forms_age_groups.DistanceDayForm()
		context['formsetResult'] = FormsetResult()
		return render(request, 'age_group_records/results_with_age_group_coefs.html', context)
	formDayDistance = forms_age_groups.DistanceDayForm(data=request.POST)
	if not formDayDistance.is_valid():
		context['formDayDistance'] = formDayDistance
		context['formsetResult'] = FormsetResult(data=request.POST)
		return render(request, 'age_group_records/results_with_age_group_coefs.html', context)
	formsetResult = FormsetResult(request.POST,
		form_kwargs={
			'event_date': formDayDistance.cleaned_data['event_date'],
			'gender': formDayDistance.cleaned_data['gender'],
			'distance': formDayDistance.cleaned_data['distance'],
			'request': request,
		})
	if not formsetResult.is_valid():
		context['formDayDistance'] = formDayDistance
		context['formsetResult'] = formsetResult
		return render(request, 'age_group_records/results_with_age_group_coefs.html', context)
	initial = []
	for form in formsetResult:
		runner = form.cleaned_data.get('runner')
		result_str = form.cleaned_data.get('result')
		vals = {
			'runner': runner.id if runner else None,
			'runner_name': form.cleaned_data.get('runner_name'),
			'birthday': form.cleaned_data.get('birthday'),
			'result': models.centisecs2time(result_str, show_zero_hundredths=True) if result_str else None,
			'age': form.cleaned_data.get('age'),
			'coefficient': form.cleaned_data.get('coefficient'),
			'result_normed': form.cleaned_data.get('result_normed'),
		}
		if any(vals.values()):
			initial.append(vals)
	context['formDayDistance'] = formDayDistance
	context['formsetResult'] = FormsetResult(initial=initial, form_kwargs={'request': request})
	return render(request, 'age_group_records/results_with_age_group_coefs.html', context)

def check_record_result(record: models.Record_result) -> Optional[str]:
	if record.country_id != 'RU':
		return f'страна {record.country}, а должна быть Россия'
	if record.age_group.age_group_type != models.RECORD_AGE_GROUP_TYPE_SENIOR:
		return f'возрастная группа — {record.age_group}, а должна быть ветеранская группа'
	if record.runner is None:
		return 'к рекорду не привязан бегун'
	if not record.runner.birthday:
		return f'у бегуна {record.runner} неизвестен год рождения'
	if record.result is None:
		return 'к рекорду не привязан результат'
	if (record.protocol is None) and not record.comment:
		return 'к рекорду не привязан протокол и не указан комментарий к результату'
	if record.protocol and record.protocol.url_source and (not record.protocol.upload) and (not record.protocol.is_on_our_google_drive):
		return f'у протокола {record.protocol.url_source} забега {results_util.SITE_URL}{record.race.get_absolute_url()} не сохранена копия'
	if (record.cur_place != 1) and (record.cur_place_electronic != 1):
		return 'результат — не лучший из известных нам'
	# if record.surface_type in (results_util.SURFACE_STADIUM, results_util.SURFACE_INDOOR) and not record.result.race.event.start_place:
	# 	return f'не указано место проведения забега {record.result.race.event.name} {results_util.SITE_URL}{record.result.race.get_absolute_url()}'
	return None

def current_records(record: models.Record_result, session_id: int) -> QuerySet:
	return models.Record_result.objects.filter(session_id__lt=session_id, age_group=record.age_group, country=record.country, distance=record.distance,
		 surface_type=record.surface_type, gender=record.gender, is_approved_record_now=True)

def commission_protocol(request, session_id: int):
	session = get_object_or_404(models.Masters_commission_session, pk=session_id)
	record_results = session.record_result_set.select_related(
			'age_group', 'distance', 'runner__user__user_profile', 'runner__city__region__country', 'result__race__distance').order_by(
			'surface_type', 'distance__distance_type', 'distance__length', 'gender', 'age_group__age_min', 'timing')
	context = {}
	context['record_results'] = [] # List of tuples: (record that we confirm now, previous record in the same group if any)
	for record_result in record_results:
		check_res = check_record_result(record_result)
		if check_res:
			context['error'] = f'{record_result.get_desc()}: {check_res}'
			break
		cur_records = current_records(record_result, session_id)
		if cur_records.count() > 1:
			context['error'] = f'{record_result.get_desc()}: больше одного текущего рекорда: {cur_records}'
			break
		context['record_results'].append((record_result, cur_records.first()))
	context['SITE_URL'] = results_util.SITE_URL
	context['session'] = session
	context['page_title'] = f'Протокол заседания № {session.get_number()} комиссии по рекордам России в беге среди ветеранов'
	context['participants'] = session.participants.all().order_by('lname', 'fname')
	return render(request, 'age_group_records/commission_protocol.html', context)
