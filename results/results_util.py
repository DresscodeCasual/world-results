from django.forms.fields import URLField as FormURLField
from django.utils.crypto import get_random_string
from django.contrib.auth.models import User
from django.http import FileResponse
from django.core import validators
from django.conf import settings
from django.urls import reverse
from django.core import mail
from django.db import models

from collections import OrderedDict
import datetime
import decimal
from http.client import HTTPMessage
import io
import os
import re
import requests
from requests import adapters
import time
from typing import Optional, Tuple, Union
import urllib.request, urllib.error, urllib.parse
from urllib3.util import retry

MILE_IN_METERS = 1609.344
SITE_URL = f'https://{settings.MAIN_HOST}'

plural_endings_array = [
	(), # 0
	('', 'а', 'ов'), # 1 # For e.g. 'результат'
	('а', 'ы', ''),  # 2 # For e.g. 'трасса', 'команда','женщина'
	('ь', 'и', 'ей'), # 3 # For e.g. 'новость'
	('я', 'и', 'й'), # 4 # For e.g. 'дистанция'
	('й', 'х', 'х'), # 5 # For e.g. 'завершивши_ся', 'предстоящий', 'похожий'
	('й', 'х', 'х'), # 6 # For e.g. 'обработанный'
	('е', 'я', 'й'), # 7 # For e.g. 'предупреждение'
	('ка', 'ки', 'ок'), # 8 # For e.g. 'ошибка'
	('', 'а', ''),   # 9 # For e.g. 'человек'
	('', '', ''), # 10 # See below
	('год', 'года', 'лет'), # 11 # For e.g. 'год/лет'
	('', 'и', 'и'), # 12 # For e.g. 'ваш'
	('а', '', ''),   # 13 # For e.g. 'мужчина'
	('и', 'ях', 'ях'), # 14 # For e.g. 'о дистанциях'
	('е', 'ах', 'ах'), # 15 # For e.g. 'о забегах'
	('а', 'ов', 'ов'), # 16 # For e.g. 'с трёх забегов'
	('', 'ы', 'ы'), # 17 # For e.g. 'добавлен'
	('и', '', ''), # 18 # For e.g. 'не меньше ... тысяч'
	('а', 'и', 'и'), # 19 # For e.g. 'тысяча'
	('у', 'и', ''), # 20 # For e.g. 'зафиксировали 5 тысяч'
	('', 'о', 'о'), # 21 # For e.g. 'проведено'
	('ю', 'и', 'и'), # 22 # For e.g. 'оплатить регистраци_'
	('и', 'й', 'й'), # 23 # For e.g. 'оплата пяти регистраци_'
	('а', 'о', 'о'), # 24 # For e.g. 'оплачен{} три регистрации'
	('о', 'а', ''), # 25 # For e.g. 'место'
	('у', 'ы', ''), # 26 # For e.g. 'цену'
	('его', 'их', 'их'), # 27 # For e.g. 'зарегистрировавш_ся'
	('года', 'лет', 'лет'), # 28 # 'от/до ... года/лет'
	('у', 'ам', 'ам'), # 29 # 'к трём забегам'
	('ьмо', 'ьма', 'ем'), # 30 письмо/писем
	('ен', 'но', 'но'), # 31 нужен/но 25 забегов
]

def ending(value, word_type):
	if value is None:
		value = 0
	value %= 100
	if word_type == 10:
		return 'е' if (value == 1) else 'ю'
	endings = plural_endings_array[word_type]
	if 11 <= value <= 19:
		return endings[2]
	value %= 10
	if value == 0:
		return endings[2]
	if value == 1:
		return endings[0]
	if value >= 5:
		return endings[2]
	return endings[1]

def int_safe(s):
	try:
		res = int(s)
	except:
		res = 0
	return res

def float_safe(s):
	try:
		res = float(s)
	except:
		res = 0.
	return res

def get_first_digits_as_number(s: str) -> int:
	s += ' '
	for i in range(len(s)):
		if not s[i].isdigit():
			return int_safe(s[:i])
	return 0

LOG_DIR = settings.BASE_DIR / 'logs'
LOG_FILE_ACTIONS = LOG_DIR / 'django_actions.log'
def write_log(s):
	f = open(LOG_FILE_ACTIONS, "a")
	try:
		f.write(datetime.datetime.today().isoformat(' ') + " " + s + "\n")
	except:
		f.write(datetime.datetime.today().isoformat(' ') + " " + s.encode('utf-8') + "\n")
	f.close()
	return s

