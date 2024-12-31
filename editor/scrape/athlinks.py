from collections import Counter, defaultdict, OrderedDict
import datetime
import io
import json
import os
import re
import time
import traceback

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, List, Optional
import requests

from django.conf import settings
from django.core.files import File
from django.db.models import Q

from results import links, models, results_util
from editor import parse_protocols, parse_strings, runner_stat
from editor.views import views_result
from . import util, athlinks_xlsx

ATHLINKS_TEMP_DIR = os.path.join(settings.INTERNAL_FILES_ROOT, 'athlinks')

ATTEMPT_TIMEOUT = datetime.timedelta(hours=5)

RACES_WITH_BAD_OVERALL_BRACKETS = (
	836628, # Peachtree Road Race 2011, https://www.athlinks.com/event/115192/results/Event/145638/Course/836628/Results - everyone is both male and female
	29125, # New Haven Road Race 2005, https://www.athlinks.com/event/19924/results/Event/19467/Course/29125/Bib/9999 - duplicate brackets
	787186, # New Haven Road Race 1999, https://www.athlinks.com/event/19924/results/Event/54546/Course/787186/Bib/4627 - duplicate brackets
	98050, # New Haven Road Race 2008, https://www.athlinks.com/event/19924/results/Event/65653/Course/98050/Bib/2 - all duplicate
	2003757, # Miami Marathon 2021, https://www.athlinks.com/event/3294/results/Event/956719/Course/2003757/Bib/2826 - two results with this bib
)

RACES_WITH_BAD_GENDER_BRACKETS = (
	836628, # Peachtree Road Race 2011, https://www.athlinks.com/event/115192/results/Event/145638/Course/836628/Results - everyone is both male and female
	29125, # New Haven Road Race 2005, https://www.athlinks.com/event/19924/results/Event/19467/Course/29125/Bib/9999 - duplicate brackets
	787186, # New Haven Road Race 1999, https://www.athlinks.com/event/19924/results/Event/54546/Course/787186/Bib/4627 - duplicate brackets
	98050, # New Haven Road Race 2008, https://www.athlinks.com/event/19924/results/Event/65653/Course/98050/Bib/2 - all duplicate
	2003757, # Miami Marathon 2021, https://www.athlinks.com/event/3294/results/Event/956719/Course/2003757/Bib/2826 - two results with this bib
)

RACES_TO_IGNORE = frozenset([
	318499, # Relay with repeating name Run-Marathon: https://www.athlinks.com/event/3241/results/Event/109837/Course/318499/Results
	87253, # https://www.athlinks.com/event/7380/results/Event/57905/Results - duplicate race
	364365, 574254, 364362, # Duplicates in the Mud In Your Eye XC Series 2008: https://www.athlinks.com/event/8902/results/Event/116504/Results
	1429346, 574708, # Duplicates in the Mud In Your Eye XC Series 2006: https://www.athlinks.com/event/8902/results/Event/7837/Results
	292846, # https://www.athlinks.com/event/12759/results/Event/241007/Course/292846/Results - 2 races with same name, sent a letter
	705690, # https://www.athlinks.com/event/13315/results/Event/468967/Course/705690/Results - sum of results for 5K & 10K
	265027, 273416, # https://www.athlinks.com/event/13914/results/Event/191350/Results - strange repeating distances
	617157, # https://www.athlinks.com/event/16739/results/Event/362830/Results - 2 races with same name
	618642, # https://www.athlinks.com/event/18578/results/Event/400806/Course/618642/Results - 2 races with same name
	126353, # https://www.athlinks.com/event/20126/results/Event/88368/Course/126353/Results - probably canicross
])

RACES_WITH_BAD_AGE_BRACKETS = (
	1981789, # San Francisco 2020, https://www.athlinks.com/event/1403/results/Event/949361/Course/1981792/Results - both 50-54 and 50-59
	1981790, # Same
	1981791, # Same
	1981792, # Same
	1981788, # Same
	1981787, # Same
	694055,  # San Francisco 2015, https://www.athlinks.com/event/1403/results/Event/467138/Course/694055/Results - same
	1056647, # New Haven Road Race 2017, https://www.athlinks.com/event/19924/results/Event/669186/Results
	912723,  # Same
	1934875, # New Haven Road Race 2020, https://www.athlinks.com/event/19924/results/Event/940328/Course/1934875/Results - M17-18 and M15-19
	1934874, # Same
	1934873, # Same
	1934876, # Same
	29125, # New Haven Road Race 2005, https://www.athlinks.com/event/19924/results/Event/19467/Course/29125/Bib/9999 - duplicate brackets
	787186, # New Haven Road Race 1999, https://www.athlinks.com/event/19924/results/Event/54546/Course/787186/Bib/4627 - duplicate brackets
	98050, # New Haven Road Race 2008, https://www.athlinks.com/event/19924/results/Event/65653/Course/98050/Bib/2 - all duplicate
	2003758, # Miami Marathon & Half 2021, https://www.athlinks.com/event/3294/results/Event/956719/Course/2003758 M13-14 and M10-14
	2003757, # Miami Marathon 2021, https://www.athlinks.com/event/3294/results/Event/956719/Course/2003757/Bib/2826 - two results with this bib
	2003756, # same
)

RACES_WITH_TEAM_RESULTS = frozenset([
	138928, # https://www.athlinks.com/event/1581/results/Event/47634/Course/138928/Bib/1544
	148135, # Relay: https://www.athlinks.com/event/1034/results/Event/107826/Course/148135/Results
	272789, # Relay: https://www.athlinks.com/event/1314/results/Event/216770/Course/272789/Bib/1944
	253253, # https://www.athlinks.com/event/1581/results/Event/158980/Course/253253/Bib/4068
])

