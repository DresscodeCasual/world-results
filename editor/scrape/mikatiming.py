import bs4
from collections import OrderedDict
import io
import json
import os
import re
from typing import Optional, Union
from urllib import parse

from results import models, results_util
from editor import parse_strings
from . import util

# For each field in the standard form for the result, we list all possible column names.
COLUMN_NAMES = {
	'': 'IGNORE',
	'event': 'IGNORE',
	'half': 'IGNORE',

	'bib': 'bib_raw',
	'number': 'bib_raw',
	'runner number': 'bib_raw',

	'ac': 'category_raw',
	'category': 'category_raw',
	'division': 'category_raw',

	'club': 'club_raw',
	'team': 'club_raw',

	'finish gun': 'gun_time_raw',
	'brutto': 'gun_time_raw',

	'name': 'name_raw',
	'name (ctz)': 'name_raw',

	'place overall': 'place_raw',
	'place (overall)': 'place_raw',

	'pl.ac': 'place_category_raw',
	'place (category)': 'place_category_raw',
	'place division': 'place_category_raw',

	'place': 'place_gender_raw',
	'place gender': 'place_gender_raw',
	'place (gender)': 'place_gender_raw',

	'finish': 'result_raw',
	'finish net': 'result_raw',

}

# '<div class=" list-field type-fullname">Name</div>' -> Name
# '<div class=" list-field type-fullname"><div>Name</div>Name</div>' -> Name
# '<div class=" list-field type-fullname"><div>Name</div>Eliud</div>' -> Eliud
# '<div class=" list-field type-fullname"><div></div></div>' -> ''
def LastString(elem: bs4.Tag) -> str:
	strings = list(elem.stripped_strings)
	if not strings:
		return ''
	return strings[-1]

BIBS_WITH_NO_NAME = frozenset([
	'0000170E9A92360000153700', # https://chicago-history.r.mikatiming.com/2023/?pid=search, marathon 2001
	'0000170E9A92360000159B82', # https://chicago-history.r.mikatiming.com/2023/?pid=search, marathon 2000
	'0000170E9A9236000016F324', # https://chicago-history.r.mikatiming.com/2023/?pid=search, marathon 1996
])

# For https://results.tcslondonmarathon.com/2024 , Mass, line 331
def OnlyString(elem: bs4.Tag) -> str:
	strings = [s for s in elem.stripped_strings if s]
	if (n_strings := len(strings)) != 1:
		if (n_strings == 0) and results_util.anyin(str(elem), BIBS_WITH_NO_NAME):
			return ''
		raise util.NonRetryableError(f'Element has {len(strings)} name strings but we need exactly one: "{elem}"')
	return strings[0]

def HeaderName(elem: bs4.Tag) -> str:
	if elem.find('small'): # <div class=" list-field type-place place-secondary hidden-xs" style="width: 60px">Place <small>(Overall)</small></div>
		return ' '.join(elem.stripped_strings)
	# <div class=" list-field type-field" style="width: 50px"><div class="visible-xs-block visible-sm-block list-label">Number</div>Number</div>
	return LastString(elem)

# Returns <value, to skip this line completely?>
def ParseValue(elem: bs4.Tag) -> tuple[Union[str, int, None], bool]:
	string = LastString(elem)
	if 'type-place' in elem['class']:
		if string == '–': # E.g. https://berlin.r.mikatiming.net/2023/?page=18&event=BML&event_main_group=BMW+BERLIN+MARATHON&num_results=100&pid=search&search%5Bage_class%5D=%25&search%5Bsex%5D=%25&search%5Bnation%5D=%25&search_sort=place_nosex
			return None, False
		if string == 'PND': # E.g. https://chicago-history.r.mikatiming.com/2023/?content=detail&fpid=search&pid=search&idp=9TGG963828ACEC
			return None, True
		if not string.isdigit():
			raise util.NonRetryableError(f'{elem}: the string is not numeric')
		return int(string), False
	return string, False

