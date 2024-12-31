from django.contrib.auth.models import User
from django.contrib import messages
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect

import datetime
import json
import time
from typing import Optional

from results import models, results_util
from editor import generators, runner_stat, stat
from editor.scrape import util
from editor.views import views_common, views_result

ROOT_JSON_URLS = ('https://s95.ru/pages/index.json', 'https://s95.by/pages/index.json')
# ROOT_JSON_URLS = ('https://s95.by/pages/index.json', )
PLATFORM_ID = 's95'

def ParkrunId(url_results: str, athlete_dict: dict[str, any]) -> Optional[int]:
	parkrun_id = athlete_dict.get('parkrun_code')
	if parkrun_id and parkrun_id > util.MAX_PARKRUN_ID:
		raise Exception(f'S95 event {url_results}: parkrun ID {parkrun_id} is too big')
	return parkrun_id

# Load results for given race from given URL with json.
# Returns the number of loaded results and the set of touched runners.
def load_race_results(race: models.Race, url_results: str) -> tuple[int, set[models.Runner]]:
	result, html, _, _, error = results_util.read_url(url_results)
	time.sleep(1)
	if not result:
		models.write_log(f'Could not load results for {race.event}, id={race.event.id}, from url {url_results}: {error}')
		return 0, set()
	try:
		data = json.loads(html)
	except Exception as e:
		raise Exception(f'{url_results}: failed decoding content of length {len(html)}, "{html[:100]}": {e}')

	race.result_set.filter(source=models.RESULT_SOURCE_DEFAULT).delete()
	results_added = 0
	runners_touched = set()
	new_results = []
	messages = []

	for result_dict in data['results']:
		gender = results_util.GENDER_UNKNOWN
		gender_raw = result_dict['athlete'].get('gender')
		runner = None
		s95_id = None
		if result_dict['athlete']['name'] == 'НЕИЗВЕСТНЫЙ' and ('id' not in result_dict['athlete']):
			lname = fname = midname = ''
		else:
			lname, fname, midname = views_result.split_name(result_dict['athlete']['name'].strip().title(), first_name_position=0)
			if gender_raw:
				gender = results_util.string2gender(gender_raw.strip())
				if gender == results_util.GENDER_UNKNOWN:
					models.send_panic_email(
						'parse/s95: load_race_results: problem with gender',
						f'Problem with race id {race.id}, url {url_results} : gender "{result_dict["athlete"]["gender"]}" cannot be parsed')
			
			platforms_dict = {}
			if parkrun_id := ParkrunId(url_results, result_dict['athlete']):
				platforms_dict['parkrun'] = parkrun_id
			s95_id = result_dict['athlete']['id']
			if s95_id:
				platforms_dict['s95'] = s95_id

			if platforms_dict:
				fields_to_fill = {'gender': gender}
				if lname:
					fields_to_fill['lname'] = lname
				if fname:
					fields_to_fill['fname'] = fname
				if midname:
					fields_to_fill['midname'] = midname
				result_desc = f'Race {url_results}, {lname} {fname}'
				runner, messages_ = util.RunnerWithPlatformIDs(platforms_dict, fields_to_fill, result_desc)
				messages += messages_

		centiseconds = models.string2centiseconds(result_dict['total_time'])
		if centiseconds == 0:
			models.send_panic_email(
				'parse/s95: load_race_results: problem with time',
				f'Problem with race id {race.id}, url {url_results} : time "{result_dict["total_time"]}" cannot be parsed')

		new_results.append(models.Result(
			race=race,
			runner=runner,
			user=runner.user if runner else None,
			runner_id_on_platform=s95_id,
			name_raw=result_dict['athlete']['name'],
			result_raw=result_dict['total_time'],
			club_name=result_dict['athlete'].get('club', ''),
			place_raw=result_dict['position'],
			result=centiseconds,
			status=models.STATUS_FINISHED,
			status_raw=models.STATUS_FINISHED,
			lname=lname,
			fname=fname,
			midname=midname,
			gender=gender,
			gender_raw=gender,
		))
		if runner:
			runners_touched.add(runner)

	models.Result.objects.bulk_create(new_results)
	views_result.fill_places(race)
	views_result.fill_race_headers(race)
	if len(new_results) > 0:
		race.load_status = models.RESULTS_LOADED
		race.save()
	if messages:
		models.send_panic_email(
			'parse/s95: load_race_results: warnings',
			f'Problem with race id {race.id}, url {url_results} :\n' + '\n'.join(messages))
	print(f'{url_results} - {len(new_results)} loaded')
	return len(new_results), runners_touched