EVENTS_WITH_METADATA_BUGS = frozenset([
	'912062', # https://www.athlinks.com/event/1015/results/Event/912062/Results is in 2021 but https://results.athlinks.com/metadata/event/912062 says 2022
	'849790', # https://www.athlinks.com/event/1162/results/Event/849790/Results - called "2020 Carlsbad 5000 don't use"
	'1041646', # https://www.athlinks.com/event/1263/results/Event/1041646/Results - there are two events in the series at 2023-02-19
	'54081', # https://www.athlinks.com/event/1561/results/Event/54446/Results - there are duplicate events on 2008-05-03
	'377635', # https://www.athlinks.com/event/1561/results/Event/681298/Results - there are duplicate events on 2005-04-30
	'681298', # https://www.athlinks.com/event/1561/results/Event/681298/Course/1094348/Results - duplicate event on 2005-04-30
	'666109', # https://www.athlinks.com/event/2169/results/Event/666109/Results
	'546909', # https://www.athlinks.com/event/2334/results/Event/546909/Results - Results from 2017 but the date is 2016
	'1051509', # https://www.athlinks.com/event/4199/results/Event/1051509/Results - results from 2023 but date is 2022
	'638171', # https://www.athlinks.com/event/4231/results/Event/638171/Results - there's also https://www.athlinks.com/event/4231/results/Event/540550/Results with same date
	'993830', # https://www.athlinks.com/event/4264/results/Event/993830/Results - duplicate event on 2021-07-04
	'875381', # https://www.athlinks.com/event/4852/results/Event/875381/Results - No results
	'877074', # https://www.athlinks.com/event/4852/results/Event/877074/Results - No results
	'691048', # https://www.athlinks.com/event/4852/results/Event/691048/Results - duplicate event
	'376942', # https://www.athlinks.com/event/6269/results/Event/376942/Results - duplicate
	'875174', # https://www.athlinks.com/event/6430/results/Event/875174/Results - duplicate and no metadata
	'622852', # https://www.athlinks.com/event/6464/results/Event/622852/Results - duplicate
	'596782', # https://www.athlinks.com/event/7065/results/Event/596782/Results - duplicate
	'47044', # https://www.athlinks.com/event/7119/results/Event/47044/Results - triathlon only
	'20580', # https://www.athlinks.com/event/7119/results/Event/20580/Results - triathlon only
	'821008', # https://www.athlinks.com/event/7502/results/Event/821008/Results - duplicate
	'599451', # https://www.athlinks.com/event/7502/results/Event/599451/Results - nothing
	'821008', # https://www.athlinks.com/event/7502/results/Event/821008/Results - duplicate
	'441', # https://www.athlinks.com/event/10455/results/Event/441/Results - triathlon only
	'294784', # https://www.athlinks.com/event/11265/results/Event/294784/Results - duplicate
	'721048', # https://www.athlinks.com/event/11580/results/Event/721048/Results - duplicate
	'670493', # https://www.athlinks.com/event/12064/results/Event/670493/Results - duplicate
	'627290', # https://www.athlinks.com/event/13086/results/Event/627290/Results - duplicate
	'624210', # https://www.athlinks.com/event/14084/results/Event/624210/Results - duplicate
])

# For some events there are contradictions between series metadata and event metadata, e.g. https://results.athlinks.com/metadata/event/546909
CORRECT_START_DATES = {
	# '546909': '2016-05-21', # https://www.athlinks.com/event/2334/results/Event/546909/Results
	'741496': '2018-06-09', # https://www.athlinks.com/event/10439/results/Event/741496/Results
}

BAD_STATUSES = frozenset(['PENDING', 'NOT_SELECTED', 'NEW'])

class InternalAthlinksError(util.WaitAndRetryError): # When Athlinks returns Internal Server Error. Maybe it means it throttles us.
	pass

class IncorrectBibError(util.NonRetryableError): # When /individual returns incorrect bib (usually None)
	pass

class ResultDetailsAbsentError(Exception): # When /individual continuously returns bib ''. It usually means there's no data about it.
	pass

class JsonParsingError(util.NonRetryableError): # When Json from Athlinks has some unexpected value.
	pass

class TimeoutError(util.RetryableError): # When the script successfully worked for more than ATTEMPT_TIMEOUT. We then continue the same attempt again.
	pass

def SeriesMetadataURL(platform_series_id: str) -> str:
	return f'https://alaska.athlinks.com/MasterEvents/Api/{platform_series_id}'

def RunnerDetailsUrl(runner_id: int) -> str:
	return f'https://alaska.athlinks.com/Athletes/Api/{runner_id}'

def get_runner_results_url(runner_id: int) -> str:
	return f'https://alaska.athlinks.com/athletes/api/{runner_id}/Races'