# Parses a string like 'Heikura, Kari' into lname, fname.
def NameDict(s: str) -> dict[str, str]:
	parts = s.split(',')
	if len(parts) != 2:
		return {
			'lname_raw': s.strip(),
			'fname_raw': '',
		}
	return {
		'lname_raw': parts[0].strip(),
		'fname_raw': parts[1].strip(),
	}

# Parses a string like 'Heikura, Kari (FIN)' into lname, fname, country_raw.
# Examples:
# Pluta (GER)
# WU, Xiao Fang(Fion) (CHN)
def NameCountryDict(s: str) -> dict[str, str]:
	country = ''
	name_str = s
	if (len(s) > 5) and (s[-1] == ')') and (s[-5] == '('):
		country = s[-4:-1]
		name_str = s[:-5].strip()
	res = NameDict(name_str)
	if country:
		res['country_raw'] = country
	return res

def EventAndRaceNames(url: str, title_page_soup: bs4.BeautifulSoup) -> tuple[str, str]:
	event_group_name = ''
	event_main_group_tag = title_page_soup.find('select', attrs={'name': 'event_main_group'})
	if event_main_group_tag:
		option_tag = event_main_group_tag.find('option', selected='selected')
		if not option_tag:
			raise util.NonRetryableError(f'{url}: no OPTION with selected=selected for the event_main_group')
		event_group_name = option_tag['value']
		if not event_group_name:
			raise util.NonRetryableError(f'{url}: no VALUE with selected=selected for the event_main_group')

	event_tag = title_page_soup.find('select', attrs={'name': 'event'})
	if not event_tag:
		raise util.NonRetryableError(f'{url}: no SELECT with name "event"')
	option_tag = event_tag.find('option') # None of them have `selected` attr, but the first option is usually what we need.
	if not option_tag:
		raise util.NonRetryableError(f'{url}: no OPTIONs for the EVENT select')
	event_name = option_tag['value']
	if not event_name:
		raise util.NonRetryableError(f'{url}: no VALUE for the first OPTION for the EVENT select')
	return event_group_name, event_name

def ResultsPageHasNextPageLink(content: bs4.BeautifulSoup) -> bool:
	for tag in content.find_all('li', class_='pages-nav-button'):
		if tag.string == '>':
			return True
	return False

# E.g. HCH3C0OH73EB8
def IsCorrectResultID(s: str) -> bool:
	return s.isalnum() and (5 <= len(s) <= 30)

def ElemOnDetailedPage(url: str, content: bs4.BeautifulSoup, key: str) -> Union[None, str]:
	elems = list(content.find_all('th', string=key))
	if len(elems) == 0:
		return None
	if len(elems) > 1:
		raise util.NonRetryableError(f'{url}: {len(elems)} elements with key "{key}" found: {elems}')
	td = elems[0].next_sibling
	if td.name != 'td':
		raise util.NonRetryableError(f'{url}: key "{key}": next element - "{td}" - is not a TD')
	return td.string

def SplitDesc(url: str, line: bs4.Tag) -> str:
	strings = list(line.find('th', class_='desc').stripped_strings)
	if len(strings) == 1:
		return strings[0]
	if len(strings) == 2:
		if strings[1] == '*':
			return strings[0]
	raise util.NonRetryableError(f'{url}: no distance found. Line:\n{line}')

# Returns None if the split should be ignored.
def ParseSplit(url: str, line: bs4.Tag) -> Optional[dict[str, any]]:
	# try:
		distance_str = SplitDesc(url, line)
		if not distance_str:
			raise util.NonRetryableError(f'{url} no distance found. Line:\n{line}')
		if distance_str in ('Finish', 'Finish Net'):
			return None
		length = parse_strings.parse_meters(length_raw=None, name=distance_str)
		if not length:
			raise util.NonRetryableError(f'{url}: Could not parse length from {distance_str}')
		time_str = line.find('td', class_='time').string
		if time_str == '–': # If the split wasn't recorded, e.g. https://berlin.r.mikatiming.net/2023/?content=detail&idp=HCH3C0OH7F73D
			return None
		value = models.string2centiseconds(time_str)
		if not value:
			raise util.NonRetryableError(f'{url}: Could not parse time from {time_str}')
		return {'distance': {
					'distance_type': models.TYPE_METERS,
					'length': length,
				},
				'value': value,
		}
	# except Exception as e:
	# 	raise util.NonRetryableError(f'{url}: we could not extract split from "{line}": {e}')

