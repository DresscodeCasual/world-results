from django.shortcuts import get_object_or_404, redirect
from django.contrib.auth.models import User
from django.contrib import messages
import datetime
import json
import re
import time

from typing import Any, Dict, List, Optional, Set, Tuple

from results import models, results_util
from editor import runner_stat
from editor.scrape import s95
from . import generators
from .views import views_common, views_parkrun, views_result, views_stat

READ_FILES_NOT_URLS = False

def get_empty_parkruns():
	series_ids = set(models.Series.objects.filter(is_weekly=True).values_list('pk', flat=True))
	month_ago = datetime.date.today() - datetime.timedelta(days=30)
	return models.Race.objects.filter(event__series_id__in=series_ids, event__start_date__lte=month_ago).exclude(
		n_participants_finished__gt=0).select_related('event')

def send_update_results(new_series: List[models.Series], new_races: List[Tuple[models.Race, int, bool]], future_events_created: int, errors: List[str]) -> Dict[Any, Any]:
	body = 'Добрый день!'
	if errors:
		body += f'\n\nСлучились следующие ошибки:'
		for i, error in enumerate(errors):
			body += f'\n{i+1}. {error}'

	if new_series:
		body += f'\n\nДобавлены на сайт {len(new_series)} новых серий:\n'
		for i, series in enumerate(new_series):
			body += f'\n{i+1}. {results_util.SITE_URL}{series.get_absolute_url()} — {series.name}, {series.url_site}'

	if new_races:
		body += f'\n\nЗагружены результаты {len(new_races)} еженедельных забегов:\n'
		i = 1
		for race, n_results, existed in new_races:
			body += (f'\n{i}. {race.event.start_date} – {race.event}, {race.event.series.url_site}, {results_util.SITE_URL}{race.get_absolute_url()},'
				 +  f' {n_results} результат{results_util.ending(n_results, 1)}')
			if not existed:
				body += ' (этого забега не было в календаре!)'
			i += 1

	if future_events_created:
		body += f'\n\nСоздано {future_events_created} будущих забегов.'

	for race in get_empty_parkruns():
		s = '\n\nНайден забег без результатов: {} {} {}{}'.format(race.event.name, race.event.start_date, results_util.SITE_URL, race.get_absolute_url())

	body += "\n\nНа сегодня это всё. До связи!\nВаш робот."

	message_from_site = models.Message_from_site.objects.create(
		message_type=models.MESSAGE_TYPE_FROM_ROBOT,
		title='World Results: результаты закачки еженедельных забегов',
		body=body,
	)
	return message_from_site.try_send()

def update_weekly_events() -> str:
	errors = []
	new_series, new_races, future_events_created, error = s95.update_weekly_results()
	if error:
		errors.append(error)

	# new_races2, future_events_created2 = views_parkrun.update_parkrun_results()
	# new_races += new_races2
	# future_events_created += future_events_created2

	if new_series or new_races or future_events_created:
		return str(send_update_results(new_series, new_races, future_events_created, errors))
	print(errors)
	return 'За неделю ничего не произошло.'

class WeeklySeries(object):
	def __init__(self, series: models.Series):
		self.series = series
	def update_weekly_results(self) -> Tuple[List[models.Series], List[Tuple[models.Race, int, bool]], int, str]:
		raise NotImplementedError()

	def create_future_events(self, series, user, debug=False) -> int:
		raise NotImplementedError()

	def get_or_create_event_and_race(
			self,
			series: models.Series,
			url_results: str,
			event_date: datetime.date,
			start_time: Optional[str],
			event_num: Optional[int],
			user: User) -> Tuple[bool, models.Race]:
		raise NotImplementedError()

	# Load results for given race from given URL with json.
	# Returns the number of loaded results and the set of touched runners.
	def load_race_results(self, race: models.Race, url_results: str, user: User) -> Tuple[int, Set[models.Runner]]:
		raise NotImplementedError()

	# Returns <success?>, <results loaded>, <runners touched>
	def reload_race_results(self, race: models.Race, user: User) -> Tuple[bool, int, int]:
		protocol = race.event.document_set.filter(document_type=models.DOC_TYPE_PROTOCOL).first()
		if protocol:
			url_results = protocol.url_source
			if url_results:
				runners_touched = set(result.runner for result in race.result_set.all().select_related('runner__user__user_profile') if result.runner)
				n_results, runners_touched_2 = self.load_race_results(race, url_results, user)
				runner_stat.update_runners_and_users_stat(runners_touched | runners_touched_2)
				return True, n_results, len(runners_touched)
		return False, 0, 0
	@classmethod
	def init(cls, series):
		if series.url_site.startswith(results_util.RUSSIAN_PARKRUN_SITE):
			return ParkrunSeries(series)
		if series.url_site.startswith(results_util.S95_SITE):
			return S95Series(series)
		return None