HEADERS = {
	# 'User-Agent' : 'YaBrowser/16.2.0.3539 Safari/537.36',
	# 'Referer' : 'https://www.google.com/',
	'User-Agent' : 'Mozilla/5.0 (Windows NT 6.1; Win64; x64)',
	'Referer' : 'https://www.yandex.ru/',
	'ACCEPT_LANGUAGE' : 'en,ru;q=0.8',
	'ACCEPT_ENCODING' : 'utf-8',
	'ACCEPT' : 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8'
}

session = requests.Session()
my_retry = retry.Retry(connect=5, backoff_factor=0.5)
adapter = adapters.HTTPAdapter(max_retries=my_retry)
session.mount('http://', adapter)
session.mount('https://', adapter)
session.headers = HEADERS

# When parkrun bans us, we scrape pages from another machine.
def url_file_name(url):
	# return '/home/chernov/dumps/parkrun_pages/' + url.replace('/', '_').replace('.', '_').replace(':', '').replace('?', '').replace('=', '_')
	return settings.BASE_DIR / 'dumps/parkrun_pages' / url.replace('/', '_').replace('.', '_').replace(':', '').replace('?', '').replace('=', '_')

def get_encoding(headers, default='utf-8'):
	if headers is None:
		return default
	charset = headers.get_content_charset()
	return charset if charset else default

MAX_FILE_SIZE = 20 * 1024 * 1024
# Read URL so that the site thinks we're just browser. Returns <Success?>, <data>, <file size>, <headers>, <error text, if any>
def read_url(url, from_file=False, to_decode=True) -> Tuple[bool, Union[str, bytes], int, Optional[HTTPMessage], str]:
	if from_file: # Once used for parkrun files when it banned us
		with io.open(url_file_name(url), 'r', encoding="utf8") as file: 
			return True, file.read(), 0, None, ''
	req_headers = {
		'User-Agent' : 'YaBrowser/16.2.0.3539 Safari/537.36',
		'Referer' : 'https://www.google.com/',
		# 'User-Agent' : 'Mozilla/5.0 (Windows NT 6.1; Win64; x64)',
		# 'Referer' : 'https://www.yandex.ru/',
		'ACCEPT_LANGUAGE' : 'en,ru;q=0.8',
		'ACCEPT_ENCODING' : 'utf-8',
		'ACCEPT' : 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8'
	}
	# req = requests.get(url)
	response = None
	downloaded = False
	for try_number in range(2):
		try:
			response = session.get(url)
			downloaded = True
			break
		except urllib.error.HTTPError as e:
			write_log("HTTP Error with URL " + url + ". Try number " + str(try_number))
			write_log("Error code: " + str(e.code))
			time.sleep(1)
		except urllib.error.URLError as e:
			write_log("URL Error with URL " + url + ". Try number " + str(try_number))
			write_log("Reason: " + str(e.reason))
			time.sleep(1)
		except:
			raise
	if not downloaded:
		return False, '', 0, None, f"Could not reach the url '{url}'"
	# try:
	# file_size = int_safe(response.info().getheaders("Content-Length")[0])
	# except:
	# 	file_size = 0
	if len(response.text) > MAX_FILE_SIZE:
		return False, '', 0, None, f"The file '{url}' size '{file_size}' is too large"
	return True, response.text, len(response.text), None, ''

TRACKER_TYPE_STRAVA = 1
TRACKER_TYPE_GARMIN = 2
TRACKER_TYPE_SUUNTO = 3
TRACKER_TYPES = (
	(TRACKER_TYPE_STRAVA, 'Strava'),
	(TRACKER_TYPE_GARMIN, 'Garmin'),
	(TRACKER_TYPE_SUUNTO, 'Suunto'),
	)