# Returns the list of splits from the page.
def ParseSplits(url: str, soup: bs4.BeautifulSoup) -> list[dict[str, any]]:
	splits_tags = list(soup.find_all('div', class_='box-splits'))
	if len(splits_tags) > 1:
		raise util.NonRetryableError(f'{url}: {len(splits_tags)} elements with class "box-splits"')
	if not splits_tags:
		return []
	split_tag = splits_tags[0]
	return [split for line in split_tag.tbody.find_all('tr') if (split := ParseSplit(url, line))]

# def EventCodesByYearFromJson(data: dict[str, any], distance_name: str) -> list[tuple[str, str]]:
# 	if 'branches' not in data:
# 		raise Exception(f'json of length {len(str(data))} with no "branches"')
# 	tuples = []
# 	cur_year = None
# 	for item in data['branches']['search']['fields']['event']['data'][:20]:
# 		key, val = item['v']
# 		res = re.match(r'ALL_EVENT_GROUP_(\d{4})', key)
# 		if res:
# 			cur_year = int(res.group(1))
# 			continue
# 		if val.lower() == distance_name:
# 			if not cur_year:
# 				raise Exception(f'We found a tuple ({key}, {val}) but we do not know the year')
# 			if tuples and (tuples[-1][0] == cur_year):
# 				raise Exception(f'We found a tuple ({key}, {val}) for year {cur_year} but the previous tuple {tuples[-1]} is for the same year')
# 			tuples.append((cur_year, key))
# 	return tuples

def EventCodeFromJson(data: dict[str, any], distance_name: str) -> str:
	if 'branches' not in data:
		raise Exception(f'json of length {len(str(data))} with no "branches"')
	for item in data['branches']['search']['fields']['event']['data']:
		key, val = item['v']
		if val.lower() == distance_name:
			return key
	raise Exception(f'No distance with name {distance_name} found in data of length {len(data)}. {len(data["branches"]["search"]["fields"]["event"]["data"])} events total there')

def EventYears(series_url: str) -> list[int]:
	params = OrderedDict([
		('content', 'ajax2'),
		('func', 'getSearchFields'),
	])
	path = util.dir(
			file_type=util.FILE_TYPE_DOWNLOADED,
			platform_id='mikatiming',
			platform_series_id=series_url,
		)
	data = util.LoadAndStore(path, url=series_url, params=params)
	if 'branches' not in data:
		raise Exception(f'{url} with params {params} has length {len(data)} and has no `branches`')
	res = []
	for item in data['branches']['search']['fields']['event_main_group']['data']:
		key, _ = item['v']
		if not isinstance(key, int):
			if key.lower() == 'all':
				continue
			raise Exception(f'{url} with params {params} returned year {key} that is not an integer')
		res.append(key)
	return res

# Returns a tuple of `event_main_group` and `event` fields, e.g. `2014` and `MAR_999999107FA3090000000065` from https://chicago-history.r.mikatiming.com/2023/.
def EventCodesByYear(series_url: str, distance_name: str) -> list[tuple[str, str]]:
	path = util.dir(
		file_type=util.FILE_TYPE_DOWNLOADED,
		platform_id='mikatiming',
		platform_series_id=series_url,
	)
	res = []
	for year in EventYears(series_url):
		params = OrderedDict([
			('content', 'ajax2'),
			('func', 'getSearchFields'),
			('options[b][search][event_main_group]', year),
		])
		data = util.LoadAndStore(path, url=series_url, params=params)
		res.append((year, EventCodeFromJson(data, distance_name)))
	return res

