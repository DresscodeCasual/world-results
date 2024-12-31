from django.shortcuts import get_object_or_404, redirect
from django.contrib.auth.models import User
from django.contrib import messages

import datetime
import re
import time
from typing import List, Optional, Tuple

from results import models, results_util
from editor import generators, runner_stat
from . import views_common, views_result, views_stat

parkrun_result_re = re.compile(r'<tr[^>]*><td[^>]*>(?P<place>\d+)</td><td[^>]*><div[^>]*><a href="[a-z0-9:./]*/parkrunner/(?P<parkrun_id>\d+)"[^>]*>(?P<name>[^<]+)</a></div><div[^>]*>[^<]*<span[^>]*><span[^>]*>[^<]*</span><span[^>]*>(?P<gender>[^<]+)</span>\d+<span[^>]*>[^<]*</span></span>(<span[^>]*>[^<]*</span><a [^>]*>[^<]*</a>)*</div><div[^>]*><div[^>]*><a [^>]*>(?P<category>[^<]+)</a><span[^>]*>[^<]*</span>[^<]*</div></div>(<div[^>]*><div[^>]*><a [^>]*>(?P<club>[^<]+)</a></div></div>)*</td><td[^>]*><div[^>]*>[^<]*</div><div[^>]*>(?P<place_gender>\d+)<span[^>]*>[^<]*</span></div></td><td[^>]*><div[^>]*><a [^>]*>[^<]*</a></div><div[^>]*>[^<]*</div></td><td[^>]*>(<div[^>]*><a [^>]*>[^<]*</a></div>)*[^<]*</td><td[^>]*><div[^>]*>(?P<result>[^<]+)</div><div[^>]*><span[^>]*>(?P<comment1>[^<]*)</span>(?P<comment2>[^<]*)')
parkrun_result_history_re = re.compile(r'<a href="\.\./(?P<number>\d+)"><span[^>]+>(?P<day>\d+)/(?P<month>\d+)/(?P<year>\d+)</span>')

try:
	PARKRUN_DISTANCE = models.Distance.objects.get(pk=results_util.DIST_5KM_ID)
except:
	PARKRUN_DISTANCE = None

READ_FILES_NOT_URLS = True

# Load results for race with given race_id, either all or for Russians only
def load_race_results(race, url_results, user, load_only_russians=False):
	result, html, _, _, error = results_util.read_url(url_results, from_file=READ_FILES_NOT_URLS)
	if not result:
		models.write_log(f'Could not load results for parkrun {race.event}, id={race.event.id}, from url {url_results}: {error}')
		return 0, set()
	race.result_set.filter(source=models.RESULT_SOURCE_DEFAULT).delete()
	results_added = 0
	runners_touched = set()

	category_sizes = {category_size.name: category_size for category_size in race.category_size_set.all()}
	category_lower_to_orig = {name.lower(): name for name in category_sizes}

	new_results = []

	for group in parkrun_result_re.finditer(html):
		groupdict = group.groupdict('')
		parkrun_id = results_util.int_safe(groupdict['parkrun_id'])
		lname, fname, midname = views_result.split_name(groupdict['name'].strip().title(), first_name_position=0)
		gender = results_util.string2gender(groupdict['gender'].strip())
		if gender == models.GENDER_UNKNOWN:
			models.send_panic_email(
				'views_parkrun: load_race_results: problem with gender',
				"Problem with race id {}, url {} : gender '{}' cannot be parsed".format(race.id, url_results, groupdict['gender']),
			)
		runner, created = models.Runner.objects.get_or_create(
			parkrun_id=parkrun_id,
			defaults={'lname': lname, 'fname': fname, 'gender': gender}
		)

		centiseconds = models.string2centiseconds(groupdict['result'])
		if centiseconds == 0:
			models.send_panic_email(
				'views_parkrun: load_race_results: problem with time',
				"Problem with race id {}, url {} : time '{}' cannot be parsed".format(race.id, url_results, groupdict['result']),
			)

		category = groupdict['category']
		if category:
			category_lower = category.lower()
			if category_lower not in category_lower_to_orig:
				category_sizes[category] = models.Category_size.objects.create(race=race, name=category)
				category_lower_to_orig[category_lower] = category

		new_results.append(models.Result(
			race=race,
			runner=runner,
			user=runner.user,
			parkrun_id=parkrun_id,
			name_raw=groupdict['name'],
			time_raw=groupdict['result'],
			club_raw=groupdict['club'],
			club_name=groupdict['club'],
			place_raw=results_util.int_safe(groupdict['place']),
			result=centiseconds,
			status=models.STATUS_FINISHED,
			status_raw=models.STATUS_FINISHED,
			category_size=category_sizes[category_lower_to_orig[category_lower]] if category else None,
			category_raw=category,
			comment=groupdict['comment1'] + groupdict['comment2'],
			lname=lname,
			fname=fname,
			midname=midname,
			gender=gender,
			gender_raw=gender,
			loaded_by=user,
		))
		runners_touched.add(runner)

	models.Result.objects.bulk_create(new_results)
	views_result.fill_places(race)
	views_result.fill_race_headers(race)
	if len(new_results) > 0:
		race.load_status = models.RESULTS_LOADED
		race.save()
	models.write_log("Race {}: {} results are loaded".format(race, len(new_results)))
	return len(new_results), runners_touched