# Returns <success?>, <results loaded>, <runners touched>
def reload_results(race: models.Race) -> tuple[bool, int, int]:
	protocol = race.event.document_set.filter(document_type=models.DOC_TYPE_PROTOCOL).first()
	if protocol:
		url_results = protocol.url_source
		if url_results:
			runners_touched = set(result.runner for result in race.result_set.all().select_related('runner__user__user_profile') if result.runner)
			n_results, runners_touched_2 = load_race_results(race, url_results)
			runner_stat.update_runners_and_users_stat(runners_touched | runners_touched_2)
			return True, n_results, len(runners_touched)
	return False, 0, 0

def reload_results_for_date(date: datetime.date):
	for race in models.Race.objects.filter(event__series__is_weekly=True, event__start_date=date, distance_id=results_util.DIST_5KM_ID).select_related(
			'event').order_by('event__name'):
		success, n_results, _ = reload_results(race)
		print(race.event.name, success, n_results)

@views_common.group_required('admins')
def reload_race_results(request, race_id):
	race = get_object_or_404(models.Race, pk=race_id)
	success, n_results, n_runners_touched = reload_results(race, request.user)
	if success:
		messages.success(request, f'Результаты загружены заново. Всего результатов: {n_results}, затронуто бегунов: {n_runners_touched}')
	else:
		messages.warning(request, 'Протокол забега не найден. Результаты не перезагружены')
	return redirect(race)

# Creates new event and new race if needed
def get_or_create_event_and_race(
		series: models.Series,
		url_results: str,
		event_date: datetime.date,
		start_time: Optional[str],
		event_num: Optional[int],
		user: User) -> tuple[bool, models.Race]:
	event = series.event_set.filter(start_date=event_date).first()
	race = None
	existed = False
	if event is None:
		name = series.name
		if event_num:
			name += f' №{event_num}'
		event = models.Event.objects.create(
			series=series,
			number=event_num,
			start_date=event_date,
			url_site=series.url_site,
			start_time=start_time,
			created_by=user,
			name=name,
		)
		event.clean()
		event.save()
	else:
		existed = True
		race = models.Race.objects.filter(event=event, distance_id=results_util.DIST_5KM_ID).first()
	if url_results and not event.document_set.filter(document_type=models.DOC_TYPE_PROTOCOL).exists():
		if url_results[-5:] == '.json':
			url_results = url_results[:-5]
		models.Document.objects.create(event=event, document_type=models.DOC_TYPE_PROTOCOL,
			loaded_type=models.LOAD_TYPE_NOT_LOADED, url_source=url_results, created_by=user)
	if not race:
		race = models.Race.objects.create(event=event, distance_id=results_util.DIST_5KM_ID, created_by=user)
		race.clean()
		race.save()
	return existed, race

# Creates new event and new race. Returns the number of created events.
def create_future_events(series, user, debug=False) -> int:
	events_created = 0
	events = models.Event.objects.filter(series=series).order_by('-start_date')
	last_event = events.first()
	if last_event is None:
		models.write_log(f'Could not find any events for series {series}, id {series.id}. Stopped creating future events.', debug=debug)
		return 0
	if last_event.number is None:
		if events.count() == 1:
			last_event.number = 1
			if not last_event.name.endswith('№1'):
				last_event.name += ' №1'
			last_event.start_time = results_util.DEFAULT_PARKRUN_START_TIME
			last_event.save()
		elif series.is_russian_parkrun():
			models.write_log("Problem with event number for series {}, id {}. Stopped creating future events.".format(series, series.id), debug=debug)
			return 0
	if (last_event.number == 1) and not last_event.race_set.exists(): # So it's enough to create first event in series without any distances
		race = models.Race.objects.create(event=last_event, distance_id=results_util.DIST_5KM_ID, created_by=user)
		race.clean()
		race.save()
	if last_event.start_date + datetime.timedelta(days=30) < datetime.date.today():
		models.send_panic_email(
			'We could not create future weekly events',
			f'Мы пытались создать новые забеги в серии {series} (id {series.id}), но последний забег в ней очень старый: {last_event.start_date}. Ничего не создаём.',
			to_all=True,
		)
		return 0
	event_number = (last_event.number + 1) if last_event.number else None
	event_date = last_event.start_date + datetime.timedelta(days=7)
	month_from_now = datetime.date.today() + datetime.timedelta(days=34)
	while event_date <= month_from_now:
		existed, race = get_or_create_event_and_race(series, '', event_date, last_event.start_time, event_number, user)
		if not existed:
			events_created += 1
		if event_number:
			event_number += 1
		event_date += datetime.timedelta(days=7)
	return events_created