def AddEventsToQueue(series_id: int, series_url: str, distance_name: str):
	n_already_present = n_added = 0
	series = models.Series.objects.get(pk=series_id)
	codes = EventCodesByYear(series_url, distance_name)
	for year, code in codes:
		events = series.event_set.filter(start_date__year=year)
		if (count := events.count()) != 1:
			raise Exception(f'There are {count} events in series {series_id} in year {year} but we need 1')
		event = events[0]
		if event.scraped_event_set.exists():
			print(f'Event {event} (id {event.id}) is already in Scraped_event')
			n_already_present += 1
			continue
		models.Scraped_event.objects.create(
			platform_id='mikatiming',
			url_site=series_url,
			url_results=series_url,
			extra_data=code,
			event=event,
		)
		print(f'Adding URL {series_url}, extra_data {code}')
		n_added += 1
	print(f'Added {n_added} records to Scraped_event. {n_already_present} were already there')

class MikaTimingScraper(util.Scraper):
	PLATFORM_ID = 'mikatiming'

	def DetailedResultURL(self, platform_runner_id: str) -> str:
		res = f'{self.url}?content=detail&idp={platform_runner_id}'
		if self.attempt.scraped_event.extra_data:
			res += f'&event={self.attempt.scraped_event.extra_data}'
		if self.attempt.scraped_event.extra_data2:
			res += f'&event_main_group={self.attempt.scraped_event.extra_data2}'
		return res

	def _ParseUrlIfNeeded(self):
		if self.platform_series_id and self.platform_event_id:
			return
		parsed = parse.urlparse(self.url)
		if (not parsed.hostname) or (not parsed.path):
			raise util.IncorrectURL(self.url)
		self.platform_series_id = parsed.hostname # E.g. berlin.r.mikatiming.net
		self.platform_event_id = parsed.path.strip('/').split('/')[0] # E.g. "2023"
		if not self.platform_event_id:
			raise util.IncorrectURL(self.url)
		models.Scraped_event.objects.filter(url_site=self.url).update(platform_series_id=self.platform_series_id, platform_event_id=self.platform_event_id)

	def InitStandardFormDict(self):
		if not self.platform_event_id:
			raise util.NonRetryableError('InitStandardFormDict needs to know platform_event_id')
		if not self.event:
			raise util.NonRetryableError('InitStandardFormDict needs to know event')

		extra_data = self.attempt.scraped_event.extra_data
		races = self.event.race_set
		# To load several "events" from e.g. https://results.tcslondonmarathon.com/2024/ to different Races
		if extra_data and ((count := races.count()) > 1):
			race = races.filter(precise_name=extra_data).first()
			if not race:
				raise util.NonRetryableError(f'InitStandardFormDict: There are {count} races in the event id {self.event.id} but none have precise name {extra_data}')
		else:
			race = self.event.race_set.first()

		distance = race.distance
		self.standard_form_dict = {
			'id_on_platform': self.platform_event_id,
			'start_date': self.event.start_date.isoformat(),
		}
		self.standard_form_dict['races'] = [{
			'distance': {
				'distance_type': distance.distance_type,
				'length': distance.length,
			},
			'results': [],
			'results_brief_loaded': False,
			'results_detailed_loaded': False,
			'loaded_from': self.url,
		}]
		
		if (extra_data := self.attempt.scraped_event.extra_data):
			# So we already went through all available years for the series
			if (extra_data2 := self.attempt.scraped_event.extra_data2):
				self.standard_form_dict['platform_event_group_name'] = extra_data2
			# else:
			# 	# It is usually a year, e.g. https://chicago-history.r.mikatiming.com/2023
			# 	self.standard_form_dict['platform_event_group_name'] = self.platform_event_id
			self.standard_form_dict['platform_event_name'] = extra_data
		else:
			# So this is probably a page for just one event
			self.standard_form_dict['platform_event_group_name'], self.standard_form_dict['platform_event_name'] = EventAndRaceNames(self.url, self.title_page_soup)

	# Returns a dictionary: <0-indexed number of the column> -> <type of the column from COLUMN_NAMES.vals>
	def _ParseHeader(self, content: bs4.BeautifulSoup) -> dict[str, int]:
		res = {}
		res_reversed = {} # <type of the column from COLUMN_NAMES.vals> -> <0-indexed number of the column>
		for i, cell in enumerate(content.select('div.list-field')):
			string = HeaderName(cell).lower()
			if string not in COLUMN_NAMES:
				raise util.NonRetryableError(f'{self.url}: header: unknown column type "{string}"')
			column_type = COLUMN_NAMES[string]
			if (column_type in res_reversed) and (column_type != 'IGNORE'):
				raise util.NonRetryableError(f'{self.url}: header: we met "{string}" in column {i} but there is already {column_type} in column {res_reversed[column_type]}.')
			res[i] = column_type
			res_reversed[column_type] = i
		return res

	def ParseResultsPage(self, soup: bs4.BeautifulSoup) -> list[dict[any]]:
		headers_soup = soup.select('li.list-group.row.list-group-item.list-group-header')
		if (n_headers := len(headers_soup)) != 1:
			raise util.NonRetryableError(f'{self.url}: {n_headers} headers on the page but we need 1.')
		headers = self._ParseHeader(headers_soup[0])
		results = []
		for line_num, line in enumerate(soup.select('li.list-group-item.row')):
			if 'list-group-header' in line['class']:
				continue
			result = {}
			to_skip_line = False
			for i, field in enumerate(line.find_all(['div', 'h4'], class_='list-field')):
				try:
					if i not in headers:
						raise util.NonRetryableError(f'{self.url}: line {line_num}: we met field number {i} of unknown type. Headers: {headers}')
					if headers[i] == 'IGNORE':
						continue
					result[headers[i]], to_skip_line = ParseValue(field)
					if to_skip_line:
						break
					# print(f'Col {i} - line "{field}" - header {headers[i]} - strings {list(field.stripped_strings)} - result "{result[headers[i]]}"')
				except util.NonRetryableError as e:
					raise util.NonRetryableError(f'{self.url}: line {line_num}: field "{field}": {e}')
			if to_skip_line:
				continue
			name_fields = line.find_all('h4', class_='type-fullname')
			if len(name_fields) != 1:
				raise util.NonRetryableError(f'{self.url}: line {line_num}: {len(name_fields)} fields with runner name but we need 1.')
			if (self.event.id == 531) and (result['place_gender_raw'] is None): # Chicago 1996: marathon and wheelchairs are altogether
				continue
			result.update(NameCountryDict(OnlyString(name_fields[0])))

			details_tag = name_fields[0].find('a')
			if not details_tag:
				raise util.NonRetryableError(f'{self.url}: line {line_num}: The link to the result details not found.')
			details_url = details_tag['href']
			result['id_on_platform'] = parse.parse_qs(details_url)['idp'][0]
			result['status_raw'] = 'FINISHED'
			if not IsCorrectResultID(result['id_on_platform']):
				raise util.NonRetryableError(f'{self.url}: line {line_num}: runner ID {result["id_on_platform"]} for {result["fname_raw"]} {result["lname_raw"]} is invalid.')

			if result.get('club_raw') == '–':
				result['club_raw'] = ''

			results.append(result)
		return results

	# Returns a dict of result properties that aren't already in the `result` dict.
	def ParseDetailedResultPage(self, url: str, content: str, result_dict: dict[str, any]) -> dict[str, any]:
		res = {}
		soup = bs4.BeautifulSoup(content.replace('\n', ''), 'html.parser')
		for field_name, dict_key in (
			('Place Overall', 'place_raw'),
			('Place Age Group', 'place_category_raw'),
			('Gender', 'gender_raw'),
			('City, State', 'city_raw'),
		):
			if (dict_key not in result_dict) and (val := ElemOnDetailedPage(url, soup, field_name)) and (val != '–'):
				res[dict_key] = val

		res['splits'] = ParseSplits(url, soup)
		res['results_detailed_loaded'] = True
		soup.decompose()
		return res

	def _IncreaseGenderCounters(self, result_dict: dict[str, any]) -> str:
		place_gender = result_dict.get('place_gender_raw')
		if not place_gender:
			return ''
		# Usually the gap should be 0, but sometimes in can be big.
		# E.g. https://chicago-history.r.mikatiming.com/2023/?page=21&event=MAR_9TGG9638119&lang=EN_CAP&num_results=1000&pid=search&pidp=start&search%5Bage_class%5D=%25&search%5Bsex%5D=%25&search%5Bnation%5D=%25&search_sort=place_nosex
		# has gap 5 for women: Stein, Gail (USA)
		for max_gap in range(10):
			if abs(place_gender - self.n_males - 1) <= max_gap:
				self.n_males += 1
				return 'M'
			if abs(place_gender - self.n_females - 1) <= max_gap:
				self.n_females += 1
				return 'F'
			if abs(place_gender - self.n_nonbinary - 1) <= max_gap:
				self.n_nonbinary += 1
				return 'NB'
		if abs(1 - self.n_males / place_gender) < 0.3:
			self.n_males += 1
			return 'M'
		if abs(1 - self.n_females / place_gender) < 0.3:
			self.n_females += 1
			return 'F'
		return ''

	def FillGender(self, url: str, result_dict: dict[str, any]) -> dict[str, any]:
		if 'gender_raw' in result_dict:
			return {}
		category = result_dict.get('category_raw')
		if category:
			if (letter := category[0].upper()) in ('M', 'W'):
				return {'gender_raw': letter}
			if (category == '–') and (self.platform_series_id in ('berlin.r.mikatiming.net', 'chicago-history.r.mikatiming.com')):
				# E.g. https://berlin.r.mikatiming.net/2023/?content=detail&idp=HCH3C0OH71733
				return {'gender_raw': 'NB'}

		# Otherwise, we try to determine gender from the places.
		gender_from_place = self._IncreaseGenderCounters(result_dict)
		if gender_from_place:
			return {'gender_raw': gender_from_place}
		if result_dict.get('category_raw') == '–':
			return {'gender_raw': 'UNKNOWN'}
		if result_dict['id_on_platform'] in ('0000170E9A92360000159FD1', ):
			# https://chicago-history.r.mikatiming.com/2023/?page=21&event=MAR_9999990E9A9236000000006B&lang=EN_CAP&num_results=1000&pid=search&search%5Bage_class%5D=%25&search%5Bsex%5D=%25&search%5Bnation%5D=%25&search_sort=place_nosex
			# Ward, Amy (USA)
			return {'gender_raw': 'F'}
		raise util.NonRetryableError(f'{url}: we cannot extract gender. '
			+ f'place_gender: {result_dict.get("place_gender_raw")}, n_males: {self.n_males}, n_females: {self.n_females}, n_nonbinary: {self.n_nonbinary}')

	# Returns the number of just loaded brief results.
	def LoadBriefResults(self) -> int:
		race = self.standard_form_dict['races'][0]
		if race['results_brief_loaded'] or race.get('is_virtual'):
			return 0

		race['results'] = []
		page = 0
		while True:
			page += 1
			params = OrderedDict([
				('event', self.standard_form_dict['platform_event_name']),
				('page', page),
				('num_results', 1000),
				('pid', 'search'),
				('search[age_class]', '%'),
				('search[sex]', '%'),
				('search[nation]', '%'),
				('search_sort', 'place_nosex'),
			])
			if 'platform_event_group_name' in self.standard_form_dict:
				params['event_main_group'] = self.standard_form_dict['platform_event_group_name']
			content = util.LoadAndStore(self.DownloadedFilesDir(), self.url, method='GET', params=params, is_json=False, debug=1)
			soup = bs4.BeautifulSoup(content, 'html.parser')
			new_results = self.ParseResultsPage(soup)
			race['results'] += new_results
			if (page % 50) == 0:
				self.attempt.UpdateStatus(f'LoadBriefResults: Loaded {page} pages and {len(race["results"])} brief results.')
			next_page_exists = ResultsPageHasNextPageLink(soup)
			soup.decompose()
			if not next_page_exists:
				break
		race['results_brief_loaded'] = True
		return len(race['results'])

	# Returns the number of just loaded detailed results.
	def LoadDetailedResults(self) -> int:
		n_loaded_total = n_loaded_now = 0

		for race in self.standard_form_dict['races']:
			if race.get('results_detailed_loaded') or race.get('is_virtual'):
				n_loaded_total += len(race['results'])
				continue
			if not race['results_brief_loaded']:
				raise util.NonRetryableError(f'{self.platform_event_id}, {race['precise_name']}: brief results not loaded, but we are trying to load detailed ones')
			# To determine gender e.g. for https://results.tcslondonmarathon.com/2024
			self.n_males = self.n_females = self.n_nonbinary = 0

			for result_num, result_dict in enumerate(race['results']):
				if result_dict.get('results_detailed_loaded'):
					n_loaded_total += 1
					self._IncreaseGenderCounters(result_dict)
					continue
				params = {'runnerId': result_dict['id_on_platform']}
				url = self.DetailedResultURL(result_dict['id_on_platform'])
				res = util.LoadAndStore(self.DownloadedFilesDir(platform_runner_id=result_dict['id_on_platform']), url, is_json=False)
				result_dict.update(self.ParseDetailedResultPage(url=url, content=res, result_dict=result_dict))
				result_dict.update(self.FillGender(url=url, result_dict=result_dict))

				n_loaded_total += 1
				n_loaded_now += 1

				if (result_num % 1000) == 999:
					self.attempt.UpdateStatus(f'LoadDetailedResults: Loaded {result_num+1} detailed results out of {len(race["results"])}')
					self.DumpStandardForm()
					if self.ToStopNow():
						raise util.TimeoutError(f'Time out. Loaded {n_loaded_total} out of {len(race["results"])} detailed results')
			race['results_detailed_loaded'] = True
		print(f'{self.url}: just loaded {n_loaded_now} detailed results. Total {n_loaded_total} are loaded')
		return n_loaded_now

	def FindOrCreateEvent(self):
		if not self.event:
			raise util.NonRetryableError(f'{self.url}: no event specified')
		races = self.event.race_set.all()
		if (n_races := races.count()) != 1:
			raise util.NonRetryableError(f'{self.url}: {results_util.SITE_URL}{self.event.get_absolute_url()} has {n_races} races but we need exactly 1')
		race_dict = self.standard_form_dict['races'][0]
		if not race_dict.get('db_race_id'):
			race_dict['db_race_id'] = races[0].id
			self.DumpStandardForm()
		super().FindOrCreateEvent()

	def SaveEventDetailsInStandardForm(self):
		self._ParseUrlIfNeeded()
		self.title_page_soup = bs4.BeautifulSoup(util.LoadAndStore(self.DownloadedFilesDir(), self.url, is_json=False), 'html.parser')
		if os.path.isfile(self.StandardFormPath()):
			print(f'Reading all event data from {self.StandardFormPath()}')
			with io.open(self.StandardFormPath(), encoding="utf8") as json_in:
				self.standard_form_dict = json.load(json_in)
		else:
			self.InitStandardFormDict()
			if self.reason_to_ignore:
				return

		if self.LoadBriefResults() > 0:
			self.DumpStandardForm()
		if not self.standard_form_dict['races']:
			raise util.NonRetryableError(f'{self.url}: no distances!')
		if self.LoadDetailedResults() > 0: # TODO
			self.DumpStandardForm()
