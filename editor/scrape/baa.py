import bs4
from collections import OrderedDict
import io
import json
import os
import requests
import time
import urllib.parse

from results import models, results_util
from editor import parse_strings
from . import util

# For each field in the standard form for the result, we list all possible column names.
COLUMN_NAMES = {
	'year': 'IGNORE',
	'ctz': 'IGNORE',

	'age': 'age_raw',

	'bib': 'bib_raw',

	'ac': 'category_raw',
	'category': 'category_raw',
	'division': 'category_raw',

	'overall': 'place_raw',
	'gender': 'place_gender_raw',
	'division': 'place_category_raw',

	'm/f': 'gender_raw',

	'city': 'city_raw',
	'state': 'region_raw',
	'st': 'region_raw',
	'country': 'country_raw',
	'ctry': 'country_raw',

	'name': 'name_raw',

	'net time': 'result_raw',
	'official finish': 'result_raw',
	'official time': 'gun_time_raw',
}

def _NonStringContents(elem: bs4.Tag) -> list[bs4.Tag]:
	return [item for item in elem.contents if (type(item) != bs4.element.NavigableString)]

def ProcessPageHeader(url: str, header: bs4.Tag) -> dict[int, str]:
	header_cols = {}
	if header_cols:
		raise util.NonRetryableError('header_cols is non-empty but ProcessPageHeader was called')
	for i, item in enumerate(header_list := list(header.find_all('th'))):
		col_name = item.string.strip().lower()
		if col_name in COLUMN_NAMES:
			header_cols[i] = COLUMN_NAMES[col_name]
		elif (col_name in ('', '&nbsp;')) and (i == len(header_list) - 1):
			header_cols[i] = 'race_type'
		else:
			raise util.NonRetryableError(f'{url}: header: unknown column type "{col_name}"')
	return header_cols

def AddSplit(result_desc: str, result_dict: dict[str, any], length: int, value_raw: str):
	if 'splits' not in result_dict:
		result_dict['splits'] = []
	for split in result_dict['splits']:
		if split['distance']['length'] == length:
			raise util.NonRetryableError(f'{result_desc}: There are two splits of length {length}, {split["value"]} and {value_raw}')
	value = models.string2centiseconds(value_raw)
	if not value:
		raise util.NonRetryableError(f'{result_desc}: Could not parse time from {value_raw}')
	result_dict['splits'].append({
		'distance': {
			'distance_type': models.TYPE_METERS,
			'length': length,
		},
		'value': value,
	})

# Returns:
# 1. The type of the race that the result belongs to (normal, wheelchair, etc),
# 2. The result dict in the standard form.
def ExtractResultDict(url: str, header_cols: dict[int, str], index: int, row1: bs4.Tag, row2: bs4.Tag) -> tuple[str, dict[str, any]]:
	res = {'status_raw': 'FINISHED'}
	if row1.name != 'tr':
		raise util.NonRetryableError(f'{url}, row {index}: tag is {row1.name} but we expected "tr"')
	if row2.name != 'tr':
		raise util.NonRetryableError(f'{url}, row {index+1}: tag is {row2.name} but we expected "tr"')
	
	for cell_num, cell in enumerate(_NonStringContents(row1)):
		if cell.name != 'td':
			raise util.NonRetryableError(f'{url}, row {index}: {cell_num}-th element is {cell.name} but we expected "td"')
		if header_cols[cell_num] != 'IGNORE':
			res[header_cols[cell_num]] = str(cell.string).strip()

	subtable = _NonStringContents(row2.td.table)
	headers = _NonStringContents(subtable[0])[1:]
	values = _NonStringContents(subtable[1])
	if len(headers) != len(values):
		raise util.NonRetryableError(f'{url}, row {index+1}: there are {len(headers)} headers but only {len(values)} values')
	for header_tag, value_tag in zip(headers, values):
		if header_tag.name != 'th':
			raise util.NonRetryableError(f'{url}, row {index+1}, header {header_tag}: tag is {header_tag.name} but we expected "th"')
		if value_tag.name != 'td':
			raise util.NonRetryableError(f'{url}, row {index+1}, value {value_tag}: tag is {value_tag.name} but we expected "td"')
		header = header_tag.string.lower()
		value = value_tag.string.strip()
		if header == '5k chkpt':
			AddSplit(result_desc=f'{url}, row {index+1}', result_dict=res, length=5000, value_raw=value)
			continue
		if header not in COLUMN_NAMES:
			raise util.NonRetryableError(f'{url}, row {index+1}: header {header} is unknown')
		if COLUMN_NAMES[header].startswith('place_'): # These are like '2 / 100' or '-'
			if value == '-':
				value = None
			else:
				value = results_util.int_safe(value.split('/')[0].strip())
				if not value:
					raise util.NonRetryableError(f'{url}, row {index+1}, column {COLUMN_NAMES[header]}: value {value_tag.string} does not have an integer place')
		else:
			value = str(value)
		res[COLUMN_NAMES[header]] = value

	if ('name_raw' in res) and ('lname_raw' not in res):
		# E.g. Plankenauer, Mag., Adolf Horst -> lname 'Plankenauer, Mag.' and fname 'Adolf Horst'
		parts = res['name_raw'].split(', ')
		if len(parts) < 2:
			raise util.NonRetryableError(f'{url}, row {index}: cannot extract last name from "{res["name_raw"]}"')
		res['lname_raw'] = ', '.join(parts[:-1]).strip()
		res['fname_raw'] = parts[-1].strip()

	race_type = res.pop('race_type', '')
	if res.get('gun_time_raw') == '-':
		del res['gun_time_raw']

	if res.get('result_raw') in ('-', ''):
		if res.get('gun_time_raw'):
			res['result_raw'] = res['gun_time_raw']
		else:
			raise util.NonRetryableError(f'{url}, row {index}, name {res["name_raw"]}, bib {res["bib_raw"]}: no result or gun time')
	return race_type, res

