from django.shortcuts import get_object_or_404, render, redirect, reverse
from django.db.models.query import Prefetch
from django.contrib.auth.models import User
from django.db.models import Count, Q
from django.contrib import messages

from collections import OrderedDict
import datetime
from decimal import Decimal
import math
import re
from typing import Any, List
import xlrd

from results import models, models_klb, results_util
from editor import generators, parse_protocols, parse_strings, runner_stat
from editor.views import views_common, views_result

OLD_RESULTS_DELETE_ALL = 1
OLD_RESULTS_DELETE_MEN = 2
OLD_RESULTS_DELETE_WOMEN = 3
OLD_RESULTS_LEAVE_ALL = 4

CELL_DATA_PASS = 0
CELL_DATA_PLACE = 1
CELL_DATA_BIB = 2
CELL_DATA_LNAME = 3
CELL_DATA_FNAME = 4
CELL_DATA_MIDNAME = 5
CELL_DATA_NAME = 6
CELL_DATA_BIRTHDAY = 7
CELL_DATA_AGE = 8
CELL_DATA_CITY = 9
CELL_DATA_REGION = 10
CELL_DATA_COUNTRY = 11
CELL_DATA_CLUB = 12
CELL_DATA_GENDER = 13
CELL_DATA_PLACE_GENDER = 14
CELL_DATA_CATEGORY = 15
CELL_DATA_PLACE_CATEGORY = 16
CELL_DATA_COMMENT = 17
CELL_DATA_RESULT = 18
CELL_DATA_GUN_RESULT = 19
CELL_DATA_SPLIT = 20
CELL_DATA_STATUS = 21
CELL_DATA_WIND = 22
CELL_DATA_PARKRUN_ID = 23

CELL_DATA_CHOICES = OrderedDict([
	(CELL_DATA_PASS, 'не загружаем'),
	(CELL_DATA_SPLIT, 'сплит'),
	(CELL_DATA_PLACE, 'место в абсолюте'),
	(CELL_DATA_BIB, 'стартовый номер'),
	(CELL_DATA_LNAME, 'фамилия'),
	(CELL_DATA_FNAME, 'имя'),
	(CELL_DATA_MIDNAME, 'отчество'),
	(CELL_DATA_NAME, 'имя целиком'),
	(CELL_DATA_BIRTHDAY, 'дата или год рождения'),
	(CELL_DATA_AGE, 'возраст'),
	(CELL_DATA_CITY, 'город'),
	(CELL_DATA_REGION, 'регион'),
	(CELL_DATA_COUNTRY, 'страна'),
	(CELL_DATA_CLUB, 'клуб'),
	(CELL_DATA_GENDER, 'пол'),
	(CELL_DATA_PLACE_GENDER, 'место среди пола'),
	(CELL_DATA_CATEGORY, 'группа'),
	(CELL_DATA_PLACE_CATEGORY, 'место в группе'),
	(CELL_DATA_COMMENT, 'комментарий'),
	(CELL_DATA_RESULT, 'результат'),
	(CELL_DATA_GUN_RESULT, 'грязное время'),
	(CELL_DATA_STATUS, 'статус результата'),
	(CELL_DATA_WIND, 'скорость ветра'),
	(CELL_DATA_PARKRUN_ID, 'parkrun/5вёрст ID'),
])

MAX_FIELD_LENGTHS = {
	CELL_DATA_BIB: models.MAX_BIB_LENGTH,
}

CATEGORY_PREFIX_NONE = 0
CATEGORY_PREFIX_RUS_SOME = 1
CATEGORY_PREFIX_RUS_ALL = 2
CATEGORY_PREFIX_ENG_SOME = 3
CATEGORY_PREFIX_ENG_ALL = 4
CATEGORY_PREFIXES = (
	(CATEGORY_PREFIX_NONE, 'ничего'),
	(CATEGORY_PREFIX_RUS_SOME, 'русские М и Ж, если группа начинается не с них'),
	(CATEGORY_PREFIX_RUS_ALL, 'русские М и Ж всем'),
	(CATEGORY_PREFIX_ENG_SOME, 'латинские M и F, если группа начинается не с них'),
	(CATEGORY_PREFIX_ENG_ALL, 'латинские M и F всем'),
)

MAX_N_COLS = 120

def default_data_types(request, protocol, data: List[List[Any]], header_row, distance, column_data_types, column_split_values):
	if len(data) == 0:
		return [], []
	ncols = len(data[0])
	column_data_types = [CELL_DATA_PASS] * ncols
	column_split_values = [0] * ncols
	header = data[header_row]
	for col_index in range(ncols):
		if header[col_index]['type'] == xlrd.XL_CELL_TEXT:
			col_name = header[col_index]['value'].lower()
			if col_name in ['старт', 'тип рез.', 'result_time', 'result_distance']:
				column_data_types[col_index] = CELL_DATA_PASS
			elif results_util.anyin(col_name, ['результат с учетом возраст', 'тренер', 'выполнен']):
				column_data_types[col_index] = CELL_DATA_PASS
			elif results_util.anyin(col_name, ['м/ж', 'м./ж.', 'среди пола', 'gender pl', 'rank_gender', 'gender_rank', 'genderposition', 'gender position',
					'gender pos']):
				column_data_types[col_index] = CELL_DATA_PLACE_GENDER
			elif results_util.anyin(col_name, ['место абс', 'место в абс', 'overall', 'rank_abs', 'м (абс)', 'абсолютное ме', 'absoluteposition']):
				column_data_types[col_index] = CELL_DATA_PLACE
			elif results_util.anyin(col_name, ['имя, фамилия', 'фамилия, имя', 'имя фамилия', 'имя и фам', 'фамилия и', 'фио', 'фи ', 'ф.и', 'ф. и'
					'спортсмен', 'пiб', 'full name', 'athlete', 'имя целиком']):
				column_data_types[col_index] = CELL_DATA_NAME
			elif results_util.anyin(col_name, ['фамилия', 'last name', 'last_name', 'name_last', 'lastname', 'прізвище', 'uzvārds']):
				column_data_types[col_index] = CELL_DATA_LNAME
			elif results_util.anyin(col_name, ['имя', 'first name', 'first_name', 'name_first', 'firstname', 'iм\'я', 'vārds']):
				column_data_types[col_index] = CELL_DATA_FNAME
			elif 'отчество' in col_name:
				column_data_types[col_index] = CELL_DATA_MIDNAME
			elif results_util.anyin(col_name, ['город', 'місто', 'территор', 'населенный пункт', 'жительства', 'поселение', 'city', 'pilsēta']):
				column_data_types[col_index] = CELL_DATA_CITY
			elif results_util.anyin(col_name, ['регион', 'регіон', 'область', 'субъект']):
				column_data_types[col_index] = CELL_DATA_REGION
			elif results_util.anyin(col_name, ['клуб', 'организация', 'команда', 'коллектив', 'ведомство', 'club', 'клб', 'кфк', 'team']):
				column_data_types[col_index] = CELL_DATA_CLUB
			elif results_util.anyin(col_name, ['gun time', 'guntime', 'грязное время', 'абсолютный результат']):
				column_data_types[col_index] = CELL_DATA_GUN_RESULT
			elif results_util.anyin(col_name, ['рез', 'итоговое', 'время', 'р-тат', 'result', 'chip time', 'chiptime', 'finish_net_time', 'finišs']):
					# , u'финиш'
				column_data_types[col_index] = CELL_DATA_RESULT
			elif results_util.anyin(col_name, ['в гр', 'в в.гр', 'в категории', 'место по возр', 'место кат', 'место в кат', 'в возр', 'м.в.гр', 'м.гр',
					'age pl', 'division', 'rank_category', 'м (в.г.)', 'место груп', 'category pos', 'categ pos', 'group pos']):
				column_data_types[col_index] = CELL_DATA_PLACE_CATEGORY
			elif results_util.anyin(col_name, ['группа', 'катего', 'возрастн', 'в.гр', 'возр. гр', 'кат.', 'гр.', 'group', 'category', 'grupa', 'cat.']):
				column_data_types[col_index] = CELL_DATA_CATEGORY
			elif results_util.anyin(col_name, ['возр', 'полн.', 'age']):
				column_data_types[col_index] = CELL_DATA_AGE
			elif results_util.anyin(col_name, ['пол', 'gender', 'm/f']):
				column_data_types[col_index] = CELL_DATA_GENDER
			elif results_util.anyin(col_name, ['№ участ', 'ст. №', 'стартовый №', 'ст.№', '№ ст', 'bib', 'start #', 'number', 'стар но', 'race no']):
				column_data_types[col_index] = CELL_DATA_BIB
			elif results_util.anyin(col_name, ['дата рож', 'рожд', 'родж', 'год', 'д.р', 'г.р', 'date of birth', 'birthday', 'year']) \
					or (col_name == 'гр'):
				column_data_types[col_index] = CELL_DATA_BIRTHDAY
			elif results_util.anyin(col_name, ['номер', 'старт.', 'старт ', 'нагр', 'ст.№']):
				column_data_types[col_index] = CELL_DATA_BIB
			elif results_util.anyin(col_name, ['стр', 'країна', 'country', 'ctz', 'valsts']):
				column_data_types[col_index] = CELL_DATA_COUNTRY
			elif results_util.anyin(col_name, ['status', 'статус']):
				column_data_types[col_index] = CELL_DATA_STATUS
			elif results_util.anyin(col_name, ['отм.', 'комментари', 'примечани']):
				column_data_types[col_index] = CELL_DATA_COMMENT
			elif results_util.anyin(col_name, ['сила ветра', 'скорость ветра', 'ветер', 'wind']):
				column_data_types[col_index] = CELL_DATA_WIND
			elif (col_name == 'место') and ('russiarunning.com' in protocol.url_source):
				column_data_types[col_index] = CELL_DATA_PLACE
			elif results_util.anyin(col_name, ['parkrun_id', 'parkrun id']):
				column_data_types[col_index] = CELL_DATA_PARKRUN_ID
			elif distance.distance_type == models.TYPE_METERS:
				split_distance = parse_strings.parse_distance(col_name, distance_type=models.TYPE_METERS)
				if split_distance:
					column_data_types[col_index] = CELL_DATA_SPLIT
					column_split_values[col_index] = split_distance.id
		elif header[col_index]['type'] == xlrd.XL_CELL_NUMBER:
			length = results_util.int_safe(header[col_index]['value'])
			if length and (distance.distance_type == models.TYPE_METERS):
				split_distance = models.Distance.objects.filter(length=length, distance_type=models.TYPE_METERS).first()
				if split_distance:
					column_data_types[col_index] = CELL_DATA_SPLIT
					column_split_values[col_index] = split_distance.id
	return column_data_types, column_split_values

