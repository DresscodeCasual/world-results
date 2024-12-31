from results import models, results_util

import datetime
import decimal
import re
import xlrd

from typing import Dict, Optional, Tuple

distances_to_ignore = ['One Mile', '1mile', '1 mile', 'Road Walk km 10', 'Road Walk Km 20', 'Road Walk Km 30']
distances_to_stop = ['4x100m', '4x200m', '10k Race Walk', 'High Jump', ]

def to_ignore_distance(s: str, surface_type: int) -> bool:
	if s in distances_to_ignore:
		return True
	if surface_type == results_util.SURFACE_STADIUM and s in ('3000m', '3000 metres'):
		return True
	return False

def parse_length(s: str) -> Optional[int]:
	if s == 'Marathon':
		return 42195
	if s == 'Half Marathon':
		return 21098
	res = re.match(r'^(\d+) metres$', s)
	if res:
		return int(res.group(1))
	res = re.match(r'^Road Run km (\d+)$', s)
	if res:
		return int(res.group(1)) * 1000
	res = re.match(r'^(\d+)m$', s)
	if res:
		return int(res.group(1))
	return None

# Returns distance and surface type
def parse_distance(s: str, surface_type: int) -> Optional[models.Distance]:
	length = parse_length(s)
	if not length:
		return None
	distance = models.Distance.objects.filter(distance_type=models.TYPE_METERS, length=length).first()
	if not distance:
		return None
	if (surface_type == results_util.SURFACE_INDOOR) and (distance.id in results_util.DISTANCES_FOR_COUNTRY_INDOOR_RECORDS):
		return distance
	for dist_id, surf in results_util.DISTANCES_FOR_COUNTRY_OUTDOOR_RECORDS:
		if (distance.id == dist_id) and (surface_type == surf):
			return distance
	return None

def parse_gender_age_group(s: str) -> Optional[Tuple[int, models.Record_age_group]]:
	res = re.match(r'^\**(M|W) *(\d+)\+*$', s)
	if not res:
		return None
	gender = results_util.GENDER_MALE if (res.group(1) == 'M') else results_util.GENDER_FEMALE
	age_group = models.Record_age_group.objects.filter(age_group_type=models.RECORD_AGE_GROUP_TYPE_SENIOR, age_min=int(res.group(2))).first()
	if age_group:
		return gender, age_group
	return None

def parse_wind(s: str) -> Optional[decimal.Decimal]:
	if s == '+0.0':
		return decimal.Decimal(0)
	if s[0] == '+':
		s = s[1:]
	res = re.match(r'^-{0,1}\d{1,2}[\.,]\d{1}$', s) # (-?)ab,c
	if res:
		return decimal.Decimal(s.replace(',', '.'))
	return None

def parse_name(s: str) -> Tuple[str, str]:
	parts = s.split(' ')
	return parts[0], ' '.join(parts[1:])

# Returns centiseconds if parsed, None otherwise.
def parse_time(s: str, length: int) -> Optional[int]:
	res = re.match(r'^(\d{1,2})[:h](\d{2}):(\d{2})$', s) # hours:minutes:seconds
	if res and length > 3000:
		return 100 * (60 * (60 * int(res.group(1)) + int(res.group(2))) + int(res.group(3)))
	res = re.match(r'^(\d{1,2}):(\d{2})\.(\d{2})$', s) # minutes:seconds.centiseconds
	if res and length < 42000:
		return 100 * (60 * int(res.group(1)) + int(res.group(2))) + int(res.group(3))
	res = re.match(r'^(\d{1,2}):(\d{2})\.(\d{1})$', s) # minutes:seconds.deciseconds
	if res and length < 42000:
		return 10 * (10 * (60 * int(res.group(1)) + int(res.group(2))) + int(res.group(3)))
	res = re.match(r'^(\d{1})[:h](\d{2}):(\d{2})\.(\d{1})$', s) # hours:minutes:seconds.deciseconds
	if res and length > 3000:
		return 10 * (10 * (60 * (60 * int(res.group(1)) + int(res.group(2))) + int(res.group(3))) + int(res.group(4)))
	res = re.match(r'^(\d{1})[:h](\d{2}):(\d{2})\.(\d{2})$', s) # hours:minutes:seconds.centiseconds
	if res and length > 3000:
		return 100 * (60 * (60 * int(res.group(1)) + int(res.group(2))) + int(res.group(3))) + int(res.group(4))
	res = re.match(r'^(\d{2}):(\d{2})$', s) # minutes:seconds
	if res and length >= 5000:
		return 100 * (60 * int(res.group(1)) + int(res.group(2)))
	res = re.match(r'^(\d{1,2})\.(\d{2})$', s) # seconds.centiseconds
	if res and length < 800:
		return 100 * int(res.group(1)) + int(res.group(2))
	res = re.match(r'^(\d{1,2})\.(\d{1})$', s) # seconds.deciseconds
	if res and length < 800:
		return 10 * (10 * int(res.group(1)) + int(res.group(2)))
	return None