def ToIgnoreSplit(platform_series_id: str, interval: dict) -> bool:
	if interval['pace']['distance']['distanceInMeters'] in (0, -1):
		# -1: e.g. https://results.athlinks.com/individual?eventId=996213&eventCourseId=2158909&bib=351
		# - probably for strange splits like triathlon transits.
		return True
	if (platform_series_id == '6538') and \
			(interval['intervalName'] in ('10 Mile Split', '15 Mile Split', '20k Split', '30k Split')):
		# https://www.athlinks.com/event/6538/results/Event/1074950/Course/2449739/Bib/735
		return True
	if (platform_series_id == '1364') and (interval['intervalName'] == 'Second Half'):
		# Two splits of length 10541: https://www.athlinks.com/event/1364/results/Event/883639/Course/1694675/Bib/560
		return True
	if (platform_series_id == '6318') and (interval['intervalName'] == 'Full Course'):
		# https://www.athlinks.com/event/6318/results/Event/1023808/Course/2267849/Bib/745
		return True
	if interval['intervalName'].lower() in ('announcer', 'announce'):
		# https://www.athlinks.com/event/4749/results/Event/1043907/Course/2341487/Bib/133 - something strange
		# And https://www.athlinks.com/event/6318/results/Event/1023808/Course/2267849/Bib/745
		return True
	return False