def xlrd_type2str(cell_type):
	if cell_type == xlrd.XL_CELL_EMPTY:
		return "XL_CELL_EMPTY"
	elif cell_type == xlrd.XL_CELL_BLANK:
		return "XL_CELL_BLANK"
	elif cell_type == xlrd.XL_CELL_NUMBER:
		return "XL_CELL_NUMBER"
	elif cell_type == xlrd.XL_CELL_TEXT:
		return "XL_CELL_TEXT"
	elif cell_type == xlrd.XL_CELL_DATE:
		return "XL_CELL_DATE"
	elif cell_type == xlrd.XL_CELL_BOOLEAN:
		return "XL_CELL_BOOLEAN"
	elif cell_type == xlrd.XL_CELL_ERROR:
		return "XL_CELL_ERROR"
	else:
		return "UNKNOWN"

def tuple2date_or_time(t):
	if all(t[:3]) and not any(t[3:]):
		return datetime.date(*t[:3]).strftime('%d.%m.%Y')
	if not any(t[:3]):
		if (len(t) > 6) and t[6]:
			return datetime.time(*t[3:]).strftime('%H:%M:%S.%f')[:-4]
		else:
			return datetime.time(*t[3:]).strftime('%H:%M:%S')
	return datetime.datetime(*t).isoformat(' ')

def xlrd_date_value2tuple(value, datemode):
	dt = xlrd.xldate.xldate_as_datetime(value, datemode)
	return ((0, 0, 0) if (dt.year <= 1899) else (dt.year, dt.month, dt.day)) + (dt.hour, dt.minute, dt.second, dt.microsecond)

def xlrd_cell2pair(cell, datemode):
	cell_type = cell.ctype
	cell_value = cell.value
	cell_datetime = cell_error = None
	if cell_type == xlrd.XL_CELL_NUMBER:
		if cell_value.is_integer():
			cell_value = int(cell_value)
	elif cell_type == xlrd.XL_CELL_DATE:
		try:
			# cell_datetime = xlrd.xldate_as_tuple(cell_value, datemode) # Doesn't work with centiseconds
			cell_datetime = xlrd_date_value2tuple(cell_value, datemode)
			cell_value = tuple2date_or_time(cell_datetime)
		except Exception as e:
			cell_error = 'Некорректные дата/время: {}'.format(str(e))
	elif cell_type == xlrd.XL_CELL_TEXT:
		cell_value = cell_value.strip()
		if cell_value == '':
			cell_type = xlrd.XL_CELL_EMPTY
		# if any(cell_value[:3]):
		# 	cell_value = datetime.date(*cell_value[:3])
		# else:
		# 	cell_value = datetime.time(*cell_value[3:])
	res = {'value': cell_value, 'type': cell_type}
	if cell_datetime:
		res['datetime'] = cell_datetime
	if cell_error:
		res['error'] = cell_error
	return res

def tuple2centiseconds(time, length=None):
	res = (((time[0] * 60) + time[1]) * 60 + time[2]) * 100
	if len(time) > 3 and time[3]:
		res += int(math.ceil(time[3] / 10000.))
	if length and results_util.result_is_too_large(length, res): # So the fields are shifted in Excel
		return res // 60
	return res

def timetuple2str(time):
	res = ''
	if time[0] > 23:
		days = time[0] // 24
		time = (time[0] % 24,) + time[1:]
		res = '{}days'.format(days)
	if (len(time) > 3) and time[3]:
		return res + datetime.time(*time).strftime('%Hh%Mm%Ss%fms')
	else:
		return res + datetime.time(*time).strftime('%Hh%Mm%Ss')

def centiseconds2str(value):
	hundredths = value % 100
	value //= 100
	seconds = value % 60
	value //= 60
	minutes = value % 60
	value //= 60
	hours = value
	return timetuple2str((hours, minutes, seconds, hundredths * 10000))

def xlrd_parse_nonempty_cell(cell): # Return cell_to_display
	if cell['type'] in [xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK]:
		# cell['error'] = u'Эта ячейка не может быть пустой'
		cell['warning'] = 'Пустая фамилия'
	return cell

# We replace common strings that make no sense with an empty string
def process_club_name(club_name: str) -> str:
	if club_name.lower() in ('нет клуба/no club', 'нет клуба', 'лично', '-'):
		return ''
	return club_name

# Process lname or fname or midname: remove commas and run title()
def process_name_part(name_part):
	res = name_part
	if res.endswith(','):
		res = res[:-1]
	return res.title()

def xlrd_parse_full_name(cell, first_name_position):
	if cell['type'] == xlrd.XL_CELL_TEXT:
		# name = cell['value'].split('\n')[-1] # It is needed for old "White nights" protocols
		name = cell['value']
		cell['lname'], cell['fname'], cell['midname'] = views_result.split_name(name, first_name_position)
		cell['lname'] = process_name_part(cell['lname'])
		cell['fname'] = process_name_part(cell['fname'])
		cell['midname'] = process_name_part(cell['midname'])

		if (len(cell['fname']) == 4) and (cell['midname'] == ''): # Maybe the name is like 'Бутусов В.И.'
			res = re.match(r'^([A-Za-zА-Яа-я])\.([A-Za-zА-Яа-я])\.$', cell['fname']) # 99999
			if res:
				cell['fname'] = res.group(1)
				cell['midname'] = res.group(2)

		if cell['lname']:
			cell['comment'] = 'Ф:"' + cell['lname'] + '"'
			if cell['fname']:
				cell['comment'] += ', И:"' + cell['fname'] + '"'
			if cell['midname']:
				cell['comment'] += ', О:"' + cell['midname'] + '"'
		else:
			cell['error'] = 'Фамилия не может быть пустой'
	elif cell['type'] == xlrd.XL_CELL_NUMBER:
		cell['lname'] = str(cell['value'])
		cell['fname'] = ''
		cell['midname'] = ''
		cell['warning'] = 'Считаем число {} фамилией'.format(cell['lname'])
	elif cell['type'] == xlrd.XL_CELL_EMPTY:
		cell['lname'] = ''
		cell['fname'] = ''
		cell['midname'] = ''
		cell['warning'] = 'Пустое имя'
	else:
		cell['error'] = 'Неподходящий тип ячейки: {}'.format(xlrd_type2str(cell['type']))
	return cell

def xlrd_parse_int_or_none_cell(cell, datemode): # Return cell_to_display
	cell['number'] = None
	if (cell['type'] == xlrd.XL_CELL_NUMBER) and isinstance(cell['value'], int):
		cell['number'] = cell['value']
	elif cell['type'] == xlrd.XL_CELL_TEXT and (results_util.int_safe(cell['value']) > 0):
		cell['number'] = results_util.int_safe(cell['value'])
	elif cell['type'] == xlrd.XL_CELL_TEXT and cell['value'].endswith('.') and (results_util.int_safe(cell['value'][:-1]) > 0):
		cell['number'] = results_util.int_safe(cell['value'][:-1])
	elif cell['type'] == xlrd.XL_CELL_TEXT:
		res = cell['value'].upper()
		if res == 'I':
			cell['number'] = 1
			cell['warning'] = 'Римская 1'
		elif res == 'II':
			cell['number'] = 2
			cell['warning'] = 'Римская 2'
		elif res == 'III':
			cell['number'] = 3
			cell['warning'] = 'Римская 3'
		elif res == 'IV':
			cell['number'] = 4
			cell['warning'] = 'Римская 4'
		elif res == 'V':
			cell['number'] = 5
			cell['warning'] = 'Римская 5'
		else:
			cell['warning'] = 'Не целое число. Считаем пустым'
	else:
		cell['warning'] = 'Не целое число. Считаем пустым'
	return cell

def xlrd_parse_float_cell(cell): # Return cell_to_display
	cell['number'] = None
	if cell['type'] in [xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK]:
		return cell
	if cell['type'] == xlrd.XL_CELL_NUMBER:
		cell['number'] = cell['value']
		return cell
	if cell['type'] == xlrd.XL_CELL_TEXT:
		if cell['value'].upper() == 'NWI': # no wind reading
			return cell
		res = re.match(r'^-{0,1}\d{1,2}[\.,]\d{1,2}$', cell['value']) # (-?)ab,c
		if res:
			cell['number'] = Decimal(cell['value'].replace(',', '.'))
			return cell
	cell['error'] = 'Невозможное значение скорости ветра'
	return cell

def xlrd_parse_gender(cell): # Return cell_to_display
	gender = models.GENDER_UNKNOWN
	if cell['type'] in [xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK]:
		cell['error'] = 'Пол не указан'
	elif cell['type'] == xlrd.XL_CELL_TEXT:
		gender = results_util.string2gender(cell['value'])
		if gender == models.GENDER_UNKNOWN:
			cell['error'] = 'Невозможное значение пола'
	else:
		cell['error'] = 'Невозможное значение пола'
	if 'error' not in cell:
		cell['gender'] = gender
		cell['comment'] = 'Пол: {}'.format(models.GENDER_CHOICES[gender][1])
	return cell

def xlrd_parse_status(cell):
	if cell['type'] in [xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK]:
		status = models.STATUS_UNKNOWN
		cell['warning'] = 'Статус не указан. Определяем его по столбцу с результатом'
	elif cell['type'] == xlrd.XL_CELL_TEXT:
		status = results_util.string2status(cell['value'])
		if status == models.STATUS_UNKNOWN:
			cell['error'] = 'Невозможное значение статуса'
	else:
		cell['error'] = 'Невозможное значение статуса'
	if 'error' not in cell:
		cell['status'] = status
		cell['comment'] = f'Статус: {results_util.RESULT_STATUSES[status][1]}'
	return cell

def parse_string_to_meters(s, distance):
	res = re.match(r'^(\d+)$', s) # 99999
	if res:
		return True, int(res.group(1))
	res = re.match(r'^(\d+)\s*м$', s) # 99999 м
	if res:
		return True, int(res.group(1))
	res = re.match(r'^(\d+)\s*км$', s) # 999 км
	if res:
		return True, int(res.group(1)) * 1000
	res = re.match(r'^(\d+)[\.,](\d{3})\s*км$', s) # 99[.,]999 км
	if res:
		return True, int(res.group(1)) * 1000 + int(res.group(2))
	res = re.match(r'^(\d+)[\.,](\d{2})\s*км$', s) # 99[.,]99 км
	if res:
		return True, int(res.group(1)) * 1000 + int(res.group(2)) * 10
	res = re.match(r'^(\d+)[\.,](\d{1})\s*км$', s) # 99[.,]9 км
	if res:
		return True, int(res.group(1)) * 1000 + int(res.group(2)) * 100
	res = re.match(r'^(\d+)\s*км\s*(\d{1,3})\s*м$', s) # 99 км 999 м
	if res:
		return True, int(res.group(1)) * 1000 + int(res.group(2))
	res = re.match(r'^(\d+)[\.,](\d{3})$', s) # 99[.,]999 -- most probably, in kilometers
	if res:
		return True, int(res.group(1)) * 1000 + int(res.group(2))
	res = re.match(r'^(\d+)[\.,](\d{2})$', s) # 99[.,]99 -- most probably, in centimeters. We cannot store centimeters
	if res:
		return True, int(res.group(1))
	return False, None

