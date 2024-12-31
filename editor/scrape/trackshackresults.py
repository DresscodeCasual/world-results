from typing import List, Tuple, Dict, Optional
import bs4
from collections import OrderedDict
import json
import os
import pathlib
import requests
from urllib import parse

from results import models, results_util
from editor import parse_strings
from . import util

# По URL страницы со списком дистанций забега вроде https://www.trackshackresults.com/disneysports/results/wdw/wdw23/index.php
# возвращает список пар: <ссылка на результаты дистанции, название дистанции>.
def FetchAndFollowLinks(mydir: pathlib.Path, url: str) -> list[tuple[str, str]]:
	"""
	Получает страницу по указанному URL и извлекает ссылки на страницы с результатами.

	Параметры:
		url (str): URL страницы.

	Возвращает:
		List[Tuple[str, str]]: Список кортежей, содержащих ссылки и текстовые описания.
	"""  
	contents = util.LoadAndStore(mydir, url, is_json=False)
	soup = bs4.BeautifulSoup(contents, 'html.parser')
	urls_h2 = soup.find_all('h2')
	url_list = [a for h2 in urls_h2 for a in h2.find_all('a')]
	urls = []
	for u in url_list:
		href = u.get('href')
		
		full_href = url + '/' + href
		# Some links lead to e.g. PDF files. We cannot decode them. Usually they correspond to multi-race challanges that we ignore anyway.
		if not href or '.php' not in href:
			continue
		page_response = requests.get(full_href)
		page_data = page_response.url
		text = u.text.replace(' Results', '')
		# print(text)
		# res = ({ur, res} for ur in )
		urls.append((page_data, text))
	return urls

# TODO(serg): Add a comment and types.
def FetchDropdownOptions(mydir: pathlib.Path, url: str) -> List[Tuple[str, str]]:
	"""
	Извлекает опции выпадающего списка с указанной страницы.

	Параметры:
		url (str): URL страницы.

	Возвращает:
		List[Tuple[str, str]]: Список кортежей, содержащих значения и текст опций.
	"""	
	contents = util.LoadAndStore(mydir, url, is_json=False)
	print(f'Fetching {url}')
	soup = bs4.BeautifulSoup(contents, 'html.parser')
	dropdown = soup.find('select', {'id': 'select1'})
	options = dropdown.find_all('option')
	res = []
	for opt in options:
		if not opt.get('value'):
			continue
		option_name = opt.text.strip()
		if 'duo division' in option_name.lower():
			# Usually a wheelchair + runner: https://www.rundisney.com/events/disneyworld/disneyworld-marathon-weekend/race-policies/
			# with no gender specified. Let's ignore them for now.
			continue
		res.append((opt['value'].strip(), option_name))
	return res

# TODO(serg): Add a comment and types.
def ParseAthleteRow(columns: List, category: str, url: str, precise: str, additional: List[Dict[int, str]]) -> Tuple[Dict, str]:
	"""
    Парсит строку таблицы с данными участника.

	Проверяет категорию и специфику атлета

    Параметры:
        columns (List): Список ячеек строки.
        text (str): Текст категории.
        url (str): URL страницы с данными.
        precise (str): Точное название.
        additional (List[Dict[int, str]]): Дополнительные данные.

    Возвращает:
		Tuple[Dict, str]:
        Dict: Словарь с данными участника, 
		str: Спецификация атлета.
    """
	WheelSpecification = (
    'PUSH RIM' if 'push rim' in category.lower() else 
    'HAND CYCLE' if 'hand cycle' in category.lower() else 
    False
    )   
	
	name = columns[1].text.strip()
	geography = columns[-1].text
	splits = []
	
	for a in additional:
		for k, v in a.items():
			if not v.endswith(' Split'):
				raise util.NonRetryableError(f'{url}: Column name "{v}" does not look like a split')
			maybe_split_name = util.RemoveSuffix(v, ' Split')
			split_length = parse_strings.parse_meters(name=maybe_split_name)
			if not split_length:
				raise util.NonRetryableError(f'{url}: we cannot recognize split distance "{v}"')
			splits.append({
				'distance': {
					'distance_type': models.TYPE_METERS,
					'length': split_length,
				},
				'value': models.string2centiseconds(columns[k].text.strip()),
			})
	# print()
	# print(additional_updated)
	if geography:
		country_region = geography.split(', ')[1].strip() 
		if len(country_region) > 2:
			country_region = {'country_raw': country_region}
		else:
			country_region = {'region_raw': country_region}
	else:
		country_region = None

	ret = {
		'name_raw': name,
		'lname_raw': name.split(' ')[-1],
		'fname_raw': ' '.join(part.strip() for part in name.split(' ')[:-1]),
		'result_raw': columns[-3].text.strip(),
		'city_raw': geography.split(', ')[0].strip(),
		'age_raw': columns[3].text.strip(),
		'place_raw': columns[4].text.strip(),
		'place_gender_raw': columns[5].text.strip(),
		'status_raw': 'finished' if columns[-3].text.strip() else 'processing',
		'category_raw': category,
		'gender_raw': 'women' if 'women' in category.lower()
					else 'men' if 'men' in category.lower() else None,
		'birthday_known': False,
		'splits': splits,
	}
	if country_region:
		ret.update(country_region)
	return ret, WheelSpecification