class ParkrunSeries(WeeklySeries):
	parkrun_result_re = re.compile(r'<tr[^>]*><td[^>]*>(?P<place>\d+)</td><td[^>]*><div[^>]*><a href="[a-z0-9:./]*/parkrunner/(?P<parkrun_id>\d+)"[^>]*>(?P<name>[^<]+)</a></div><div[^>]*>[^<]*<span[^>]*><span[^>]*>[^<]*</span><span[^>]*>(?P<gender>[^<]+)</span>\d+<span[^>]*>[^<]*</span></span>(<span[^>]*>[^<]*</span><a [^>]*>[^<]*</a>)*</div><div[^>]*><div[^>]*><a [^>]*>(?P<category>[^<]+)</a><span[^>]*>[^<]*</span>[^<]*</div></div>(<div[^>]*><div[^>]*><a [^>]*>(?P<club>[^<]+)</a></div></div>)*</td><td[^>]*><div[^>]*>[^<]*</div><div[^>]*>(?P<place_gender>\d+)<span[^>]*>[^<]*</span></div></td><td[^>]*><div[^>]*><a [^>]*>[^<]*</a></div><div[^>]*>[^<]*</div></td><td[^>]*>(<div[^>]*><a [^>]*>[^<]*</a></div>)*[^<]*</td><td[^>]*><div[^>]*>(?P<result>[^<]+)</div><div[^>]*><span[^>]*>(?P<comment1>[^<]*)</span>(?P<comment2>[^<]*)')
	parkrun_result_history_re = re.compile(r'<a href="\.\./(?P<number>\d+)"><span[^>]+>(?P<day>\d+)/(?P<month>\d+)/(?P<year>\d+)</span>')
	def get_series_history_url(self) -> str:
		return self.series.url_site.rstrip('/') + '/results/eventhistory/'
	def get_event_url(self, number: int) -> str:
		return self.series.url_site.rstrip('/') + f'/results/{number}'
	# correct_event_id must be an id of event in series with a correct number.
	# Returns the number of fixed events.
	def fix_parkrun_numbers(self, correct_event_id=None, correct_event=None) -> int:
		if correct_event is None:
			correct_event = models.Event.objects.get(pk=correct_event_id, series_id=self.series.id)
		last_correct_date = correct_event.start_date
		cur_number = correct_event.number
		n_fixed_parkruns = 0
		for event in self.series.event_set.filter(start_date__gt=last_correct_date).order_by('start_date'):
			cur_number += 1
			event.number = cur_number
			correct_name = '{} №{}'.format(self.series.name, cur_number)
			if event.name != correct_name:
				event.name = correct_name
				event.save()
				n_fixed_parkruns += 1
		return n_fixed_parkruns
	# Check: Are there any new runs with current series that are not in base? If yes, load them.
	# Returns:
	# * List of races loaded: <Race, n_results, did it exist?>,
	# * Set of runners touched.
	def update_results(self, user, update_runners_stat=True) -> Tuple[List[Tuple[models.Race, int, bool]], Set[models.Runner]]:
		new_races = []
		url_history = self.get_series_history_url()
		result, html, _, _, error = results_util.read_url(url_history, from_file=READ_FILES_NOT_URLS)
		if not result:
			models.send_panic_email(
				'views_parkrun: update_series_results: problem with event history',
				f'Could not load event history for parkrun {self.series.name}, id={self.series.id}, from url {url_history}: {error}')
			return [], set()
		new_races_created = False
		runners_touched = set()
		for group in self.parkrun_result_history_re.finditer(html):
			groupdict = group.groupdict()
			event_num = results_util.int_safe(groupdict['number'])

			event_date = datetime.date(results_util.int_safe(groupdict['year']), results_util.int_safe(groupdict['month']), results_util.int_safe(groupdict['day']))
			url_results = self.get_event_url(event_num)
			existed, race = self.get_or_create_event_and_race(url_results, event_date, results_util.DEFAULT_PARKRUN_START_TIME, event_num, user)
			if race.load_status != models.RESULTS_LOADED:
				models.write_log(f'New event found: {group}')
				n_results, new_runners_touched = self.load_race_results(race, url_results, user)
				runners_touched |= new_runners_touched
				new_races.append((race, n_results, existed))
				if not existed:
					new_races_created = True
			else:
				if new_races_created: # Maybe there were some extra parkruns, e.g. for New Year/Christmas
					self.fix_parkrun_numbers(race.event_id)
				break
		if update_runners_stat:
			runner_stat.update_runners_and_users_stat(runners_touched)
		return new_races, runners_touched

	def create_future_events(self, user, debug=False) -> int:
		raise NotImplementedError()

	def get_or_create_event_and_race(
			self,
			url_results: str,
			event_date: datetime.date,
			start_time: Optional[str],
			event_num: Optional[int],
			user: User) -> Tuple[bool, models.Race]:
		raise NotImplementedError()

	# Load results for given race from given URL with json.
	# Returns the number of loaded results and the set of touched runners.
	def load_race_results(self, race: models.Race, url_results: str, user: User) -> Tuple[int, Set[models.Runner]]:
		raise NotImplementedError()
	@classmethod
	def all_series(cls):
		return models.Series.get_russian_parkruns()
	@classmethod
	# 1. Updates all results of all series from given source;
	# 2. Creates future events in relevant series;
	# 3. Returns:
	# * List of just created events, with <number of just lodad results> and <did the race exist before>
	# * Number of just created future events
	# * Error, if any
	def update_weekly_results(cls) -> Tuple[List[Tuple[models.Race, int, bool]], int, str]:
		new_races = []
		runners_touched = set()
		future_events_created = 0
		for series in models.Series.get_russian_parkruns().filter(create_weekly=True).order_by('id'):
			try:
				races, runners = cls(series).update_results(models.USER_ROBOT_CONNECTOR, update_runners_stat=False)
				new_races += races
				runners_touched |= runners
			except FileNotFoundError:
				pass
			if not READ_FILES_NOT_URLS:
				time.sleep(6)

		for series in models.Series.objects.filter(create_weekly=True):
			future_events_created += cls(series).create_future_events(models.USER_ROBOT_CONNECTOR)
		runner_stat.update_runners_and_users_stat(runners_touched)
		views_stat.update_results_count()
		views_stat.update_events_count()
		generators.generate_parkrun_stat_table()
		return new_races, future_events_created