STRAVA_ACTIVITY_PREFIX = 'strava.com/activities/'
STRAVA_ACTIVITY_APP_PREFIX = 'strava.app.link/'
GARMIN_ACTIVITY_PREFIX = 'connect.garmin.com/modern/activity/'
# Returns 2 args:
# 1. Activity number if found, None otherwise
# 2. Tracker type if determined, None otherwise
# 3. True if (activity number not found, and it looks like a link to private activity), False otherwise
def maybe_strava_activity_number(s: str) -> Tuple[Optional[int], Optional[int], bool]:
	if STRAVA_ACTIVITY_PREFIX in s:
		maybe_number = get_first_digits_as_number(s.split(STRAVA_ACTIVITY_PREFIX)[-1])
		if maybe_number:
			return maybe_number, TRACKER_TYPE_STRAVA, False
	if GARMIN_ACTIVITY_PREFIX in s:
		maybe_number = get_first_digits_as_number(s.split(GARMIN_ACTIVITY_PREFIX)[-1])
		if maybe_number:
			return maybe_number, TRACKER_TYPE_GARMIN, False
	if STRAVA_ACTIVITY_APP_PREFIX in s:
		maybe_code = s.split(STRAVA_ACTIVITY_APP_PREFIX)[-1]
		url = 'https://' + STRAVA_ACTIVITY_APP_PREFIX + maybe_code
		result, content, _, _, _ = read_url(url)
		if result:
			match = re.search(fr'{STRAVA_ACTIVITY_PREFIX}(\d{{1,15}})[/?]', content)
			if match:
				return int(match.group(1)), TRACKER_TYPE_STRAVA, False
			if 'on Strava to see this activity' in content:
				return None, None, True
	return None, None, False

def get_age_on_date(event_date, birthday):
	if birthday and event_date:
		return event_date.year - birthday.year - ((event_date.month, event_date.day) < (birthday.month, birthday.day))
	return None

SURFACE_DEFAULT = 0
SURFACE_SOFT = 2
SURFACE_MOUNTAIN = 3
SURFACE_OBSTACLE = 4
SURFACE_ROAD = 5
SURFACE_STADIUM = 6
SURFACE_INDOOR = 7
SURFACE_INDOOR_NONSTANDARD = 8
SURFACE_TYPES = (
	(SURFACE_DEFAULT, 'unknown'),
	(SURFACE_ROAD, 'road'),
	(SURFACE_STADIUM, 'track'),
	(SURFACE_INDOOR, 'indoor 200 meter track'),
	(SURFACE_INDOOR_NONSTANDARD, 'indoor track different from 200 meters'),
	(SURFACE_SOFT, 'cross country or trail'),
	(SURFACE_MOUNTAIN, 'mountain running'),
	(SURFACE_OBSTACLE, 'obstacle race'),
)
SURFACES_STADIUM_OR_INDOOR = (SURFACE_STADIUM, SURFACE_INDOOR, SURFACE_INDOOR_NONSTANDARD)

# Maybe can be deleted?
# SURFACES_UNEVEN = (SURFACE_SOFT, SURFACE_MOUNTAIN)

SURFACE_TYPES_DICT = dict(SURFACE_TYPES)
SURFACE_CODES = {
	SURFACE_DEFAULT: 'any',
	SURFACE_ROAD: 'road',
	SURFACE_STADIUM: 'stadium',
	SURFACE_INDOOR: 'indoor',
}
SURFACE_CODES_INV = {v: k for k, v in SURFACE_CODES.items()}

DIST_6DAYS_ID = 170
DIST_3DAYS_ID = 169
DIST_48HOURS_ID = 168
DIST_24HOURS_ID = 167
DIST_12HOURS_ID = 166
DIST_100MILES_ID = 165
DIST_100KM_ID = 162
DIST_50KM_ID = 50
DIST_MARATHON_ID = 109
DIST_30KM_ID = 30
DIST_HALFMARATHON_ID = 110
DIST_1HOUR_ID = 160
DIST_20KM_ID = 20
DIST_15KM_ID = 15
DIST_10KM_ID = 10
DIST_5KM_ID = 5
DIST_3KM_ID = 3
DIST_1500M_ID = 156
DIST_800M_ID = 163
DIST_400M_ID = 157
DIST_200M_ID = 164
DIST_100M_ID = 158
DIST_60M_ID = 159

DIST_RACEWALKING_5KM_ID = 161

# DIST_LONG_JUMP_ID = 2827
# DIST_TRIPLE_JUMP_ID = 2828
# DIST_HIGH_JUMP_ID = 2829
# DIST_POLE_VAULT_ID = 2835
# DIST_SHOT_PUT_ID = 2834
# DIST_DISCUS_THROW_ID = 2830
# DIST_HAMMER_THROW_ID = 2831
# DIST_JAVELIN_THROW_ID = 2832
# DIST_WEIGHT_THROW_ID = 2833