# Athelete specification
def SaveToCorrectAthletesList(data, WheelSpecification, Athletes, PushRimAthletes, HandCycleAthletes):
    if WheelSpecification == False:
        Athletes.append(data)
    elif WheelSpecification == "PUSH RIM":
        PushRimAthletes.append(data)
    else:
        HandCycleAthletes.append(data)

# TODO(serg): Add a comment and types.
def FetchAthleteData(mydir, option_values, url, precise):
	"""
    Извлекает данные участников.

    Параметры:
        option_values (List[Tuple[str, str]]): Список опций из выпадающего списка.
        url (str): URL страницы с данными.
        precise (str): Точное название категории.

    Возвращает:
        List[Dict]: Список данных участников.
    """
	# Adding three main branches of athletes
	athletes = []
	PushRimAthletes = []
	HandCycleAthletes = []
	ind = 0
	for div, text in option_values:
		params = OrderedDict([
			('Link', 126),
			('Type', 2),
			('Div', div),
			('Ind', ind),
		])
		contents = util.LoadAndStore(mydir, url, params=params, is_json=False)
		full_url = url + '?' + parse.urlencode(params)
		soup = bs4.BeautifulSoup(contents, 'html.parser')
		info_table = soup.find('table', class_='info_table')
		additional = info_table.find_all('tr')[0]
		additional = [a.text.strip() for a in additional]

		# TODO(serg): Make it more readable.
		for i, a in enumerate(additional):
			if a == '':
				additional.remove(a)
		for i, a in enumerate(additional):
			additional[i] = {i: a}
		
		
		additional = additional[6:-3]
		rows = soup.find_all('tr', class_='norm_row') + soup.find_all('tr', 'alt_row')
		if not rows:
			break
		for row in rows:
			columns = row.find_all('td')

			data, WheelSpecification = ParseAthleteRow(columns, text, full_url, precise, additional)
			SaveToCorrectAthletesList(data, WheelSpecification, athletes, PushRimAthletes, HandCycleAthletes)
            
		ind += 1
	return athletes


class TrackShackResultsScraper(util.Scraper):
	PLATFORM_ID = 'trackshackresults'

	def _ParseUrlIfNeeded(self):
		if self.platform_series_id and self.platform_event_id:
			return
		parsed = parse.urlparse(util.RemoveSuffix(self.url, '/index.php'))
		if (not parsed.hostname) or (not parsed.path):
			raise util.IncorrectURL(self.url)
		if parsed.hostname != 'www.trackshackresults.com':
			raise util.IncorrectURL(self.url)
		self.platform_series_id = self.platform_event_id = util.RemovePrefix(parsed.path, '/')
		if not self.platform_event_id:
			raise util.IncorrectURL(self.url)
		self.attempt.scraped_event.platform_series_id = self.platform_series_id
		self.attempt.scraped_event.platform_event_id = self.platform_event_id
		self.attempt.scraped_event.save()

	def LoadResults(self):
		mydir = self.DownloadedFilesDir()
		# Last one is index.php which leads to all the previous ones.
		urls = FetchAndFollowLinks(mydir, self.url)[:-1]

		for url, distance_name in urls:
			length = util.FixLength(parse_strings.parse_meters(name=distance_name, platform_id=self.PLATFORM_ID))
			if not length:
				raise util.NonRetryableError(f'We cannot recognize distance "{record["distance"]}"')

			option_values = FetchDropdownOptions(mydir, url)
			athletes, PushRimAthletes, HandCycleAthletes = FetchAthleteData(mydir, option_values, url, distance_name)

			self.standard_form_dict['races'].append({
				'distance': {
					'distance_type': models.TYPE_METERS,
					'length': length,
				},
				'precise_name': distance_name,
				'results': athletes,
			})
			if HandCycleAthletes:
				self.standard_form_dict['races'].append({
					'distance': {
						'distance_type': models.TYPE_METERS,
						'length': length,
					},
					'precise_name': 'hand cycle',
					'results': HandCycleAthletes,
					'is_for_handicapped': True
			})
			if HandCycleAthletes:
				self.standard_form_dict['races'].append({
					'distance': {
						'distance_type': models.TYPE_METERS,
						'length': length,
					},
					'precise_name': 'push rim',
					'results': PushRimAthletes,
					'is_for_handicapped': True
			})


	def InitStandardFormDict(self):
		if not self.platform_event_id:
			raise util.NonRetryableError('InitStandardFormDict needs to know platform_event_id')
		if not self.event:
			raise util.NonRetryableError('InitStandardFormDict needs to know event')
		races = self.event.race_set.all()
		self.standard_form_dict = {
			'id_on_platform': self.platform_event_id,
			'start_date': self.event.start_date.isoformat(),
			'races': [],
		}
		
	def SaveEventDetailsInStandardForm(self):
		self._ParseUrlIfNeeded()
		if os.path.isfile(self.StandardFormPath()):
			print(f'Reading all event data from {self.StandardFormPath()}')
			with io.open(self.StandardFormPath(), encoding="utf8") as json_in:
				self.standard_form_dict = json.load(json_in)
		else:
			self.InitStandardFormDict()
			self.LoadResults()
			self.DumpStandardForm()