def get_series_history_url(series: models.Series) -> str:
	return series.url_site.rstrip('/') + '.json'

def get_event_url(series: models.Series, global_number: int) -> str:
	return series.url_site.rstrip('/') + f'/activities/{global_number}'

# Check: Are there any new runs with current series that are not in base? If yes, load them.
def update_series_results(series: models.Series, user: User, update_runners_stat: bool=True):
	new_races = []
	url_history = get_series_history_url(series)
	result, html, _, _, error = results_util.read_url(url_history)
	if not result:
		models.send_panic_email(
			'parse/s95: update_series_results: problem with event history',
			f'Could not load event history for parkrun {series.name}, id={series.id}, from url {url_history}: {error}')
		return [], set()
	data = json.loads(html)
	new_races_created = False
	runners_touched = set()
	for item in data['activities']:
		event_date = datetime.datetime.strptime(item['date'], '%Y-%m-%d').date()
		url_results = item['url']
		existed, race = get_or_create_event_and_race(series, url_results, event_date, results_util.DEFAULT_PARKRUN_START_TIME, None, user)
		if race.load_status != models.RESULTS_LOADED:
			models.write_log(f'New event found: {url_results}')
			n_results, new_runners_touched = load_race_results(race, url_results)
			runners_touched |= new_runners_touched
			new_races.append((race, n_results, existed))
			if not existed:
				new_races_created = True
	if update_runners_stat:
		runner_stat.update_runners_and_users_stat(runners_touched)
	return new_races, runners_touched

def create_new_series(data: dict[any, any], series_url: str) -> models.Series:
	city_name = data['town'].strip()
	if city_name == 'Пенза (Город Спутник)':
		city_name = 'Пенза'
	city = models.City.objects.filter(Q(name=city_name) | Q(name_orig=city_name)).order_by('-population').first()
	if not city:
		raise Exception(f'S95: create_new_series: City {city_name} not found')
	series = models.Series.objects.create(
		name=f'S95 {data["name"]}',
		city=city,
		start_place=data['place'][:100],
		url_site=series_url,
		surface_type=results_util.SURFACE_ROAD,
		is_weekly=True,
		create_weekly=data['active'] and ('smfest' not in series_url),
		)
	models.log_obj_create(models.USER_ROBOT_CONNECTOR, series, models.ACTION_CREATE, comment=f'При обработке протокола {series_url}', verified_by=models.USER_ROBOT_CONNECTOR)
	return series

# Returns:
# * List of just created series
# * List of just created events, with <number of just lodad results> and <did the race exist before>
# * Number of just created future events
# * Error, if any
def update_weekly_results() -> tuple[list[models.Series], list[tuple[models.Race, int, bool]], int, str]:
	series_to_process = []
	new_series = []
	new_races = []
	runners_touched = set()
	future_events_created = 0

	for root_url in ROOT_JSON_URLS:
		result, html, _, _, error = results_util.read_url(root_url)
		if not result:
			return [], [], 0, f'Не получилось загрузить данные о сериях с адреса {root_url}: {error}'
		data = json.loads(html)

		for item in data['events']:
			if item['name'] == 'S95 & Friends':
				continue # A strange series
			series_json_url = item['url']
			if series_json_url[-5:] != '.json':
				return new_series, new_races, future_events_created, f'Адрес серии {series_json_url} не кончается на ".json"'
			series_url = series_json_url[:-5]
			existing_series = models.Series.objects.filter(url_site=series_url)
			if existing_series.count() > 1:
				return new_series, new_races, future_events_created, f'Найдено больше одной серии с URL {series_url}: ' + ', '.join(str(s.id) for s in existing_series)
			series = existing_series.first()
			if not series:
				series = create_new_series(item, series_url)
			series_to_process.append(series)

	for series in series_to_process:
		races, runners = update_series_results(series, models.USER_ROBOT_CONNECTOR, update_runners_stat=False)
		new_races += races
		runners_touched |= runners
		time.sleep(6)
		if series.create_weekly:
			future_events_created += create_future_events(series, models.USER_ROBOT_CONNECTOR)
	if runners_touched:
		runner_stat.update_runners_and_users_stat(runners_touched)
		stat.update_results_count()
		stat.update_events_count()
		# generators.generate_parkrun_stat_table()
	return new_series, new_races, future_events_created, ''