DISTANCE_ANY = -1
DISTANCE_WHOLE_EVENTS = -2

DISTANCES_FOR_CLUB_STATISTICS = (
	DIST_MARATHON_ID,
	DIST_HALFMARATHON_ID,
	DIST_10KM_ID,
	DIST_5KM_ID,
	DIST_1HOUR_ID,
)

DISTANCES_FOR_COUNTRY_OUTDOOR_RECORDS = [
	(DIST_MARATHON_ID, SURFACE_ROAD),
	(DIST_HALFMARATHON_ID, SURFACE_ROAD),
	(DIST_1HOUR_ID, SURFACE_DEFAULT),
	(DIST_10KM_ID, SURFACE_ROAD),
	(DIST_10KM_ID, SURFACE_STADIUM),
	(DIST_5KM_ID, SURFACE_STADIUM),
	(DIST_1500M_ID, SURFACE_STADIUM),
	(DIST_800M_ID, SURFACE_STADIUM),
	(DIST_400M_ID, SURFACE_STADIUM),
	(DIST_200M_ID, SURFACE_STADIUM),
	(DIST_100M_ID, SURFACE_STADIUM),
]

DISTANCES_FOR_COUNTRY_INDOOR_RECORDS = (
	DIST_3KM_ID,
	DIST_1500M_ID,
	DIST_800M_ID,
	DIST_400M_ID,
	DIST_200M_ID,
	DIST_60M_ID,
)

DISTANCES_FOR_COUNTRY_ULTRA_RECORDS = (
	DIST_6DAYS_ID,
	DIST_3DAYS_ID,
	DIST_48HOURS_ID,
	DIST_24HOURS_ID,
	DIST_12HOURS_ID,
	DIST_100MILES_ID,
	DIST_100KM_ID,
)
N_TOP_RESULTS_FOR_ULTRA_MAIN_PAGE = 5

DISTANCES_FOR_RATING = (
	DIST_100KM_ID,
	DIST_MARATHON_ID,
	DIST_HALFMARATHON_ID,
	DIST_1HOUR_ID,
	DIST_10KM_ID,
	DIST_5KM_ID,
	DIST_24HOURS_ID,
	DIST_3KM_ID,
	DIST_15KM_ID,
	DIST_20KM_ID,
	DIST_30KM_ID,
	DIST_50KM_ID,
)

RECORD_RESULT_SYMBOLS_TO_CUT = {
	DIST_MARATHON_ID: 0,
	DIST_HALFMARATHON_ID: 0,
	DIST_1HOUR_ID: 0,
	DIST_10KM_ID: 0,
	DIST_5KM_ID: 2,
	DIST_3KM_ID: 2,
	DIST_1500M_ID: 2,
	DIST_800M_ID: 3,
	DIST_400M_ID: 3,
	DIST_200M_ID: 3,
	DIST_100M_ID: 5,
	DIST_60M_ID: 5,
}

DISTANCES_TOP_FOUR = (
	DIST_MARATHON_ID,
	DIST_HALFMARATHON_ID,
	DIST_10KM_ID,
	DIST_5KM_ID,
)

DISTANCES_FOR_REPORT_LARGEST_EVENTS = (
	DIST_100KM_ID,
	DIST_MARATHON_ID,
	DIST_30KM_ID,
	DIST_HALFMARATHON_ID,
	DIST_1HOUR_ID,
	DIST_15KM_ID,
	DIST_10KM_ID,
	DIST_5KM_ID,
)

DISTANCE_CODES = {
	DIST_6DAYS_ID: '6d',
	DIST_3DAYS_ID: '3d',
	DIST_48HOURS_ID: '48h',
	DIST_24HOURS_ID: '24h',
	DIST_12HOURS_ID: '12h',
	DIST_100MILES_ID: '100miles',
	DIST_100KM_ID: '100km',
	DIST_50KM_ID: '50km',
	DIST_MARATHON_ID: 'marathon',
	DIST_30KM_ID: '30km',
	DIST_HALFMARATHON_ID: 'half',
	DIST_1HOUR_ID: '1hour',
	DIST_20KM_ID: '20km',
	DIST_15KM_ID: '15km',
	DIST_10KM_ID: '10km',
	DIST_5KM_ID: '5km',
	DIST_3KM_ID: '3km',
	DIST_1500M_ID: '1500m',
	DIST_800M_ID : '800m',
	DIST_400M_ID : '400m',
	DIST_200M_ID : '200m',
	DIST_100M_ID : '100m',
	DIST_60M_ID : '60m',
	DISTANCE_ANY: 'any',
	DISTANCE_WHOLE_EVENTS: 'sum',
}
DISTANCE_CODES_INV = {v: k for k, v in DISTANCE_CODES.items()}