def parse_birthday_ddmmyy(s: str) -> Optional[datetime.date]:
	if len(s) != 6:
		return None
	try:
		return datetime.date(1900 + int(s[5:]), int(s[2:4]), int(s[:2]))
	except:
		return None

def parse_event_day_dd_mm_yy(dd: str, mm: str, yy: str) -> Optional[datetime.date]:
	year_suffix = int(yy)
	year = (1900 + year_suffix) if (year_suffix >= 60) else (2000 + year_suffix)
	try:
		return datetime.date(year, int(mm), int(dd))
	except:
		return None

# 17/09/16 or 5/23/2021
def parse_event_day_slashes(s: str) -> Optional[datetime.date]:
	items = s.split('/')
	if len(items) != 3:
		return None
	if len(items[2]) == 2:
		return parse_event_day_dd_mm_yy(items[0], items[1], items[2])
	if len(items[2]) == 4:
		try:
			return datetime.date(int(items[2]), int(items[0]), int(items[1]))
		except:
			return None
	return None

def parse_country(code: str, lname: Optional[str] = '') -> Optional[models.Country]:
	if len(code) != 3:
		return None
	if code == 'URS' and lname == 'Podkopayeva':
		return models.Country.objects.get(pk='RU')
	conv = models.Country_conversion.objects.filter(country_raw=code).first()
	if conv is None:
		return None
	return conv.country

def parse_event_city_country(s: str) -> Optional[Tuple[str, Optional[models.Country]]]:
	if s in ('', '(null)'):
		return '', None
	if s == 'Monaco':
		s = 'Monaco, MCO'
	parts = s.split(', ')
	if len(parts) != 2:
		return None
	country = parse_country(parts[1])
	if not country:
		return None
	return (parts[0], country)

