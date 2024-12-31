from django.contrib.auth.models import User

import bs4
import datetime
import re
import time
from typing import List, Optional, Tuple

from results import models, results_util
from editor import generators, runner_stat
from editor.views import views_common
from . import util

def SeriesHistoryUrl(series: models.Series) -> str:
	return series.url_site.rstrip('/') + '/results/eventhistory/'

def EventUrl(series: models.Series, number: int) -> str:
	return series.url_site.rstrip('/') + f'/results/{number}'

try:
	PARKRUN_DISTANCE = models.Distance.objects.get(pk=results_util.DIST_5KM_ID)
except:
	PARKRUN_DISTANCE = None

READ_FILES_NOT_URLS = False
DEFAULT_START_TIME = datetime.time(hour=9)

# Vasya Moy PUPKIN -> ('Vasya Moy', 'PUPKIN')
# Vasya MOY PUPKIN -> ('Vasya', 'MOY PUPKIN')
def ParseName(name: str) -> tuple[str, str]:
	parts = name.split()
	if len(parts) <= 1:
		return '', parts
	most_right_name_not_of_capitals = 0
	for i in range(1, len(parts)):
		if parts[i].isupper():
			# So i-th part is the leftmost one with only capital letters. This is where the last name starts.
			return ' '.join(parts[:i]), ' '.join(parts[i:])
	return ' '.join(parts[:-1]), parts[-1]

def ExtractRunnerID(url: str) -> int:
	if url.startswith('/'):
		parts = url.split('/')
		if (len(parts) == 4) and (parts[2] == 'parkrunner'):
			return results_util.int_safe(parts[3])
	return 0

# Converts the contents of the results page into the standard form dicts.
def RaceResults(url: str, content: str) -> list[dict[str, any]]:
	res = []
	soup = bs4.BeautifulSoup(content, 'html.parser')
	part = soup.find('div', class_='Results')
	unknown_name = part['data-unknown']
	for i, row in enumerate(part.find_all('tr', class_='Results-table-row')):
		item = {}
		item['place_raw'] = results_util.int_safe(row.find('td', class_='Results-table-td--position').string)
		if not item['place_raw']:
			raise util.NonRetryableError(f'{url}, row {i}: place is {item["place_raw"]}')

		name_div = row.find('td', class_='Results-table-td--name').find('div', class_='compact')
		name_tag = name_div.a
		if name_tag is None and name_div.string == unknown_name:
			continue # We ignore lines with "Unknown" runner because there are no results and no useful data at all.
		item['name_raw'] = name_tag.string

		if not item['name_raw']:
			raise util.NonRetryableError(f'{url}, row {i}: no name in "{name_tag}"')
		item['fname_raw'], item['lname_raw'] = ParseName(item['name_raw'])

		item['runner_id_on_platform'] = ExtractRunnerID(name_tag['href'])
		if not item['runner_id_on_platform']:
			raise util.NonRetryableError(f'{url}, row {i}: runner_id_on_platform from {name_tag["href"]} is {item["runner_id_on_platform"]}')

		item['gender_raw'] = 'F' if (row.find('td', class_='Results-table-td--M') is None) else 'M'

		item['category_raw'] = row.find('td', class_='Results-table-td--ageGroup').find('div', class_='compact').string
		if not item['category_raw']:
			raise util.NonRetryableError(f'{url}, row {i}: no category')

		item['club_raw'] = row.find('td', class_='Results-table-td--club').string.strip()

		part_result = row.find('td', class_='Results-table-td--time')

		item['result_raw'] = part_result.find('div', class_='compact').string
		if not item['result_raw']:
			raise util.NonRetryableError(f'{url}, row {i}: no category')

		item['comment_raw'] = ' '.join(part_result.find('div', class_='detailed').stripped_strings)

		res.append(item)
	return res