GENDER_UNKNOWN = 0
GENDER_FEMALE = 1
GENDER_MALE = 2
GENDER_NONBINARY = 3
GENDER_CHOICES = (
	(GENDER_UNKNOWN, 'Не указан'),
	(GENDER_FEMALE, 'Женский'),
	(GENDER_MALE, 'Мужской'),
	(GENDER_NONBINARY, 'Иной'),
)
GENDER_CHOICES_RUS = GENDER_CHOICES[:-1]
GENDER_CODES = OrderedDict([
	(GENDER_UNKNOWN, 'unknown'),
	(GENDER_FEMALE, 'female'),
	(GENDER_MALE, 'male'),
	(GENDER_NONBINARY, 'nonbinary'),
])
GENDER_CODES_INV = {v: k for k, v in GENDER_CODES.items()}

def string2gender(s):
	if not s:
		return GENDER_UNKNOWN
	if not isinstance(s, str):
		return GENDER_UNKNOWN
	if s.upper() == 'UNKNOWN':
		return GENDER_UNKNOWN
	if s.upper() in ['NB', 'U', 'X']:
		return GENDER_NONBINARY
	letter = s[0].upper()
	if letter in ['М', 'M', 'Ч', 'Ю']:
		return GENDER_MALE
	if letter in ['Ж', 'F', 'W', 'Д', 'K', 'N']:
		return GENDER_FEMALE
	if 'ЮНИОРКИ' in s.upper():
		return GENDER_FEMALE
	return GENDER_UNKNOWN

STATUS_FINISHED = 0
STATUS_DNF = 1
STATUS_DSQ = 2
STATUS_DNS = 3
STATUS_UNKNOWN = 4
STATUS_COMPLETED = 5
RESULT_STATUSES = (
	(STATUS_FINISHED, 'Finished'),
	(STATUS_DNF, 'DNF'),
	(STATUS_DSQ, 'DSQ'),
	(STATUS_DNS, 'DNS'),
	(STATUS_COMPLETED, 'Completed the distance'), # For untimed events if we ever have them
)
def string2status(s: str, source: Optional[str]='') -> int:
	if not s:
		if source == 'athlinks':
			return STATUS_FINISHED
		return STATUS_UNKNOWN
	s = s.upper().strip()
	if s in ('Q', 'FINISHED', 'CONF'):
		return STATUS_FINISHED
	if (s in ('DNF', 'A')) or s.startswith('СОШ'):
		return STATUS_DNF
	if (s in ('DSQ', 'DQ', 'UNRANKED', 'NC')) or ('ДИСКВ' in s):
		return STATUS_DSQ
	if (s == 'DNS') or s.startswith('НЕ СТАРТ'):
		return STATUS_DNS
	return STATUS_UNKNOWN

RUSSIAN_PARKRUN_SITE = 'https://www.parkrun.ru'
VERST_SITE = 'https://5verst.ru'
S95_SITE = 'https://s95.ru'

CUR_YEAR = datetime.date.today().year

MAX_DISTANCE_FOR_ELECTRONIC_RECORDS = 800

# To distinguish between parkrun_id and verst_id
MAX_PARKRUN_ID = 99999999

def restart_django():
	touch_fname = settings.BASE_DIR / 'touch_to_reload'
	with open(touch_fname, 'a'):
		os.utime(touch_fname, None)

def fix_quotes(s):
	if s.count('"') == 2:
		return s.replace('"', '«', 1).replace('"', '»', 1)
	return s