def AddEventsToQueue(series_id: int):
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

def AddMarathon(year: int):
	event = models.Event.objects.get(series__name='Boston Marathon', start_date__year=year)
	scraped_event, _ = models.Scraped_event.objects.get_or_create(
		platform_id=BaaScraper.PLATFORM_ID,
		url_site='http://registration.baa.org/cfm_Archive/iframe_ArchiveSearch.cfm',
		url_results='http://registration.baa.org/cfm_Archive/iframe_ArchiveSearch.cfm',
		platform_series_id='registration.baa.org/cfm_Archive/iframe_ArchiveSearch.cfm',
		platform_event_id=str(year),
		event=event,
	)
	return scraped_event

def AddMarathons():
	for year in range(2001, 2017):
		event = models.Event.objects.get(series__name='Boston Marathon', start_date__year=year)
		scraped_event, _ = models.Scraped_event.objects.get_or_create(
			platform_id=BaaScraper.PLATFORM_ID,
			url_site='http://registration.baa.org/cfm_Archive/iframe_ArchiveSearch.cfm',
			url_results='http://registration.baa.org/cfm_Archive/iframe_ArchiveSearch.cfm',
			platform_series_id='registration.baa.org/cfm_Archive/iframe_ArchiveSearch.cfm',
			platform_event_id=str(year),
			event=event,
		)