# Converts the contents of the series history page into the list of pairs: (event number, date).
def SeriesEvents(url: str, content: str) -> list[tuple[int, datetime.date]]:
	res = []
	soup = bs4.BeautifulSoup(content, 'html.parser')
	for i, row in enumerate(part.find_all('tr', class_='Results-table-row')):
		num = results_util.int_safe(row['data-parkrun'])
		if not num:
			raise util.NonRetryableError(f'{url}, row {i}: strange parkrun number')
		res.append((num, datetime.date.fromisoformat(row['data-date'])))
	return res

# Returns <success?>, <results loaded>, <runners touched>
def reload_parkrun_results(race: models.Race, user: User) -> Tuple[bool, int, int]:
	protocol = race.event.document_set.filter(document_type=models.DOC_TYPE_PROTOCOL).first()
	if protocol:
		url_results = protocol.url_source
		if url_results:
			runners_touched = set(result.runner for result in race.result_set.all().select_related('runner__user__user_profile') if result.runner)
			n_results, runners_touched_2 = LoadRaceResults(race, url_results, user)
			runner_stat.update_runners_and_users_stat(runners_touched | runners_touched_2)
			return True, n_results, len(runners_touched)
	return False, 0, 0

def reload_parkrun_results_for_date(date: datetime.date):
	for race in models.Race.objects.filter(event__series__is_weekly=True, event__start_date=date, distance=PARKRUN_DISTANCE).select_related('event').order_by('event__name'):
		success, n_results, _ = reload_parkrun_results(race, models.USER_ROBOT_CONNECTOR)
		print(race.event.name, success, n_results)

# Creates new event and new race if needed.
# Returns:
# * whether the event already existed,
# * The only race in the event.
def GetOrCreateEventAndRace(
		series: models.Series,
		url_results: str,
		event_date: datetime.date,
		start_time: Optional[datetime.time],
		event_num: Optional[int],
		user: User) -> Tuple[bool, models.Race]:
	event = series.event_set.filter(start_date=event_date).first()
	race = None
	existed = False
	if event:
		existed = True
		race = models.Race.objects.filter(event=event, distance=PARKRUN_DISTANCE).first()
	else:
		name = series.name
		if event_num:
			name += f' №{event_num}'
		event = models.Event.objects.create(
			series=series,
			name=name,
			number=event_num,
			start_date=event_date,
			url_site=series.url_site,
			start_time=start_time,
			created_by=user,
		)
		event.clean()
		event.save()
	if url_results and not event.document_set.filter(document_type=models.DOC_TYPE_PROTOCOL).exists():
		models.Document.objects.create(event=event, document_type=models.DOC_TYPE_PROTOCOL,
			loaded_type=models.LOAD_TYPE_NOT_LOADED, url_source=url_results, created_by=user)
	if not race:
		race = models.Race.objects.create(event=event, distance=PARKRUN_DISTANCE, created_by=user)
		race.clean()
		race.save()
	return existed, race

# Creates new event and new race. Returns True(no results yet)/False(results are already loaded) and race id.
def CreateFutureEvents(
		series: models.Series,
		user: User,
		debug: int=0,
		ignore_last_event_date: bool=False):
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
		race = models.Race.objects.create(event=last_event, distance=PARKRUN_DISTANCE, created_by=user)
		race.clean()
		race.save()
	if (not ignore_last_event_date) and last_event.start_date + datetime.timedelta(days=30) < datetime.date.today():
		models.send_panic_email(
			'We could not create future parkruns',
			f'Мы пытались создать новые паркраны в серии {series} (id {series.id}), но последний забег в ней очень старый: {last_event.start_date}. Ничего не создаём.',
			to_all=True,
		)
		return 0
	event_number = (last_event.number + 1) if last_event.number else None
	event_date = last_event.start_date + datetime.timedelta(days=7)
	month_from_now = datetime.date.today() + datetime.timedelta(days=34)
	while event_date <= month_from_now:
		existed, race = GetOrCreateEventAndRace(series, '', event_date, last_event.start_time, event_number, user)
		if not existed:
			events_created += 1
		if event_number:
			event_number += 1
		event_date += datetime.timedelta(days=7)
	return events_created