# Returns <success?>, <results loaded>, <runners touched>
def reload_parkrun_results(race: models.Race, user: User) -> Tuple[bool, int, int]:
	protocol = race.event.document_set.filter(document_type=models.DOC_TYPE_PROTOCOL).first()
	if protocol:
		url_results = protocol.url_source
		if url_results:
			runners_touched = set(result.runner for result in race.result_set.all().select_related('runner__user__user_profile') if result.runner)
			n_results, runners_touched_2 = load_race_results(race, url_results, user)
			runner_stat.update_runners_and_users_stat(runners_touched | runners_touched_2)
			return True, n_results, len(runners_touched)
	return False, 0, 0

def reload_parkrun_results_for_date(date: datetime.date):
	for race in models.Race.objects.filter(event__series__is_weekly=True, event__start_date=date, distance=PARKRUN_DISTANCE).select_related('event').order_by('event__name'):
		success, n_results, _ = reload_parkrun_results(race, models.USER_ROBOT_CONNECTOR)
		print(race.event.name, success, n_results)

# Creates new event and new race if needed
def get_or_create_parkrun_event_and_race(
		series: models.Series,
		url_results: str,
		event_date: datetime.date,
		start_time: Optional[str],
		event_num: Optional[int],
		user: User) -> Tuple[bool, models.Race]:
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
			name=name
		)
		event.clean()
		event.save()
	else:
		existed = True
		race = models.Race.objects.filter(event=event, distance=PARKRUN_DISTANCE).first()
	if url_results and not event.document_set.filter(document_type=models.DOC_TYPE_PROTOCOL).exists():
		models.Document.objects.create(event=event, document_type=models.DOC_TYPE_PROTOCOL,
			loaded_type=models.LOAD_TYPE_NOT_LOADED, url_source=url_results, created_by=user)
	if not race:
		race = models.Race.objects.create(event=event, distance=PARKRUN_DISTANCE, created_by=user)
		race.clean()
		race.save()
	return existed, race

# Creates new event and new race. Returns True(no results yet)/False(results are already loaded) and race id
def create_future_events(series, user, debug=False, ignore_last_event_date=False):
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
		existed, race = get_or_create_parkrun_event_and_race(series, '', event_date, last_event.start_time, event_number, user)
		if not existed:
			events_created += 1
		if event_number:
			event_number += 1
		event_date += datetime.timedelta(days=7)
	return events_created

# Creates events for old parkrun series
def create_future_old_parkrun_events():
	series = models.Series.objects.get(pk=results_util.OLD_PARKRUN_SERIES_ID)
	events_created = 0
	event = series.event_set.order_by('-start_date').first()
	event_date = event.start_date + datetime.timedelta(days=7)
	while (event_date.year <= 2017) and (events_created < 100): 
		event.start_date = event_date
		event.id = None
		event.clean()
		event.save()
		race = models.Race.objects.create(event=event, distance=PARKRUN_DISTANCE, created_by=models.USER_ROBOT_CONNECTOR)
		race.clean()
		race.save()
		event_date += datetime.timedelta(days=7)
		events_created += 1
	print('Events created:', events_created)

def get_series_history_url(series: models.Series) -> str:
	return series.url_site.rstrip('/') + '/results/eventhistory/'

def get_event_url(series: models.Series, number: int) -> str:
	return series.url_site.rstrip('/') + f'/results/{number}'

# Check: Are there any new runs with current series that are not in base? If yes, load them.
def update_series_results(series, user, update_runners_stat=True):
	new_races = []
	url_history = get_series_history_url(series)
	result, html, _, _, error = results_util.read_url(url_history, from_file=READ_FILES_NOT_URLS)
	if not result:
		models.send_panic_email(
			'views_parkrun: update_series_results: problem with event history',
			f'Could not load event history for parkrun {series.name}, id={series.id}, from url {url_history}: {error}')
		return [], set()
	new_races_created = False
	runners_touched = set()
	for group in parkrun_result_history_re.finditer(html):
		groupdict = group.groupdict()
		event_num = results_util.int_safe(groupdict['number'])

		event_date = datetime.date(results_util.int_safe(groupdict['year']), results_util.int_safe(groupdict['month']), results_util.int_safe(groupdict['day']))
		url_results = get_event_url(series, event_num)
		existed, race = get_or_create_parkrun_event_and_race(series, url_results, event_date, results_util.DEFAULT_PARKRUN_START_TIME, event_num, user)
		if race.load_status != models.RESULTS_LOADED:
			models.write_log(f'New event found: {group}')
			n_results, new_runners_touched = load_race_results(race, url_results, user)
			runners_touched |= new_runners_touched
			new_races.append((race, n_results, existed))
			if not existed:
				new_races_created = True
		else:
			if new_races_created: # Maybe there were some extra parkruns, e.g. for New Year/Christmas
				fix_parkrun_numbers(race.event_id)
			break
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