# One scraping example: https://github.com/Kobold/scrape_boston_marathon/blob/master/main.py
class BaaScraper(util.Scraper):
	PLATFORM_ID = 'baa'
	header_cols = {}

	def ProcessRaceType(self, race_type: str):
		if race_type in self.race_num:
			return
		# So we haven't met this race_type (e.g. wheelchair) before. Let's add it.
		self.standard_form_dict['races'].append({
			'distance': {
				'distance_type': models.TYPE_METERS,
				'length': 42195,
			},
			'results': [],
			'results_detailed_loaded': False,
			'is_for_handicapped': True,
			'loaded_from': self.url,
			'precise_name': race_type.title(),
		})
		self.race_num[race_type] = len(self.standard_form_dict['races']) - 1


	def LoadResults(self):
		# Thanks to https://github.com/Kobold/scrape_boston_marathon
		params = OrderedDict([
			('mode', 'results'),
			('criteria', ''),
			('StoredProcParamsOn', 'yes'),
			('VarRaceYearLowID', self.platform_event_id),
			('VarRaceYearHighID', '0'),
			('records', '25'),
			('VarAgeLowID', '0'),
			('VarAgeHighID', '0'),
			('VarGenderID', '0'),
			('VarBibNumber', ''),
			('VarLastName', ''),
			('VarFirstName', ''),
			('VarStateID', '0'),
			('VarCountryOfResidenceID', '0'),
			('VarCity', ''),
			('VarZip', ''),
			('VarTimeLowHr', ''),
			('VarTimeLowMin', ''),
			('VarTimeLowSec', '00'),
			('VarTimeHighHr', ''),
			('VarTimeHighMin', ''),
			('VarTimeHighSec', '59'),
			('VarSortOrder', 'ByTime'),
			('VarAddInactiveYears', '0'),
			('headerexists', 'Yes'),
			('queryname', 'SearchResults'),
			('tablefields', 'RaceYear,FullBibNumber,FormattedSortName,AgeOnRaceDay,GenderCode,City,StateAbbrev,CountryOfResAbbrev,ReportingSegment'),
		])
		start = 1
		while True:
			post_params = OrderedDict([
				('start', start),
				('next', 'Next 25 Records'),
			])
			# response = requests.post(
			# 	'http://registration.baa.org/cfm_Archive/iframe_ArchiveSearch.cfm',
			# 	headers=results_util.HEADERS,
			# 	params=params,
			# 	data=post_params,
			# )
			# content = response.text
			url = f'http://{self.platform_series_id}?{urllib.parse.urlencode(params)}'
			content = util.LoadAndStore(self.DownloadedFilesDir(), url=url, method='POST', params=post_params, is_json=False, arg_for_post_data='data', debug=1)
			soup = bs4.BeautifulSoup(content, 'html.parser')
			print(f'Received {len(content)} bytes')
			print(f'Found {len(list(soup.find_all("table", class_="table_infogrid")))} results')
			print(url)

			table = soup.find('table', class_='tablegrid_table')
			if not self.header_cols:
				self.header_cols = ProcessPageHeader(self.url, table.thead.tr)

			items = _NonStringContents(table.tbody)
			if not items:
				raise util.NonRetryableError(f'{response.url}: no items found. Length of page: {len(content)}')

			for i in range(0, len(items) - 1, 2):
				# print(f'i={i}: calling ExtractResultDict with row1="{items[i]}", row2="{items[i+1]}"')
				race_type, result_dict = ExtractResultDict(self.url, self.header_cols, i, items[i], items[i+1])
				self.ProcessRaceType(race_type)
				self.standard_form_dict['races'][self.race_num[race_type]]['results'].append(result_dict)
			soup.decompose()
			if 'Next 25 Records' not in content:
				break
			start += 25
			if (start % 5000) == 1:
				self.attempt.UpdateStatus(f'LoadResults: Loaded {start-1} results')
				# self.DumpStandardForm()
				if self.ToStopNow():
					raise util.TimeoutError(f'Time out. Loaded {start-1} results')

	def FindOrCreateEvent(self):
		if not self.event:
			raise util.NonRetryableError(f'{self.url}: no event specified')
		super().FindOrCreateEvent()

	def InitStandardFormDict(self):
		if not self.platform_event_id:
			raise util.NonRetryableError('InitStandardFormDict needs to know platform_event_id')
		if not self.event:
			raise util.NonRetryableError('InitStandardFormDict needs to know event')
		race = self.event.race_set.first()
		distance = race.distance
		self.standard_form_dict = {
			'id_on_platform': self.platform_event_id,
			'start_date': self.event.start_date.isoformat(),
		}
		self.standard_form_dict['races'] = [{
			'distance': {
				'distance_type': models.TYPE_METERS,
				'length': 42195,
			},
			'results': [],
			'results_detailed_loaded': False,
			'loaded_from': self.url,
		}]
		self.race_num = {'': 0} # race_type -> index in self.standard_form_dict['races']
		
	def SaveEventDetailsInStandardForm(self):
		if os.path.isfile(self.StandardFormPath()):
			print(f'Reading all event data from {self.StandardFormPath()}')
			with io.open(self.StandardFormPath(), encoding="utf8") as json_in:
				self.standard_form_dict = json.load(json_in)
		else:
			self.InitStandardFormDict()
			self.LoadResults()
			self.DumpStandardForm()
