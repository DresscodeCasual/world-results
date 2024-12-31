# By Sergey Salnikov https://vk.com/salnikov_s
from collections import namedtuple

import datetime
import re
import xlsxwriter

def get(structure, path):
	"""Достаёт из глубокой структуры поле по задаваемому строкой пути. При
	отсутствии возвращает None.

	>>> get({"foo": [{"bar": 42}]}, "foo 0 bar")
	42
	"""
	for key in path.split():
		try:
			try:
				structure = structure[int(key)]
			except ValueError:
				structure = structure[key]
		except (IndexError, KeyError):
			return None
	return structure

def field_present(results, field):
	for record in results:
		if get(record, field.path) is not None:
			return True
	return False

Field = namedtuple("Field", "header path")

class Int(Field):
	width = 6

	ABSURDLY_HIGH = 900000

	def write(self, worksheet, row, col, record, _time_format):
		try:
			x = int(get(record, self.path))
			# У нефинишировавших на сервере указано «999999 место».
			if x > 0 and x < self.ABSURDLY_HIGH:
				worksheet.write(row, col, x)
		except (TypeError, ValueError):
			pass

class Str(Field):
	width = 15

	def write(self, worksheet, row, col, record, _time_format):
		value = get(record, self.path)
		# На сервере довольно много бессмысленных строк типа "," и
		# "--". Скорее всего, они не несут полезной информации.
		if value is not None and not re.match(r'\W*$', str(value)):
			if (self.header == "Статус") and (value == "CONF") and (get(record, "racerHasFinished") == False):
				# Ugly hack for strange athlinks rows with distance different from given,
				# e.g. Камчатный at https://www.athlinks.com/event/200468/results/Event/852444/Course/1575836/Results
				value = "DNF"
			# В поле Locality обычно пишут клуб и город через запятую. В названии клуба могут быть запятые
			if self.header == "Город":
				if ',' in value:
					value = value.split(',')[-1].strip()
				else:
					value = ''
			if self.header == "Клуб":
				if ',' in value:
					value = ', '.join(x.strip() for x in value.split(',')[:-1])
			worksheet.write(row, col, value)

class SmallStr(Str):
	width = 6

class MediumStr(Str):
	width = 9

class Time(Field):
	width = 9

	EPSILON = datetime.timedelta(seconds=1)

	def write(self, worksheet, row, col, record, time_format):
		try:
			x = get(record, self.path)
			t = datetime.timedelta(milliseconds=x["timeInMillis"])
			# Отсутствующее время на сервере сохранено как -1 мс. Но
			# если вдруг иногда -1, а иногда и 0 — то это, наверно,
			# тоже не надо показывать.
			if t > self.EPSILON:
				worksheet.write_datetime(row, col, t, time_format)
		except (TypeError, KeyError):
			return None

def get_fields(results):
	fields = [
		Str("BIB", "bib"),
		Int("entryId", "entryId"),
		Str("Фамилия", "lastName"),
		Str("Имя", "firstName"),
		Int("Возраст", "age"),
		Str("Город", "locality"),
		Str("Клуб", "locality"),
		Str("Регион", "region"),
		SmallStr("Страна", "country"),
		Int("Место в абсолюте", "intervals 0 brackets 0 rank"),
		Int("Всего участников", "intervals 0 brackets 0 totalAthletes"),
		SmallStr("Пол", "gender"),
		Int("Место среди пола", "intervals 0 brackets 1 rank"),
		Int("Участников в нём", "intervals 0 brackets 1 totalAthletes"),
		MediumStr("Группа", "intervals 0 brackets 2 bracketName"),
		Int("Место в группе", "intervals 0 brackets 2 rank"),
		Int("Участников в ней", "intervals 0 brackets 2 totalAthletes"),
		Str("Статус", "entryStatus"),
		Time("Чистое время", "intervals 0 chipTime"),
		Time("Грязное время", "intervals 0 gunTime"),
	]
	intervals = get(results, "0 intervals")
	if intervals:
		for i, interval in enumerate(intervals):
			intervalName = get(interval, "intervalName")
			intervalFull = get(interval, "intervalFull")
			if intervalName and not intervalFull:
				fields.append(Time(intervalName, f"intervals {i} chipTime"))
	return [field for field in fields if field_present(results, field)]

def write(output, courses):
	workbook = xlsxwriter.Workbook(output)
	for course in courses:
		# 31 знак — ограничение на имя листа в формате xlsx
		name = course.name[:31]
		for symbol in '[]:*?/\\':
			name = name.replace(symbol, '')
		worksheet = workbook.add_worksheet(name)
		bold = workbook.add_format({"bold": True})
		fields = get_fields(course.results)
		for col_number, field in enumerate(fields):
			worksheet.set_column(col_number, col_number, field.width)
			worksheet.write(0, col_number, field.header, bold)
		time_format = workbook.add_format({"num_format": "hh:mm:ss", "align": "left"})
		for row_number, record in enumerate(course.results):
			for col_number, field in enumerate(fields):
				field.write(worksheet, row_number + 1, col_number, record, time_format)
	workbook.close()
