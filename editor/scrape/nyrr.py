from django.conf import settings

from results import links, models, results_util
from editor import parse_strings
from . import util

from collections import Counter, OrderedDict
import datetime
import io
import json
import os
from typing import Optional
import requests
import time

HEADERS = {
	# 'User-Agent' : 'YaBrowser/16.2.0.3539 Safari/537.36',
	# 'Referer' : 'https://www.google.com/',
	'User-Agent' : 'Mozilla/5.0 (Windows NT 6.1; Win64; x64)',
	'ACCEPT_LANGUAGE' : 'en,ru;q=0.8',
	'ACCEPT_ENCODING' : 'utf-8',
	'ACCEPT' : 'application/json,text/plain',
	'Content-Type' : 'application/json;charset=UTF-8',
	# 'Origin' : 'https://results.nyrr.org',
	'Referer' : 'https://results.nyrr.org/',
}

WRONG_PAGE_SIZES = (
	# (event ID, page number) with a wrong number of records
	('18Q10K', 32), # https://results.nyrr.org/event/18Q10K/finishers - no place 3128
	('18Q10K', 115),
	('H2024', 244), # https://results.nyrr.org/event/H2024/finishers - no place 24365
	('H2024', 279),
	('22BKH', 189), # https://results.nyrr.org/event/22BKH/finishers - no place 18827 (last)
	('22SHALOOP', 33), # https://results.nyrr.org/event/22SHALOOP/finishers - no place 3242 (last)
	('5AV-19', 93), # https://results.nyrr.org/event/5AV-19/finishers#opf=9200&page=2 - no places 9273-9276 (last)
	('19AHP', 57),
	('19AHP', 59),
	('19BKH', 269), # https://results.nyrr.org/event/19BKH/finishers
	('19RNYRRVCP', 2), # https://results.nyrr.org/event/19RNYRRVCP/finishers - repeating places
	('19RNYRRVCP', 3),
	('1B9ACD', 8), # https://results.nyrr.org/event/1B9ACD/finishers#opf=701&page=2
	('1B9ACD', 13),
	('1B9ACD', 50),
	('185THAVE', 78), # https://results.nyrr.org/event/185THAVE/finishers
	('1B9343', 41), # https://results.nyrr.org/event/1B9343/finishers
	('18JDAY', 16), # https://results.nyrr.org/event/18JDAY/finishers
	('18JDAY', 51),
	('17GLWD', 57), # https://results.nyrr.org/event/17GLWD/finishers
)

WRONG_EVENT_SIZES = frozenset([
	'22BKH',
	'22SHALOOP',
	'5AV-19',
	'19BKH',
	'19RNYRRVCP',
	'185THAVE',
	'1B9343',
	'17GLWD',
	'16AHP',
])

# Some bugs
BAD_RESULT_IDS = frozenset([
	'19477963', # https://results.nyrr.org/event/2018GLWD/result/1750
	'16025540', # https://results.nyrr.org/event/18RAO/result/894
	'17657381', # https://results.nyrr.org/event/H2018/result/12679
])

