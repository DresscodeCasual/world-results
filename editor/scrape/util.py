from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from collections import defaultdict
from dataclasses import dataclass, field
import datetime
import io
import json
import os
import pathlib
import requests
import time
from typing import Optional

from results import models, results_util
from editor import parse_protocols, runner_stat
from editor.views import views_result

FILE_TYPE_DOWNLOADED = 1
FILE_TYPE_STANDARD_FORM = 2
DIR_FOR_FILE_TYPE = {
	FILE_TYPE_DOWNLOADED: 'downloaded',
	FILE_TYPE_STANDARD_FORM: 'standard_form'
}

ATTEMPT_TIMEOUT = datetime.timedelta(hours=5)

WAIT_BEFORE_LOADING = datetime.timedelta(days=7)

ACTIVE_PLATFORM_IDS = (
	'nyrr',
	'mikatiming',
	'athlinks',
	'baa',
)

EVENTS_WITH_WRONG_DATE = frozenset([
	'https://www.athlinks.com/event/1744/results/Event/560979/Results', # Series API says it is in 2016, while event API is wrong and says 2017.
])

MAX_PARKRUN_ID = 99999999 # To distinguish them from 5verst codes.

class RetryableError(Exception):
	pass

class TimeoutError(RetryableError): # When the script successfully worked for more than ATTEMPT_TIMEOUT. We then continue the same attempt again.
	pass

PAUSE_BEFORE_RETRY = datetime.timedelta(hours=1)
class WaitAndRetryError(RetryableError): # When we want to wait for 1 hour and then automatically retry.
	pass

class NonRetryableError(Exception):
	pass

class JsonParsingError(NonRetryableError): # When Json from Athlinks has some unexpected value.
	pass

class IncorrectURL(NonRetryableError):
	pass

def alphanumeric_or_underscore(char: str) -> str:
	return char if ((ord('A') <= ord(char) <= ord('Z')) or (ord('0') <= ord(char) <= ord('9'))) else '_'

# Returns the shard for the runner (i.e. the subdirectory where we store their data)
# based on the runner id on some platform.
# We take two last symbols of its ID in upper case, and replace non-alphanumeric symbols
# with underscores.
def runner_shard(runner_id: str) -> str:
	if not runner_id:
		raise RuntimeError('runner ID cannot be empty')
	stripped = runner_id.strip()
	if stripped != runner_id:
		raise RuntimeError(f'runner ID "{runner_id}" cannot start or end with a space')
	last_symbols = stripped[-2:]
	return ''.join(alphanumeric_or_underscore(char) for char in stripped[-2:].upper())

# Returns maximal and minimal possible birthday of a person given their todays age.
def MaxBirthday(today: datetime.date, age_today: int) -> datetime.date:
	try:
		return today.replace(year = today.year - age_today)
	except ValueError:
		return today - (datetime.date(today.year, 3, 1) - datetime.date(today.year - age_today, 3, 1))
def MinBirthday(today: datetime.date, age_today: int) -> datetime.date:
	try:
		return today.replace(year = today.year - age_today - 1) + datetime.timedelta(days=1)
	except ValueError:
		return today - (datetime.date(today.year, 3, 1) - datetime.date(today.year - age_today - 1, 3, 1)) + datetime.timedelta(days=1)

# Sometimes sites specify weird race lengths, maybe because of some miles->km calculations.
def FixLength(length: int) -> int:
	if length == 21082:
		return 21098
	if length == 21097:
		return 21098
	if length == 42165:
		return 42195
	return length

def AddMinute(tm):
    fulldate = datetime.datetime(100, 1, 1, tm.hour, tm.minute, tm.second)
    fulldate = fulldate + datetime.timedelta(minutes=1)
    return fulldate.time()

# Returns the next events per platform_id to work on.
def EventQueue(platform_id: str):
	# We don't try to load events that ended less than 10 days ago, so that the results can settle.
	earliest_to_process = datetime.date.today() - datetime.timedelta(days=10)
		# For NYRR, let's start with the latest events.
	ordering = '-id' if (platform_id == 'nyrr') else 'id'
	return models.Scraped_event.objects.filter(
			Q(dont_retry_before=None) | Q(dont_retry_before__lt=timezone.now()),
			platform_id=platform_id,
			result=models.DOWNLOAD_NOT_STARTED,
		).exclude(start_date__gte=earliest_to_process).order_by(ordering)

# Returns the directory where to store provided type of data.
# Every file that we want to save is associated with a series, an event, or a runner.
def dir(file_type: int,
		platform_id: str,
		platform_series_id: Optional[str] = None,
		platform_event_id: Optional[str] = None,
		platform_runner_id: Optional[str] = None) -> pathlib.Path:
	if not platform_series_id and not platform_runner_id:
		raise RuntimeError('Either series ID or runner ID must be non-empty')
	if platform_event_id and not platform_series_id:
		raise RuntimeError('If event ID is present, series ID must be non-empty')
	if platform_series_id and platform_runner_id:
		raise RuntimeError('You cannot specify both platform_series_id and platform_runner_id')
	res = pathlib.Path(settings.INTERNAL_FILES_ROOT) / DIR_FOR_FILE_TYPE[file_type] / platform_id
	if platform_series_id:
		res /= platform_series_id
		if platform_event_id:
			res /= platform_event_id
	elif platform_runner_id:
		res /= 'runners'
		res /= runner_shard(platform_runner_id)
	return res