def is_run_or_walk_in_meters(distance):
	return distance.distance_type in (models.TYPE_METERS, models.TYPE_NORDIC_WALKING, models.TYPE_RACEWALKING, models.TYPE_CANICROSS, models.TYPE_HURDLING, models.TYPE_STEEPLECHASE)

def parse_string_to_time(s, distance):
	if s.startswith('А. '):
		s = s[len('А. '):]
	elif s.startswith('Б. '):
		s = s[len('Б. '):]
	res = re.match(r'^(\d{1,4})[hч.:;](\d{1,2})[mм:;\'](\d{1,2})с{0,1}$', s) # Hours[h.:;]minutes[m:;]seconds
	if res:
		hours = int(res.group(1))
		if is_run_or_walk_in_meters(distance) and distance.length <= 10000 and hours >= 3:
			pass
		else:
			return True, (hours, int(res.group(2)), int(res.group(3)))
	res = re.match(r'^(\d{1,2})[h.,:](\d{1,2})[.,:](\d{1,2})[.,:](\d{2})$', s) # Hours[h.,:]minutes[.,:]seconds[.,:]centiseconds
	if res:
		return True, (int(res.group(1)), int(res.group(2)), int(res.group(3)), int(res.group(4)) * 10000)
	res = re.match(r'^(\d{1,2})[h.,:](\d{1,2})[.,:](\d{1,2})[.,:](\d{1})$', s) # Hours[h.,:]minutes[.,:]seconds[.,:]deciseconds
	if res:
		return True, (int(res.group(1)), int(res.group(2)), int(res.group(3)), int(res.group(4)) * 100000)
	res = re.match(r'^(\d{2,3})[.,:_](\d{2})\.{0,1}$', s) # Minutes[.,:]seconds
	if res:
		if is_run_or_walk_in_meters(distance) and distance.length <= 400:
			pass
		else:
			minutes = int(res.group(1))
			hours = minutes // 60
			minutes %= 60
			return True, (hours, minutes, int(res.group(2)))
	res = re.match(r'^(\d{1,2})м(\d{2})сек$', s) # 1м32сек
	if res:
		return True, (0, int(res.group(1)), int(res.group(2)))
	res = re.match(r'^(\d{1,2})[\.,:_](\d{2})[\._]{0,1}$', s) # Minutes[.,:]seconds or seconds[.,:]centiseconds
	if res:
		if is_run_or_walk_in_meters(distance) and (distance.length <= 400) and (int(res.group(1)) >= 5): # seconds[.,:]centiseconds
			seconds = int(res.group(1))
			minutes = seconds // 60
			seconds %= 60
			return True, (0, minutes, seconds, int(res.group(2)) * 10000)
		else: # Minutes[.,]seconds
			minutes = int(res.group(1))
			hours = minutes // 60
			minutes %= 60
			seconds = int(res.group(2))
			if seconds <= 59:
				return True, (hours, minutes, seconds)
	res = re.match(r'^(\d{2})[\.,](\d{1})$', s) # Seconds[.,:]deciseconds
	if res:
		if is_run_or_walk_in_meters(distance) and distance.length <= 600:
			return True, (0, 0, int(res.group(1)), int(res.group(2)) * 100000)
	res = re.match(r'^(\d{1})[\.,](\d{1})$', s) # Seconds[.,:]deciseconds again
	if res:
		if is_run_or_walk_in_meters(distance) and distance.length <= 100:
			return True, (0, 0, int(res.group(1)), int(res.group(2)) * 100000)
	res = re.match(r'^(\d{2,3})[\.,:_](\d{2})[\.,_](\d{1})$', s) # Minutes[.:]seconds[.,]deciseconds
	if res:
		minutes = int(res.group(1))
		hours = minutes // 60
		minutes %= 60
		return True, (hours, minutes, int(res.group(2)), int(res.group(3)) * 100000)
	res = re.match(r'^(\d{1})[\.,:_](\d{2})[\.,_](\d{1})$', s) # Minutes[.,:]seconds[.,]deciseconds again
	if res and is_run_or_walk_in_meters(distance) and distance.length <= 3000:
		minutes = int(res.group(1))
		return True, (0, minutes, int(res.group(2)), int(res.group(3)) * 100000)
	res = re.match(r'^0{0,1}(\d{1}):(\d{2})[\.,](\d{2})$', s) # Hours:minutes.seconds
	if res and is_run_or_walk_in_meters(distance) and distance.length >= 3000:
		hours = int(res.group(1))
		if (hours <= 2) or (distance.length >= 10000):
			return True, (hours, int(res.group(2)), int(res.group(3)))
	res = re.match(r'^0{0,1}(\d{1}):(\d{2})[\.,]0$', s) # Hours:minutes.deciseconds
	if res and is_run_or_walk_in_meters(distance) and distance.length > 3000:
		return True, (int(res.group(1)), int(res.group(2)), 0)
	res = re.match(r'^0{0,1}(\d{1})[\.,](\d{1,2})[\.,](\d{2})\.{0,1}$', s)
	if res: # Hours[.,]minutes[.,]seconds or minutes[.,]seconds[.,]centiseconds
		if is_run_or_walk_in_meters(distance) and distance.length <= 3000: # minutes[.,]seconds[.,]centiseconds
			return True, (0, int(res.group(1)), int(res.group(2)), int(res.group(3)) * 10000)
		else: # Hours[.,]minutes[.,]seconds
			return True, (int(res.group(1)), int(res.group(2)), int(res.group(3)))
	res = re.match(r'^(\d{1})[\.,](\d{1,2})[\.,](\d{1})$', s)
	if res: # Hours[.,]minutes[.,]seconds or minutes[.,]seconds[.,]deciseconds
		if is_run_or_walk_in_meters(distance) and distance.length <= 3000: # minutes[.,]seconds[.,]deciseconds
			return True, (0, int(res.group(1)), int(res.group(2)), int(res.group(3)) * 100000)
		else: # Hours[.,]minutes[.,]seconds
			return True, (int(res.group(1)), int(res.group(2)), int(res.group(3)) * 10)
	res = re.match(r'^(\d{1,3})[:\.,](\d{2})[\.,](\d{2})$', s) # Minutes:seconds.centiseconds
	if res and is_run_or_walk_in_meters(distance) and distance.length <= 21100:
		minutes = int(res.group(1))
		hours = minutes // 60
		minutes %= 60
		return True, (hours, minutes, int(res.group(2)), int(res.group(3)) * 10000)
	res = re.match(r'^(\d{1,2}):(\d{1,2}):(\d{1,2})[:\.,](\d{3})$', s) # Hours:minutes:seconds:thousandths
	if res:
		hours = int(res.group(1))
		minutes = int(res.group(2))
		seconds = int(res.group(3))
		thousandths = int(res.group(4))
		hundredths = thousandths // 10
		if thousandths % 10:
			if hundredths < 99:
				hundredths += 1
			elif seconds < 59:
				hundredths = 0
				seconds += 1
			elif minutes < 59:
				hundredths = 0
				seconds = 0
				minutes += 1
			else:
				hundredths = 0
				seconds = 0
				minutes = 0
				hours += 1
		return True, (hours, minutes, seconds, hundredths * 10000)
	res = re.match(r'^(\d{1,2}):(\d{1,2})[.,](\d{3})$', s) # minutes:seconds[.,]thousandths
	if res:
		hours = 0
		minutes = int(res.group(1))
		seconds = int(res.group(2))
		thousandths = int(res.group(3))
		return True, round_thousandths_up(hours, minutes, seconds, thousandths)
	res = re.match(r'^(\d{1,2})[.,](\d{3})$', s) # seconds[.,]thousandths
	if res and is_run_or_walk_in_meters(distance) and distance.length <= 400:
		seconds = int(res.group(1))
		thousandths = int(res.group(2))
		return True, round_thousandths_up(0, 0, seconds, thousandths)
	res = re.match(r'^(\d{1,2})[ ]*ч\.*[ ]*(\d{1,2})[ ]*м\.*[ ]*(\d{1,2})[ ]*[cс]\.*$', s) # Hours[.:;]minutes[:;]seconds
	if res:
		return True, (int(res.group(1)), int(res.group(2)), int(res.group(3)))
	res = re.match(r'^(\d{1,2})[ ]*м\.*[ ]*(\d{1,2})[ ]*[cс]\.*$', s) # Hours[.:;]minutes[:;]seconds
	if res:
		return True, (0, int(res.group(1)), int(res.group(2)))
	return False, None

# We round thousandths up. Maybe this needs to increase seconds/minutes/hours
# Returns (hours, minutes, seconds, microseconds)
def round_thousandths_up(hours, minutes, seconds, thousandths):
	hundredths = thousandths // 10
	if thousandths % 10:
		if hundredths < 99:
			hundredths += 1
		elif seconds < 59:
			hundredths = 0
			seconds += 1
		elif minutes < 59:
			hundredths = 0
			seconds = 0
			minutes += 1
		else:
			hundredths = 0
			seconds = 0
			minutes = 0
			hours += 1
	return hours, minutes, seconds, hundredths * 10000