class S95Series(WeeklySeries):
	# Load results for given race from given URL with json.
	# Returns the number of loaded results and the set of touched runners.
	def load_race_results(self, race: models.Race, url_results: str, user: User) -> Tuple[int, Set[models.Runner]]:
		if not url_results.startswith(results_util.S95_SITE):
			models.write_log(f'Could not load results for {race.event}, id={race.event.id}, from url {url_results}: not a valid protocol URL')
			return 0, set()
		if url_results[-5:] != '.json':
			if url_results[-1] == '/':
				url_results = url_results[:-1]
			url_results += '.json'
		result, html, _, _, error = results_util.read_url(url_results)
		if not result:
			models.write_log(f'Could not load results for {race.event}, id={race.event.id}, from url {url_results}: {error}')
			return 0, set()
		data = json.loads(html)

		race.result_set.filter(source=models.RESULT_SOURCE_DEFAULT).delete()
		results_added = 0
		runners_touched = set()
		new_results = []

		for result_dict in data['results']:
			lname, fname, midname = views_result.split_name(result_dict['athlete']['name'].strip().title(), first_name_position=0)
			gender = results_util.GENDER_UNKNOWN
			gender_raw = result_dict['athlete'].get('gender')
			if gender_raw:
				gender = results_util.string2gender(gender_raw.strip())
				if gender == models.GENDER_UNKNOWN:
					models.send_panic_email(
						'parse_s95: load_race_results: problem with gender',
						f'Problem with race id {race.id}, url {url_results} : gender "{result_dict["athlete"]["gender"]}" cannot be parsed')
			
			runner = None
			parkrun_id = result_dict['athlete'].get('parkrun_code')
			if parkrun_id:
				kwargs = results_util.get_parkrun_or_verst_dict(parkrun_id)
				runner, created = models.Runner.objects.get_or_create(
					**kwargs,
					defaults={'lname': lname, 'fname': fname, 'midname': midname, 'gender': gender}
				)
				if created:
					models.log_obj_create(user, runner, models.ACTION_CREATE, comment=f'При обработке протокола {url_results}', verified_by=user)

			centiseconds = models.string2centiseconds(result_dict['total_time'])
			if centiseconds == 0:
				models.send_panic_email(
					'parse_s95: load_race_results: problem with time',
					f'Problem with race id {race.id}, url {url_results} : time "{result_dict["total_time"]}" cannot be parsed')

			new_results.append(models.Result(
				race=race,
				runner=runner,
				user=runner.user if runner else None,
				parkrun_id=parkrun_id,
				name_raw=result_dict['athlete']['name'],
				time_raw=result_dict['total_time'],
				club_raw=result_dict['athlete'].get('club', ''),
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
				loaded_by=user,
			))
			if runner:
				runners_touched.add(runner)

		models.Result.objects.bulk_create(new_results)
		views_result.fill_places(race)
		views_result.fill_race_headers(race)
		if len(new_results) > 0:
			race.load_status = models.RESULTS_LOADED
			race.save()
		return len(new_results), runners_touched