def RemovePrefix(text, prefix):
    if text.startswith(prefix):
        return text[len(prefix):]
    return text

def RemoveSuffix(text, suffix):
    if text.endswith(suffix):
        return text[:-len(suffix)]
    return text

def url2filename(url: str, method: str = 'GET', params: dict[str, any] = {}) -> str:
	res = RemovePrefix(RemovePrefix(url, 'https://'), 'http://').replace('/', '_').replace('?', '_').replace('=', '_').replace('.', '_').replace('&', '_')
	delimiter = '_' if (method == 'GET') else '#'
	params_str = ''
	for key, val in sorted(params.items()):
		if val:
			params_str += f'{delimiter}{key}{delimiter}{val}'
	# We want POST params to always be present in the file name.
	return res[:(250 - len(params_str))] + params_str

# Should we load to the DB the results of the event with provided name?
def ToLoadResults(race_name: str) -> bool:
	race_name = race_name.lower()
	return (
		('shuttle service' not in race_name)
		and ('metrorail easy ticket' not in race_name)
		and race_name != 'vip'
		and ('эстафета' not in race_name)
		and ('relay' not in race_name)
		and ('realy' not in race_name)
		and ('duo team' not in race_name)
	)

def IsForHandicapped(race_name: str) -> bool:
	return results_util.anyin(race_name.lower(), ('wheelchair', 'handcycle', 'push assist', 'physically challenged'))

def TryGetJson(req: requests.Response, is_json: bool=True) -> tuple[any, str]:
	N_REPEATS = 3
	res = {}
	for i in range(N_REPEATS):
		res = req.json() if is_json else req.text
		if i > N_REPEATS / 2:
			print(f'{datetime.datetime.now()} {req.url}: making attempt No {i+1}')
		if True:
			return res, req.url
		time.sleep(i*i+1)
	err_text = f'{req.url} returned bad json {N_REPEATS} times in a row'
	raise RuntimeError(err_text)

def IsJsonWithTransientError(content) -> bool:
	if not isinstance(content, dict):
		return False
	if content.get('success') == False:
		return True
	message = str(content.get('message', '')).lower()
	if message == 'internal server error':
		return True
	if message.startswith(('unable to get metadata', 'unable to acquire metadata')):
		return True
	return False

def LoadAndStore(mydir: pathlib.Path,
		url: str,
		method: str = 'GET',
		params: dict[str, any] = {},
		allow_empty_result: bool=False,
		is_json: bool=True,
		arg_for_post_data: str='json', # In most cases 'json' works, but baa.com needs 'data', I don't know why.
		debug=0) -> any:
	path = mydir / url2filename(url, method, params)
	if os.path.isfile(path) and (os.path.getsize(path) > 0):
		if debug > 0:
			print(f'Reading URL {url}; {method}; {params} (from file)')
		with io.open(path, encoding="utf8") as file_in:
			return json.load(file_in) if is_json else file_in.read()

	mydir.mkdir(parents=True, exist_ok=True)
	# os.chmod(mydir, 0o770)
	if debug > 0:
		print(f'Reading URL {url}; {method}; {params} (from web)')
	if method == 'GET':
		req = results_util.session.get(url, params=params)
	else:
		req = results_util.session.post(url, **{arg_for_post_data: params})
	res, _ = TryGetJson(req, is_json=is_json)
	if not res:
		if allow_empty_result:
			return None
		raise NonRetryableError(f'URL {url} with params {params} returned empty json. Path not found: {path}')
	if not IsJsonWithTransientError(res): # Otherwise, it may be a transient error. We don't want to cache such results.
		with io.open(path, "w", encoding="utf8") as json_out:
			if is_json:
				json.dump(
					res,
					json_out,
					ensure_ascii=False,
					sort_keys=True,
					indent=4
				)
			else:
				json_out.write(res)
	time.sleep(1)
	return res	

def IsVirtual(name: str) -> bool:
	return 'virtual' in name.lower()