class NyrrScraper(util.Scraper):
	PLATFORM_ID = 'nyrr'
	ALL_EVENTS_URL = 'https://rmsprodapi.nyrr.org/api/v2/events/search'
	EVENT_RESULTS_URL = 'https://rmsprodapi.nyrr.org/api/v2/runners/finishers-filter'
	RESULT_DETAILS_URL = 'https://rmsprodapi.nyrr.org/api/v2/runners/resultDetails'
	RUNNER_DETAILS_URL = 'https://rmsprodapi.nyrr.org/api/v2/runners/recentDetails'
	RUNNER_RESULTS_URL = 'https://rmsprodapi.nyrr.org/api/v2/runners/races'
	PAGE_SIZE = 100
	DEFAULT_CITY = models.City.objects.filter(region__name='New York', name='New York').first()

	def EventDetailsReq(self) -> any: # tuple[str, dict[str, str]]:
		return requests.post('https://rmsprodapi.nyrr.org/api/v2/events/details', headers=HEADERS, json={'eventCode': self.platform_event_id}).json()
		# return 'https://rmsprodapi.nyrr.org/api/v2/events/details', {'eventCode': self.platform_event_id}

	# Returns:
	# * events added to the queue
	# * events already present in the queue
	# * error, if any
	@classmethod
	def AddEventsToQueue(cls, for_all_years: bool=True, limit: Optional[int]=None, debug: int=0) -> str:
		total_items = None
		n_added = n_already_present = 0
		all_items = []
		ITEMS_PER_PAGE = 100
		cur_year = datetime.date.today().year
		year_range = range(1970, cur_year + 1) if for_all_years else range(cur_year - 1, cur_year + 1)
		for year in year_range:
			res = requests.post(cls.ALL_EVENTS_URL, headers=HEADERS, json={
					'pageIndex': 1,
					'pageSize': ITEMS_PER_PAGE,
					'sortColumn': 'StartDateTime',
					'sortDescending': 1,
					'year': year,
				}).json()

			if not res.get('items'):
				return f'ERROR: Could not load {cls.ALL_EVENTS_URL}: {res}. Added {n_added} events to queue; {n_already_present} events were already there.'

			if debug:
				print(f'Total items on year {year}: {res["totalItems"]}')
			if not total_items:
				total_items = res["totalItems"]

			for i, item in enumerate(res['items']):
				all_items.append(item)
				code = item['eventCode']
				if not code:
					return f'ERROR: No code for {item["eventName"]}. Added {n_added} events to queue; {n_already_present} events were already there.'
				url = links.NyrrEventURL(code)
				if models.Scraped_event.objects.filter(url_results=url).exists():
					n_already_present += 1
					if debug:
						print(f'{url} is already in the queue')
					continue
				models.Scraped_event.objects.create(
					url_site=url,
					url_results=url,
					platform_id=cls.PLATFORM_ID,
					platform_series_id=code,
					platform_event_id=code,
					start_date=datetime.datetime.fromisoformat(item['startDateTime']).date(),
				)
				n_added += 1
				if debug:
					print(f'{url} was added')
				if limit and n_added == limit:
					return f'Added {n_added} events to queue; {n_already_present} events were already there.'
			time.sleep(1)
		if for_all_years:
			with io.open(settings.INTERNAL_FILES_ROOT + 'misc/nyrr/all_events.json', "w", encoding="utf8") as file_out:
				json.dump(
					all_items,
					file_out,
					ensure_ascii=False,
					sort_keys=True,
					indent=1
				)
		return f'Added {n_added} events to queue; {n_already_present} events were already there.'

	def _TotalItems(self, mydir):
		params = OrderedDict([
			('eventCode', self.platform_event_id),
			('pageIndex', 1),
			('pageSize', self.PAGE_SIZE),
			('sortColumn', 'overallTime'),
		])
		res = util.LoadAndStore(mydir, self.EVENT_RESULTS_URL, method='POST', params=params)
		return res['totalItems']

	# Returns the number of just loaded brief results.
	def LoadBriefResults(self) -> int:
		mydir = self.DownloadedFilesDir()
		n_loaded = 0
		total_items = None
		for race in self.standard_form_dict['races']:
			if race['results_brief_loaded'] or race['is_virtual']:
				if race['results_brief_loaded']:
					n_loaded += len(race['results'])
				continue

			race['results'] = []
			total_items = self._TotalItems(mydir)
			print(f'{self.platform_event_id}: total {total_items} results to load')
			last_page = 1 + (total_items - 1) // self.PAGE_SIZE
			for page in range(1, last_page + 1):
				params = OrderedDict([
					('eventCode', self.platform_event_id),
					('pageSize', self.PAGE_SIZE),
					('sortColumn', 'overallPlace'),
					('overallPlaceFrom', (page-1) * self.PAGE_SIZE + 1),
					('overallPlaceTo', page * self.PAGE_SIZE),
				])
				res = util.LoadAndStore(mydir, self.EVENT_RESULTS_URL, method='POST', params=params)

				expected_items = self.PAGE_SIZE if (page < last_page) else (total_items - (page-1) * self.PAGE_SIZE)
				if abs(len(res['items']) - expected_items) > 9 and (self.EventYear() >= 2023):
					# There are too many old races with wrong number of participants.
					if (self.platform_event_id, page) not in WRONG_PAGE_SIZES:
						raise util.NonRetryableError(f'{self.platform_event_id}, {params}: {len(res["items"])} results but we expected {expected_items}')

				for item in res['items']:
					race['results'].append({
						'id_on_platform': str(item['runnerId']), #: 39947974,
						'fname_raw': item['firstName'], #: "Yenew",
						'lname_raw': item['lastName'], #: "Alamirew Getahun",
						'bib_raw': item['bib'] or '', #: "4235",
						'age_raw': item['age'], #: 34,
						'gender_raw': item['gender'], #: "M",
						'city_raw': item['city'] or '', #: "Washington",
						'country_raw': item['countryCode'] or '', #: "USA",
						'region_raw': item['stateProvince'] or '', #: "DC",
						'place_raw': item['overallPlace'], #: 1,
						'result_raw': item['overallTime'], #: "0:30:45",
						'place_gender_raw': item['genderPlace'], #: 1,
						'status_raw': 'FINISHED',
					})
			n_loaded += len(race['results'])
			race['results_brief_loaded'] = True
		print(f'{self.standard_form_dict["name"]}: loaded {n_loaded} brief results')
		if total_items and (abs(n_loaded - total_items) > 10) and (self.platform_event_id not in WRONG_EVENT_SIZES) and (self.EventYear() >= 2023):
			raise util.NonRetryableError(f'{self.platform_event_id}: {n_loaded} results loaded but there should be {total_items}')
		return n_loaded

	# Returns the number of just loaded detailed results.
	def LoadDetailedResults(self) -> int:
		n_loaded_total = n_loaded_now = 0
		for race in self.standard_form_dict['races']:
			if race['results_detailed_loaded'] or race['is_virtual']:
				n_loaded_total += len(race['results'])
				continue
			if not race['results_brief_loaded']:
				raise util.NonRetryableError(f'{self.platform_event_id}, {race['precise_name']}: brief results not loaded, but we are trying to load detailed ones')

			for result_num, result in enumerate(race['results']):
				if result.get('results_detailed_loaded'):
					n_loaded_total += 1
					continue
				params = {'runnerId': result['id_on_platform']}
				res = util.LoadAndStore(self.DownloadedFilesDir(platform_runner_id=result['id_on_platform']), self.RESULT_DETAILS_URL, method='POST', params=params)

				if not res['success']:
					raise util.NonRetryableError(f'{self.platform_event_id}, {race["precise_name"]}: bad response for runnerId {result["id_on_platform"]}: {res}')

				if res['details']:
					category = res['details']['ageGroupFromTo']
					if category and category[0].isdigit() and result.get('gender_raw'):
						category = result['gender_raw'][0] + category
					result.update({
						'club_raw': res['details']['teamName'] or '',
						'gun_time_raw': res['details']['gunTime'],
						'place_category_raw': res['details']['placeAgeGroup'],
						'category_raw': category,
					})

					if 'splitResults' in res['details']:
						if 'splits' not in result:
							result['splits'] = []
						for split in res['details']['splitResults']:
							if isinstance(speed := split.get('speed'), str) and speed.lower() == 'infinity': # E.g. https://results.nyrr.org/runner/49654/result/M2019
								# This is a zero split. Let's ignore them.
								continue
							value = models.string2centiseconds(split['time'])
							if not value:
								raise util.NonRetryableError(f'{self.platform_event_id}, {race["precise_name"]}: bad split for runnerId {result["id_on_platform"]}: {split}')
							length = parse_strings.parse_meters(length_raw=None, name=split['splitCode'], platform_id=self.PLATFORM_ID) # There is also 'distance' field
							if (length <= 0) or (length > race['distance']['length']):
								raise util.NonRetryableError(f'{self.platform_event_id}, {race["precise_name"]}: bad split for runnerId {result["id_on_platform"]}: length {split["splitCode"]}')
							if length == race['distance']['length']:
								continue # E.g. NYC Marathon has a 'MAR' split with the final result. We don't want to load it
							result['splits'].append({
								'distance': {
									'distance_type': models.TYPE_METERS,
									'length': length,
								},
								'value': value,
							})
				else:
					if result['fname_raw'] != 'Anonymous':
						raise util.NonRetryableError(f'{self.platform_event_id}, {race["precise_name"]}: no details in {self.RESULT_DETAILS_URL} with {params}: {res}. Result: {result}')

				result['results_detailed_loaded'] = True
				n_loaded_total += 1
				n_loaded_now += 1

				if (result_num % 1000) == 999:
					self.attempt.UpdateStatus(f'LoadDetailedResults: Loaded {result_num+1} detailed results out of {len(race["results"])}')
					self.DumpStandardForm()
					if self.ToStopNow():
						raise util.TimeoutError(f'Time out. Loaded {n_loaded_total} out of {len(race["results"])} detailed results')
			race['results_detailed_loaded'] = True
		print(f'{self.standard_form_dict["name"]}: just loaded {n_loaded_now} detailed results. Total {n_loaded_total} are loaded')
		return n_loaded_now

	def InitStandardFormDict(self):
		resp = self.EventDetailsReq()['eventDetails']
		start_datetime = datetime.datetime.fromisoformat(resp['startDateTime'])
		distance = {
			'distance_type': models.TYPE_METERS,
			'length': util.FixLength(int(round(resp['distanceDimension'] * 1000))),
		}
		race = {
			'distance': distance,
			'precise_name': resp['distanceName'],
			'is_virtual': resp['isVirtual'],
			'results': [],
			'results_brief_loaded': False,
			'results_detailed_loaded': False,
			'loaded_from': links.NyrrEventURL(self.platform_event_id),
			'is_virtual': util.IsVirtual(resp['eventName']),
		}
		self.standard_form_dict = {
			'name': resp['eventName'].replace('  ', ' '),
			'id_on_platform': self.platform_event_id,
			'start_date': start_datetime.date().isoformat(),
			'start_time': start_datetime.time().isoformat(),
			'start_place': resp['venue'],
			'races': [race],
		}

	def SaveEventDetailsInStandardForm(self):
		if os.path.isfile(self.StandardFormPath()):
			print(f'Reading all event data from {self.StandardFormPath()}')
			with io.open(self.StandardFormPath(), encoding="utf8") as json_in:
				self.standard_form_dict = json.load(json_in)
		else:
			self.InitStandardFormDict()
			self.DumpStandardForm()

		if self.LoadBriefResults() > 0:
			self.DumpStandardForm()
		if self.LoadDetailedResults() > 0:
			self.DumpStandardForm()

	# Removes obvious prefixes and suffixes from the event name to get a reasonable series name.
	def _SimplifiedEventName(self):
		res = self.standard_form_dict['name']
		year = int(self.standard_form_dict['start_date'][:4])
		if res.endswith(f' {year}'):
			res = res[:-5]
		if res.startswith(f'{year} '):
			res = res[5:]
		if res.startswith('NYRR '):
			res = res[5:]
		return res


	def FindOrCreateSeries(self):
		simplified_event_name = self._SimplifiedEventName()
		possible_series_names = (simplified_event_name, f'NYRR {simplified_event_name}')
		series_names = models.Series_name.objects.filter(platform_id=self.PLATFORM_ID, event_name__in=possible_series_names)
		distinct_names = set(series_names.values_list('name', flat=True))
		if len(distinct_names) != 1:
			raise util.NonRetryableError(f'There are {series_names.count()} NYRR series with names similar to {simplified_event_name} for platform ID {self.PLATFORM_ID}: '
				+ f'{distinct_names} but we need 1')
		series_name = series_names[0]
		if series_name.series:
			self.series = series_name.series
			return
		# Otherwise, we only know the name of the series, but it may not exist yet.
		series = models.Series.objects.filter(name__in=possible_series_names, city__region__name='New York')
		if series.count() > 1:
			raise util.NonRetryableError(f'There are {series.count()} series in NYS with names {possible_series_names} so we cannot find series for the NYRR event {self.standard_form_dict['name']}')
		if series.count() == 1:
			self.series = series[0]
			return
		self.series = models.Series.objects.create(
			name=simplified_event_name,
			country_id='US',
			city=self.DEFAULT_CITY,
			url_site='https://nyrr.org',
		)
		models.log_obj_create(models.USER_ROBOT_CONNECTOR, self.series, models.ACTION_CREATE, verified_by=models.USER_ROBOT_CONNECTOR,
			comment='From nyrr.FindOrCreateSeries')

	# Creates models.Runner and Nyrr_runner from the provided runner json.
	# Returns just created nyrr_runner.
	def _CreateRunnerAndNyrrRunner(self, platform_result_id: int, runner_data: dict[str, any]) -> models.Nyrr_runner:
		gender = results_util.string2gender(runner_data['gender'])
		if gender == results_util.GENDER_UNKNOWN:
			raise util.NonRetryableError(f'{runner_data}: unknown gender {runner_data["gender"]}')
		today = datetime.date.today()

		nyrr_runner, just_created = models.Nyrr_runner.objects.get_or_create(
			sample_platform_id=runner_data['runnerId'],
			defaults={'fname': runner_data['firstName'], 'lname': runner_data['lastName']},
		)
		if just_created:
			runner = models.Runner.objects.create(
				fname=runner_data['firstName'], # .strip().title(), # "Theresa"
				lname=runner_data['lastName'], # .strip().title(), # "McCabe"
				birthday_min=None if (runner_data['age'] is None) else util.MinBirthday(today, runner_data['age']), # 39
				birthday_max=None if (runner_data['age'] is None) else util.MaxBirthday(today, runner_data['age']), # 39
				gender=gender, # "W"
				city_name=runner_data['city'] or '', # "Manhasset"
				region_name=runner_data['stateProvince'] or '', # "NY"
				country_name=runner_data['countryName'] or '', # "United States"
				club_name=runner_data['teamName'] or '', # "Central Park Track Club Tracksmith"
			)
			models.log_obj_create(models.USER_ROBOT_CONNECTOR, runner, models.ACTION_CREATE, verified_by=models.USER_ROBOT_CONNECTOR,
				comment=f'When processing NYRR event {self.platform_event_id}')
			models.Runner_platform.objects.create(
				runner=runner,
				platform_id=self.PLATFORM_ID,
				value=nyrr_runner.id,
				updated_from_source=True,
			)
		else:
			if not models.Runner_platform.objects.filter(platform_id=self.PLATFORM_ID, value=nyrr_runner.id).exists():
				raise util.NonRetryableError(f'_CreateRunnerAndNyrrRunner for runner_data {runner_data}: Nyrr_runner with sample_platform_id={runner_data["runnerId"]}'
					+ f' exists but there is no Runner_platform with value={nyrr_runner.id}')
		return nyrr_runner

	# If there are >600 results for given runner, we need to shard by year.
	# Returns:
	# * List of POST params dicts for requests,
	# * First page of results.
	def _RunnerResultsRequests(self, result_id_on_platform: str, first_active_year: int, last_active_year: int) -> tuple[list[any], list[any]]:
		params = OrderedDict([
			('runnerId', result_id_on_platform),
			('pageIndex', 1),
			('pageSize', self.PAGE_SIZE),
			('sortColumn', 'EventDate'),
			('sortDescending', True),
		])
		res = util.LoadAndStore(self.DownloadedFilesDir(platform_runner_id=result_id_on_platform), self.RUNNER_RESULTS_URL, method='POST', params=params)

		if 'items' not in res:
			raise util.NonRetryableError(f'No "items" field in {self.RUNNER_RESULTS_URL} with {params}: {res}')
		if res['totalItems'] <= 600:
			last_page = 1 + (res['totalItems'] - 1) // self.PAGE_SIZE
			params_list = [
				OrderedDict([
					('runnerId', result_id_on_platform),
					('pageIndex', page),
					('pageSize', self.PAGE_SIZE),
					('sortColumn', 'EventDate'),
					('sortDescending', True),
				])
				for page in range(2, last_page + 1)
			]
		else:
			last_not_covered_year = int(res['items'][-1]['startDateTime'][:4])
			if last_not_covered_year < 1950:
				raise util.NonRetryableError(f'Strange last year in {self.RUNNER_RESULTS_URL} with {params}: {res["items"][-1]}')
			params_list = [
				OrderedDict([
					('runnerId', result_id_on_platform),
					('year', str(year)),
					('pageIndex', 1),
					('pageSize', self.PAGE_SIZE),
					('sortColumn', 'EventDate'),
					('sortDescending', True),
				])
				for year in range(first_active_year, min(last_not_covered_year, last_active_year) + 1)
			]
		return params_list, res['items']

	def _CreateRunnerIfNeededAndAddResultIDs(self, result_dict: dict[str, any]) -> tuple[int, int, int]:
		records_created = 0
		result_id_on_platform = result_dict['id_on_platform']

		params = {'runnerId': result_id_on_platform}
		res = util.LoadAndStore(self.DownloadedFilesDir(platform_runner_id=result_id_on_platform), self.RUNNER_DETAILS_URL, method='POST', params=params)
		if not res['success']:
			raise util.NonRetryableError(f'{self.platform_event_id}, result {result_id_on_platform}: '
				+ f'bad response at {self.RUNNER_DETAILS_URL} for runnerId {result_id_on_platform}: {res}')
		runner_data = res['details']
		if not runner_data:
			# There are too many such errors, e.g. https://results.nyrr.org/event/M2017/result/7609
			# if (result_dict['fname_raw'] == 'Anonymous') or (result_id_on_platform in BAD_RESULT_IDS):
			return -1, 0, 0
			# raise util.NonRetryableError(f'No items in {self.RUNNER_RESULTS_URL} for result ID {result_id_on_platform}, bib {result_dict["bib_raw"]}')

		params_list, items = self._RunnerResultsRequests(
			result_id_on_platform=result_id_on_platform,
			first_active_year=runner_data['firstEventYear'],
			last_active_year=runner_data['lastEventYear'],
		)
		for params in params_list:
			res = util.LoadAndStore(self.DownloadedFilesDir(platform_runner_id=result_id_on_platform), self.RUNNER_RESULTS_URL, method='POST', params=params)

			if 'items' not in res:
				raise util.NonRetryableError(f'No "items" field in {self.RUNNER_RESULTS_URL} with {params}: {res}')
			if ('year' in params) and (res['totalItems'] > self.PAGE_SIZE):
				raise util.NonRetryableError(f'Too many items for year={params["year"]} at {self.RUNNER_RESULTS_URL} with {params}: {res["totalItems"]}')
			new_items = res['items']
			if (not new_items) and ('year' not in params) and (result_dict['fname_raw'] != 'Anonymous'):
				raise util.NonRetryableError(f'No items in {self.RUNNER_RESULTS_URL} with {params}: {res}')

			items += new_items

		if not items:
			if (result_dict['fname_raw'] == 'Anonymous') or (result_id_on_platform in BAD_RESULT_IDS):
				return -1, 0, 0
			raise util.NonRetryableError(f'No items in {self.RUNNER_RESULTS_URL} for result ID {result_id_on_platform}, bib {result_dict["bib_raw"]}')

		result_ids = {item['runnerId'] for item in items}

		# All runners in Nyrr_runner already associated with the results of this person. There should be:
		# * 0 (then we create a new Nyrr_runner)
		# or 1 (then we just add new records to Nyrr_result)
		platform_runner_ids = Counter(list(models.Nyrr_result.objects.filter(pk__in=result_ids).values_list('nyrr_runner_id', flat=True)))

		n_runner_ids = len(platform_runner_ids.keys())

		if n_runner_ids > 1:
			raise util.NonRetryableError(f'{self.url}, result ID {result_id_on_platform}: {n_runner_ids} runner IDs: {platform_runner_ids.items()}')

		if n_runner_ids == 1:
			nyrr_runner_id = list(platform_runner_ids.keys())[0]
			runners_created = 0
		else: # This is a new runner for us
			nyrr_runner_id = self._CreateRunnerAndNyrrRunner(result_id_on_platform, runner_data=runner_data).id
			runners_created = 1

		for result_id in result_ids:
			_, just_created = models.Nyrr_result.objects.get_or_create(pk=result_id, defaults={'nyrr_runner_id': nyrr_runner_id})
			if just_created:
				records_created += 1

		return nyrr_runner_id, runners_created, records_created

	# Adds the `runner_id_on_platform` field to each result dictionary. Creates Runner, Nyrr_runner, Runner_platform entries in DB if needed.
	def ProcessNewRunners(self):
		runner_ids_filled = runners_created = nyrr_results_created = 0
		for race_dict in self.standard_form_dict['races']:
			for result_num, result_dict in enumerate(race_dict.get('results', [])):
				if 'runner_id_on_platform' in result_dict:
					continue
				
				nyrr_result = models.Nyrr_result.objects.filter(pk=result_dict['id_on_platform']).first()
				if nyrr_result:
					# TODO: Check the name of the runner?
					result_dict['runner_id_on_platform'] = nyrr_result.nyrr_runner_id
				else:
					nyrr_runner_id, runners_just_created, nyrr_results_just_created = self._CreateRunnerIfNeededAndAddResultIDs(result_dict)
					if nyrr_runner_id == -1: # This is an anonymous result, and there's no runner.
						continue
					runners_created += runners_just_created
					nyrr_results_created += nyrr_results_just_created

					result_dict['runner_id_on_platform'] = nyrr_runner_id

				runner_ids_filled += 1
				if (result_num % 1000) == 999:
					self.attempt.UpdateStatus(f'ProcessNewRunners: filled {result_num+1} runner IDs out of {len(race_dict["results"])}')
					self.DumpStandardForm()
					if self.ToStopNow():
						raise util.TimeoutError(f'Time out. Loaded {runner_ids_filled} out of {len(race_dict["results"])} runner IDs. '
							+ f'Created {runners_created} runners, {nyrr_results_created} Nyrr_result records')
		print(f'Filled {runner_ids_filled} runner IDs. Created {runners_created} runners, {nyrr_results_created} Nyrr_result records')

def print_events():
	with io.open(settings.INTERNAL_FILES_ROOT + 'misc/nyrr/all_events.json', encoding="utf8") as json_in:
		items = json.load(json_in)
		for item in items:
			name = name_trimmed = item['eventName']
			start_datetime = datetime.datetime.fromisoformat(item['startDateTime'])
			if name_trimmed.endswith(f' {start_datetime.year}'):
				name_trimmed = name_trimmed[:-5]
			if name_trimmed.startswith(f'{start_datetime.year} '):
				name_trimmed = name_trimmed[5:]
			if name_trimmed.startswith('NYRR '):
				name_trimmed = name_trimmed[5:]
			print(f'{item["startDateTime"]}\t{name}\t{name_trimmed}\t{item["eventCode"]}\t{item["distanceName"]}\t{item["distanceUnitCode"]}\t{item["venue"]}\t')