# Convert distance in meters to either '15 км' or '2345 м'
def length2m_or_km(length, avoid_km=False):
	if avoid_km or ((length % 1000) > 0):
		return '{} m'.format(length)
	return '{} km'.format(length // 1000)

def get_mail_connection(sender_email):
	if settings.EMAIL_HOST_USER in sender_email:
		return mail.get_connection(username=settings.EMAIL_HOST_USER, password=settings.EMAIL_HOST_PASSWORD)
	else: # 'info@' in sender_email
		return mail.get_connection(username=settings.EMAIL_INFO_USER, password=settings.EMAIL_INFO_PASSWORD)

XLSX_FILES_DIR = settings.MEDIA_ROOT + 'dj_media/xlsx_reports'

def get_file_response(fname):
	response = FileResponse(open(fname, 'rb'), content_type='application/vnd.ms-excel')
	leaf_file = fname.split("/")[-1]
	response['Content-Disposition'] = f'attachment; filename="{leaf_file}"'
	return response

def anyin(s, templates):
	return any(x in s for x in templates)

VERIFICATION_CODE_LENGTH = 10
def generate_verification_code():
	chars = 'abcdefghijklmnopqrstuvwxyz0123456789'
	return get_random_string(VERIFICATION_CODE_LENGTH, chars)

MAILING_TYPE_SITE_NEWS = 0
MAILING_TYPE_NEW_RESULTS = 1
MAILING_TYPE_RELATED_EVENTS = 2
# Triples: id; text for "Вы отказались от рассылки ..."; name of User_profile field
MAILING_TYPES = (
	(MAILING_TYPE_SITE_NEWS, 'новостей сайта', 'ok_to_send_news'),
	(MAILING_TYPE_NEW_RESULTS, 'о новых привязанных Вам результатах', 'ok_to_send_results'),
	(MAILING_TYPE_RELATED_EVENTS, 'о появлении на сайте забегов, в которых Вы участвовали в последние два года', 'ok_to_send_on_related_events'),
)

def encode_slashes(value):
	return value.replace('/', '%2F')

def decode_slashes(value): # Reverts encode_slashes
	return value.replace('%2F', '/')

def reverse_runners_by_name(lname, fname):
	return reverse('results:runners', kwargs={'lname': encode_slashes(lname), 'fname': encode_slashes(fname)})

months = ['', 'January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']

def date2str(mydate, with_nbsp=True, short_format=False):
	if short_format:
		return mydate.strftime('%m/%d/%Y')
		# return mydate.strftime('%d.%m.%Y')
	return mydate.strftime('%B %d, %Y') # Aug 08, 2024
def dates2str(start_date, finish_date, with_nbsp=True):
	NBSP = '&nbsp;' if with_nbsp else ' '
	if not finish_date:
		return date2str(start_date, with_nbsp=with_nbsp)
	if start_date.year == finish_date.year:
		if start_date.month == finish_date.month:
			return f'{start_date.day}–{finish_date.day}{NBSP}{months[start_date.month]} {start_date.year}'
		else:
			return f'{start_date.day}{NBSP}{months[start_date.month]}{NBSP}– {finish_date.day}{NBSP}{months[finish_date.month]} {start_date.year}'
	else:
		return f'{date2str(start_date, with_nbsp=with_nbsp)}{NBSP}– {date2str(finish_date, with_nbsp=with_nbsp)}'

# Make a decimal with three digits after comma
def quantize(d: float) -> decimal.Decimal:
	return decimal.Decimal(d).quantize(decimal.Decimal('.001'), rounding=decimal.ROUND_HALF_UP)

# We want to show at /runners/ stats for current year starting from February 1st.
TODAY = datetime.date.today()
CUR_YEAR_FOR_RUNNER_STATS = TODAY.year if (TODAY.month >= 2) else (TODAY.year - 1)

def get_parkrun_or_verst_dict(id: int):
	if id <= MAX_PARKRUN_ID:
		return {'parkrun_id': id}
	return {'verst_id': id}

def detailed_user_desc(user: User) -> str:
	return f'{user.get_full_name()} (username {user.username}, email {user.email}, {SITE_URL}{reverse("results:user_details", kwargs={"user_id": user.id})} )'

def result_is_too_large(length, centiseconds):
	return ((centiseconds % 6000) == 0) \
		and (
			((length <= 10000) and (centiseconds >= 5*3600*100))   # 5 hours
			or ((length <= 3000) and (centiseconds >= 2*3600*100)) # 2 hours
			or ((length <= 1000) and (centiseconds >= 1*3600*100)) # 1 hour
		)