# Receives:
# * ids - a dict of pairs <platform_id, value>,
# * fields_to_fill - a dict of Runner model fields with values to fill in a new or existing runner.
# Tries to find/create a runner with all of them (maybe by merging some existing runners).
# Returns:
# * A runner with all these platform connections,
# * A list of warnings to add to a email to admins.
# Raises an exception if this will need to merge two runners with different IDs from the same platform.
def RunnerWithPlatformIDs(ids: dict[str, int], fields_to_fill: dict[str, int], result_desc: str) -> tuple[models.Runner, list[str]]:
	if not ids:
		raise Exception(f'RunnerWithPlatformIDs: {result_desc}: ids cannot be empty')
	platforms_to_add = set()
	platforms_mentioned_in_runners = {} # platform_id -> value
	runners_to_merge = set() # Tuples: (runner, <number of its platforms>)
	messages = []
	# 1. We find all existing runners with provided platform IDs, and check if platforms intersect.
	for platform_id, value in sorted(ids.items()):
		if platform_id in platforms_mentioned_in_runners:
			if value == platforms_mentioned_in_runners[platform_id]:
				# We already know that this runner should have this platform_id->value. Nothing to do.
				continue
			else:
				raise Exception(f'RunnerWithPlatformIDs: {result_desc}: cannot process {ids}: platform {platform_id} is met twice, '
					+ f'with values {value} and {platforms_mentioned_in_runners[platform_id]}')
		runner_platform = models.Runner_platform.objects.filter(platform_id=platform_id, value=value).first()
		if not runner_platform:
			platforms_to_add.add(platform_id)
			continue
		runner = runner_platform.runner
		runner_platforms = list(runner.runner_platform_set.all())
		for r_p in runner_platforms:
			if (r_p.platform_id in platforms_mentioned_in_runners) and (r_p.value != platforms_mentioned_in_runners[r_p.platform_id]):
				raise Exception(f'RunnerWithPlatformIDs: {result_desc}: cannot process {ids}: platform {r_p.platform_id} is met twice, '
					+ f'with values {r_p.value} and {platforms_mentioned_in_runners[r_p.platform_id]}')
		# We start adding ids to platforms_mentioned_in_runners only after the loop finishes: if a runner has two values at some platform,
		# we don't want to raise an exception.
		runners_to_merge.add((runner, len(runner_platforms)))
		for r_p in runner_platforms:
			if r_p not in platforms_mentioned_in_runners:
				platforms_mentioned_in_runners[r_p.platform_id] = r_p.value

	# 2. We merge all found runners, or create the new one.
	runner = models.Runner()
	if runners_to_merge:
		runners_ordered = sorted(runners_to_merge, key=lambda x: -x[1]) # We keep the runner with most connections
		runner, _ = runners_ordered[0]
		for r, _ in runners_ordered[1:]:
			success, error = runner.merge(r)
			if not success:
				raise Exception(f'RunnerWithPlatformIDs: {result_desc}: We could not merge runner {r} (id {r.id}) into {runner} (id {runner.id}): {error}')
			if error:
				messages.append(error)

	# 3. Add new fields to the runner.
	fields_changed = []
	for field, new_val in fields_to_fill.items():
		cur_val = getattr(runner, field)
		if cur_val == new_val:
			continue
		if cur_val:
			messages.append(
				f'RunnerWithPlatformIDs: {result_desc}: when updating {field} for runner {runner} (id {runner.id}): old value "{cur_val}", new value "{new_val}"')
			continue
		setattr(runner, field, new_val)
		fields_changed.append(field)
	if not runner.id:
		runner.save()
		models.log_obj_create(models.USER_ROBOT_CONNECTOR, runner, models.ACTION_CREATE, verified_by=models.USER_ROBOT_CONNECTOR,
			comment='from RunnerWithPlatformIDs')
	elif fields_changed:
		runner.save()
		models.log_obj_create(models.USER_ROBOT_CONNECTOR, runner, models.ACTION_UPDATE, verified_by=models.USER_ROBOT_CONNECTOR, field_list=fields_changed,
			comment='from RunnerWithPlatformIDs')

	# 4. Add remaining platform IDs.
	for platform_id in platforms_to_add:
		models.Runner_platform.objects.create(platform_id=platform_id, runner=runner, value=ids[platform_id])
	return runner, messages

