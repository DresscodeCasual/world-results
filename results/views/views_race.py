from django.shortcuts import get_object_or_404, render, redirect
from django.contrib.auth.decorators import login_required
from django.db.models import Q, F, Sum, Count
from django.urls import reverse
from django.db.models.query import Prefetch
from django.contrib import messages
from django.http import Http404, QueryDict

import datetime
from typing import Any, List

from results import models, models_klb, forms, results_util
from results.views import views_common
from results.templatetags.results_extras import add_prefix
from editor import parse_weekly_events, runner_stat
from editor.views import views_klb
from starrating.utils import show_rating

def filterRacesByCity(races, conditions: List[str], city: models.City):
	races = races.filter(
		Q(event__city=city)
		| Q(event__city_finish=city)
		| (Q(event__city=None) & Q(event__series__city=city))
		| (Q(event__city=None) & Q(event__series__city_finish=city))
	)
	conditions.append(f'in {city.name} city')
	return races
def filterRacesByRegion(races, conditions: List[str], region: models.Region):
	races = races.filter(
		Q(event__city__region=region)
		| Q(event__city_finish__region=region)
		| (Q(event__city=None) & Q(event__series__city__region=region))
		| (Q(event__city=None) & Q(event__series__city_finish__region=region))
	)
	conditions.append(f'in {region.name} region')
	return races
def filterRacesByRegionGroup(races, conditions: List[str], regions: List[models.Region]):
	races = races.filter(
		Q(event__city__region__in=regions)
		| Q(event__city_finish__region__in=regions)
		| (Q(event__city=None) & Q(event__series__city__region__in=regions))
		| (Q(event__city=None) & Q(event__series__city_finish__region__in=regions))
	)
	delimiter = u' and ' if (len(regions) == 2) else ', '
	conditions.append('in regions ' + delimiter.join(region.name for region in regions))
	return races
def filterRacesByDistrict(races, conditions: List[str], district: models.District):
	region_ids = set(district.region_set.values_list('pk', flat=True))
	races = races.filter(
		Q(event__city__region_id__in=region_ids)
		| Q(event__city_finish__region_id__in=region_ids)
		| (Q(event__city=None) & Q(event__series__city__region_id__in=region_ids))
		| (Q(event__city=None) & Q(event__series__city_finish__region_id__in=region_ids))
	)
	conditions.append(f'in {district.prep_case} federal district')
	return races
def filterRacesByCountry(races, conditions: List[str], country: models.Country):
	races = races.filter(
		Q(event__city__region__country=country)
		| Q(event__city_finish__region__country=country)
		| (Q(event__city=None) & Q(event__series__city__region__country=country))
		| (Q(event__city=None) & Q(event__series__city_finish__region__country=country))
		| (Q(event__city=None) & Q(event__series__city=None) & Q(event__series__country=country))
	)
	conditions.append(f'in {country.name}')
	return races
def filterRacesByDateFrom(races, conditions: List[str], date_from: datetime.date):
	conditions.append('later or on ' + date_from.strftime('%d.%m.%Y'))
	return races.filter(Q(event__start_date__gte=date_from) | Q(event__finish_date__gte=date_from))
def filterRacesByDateTo(races, conditions: List[str], date_to: datetime.date):
	conditions.append('before or on ' + date_to.strftime('%d.%m.%Y'))
	return races.filter(event__start_date__lte=date_to)
def filterRacesByName(races, conditions: List[str], name: str):
	conditions.append(f'with «{name}» in its name')
	return races.filter(Q(event__series__name__icontains=name) | Q(event__series__name_orig__icontains=name) | Q(event__name__icontains=name))
def filterRacesByDateRegion(races, date_region, today: datetime.date):
	list_title = 'Events'
	if date_region == forms.DATE_REGION_FUTURE:
		races = races.filter(Q(event__start_date__gte=today) | Q(event__finish_date__gte=today))
		list_title = "Events Calendar"
	elif date_region == forms.DATE_REGION_PAST:
		races = races.filter(event__start_date__lte=today)
		list_title = "Completed Events"
	elif date_region == forms.DATE_REGION_NEXT_WEEK:
		races = races.filter(Q(event__start_date__gte=today) | Q(event__finish_date__gte=today), event__start_date__lte=today + datetime.timedelta(days=7))
		list_title = f'Events for the next week ({results_util.dates2str(today, today + datetime.timedelta(days=7))})'
	elif date_region == forms.DATE_REGION_NEXT_MONTH:
		races = races.filter(Q(event__start_date__gte=today) | Q(event__finish_date__gte=today), event__start_date__lte=today + datetime.timedelta(days=31))
		list_title = f'Events for the next month ({results_util.dates2str(today, today + datetime.timedelta(days=31))})'
	return races, list_title
def filterRacesByDistance(races, conditions: List[str], distance: models.Distance):
	conditions.append(f'for {distance}')
	return races.filter(distance=distance)
def filterRacesByDistanceFrom(races, conditions: List[str], distance_from: float):
	distance_from = int(distance_from * 1000)
	conditions.append(f'shorter or equal to {distance_from} meters')
	return races.filter(distance__distance_type=models.TYPE_METERS, distance__length__gte=distance_from)
def filterRacesByDistanceTo(races, conditions: List[str], distance_to: float):
	distance_to = int(distance_to * 1000)
	conditions.append(f'longer or equal to {distance_to} meters')
	return races.filter(distance__distance_type=models.TYPE_METERS, distance__length__lte=distance_to)
def excludeParkrunEvents(races, conditions: List[str]):
	conditions.append('without weekly parkrun-like events')
	return races.exclude(event__series__is_weekly=True)