def parse_number_to_time(value, length): # Maybe it is minutes.seconds or seconds.centiseconds?
	if isinstance(value, int):
		return False, 'error 1'
	value *= 100
	if abs(value - round(value)) < 1e-10:
		value = int(round(value))
		if length <= 400: # seconds.centiseconds
			return True, value
		# Else: minutes.seconds
		minutes = value // 100
		seconds = value % 100
		if seconds >= 60:
			return False, 'error 3'
		return True, (minutes * 60 + seconds) * 100

	# Maybe it is a <=100m distance with thousandths?
	value *= 10
	if (length <= 100) and (abs(value - round(value)) < 1e-10):
		value = (int(round(value)) // 10) + 1
		return True, value

	return False, 'error 2:{}'.format(value - int(value))


def xlrd_parse_result(cell, datemode, distance, is_split=False, status_for_empty=models.STATUS_DNF):
	status = None
	result = None
	dist_is_minutes = (distance.distance_type in models.TYPES_MINUTES)
	result_is_empty = False
	if cell['type'] == xlrd.XL_CELL_DATE:
		if 'error' not in cell:
			if dist_is_minutes:
				cell['error'] = 'Неподходящее значение: {}'.format(cell['datetime'])
			else:
				if any(cell['datetime'][3:]) and not any(cell['datetime'][:3]):
					status = models.STATUS_FINISHED
					result = tuple2centiseconds(cell['datetime'][3:], length=distance.length)
					cell['comment'] = 'Время: {}'.format(centiseconds2str(result))
				else:
					cell['error'] = 'Время с плохими полями: {}'.format(cell['datetime'])
	elif cell['type'] in [xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK]:
		if is_split:
			cell['comment'] = 'Сплит не указан'
		else:
			result_is_empty = True
			cell['warning'] = 'Пусто'
	elif cell['type'] == xlrd.XL_CELL_TEXT:
		if dist_is_minutes:
			parsed, length = parse_string_to_meters(cell['value'], distance)
			if parsed:
				if length == 0:
					result_is_empty = True
					cell['warning'] = 'Нулевой результат'
		else:
			parsed, time = parse_string_to_time(cell['value'], distance)
			if parsed:
				if (time[1] > 59) or ((time[2] > 59)):
					parsed = False
				elif not any(time):
					result_is_empty = True
					cell['warning'] = 'Нулевое время'
		if parsed:
			if not result_is_empty:
				if dist_is_minutes:
					status = models.STATUS_FINISHED
					result = length
					cell['comment'] = 'Текст: {} м'.format(result)
				else:
					status = models.STATUS_FINISHED
					result = tuple2centiseconds(time)
					cell['comment'] = 'Текст: {}'.format(centiseconds2str(result))
		else:
			if is_split:
				res = cell['value'].upper()
				if (res in ['-', '–', '—']) or res.startswith(
						('DNS', 'DNF', 'DSQ', 'DQ', 'ЗАВЕРШИЛ', 'СОШ', 'НЕ ФИН', 'НЕ СТАРТ', 'Н.СТАРТ', 'НЕТ ИНФО')):
					cell['comment'] = 'Сплит не указан'
				else:
					cell['error'] = 'Нераспознанный сплит: {}'.format(res)
			else:
				res = cell['value'].upper()
				if res.startswith(('DNF', 'СОШ', 'Б. СОШ', 'НФ', 'Н/Ф', 'CОШ', 'НЕ ФИ', 'ЗАВЕРШИЛ', '1 КРУГ', '2 КРУГА', 'НЕТ. РЕГ. СТ.',
						'СН.КОНТ', 'НЕ ЗАК', 'НЕТ ФИНИШ', 'Б/В', 'СХОД', 'ПРЕВ КВ', 'ОТСУТ.')):
					status = models.STATUS_DNF
					cell['comment'] = 'DNF'
				elif res.startswith(('DSQ', 'DNQ', 'DQ', 'ДИСК', 'ДСКВ', 'СНЯТ', 'CНЯТ', 'ЛИМИТ')) or res.endswith('АННУЛ.'):
					status = models.STATUS_DSQ
					cell['comment'] = 'DSQ'
				elif res.startswith(('DNS', 'НЕ СТА', 'НЕ СТ', 'Н/Я', 'Н\Я', 'НЯ', 'Н/Д', 'Н\Д', 'Н/С', 'Н\С', 'Н.Я',
						'Б/Р', 'НЕЯВКА', 'Б.НЕЯВКА', 'Б. НЕЯВКА', 'НЕ ЯВ', '-', '–', '—')) \
						or (res == 'НС'):
					status = models.STATUS_DNS
					cell['comment'] = 'DNS'
				else:
					cell['error'] = 'Нераспознанный результат'
	elif cell['type'] == xlrd.XL_CELL_NUMBER:
		if dist_is_minutes:
			status = models.STATUS_FINISHED
			result = cell['value']
			if result <= 1000: # These are kilometers
				result *= 1000
			if not isinstance(result, int):
				result = int(math.floor(result))
			cell['comment'] = f'Число: {result} м'
		else:
			parsed, centiseconds = parse_number_to_time(cell['value'], distance.length)
			if parsed:
				status = models.STATUS_FINISHED
				result = centiseconds
				cell['comment'] = f'Число: {centiseconds2str(centiseconds)}'
			else:
				cell['error'] = 'Неподходящее числовое значение: {}'.format(cell['value'])
	else:
		cell['error'] = 'Неподходящий тип ячейки: {}'.format(xlrd_type2str(cell['type']))
	if result_is_empty:
		if is_split:
			cell['warning'] += '. Считаем, что сплит не указан'
		else:
			status = status_for_empty
			cell['warning'] += f'. Считаем, что {results_util.RESULT_STATUSES[status_for_empty][1]}'
	if status != models.STATUS_FINISHED:
		result = 0
	if result and (not is_split) and (distance.distance_type == models.TYPE_METERS):
		if (distance.length >= 400) and (result <= 2000):
			cell['error'] = 'Слишком быстрое время для такой дистанции'
		if (distance.length >= 800) and (result <= 6000):
			cell['error'] = 'Слишком быстрое время для такой дистанции'
		if (distance.length >= 40000) and (result <= 180000):
			cell['error'] = 'Слишком быстрое время для такой дистанции'
		elif (distance.length <= 1000) and (result >= 400000):
			cell['error'] = 'Слишком медленное время для такой дистанции'
	if 'error' not in cell:
		cell['status'] = status
		cell['result'] = result
	return cell

# short_birth_year=10, event_year=2019 -> 2010-01-01
# short_birth_year=10, event_year=2005 -> 1910-01-01
def two_digit_year_to_birthday(short_birth_year, event_year):
	event_year_first_digits, event_year_last_digits = divmod(event_year, 100)
	if short_birth_year <= event_year_last_digits:
		birth_year = short_birth_year + event_year_first_digits * 100
	else:
		birth_year = short_birth_year + (event_year_first_digits - 1) * 100
	return datetime.date(birth_year, 1, 1)

def parse_string_to_birthday(s, event_date): # Returns <is parsed?>, birthday, birthday_known
	s = s.lower().strip('.')
	if s in ('', 'н/д', '-'):
		return True, None, False
	res = re.match(r'^(\d{1,2})[\.,/](\d{1,2})[\.,/](\d{4})\.{0,1}$', s)
	if res:
		try:
			maybe_year = int(res.group(3))
			if (event_date.year - 110) <= maybe_year <= event_date.year:
				return True, datetime.date(maybe_year, int(res.group(2)), int(res.group(1))), True
		except:
			return False, None, False
	res = re.match(r'^(\d{1,2})[\.,/](\d{1,2})[\.,/](\d{2})$', s)
	if res:
		try:
			two_digit_year = int(res.group(3))
			four_digit_year = two_digit_year_to_birthday(two_digit_year, event_date.year).year
			return True, datetime.date(four_digit_year, int(res.group(2)), int(res.group(1))), True
		except:
			return False, None, False
	res = re.match(r'^\.{0,1}(\d{4})$', s)
	if res:	
		try:
			maybe_year = int(res.group(1))
			if (event_date.year - 110) <= maybe_year <= event_date.year:
				return True, datetime.date(maybe_year, 1, 1), False
		except:
			return False, None, False
	res = re.match(r'^(\d{4})[\.-](\d{2})[\.-](\d{2})$', s)
	if res:
		try:
			maybe_year = int(res.group(1))
			if (event_date.year - 110) <= maybe_year <= event_date.year:
				return True, datetime.date(maybe_year, int(res.group(2)), int(res.group(3))), True
		except:
			return False, None, False
	res = re.match(r'^(\d{2})$', s)
	if res:
		return True, two_digit_year_to_birthday(int(res.group(1)), event_date.year), False
	if s.startswith(('в/к', 'в\к', 'вне к')):
		return True, None, False
	return False, None, False

def xlrd_parse_birthday(cell, datemode, event_date): # Return tuple: cell_display, birthday, birthday_known
	birthday = None
	birthday_known = False
	if cell['type'] == xlrd.XL_CELL_DATE:
		if all(cell['datetime'][:3]) and not any(cell['datetime'][3:]):
			birthday = datetime.date(*(cell['datetime'][:3]))
			if (event_date.year - 110) <= birthday.year <= event_date.year:
				birthday_known = True
				cell['comment'] = 'Дата рождения: {}'.format(birthday.strftime('%d.%m.%Y'))
			else:
				cell['error'] = 'Невозможная дата рождения: {}'.format(birthday.strftime('%d.%m.%Y'))
		else:
			cell['error'] = 'Дата с плохими полями: {}'.format(cell['datetime'])
	elif cell['type'] == xlrd.XL_CELL_NUMBER:
		birthyear = cell['value']
		if not isinstance(birthyear, int):
			if birthyear.is_integer():
				birthyear = int(round(cell['value']))
			else:
				cell['error'] = 'Неподходящий год рождения: {}'.format(birthyear)
		if 'error' not in cell:
			if (event_date.year - 110) <= birthyear <= event_date.year:
				birthday = datetime.date(birthyear, 1, 1)
				cell['comment'] = 'Год рождения: {}'.format(birthyear)
			elif 10 <= birthyear <= 99:
				birthday = two_digit_year_to_birthday(birthyear, event_date.year)
				cell['warning'] = 'Вероятно, год: {}'.format(birthday.year)
			# elif 1800 <= birthyear <= 1899: # Hack for results.zone protocols
			# 	cell['warning'] = 'Неподходящий год рождения. Считаем пустым'
			else:
				cell['error'] = 'Неподходящий год рождения: {}'.format(birthyear)
	elif cell['type'] in [xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK]:
		cell['warning'] = 'Пустая ячейка'
	elif cell['type'] == xlrd.XL_CELL_TEXT:
		parsed, birthday, birthday_known = parse_string_to_birthday(cell['value'], event_date)
		if parsed:
			if birthday_known:
				cell['comment'] = 'Дата рождения: {}'.format(birthday.strftime('%d.%m.%Y'))
			elif birthday:
				cell['comment'] = 'Год рождения: {}'.format(birthday.year)
			elif cell['value']:
				cell['warning'] = 'Считаем пустым'
			else:
				cell['warning'] = 'Пустая ячейка'
		else:
			cell['error'] = 'Это не дата рождения: {}'.format(cell['value'])
	else:
		cell['error'] = 'Неподходящий тип ячейки: {}'.format(xlrd_type2str(cell['type']))
	if birthday and ('error' not in cell) and (birthday >= datetime.date.today()):
		cell['error'] = 'Дата рождения — в будущем. Так нельзя!'
	if 'error' not in cell:
		cell['birthday'] = birthday
		cell['birthday_known'] = birthday_known
	return cell

def process_column_types(request, race, column_data_types, column_split_values):
	ncols = len(column_data_types)
	type2col = [None] * len(CELL_DATA_CHOICES)
	split2col = {}
	ok_to_load = True
	is_by_skoblina = race.event.series.is_by_skoblina()

	for i in range(ncols): # First, we load all column types to backward dictionary
		field_type = column_data_types[i]
		if field_type == CELL_DATA_PASS:
			continue
		if field_type == CELL_DATA_SPLIT:
			if column_split_values[i] == 0:
				parse_protocols.log_warning(request, 'В колонке {} не указана дистанция для предварительного результата. Так нельзя.'.format(i))
				ok_to_load = False
				continue
			if column_split_values[i] in split2col:
				parse_protocols.log_warning(request, 'Колонки {} и {} содержат сплит на одну и ту же дистанцию. Так нельзя.'.format(
					split2col[column_split_values[i]], i))
				ok_to_load = False
				continue
			if column_split_values[i] == race.distance.id:
				if is_by_skoblina: # Hack for Skoblina protocols
					column_data_types[i] = CELL_DATA_PASS
				else:
					parse_protocols.log_warning(request, 'Сплит в колонке {} совпадает с длиной всей дистанции. Так нельзя.'.format(i))
					ok_to_load = False
					continue
			if race.distance_real and (column_split_values[i] == race.distance_real.id):
				parse_protocols.log_warning(request, 'Сплит в колонке {} совпадает с фактической длиной всей дистанции. Так нельзя.'.format(i))
				ok_to_load = False
				continue
			split2col[column_split_values[i]] = i
		else:
			if type2col[field_type]:
				if is_by_skoblina and (field_type == CELL_DATA_PLACE_GENDER): # Hack for Skoblina protocols
					column_data_types[i] = CELL_DATA_PASS
				else:
					parse_protocols.log_warning(request, 'Колонки {} и {} имеют один и тот же тип «{}». Так нельзя.'.format(
						type2col[field_type], i, CELL_DATA_CHOICES[field_type]))
					ok_to_load = False
					continue
			type2col[field_type] = i
	# Now let's check that all important columns exist
	if (type2col[CELL_DATA_NAME] is None) and ( (type2col[CELL_DATA_FNAME] is None) or (type2col[CELL_DATA_LNAME] is None) ):
		parse_protocols.log_warning(request, 'Должна быть либо колонка «имя целиком», либо отдельные колонки «имя» и «фамилия».')
		ok_to_load = False
	if (type2col[CELL_DATA_NAME] is not None) and (
			(type2col[CELL_DATA_FNAME] is not None)
			or (type2col[CELL_DATA_LNAME] is not None)
			or (type2col[CELL_DATA_MIDNAME] is not None)
		):
		parse_protocols.log_warning(request, 'Раз есть колонка «имя целиком», не должно быть отдельных колонок для фамилии, имени или отчества.')
		ok_to_load = False
	if type2col[CELL_DATA_RESULT] is None:
		parse_protocols.log_warning(request, 'Вы не указали колонку с результатом. Так нельзя.')
		ok_to_load = False
	return type2col, split2col, ok_to_load

def process_cell_values(race, rows_with_results, datemode, data, column_data_types, column_numbers, type2col, settings):
	n_parse_errors = n_parse_warnings = 0
	settings['has_empty_results'] = False
	settings['has_categories_for_both_genders'] = False
	if type2col[CELL_DATA_NAME] is not None:
		# [:-1] is a hack for old "White Nights" protocols with multi-line cells with names
		first_name_position = views_result.get_first_name_position(
			[ str(data[i][type2col[CELL_DATA_NAME]]['value']).split('\n')[-1]
				for i in range(len(data)) if rows_with_results[i] ]
		)
	for row_index in range(len(data)):
		if rows_with_results[row_index]:
			for col_index in range(len(data[row_index])):
				cell = data[row_index][col_index]
				data_type = column_data_types[col_index]
				if data_type == CELL_DATA_BIRTHDAY:
					cell = xlrd_parse_birthday(cell, datemode, race.event.start_date)
				elif data_type == CELL_DATA_RESULT:
					cell = xlrd_parse_result(cell, datemode, race.distance, status_for_empty=settings['status_for_empty'])
					if cell['type'] in [xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK]:
						settings['has_empty_results'] = True
				elif data_type == CELL_DATA_GUN_RESULT:
					cell = xlrd_parse_result(cell, datemode, race.distance, is_split=True)
				elif data_type == CELL_DATA_SPLIT:
					cell = xlrd_parse_result(cell, datemode, race.distance, is_split=True)
				elif data_type == CELL_DATA_NAME:
					cell = xlrd_parse_full_name(cell, first_name_position)
				elif data_type == CELL_DATA_LNAME:
					cell = xlrd_parse_nonempty_cell(cell)
				elif data_type == CELL_DATA_GENDER:
					cell = xlrd_parse_gender(cell)
				elif data_type == CELL_DATA_STATUS:
					cell = xlrd_parse_status(cell)
				elif data_type == CELL_DATA_WIND:
					cell = xlrd_parse_float_cell(cell)
				elif data_type in [CELL_DATA_PLACE, CELL_DATA_PLACE_GENDER, CELL_DATA_PLACE_CATEGORY, CELL_DATA_AGE, CELL_DATA_PARKRUN_ID]:
					cell = xlrd_parse_int_or_none_cell(cell, datemode)
					if data_type == CELL_DATA_AGE and cell['number'] and not (models.MIN_RUNNER_AGE <= cell['number'] <= models.MAX_RUNNER_AGE):
						cell['error'] = 'Недопустимый возраст'

				if ('error' not in cell) and (data_type in MAX_FIELD_LENGTHS) \
						and (len(str(cell['value'])) > MAX_FIELD_LENGTHS[data_type]):
					cell['error'] = f'Слишком длинное значение: {len(str(cell["value"]))} больше разрешенного {MAX_FIELD_LENGTHS[data_type]}'

				if 'error' in cell:
					n_parse_errors += 1
					column_numbers[col_index]['errors'] = column_numbers[col_index].get('errors', 0) + 1
				if 'warning' in cell:
					n_parse_warnings += 1
					column_numbers[col_index]['warnings'] = column_numbers[col_index].get('warnings', 0) + 1
				data[row_index][col_index] = cell
	if n_parse_errors == 0:
		male_categories = set()
		female_categories = set()
		if ( (type2col[CELL_DATA_CATEGORY] is not None) or any(settings['categories']) ) \
			and ( (type2col[CELL_DATA_GENDER] is not None) or settings['show_gender_column'] ):
			for row_index in range(len(data)):
				if rows_with_results[row_index]:
					if type2col[CELL_DATA_CATEGORY] is not None:
						category = data[row_index][type2col[CELL_DATA_CATEGORY]]['value']
					else:
						category = settings['categories'][row_index]
					if category:
						if type2col[CELL_DATA_GENDER] is not None:
							gender = data[row_index][type2col[CELL_DATA_GENDER]]['gender']
						else:
							gender = results_util.GENDER_FEMALE if settings['genders'][row_index] else results_util.GENDER_MALE
						if gender == results_util.GENDER_MALE:
							male_categories.add(category)
						elif gender == results_util.GENDER_FEMALE:
							female_categories.add(category)
			settings['has_categories_for_both_genders'] = len(male_categories & female_categories) > 0

	return data, n_parse_errors, n_parse_warnings, column_numbers, settings

# Ok, loading results
def load_protocol(request, race, protocol, data, rows_with_results, column_data_types, column_split_values, type2col, settings):
	user = request.user if request else User.objects.get(pk=1)
	results_for_deletion = models.Result.objects.none()
	if settings['save_old_results'] == OLD_RESULTS_DELETE_ALL:
		results_for_deletion = race.result_set.filter(source=models.RESULT_SOURCE_DEFAULT)
	elif settings['save_old_results'] == OLD_RESULTS_DELETE_MEN:
		results_for_deletion = race.result_set.filter(source=models.RESULT_SOURCE_DEFAULT, gender=results_util.GENDER_MALE)
	elif settings['save_old_results'] == OLD_RESULTS_DELETE_WOMEN:
		results_for_deletion = race.result_set.filter(source=models.RESULT_SOURCE_DEFAULT, gender=results_util.GENDER_FEMALE)

	n_deleted_links = parse_protocols.delete_results_and_store_connections(request, user, race, results_for_deletion)
	n_recovered_links = 0
	nrows = len(data)
	ncols = len(column_data_types)
	n_results_loaded = n_splits_loaded = n_parkrun_runners_created = n_parkruns_connected = 0
	runners_touched = set()

	# we save pairs (category name, <category_size object>)
	category_sizes = {category_size.name: category_size for category_size in race.category_size_set.all()}
	category_lower_to_orig = {name.lower(): name for name in category_sizes.keys()}
	# TODO: Remove when problem with Existing category sizes is solved
	category_sizes_initial = {category_size.name: category_size for category_size in race.category_size_set.all()}
	category_lower_to_orig_initial = {name.lower(): name for name in category_sizes.keys()}

	column_split_distances = [None] * ncols
	for i in range(ncols):
		if column_split_values[i]:
			column_split_distances[i] = models.Distance.objects.get(pk=column_split_values[i])
	for i in range(nrows):
		if not rows_with_results[i]:
			continue
		row = data[i]
		result = models.Result(race=race, loaded_by=user)
		if type2col[CELL_DATA_NAME] is not None:
			cell = row[type2col[CELL_DATA_NAME]]
			result.name_raw = cell['value']
			result.lname, result.fname, result.midname = cell['lname'], cell['fname'], cell['midname']
		else:
			if type2col[CELL_DATA_LNAME] is not None:
				result.lname_raw = row[type2col[CELL_DATA_LNAME]]['value']
				result.lname = str(result.lname_raw).title()
			if type2col[CELL_DATA_FNAME] is not None:
				result.fname_raw = row[type2col[CELL_DATA_FNAME]]['value']
				result.fname = str(result.fname_raw).title()
			if type2col[CELL_DATA_MIDNAME] is not None:
				result.midname_raw = row[type2col[CELL_DATA_MIDNAME]]['value']
				result.midname = str(result.midname_raw).title()
		if type2col[CELL_DATA_BIRTHDAY] is not None:
			# result.birthday_raw = row[type2col[CELL_DATA_BIRTHDAY]]['value']
			result.birthday = row[type2col[CELL_DATA_BIRTHDAY]]['birthday']
			result.birthday_known = row[type2col[CELL_DATA_BIRTHDAY]]['birthday_known']
			if result.birthday_known:
				result.birthday_raw = result.birthday
			elif result.birthday:
				result.birthyear_raw = result.birthday.year
		if type2col[CELL_DATA_AGE] is not None:
			result.age_raw = row[type2col[CELL_DATA_AGE]]['number']
			result.age = result.age_raw
		if type2col[CELL_DATA_COUNTRY] is not None:
			result.country_raw = row[type2col[CELL_DATA_COUNTRY]]['value']
			result.country_name = result.country_raw
		if type2col[CELL_DATA_REGION] is not None:
			result.region_raw = row[type2col[CELL_DATA_REGION]]['value']
		if type2col[CELL_DATA_CITY] is not None:
			result.city_raw = row[type2col[CELL_DATA_CITY]]['value']
			result.city_name = result.city_raw
		if type2col[CELL_DATA_CLUB] is not None:
			result.club_raw = str(row[type2col[CELL_DATA_CLUB]]['value'])[:100]
			result.club_name = process_club_name(result.club_raw)
		if type2col[CELL_DATA_PLACE] is not None:
			result.place_raw = row[type2col[CELL_DATA_PLACE]]['number']
			if settings['use_places_from_protocol']:
				result.place = result.place_raw
		if type2col[CELL_DATA_BIB] is not None:
			result.bib = row[type2col[CELL_DATA_BIB]]['value']
			result.bib_raw = result.bib
		if (type2col[CELL_DATA_STATUS] is None) or (row[type2col[CELL_DATA_STATUS]]['status'] == models.STATUS_UNKNOWN):
			result.result = row[type2col[CELL_DATA_RESULT]]['result']
			result.status = row[type2col[CELL_DATA_RESULT]]['status']
		else:
			result.status = row[type2col[CELL_DATA_STATUS]]['status']
			if result.status == models.STATUS_FINISHED:
				result.result = row[type2col[CELL_DATA_RESULT]]['result']
			else:
				result.result = 0
		result.status_raw = result.status
		result.time_raw = str(row[type2col[CELL_DATA_RESULT]]['value'])[:20]
		if type2col[CELL_DATA_GUN_RESULT] is not None:
			result.gun_result = row[type2col[CELL_DATA_GUN_RESULT]]['result']
			result.gun_time_raw = row[type2col[CELL_DATA_GUN_RESULT]]['value']
		if type2col[CELL_DATA_GENDER] is not None:
			result.gender = row[type2col[CELL_DATA_GENDER]]['gender']
			result.gender_raw = str(row[type2col[CELL_DATA_GENDER]]['value'])[:10]
		else:
			result.gender = results_util.GENDER_FEMALE if settings['genders'][i] else results_util.GENDER_MALE
		if type2col[CELL_DATA_PLACE_GENDER] is not None:
			result.place_gender_raw = row[type2col[CELL_DATA_PLACE_GENDER]]['number']
			if settings['use_places_from_protocol']:
				result.place_gender = result.place_gender_raw

		category = ''
		if type2col[CELL_DATA_CATEGORY] is not None:
			result.category_raw = str(row[type2col[CELL_DATA_CATEGORY]]['value'])[:models.MAX_CATEGORY_LENGTH]
			category = result.category_raw
		else:
			category = settings['categories'][i]
		if category and (settings['category_prefix'] != CATEGORY_PREFIX_NONE):
			gender_from_category = results_util.string2gender(category)
			if ( (settings['category_prefix'] == CATEGORY_PREFIX_RUS_SOME) and (gender_from_category == models.GENDER_UNKNOWN) ) \
					or (settings['category_prefix'] == CATEGORY_PREFIX_RUS_ALL):
				category = ('Ж' if (result.gender == results_util.GENDER_FEMALE) else 'М') + str(category)
			elif ( (settings['category_prefix'] == CATEGORY_PREFIX_ENG_SOME) and (gender_from_category == models.GENDER_UNKNOWN) ) \
					or (settings['category_prefix'] == CATEGORY_PREFIX_ENG_ALL):
				category = ('F' if (result.gender == results_util.GENDER_FEMALE) else 'M') + str(category)
		if category:
			category = category[:models.MAX_CATEGORY_LENGTH].strip()
			category_lower = category.lower()
			if category_lower not in category_lower_to_orig:
				# For unknown reason this Category_size sometimes already exists
				category_sizes[category], created = models.Category_size.objects.get_or_create(race=race, name=category)
				category_lower_to_orig[category_lower] = category
			result.category_size = category_sizes[category_lower_to_orig[category_lower]]
			# result.category = category

		if type2col[CELL_DATA_PLACE_CATEGORY] is not None:
			result.place_category_raw = row[type2col[CELL_DATA_PLACE_CATEGORY]]['number']
			if settings['use_places_from_protocol']:
				result.place_category = result.place_category_raw
		if type2col[CELL_DATA_COMMENT] is not None:
			result.comment = str(row[type2col[CELL_DATA_COMMENT]]['value'])[:models.MAX_RESULT_COMMENT_LENGTH]
		if type2col[CELL_DATA_WIND] is not None:
			result.wind = row[type2col[CELL_DATA_WIND]]['number']
		if (type2col[CELL_DATA_PARKRUN_ID] is not None) and (row[type2col[CELL_DATA_PARKRUN_ID]]['number'] is not None):
			result.parkrun_id = row[type2col[CELL_DATA_PARKRUN_ID]]['number']
			if result.gender not in (results_util.GENDER_MALE, results_util.GENDER_FEMALE):
				parse_protocols.log_warning(request, f'У результата {result.time_raw} не указан пол. Не привязываем к бегуну по parkrun_id')
			else:
				kwargs = results_util.get_parkrun_or_verst_dict(result.parkrun_id)
				runner, created = models.Runner.objects.get_or_create(
					defaults={'lname': result.lname, 'fname': result.fname, 'gender': result.gender},
					**kwargs,
				)
				n_parkruns_connected += 1
				if created:
					n_parkrun_runners_created += 1
				result.runner = runner
				result.user_id = runner.user_id
				runners_touched.add(runner)
		result.save()
		n_results_loaded += 1
		result.refresh_from_db()
		cur_split_sum = 0
		for col_index in range(ncols):
			if column_data_types[col_index] == CELL_DATA_SPLIT and row[col_index]['result']:
				if settings['cumulative_splits']:
					cur_split_sum += row[col_index]['result']
					split_value = cur_split_sum
				else:
					split_value = row[col_index]['result']
				split = models.Split.objects.create(result=result, distance=column_split_distances[col_index], 
					value=split_value)
				n_splits_loaded += 1
		# Now we try to recover killed with links to runners/users.
		if (n_deleted_links > n_recovered_links) and parse_protocols.try_fix_lost_connection(result):
			n_recovered_links += 1
	race.load_status = models.RESULTS_SOME_OFFICIAL if settings['use_places_from_protocol'] else models.RESULTS_LOADED
	race.loaded_from = protocol.upload.name
	race.was_checked_for_klb = False
	race.save()
	models.Result.objects.filter(race=race, source=models.RESULT_SOURCE_KLB).delete()
	if hasattr(race, 'reg_race_details'):
		models.Race_to_attach_registered.objects.get_or_create(race=race)
	runner_stat.update_runners_and_users_stat(runners_touched)
	if runners_touched:
		parse_protocols.log_success(request, f'Привязано {len(runners_touched)} результатов по parkrun_id')
	if n_parkrun_runners_created:
		parse_protocols.log_success(request, f'В том числе создано {n_parkrun_runners_created} новых бегунов')

	if settings['use_places_from_protocol']:
		race.category_size_set.all().update(size=None)
		views_result.reset_race_headers(race)
	else:
		views_result.fill_places(race)
		views_result.fill_race_headers(race)
	views_result.fill_timing_type(race)

	models.Table_update.objects.create(model_name=race.event.__class__.__name__, row_id=race.event.id, child_id=race.id,
		action_type=models.ACTION_RESULTS_LOAD, user=user, is_verified=models.is_admin(user)
	)
	generators.generate_last_loaded_protocols()
	parse_protocols.log_success(request, 'Загрузка завершена! Загружено результатов: {}{}{}.'.format(
		n_results_loaded, ', промежуточных результатов: ' if n_splits_loaded else '', n_splits_loaded if n_splits_loaded else ''))
	if n_deleted_links:
		parse_protocols.log_success(request, 'Восстановлено {} привязок результатов из {}.'.format(n_recovered_links, n_deleted_links))

def get_race(POST, races):
	race = None
	if 'new_race_id' in POST:
		race = races.filter(pk=POST['new_race_id']).first()
	elif 'race_id' in POST:
		race = races.filter(pk=POST['race_id']).first()
	if race is None:
		race = races.order_by('distance__distance_type', '-distance__length', 'precise_name').first()
	return race

def get_sheet_index(sheet_id, POST):
	if sheet_id:
		return results_util.int_safe(sheet_id)
	if 'new_sheet_index' in POST:
		return results_util.int_safe(POST['new_sheet_index'])
	elif 'sheet_index' in POST:
		return results_util.int_safe(POST['sheet_index'])
	return 0

@views_common.group_required('editors', 'admins')
def protocol_details(request, event_id=None, race_id=None, protocol_id=None, sheet_id=None):
	if event_id:
		event = get_object_or_404(models.Event, pk=event_id)
		race = None
	else:
		race = get_object_or_404(models.Race, pk=race_id)
		event = race.event
	context, has_rights, target = views_common.check_rights(request, event=event)
	context['allow_places_from_protocol'] = context['is_admin'] or (request.user.id in [395, ])
	if not has_rights:
		return target
	
	races = event.race_set
	if race is None:
		race = get_race(request.POST, races)
	if race is None:
		messages.warning(request, 'У выбранного забега нет ни одной дистанции. Сначала добавьте их.')
		return redirect(event)
	context['race'] = race
	context['event'] = event
	context['races'] = races.select_related('distance').order_by('distance__distance_type', '-distance__length', 'precise_name')
	wb_xls = None
	column_numbers = None
	n_splits = 0

	settings = {}
	settings['save_old_results'] = OLD_RESULTS_LEAVE_ALL
	settings['cumulative_splits'] = False
	settings['use_places_from_protocol'] = False
	settings['status_for_empty'] = models.STATUS_DNF
	settings['category_prefix'] = CATEGORY_PREFIX_NONE

	protocols = event.get_xls_protocols()
	if protocol_id:
		protocol = get_object_or_404(protocols, pk=protocol_id)
	else:
		protocol = protocols.first()

	if not protocol:
		messages.warning(request, 'У выбранного забега нет ни одного подходящего протокола.')
		return redirect(event)
	context['protocols'] = protocols
	context['protocol'] = protocol

	path = protocol.get_upload_path()
	extension = path.split(".")[-1].lower()
	if extension in ["xls", "xlsx", "xlsm"]:
		try:
			wb_xls = xlrd.open_workbook(path)
		except Exception as e:
			messages.warning(request, f'Не получилось открыть файл {path}: ошибка xlrd: {repr(e)}')
	else:
		messages.warning(request, f'Не получилось открыть файл {path}: недопустимое расширение {extension}')

	if wb_xls:
		context['sheetnames'] = wb_xls.sheet_names()
		sheet_index = get_sheet_index(sheet_id, request.POST)
		context['sheet_index'] = sheet_index
		sheet = wb_xls.sheet_by_index(sheet_index)
		ncols = sheet.ncols
		if ncols > MAX_N_COLS:
			messages.warning(request, f'В протоколе целых {ncols} столбцов! Это слишком много. Работаем с первыми {MAX_N_COLS}')
			ncols = MAX_N_COLS

		data = []
		max_nonempty_cells_number = 0
		max_nonempty_cells_index = 0
		for row_index in range(sheet.nrows):
			row = []
			nonempty_cells_number = 0
			for col_index in range(ncols):
				row.append(xlrd_cell2pair(sheet.cell(row_index, col_index), wb_xls.datemode))
				if sheet.cell_type(row_index, col_index) not in [xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK]:
					nonempty_cells_number += 1
			# row[0] = str(row_index) # + "(" + str(nonempty_cells_number) + ")"
			data.append(row)
			if nonempty_cells_number > max_nonempty_cells_number + 3:
				max_nonempty_cells_number = nonempty_cells_number
				max_nonempty_cells_index = row_index
		header_row = max_nonempty_cells_index
		column_data_types = [CELL_DATA_PASS] * ncols
		column_split_values = [0] * ncols
		column_numbers = [{'number': i} for i in range(ncols)]
		rows_with_results = [0] * sheet.nrows

		settings['show_gender_column'] = False
		settings['genders'] = [False] * sheet.nrows
		settings['show_category_column'] = False
		settings['categories'] = [''] * sheet.nrows
		settings['has_empty_results'] = False
		settings['show_category_prefix_choices'] = False

		to_update_rows = ('frmProtocol_update' in request.POST) or ('frmProtocol_submit' in request.POST)
		to_submit = ('frmProtocol_submit' in request.POST)
		if to_update_rows or ('new_race_id' in request.POST):
			for i in range(sheet.nrows):
				rows_with_results[i] = request.POST.get('count_row_' + str(i), 0)
			for i in range(ncols):
				column_data_types[i] = results_util.int_safe(request.POST.get('select_' + str(i), 0))
				column_split_values[i] = results_util.int_safe(request.POST.get('select_split_' + str(i), 0))
			header_row = results_util.int_safe(request.POST.get('header_row', 0))
			settings['save_old_results'] = results_util.int_safe(request.POST.get('save_old_results', OLD_RESULTS_LEAVE_ALL))
			settings['show_gender_column'] = results_util.int_safe(request.POST.get('show_gender_column', 0)) > 0
			if settings['show_gender_column']:
				for i in range(sheet.nrows):
					settings['genders'][i] = ('gender_row_' + str(i)) in request.POST
			settings['show_category_column'] = results_util.int_safe(request.POST.get('show_category_column', 0)) > 0
			if settings['show_category_column']:
				for i in range(sheet.nrows):
					settings['categories'][i] = request.POST.get('category_row_' + str(i), '').strip()
			settings['cumulative_splits'] = 'cumulative_splits' in request.POST

			status_for_empty = results_util.int_safe(request.POST.get('status_for_empty'))
			if status_for_empty in (models.STATUS_DNF, models.STATUS_DSQ, models.STATUS_DNS):
				settings['status_for_empty'] = status_for_empty

			settings['use_places_from_protocol'] = 'use_places_from_protocol' in request.POST
			settings['show_category_prefix_choices'] = 'category_prefix' in request.POST
			if settings['show_category_prefix_choices']:
				settings['category_prefix'] = results_util.int_safe(request.POST.get('category_prefix', CATEGORY_PREFIX_NONE))
		else: # default values
			for i in range(header_row + 1, sheet.nrows):
				rows_with_results[i] = 1
		if (not any(column_data_types)) or ( (not to_submit) and ('refresh_row_headers' in request.POST) ):
			column_data_types, column_split_values = default_data_types(
				request, protocol, data, header_row, race.distance, column_data_types, column_split_values)
		for i in range(ncols):
			if column_split_values[i]:
				n_splits += 1

		if to_update_rows:
			# Are column types OK?
			type2col, split2col, column_types_ok = process_column_types(request, race, column_data_types, column_split_values)
			# Are data in all important columns OK?
			data, n_parse_errors, n_parse_warnings, column_numbers, settings = process_cell_values(
				race, rows_with_results, wb_xls.datemode, data, column_data_types, column_numbers, type2col, settings)
			context['n_parse_errors'] = n_parse_errors
			context['n_parse_warnings'] = n_parse_warnings
			context['ok_to_import'] = column_types_ok and (n_parse_errors == 0)
			if column_types_ok:
				if (not settings['show_gender_column']) and (type2col[CELL_DATA_GENDER] is None):
					settings['show_gender_column'] = True
					column_types_ok = False
					if type2col[CELL_DATA_CATEGORY] is None:
						messages.warning(request, 'В протоколе нет столбца с полом. Этот столбец добавлен автоматически. '
							+ 'Отметьте галочки в строках с женщинами.')
					else:
						for i in range(sheet.nrows):
							settings['genders'][i] = \
								results_util.string2gender(data[i][type2col[CELL_DATA_CATEGORY]]['value']) == results_util.GENDER_FEMALE
						messages.warning(request, 'В протоколе нет столбца с полом. Этот столбец добавлен автоматически. '
							+ 'Мы попытались заполнить его, исходя из столбца «Группа»; проверьте, что получилось.')
				if (not settings['show_category_column']) and (type2col[CELL_DATA_CATEGORY] is None):
					settings['show_category_column'] = True
					column_types_ok = False
					messages.warning(request, 'В протоколе нет столбца с категорией. Этот столбец добавлен автоматически. '
						+ 'Если хотите, заполните его.')
				if (not settings['show_category_prefix_choices']) and settings['has_categories_for_both_genders']:
					settings['show_category_prefix_choices'] = True
					messages.warning(request, 'Есть одинаковые группы у мужчин и у женщин. Вы можете указать, приписать ли '
						+ 'к названиям групп буквы, обозначающие пол.')

			if column_types_ok and (n_parse_errors == 0):
				if to_submit:
					load_protocol(request, race, protocol, data, rows_with_results, column_data_types,
						column_split_values, type2col, settings)
					if (races.count() == 1) and (not protocol.is_processed):
						protocol.mark_processed(request.user, comment='Автоматически при загрузке единственной дистанции')
						messages.success(request, 'Протокол помечен как полностью обработанный. Отлично!')
					# return render(request, "editor/protocol_details.html", context)
				else:
					messages.success(request, 'Все проверки пройдены, можно загружать!')

		context['column_data_types'] = [
			{'value': column_data_types[i], 'split': column_split_values[i]}
			for i in range(ncols)
		]
		context['used_rows'] = set([i for i in range(len(column_data_types)) if (column_data_types[i] != CELL_DATA_PASS)])
		context['data'] = [{'checked': rows_with_results[i], 'data': data[i],
			'gender': settings['genders'][i], 'category': settings['categories'][i]} for i in range(sheet.nrows)]
		context['header_row'] = header_row
		if settings['has_empty_results']:
			context['has_empty_results'] = settings['has_empty_results']
			context['STATUS_DNF'] = models.STATUS_DNF
			context['STATUS_DSQ'] = models.STATUS_DSQ
			context['STATUS_DNS'] = models.STATUS_DNS
			context['status_for_empty'] = settings['status_for_empty']
	
		context['column_numbers'] = column_numbers
		context['cell_data_choices'] = CELL_DATA_CHOICES
		context['show_gender_column'] = settings['show_gender_column']
		context['show_category_column'] = settings['show_category_column']
		context['save_old_results'] = settings['save_old_results']
		context['use_places_from_protocol'] = settings['use_places_from_protocol']
		if n_splits >= 2:
			context['show_cumulative_splits'] = True
			context['cumulative_splits'] = settings['cumulative_splits']
		if settings['show_category_prefix_choices']:
			context['show_category_prefix_choices'] = settings['show_category_prefix_choices']
			context['CATEGORY_PREFIXES'] = CATEGORY_PREFIXES
			context['category_prefix'] = settings['category_prefix']
	context['page_title'] = 'Обработка протокола'
	context['distances'] = models.Distance.objects.filter(distance_type=race.distance.distance_type).order_by('-popularity_value', 'length')
	return render(request, "editor/protocol_details.html", context)

def process_protocol(race_id=None, protocol_id=None, sheet_index=None, settings={},
		header_row=None, column_data_types=None, column_split_values=None, rows_with_results=None, errors_limit=5):
	race = models.Race.objects.filter(pk=race_id).first()
	if race:
		print('Работаем с забегом {}, дистанцией {} (id {}).'.format(race.event, race, race.id))
	else:
		print('Не найдена дистанция с id', race_id)
		return False
	event = race.event
	wb_xls = None

	protocols = event.get_xls_protocols()
	print('Подходящие протоколы у дистанции:')
	for protocol in protocols:
		print('{}, id {}'.format(protocol.get_upload_path(), protocol.id))
	if protocol_id:
		protocol = protocols.get(pk=protocol_id)
		if not protocol:
			print('Протокол с id {} не найден или имеет неправильный формат.'.format(protocol_id))
			return False
	else:
		protocol = protocols.first()
		if not protocol:
			print('У выбранного забега нет ни одного подходящего протокола.')
			return False

	print('Работаем с протоколом {}, id {}.'.format(protocol.get_upload_path(), protocol.id))
	try:
		wb_xls = xlrd.open_workbook(protocol.get_upload_path())
	except Exception as e:
		print(f'Не получилось открыть файл протокола: ошибка xlrd: {repr(e)}')
		return False

	sheetnames = wb_xls.sheet_names()
	print('Листы в протоколе:')
	for i in range(len(sheetnames)):
		print('№ {}: {}'.format(i, sheetnames[i]))
	sheet_index = sheet_index if (sheet_index and (0 <= sheet_index < len(sheetnames))) else 0
	sheet = wb_xls.sheet_by_index(sheet_index)
	print('Работаем с листом «{}», № {}.'.format(sheetnames[sheet_index], sheet_index))

	nrows = sheet.nrows
	ncols = sheet.ncols
	if ncols > MAX_N_COLS:
		print(f'В протоколе целых {ncols} столбцов! Это слишком много. Работаем с первыми {MAX_N_COLS}')
		ncols = MAX_N_COLS

	data = []
	max_nonempty_cells_number = 0
	max_nonempty_cells_index = 0
	for row_index in range(nrows):
		row = []
		nonempty_cells_number = 0
		for col_index in range(ncols):
			row.append(xlrd_cell2pair(sheet.cell(row_index,col_index), wb_xls.datemode))
			if sheet.cell_type(row_index,col_index) not in [xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK]:
				nonempty_cells_number += 1
		# row[0] = str(row_index) # + "(" + str(nonempty_cells_number) + ")"
		data.append(row)
		if nonempty_cells_number > max_nonempty_cells_number + 3:
			max_nonempty_cells_number = nonempty_cells_number
			max_nonempty_cells_index = row_index
	print('Размер листа: {} строк, {} столбцов.'.format(len(data), len(data[0]) if data else 0))

	if 'save_old_results' not in settings:
		settings['save_old_results'] = OLD_RESULTS_LEAVE_ALL
	if 'cumulative_splits' not in settings:
		settings['cumulative_splits'] = False
	if 'use_places_from_protocol' not in settings:
		settings['use_places_from_protocol'] = False
	if settings.get('status_for_empty') not in (models.STATUS_DNF, models.STATUS_DSQ, models.STATUS_DNS):
		settings['status_for_empty'] = models.STATUS_DNF
	if 'category_prefix' not in settings:
		settings['category_prefix'] = CATEGORY_PREFIX_NONE
	if 'genders' not in settings:
		settings['genders'] = None
	if 'categories' not in settings:
		settings['categories'] = [''] * nrows
	settings['show_gender_column'] = False
	settings['show_category_column'] = False

	if header_row is None:
		header_row = max_nonempty_cells_index
	print('Строка с заголовком таблицы: {}.'.format(header_row))
	if column_data_types is None:
		column_data_types = [CELL_DATA_PASS] * ncols
		column_split_values = [0] * ncols
		column_data_types, column_split_values = default_data_types(None, protocol, data, header_row, race.distance,
			column_data_types, column_split_values)
	if column_split_values is None:
		column_split_values = [0] * ncols
		column_split_distances = [None] * ncols
	else:
		column_split_distances = [models.Distance.objects.filter(pk=val).first() for val in column_split_values]
	print('Типы и заголовки столбцов:')
	for i, data_type in enumerate(column_data_types):
		print('{} ({}): {}'.format(i, data[header_row][i]['value'], CELL_DATA_CHOICES[data_type]), end=' ')
		if data_type == CELL_DATA_SPLIT:
			print(column_split_distances[i].name, end=' ') # pytype: disable=attribute-error
		print('')
	if rows_with_results is None:
		rows_with_results = [0] * nrows
		for i in range(header_row + 1, nrows):
			rows_with_results[i] = 1
	print('Обрабатываем диапазоны строк:')
	cur_segment_start = -1
	for i in range(nrows):
		if rows_with_results[i]:
			if cur_segment_start < 0:
				cur_segment_start = i
		else:
			if cur_segment_start >= 0:
				print('Строки {}-{}'.format(cur_segment_start, i - 1))
				cur_segment_start = -1
	if rows_with_results[-1]:
		print('Строки {}-{}'.format(cur_segment_start, nrows - 1))

	# Are column types OK?
	type2col, split2col, column_types_ok = process_column_types(None, race, column_data_types, column_split_values)
	# Are data in all important columns OK?
	column_numbers = [{'number': i} for i in range(ncols)]
	data, n_parse_errors, n_parse_warnings, column_numbers, settings = process_cell_values(
		race, rows_with_results, wb_xls.datemode, data, column_data_types, column_numbers, type2col, settings)
	print('Всего ошибок:', n_parse_errors)
	print('Всего предупреждений:', n_parse_warnings)
	ok_to_import = column_types_ok and (n_parse_errors == 0)
	if column_types_ok:
		if (settings['genders'] is None) and (type2col[CELL_DATA_GENDER] is None):
			if settings['try_get_gender_from_group'] and not (type2col[CELL_DATA_CATEGORY] is None):
				print('Пол в протоколе не указан. Пробуем извлечь его из столбца с группой...')
				settings['genders'] = [False] * nrows
				gender_guessed = 0
				gender_not_guessed = 0
				for i in range(nrows):
					if rows_with_results[i]:
						gender = results_util.string2gender(data[i][type2col[CELL_DATA_CATEGORY]]['value'])
						if gender == models.GENDER_UNKNOWN:
							gender_not_guessed += 1
						else:
							gender_guessed += 1
						settings['genders'][i] = (gender == results_util.GENDER_FEMALE)
				print(('Получилось понять пол у {} строк. Не получилось — у {} строк. ' +
					'Вы можете также передать как параметр массив settings["genders"]').format(gender_guessed, gender_not_guessed))
			elif settings['all_are_male']:
				print('Пол в протоколе не указан. Считаем всех мужчинами')
				settings['genders'] = [False] * nrows
			elif settings['all_are_female']:
				print('Пол в протоколе не указан. Считаем всех женщинами')
				settings['genders'] = [True] * nrows
			else:
				print('Ошибка: вы не указали пол спортсменов!')
				column_types_ok = False
		if (settings['categories'] is None) and (type2col[CELL_DATA_CATEGORY] is None):
			print('Ошибка: вы не указали группы спортсменов!')
			column_types_ok = False

	if not column_types_ok:
		return False
	for col_index in range(ncols):
		if 'errors' in column_numbers[col_index]:
			errors_total = column_numbers[col_index]['errors']
			errors_printed = 0
			print('Столбец {} ({}): {} ошибок. Первые из них:'.format(
				col_index, data[header_row][col_index]['value'], errors_total))
			for row_index in range(nrows):
				if 'error' in data[row_index][col_index]:
					print('({}, {}): Значение «{}», ошибка «{}»'.format(row_index, col_index,
						data[row_index][col_index]['value'], data[row_index][col_index]['error']))
					errors_printed += 1
					if (errors_printed == errors_limit) or (errors_printed == errors_total):
						break
		if 'warnings' in column_numbers[col_index]:
			warnings_total = column_numbers[col_index]['warnings']
			warnings_printed = 0
			print('Столбец {} ({}): {} предупреждений. Первые из них:'.format(
				col_index, data[header_row][col_index]['value'], warnings_total))
			for row_index in range(nrows):
				if 'warning' in data[row_index][col_index]:
					print('({}, {}): Значение «{}», ошибка «{}»'.format(row_index, col_index,
						data[row_index][col_index]['value'], data[row_index][col_index]['warning']))
					warnings_printed += 1
					if (warnings_printed == errors_limit) or (warnings_printed == warnings_total):
						break
	if (n_parse_errors == 0):
		if settings['try_load']:
			print('Все проверки пройдены, загружаем!')
			load_protocol(None, race, protocol, data, rows_with_results, column_data_types,
				column_split_values, type2col, settings)
		else:
			print('Все проверки пройдены, можно загружать!')
	return True

@views_common.group_required('admins')
def events_for_result_import(request):
	context = {}
	context['page_title'] = 'Забеги с протоколами и без результатов'

	context['races_for_klb'] = []
	races_for_klb = models.Race.objects.filter(
		Q(distance__distance_type=models.TYPE_MINUTES_RUN) | Q(distance__distance_type=models.TYPE_METERS, distance__length__gte=10000),
		event__start_date__year=models_klb.CUR_KLB_YEAR,
		was_checked_for_klb=False,
		loaded=models.RESULTS_LOADED).select_related('event', 'distance').order_by('event__start_date')[:50]
	for race in races_for_klb:
		if (race.get_klb_status() == models.KLB_STATUS_OK) and not race.klb_result_set.filter(result=None).exists():
			context['races_for_klb'].append(race)
			if len(context['races_for_klb']) >= 10:
				break

	protocols = models.Document.objects.filter(models.Q_IS_XLS_FILE,
		document_type__in=models.DOC_PROTOCOL_TYPES, event__isnull=False, is_processed=False)
	event_ids = set(protocols.values_list('event__id', flat=True))
	events_raw = models.Event.objects.filter(
		id__in=event_ids, start_date__lte=datetime.date.today() - datetime.timedelta(days=7)).prefetch_related(
		Prefetch('race_set',queryset=models.Race.objects.select_related(
			'distance').annotate(Count('result')).order_by('distance__distance_type', '-distance__length')),
		Prefetch('document_set',queryset=models.Document.objects.filter(models.Q_IS_XLS_FILE, document_type__in=models.DOC_PROTOCOL_TYPES))
		).order_by('-start_date')
	events = []
	for event in events_raw:
		if len(events) >= 50:
			break
		if event.race_set.filter(load_status=models.RESULTS_NOT_LOADED).exists() and event.document_set.exists():
			events.append(event)
	context['events'] = events
	countries = ('RU', 'BY', 'UA')
	context['large_races'] = models.Race.objects.filter(
		Q(event__city__region__country_id__in=countries) | Q(event__series__city__region__country_id__in=countries),
		loaded=models.RESULTS_NOT_LOADED).select_related('event', 'distance').order_by('-n_participants')[:20]

	return render(request, "editor/events_for_result_import.html", context)

@views_common.group_required('editors', 'admins')
def protocol_mark_processed(request, protocol_id):
	protocol = get_object_or_404(models.Document, document_type__in=models.DOC_PROTOCOL_TYPES, event__isnull=False, pk=protocol_id)
	event = protocol.event
	context, has_rights, target = views_common.check_rights(request, event=event)
	if not has_rights:
		return target
	if protocol.is_processed:
		messages.warning(request, 'Этот протокол уже был помечен как полностью обработанный.')
	else:
		protocol.mark_processed(request.user)
		messages.success(request, 'Протокол помечен как полностью обработанный. Отлично!')
	if protocol.id in event.get_xls_protocols().values_list('pk', flat=True):
		return redirect(event.get_protocol_details_url(protocol=protocol))
	return redirect(reverse('editor:klb_status') + '#protocols_not_loaded')