@dataclass
class Scraper:
	attempt: models.Download_attempt
	url: str = ''
	platform_series_id: Optional[str] = None
	platform_event_id: Optional[str] = None
	series: Optional[models.Series] = None
	event: Optional[models.Event] = None
	protocol: Optional[models.Document] = None
	races_to_reload: list[int] = field(default_factory=list) # By default, we don't reload results for races that are already loaded.
	attempt_timeout: datetime.timedelta = ATTEMPT_TIMEOUT
	standard_form_dict: dict[str, any] = field(default_factory=dict)
	reason_to_ignore: str = '' # If non-empty, we do nothing with the event and don't raise an exception.
	debug: int = 0

	RACES_WITH_REPEATING_SPLIT_DISTANCES: set[int] = field(default_factory=set)
	KNOWN_BAD_BIBS: set[tuple[int, str]] = field(default_factory=set)
	KNOWN_BAD_PLATFORM_IDS: set[tuple[int, int]] = field(default_factory=set)
	RACES_WITH_BAD_BIBS: set[tuple[int, int]] = field(default_factory=set)

	# Are we already running for too long?
	def ToStopNow(self):
		return self.time_to_stop and (datetime.datetime.now() > self.time_to_stop)

	def EventYear(self):
		return datetime.date.fromisoformat(self.standard_form_dict['start_date']).year

	# The file path to store the whole event in the standard form.
	def StandardFormPath(self) -> pathlib.Path:
		platform_event_id = self.platform_event_id
		if self.attempt.scraped_event.extra_data:
			platform_event_id += f'_{self.attempt.scraped_event.extra_data}'
		return dir(
			file_type=FILE_TYPE_STANDARD_FORM,
			platform_id=self.PLATFORM_ID,
			platform_series_id=self.platform_series_id,
			platform_event_id=platform_event_id,

		) / 'event.json'

	# The directory to store all event-related downloaded files (usually json's and HTMLs).
	def DownloadedFilesDir(self, platform_runner_id: str = '') -> pathlib.Path:
		if platform_runner_id:
			return dir(
				file_type=FILE_TYPE_DOWNLOADED,
				platform_id=self.PLATFORM_ID,
				platform_runner_id=platform_runner_id,
			)
		return dir(
			file_type=FILE_TYPE_DOWNLOADED,
			platform_id=self.PLATFORM_ID,
			platform_series_id=self.platform_series_id,
			platform_event_id=self.platform_event_id,
		)

	def DumpStandardForm(self):
		path = self.StandardFormPath()
		path.parent.mkdir(parents=True, exist_ok=True)
		with io.open(path, "w", encoding="utf8") as file_out:
			json.dump(
				self.standard_form_dict,
				file_out,
				ensure_ascii=False,
				sort_keys=True,
				indent=1,
			)

	def SaveEventDetailsInStandardForm(self):
		raise NotImplementedError

	# Returns a reasonable finish date based on the dates in the standerd form.
	def FinishDate(self) -> Optional[datetime.date]:
		finish_date_str = self.standard_form_dict.get('finish_date')
		if not finish_date_str:
			return None
		start_date = datetime.date.fromisoformat(self.standard_form_dict['start_date'])
		res = datetime.date.fromisoformat(finish_date_str)
		# Sometimes there are crazy end dates in the jsons.
		if res <= start_date:
			return None
		if res > start_date + datetime.timedelta(days=14):
			return None
		return res

	def FillPlatformIdForEvent(self):
		if not self.platform_event_id:
			raise RuntimeError(f'FillPlatformIdForEvent called when platform_event_id is empty')
		if not self.event:
			raise RuntimeError(f'FillPlatformIdForEvent called when event is empty')
		if self.event.platform_id:
			if self.event.platform_id != self.PLATFORM_ID:
				raise RuntimeError(f'Event {self.event} already has ID {self.event.id_on_platform} on platform {self.event.platform_id}. We do not change platform to {self.PLATFORM_ID}')
			if self.event.id_on_platform != self.platform_event_id:
				event = self.event
				self.event = None
				raise RuntimeError(f'Event {event} already has ID {event.id_on_platform} on platform {event.platform_id}. We do not change ID to {self.platform_event_id}')
			return
		self.event.platform_id = self.PLATFORM_ID
		self.event.id_on_platform = self.platform_event_id
		self.event.save()

	def FillPlatformIdForSeries(self): # TODO
		raise NotImplementedError

	# Finds the series to use, creates it if it doesn't exist yet, and creates the Series_platform record.
	def FindOrCreateSeries(self):
		series = models.Series_platform.objects.filter(platform_id=self.PLATFORM_ID, value=self.platform_series_id).first()
		if not series:
			raise NonRetryableError(f'There are no series with ID {self.platform_series_id} on platform {self.PLATFORM_ID}')
		self.series = models.Series.get(pk=series_ids[0])

	# Finds the event to use, creates it if it doesn't exist yet, and fills the event.{platform_id,id_on_platform} fields.
	def FindOrCreateEvent(self):
		if self.protocol:
			if not self.protocol.event:
				raise RuntimeError(f'Protocol with id {self.protocol.id} has no event')
			if not self.protocol.url_source:
				raise RuntimeError(f'Protocol with id {self.protocol.id} has no URL')
			if self.protocol.document_type not in models.DOC_PROTOCOL_TYPES:
				raise RuntimeError(f'Protocol with id {self.protocol.id} has type {self.protocol.get_document_type_display()}')
			self.event = self.protocol.event
			self.FillPlatformIdForEvent()
			return
		platform_start_date = datetime.date.fromisoformat(self.standard_form_dict['start_date'])
		if self.event:
			if (self.event.start_date != platform_start_date) and (self.url not in EVENTS_WITH_WRONG_DATE):
				raise RuntimeError(f'Event date: {self.event.start_date}, platform date: {platform_start_date}')
			self.FillPlatformIdForEvent()
			return

		self.FindOrCreateSeries()
		events = self.series.event_set.filter(start_date=platform_start_date)
		if self.PLATFORM_ID == 'nyrr':
			# At NYRR, there can be several events with the same date.
			# Ideally, we want them to stay as different races under the same event. But it's too hard.
			events = events.filter(name=self.standard_form_dict['name'].replace(' - ', ' — '))
		n_events = events.count()
		if n_events > 1:
			events = events.filter(name=self.standard_form_dict['name'].replace(' - ', ' — '))
			if events.count() != 1:
				raise RuntimeError(f'There are {n_events} events at {platform_start_date} in series {self.series}. We do not know which to use')
		if n_events == 1:
			self.event = events[0]
			self.FillPlatformIdForEvent()
			return
		start_time = None
		if start_time_iso := self.standard_form_dict.get('start_time'):
			start_time = datetime.time.fromisoformat(start_time_iso).replace(microsecond=0)
			if (self.PLATFORM_ID == 'nyrr'):
				# Let's then add several minutes to create a unique (start_date, start_time) tuple.
				while self.series.event_set.filter(start_date=platform_start_date, start_time=start_time).exists():
					start_time = AddMinute(start_time)
		self.event = models.Event.objects.create(
			series=self.series,
			name=self.standard_form_dict['name'],
			start_date=platform_start_date,
			start_time=start_time,
			finish_date=self.FinishDate(),
			platform_id=self.PLATFORM_ID,
			id_on_platform=self.platform_event_id,
			created_by=models.USER_ROBOT_CONNECTOR,
		)
		models.log_obj_create(models.USER_ROBOT_CONNECTOR, self.event, models.ACTION_CREATE, verified_by=models.USER_ROBOT_CONNECTOR,
			comment='При автоматической загрузке результатов забега')

	def FindOrCreateProtocol(self):
		if self.protocol:
			return
		maybe_doc = self.event.document_set.filter(url_source=self.url, document_type__in=models.DOC_PROTOCOL_TYPES).first()
		if maybe_doc:
			self.protocol = maybe_doc
			return
		self.protocol = models.Document.objects.create(
			event=self.event,
			document_type=models.DOC_TYPE_PROTOCOL,
			hide_local_link=models.DOC_HIDE_ALWAYS,
			url_source=self.url,
		)
		models.log_obj_create(models.USER_ROBOT_CONNECTOR, self.event, models.ACTION_DOCUMENT_CREATE, child_object=self.protocol, verified_by=models.USER_ROBOT_CONNECTOR)

	def CreateRace(self, race_dict: dict[str, any]):
		dist_dict = race_dict['distance']
		precise_name = race_dict.get('precise_name', '')
		if dist_dict['length'] == 0:
			raise NonRetryableError(f'Race {precise_name} has distance length 0. We do not create it')
		distance, created = models.Distance.objects.get_or_create(distance_type=dist_dict['distance_type'], length=dist_dict['length'])
		if created:
			distance.name = distance.nameFromType()
			distance.save()
			models.log_obj_create(models.USER_ROBOT_CONNECTOR, distance, models.ACTION_CREATE, verified_by=models.USER_ROBOT_CONNECTOR,
				comment=f'While creating race {precise_name} for event {self.platform_event_id}')
		race = models.Race.objects.create(
			event=self.event,
			distance=distance,
			platform_id=self.PLATFORM_ID,
			id_on_platform=race_dict.get('id_on_platform', ''),
			precise_name=precise_name,
			is_for_handicapped=race_dict.get('is_for_handicapped') or IsForHandicapped(precise_name),
			is_virtual=race_dict.get('is_virtual', False),
			has_no_results=race_dict.get('is_virtual', False) or race_dict.get('has_no_results', False),
			created_by=models.USER_ROBOT_CONNECTOR,
		)
		models.log_obj_create(models.USER_ROBOT_CONNECTOR, self.event, models.ACTION_RACE_CREATE, child_object=race, verified_by=models.USER_ROBOT_CONNECTOR)
		race_dict['db_race_id'] = race.id

	def CreateRaces(self):
		for race_dict in self.standard_form_dict['races']:
			self.CreateRace(race_dict)

	# Compares existing races and the ones in standard_form_dict, and creates new races if needed.
	def MatchAndAddRacesInGroup(self, races: list[models.Race], race_dicts: list[dict[str, any]]):
		if self.debug > 0:
			print(f'Races: {races}')
			print(f'race_dicts: {[race_dict["precise_name"] for race_dict in race_dicts]}')
		if not race_dicts:
			# So there are races in our DB of this length, but the platform doesn't know about them. This is fine.
			return
		if len(races) > len(race_dicts):
			raise NonRetryableError(f'There are already {len(races)} races of length {races[0].distance.length} '
				+ f'at {results_util.SITE_URL}{races[0].event.get_absolute_url()} but just {len(race_dicts)} race_dicts at {self.url}')
		not_matched_races = {race.id: race for race in races}
		not_matched_race_dicts = {i: race_dict for i, race_dict in enumerate(race_dicts)}
		for race in races:
			if not race.precise_name:
				continue
			for i, race_dict in not_matched_race_dicts.items():
				if race_dict.get('precise_name', '') == race.precise_name:
					race_dict['db_race_id'] = race.id
					del not_matched_races[race.id]
					del not_matched_race_dicts[i]
					break
		if not not_matched_races:
			# So we found a race_dict for each existing race. We just need to create a race for each not matched race_dict.
			for race_dict in not_matched_race_dicts.values():
				self.CreateRace(race_dict)
			return
		if len(not_matched_races) > 1:
			raise NonRetryableError(f'There are {len(not_matched_races)} of length {races[0].distance.length} that we cannot match to the race_dicts at {self.url}')
		race = next(iter(not_matched_races.values()))
		if len(not_matched_race_dicts) > 1:
			if (race.precise_name != '') or race.result_set.exists():
				raise NonRetryableError(f'There is one unmatched race (id {race.id}) and {len(not_matched_race_dicts)} unmatched race_dicts '
					+ f'of length {races[0].distance.length} at {self.url}')
			# Otherwise it doesn't matter which race_dict to match to that race.
		# So there's one unmatched race and one or more unmatched race_dicts. We match them to each other, and create races for other race_dicts.
		for i, race_dict in not_matched_race_dicts.items():
			if i == 0:
				race.precise_name = race_dict.get('precise_name', '')
				race.platform_id = self.PLATFORM_ID
				race.id_on_platform = race_dict.get('id_on_platform', '')
				race.save()
				models.log_obj_create(models.USER_ROBOT_CONNECTOR, self.event, models.ACTION_RACE_UPDATE, child_object=race,
					field_list=['precise_name', 'platform_id', 'id_on_platform'], verified_by=models.USER_ROBOT_CONNECTOR)
				race_dict['db_race_id'] = race.id
			else:
				self.CreateRace(race_dict)

	def MatchAndAddRaces(self):
		class DistGroup:
			races: list[models.Race]
			race_dicts: list[dict[str, any]]
			def __init__(self):
				self.races = []
				self.race_dicts = []
		groups = defaultdict(DistGroup)
		for race in self.event.race_set.select_related('distance'):
			if race.is_virtual or not ToLoadResults(race.precise_name):
				continue
			if race.distance.distance_type not in models.TYPES_FOR_RUNNER_STAT:
				raise ValueError(f'{results_util.SITE_URL}{race.get_absolute_url()} has type {race.distance.get_distance_type_display()}')
			if race.distance.distance_type in models.TYPES_MINUTES:
				raise ValueError(f'{results_util.SITE_URL}{race.get_absolute_url()} has type {race.distance.get_distance_type_display()}')
			groups[race.distance.length].races.append(race)
		for race_dict in self.standard_form_dict['races']:
			if race_dict.get('is_virtual') or not ToLoadResults(race_dict.get('precise_name', '')):
				continue
			groups[race_dict['distance']['length']].race_dicts.append(race_dict)
		for group in groups.values():
			self.MatchAndAddRacesInGroup(group.races, group.race_dicts)

	# Tries to match existing (in DB) races to the ones in the standard form, and create absent ones.
	def MatchAndCreateRaces(self):
		if self.event.race_set.exists():
			self.MatchAndAddRaces()
		else:
			self.CreateRaces()

	def LoadResultsToDB(self):
		user = models.USER_ROBOT_CONNECTOR
		DEFAULT_RESULT = 0 if (self.PLATFORM_ID == 'athlinks') else ''
		d = self.standard_form_dict
		n_results_loaded = 0

		self.n_courses_touched = self.n_results_created = self.n_splits_created = self.n_runners_created = self.n_runners_connected = 0
		runners_touched = set()
		cached_distances = {} # models.Distance objects used for splits
		for race_num, race_dict in enumerate(d['races']):
			if race_dict.get('is_virtual') or not ToLoadResults(race_dict.get('precise_name', '')):
				continue
			race_id_on_platform = race_dict.get('id_on_platform')
			race = models.Race.objects.get(pk=race_dict['db_race_id'])
			race_descr = (f'Series {self.platform_series_id}, event {self.platform_event_id}, '
				+ f'race {race_id_on_platform}, {results_util.SITE_URL}{race.get_absolute_url()}, {race.distance_with_details()}')
			if race.event_id != self.event.id:
				raise ValueError(f'{race_descr}: race {race_dict} is from event {race.event_id} but we are working with {self.event} (id {self.event.id})')
			if (race.load_status == models.RESULTS_LOADED) and (race.id not in self.races_to_reload):
				print(f'{race_descr}: skipping as results are already loaded')
				continue
			if race.is_virtual:
				print(f'{race_descr} is virtual so we do not load its results')
				continue

			self.n_courses_touched += 1
			race_changed_fields = []
			if race.platform_id:
				if race.platform_id != self.PLATFORM_ID:
					raise ValueError(f'{race_descr}: race {race} is from platform {race.platform_id} but we are working with {self.PLATFORM_ID}')
			else:
				race.platform_id = self.PLATFORM_ID
				race_changed_fields.append('platform')

			n_deleted_links = parse_protocols.delete_results_and_store_connections(None, user, race, race.result_set.filter(source=models.RESULT_SOURCE_DEFAULT))
			n_recovered_links = 0
			race.category_size_set.all().delete()
			category_sizes = {} # {category_size.name: category_size}
			category_lower_to_orig = {} # {name.lower(): name}

			if race_id_on_platform and (race_id_on_platform != race.id_on_platform):
				race.id_on_platform = race_id_on_platform
				race_changed_fields.append('id_on_platform')

			if len(race_dict.get('results', [])) == 0:
				if not race.has_no_results:
					race.has_no_results = True
					race_changed_fields.append('has_no_results')
				if race_changed_fields:
					race.save()
					models.log_obj_create(user, self.event, models.ACTION_RACE_UPDATE, child_object=race, field_list=race_changed_fields, verified_by=user)
				print(f'{race_descr}: skipping as there are no results')
				continue
			for result_num, result_dict in enumerate(race_dict['results']):
				bib = result_dict.get('bib_raw', '')[:models.MAX_BIB_LENGTH]
				result_descr = f'BIB "{bib}", result {result_dict.get("result_raw")}'
				id_on_platform = str(result_dict.get('id_on_platform', ''))
				if id_on_platform:
					result_descr += f', id_on_platform {id_on_platform}'
				result = models.Result(
					race=race,
					loaded_by=user,
					name_raw=result_dict.get('name_raw', ''),
					lname_raw=result_dict.get('lname_raw', ''),
					fname_raw=result_dict.get('fname_raw', ''),
					gender_raw=(result_dict.get('gender_raw') or '')[:10],
					bib_raw=bib,
					bib    =bib,
					age_raw=result_dict.get('age_raw'),
					age    =result_dict.get('age_raw'),
					country_raw =result_dict.get('country_raw', ''),
					id_on_platform=id_on_platform,
					runner_id_on_platform=result_dict.get('runner_id_on_platform'),
					status_raw=results_util.string2status(result_dict.get('status_raw', ''), source=self.PLATFORM_ID),
					city_raw=result_dict.get('city_raw', ''),
					region_raw=result_dict.get('region_raw', ''),
					result_raw=result_dict.get('result_raw', DEFAULT_RESULT),
					place_raw=result_dict.get('place_raw'),
					place_gender_raw=result_dict.get('place_gender_raw'),
					place_category_raw=result_dict.get('place_category_raw'),
					club_name=result_dict.get('club_raw', ''),
					)
				result.lname = result.lname_raw.title().strip()
				result.fname = result.fname_raw.title().strip()
				result.gender = results_util.string2gender(result.gender_raw)
				result.status = result.status_raw
				if self.PLATFORM_ID == 'athlinks':
					# There the raw result is already a number of centiseconds
					result.result = result.result_raw
				else:
					result.result = models.string2centiseconds(result.result_raw)
				if result.lname == '' and result.fname == '':
					if self.PLATFORM_ID in ('athlinks', 'mikatiming'):
						pass
					else:
						raise JsonParsingError(f'{race_descr}, {result_descr}: no last or first name')
				if result.gender == results_util.GENDER_UNKNOWN:
					if (self.PLATFORM_ID == 'nyrr') and (result.fname_raw == 'Anonymous'):
						pass
					elif self.PLATFORM_ID in ('athlinks', 'mikatiming'):
						pass
					else:
						raise JsonParsingError(f'{race_descr}, {result_descr}: unknown gender {result.gender_raw}')
				if result.status == results_util.STATUS_UNKNOWN:
					raise JsonParsingError(f'{race_descr}, {result_descr}: unknown status {result_dict.get("status_raw")}')

				if result.status == results_util.STATUS_FINISHED and result.result <= 0:
					if (self.PLATFORM_ID == 'athlinks') and (result.fname.lower() in ('unknown', 'unknown male', 'unknown female')):
						# Present e.g. in https://www.athlinks.com/event/115192/results/Event/905578/Course/1773173/Results
						continue
					if (self.PLATFORM_ID == 'athlinks') and (result.result == 0):
						# Common error like https://www.athlinks.com/event/115192/results/Event/905995/Course/1775375/Entry/419973081
						result.status = results_util.STATUS_DNF
					else:
						raise JsonParsingError(f'{race_descr}, {result_descr}: '
							+ f'Result is {result.result_raw} while status is "{result_dict.get("entryStatus")}"')

				if result.country_raw:
					maybe_country = models.Country_conversion.objects.filter(country_raw=result.country_raw).first()
					if maybe_country:
						result.country = maybe_country.country

				if 'gun_time_raw' in result_dict:
					result.gun_time_raw = result_dict['gun_time_raw']
					if result.gun_time_raw:
						if self.PLATFORM_ID == 'athlinks':
							# There the raw result is already a number of centiseconds
							result.gun_result = result.gun_time_raw
						else:
							result.gun_result = models.string2centiseconds(result.gun_time_raw)

				category_raw = result_dict.get('category_raw')
				if category_raw:
					category = category_raw.strip()[:models.MAX_CATEGORY_LENGTH]
					category_lower = category.lower()
					if category_lower not in category_lower_to_orig:
						# For unknown reason this Category_size sometimes already exists
						category_sizes[category], created = models.Category_size.objects.get_or_create(race=race, name=category)
						category_lower_to_orig[category_lower] = category
					result.category_size = category_sizes[category_lower_to_orig[category_lower]]

				runner_id_on_platform = result_dict.get('runner_id_on_platform')
				if runner_id_on_platform:
					runner_platform = models.Runner_platform.objects.filter(platform_id=self.PLATFORM_ID, value=runner_id_on_platform).first()
					if runner_platform:
						runner = runner_platform.runner
					else:
						runner = models.Runner.objects.create(
							lname=result.lname,
							fname=result.fname,
							gender=result.gender,
						)
						models.log_obj_create(user, runner, models.ACTION_CREATE, comment=f'When loading results from {self.url}', verified_by=user)
						models.Runner_platform.objects.create(
							platform_id=self.PLATFORM_ID,
							runner=runner,
							value=runner_id_on_platform,
						)
						self.n_runners_created += 1
					self.n_runners_connected += 1
					result.runner = runner
					result.user_id = runner.user_id
					runners_touched.add(runner)

				if self.platform_event_id == '23MINI':
					print(f'{race_descr}{result.lname}, {result_descr}: Saving to DB "{result.lname}" "{result.fname}"')
				result.save()
				self.n_results_created += 1

				splits_created = set() # Set of distances. They cannot repeat
				for split_dict in result_dict.get('splits', []):
					split_length = split_dict['distance']['length']
					split_distance = cached_distances.get(split_length)
					if not split_distance:
						print(f'Looking for distance of length {split_length}')
						split_distance, created = models.Distance.objects.get_or_create(distance_type=models.TYPE_METERS, length=split_length)
						if created:
							split_distance.name = split_distance.nameFromType()
							split_distance.save()
						cached_distances[split_length] = split_distance
					if split_distance in splits_created:
						if self.PLATFORM_ID == 'athlinks':
							continue # Too many strange sets of splits, like https://www.athlinks.com/event/2164/results/Event/544721/Course/809433/Bib/36
						raise JsonParsingError(f'{race_descr}, {result_descr}: split of length {split_length} is already present')
					splits_created.add(split_distance)
					models.Split.objects.create(
						result=result,
						distance=split_distance,
						value=split_dict['value'],
					)
					self.n_splits_created += 1

				# Now we try to recover killed with links to runners/users.
				if (n_deleted_links > n_recovered_links) and parse_protocols.try_fix_lost_connection(result):
					n_recovered_links += 1

				if (result_num % 1000) == 999:
					self.attempt.UpdateStatus(f'LoadResultsToDB: Loading {race_num+1} race out of {len(d["races"])}. '
						+ f'Loaded {result_num+1} results out of {len(race_dict["results"])}')

			race.load_status = models.RESULTS_LOADED
			race.loaded_from = self.url
			race.was_checked_for_klb = False
			race.save()
			if race_changed_fields:
				models.log_obj_create(user, self.event, models.ACTION_RACE_UPDATE, child_object=race, field_list=race_changed_fields, verified_by=user)

			views_result.fill_places(race)
			views_result.fill_race_headers(race)
			views_result.fill_timing_type(race)

			models.Table_update.objects.create(model_name=self.event.__class__.__name__, row_id=self.event.id, child_id=race.id,
				action_type=models.ACTION_RESULTS_LOAD, user=user, is_verified=True)
			# generators.generate_last_loaded_protocols()
			parse_protocols.log_success(None, f'Загрузка старта {results_util.SITE_URL}{race.get_absolute_url()} ({race}) завершена! Загружено результатов: {self.n_results_created},'
				+ f' промежуточных результатов: {self.n_splits_created}')

			runner_stat.update_runners_and_users_stat(runners_touched)
			if runners_touched:
				parse_protocols.log_success(None, f'{len(runners_touched)} результатов привязано к бегунам')
			if self.n_runners_created:
				parse_protocols.log_success(None, f'В том числе создано {self.n_runners_created} новых бегунов')
			if n_deleted_links:
				parse_protocols.log_success(None, f'Восстановлено {n_recovered_links} привязок результатов из {n_deleted_links}.')
			if self.ToStopNow() and (race_num != len(d['races']) - 1):
				raise util.TimeoutError(f'Time out. Loaded {race_num+1} out of {len(d["races"])} races to the DB.')

	def ProcessNewRunners(self): # By default we do nothing.
		pass

	# Does all the job, and returns the result.
	# May throw an exception. 
	def Process(self) -> str:
		self.time_to_stop = datetime.datetime.now() + self.attempt_timeout
		# Step 1: scrape all the data.
		self.SaveEventDetailsInStandardForm()
		if self.reason_to_ignore:
			return self.reason_to_ignore
		if not self.standard_form_dict['races']:
			raise NonRetryableError(f'{self.url}: no races!')
		if all(race.get('is_virtual') for race in self.standard_form_dict['races']):
			return 'All races are virtual. Marking the event as loaded.'

		# Step 2: load the data to proper event, and create records when needed (races, distances, runners).
		self.FindOrCreateEvent()
		self.FindOrCreateProtocol()
		self.MatchAndCreateRaces()
		# for race in self.standard_form_dict['races']:
		# 	print(f'MatchAndCreateRaces: {race["precise_name"]} -> {race["db_race_id"]}')
		self.DumpStandardForm()
		self.ProcessNewRunners()
		self.DumpStandardForm()

		# Step 3: load results to the database.
		self.LoadResultsToDB()
		return f'loaded {self.n_results_created} results'