def filterRacesWithLoadedResults(races, conditions: List[str]):
	conditions.append('with loaded results')
	return races.filter(load_status__in=(models.RESULTS_LOADED, models.RESULTS_SOME_OFFICIAL))

def races_default(request, full=False):
	context = views_common.user_edit_vars(request.user)
	context['page_title'] = 'Future events that we know about'
	context['calendar_template'] = 'generated/default_calendar{}.html'.format('_full' if full else '')

	initial = {}
	user = request.user
	if user.is_authenticated and hasattr(user, 'user_profile') and user.user_profile.hide_parkruns_in_calendar:
		initial['hide_parkruns'] = True
	context['form'] = forms.EventForm(initial=initial)
	return render(request, 'results/races_default.html', context)

# Is it true that there's no valuable values to filter the calendar?
def empty_enough(get_dict: QueryDict) -> bool:
	my_dict = get_dict.dict()
	for key in ('ysclid', 'fbclid', 'utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'utm_term'):
		my_dict.pop(key, None)
	return len(my_dict) == 0

def races(request, city_id=None, region_id=None, country_id=None, distance_id=None, date_region=None, race_name=None, region_group=None, view=0):
	if (request.method == "GET") and empty_enough(request.GET) and (city_id is None) and (region_id is None) and (country_id is None) \
			and (distance_id is None) and (date_region is None) and (race_name is None) and (region_group is None):
		return races_default(request)
	user = request.user
	context = views_common.user_edit_vars(user)
	list_title = "Все забеги"
	today = datetime.date.today()
	conditions = []
	form_params = {}
	initial = {}
	form = None
	use_default_date_region = True
	form_was_submitted = ('btnSearchSubmit' in request.GET) or ('page' in request.GET)

	if region_group:
		form_params['regions'] = set()
		for reg_id in region_group.split(','):
			form_params['regions'].add(get_object_or_404(models.Region, pk=reg_id))
		if form_params['regions']:
			initial['region'] = list(form_params['regions'])[0]
		use_default_date_region = False
	if city_id:
		form_params['city'] = get_object_or_404(models.City, pk=city_id)
		context['city_wiki'] = form_params['city'].url_wiki
		context['city'] = form_params['city']
		if form_params['city'].region.is_active:
			initial['region'] = form_params['city'].region
		else:
			initial['country'] = form_params['city'].region.country
		use_default_date_region = False
		form_params['date_region'] = forms.DATE_REGION_FUTURE
		initial['date_region'] = forms.DATE_REGION_FUTURE
	if region_id:
		form_params['region'] = get_object_or_404(models.Region, pk=region_id)
		initial['region'] = form_params['region']
		use_default_date_region = False
	if country_id:
		form_params['country'] = get_object_or_404(models.Country, pk=country_id)
		initial['country'] = form_params['country'].id
	if distance_id:
		form_params['distance'] = get_object_or_404(models.Distance, pk=distance_id)
		initial['distance_from'] = form_params['distance'].length / 1000.
		initial['distance_to'] = form_params['distance'].length / 1000.
	if date_region:
		form_params['date_region'] = results_util.int_safe(date_region)
		initial['date_region'] = form_params['date_region']
	if race_name:
		use_default_date_region = False
		form_params['race_name'] = race_name.strip()
		initial['race_name'] = form_params['race_name']
		form_params['date_region'] = forms.DATE_REGION_ALL
		initial['date_region'] = forms.DATE_REGION_ALL
	if ('hide_parkruns' in request.GET):
		form_params['hide_parkruns'] = True
		initial['hide_parkruns'] = True
	elif (not form_was_submitted) and user.is_authenticated and hasattr(user, 'user_profile') and user.user_profile.hide_parkruns_in_calendar:
		form_params['hide_parkruns'] = True
		initial['hide_parkruns'] = True
	if form_was_submitted:
		use_default_date_region = False
		form = forms.EventForm(request.GET)
		if form.is_valid():
			form_params = {key: val for (key, val) in list(form.cleaned_data.items()) if val}
			context['hide_parkruns'] = form_params.get('hide_parkruns')
	if use_default_date_region:
		form_params['date_region'] = forms.DATE_REGION_DEFAULT
		initial['date_region'] = forms.DATE_REGION_DEFAULT

	races = models.Race.objects.all()
	if not context['is_admin']:
		races = races.filter(event__invisible=False)

	if 'city' in form_params:
		context['city'] = form_params['city']
		races = filterRacesByCity(races, conditions, form_params['city'])
	elif 'regions' in form_params:
		races = filterRacesByRegionGroup(races, conditions, form_params['regions'])
	elif 'region' in form_params:
		races = filterRacesByRegion(races, conditions, form_params['region'])
	elif 'district' in form_params:
		races = filterRacesByDistrict(races, conditions, form_params['district'])
	elif 'country' in form_params:
		races = filterRacesByCountry(races, conditions, form_params['country'])
	if 'date_region' in form_params:
		races, list_title = filterRacesByDateRegion(races, results_util.int_safe(form_params['date_region']), today)
	if 'race_name' in form_params:
		races = filterRacesByName(races, conditions, form_params['race_name'])
	if 'date_from' in form_params:
		races = filterRacesByDateFrom(races, conditions, form_params['date_from'])
	if 'date_to' in form_params:
		races = filterRacesByDateTo(races, conditions, form_params['date_to'])
	if 'distance' in form_params:
		races = filterRacesByDistance(races, conditions, form_params['distance'])
	if 'distance_from' in form_params:
		races = filterRacesByDistanceFrom(races, conditions, form_params['distance_from'])
	if 'distance_to' in form_params:
		races = filterRacesByDistanceTo(races, conditions, form_params['distance_to'])
	if 'hide_parkruns' in form_params:
		races = excludeParkrunEvents(races, conditions)
	if 'only_with_results' in form_params:
		races = filterRacesWithLoadedResults(races, conditions)

	event_ids = set(races.values_list('event__id', flat=True))
	events = models.Event.objects.filter(id__in=event_ids)
	
	events = views_common.add_related_to_events(events)

	if ( results_util.int_safe(form_params.get('date_region', forms.DATE_REGION_DEFAULT))
			in [forms.DATE_REGION_FUTURE, forms.DATE_REGION_NEXT_WEEK, forms.DATE_REGION_NEXT_MONTH] ) \
			or ( ('date_from' in form_params) and (form_params['date_from'] >= today)):
		events = events.order_by('start_date', 'name')
		context['show_n_finished'] = False
	else:
		events = events.order_by('-start_date', 'name')
		context['show_n_finished'] = True

	if form is None:
		form = forms.EventForm(initial=initial)
	context['list_title'] = list_title + " " + ", ".join(conditions)
	context['form'] = form
	context['page_title'] = context['list_title']
	return views_common.paginate_and_render(request, 'results/races2.html' if view else 'results/races.html', context, events)

def future_trails(request):
	context = views_common.user_edit_vars(request.user)
	context['page_title'] = 'Календарь кроссов, трейлов, горного бега'
	events = models.Event.objects.filter(
		Q(surface_type__in=models.SURFACES_UNEVEN) | Q(surface_type=models.SURFACE_DEFAULT, series__surface_type__in=models.SURFACES_UNEVEN),
		start_date__gte=datetime.date.today())

	if not context['is_admin']:
		events = events.filter(invisible=False)
	context['events'] = views_common.add_related_to_events(events)
	return render(request, 'results/future_races.html', context)

def parkruns_and_similar(request):
	context = views_common.user_edit_vars(request.user)
	context['page_title'] = 'Календарь паркранов и других еженедельных забегов на 5 км'
	events = models.Event.objects.filter(series__is_weekly=True, start_date__gte=datetime.date.today())

	if not context['is_admin']:
		events = events.filter(invisible=False)
	context['events'] = views_common.add_related_to_events(events)
	return render(request, 'results/future_races.html', context)

def events_for_masters(request):
	context = views_common.user_edit_vars(request.user)
	context['page_title'] = 'Календарь соревнований среди ветеранов'
	events = models.Event.objects.filter(series__is_for_masters=True, start_date__gte=datetime.date.today())
	if not context['is_admin']:
		events = events.filter(invisible=False)
	context['events'] = views_common.add_related_to_events(events)
	return render(request, 'results/future_races.html', context)

def events_triathlon(request):
	context = views_common.user_edit_vars(request.user)
	context['page_title'] = 'Календарь триатлонов и подобных соревнований'
	events = models.Event.objects.filter(series__series_type=models.SERIES_TYPE_TRIATHLON, start_date__gte=datetime.date.today())
	if not context['is_admin']:
		events = events.filter(invisible=False)
	context['events'] = views_common.add_related_to_events(events)
	return render(request, 'results/future_races.html', context)

def add_races_annotations(races):
	return races.exclude(distance__distance_type=models.TYPE_TRASH).select_related('distance', 'distance_real').order_by(
		'distance__distance_type', '-distance__length', 'precise_name')

def event_races_for_context(event):
	return add_races_annotations(event.race_set)

def filter_results_by_name(race, results, name):
	if race.distance.distance_type not in models.TYPES_MINUTES:
		result = models.string2centiseconds(name)
		if result > 0:
			return results.filter(result__gte=result)
	return results.filter(Q(fname__icontains=name) | Q(lname__icontains=name) | Q(club_name__icontains=name) | Q(city_raw__icontains=name))

def claim_results(request, race, klb_status):
	user = request.user
	results_claimed = 0
	results_claimed_for_klb = 0
	runners_for_user = user.user_profile.get_runners_to_add_results(race, race_is_for_klb = (klb_status == models.KLB_STATUS_OK))
	runners_touched = set()
	race_date = race.start_date if race.start_date else race.event.start_date

	# For results that aren't connected with any runner yet
	for key, val in list(request.POST.items()):
		val = results_util.int_safe(val)
		if key.startswith("for_result_") and val:
			result_id = results_util.int_safe(key[len("for_result_"):])
			result = race.result_set.filter(pk=result_id).first()
			if result is None:
				messages.warning(request, 'Результат с id {} не найден. Пропускаем'.format(result_id))
				continue
			if result.runner:
				runner = result.runner
				messages.warning(request, 'Результат {} уже привязан к участнику забегов {}. Пропускаем'.format(
					result, runner.get_name_and_id()))
				continue

			runner = models.Runner.objects.filter(pk=val).first()
			if runner is None:
				messages.warning(request, 'Участник забегов с id {} не найден. Пропускаем'.format(val))
				continue

			if runner not in runners_for_user:
				messages.warning(request, 'У Вас нет прав на добавление результата участнику {}'.format(runner.get_name_and_id()))
				continue

			if runner in runners_touched:
				messages.warning(request, 'Мы только что уже привязали один результат бегуну {}. Пропускаем '.format(runner.get_name_and_id()))
				continue

			if runners_for_user[runner]['is_already_in_race']:
				messages.warning(request, 'У бегуна {} уже есть результат на этой дистанции забега. Пропускаем '.format(
					runner.get_name_and_id()))
				continue

			is_for_klb = ('for_klb_{}'.format(result_id) in request.POST)
			participant = None
			if is_for_klb:
				if klb_status != models.KLB_STATUS_OK:
					messages.warning(request, 'Эта дистанция не может быть засчитана в КЛБМатч: {}'.format(
						models.KLB_STATUSES[klb_status][1]))
					is_for_klb = False
				elif not result.is_ok_for_klb():
					messages.warning(request, 'Результат {} слишком мал для КЛБМатча'.format(result))
					is_for_klb = False
				elif not hasattr(runner, 'klb_person'):
					messages.warning(request, '{} не участвует в КЛБМатче. На модерацию в матч результат не отправляем'.format(
						runner.get_name_and_id()))
					is_for_klb = False
				elif not runners_for_user[runner]['is_in_klb']:
					messages.warning(request, 'У Вас нет прав на добавление результата бегуну {} в КЛБМатч'.format(runner.get_name_and_id()))
					is_for_klb = False
				else:
					participant = runner.klb_person.klb_participant_set.filter(year=models_klb.first_match_year(race_date.year)).first()
					if participant is None:
						messages.warning(request, '{} не участвует в КЛБМатче. На модерацию в матч результат не отправляем'.format(
							runner.get_name_and_id()))
						is_for_klb = False
					elif participant.date_registered and (participant.date_registered > race_date):
						messages.warning(request, 'Участник {} был включён в команду только {}. Его результат не будет учтён в КЛБМатче'.format(
							runner.name(), participant.date_registered.strftime('%d.%m.%Y')))
						is_for_klb = False
					elif participant.date_removed and (participant.date_removed < race_date):
						messages.warning(request, 'Участник {} был исключён из команды уже {}. Его результат не будет учтён в КЛБМатче'.format(
							runner.name(), participant.date_removed.strftime('%d.%m.%Y')))
						is_for_klb = False
			res, message = result.claim_for_runner(user, runner, comment='Массовая привязка на странице забега',
				is_for_klb=is_for_klb and not models.is_admin(user))
			if res:
				results_claimed += 1
				if is_for_klb:
					results_claimed_for_klb += 1
					if models.is_admin(user):
						views_klb.create_klb_result(result, runner.klb_person, user, comment='Массовая привязка на странице забега',
							participant=participant)
				runners_touched.add(runner)
			else:
				messages.warning(request, 'Результат {} участнику {} не засчитан. Причина: {}'.format(
					str(result), runner.name(), message))

	# For results that are connected to a runner, a team member can send to moderation for KLBMatch
	if klb_status == models.KLB_STATUS_OK:
		for key in list(request.POST.keys()):
			if key.startswith("just_for_klb_"):
				result_id = results_util.int_safe(key[len("just_for_klb_"):])
				result = race.result_set.filter(pk=result_id).first()
				if result is None:
					messages.warning(request, f'Результат с id {result_id} не найден. Пропускаем')
					continue
				runner = result.runner
				if not runner:
					messages.warning(request, f'Результат {result} не привязан ни к какому участнику забегов. Пропускаем')
					continue
				if not runners_for_user[runner]['good_to_add_to_klb']:
					if not runners_for_user[runner]['is_in_klb']:
						messages.warning(request, f'Результат {result} бегуна {runner} не может быть посчитан в КЛБМатч — человек не был участником КЛБМатча в день забега')
					else:
						messages.warning(request, f'Результат {result} бегуна {runner} не может быть посчитан в КЛБМатч')
					continue
				results_claimed_for_klb += 1
				if models.is_admin(user):
					participant = runner.klb_person.klb_participant_set.get(year=models_klb.first_match_year(race_date.year))
					views_klb.create_klb_result(result, runner.klb_person, user, comment='Массовая привязка на странице забега', participant=participant)
				else:
					models.log_obj_create(user, race.event, models.ACTION_RESULT_UPDATE, field_list=[],
						child_object=result, comment='Отправка уже привязанного результата на модерацию в КЛБМатч', is_for_klb=True)

	runner_stat.update_runners_and_users_stat(runners_touched)
	if results_claimed:
		messages.success(request, 'Засчитано результатов: {}'.format(results_claimed))
		race.fill_winners_info()
	if results_claimed_for_klb:
		messages.success(request, f'{results_claimed_for_klb} результат{results_util.ending(results_claimed_for_klb, 1)}'
			+ f' отправлен{results_util.ending(results_claimed_for_klb, 17)} на модерацию в КЛБМатч')

def constants_for_event_context(user, event):
	context = {}
	context['series'] = event.series
	context['event'] = event
	context['races'] = event_races_for_context(event)
	context['has_races_with_and_wo_results'] = event.race_set.filter(load_status=models.RESULTS_LOADED).exists() \
		and event.race_set.filter(load_status=models.RESULTS_NOT_LOADED).exists()
	context['can_add_results_to_others'] = user.is_authenticated and hasattr(user, 'user_profile') and user.user_profile.can_add_results_to_others()
	context['n_races'] = event.race_set.count()
	return context

TAB_DEFAULT = 0
TAB_EDITOR = 1
TAB_UNOFFICIAL = 2
TAB_ADD_TO_CLUB = 3
TAB_KLB = 4
TAB_AGE_GROUP_RECORDS = 5
def constants_for_race_context(user, event):
	context = constants_for_event_context(user, event)
	context['TAB_DEFAULT'] = TAB_DEFAULT
	context['TAB_EDITOR'] = TAB_EDITOR
	context['TAB_UNOFFICIAL'] = TAB_UNOFFICIAL
	context['TAB_ADD_TO_CLUB'] = TAB_ADD_TO_CLUB
	context['TAB_KLB'] = TAB_KLB
	context['TAB_AGE_GROUP_RECORDS'] = TAB_AGE_GROUP_RECORDS
	context['RESULTS_SOME_OFFICIAL'] = models.RESULTS_SOME_OFFICIAL
	context['RESULTS_SOME_OR_ALL_OFFICIAL'] = models.RESULTS_SOME_OR_ALL_OFFICIAL
	return context

def race_details(request, race_id=None, tab_editor=False, tab_unofficial=False, tab_add_to_club=False):
	race = get_object_or_404(models.Race, pk=race_id)
	event = race.event
	series = event.series
	user = request.user

	context: dict[str, Any] = views_common.user_edit_vars(user, series=series)
	if event.invisible and not (context['is_admin'] or context['is_editor']):
		raise Http404()

	request_params = request.POST if request.method == 'POST' else request.GET
	context.update(constants_for_race_context(user, event))
	context['race'] = race

	tab = TAB_DEFAULT
	if tab_editor and (context['is_admin'] or context['is_editor']):
		tab = TAB_EDITOR
	elif tab_unofficial and (context['is_admin'] or context['is_editor']):
		tab = TAB_UNOFFICIAL
	elif tab_add_to_club:
		if not request.user.is_authenticated:
			messages.warning(request, 'Please log in to be able to add results to the members of your club')
			return redirect('probeg_auth:login')
		if not context['can_add_results_to_others']:
			messages.warning(request, 'You aren\'t a member of any club, thus you cannot connect results to others')
		else:
			tab = TAB_ADD_TO_CLUB

	# klb_status = race.get_klb_status()
	# context['race_is_ok_for_klb'] = (klb_status == models.KLB_STATUS_OK)

	context['page_title'] = f'{event}: результаты забега'

	page = None
	if (race.load_status in models.RESULTS_SOME_OR_ALL_OFFICIAL) and context['can_add_results_to_others'] \
			and ( ('frmResults_claim' in request_params) or ('frmResults_claim_nextpage' in request_params) ):
		claim_results(request, race, klb_status)
		if 'frmResults_claim_nextpage' in request_params:
			page = views_common.get_page_num(request) + 1

	results = race.get_official_results()
	context['race_has_results'] = results.exists() # When filters show 0 results, we need to show filters anyway!
	context['event_has_protocol'] = event.document_set.filter(document_type__in=models.DOC_PROTOCOL_TYPES).exists()
	context['tab'] = tab
	filtered_results = views_common.prefetch_record_results(results).select_related(
		'runner', 'user__user_profile', 'klb_result__klb_person', 'result_on_strava')
	if context['race_has_results'] and (tab != TAB_UNOFFICIAL):
		initial = {}
		if request_params.get('gender'):
			initial['gender'] = request_params['gender']
			filtered_results = filtered_results.filter(gender=request_params['gender'])
		if request_params.get('category'):
			initial['category'] = results_util.int_safe(request_params['category'])
			filtered_results = filtered_results.filter(category_size_id=initial['category'])
		if request_params.get('name'):
			name = request_params['name'].strip()
			initial['name'] = name
			filtered_results = filter_results_by_name(race, filtered_results, name)
		if request_params.get('with_strava'):
			initial['with_strava'] = True
			filtered_results = filtered_results.exclude(Q(user__user_profile__isnull=True) | Q(user__user_profile__strava_account=''), result_on_strava=None)
		context['resultFilterForm'] = forms.ResultFilterForm(race, initial=initial)
		context['can_claim_result'] = user.is_authenticated and not results.filter(user=user).exists()
	else:
		context['unofficial_results'] = race.get_unofficial_results()
		context['unoff_results_with_splits'] = views_common.get_results_with_splits_ids(context['unofficial_results'])

		context['year'] = event.start_date.year
		context['can_add_result'] = user.is_authenticated and not context['unofficial_results'].filter(user=user).exists()
		if context['is_admin']:
			context['frmClubAndNumber'] = forms.ClubAndNumberForm()
		elif user.is_authenticated:
			context['club_set'] = user.user_profile.get_club_set_to_add_results()
	if tab == TAB_ADD_TO_CLUB:
		context['runners'] = user.user_profile.get_runners_to_add_results(race, race_is_for_klb = (klb_status == models.KLB_STATUS_OK))
		context['user_is_female'] = user.user_profile.is_female()
		if klb_status == models.KLB_STATUS_OK:
			context['runners_good_for_klb'] = set([runner for runner, data in context['runners'].items() if data['is_in_klb']])
	# if klb_status == models.KLB_STATUS_OK:
	# 	context['klb_pending_result_ids'] = set(models.Table_update.objects.filter(
	# 		action_type__in=(models.ACTION_UNOFF_RESULT_CREATE, models.ACTION_RESULT_UPDATE),
	# 		is_verified=False, is_for_klb=True, row_id=event.id).values_list('child_id', flat=True))
	# 	context['was_not_checked_for_klb'] = (tab == TAB_DEFAULT) and context['race_has_results'] and not race.was_checked_for_klb
	# context['klb_results_exist'] = race.result_set.exclude(klb_result=None).exists() or context.get('klb_pending_result_ids')

	context['show_timing'] = (race.get_surface_type() in results_util.SURFACES_STADIUM_OR_INDOOR) and \
		(race.timing in (models.TIMING_ELECTRONIC, models.TIMING_HAND))

	if context['is_admin'] and event.is_in_past() and (parse_weekly_events.WeeklySeries.init(series) != None):
		context['show_update_weekly_results_button'] = True
		context['show_delete_skipped_parkrun_button'] = not event.document_set.filter(document_type=models.DOC_TYPE_PROTOCOL).exists()

	context['show_link_to_add_race_rating'] = user.is_authenticated \
		and user.result_set.filter(race=race).exists() and not user.group_set.filter(race=race, is_empty=False).exists()

	return views_common.paginate_and_render(request, 'results/race_details.html', context, filtered_results, page=page, add_results_with_splits=True)

def event_klb_results(request, event_id=None):
	event = get_object_or_404(models.Event, pk=event_id)
	series = event.series
	user = request.user
	context = views_common.user_edit_vars(user, series=series)
	if event.invisible and not (context['is_admin'] or context['is_editor']):
		raise Http404()
	context.update(constants_for_race_context(user, event))
	context['tab'] = TAB_KLB
	context['klb_results'] = event.klb_result_set.select_related('result', 'race__distance', 'klb_person',
		'klb_participant__team__club__city__region__country').order_by(
		'race__distance__distance_type', '-race__distance__length', 'race__precise_name', '-klb_score')
	context['page_title'] = f'{event}: результаты забега, учтённые в КЛБМатче'
	return render(request, 'results/race_details.html', context)

def event_age_group_records(request, event_id=None):
	event = get_object_or_404(models.Event, pk=event_id)
	series = event.series
	user = request.user
	context = views_common.user_edit_vars(user, series=series)
	if event.invisible and not (context['is_admin'] or context['is_editor']):
		raise Http404()
	context.update(constants_for_race_context(user, event))
	context['tab'] = TAB_AGE_GROUP_RECORDS
	context['records'] = models.Record_result.objects.exclude(cur_place=None, cur_place_electronic=None, was_record_ever=False).filter(
		race__event=event).select_related(
		'country', 'runner__user__user_profile', 'race__distance', 'age_group').order_by(
		'race__distance__distance_type', '-race__distance__length', 'runner__lname', 'runner__fname')
	context['page_title'] = f'{event}: рекорды в возрастных группах, показанные на забеге'.format(event)

	country = event.getCountry()
	if country and (country.id in results_util.THREE_COUNTRY_IDS):
		context['records_by_month_link'] = reverse('results:age_group_records_by_month',
			kwargs={'country_id': country.id, 'year': event.start_date.year, 'month': event.start_date.month})
	return render(request, 'results/race_details.html', context)

def calendar_content(event, races):
	context = {}
	context['n_plans'] = 0
	context['plans_by_distance'] = []
	if races.count() > 1:
		for race in races:
			items = race.calendar_set.select_related('user__user_profile').filter(user__is_active=True)
			items_count = items.count()
			if items_count:
				context['plans_by_distance'].append((race.distance_with_details(details_level=0), items, items_count))
				context['n_plans'] += items_count
		items = event.calendar_set.select_related('user__user_profile').filter(race=None, user__is_active=True)
		items_count = items.count()
		if items_count:
			context['plans_by_distance'].append(('не указали дистанцию', items, items_count))
			context['n_plans'] += items_count
	else:
		items = event.calendar_set.select_related('user__user_profile').filter(user__is_active=True)
		items_count = items.count()
		if items_count:
			context['plans_by_distance'].append(('', items, items_count))
			context['n_plans'] += items_count
	return context

def event_details(request, event_id=None, beta=0):
	event = get_object_or_404(models.Event, pk=event_id)
	series = event.series
	user = request.user
	context: dict[str, Any] = views_common.user_edit_vars(user, series=series)
	if event.invisible and not (context['is_admin'] or context['is_editor']):
		raise Http404()

	context.update(constants_for_event_context(user, event))
	context.update(calendar_content(event, context['races']))

	context['page_title'] = f'{event}, {event.dateFull()}'
	if user.is_authenticated:
		context['calendar'] = user.calendar_set.filter(event=event).first()
		context['is_authenticated'] = True

	context['reviews'] = models.Document.objects.filter(event=event, document_type=models.DOC_TYPE_IMPRESSIONS).order_by('author')
	context['photos'] = models.Document.objects.filter(event=event, document_type=models.DOC_TYPE_PHOTOS).order_by('author')
	context['news_set'] = event.news_set.order_by('-date_posted')
	if context['is_admin'] or (context['is_editor'] and event.can_be_edited):
		context['news_set'] = context['news_set'].prefetch_related('social_post_set')
		districts = set([None])
		for city in [event.city, event.city_finish, series.city, series.city_finish]:
			if city and city.region.district:
				districts.add(city.region.district)
		context['social_pages'] = models.Social_page.objects.filter(Q(district__in=districts) | Q(district__isnull=True)).exclude(page_type=models.SOCIAL_TYPE_FB)
	else:
		context['news_set'] = context['news_set'].filter(is_for_social=False)
		for news in list(context['news_set']):
			news.n_views += 1
			news.save()


	if context['is_admin'] and event.race_set.filter(load_status=models.RESULTS_LOADED).exists() and \
			event.race_set.filter(load_status=models.RESULTS_NOT_LOADED).exists():
		context['show_remove_races_link'] = True

	# For Sportmaster campaign (2017-04)
	# if user.is_authenticated and hasattr(user, 'user_profile') and user.user_profile.gender == results_util.GENDER_FEMALE:
	# 	context['user_is_female'] = True

	context['sr_event'] = show_rating.get_sr_overall_data(event, context['to_show_rating'])
	context['SITE_URL'] = results_util.SITE_URL

	if beta:
		return render(request, 'results/event_details_goprotect.html', context)
	else:
		return render(request, 'results/event_details.html', context)

@login_required
def add_event_to_calendar(request, event_id):
	event = get_object_or_404(models.Event, pk=event_id)
	race_id = request.GET.get('race_id', False)
	if race_id:
		race = get_object_or_404(models.Race, pk=race_id)
	else: # If there is only one race in the event, we use it
		races = event.race_set.all()
		if races.count() == 1:
			race = races.first()
		else:
			race = None

	res, message = event.add_to_calendar(race, request.user)
	if res:
		messages.success(request, 'Забег «{}» успешно добавлен в Ваш календарь.'.format(str(race.name_with_event() if race else event)))
	else:
		messages.warning(request, 'Забег «{}» не добавлен в Ваш календарь. Причина: {}'.format(str(event), message))
	return redirect(event)

@login_required
def remove_event_from_calendar(request, event_id):
	event = get_object_or_404(models.Event, pk=event_id)
	res, message = event.remove_from_calendar(request.user)
	if res:
		messages.success(request, 'Забег «{}» успешно удалён из Вашего календаря.'.format(str(event)))
	else:
		messages.warning(request, 'Забег «{}» не удалён из Вашего календаря. Причина: {}'.format(str(event), message))
	return redirect(event)

def protocols_wanted(request, events_type_code=forms.EVENT_TYPE_CODES[1], year=results_util.TODAY.year - 1, region_id=forms.DEFAULT_REGION_ID):
	if request.method == 'POST':
		return redirect('results:protocols_wanted',
			events_type_code=forms.EVENT_TYPE_CODES.get(results_util.int_safe(request.POST['events_type']), forms.PROTOCOL_ABSENT),
			year=request.POST['year'],
			region_id=results_util.int_safe(request.POST['region']),
		)

	context = {}
	events_type = forms.EVENT_TYPE_CODES_INV[events_type_code]
	region = models.Region.objects.filter(pk=region_id).first()
	if not region:
		region = models.Region.objects.get(pk=forms.DEFAULT_REGION_ID)
	year_int = results_util.int_safe(year) # will be 0 if 'for all years'
	context['form'] = forms.ProtocolHelpForm(initial={'events_type': events_type, 'year': year, 'region': region.id})

	races_wo_results = models.Race.objects.filter(has_no_results=False, kept_for_reg_history_only=False).exclude(load_status=models.RESULTS_LOADED).exclude(
		distance__distance_type=models.TYPE_RELAY)
	if year_int:
		races_wo_results = races_wo_results.filter(event__start_date__year=year_int)
	events_wo_results_ids = set(races_wo_results.values_list('event_id', flat=True))

	events_with_protocol = models.Document.objects.filter(document_type__in=models.DOC_PROTOCOL_TYPES, is_processed=False)
	if year_int:
		events_with_protocol = events_with_protocol.filter(event__start_date__year=year_int)
	events_with_protocol_ids = set(events_with_protocol.values_list('event_id', flat=True))

	events = models.Event.objects.filter(
		start_date__lte=results_util.TODAY - datetime.timedelta(days=14),
		cancelled=False,
		invisible=False,
		).prefetch_related(
			Prefetch('race_set', queryset=models.Race.objects.filter(has_no_results=False).exclude(load_status=models.RESULTS_LOADED).select_related(
				'distance').annotate(Count('result')).order_by('distance__distance_type', '-distance__length'))
			).order_by('start_date')
	if region:
		events = events.filter(Q(city__region=region) | Q(series__city__region=region))

	context['page_title'] = 'Забеги '
	if region:
		if region.is_active:
			context['page_title'] += f'в регионе {region.name} '
		else:
			context['page_title'] += f'в стране {region.name} '
	if year_int:
		context['page_title'] += f'в {year_int} году '
	else:
		context['page_title'] += 'за все годы '
	if events_type == forms.PROTOCOL_ABSENT:
		events = events.filter(pk__in=events_wo_results_ids - events_with_protocol_ids)
		context['page_title'] += 'без протоколов и с неполными протоколами'
	else: #if events_type == forms.PROTOCOL_BAD_FORMAT:
		events_with_xls_protocol = models.Document.objects.filter(models.Q_IS_XLS_FILE)
		if year_int:
			events_with_xls_protocol = events_with_xls_protocol.filter(event__start_date__year=year_int)
		events_with_xls_protocol_ids = set(events_with_xls_protocol.values_list('event_id', flat=True))
		events = events.filter(pk__in=(events_wo_results_ids & events_with_protocol_ids) - events_with_xls_protocol_ids).prefetch_related(
			Prefetch('document_set', queryset=models.Document.objects.filter(document_type__in=models.DOC_PROTOCOL_TYPES)))
		context['page_title'] += 'с протоколами в неудобных форматах'
	context['events_type'] = events_type
	context['events'] = events
	return render(request, 'results/protocols_wanted.html', context)

def rating(request, country_id=None, distance_code=None, year=None, rating_type_code=None, page=1):
	if request.method == 'POST':
		kwargs = {
			'country_id': request.POST.get('country_id', 'RU'),
			'distance_code': results_util.DISTANCE_CODES[results_util.int_safe(request.POST.get('distance_id', results_util.DIST_MARATHON_ID))],
			'year': request.POST.get('year'),
			'rating_type_code': forms.RATING_TYPES_CODES[results_util.int_safe(request.POST.get('rating_type', forms.RATING_TYPE_DEFAULT))],
		}
		page = results_util.int_safe(request.POST.get('page'))
		if page:
			kwargs['page'] = page
		return redirect('results:rating', **kwargs)

	context = views_common.user_edit_vars(request.user)
	if country_id is None:
		context['page_title'] = 'Рейтинг забегов по версии сайта «ПроБЕГ»'
		context['ratingForm'] = forms.RatingForm()
		return render(request, 'results/rating.html', context)

	context['show_rating'] = True

	country = models.Country.objects.filter(pk=country_id).first()
	distance_id = results_util.DISTANCE_CODES_INV.get(distance_code)
	distance = models.Distance.objects.filter(pk=distance_id).first()
	rating_type = forms.RATING_TYPES_CODES_INV.get(rating_type_code, forms.RATING_N_FINISHERS)

	context['value_name'] = forms.RATING_TYPES[rating_type][1]

	context['ratingForm'] = forms.RatingForm({
		'country_id': country_id,
		'distance_id': distance_id,
		'year': year,
		'rating_type': rating_type,
	})

	if distance:
		title_distance = f'Лучшие забеги на дистанцию {distance.name}'
	elif distance_id == results_util.DISTANCE_ANY:
		title_distance = 'Крупнейшие забеги на любую дистанцию'
		context['show_distance_column'] = True
	elif distance_id == results_util.DISTANCE_WHOLE_EVENTS:
		title_distance = 'Крупнейшие забеги'
	else:
		messages.warning(request, f'Вы указали неправильный тип дистанции {distance_id}. Пожалуйста, напишите нам, если вы считаете, что эта ссылка должна работать.')
		return redirect('results:rating')

	if year:
		title_year = f'в {year} году'
	else:
		title_year = 'за все годы'
	context['page_title'] = f'{title_distance} {forms.get_degree_from_country(country)} {title_year} по {forms.RATING_TYPES_DEGREES[rating_type][1]}'

	if country:
		country_ids = [country.id]
	else:
		country_ids = forms.RATING_COUNTRY_IDS

	if distance_id == results_util.DISTANCE_WHOLE_EVENTS:
		context['rating_by_whole_events'] = True
		events = models.Event.get_events_by_countries(year, country_ids).annotate(
			n_participants_finished=Sum('race__n_participants_finished'),
			n_participants_finished_male=Sum('race__n_participants_finished_male'),
			n_participants_finished_women=Sum('race__n_participants_finished')-Sum('race__n_participants_finished_male')
		)
		if rating_type == forms.RATING_N_FINISHERS:
			rating_value = 'n_participants_finished'
		elif rating_type == forms.RATING_N_FINISHERS_MALE:
			rating_value = 'n_participants_finished_male'
		elif rating_type == forms.RATING_N_FINISHERS_FEMALE:
			rating_value = 'n_participants_finished_women'
		events = events.filter(**{f'{rating_value}__gt': 0})
		filtered_results = events.select_related('series__city__region__country', 'city__region__country').prefetch_related(
			Prefetch('race_set',
				queryset=models.Race.objects.select_related('distance').order_by(
					'distance__distance_type', '-distance__length', 'precise_name')),
		).order_by(f'-{rating_value}')
	else:
		races = models.Race.get_races_by_countries(year, country_ids)
		if distance:
			races = races.filter(distance=distance)
		if rating_type in forms.RATING_TYPES_BY_FINISHERS:
			context['rating_by_n_finishers'] = True
			if rating_type == forms.RATING_N_FINISHERS:
				races = races.filter(n_participants_finished__gt=0).annotate(rating_value=F('n_participants_finished'))
			elif rating_type == forms.RATING_N_FINISHERS_MALE:
				races = races.filter(n_participants_finished_male__gt=0).annotate(rating_value=F('n_participants_finished_male'))
			elif rating_type == forms.RATING_N_FINISHERS_FEMALE:
				races = races.annotate(rating_value=F('n_participants_finished')-F('n_participants_finished_male')).filter(rating_value__gt=0)
			filtered_results = races.select_related(
				'event__series__city__region__country', 'event__city__region__country').order_by('-rating_value')
		else:
			result_ordering = '-result' if (distance.distance_type in models.TYPES_MINUTES) else 'result'
			context['rating_by_best_result'] = True
			races = races.filter(Q(distance_real=None) | Q(distance_real__length__gt=distance.length), is_for_handicapped=False)
			if rating_type == forms.RATING_BEST_MALE:
				results = models.Result.objects.filter(
					race__in=races, place_gender=1, gender=results_util.GENDER_MALE, status=models.STATUS_FINISHED)
			elif rating_type == forms.RATING_BEST_FEMALE:
				results = models.Result.objects.filter(
					race__in=races, place_gender=1, gender=results_util.GENDER_FEMALE, status=models.STATUS_FINISHED)
			filtered_results = results.select_related(
				'race__event__series__city__region__country', 'race__event__city__region__country').order_by(result_ordering)
	return views_common.paginate_and_render(request, 'results/rating.html', context, filtered_results, page=page)

def get_logo_page(request, event_id=None, series_id=None, organizer_id=None):
	context = {}
	if event_id:
		event = get_object_or_404(models.Event, pk=event_id)
		context['image_url'] = add_prefix(event.get_url_logo())
	elif series_id:
		series = get_object_or_404(models.Series, pk=series_id)
		context['image_url'] = add_prefix(series.get_url_logo())
	elif organizer_id:
		organizer = get_object_or_404(models.Organizer, pk=organizer_id)
		context['image_url'] = add_prefix(organizer.logo)
	return render(request, "results/modal_image.html", context)