def parse_world_records(filename: str, surface_type: int):
	n_parsed = 0
	n_records_still_ok = n_new_records = n_worse_records = 0
	cur_records = {}
	for record in models.Record_result.objects.filter(is_world_record=True, surface_type=surface_type):
		cur_records[(record.gender, record.age_group_id, record.distance_id, record.surface_type)] = record

	with open(filename, 'r', encoding='UTF-8') as file:
		lines = [line.strip() for line in file]
	distance = None
	i = 0
	while i < len(lines):
		if lines[i] in distances_to_stop:
			break
		if to_ignore_distance(lines[i], surface_type=surface_type):
			i += 1
			while parse_distance(lines[i], surface_type=surface_type) is None:
				i += 1
		if lines[i].startswith('WMA RECORDS'):
			i += 1
		new_distance = parse_distance(lines[i], surface_type=surface_type)
		if new_distance:
			distance = new_distance
			i += 1
		else:
			if distance is None: # So we just started and here must be a distance
				print(f'Line {i}: "{lines[i]}": Could not parse distance')
				return
			# Otherwise this must be just the next age group
		if i == 1 and lines[i].lower() == 'wind':
			i += 1
		gender_age_group = parse_gender_age_group(lines[i])
		if gender_age_group is None:
			print(f'Line {i}: "{lines[i]}": Could not parse gender and age group')
			return
		gender, age_group = gender_age_group
		i += 1
		if lines[i] in ['a', 'b']: # So there are several results with this time
			i += 1
		centiseconds = parse_time(lines[i], distance.length)
		if centiseconds is None:
			print(f'Line {i}: "{lines[i]}": Could not parse result')
			return
		i += 1
		wind = None
		if (surface_type == results_util.SURFACE_STADIUM) and (distance.length <= 200):
			wind = parse_wind(lines[i])
			if wind is not None:
				i += 1
		fname, lname = parse_name(lines[i])
		i += 1
		runner_country = parse_country(lines[i], lname=lname)
		if runner_country is None:
			print(f'Line {i}: "{lines[i]}": Could not parse country')
			return
		i += 1
		try:
			age = int(lines[i])
		except:
			print(f'Line {i}: "{lines[i]}": Could not parse age')
			return
		i += 1
		event_day = parse_event_day_slashes(lines[i])
		if event_day is None:
			print(f'Line {i}: "{lines[i]}": Could not parse event_day')
			return
		i += 1
		event_city_country = lines[i]
		parts = parse_event_city_country(lines[i])
		if parts is None:
			print(f'Line {i}: "{lines[i]}": Could not parse event city and country')
			return
		event_city, event_country = parts
		i += 1

		n_parsed += 1
		cur_record = cur_records.get((gender, age_group.id, distance.id, surface_type))
		if cur_record:
			if centiseconds == cur_record.value:
				n_records_still_ok += 1
				continue
			if centiseconds > cur_record.value:
				n_worse_records += 1
				print(f'{gender}, {age_group}, {distance}, {surface_type}: existing record {cur_record} is better than new one {centiseconds}')
				continue
			if cur_record.ignore_for_country_records:
				cur_record.delete()
			else:
				cur_record.is_world_record = False
				cur_record.save()
		n_new_records += 1
		new_record = models.Record_result.objects.create(
				gender=gender,
				age_group=age_group,
				age_on_event_date=age,
				is_age_on_event_date_known=True,
				distance=distance,
				surface_type=surface_type,
				is_world_record=True,
				ignore_for_country_records=True,
				fname=fname,
				lname=lname,
				value=centiseconds,
				runner_country=runner_country,
				event_city=event_city,
				event_country=event_country,
				date=event_day,
				is_date_known=True,
				timing=models.TIMING_ELECTRONIC,
				created_by=models.USER_ROBOT_CONNECTOR,
			)
	print(f'Done! Parsed records: {n_parsed}, n_records_still_ok: {n_records_still_ok}, n_new_records: {n_new_records}, n_worse_records: {n_worse_records}')

def get_europe_records_dict() -> Dict[Tuple[int, int, int, int], models.Record_result]:
	res = {}
	for r in models.Record_result.objects.filter(is_europe_record=True):
		res[(r.gender, r.age_group_id, r.distance_id, r.surface_type)] = r
	return res

def parse_name_country(s: str) -> Optional[Tuple[str, str, models.Country]]:
	parts = s.strip().split(',')
	if len(parts) != 2:
		return None
	name_parts = parts[0].strip().split(' ')
	if len(name_parts) < 2:
		return None
	lname = name_parts[-1]
	fname = ' '.join(name_parts[:-1])
	country = parse_country(parts[1].strip(), lname)
	if not country:
		return None
	return lname, fname, country

def parse_date(s: str) -> Optional[datetime.date]:
	res = re.match(r'^(\d{2})-(\d{2})-(\d{4})$', s)
	if res:
		try:
			return datetime.date(int(res.group(3)), int(res.group(2)), int(res.group(1)))
		except:
			return None
	return None

def good_value(cell):
	return cell.value.replace('\xa0', '').strip()