class VerstSeries(WeeklySeries):
	@classmethod
	def all_series(cls):
		return models.Series.filter(url_site__startswith=results_util.VERST_SITE)

@views_common.group_required('admins')
def reload_race_results(request, race_id):
	race = get_object_or_404(models.Race, pk=race_id)
	series = race.event.series
	weekly_obj = WeeklySeries.init(series)
	if weekly_obj is None:
		messages.warning(request, f'Не умеем перезагружать результаты забегов из серии «{series.name}» ({results_util.SITE_URL}{series.get_absolute_url()})')
		return redirect(race)
	success, n_results, n_runners_touched = weekly_obj.reload_race_results(race, request.user)
	if success:
		messages.success(request, f'Результаты загружены заново. Всего результатов: {n_results}, затронуто бегунов: {n_runners_touched}')
	else:
		messages.warning(request, 'Протокол забега не найден. Результаты не перезагружены')
	return redirect(race)

def reload_old_s95():
	races = models.Race.objects.filter(event__series__url_site__startswith=results_util.S95_SITE, loaded=models.RESULTS_LOADED)
	race_ids = set(races.values_list('pk', flat=True))
	races_with_parkrunid = set(models.Result.objects.filter(race_id__in=race_ids).exclude(parkrun_id=None).values_list('race_id', flat=True))
	print(race_ids - races_with_parkrunid, len(race_ids - races_with_parkrunid))
	for race_id in (race_ids - races_with_parkrunid):
		print(race_id, '...')
		race = models.Race.objects.get(pk=race_id)
		series = race.event.series
		weekly_obj = WeeklySeries.init(series)
		if weekly_obj is None:
			print(f'Не умеем перезагружать результаты забегов из серии «{series.name}» ({results_util.SITE_URL}{series.get_absolute_url()})')
			continue
		success, n_results, n_runners_touched = weekly_obj.reload_race_results(race, models.USER_ROBOT_CONNECTOR)
		print(race_id, success, n_results, n_runners_touched)