# Check: Are there any new runs with current series that are not in base? If yes, load them.
def UpdateSeriesResults(series: models.Series, update_runners_stat=True):
	new_races = []
	url_history = SeriesHistoryUrl(series)
	contents, _ = util.TryGetJson(results_util.session.get(url_history), is_json=False)
	oldest_race_created = None
	runners_touched = set()
	series_events = SeriesEvents(url_history, contents)
	for num, event_date in series_events:
		url_results = EventUrl(series, event_num)
		existed, race = GetOrCreateEventAndRace(series, url_results, event_date, DEFAULT_START_TIME, event_num)
		if race.load_status != models.RESULTS_LOADED:
			n_results, new_runners_touched = LoadRaceResults(race, url_results, user)
			runners_touched |= new_runners_touched
			new_races.append((race, n_results, existed))
			if not existed:
				oldest_race_created = race
		elif event_date <= series.latest_loaded_event:
			# So we already loaded everything before that.
			break
	if oldest_race_created:
		# If we just created any races, let's check if event numbers for future races are correct:
		# Maybe there were some extra parkruns, e.g. for New Year/Christmas.
		FixEventNumbers(oldest_race_created.event_id)
	if series_events and (series.latest_loaded_event < (last_loaded_event := series_events[0][1]) ):
		series.latest_loaded_event = last_loaded_event
		series.save()
	if update_runners_stat:
		runner_stat.update_runners_and_users_stat(runners_touched)
	return new_races, runners_touched

def update_parkrun_results() -> Tuple[List[Tuple[models.Race, int, bool]], int]:
	new_races = []
	runners_touched = set()
	future_events_created = 0
	for series in models.Series.get_russian_parkruns().filter(create_weekly=True).order_by('id'):
		try:
			races, runners = update_series_results(series, models.USER_ROBOT_CONNECTOR, update_runners_stat=False)
			new_races += races
			runners_touched |= runners
		except FileNotFoundError:
			pass
		if not READ_FILES_NOT_URLS:
			time.sleep(6)

	for series in models.Series.objects.filter(create_weekly=True):
		future_events_created += create_future_events(series, models.USER_ROBOT_CONNECTOR)
	runner_stat.update_runners_and_users_stat(runners_touched)
	views_stat.update_results_count()
	views_stat.update_events_count()
	generators.generate_parkrun_stat_table()
	return new_races, future_events_created

def create_parkrun_protocols():
	docs_added = 0
	for series in models.Series.get_russian_parkruns().order_by('id'):
		for event in series.event_set.all():
			if not event.document_set.filter(document_type=models.DOC_TYPE_PROTOCOL).exists():
				models.Document.objects.create(series=series, event=event, document_type=models.DOC_TYPE_PROTOCOL,
					loaded_type=models.LOAD_TYPE_NOT_LOADED, url_source=event.url_site, created_by=models.USER_ROBOT_CONNECTOR
					)
				docs_added += 1
	print('Finished! Documents added:', docs_added)

def create_future_events_once(debug=False): # It should be called when new parkrun series is just created
	for series in models.Series.objects.filter(create_weekly=True):
		n_created = create_future_events(series, models.USER_ROBOT_CONNECTOR, debug=debug)
		if debug:
			print('Created {} parkruns in series {}'.format(n_created, series.name))
	if debug:
		print('Finished!')

def FixEventNumbers(correct_event_id=None, correct_event=None): # Enter id of last event (or last event itself) in series with correct number
	if correct_event is None:
		correct_event = models.Event.objects.get(pk=correct_event_id)
	series = correct_event.series
	last_correct_date = correct_event.start_date
	cur_number = correct_event.number
	n_fixed_parkruns = 0
	for event in series.event_set.filter(start_date__gt=last_correct_date).order_by('start_date'):
		cur_number += 1
		event.number = cur_number
		correct_name = '{} №{}'.format(correct_event.series.name, cur_number)
		if event.name != correct_name:
			event.name = correct_name
			event.save()
			n_fixed_parkruns += 1
	return series, n_fixed_parkruns

class ParkrunScraper(util.Scraper):
	PLATFORM_ID = 'parkrun'

	@classmethod
	def ProcessSeries(series: models.Series):