def parse_european_records(filename: str):
	n_parsed = 0
	n_records_still_ok = n_new_records = n_worse_records = 0
	cur_records = {}
	for record in models.Record_result.objects.filter(is_europe_record=True):
		cur_records[(record.gender, record.age_group_id, record.distance_id, record.surface_type)] = record

	wb_xls = xlrd.open_workbook(filename)
	for sheet_name, surface_type in (
		('outdoor', results_util.SURFACE_STADIUM),
		('indoor', results_util.SURFACE_INDOOR),
		('non-stadia', results_util.SURFACE_ROAD),
	):
		sheet = wb_xls.sheet_by_name(sheet_name)
		distance = None
		i = 0
		while i < sheet.nrows:
			cell = sheet.cell(i, 0)
			value = good_value(cell)
			if cell.ctype == xlrd.XL_CELL_EMPTY or value.startswith('EVAA ') or (value in ('Age', 'Group', )):
				i += 1
				continue
			if value in distances_to_stop:
				break
			if to_ignore_distance(value, surface_type=surface_type):
				i += 1
				while i < sheet.nrows and parse_distance(good_value(sheet.cell(i, 0)), surface_type=surface_type) is None:
					i += 1
				continue
			new_distance = parse_distance(value, surface_type=surface_type)
			if new_distance:
				distance = new_distance
				i += 1
				continue
			if distance is None: # So we just started and here must be a distance
				print(f'Line {i}: "{value}": Could not parse distance')
				return
			# Otherwise this must be just the next age group
			gender_age_group = parse_gender_age_group(value)
			if gender_age_group is None:
				print(f'Line {i}: "{value}": Could not parse gender and age group')
				return
			gender, age_group = gender_age_group

			wind = None
			if (surface_type == results_util.SURFACE_STADIUM) and (distance.length <= 200) and (sheet.cell(i, 1).ctype != xlrd.XL_CELL_EMPTY):
				wind = parse_wind(good_value(sheet.cell(i, 1)))
			centiseconds = parse_time(good_value(sheet.cell(i, 2)), distance.length)
			if centiseconds is None:
				print(f'Line {i}: "{good_value(sheet.cell(i, 2))}": Could not parse result')
				return

			name_country = parse_name_country(good_value(sheet.cell(i, 3)))
			if name_country is None:
				print(f'Line {i}: "{good_value(sheet.cell(i, 3))}": Could not parse name and country')
				return
			lname, fname, runner_country = name_country

			birthday = parse_date(good_value(sheet.cell(i, 4)))
			if birthday is None:
				print(f'Line {i}: "{good_value(sheet.cell(i, 4))}": Could not parse birthday')
				return
			if not (1900 <= birthday.year <= datetime.date.today().year):
				print(f'Line {i}: "{good_value(sheet.cell(i, 4))}": Incorrect year')
				return

			parts = parse_event_city_country(good_value(sheet.cell(i, 5)))
			if parts is None:
				print(f'Line {i}: "{good_value(sheet.cell(i, 5))}": Could not parse event city and country')
				return
			event_city, event_country = parts

			event_day = parse_date(good_value(sheet.cell(i, 6)))
			if event_day is None:
				print(f'Line {i}: "{good_value(sheet.cell(i, 6))}": Could not parse event_day')
				return
			age_on_event_date = results_util.get_age_on_date(event_day, birthday)
			if not (age_group.age_min <= age_on_event_date <= age_group.age_min + 4):
				print(f'Line {i}: "{good_value(sheet.cell(i, 6))}": age group is {age_group.age_min} but age on event date is {age_on_event_date}')
				return

			n_parsed += 1
			cur_record = cur_records.get((gender, age_group.id, distance.id, surface_type))
			if cur_record:
				if centiseconds == cur_record.value:
					n_records_still_ok += 1
					i += 1
					continue
				if centiseconds > cur_record.value:
					n_worse_records += 1
					print(f'{gender}, {age_group}, {distance}, {surface_type}: existing record {cur_record} is better than new one {centiseconds}')
					i += 1
					continue
				if cur_record.ignore_for_country_records:
					cur_record.delete()
				else: # So this is the result from Russia or Belarus. We don't delete it then.
					cur_record.is_europe_record = False
					cur_record.save()
			n_new_records += 1
			new_record = models.Record_result.objects.create(
					gender=gender,
					age_group=age_group,
					age_on_event_date=age_on_event_date,
					is_age_on_event_date_known=True,
					distance=distance,
					surface_type=surface_type,
					is_europe_record=True,
					ignore_for_country_records=True,
					fname=fname,
					lname=lname,
					value=centiseconds,
					runner_country=runner_country,
					event_city=event_city,
					event_country=event_country,
					date=event_day,
					is_date_known=True,
					timing=models.TIMING_ELECTRONIC,
					created_by=models.USER_ROBOT_CONNECTOR,
				)
			print(new_record)
			i += 1
	print(f'Done! Parsed records: {n_parsed}, n_records_still_ok: {n_records_still_ok}, n_new_records: {n_new_records}, n_worse_records: {n_worse_records}')