def fix_parkrun_numbers(correct_event_id=None, correct_event=None): # Enter id of last event (or last event itself) in series with correct number
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

# In October 2019 parkrun changed the URLs of result pages:
#    https://www.parkrun.ru/timiryazevsky/weeklyresults/?runSeqNumber=233
# -> https://www.parkrun.ru/timiryazevsky/results/weeklyresults/?runSeqNumber=233
def fix_parkrun_protocol_urls():
	n_fixed = 0
	for doc in models.Document.objects.filter(document_type=models.DOC_TYPE_PROTOCOL,
			url_source__startswith='http://www.parkrun.ru'):
		doc.url_source = doc.url_source.replace('http://', 'https://')
		doc.save()
		n_fixed += 1
	print(('https is added: {} protocols'.format(n_fixed)))

	n_fixed = 0
	for doc in models.Document.objects.filter(document_type=models.DOC_TYPE_PROTOCOL,
			url_source__contains='//weeklyresults'):
		doc.url_source = doc.url_source.replace('//weeklyresults', '/results/weeklyresults')
		doc.save()
		n_fixed += 1
	print(('// to /results: {} protocols'.format(n_fixed)))

	n_fixed = 0
	for doc in models.Document.objects.filter(document_type=models.DOC_TYPE_PROTOCOL,
			url_source__contains='/weeklyresults').exclude(url_source__contains='/results/weeklyresults'):
		doc.url_source = doc.url_source.replace('/weeklyresults', '/results/weeklyresults')
		doc.save()
		n_fixed += 1
	print(('/results added: {} protocols'.format(n_fixed)))

def test_regexp():
	# url_results = 'https://www.parkrun.ru/volgogradpanorama/results/weeklyresults/?runSeqNumber=199'
	url_results = 'https://www.parkrun.ru/stavropol/results/eventhistory/'
	result, html, _, _, error = results_util.read_url(url_results)
	if not result:
		print(f'Could not load results from url {url_results}: {error}')
		return
	for i, obj in enumerate(parkrun_result_history_re.finditer(html)):
		print(('{}. {}'.format(i, ', '.join('{}: {}'.format(k, v.strip() if v else v) for k, v in list(obj.groupdict().items())))))

# If some parkrun didn't happen, we remove it and fix the numbers
def _delete_skipped_parkrun(race: models.Race) -> Tuple[bool, str]:
	event = race.event
	series = event.series
	if not series.is_russian_parkrun():
		return False, 'Это — не российский паркран'
	races_count = event.race_set.count()
	if races_count != 1:
		return False, 'Дистанций у забега {}, а не одна. Что-то не так'.format(races_count)
	if race.result_set.exists():
		return False, 'У забега уже есть загруженные результаты'
	if event.document_set.filter(document_type=models.DOC_TYPE_PROTOCOL).exists():
		return False, 'У забега уже есть протокол'
	race.delete()
	prev_event = series.event_set.filter(start_date__lt=event.start_date).order_by('-start_date').first()
	event.delete()
	if prev_event:
		fix_parkrun_numbers(correct_event=prev_event)
	return True, ''

@views_common.group_required('admins')
def delete_skipped_parkrun(request, race_id):
	race = get_object_or_404(models.Race, pk=race_id)
	series = race.event.series
	success, error = _delete_skipped_parkrun(race)
	if success:
		messages.success(request, 'Паркран успешно удалён. Номера последующих паркранов исправлены')
		return redirect(series)
	else:
		messages.warning(request, 'Паркран не удалён. Причина: {}'.format(error))
		return redirect(race)

def delete_parkruns_since(series_id: int, date: datetime.date):
	series = get_object_or_404(models.Series, pk=series_id)
	if series.create_weekly:
		print('Этот паркран сейчас не закрыт')
		return
	for event in series.event_set.filter(start_date__gte=date).order_by('-start_date'):
		print(event.start_date, _delete_skipped_parkrun(event.race_set.all()[0]))

# Because parkrun banned our server
def print_active_parkrun_series():
	for series in models.Series.get_russian_parkruns().filter(create_weekly=True).order_by('name'):
		print(get_series_history_url(series))