# Athlinks usually stores timestamps as a dictionary with fields `timeInMillis` and `timeZone` (usually UTC).
# We ignore the latter for now.
def DateFromDict(eventStartTime: dict[str, any]) -> datetime.date:
	return datetime.datetime.utcfromtimestamp(eventStartTime['timeInMillis'] // 1000).date()

def IsForHandicapped(race_name: str) -> bool:
	for substr in ('wheelchair', 'push assist'):
		if substr in race_name.lower():
			return True
	return False

# Whether we want to completely ignore a race.
def ToIgnoreRace(metadata: Dict[str, Any]) -> bool:
	name_lower = metadata['eventCourseName'].lower()
	if name_lower in (
			'deferred',
			'team crossfit',
			'virtual paw\'er challenge',
			'dolphin challenge', # https://www.athlinks.com/event/3175/results/Event/169734/Course/278050/Results
			'whale challenge', # https://www.athlinks.com/event/3175/results/Event/141101/Results
			'relay', # https://www.athlinks.com/event/7119/results/Event/1009768/Results
		):
		return True
	if results_util.anyin(name_lower, ('cycling', 'duathlon', 'triathlon', 'swimming', 'aquabike', 'bike 18 miles', 'team adventure', 'run-swim-run', 'run swim run', 'aquathlon')):
		return True
	for prefix in ('sprint relay', 'race sprint tri', 'race tri', 'sprint tri', 'tri-', 'tri #', 'race dua', '24 hrs '):
		if name_lower.startswith(prefix):
			return True
	if metadata['eventCourseId'] in RACES_TO_IGNORE:
		return True
	return False

def is_internal_error(response: Any) -> bool:
	return isinstance(response, dict) and (len(response) == 1) and (response.get('message', '').lower() == 'internal server error')

# Returns:
# 1. whether bib is correct,
# 2. the error message about bib if incorrect,
# 3. if the error is retryable.
def ids_are_correct(response: Any, bib_to_check: str, entryId_to_check: int) -> tuple[bool, str, bool]:
	if (not bib_to_check) and (not entryId_to_check): # So we don't need to check anything
		return True, '', True
	if not isinstance(response, dict):
		return False, f'response is not a dict: {response}', False
	if bib_to_check and response.get('bib') != bib_to_check:
		# If there's no bib, it's usually a transient error. If bib is '0', it's a permanent bug at Athlinks.
		to_retry = response.get('bib') is None
		return False, f'bib "{response.get("bib")}" but we expected {bib_to_check}', to_retry
	if entryId_to_check and response.get('entryId') != entryId_to_check:
		return False, f'entryId "{response.get("entryId")}" but we expected {entryId_to_check}', True
	return True, '', True

# Returns json and the URL called.
def TryGetJson(req: requests.Response, bib_to_check: str='', entryId_to_check: int=0) -> tuple[Any, str]:
	N_REPEATS = 5
	res = {}
	bib_err = ''
	is_error_retryable = False # If is_internal_error(res), then we want to retry automatically.
	for i in range(N_REPEATS):
		res = req.json()
		if i > N_REPEATS / 2:
			print(f'{datetime.datetime.now()} {req.url}: making attempt No {i+1}')
		if is_internal_error(res):
			is_error_retryable = True
		else:
			ids_are_ok, bib_err, is_error_retryable = ids_are_correct(res, bib_to_check, entryId_to_check)
			if ids_are_ok:
				return res, req.url
			if (i == N_REPEATS - 1):
				message = res.get('message', '')
				if message.startswith('no IRP results found') or message.startswith('IRP: '):
					raise ResultDetailsAbsentError()
				if bib_to_check and (res.get('bib') == ''):
					# If this is the last attempt and empty BIB is returned, it is probably a bug on Athlinks side,
					# like https://results.athlinks.com/individual?eventId=53849&eventCourseId=81143&bib=653 .
					raise ResultDetailsAbsentError()
				if entryId_to_check and (res.get('entryId') == 0):
					raise ResultDetailsAbsentError()
		time.sleep(i*i+1)
	err_text = f'{req.url} returned bad json {N_REPEATS} times in a row: {bib_err if bib_err else res}'
	if is_error_retryable:
		raise InternalAthlinksError(err_text)
	raise IncorrectBibError(err_text)

# Returns json and the URL called.
def FetchResult(platform_event_id: int, platform_race_id: int, bib: str, entryId: int) -> tuple[Any, str]:
	url = 'https://results.athlinks.com/individual'
	params = {
		'eventId': platform_event_id,
		'eventCourseId': platform_race_id,
	}
	kwargs = {}
	if bib:
		params['bib'] = bib
		kwargs['bib_to_check'] = bib
	elif entryId:
		params['id'] = entryId
		kwargs['entryId_to_check'] = entryId
	else:
		raise ResultDetailsAbsentError()
		# raise util.NonRetryableError(f'Event {platform_event_id}, course {platform_race_id}: both bib and entryId are empty')
	return TryGetJson(results_util.session.get(url, params=params), **kwargs)

# Among splits, there is also the final result: the one with intervalFull=true.
def FullInterval(intervals: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
	for interval in intervals:
		if interval['intervalFull'] is True:
			return interval
	return {}

@dataclass
class AthlinksScraper(util.Scraper):
	PLATFORM_ID = 'athlinks'
	PAGE_SIZE = 100

	def __post_init__(self):
		self.RACES_WITH_REPEATING_SPLIT_DISTANCES = frozenset([
			2374814, # https://www.athlinks.com/event/1403/results/Event/1052040/Course/2374814/Results - two marathon splits
			2499998, # https://www.athlinks.com/event/1403/results/Event/1072999/Course/2499998/Results - same
		])

		# Tuples of (eventCourseId, bib)
		self.KNOWN_BAD_BIBS = frozenset([
			(1054100, '22598'), # https://www.athlinks.com/event/3281/results/Event/668089/Results
			(1157265, '28789'), # https://www.athlinks.com/event/3294/results/Event/383053/Results
			(1173442, '2993'), # https://www.athlinks.com/event/1263/results/Event/650689/Results
			(1218430, '17699'),   # https://www.athlinks.com/event/3234/results/Event/725806/Results
			(12630, '8546'),   # https://www.athlinks.com/event/1403/results/Event/8709/Results
			(1309646, '1277'), # https://www.athlinks.com/event/1241/results/Event/766666/Results
			(1464933, '7046'), # https://www.athlinks.com/event/115192/results/Event/826783/Results
			(1478205, '699'), # https://www.athlinks.com/event/3213/results/Event/830240/Results
			(169146, '1928'),   # https://www.athlinks.com/event/3234/results/Event/116527/Results
			(1789184, '2247'), # https://www.athlinks.com/event/1061/results/Event/896579/Results
			(198028, '7631'),  # https://www.athlinks.com/event/1403/results/Event/135835/Results
			(208146, '577'), # https://www.athlinks.com/event/1314/results/Event/146950/Results
			(2081804, '27807'), # https://www.athlinks.com/event/115192/results/Event/975293/Results
			(210785, '2103'), # https://www.athlinks.com/event/3294/results/Event/209194/Results
			(219271, '100852'), # https://www.athlinks.com/event/1162/results/Event/126803/Results
			(219273, '700852'), # https://www.athlinks.com/event/1162/results/Event/126803/Results
			(220776, '200852'), # https://www.athlinks.com/event/1162/results/Event/126803/Results
			(223418, '6400'),   # https://www.athlinks.com/event/115192/results/Event/573192/Results
			(2308435, '179'), # https://results.athlinks.com/individual?eventId=1036378&eventCourseId=2308435&bib=179
			(2308435, '379'), # https://results.athlinks.com/individual?eventId=1036378&eventCourseId=2308435&bib=379
			(2320052, '15983'), # https://www.athlinks.com/event/3294/results/Event/1039374/Course/2320052/Results
			(2320052, '24402'), # https://www.athlinks.com/event/3294/results/Event/1039374/Course/2320052/Results
			(2320052, '4626'), # https://www.athlinks.com/event/3294/results/Event/1039374/Course/2320052/Results
			(2441959, '38426'), # https://www.athlinks.com/event/1403/results/Event/1072999/Course/2441959/Bib/38426 - just no name
			(2465693, '4091'), # https://www.athlinks.com/event/366682/results/Event/1078629/Results
			(272789, '1944'), # https://www.athlinks.com/event/1314/results/Event/216770/Course/272789/Bib/1944
			(279252, '700538'), # https://www.athlinks.com/event/1162/results/Event/175165/Results
			(348975, '4137'), # https://www.athlinks.com/event/3294/results/Event/209194/Results
			(349135, '16984'), # https://www.athlinks.com/event/3294/results/Event/209194/Results
			(349135, '23947'), # https://www.athlinks.com/event/3294/results/Event/209194/Results
			(421906, '20233'), # https://www.athlinks.com/event/1403/results/Event/235302/Results
			(434619, '31535'), # https://www.athlinks.com/event/1403/results/Event/303695/Results
			(459875, '50990'), # https://www.athlinks.com/event/1403/results/Event/177735/Results
			(591233, '5354'),   # https://www.athlinks.com/event/19924/results/Event/393954/Course/591233/Results
			(638412, '2791'), # https://www.athlinks.com/event/1338/results/Event/424412/Results
			(661399, '776'),   # https://www.athlinks.com/event/19924/results/Event/475634/Results
			(665189, '8515'),   # https://www.athlinks.com/event/3234/results/Event/508436/Results
			(66545, '0'), # https://www.athlinks.com/event/1263/results/Event/44695/Course/66545/Results
			(680043, '8'), # Peachtree Road Race 2000, Aaron Gordion, https://www.athlinks.com/event/115192/results/Event/125334/Course/680043/Results
			(688604, '7091'), # Yatis Dodia
			(688604, '79029'), # Peachtree Road Race 2015, Mary Hairston, https://www.athlinks.com/event/115192/results/Event/461369/Course/688604/Results
			(694175, '31260'), # https://www.athlinks.com/event/1403/results/Event/467138/Results
			(729288, '1709'), # https://www.athlinks.com/event/1263/results/Event/490483/Results
			(75071, '18933'), # https://www.athlinks.com/event/3281/results/Event/49430/Results
			(755963, '2547'),   # https://www.athlinks.com/event/3234/results/Event/725806/Results
			(791443, '16038'), # https://www.athlinks.com/event/1162/results/Event/530429/Course/791443/Bib/16038
			(855122, '45075'), # https://www.athlinks.com/event/1403/results/Event/571379/Results
			(912141, '10244'), # https://www.athlinks.com/event/19924/results/Event/475634/Results
			(930991, '56299'), # https://www.athlinks.com/event/115192/results/Event/573192/Results
		])

		# Tuples of (eventCourseId, entryID)
		self.KNOWN_BAD_PLATFORM_IDS = frozenset([
			'79512419', # https://www.athlinks.com/event/1403/results/Event/136980/Results
			'223539928', # https://www.athlinks.com/event/115192/results/Event/71332/Course/105241/Results - last one
			'341044032', # https://www.athlinks.com/event/1015/results/Event/742656/Course/1238456/Results - place 577: just empty name
			'40101584', # https://www.athlinks.com/event/1364/results/Event/66569/Results
		])

		# When there are too many errors
		self.RACES_WITH_BAD_BIBS = frozenset([
			199839, # Peachtree Road Race 2011, https://www.athlinks.com/event/115192/results/Event/145638/Results
			431823, # Peachtree Road Race 2013, https://www.athlinks.com/event/115192/results/Event/270063/Results
			348567, # Miami Marathon 2014, https://www.athlinks.com/event/3294/results/Event/247742/Results
			349422, # Miami Marathon 2013, https://www.athlinks.com/event/3294/results/Event/209194/Course/349422/Bib/1508
			210786, # Miami Marathon 2012, https://www.athlinks.com/event/3294/results/Event/153461/Results
			2285261, # Dutchess County Classic 2022, https://www.athlinks.com/event/5212/results/Event/1028725/Results
			2285262,
			2285263,
			2413221, # Liz Hurley Ribbon Run 2023, https://www.athlinks.com/event/1061/results/Event/1064442/Results
			792400, # https://www.athlinks.com/event/1723/results/Event/533148/Course/792400/Entry/252871735
			2010027, # https://www.athlinks.com/event/2164/results/Event/958205/Course/2010027/Results - Cowan has entryId 0
			1212968, # https://www.athlinks.com/event/4732/results/Event/732728/Results - Eva Cristiani has no bib
			916941, # https://www.athlinks.com/event/16102/results/Event/605079/Results - Landon Wegleitner has entryId 0
			971750, # https://www.athlinks.com/event/16739/results/Event/631891/Results
		])

	def EventMetadataURL(self) -> str:
		return f'https://results.athlinks.com/metadata/event/{self.platform_event_id}'

	def BriefResultsURL(self) -> str:
		return f'https://results.athlinks.com/event/{self.platform_event_id}'

	# Returns:
	# * events added to the queue
	# * events already present in the queue
	# * error, if any
	@classmethod
	def AddSeriesEventsToQueue(cls, platform_series_id: str, series_id: Optional[int]=None, limit: Optional[int]=None, debug: int=0) -> tuple[int, int, str]:
		series = None
		series_field_list = []
		if series_id:
			series = models.Series.objects.get(pk=series_id)
			series_platform = series.series_platform_set.filter(platform_id=cls.PLATFORM_ID).first()
			if series_platform:
				if series_platform.value != platform_series_id:
					return 0, 0, f'Series {series} (id {series.id}) already has ID at platform "{PLATFORM_ID}" {series_platform.value} != {platform_series_id}'
			else:
				models.Series_platform.objects.create(platform_id=cls.PLATFORM_ID, series=series, value=platform_series_id)

		res, url = util.TryGetJson(requests.get(SeriesMetadataURL(platform_series_id), headers=results_util.HEADERS))
		if not res['success']:
			return 0, 0, f'Could not load {url}: {res["errorMessage"]}'
		result = res['result']
		
		current_race = result.get('current_race')
		if series and current_race:
			if (not series.url_site) and current_race.get('siteUri'):
				series.url_site = current_race['siteUri']
				series_field_list.append('url_site')
			if (not series.url_facebook) and current_race.get('facebookUrl'):
				series.url_facebook = current_race['facebookUrl']
				series_field_list.append('url_facebook')

		if series_field_list:
			series.save()
			models.log_obj_create(models.USER_ROBOT_CONNECTOR, series, models.ACTION_UPDATE, field_list=series_field_list, verified_by=models.USER_ROBOT_CONNECTOR,
				comment='From AddSeriesEventsToQueue')

		n_added = n_already_present = 0
		for event in result['eventRaces']:
			url = links.AthlinksEventURL(platform_series_id, event['raceID'])
			if models.Scraped_event.objects.filter(url_results=url).exists():
				n_already_present += 1
				if debug:
					print(f'{url} is already in the queue')
				continue
			models.Scraped_event.objects.create(
				url_site=url,
				url_results=url,
				platform_id=cls.PLATFORM_ID,
				platform_series_id=platform_series_id,
				platform_event_id=event['raceID'],
				start_date=datetime.datetime.fromisoformat(event['raceDate']).date(),
			)
			if debug:
				print(f'{url} was added')
			n_added += 1
			if limit and n_added == limit:
				break
		return n_added, n_already_present, ''

	def _ParseUrlIfNeeded(self):
		if self.platform_series_id and self.platform_event_id:
			return
		matches = re.findall(r"/event/(\d+)/results/Event/(\d+)", self.url)
		if len(matches) != 1:
			raise IncorrectUrl(self.url)
		self.platform_series_id, self.platform_event_id = matches[0]
		models.Scraped_event.objects.filter(url_site=self.url).update(platform_series_id=self.platform_series_id, platform_event_id=self.platform_event_id)

	def InitStandardFormDict(self):
		if self.platform_event_id in EVENTS_WITH_METADATA_BUGS:
			self.reason_to_ignore = f'Metadata at {self.EventMetadataURL()} has errors'
			return
		if not self.platform_event_id:
			raise util.NonRetryableError('FetchCoursesAndBibs needs to know platform_event_id to read metadata')
		event_metadata = util.LoadAndStore(self.DownloadedFilesDir(), self.EventMetadataURL())
		if event_metadata.get('message', '').lower() == 'metadata not found!':
			self.reason_to_ignore = f'No metadata for event at {self.EventMetadataURL()}'
			return

		self.standard_form_dict = {
			'name': event_metadata['eventName'],
			'start_date': DateFromDict(event_metadata['eventStartDateTime']).isoformat(),
			'finish_date': DateFromDict(event_metadata['eventEndDateTime']).isoformat(),
			'id_on_platform': self.platform_event_id,
		}
		if self.platform_event_id in CORRECT_START_DATES:
			self.standard_form_dict['start_date'] = CORRECT_START_DATES[self.platform_event_id]
		self.standard_form_dict['races'] = []
		for record in event_metadata['eventCourseMetadata']:
			if ToIgnoreRace(record):
				continue
			length = util.FixLength(parse_strings.parse_meters(length_raw=record['distance'], name=record['eventCourseName'].strip(), platform_id=self.PLATFORM_ID))
			if (not length) and len(intervals := record.get('metadata', {}).get('intervals', [])) == 1:
				length = int(round(intervals[0]['distance']))
			if not length:
				if record.get('raceType') == 'untimed': # E.g. https://www.athlinks.com/event/1241/results/Event/1084825/Results
					continue
				raise util.NonRetryableError(f'Race {record["eventCourseName"]} has distance {record["distance"]} that we do not recognize')
			self.standard_form_dict['races'].append({
				'id_on_platform': record['eventCourseId'],
				'precise_name': record['eventCourseName'].strip(),
				'distance': {
					'distance_type': models.TYPE_METERS,
					'length': length,
				},
				'is_virtual': record['isVirtual'],
				'is_for_handicapped': IsForHandicapped(record['eventCourseName'].strip()),
				'results_brief_loaded': False,
				'results_detailed_loaded': False,
			})
		self.standard_form_dict['races'] = sorted(self.standard_form_dict['races'], key=lambda x: (-x['distance']['length'], x['precise_name']))

	def FetchCoursesAndBibs(self):
		for race_dict in self.standard_form_dict['races']:
			if race_dict['is_virtual']:
				continue
			if race_dict['results_brief_loaded']:
				continue
			params = OrderedDict([
				('from', 0),
				('limit', self.PAGE_SIZE),
				('eventCourseId', race_dict['id_on_platform']),
			])
			first_page = util.LoadAndStore(self.DownloadedFilesDir(), self.BriefResultsURL(), params=params, allow_empty_result=True)
			if first_page is None: # E.g. "Sabastian's 1K Mad Dash" at https://www.athlinks.com/event/1403/results/Event/1072999/Course/2499908/Results
				race_dict['has_no_results'] = True
				continue
			if not (type(first_page) is list):
				raise util.JsonParsingError(f'{self.BriefResultsURL()} with params {params} returns not a list: {first_page}')
			if (type(first_page) is list) and (len(first_page) == 0):
				race_dict['results'] = []
				continue

			total_athletes = first_page[0]['totalAthletes']
			results = first_page[0]['interval']['intervalResults']
			for start in range(self.PAGE_SIZE, total_athletes, self.PAGE_SIZE):
				params['from'] = start
				page = util.LoadAndStore(self.DownloadedFilesDir(), self.BriefResultsURL(), params=params)
				if not (type(page) is list):
					raise util.JsonParsingError(f'{self.BriefResultsURL()} with params {params} returns not a list: {page}')
				results += page[0]['interval']['intervalResults']

			race_dict['results'] = []
			for result_json in results:
				if (not result_json['bib']) and (not result_json['entryId']):
					if race_dict['id_on_platform'] not in self.RACES_WITH_BAD_BIBS:
						raise util.JsonParsingError(f'{self.BriefResultsURL()} with params {params} returned result {result_json}: all is empty')
				if result_json.get('entryStatus') in BAD_STATUSES:
					continue
				if race_dict['id_on_platform'] in RACES_WITH_TEAM_RESULTS and result_json['gender'] == 'R':
					continue
				if race_dict['id_on_platform'] == 1238456 and result_json['time']['timeInMillis'] > 200000000000:
					# Crazy bug: https://www.athlinks.com/event/1015/results/Event/742656/Course/1238456/Entry/341044557
					continue
				race_dict['results'].append({
					'bib_raw': result_json['bib'],
					'id_on_platform': result_json['entryId'],
					'lname_raw': result_json.get('lastName', ''),
					'fname_raw': result_json.get('firstName', ''),
					'gender_raw': result_json.get('gender', ''),
					'age_raw': result_json.get('age'),
					'status_raw': result_json.get('entryStatus', ''),
					'runner_id_on_platform': result_json.get('racerId'),
					'city_raw': result_json.get('locality', ''),
					'region_raw': result_json.get('region', ''),
					'country_raw': result_json.get('country', ''),
				})
			race_dict['results_brief_loaded'] = True

	def DumpXlsx(self):
		 athlinks_xlsx.write(self.StandardFormPath().removesuffix('.json') + '.xlsx', self.courses)

	# Adds more fields to result_dict.
	def _AddDetailedFields(self, result_dict: dict[str, any], result_json: dict[str, any], race_dict: dict[str, any]):
		bib = result_dict["bib_raw"]
		result_descr = f'Race {race_dict["id_on_platform"]}, BIB "{bib}", entryId {result_dict["id_on_platform"]}'
		if 'intervals' not in result_json:
			if race_dict['id_on_platform'] == 680043: # https://www.athlinks.com/event/115192/results/Event/125334/Course/680043/Results - bug
				result_dict['results_detailed_loaded'] = True
				return
			raise JsonParsingError(f'{result_descr}: no intervals in {result_json}')
		interval = FullInterval(result_json['intervals'])
		if 'chipTime' not in interval:
			result_dict['results_detailed_loaded'] = True
			return
		time_dict = interval['chipTime']
		result_dict.update({
			'result_raw': time_dict.get('timeInMillis', 0) // 10,
		})
		if time_dict.get('timeInMillis') == -1:
			result_dict['result_raw'] = 0
			result_dict['status_raw'] = 'DNF'

		if 'gunTime' in interval:
			result_dict['gun_time_raw'] = interval['gunTime']['timeInMillis'] // 10

		bracket_overall_present = bracket_gender_present = bracket_age_present = False
		for bracket in self.filtered_brackets(interval['brackets']):
			if bracket['bracketType'].upper() in ('OPEN', 'OVERALL'):
				if bracket_overall_present:
					# if race_dict['id_on_platform'] in RACES_WITH_BAD_OVERALL_BRACKETS:
						continue
					# raise JsonParsingError(f'{result_descr}: 2 overall brackets')
				bracket_overall_present = True
				result_dict['place_raw'] = bracket['rank']
			elif bracket['bracketType'].upper() in ('GENDER', 'SEX'):
				if bracket_gender_present:
					# if race_dict['id_on_platform'] in RACES_WITH_BAD_GENDER_BRACKETS:
						continue
					# raise JsonParsingError(f'{result_descr}: 2 gender brackets')
				bracket_gender_present = True
				result_dict['place_gender_raw'] = bracket['rank']
			elif (bracket['bracketType'].upper() == 'AGE') or (
						# Sometimes there's an age group bracket called 'Other'
						bracket['bracketType'].upper() == 'OTHER'
						and len(interval['brackets']) == 3
						and bracket_overall_present
						and bracket_gender_present
						and not bracket_age_present
					):
				if bracket_age_present:
					# if race_dict['id_on_platform'] in RACES_WITH_BAD_AGE_BRACKETS:
						continue
					# raise JsonParsingError(f'{result_descr}: 2 age brackets')
				bracket_age_present = True
				result_dict['place_category_raw'] = bracket['rank']
			elif bracket['bracketType'].upper() == 'OTHER':
				continue
			else:
				raise JsonParsingError(f'{result_descr}: bracket of unknown type: {bracket}')

		lengths_already_present = set()
		for interval in result_json['intervals']:
			if interval['intervalFull'] == True:
				continue
			if ToIgnoreSplit(platform_series_id=self.platform_series_id, interval=interval):
				continue
			split_length = parse_strings.fix_weird_lengths(interval['distance']['distanceInMeters'])
			if split_length <= 0:
				raise JsonParsingError(f'{result_descr}: split {interval["distance"]} is too short')
			if split_length >= race_dict['distance']['length']:
				raise JsonParsingError(f'{result_descr}: split {split_length} is longer than race distance {race_dict["distance"]["length"]}.'
					+ f'Series ID {self.platform_series_id}, interval name "{interval["intervalName"]}"')
			if split_length in lengths_already_present:
				continue
			
			lengths_already_present.add(split_length)
			if 'splits' not in result_dict:
				result_dict['splits'] = []
			result_dict['splits'].append({
				'distance': {
					'distance_type': models.TYPE_METERS,
					'length': split_length,
				},
				'value': interval['chipTime'].get('timeInMillis', 0) // 10,
			})
		result_dict['results_detailed_loaded'] = True

	def FetchResults(self):
		for race_num, race_dict in enumerate(self.standard_form_dict['races']):
			if race_dict.get('has_no_results'):
				continue
			if race_dict.get('is_virtual'):
				continue
			if race_dict['results_detailed_loaded']:
				print(f'Course {race_dict["id_on_platform"]} is already loaded')
				continue
			n_loaded_total = n_loaded_now = 0
			start = datetime.datetime.now()
			already_loaded = 0
			for result_num, result_dict in enumerate(race_dict['results']):
				if result_dict.get('results_detailed_loaded'):
					n_loaded_total += 1
					continue
				try:
					result_detailed_json, url = FetchResult(
						platform_event_id=self.platform_event_id,
						platform_race_id=race_dict['id_on_platform'],
						bib=result_dict['bib_raw'],
						entryId=result_dict['id_on_platform'],
					)
				except ResultDetailsAbsentError:
					continue
				except IncorrectBibError as e:
					self.DumpStandardForm()
					print(f'Loaded {len(race_dict["results"])} results')
					raise IncorrectBibError(f'{e}. Loaded {len(race_dict["results"])} results for course {race_dict["id_on_platform"]}') from e
				except InternalAthlinksError as e:
					if (race_dict["id_on_platform"], result_dict['bib_raw']) in self.KNOWN_BAD_BIBS or race_dict["id_on_platform"] in self.RACES_WITH_BAD_BIBS:
						continue
					if result_dict['id_on_platform'] in self.KNOWN_BAD_PLATFORM_IDS:
						continue
					self.DumpStandardForm()
					print(f'Loaded {len(race_dict['results'])} results')
					raise InternalAthlinksError(f'{e}. Loaded {len(race_dict['results'])} results for course {race_dict["id_on_platform"]}') from e

				if (len(result_detailed_json) == 1) and ('message' in result_detailed_json):
					self.DumpStandardForm()
					print(f'Loaded {len(race_dict['results'])} results')
					raise util.NonRetryableError(f'{url} returned error: {result_json["message"]}')
				self._AddDetailedFields(result_dict, result_detailed_json, race_dict)

				n_loaded_total += 1
				n_loaded_now += 1

				if (n_loaded_total % 1000) == 0:
					self.attempt.UpdateStatus(f'FetchResults: Loading {race_num+1} race out of {len(self.standard_form_dict["races"])}. '
						+ f'Loaded {result_num+1} detailed results out of {len(race_dict["results"])}')
					self.DumpStandardForm()
					if self.ToStopNow():
						raise util.TimeoutError(f'Time out. Loaded {n_loaded_total} out of {len(race_dict["results"])} detailed results')
			print(f'Course {race_dict["id_on_platform"]}: loaded {len(race_dict["results"])} results in {datetime.datetime.now() - start}')
			race_dict['results_detailed_loaded'] = True
			self.DumpStandardForm()
		# self.DumpXlsx()

	def ProcessNewRunners(self):
		pass

	def filtered_brackets(self, brackets: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
		res = []
		for bracket in brackets:
			if bracket['bracketType'] == 'Elite':
				continue
			if self.platform_series_id == '19924' and bracket['bracketName'] == 'M80-9':
				continue # https://www.athlinks.com/event/19924/results/Event/984803/Course/2117146/Results; should be M80-99; email written to jody@jbsports.com
			if self.platform_series_id == '115192' and bracket['bracketName'] in ('Male Masters', 'Female Masters', 'Non-Binary Masters'):
				continue # https://www.athlinks.com/event/115192/results/Event/1045874/Course/2348093/Results; both M50-54 and this one
			if self.platform_series_id == '3234' and bracket['bracketName'] == 'M ELITE':
				continue # https://www.athlinks.com/event/3234/results/Event/378310/Course/429092/Bib/2913; group with just one person
			res.append(bracket)
		return res

	def FindOrCreateSeries(self):
		series_platform = models.Series_platform.objects.filter(platform_id=self.PLATFORM_ID, value=self.platform_series_id).first()
		if series_platform:
			self.series = series_platform.series
			return

		series_metadata, url = util.TryGetJson(requests.get(SeriesMetadataURL(self.platform_series_id), headers=results_util.HEADERS))
		if not series_metadata['success']:
			return False, f'Could not load {url}: {series_metadata["errorMessage"]}'
		result = series_metadata['result']
		self.series = models.Series.objects.filter(Q(city__name=result['city']) | Q(city_raw=result['city']), name=result['name']).first()
		if self.series:
			series_platform = self.series.platforms.filter(platform_id=self.PLATFORM_ID).first()
			if series_platform:
				raise util.NonRetryableError(f'There is a similar series with a different platform ID: {series_platform.value} vs {self.platform_series_id}')
		else:
			url_facebook = result['currentRace'].get('facebookUrl') or ''
			if '/oauth?' in url_facebook: # https://www.athlinks.com/event/16690/results/Event/678475/Results - weird URL
				url_facebook = ''
			url_facebook = url_facebook.split('?eid=')[0]
			self.series = models.Series.objects.create(
				name=result['name'],
				city=models.City.objects.filter(name=result['city']).order_by('-population').first(),
				city_raw=result['city'],
				region_raw=result['stateProvAbbrev'] or '',
				country_raw=result['countryName'] or '',
				url_site=result['webSiteURL'] or result['currentRace'].get('siteUri', ''),
				url_facebook=url_facebook,
				url_instagram=result['currentRace'].get('instagramHandle') or '',
				surface_type=results_util.SURFACE_SOFT if ('trail' in result['name'].lower()) else results_util.SURFACE_ROAD,
			)
			models.log_obj_create(models.USER_ROBOT_CONNECTOR, self.series, models.ACTION_CREATE, verified_by=models.USER_ROBOT_CONNECTOR,
				comment='From athlinks.FindOrCreateSeries')
		models.Series_platform.objects.create(series=self.series, platform_id=self.PLATFORM_ID, value=self.platform_series_id)

	def SaveEventDetailsInStandardForm(self):
		self._ParseUrlIfNeeded()
		if os.path.isfile(self.StandardFormPath()):
			print(f'Reading all event data from {self.StandardFormPath()}')
			with io.open(self.StandardFormPath(), encoding="utf8") as json_in:
				self.standard_form_dict = json.load(json_in)
		else:
			self.InitStandardFormDict()
			if self.reason_to_ignore:
				return

		self.FetchCoursesAndBibs()
		self.DumpStandardForm()
		if not self.standard_form_dict['races']:
			raise util.NonRetryableError(f'{self.url}: no distances!')
		self.FetchResults()
		self.DumpStandardForm()

# Returns error message if any; empty string on success.
def FillRunnerData(runner: models.Runner, platform_id: int) -> str:
	pass
