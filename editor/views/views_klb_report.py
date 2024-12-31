"""
Функции для создания отчетов.
Состав и форма отчетов задаются конфигурационными файлами в CONFIG_FILE_DIR

Запускать предполагается двумя способами:

1. По нажатии соответствующей кнопки на сайте (должна вызываться функция set_wrapper).
2. Для тестирования: python manage.py xlsxrep (см. editor/management/commands/xlsxrep.py)

Todo
0. Check and correct codestyle
1. Заменить assert'ы на нормальную обработку ошибок
3. Подумать об оптимизации SQL-запросов с помощью метода QuerySet.only()
4. Перевести комментарии на английский.
"""

import builtins
import codecs
import configparser
import logging

from django.core.management.base import CommandError
from django.db.models import F, Q, Value, CharField, Count
from django.db.models.query import Prefetch, QuerySet
from django.db.models.manager import Manager
from django.shortcuts import redirect
from django.contrib import messages
from django.conf import settings

import datetime
import time
from typing import List, Optional

from operator import itemgetter
import os
import glob
import operator
import builtins
from functools import reduce


import itertools
import re

import xlsxwriter

from results import models, models_klb
from .views_common import group_required

# CONFIG_FILE_DIR = '/home/admin/parkrun/config/klb_reports/'
CONFIG_FILE_DIR = os.path.join(settings.BASE_DIR, 'config/klb_reports/')

klb_year = -1  # Year for which the report will be generated. Will be set in function mk_table_set

RE_NUMBER_OR_VARIABLE = re.compile("^[a-zA-Z_0-9.]+$")

XLSX_TYPES = {'str', 'int', 'float', None}  # int and float are mapped to the same numerical xlsx type
OUTPUT_DIR_RELATIVE_PATH = 'dj_media/reports/'

log = logging.getLogger(__name__)


def generate_datetime_now_string():
	now = datetime.datetime.now()
	# return now.strftime("%Y-%m-%d %H:%M:%S %Z") # with timezone
	return now.strftime("%Y-%m-%d %H:%M:%S")


#########################
# For config processing #
#########################

NAME_OF_MAIN_CONFIG = 'main.conf'

GLOBAL_SECT = '_global'	# ascii chars only!
DEFAULT_SECT = '_default'  # ascii chars only!
# Do not use standard section [DEFAULT] becouse
# we need defaults only for column sections but not for GLOBAL_SECT


ALL_ROLES = {'editor', 'client', 'special'}	 # ? May be change "client" to "user" or smth else?
# CURRENT_ROLE = 'client'


class ReportGeneratorError(CommandError):
	pass

class NotEqualValuesError(ReportGeneratorError):
	def __init__(self, sheet_name, column_name, id_, values):
		self.sheet_name = sheet_name
		self.column_name = column_name
		self.id_ = id_
		self.values = values

	def __str__(self):
		return 'Отличаются значения value и value2 на листе "{}", в столбце "{}", id={}. Значения: "{}"'.format(
			self.sheet_name,
			self.column_name,
			str(self.id_),
			self.values
		)


class ReadConfigError(ReportGeneratorError):
	pass


##############################################################################
# Properties specification for read_table_config() and read_main_config()
#
# Properties specification is given in 2 dictionaries.
# Values are pairs (type of property, default value).
# If the default value is None, this property must be given in the config file
# Excepiton: main_model and row_generator are mutually exclusive:
#   must be given one and only one of them.

# For read_table_config()
global_properties_info = {  # Свойства раздела [_global]
		'main_model': (str, ''),
		'row_generator': (str, ''),
		'fields_for_select_related': (str, ''),
		'only_fields': (str, ''),
		'filter': (str, '{}'),
		'process_by_month': (str, ''),
		'exclude': (str, '{}'),
		'order_by': (str, ''),
		'sheet_name': (str, ''),  # ignored for csv-output
		'header.f.text_wrap': (bool, True),
		'header.f.bold': (bool, True),
		'header.f.align': (str, 'center'),
		'header.f.*': (None, ''),
		'id_for_statistics': (str, None)
	}

# For read_table_config()
column_properties_info = {  # Свойства разделов описания колонок
		'value': (str, None),
		'value2': (str, ''),
		'eval': (str, ''),
		'eval2': (str, ''),
		'comment': (str, ''),
#		'wid.t!h$a%z*zz+bb': (int, -1),
		'may_be_none': (bool, False),
		'access': (str, 'all'),
		# 'auto_increment': (int, 0),
		'output_for_none': (str, ''),
		'f.*': (None, ''),
		'f.align': (str, ''),  # will be set depend of xlsx.type
		'f.text_wrap': (bool, False),
		'f.num_format': (str, ''),
		'xlsx.type': (str, 'str'),  # may be 'num' (obsoleted), int, float, 'str' (my be 'bool' ?)
							  # this is type for xlsx
		'width.equal': (float, -1),
		'width.min': (float, -1),
		'width.max': (float, -1),
		'width.auto': (bool, ''), # will be set = not f.text.wrap
		'width.a': (float, 1.1),
		'width.b': (float, 0.1),
		'width.int_part_plus': (float, -1.0),  # if < 0, use the total length. not the length of floor(value)
		'used_fields': (str, ''),  # todo: are needed for autogenerating fileld list for only()
			# if value contains a function call
}


main_config_properties_info = {
	'general' : {
		'filetype': (str, None),
		'table_configs': (str, '*.ini'),
		'output_file_prefix': (str, ''),
		'output_file_dt_format': (str, '-%y%m%d-%H%M'),
		'show_datetime': (bool, True),
		'show_debug_info_on_columns': (bool, False),
		'role': (str, None),
		'reports_for_editors_and_clients': (bool, None),
		'year': (int, models_klb.CUR_KLB_YEAR),
		'sleep': (int, 0)
	},
	'xlsx.workbook.options' : {
		'xlsx.constant_memory': (bool, True),
		'xlsx.default_date_format': (str, 'dd/mm/yy'),
		'xlsx.*' : (None, '')
	},
	'xlsx.workbook.properties' : {
		'xlsx.*' : (str, '')
	}
}


# for read_main_config

# End of properties specification for read_table_config()  #
############################################################

def width_for_column(column_data, width_of_data):
	if column_data['width.auto']:
		if column_data['width.int_part_plus'] >= 0:
			# assert type_ == 'float'
			data_width = width_of_data[1] + column_data['width.int_part_plus']
		else:
			data_width = width_of_data[0]
		w = column_data['width.a'] * data_width + column_data['width.b']

		width_min = column_data['width.min']
		width_max = column_data['width.max']
		w = max(w, width_min)
		if width_max >= 0:
			w = min(w, width_max)
		return w
	else:
		return column_data['width.equal']


def process_section(
		config,					   # : ConfigParser.SafeConfigParser
		section,
		properties_info,
		check_mandatory=True,
		defaults=None
	):

		"""
		Helper function for reading config files.

		It is used both by read_table_config() and read_main_config()
		"""

		section_data = {k: v[1] for k, v in list(properties_info.items())}
		if defaults:
			section_data.update(defaults)

		section_items = config.items(section)
		assert isinstance(section_items, list)
		log.debug("s_items: " + str(section_items))
		###
		### Todo:
		### переделать логику
		### если есть !, сначала проверяем, нет ли типа для имени до него. Если есть - ошибка
		### (или, как вариант, требовать, чтобы типы совпадали)
		###
		for property_name, property_value in section_items:
			# log.debug(str(property_name) +" " +  str(property_value))
			property_type = None
			if property_name in properties_info:
				property_type = properties_info[property_name][0]
			elif '.' in property_name:
				property_prefix = property_name.rsplit('.', 1)[-2] + ".*" 
				if property_prefix in properties_info:
					# log.debug('property_prefix in properties_info:')
					property_type = properties_info[property_prefix][0]
					# log.debug("p_prefix=" + property_prefix)
					# log.debug('p_type=' + str(property_type))
					if property_type is None:
						if property_name.count('!') != 1:
							log.critical('Unknown type of property "' + property_name + '" in section "' + section + "'")
							raise ReadConfigError
						property_wo_type, property_type_str = property_name.split('!')
						assert property_wo_type not in dict(section_items)
						property_type = getattr(builtins, property_type_str)
					else:
						assert '!' not in property_name
			if  property_type is None:
#****				print '+++', '['+ property_name.rsplit('.', 1)[-2] + ".*]"
				log.critical('Unknown property name "' + property_name + '" in section "' + section + "' or it's type")
				raise ReadConfigError
			if property_type == str:
				section_data[property_name] = str(property_value)
			elif property_type == bool:
				tmp = str(property_value)
				if tmp not in ('yes', 'no'):
					log.critical(
						"Boolean property must be yes or no. (Property {} in section {})".format(
							property_name,
							section
						)
					)
					raise ReadConfigError
				section_data[property_name] = (tmp == 'yes')
			else:
				section_data[property_name] = property_type(property_value)

		if check_mandatory:
			for p_name, p_value in list(section_data.items()):
				if p_value is None:
					log.critical('Mandatory property "' + p_name + '" not found in section "' + section + '"')
					raise ReadConfigError

		'''
		if section == 'Команда':
			print '-- Команда --'
			print type(section)
			print section_data
		'''
		return section_data

# /def process_section(...)

def read_main_config(file_name, property_info_dict):  # -> dict
	try:
		with open(file_name, 'rt') as _:
			pass
	except IOError:
		log.critical("Config file '" + file_name + "' not found")
		raise ReadConfigError

	conf_data = []
	config = configparser.SafeConfigParser(inline_comment_prefixes=(';',))
	config.read(file_name)
	section_list = config.sections()
	assert len(section_list) >= 1


	# print section_list

	for section in section_list:
		conf_data.append((
			str(section),
			process_section(
				config,
				section,
				property_info_dict[section]
			)
		))

	conf_data = dict(conf_data)


	# Checking correctness of config data
	assert conf_data['general']['filetype'] in ('xlsx', 'csv')

	return conf_data


def read_table_config(file_name):
	"""
	Read config file for one table (one xlsx-sheet or one csv-filel)
	"""

	def global_properties_checker(p_dict):
		assert isinstance(p_dict, dict)
		assert (p_dict['main_model'] == '') != (p_dict['row_generator'] == '')
#		assert p_dict['show_datetime'] in ('yes', 'no')
		assert RE_NUMBER_OR_VARIABLE.match(p_dict['id_for_statistics'])


	def column_properties_checker(p_dict):
		assert isinstance(p_dict, dict)
		if p_dict['eval2']:
			assert p_dict['value2'], 'eval2 may not be given without value2'
		assert p_dict['xlsx.type'] in XLSX_TYPES

		assert p_dict['width.int_part_plus'] < 0 or p_dict['xlsx.type'] == 'float'

		if p_dict['width.auto'] is True:
			assert p_dict['width.equal'] < 0
		elif p_dict['width.auto'] is False:
			assert p_dict['width.min'] < 0
			assert p_dict['width.max'] < 0
			assert p_dict['width.int_part_plus'] < 0
		else:
			assert p_dict['width.auto'] == ''

		assert p_dict['width.min'] < 0 or p_dict['width.max'] < 0 or \
			p_dict['width.min'] <= p_dict['width.max']

		assert p_dict['width.a'] > 0 and p_dict['width.b'] > -0.1 



	conf_data = []
	config = configparser.SafeConfigParser(inline_comment_prefixes=(';',))
	config.read(file_name)
	section_list = config.sections()
#	print section_list
	assert len(section_list) > 1

	########
	# Раздел [_global] (GLOBAL_SECT == '_global')
	section = section_list[0]
	assert section == GLOBAL_SECT
	conf_data.append((
		str(GLOBAL_SECT),
		process_section(config, GLOBAL_SECT, global_properties_info)
	))

	global_properties_checker(conf_data[0][1])

	default_data = None
	start_idx = 1
	if section_list[start_idx] == DEFAULT_SECT:
		start_idx += 1
		default_data = process_section(config, DEFAULT_SECT, column_properties_info, False)
		conf_data.append((
			str(DEFAULT_SECT),
			default_data
		))

	assert start_idx < len(section_list)  # must be one column at least
	for section in section_list[start_idx:]:
		conf_data.append((
			str(section),
			process_section(config, section, column_properties_info, defaults=default_data)
		))
		column_properties_checker(conf_data[-1][1])

	return conf_data

# /def read_table_config(file_name):

# End of config processing #
############################


def is_there_column_property(property_, columns):
	assert property_ in column_properties_info
	try:
		return any(c_val[property_] != column_properties_info[property_][1] for _, c_val in columns)
	except KeyError:
		print(("p:", property_))
		print(("c:", columns))
		raise

###########################
# Functions to get values #
###########################
# Todo: may be these functions should be moved to a special module for them.

def wich_group(
		team,
		small_team_limit=str(models_klb.get_small_team_limit(klb_year)),
		medium_team_limit=str(models_klb.get_medium_team_limit(klb_year))
		):
		if team.place is None:
			assert team.place_medium_teams is None and team.place_small_teams is None
			log.critical('team.place may be None only for individual participants. They must be excluded')
			raise ReportGeneratorError
		elif team.place_small_teams is not None:
			assert team.place_medium_teams is None and team.place is not None
			return 'до ' + small_team_limit
		elif team.place_medium_teams is not None:
			assert team.place_small_teams is None and team.place is not None
			return 'до ' + medium_team_limit
		else:
			return ''


def place_in_group(team):	# Not used now
		return team.place_medium_teams or team.place_small_teams or team.place


def get_number_of_klb_results_of_race(race):
	# Very inefficient. Not for production environment.
	return len(race.klb_result_set.all())


def strCityCountry_without_nbsp(race):
	return race.event.strCityCountry(with_nbsp=False)

# End of Functions to get values
##################################


###############################################
# Functions to get iterable of data base rows #
###############################################
# Todo: may be these functions should be moved to a special module for them.


def test_rows_generator():
	return list(models.Klb_team.objects.select_related('club__country', 'club__city__region').filter(year=2018).exclude(club_id=75).order_by('-score'))


def get_events_not_in_klb():  # -> QuerySet
	# This is a partial copy-paste from
	# results.views.views_klb.events_not_in_klb().
	# Todo: place the common code in one function somewhere
	return models.Event.objects.filter(start_date__year__range=models_klb.match_year_range(klb_year), invisible=False, cancelled=False, not_in_klb=True).prefetch_related(
		Prefetch('race_set', queryset=models.Race.objects.select_related('distance').order_by('distance__distance_type', '-distance__length'))
	).select_related('series__city__region__country', 'city__region__country').annotate(reason=F('comment'))


def get_events_added_late():  # -> QuerySet
		# This is a partial copy-paste from
		# results.views.views_klb.events_not_in_klb().
		# Todo: place common the code in one function somewhere
		countries = ('BY', 'RU', 'UA')

		possible_match_event_ids = models.Race.objects.filter(
				Q(distance__distance_type=models.TYPE_MINUTES_RUN)
				| (
						Q(distance__distance_type=models.TYPE_METERS,
								distance__length__gte=models_klb.get_min_distance_for_score(klb_year),
								distance__length__lte=models_klb.get_max_distance_for_score(klb_year),
						)
						& ( Q(distance_real__length__gte=models_klb.get_min_distance_for_bonus(klb_year)) | Q(distance_real=None) )
				),
				event__start_date__year__range=models_klb.match_year_range(klb_year),
		).values_list('event_id', flat=True).distinct()

		# For 2023
		event_with_regulation_ids = set(models.Document.objects.filter(
			document_type__in=(models.DOC_TYPE_REGULATION, models.DOC_TYPE_REGULATION_STAMPED, models.DOC_TYPE_ANNOUNCEMENT)).exclude(
			url_source='').exclude(event=None).values_list('event_id', flat=True))
		return models.Event.objects.filter(
			Q(city__region__country_id__in=countries) | Q(series__city__region__country_id__in=countries),
			invisible=False,
			cancelled=False,
			pk__in=possible_match_event_ids - event_with_regulation_ids,
			start_date__year=klb_year,
			start_date__lte=F('date_added_to_calendar'),
		).annotate(reason=Value('Добавлен в календарь после самого события', output_field=CharField()))


def get_events_not_in_match():  # -> list[subclass of Model]
	# Todo: this code was written for django 1.9.
	# In django 1.11+ it may be done more efficiently
	# with sql operation UNION.
	events_not_in_klb = get_events_not_in_klb()
	events_added_late = get_events_added_late()
	return sorted(list(events_not_in_klb) + list(events_added_late), key=lambda x: x.start_date, reverse=True)

# get_events_not_in_match = partial(results.views.views_klb.get_events_not_in_klb, klb_year)

def get_races_not_in_match():   # -> list[models.Race]
	races_not_in_match = []
	for event in get_events_not_in_match():
		# May be not the most efficint method...
		races_not_in_match.extend(
			list(
				event.race_set.annotate(
					reason=Value(event.reason, output_field=CharField())
				)
			)
		)
	races_not_in_match.sort(key=lambda x: x.id)
	races_not_in_match.sort(key=lambda x: x.distance.length, reverse=True)
	races_not_in_match.sort(key=lambda x: x.distance.distance_type)
	races_not_in_match.sort(key=lambda x: x.event.name)
	races_not_in_match.sort(key=lambda x: x.event.start_date)
	return races_not_in_match


def get_races_in_klb():
	# This is a partial copy-paste from
	# editor.views.views_series.events_in_klb().
	# Todo: place the common code in one function somewhere
	race_ids = set(models.Klb_result.objects.filter(race__event__start_date__year__range=models_klb.match_year_range(klb_year)).values_list('race_id', flat=True))
	races = models.Race.objects.filter(pk__in=race_ids)
	return races.select_related(
		'event__series__city__region__country',
		'event__city__region__country',
		'event__series__country',
		'distance'
		).order_by(
			'-event__start_date',
			'event__name',
			'event_id',
			'distance__distance_type',
			'-distance__length',
			'precise_name'
		).annotate(num_results=Count('klb_result'))

#		.prefetch_related(Prefetch('result_set'))\


# End of Functions to get iterable of data base rows #
######################################################


class Row_writer:
	row_no: int = 0
	def current_row(self):
		return self.row_no

class CSV_row_writer(Row_writer):

	def __init__(self, out_stream):
		self.out_stream = out_stream
		self.row_no = 0

	def start_calculate_widths(self):
		pass

	def write(self, data_list, types_list=None, fmt_list=None):
		# types_list and fmt_lst are not used here
		self.out_stream.write('\t'.join(data_list) + '\n')
		self.row_no += 1


class XLSX_row_writer(Row_writer):
	types_list: Optional[List[Optional[str]]] = None
	widths: Optional[List[List[int]]] = None

	def __init__(self, worksheet):
		self.worksheet = worksheet
		self.row_no = 0
		self.n_of_fields = None
		self.in_widths_calculation = False


	def start_calculate_widths(self):
		assert self.in_widths_calculation == False
		self.in_widths_calculation = True


	def stop_calculate_widths(self):
		assert self.in_widths_calculation == True
		self.in_widths_calculation = False
		del self.widths


	def write(self, data_list, types_list=None, fmt_list=None):
		length = len(data_list)
		if not isinstance(types_list, list):
			assert types_list in XLSX_TYPES
			types_list = [types_list] * length
		else:
			if len(types_list) != length:
				print(length)
				print(types_list)
				print(data_list)
				exit(0)
			assert len(types_list) == length

		if self.in_widths_calculation:
			if self.n_of_fields is None:
				self.n_of_fields = length
				self.widths = [[0, 0] if t == 'float' else [0] for t in types_list]
				self.types_list = types_list
			else:
				if self.n_of_fields != length:
					log.critical(str( self.n_of_fields) + " " + str(length))
					log.critical(str(data_list))
					log.critical("Internal error: number of columns must be constant")
					raise ReportGeneratorError
				if self.types_list != types_list:
					log.critical("Internal error: types of columns must be always the same")
					raise ReportGeneratorError


			# Widths for autofit
			for val, type_, width in zip(data_list, types_list, self.widths):
				total_len = len(val)
				width[0] = max(width[0], total_len)
				if type_ == 'float':
					if '.' not in val:
						len_before_point = total_len
					else:
						assert val.count('.') == 1
						len_before_point = val.index('.')

					width[1] = max(width[1], len_before_point)

		if not isinstance(fmt_list, list):
			fmt_list = [fmt_list] * length
		else:
			assert len(fmt_list) == length
		for col_no, item, type_, fmt  in zip(itertools.count(), data_list, types_list, fmt_list):
			assert type(item) in (str, str)
			if item != '':
#				if type_ == 'num':  # deprecated
#					item = float(item) if '.' in item else int(item)
				if type_ == 'int':
					item = int(item)
				elif type_ == 'float':
					item = float(item)
			if fmt is None:
				arg_list = [self.row_no, col_no, item]
			else:
				arg_list = [self.row_no, col_no, item, fmt]
			if item == '':
				log.debug('self.worksheet.write_blank(*arg_list)'  + str( arg_list))
				self.worksheet.write_blank(*arg_list)
			elif type_ == 'str':
				log.debug('self.worksheet.write_string(*arg_list)' + str(arg_list))
				self.worksheet.write_string(*arg_list)
			elif type_ in {'num', 'int', 'float'}:
				log.debug('self.worksheet.write_number(*arg_list)' + str( arg_list))
				self.worksheet.write_number(*arg_list)
			else:
				log.critical(
					'Bad xlsx type {} in row {}:{} of worksheet {}'.format(
						type_, self.row_no, col_no, self.worksheet.get_name()
					)
				)
				raise ReportGeneratorError

		self.row_no += 1

	def get_widths(self):
		'''Return widths of all fields.

		For type float givse the pair (total_lenght, n_of_digits_before_point)
		'''
		return self.widths


def prepare_config_data_for_columns(columns, current_role):
	"""
	It prepares these date an once, not for each row

	1. Filters out depend on access
	2. Adds first column (column 0) for line numbers
	3. Generates types_list
	4. Addjust f.aling property
	etc...
	"""


	for column_name, column_data in columns:
		log.debug("column_name: " + column_name)
		log.debug("column_data: " + str(column_data))

		access = column_data['access']
		if access == 'all':
			column_data['allowed'] = True
		else:
			access_list = access.split()
			assert all([x in ALL_ROLES for x in access_list])
			column_data['allowed'] = current_role in access_list

		if column_data['f.align'] == '':
			xlsx_type = column_data['xlsx.type']
			if xlsx_type in {'num', 'int', 'float'}:
				column_data['f.align'] = 'right'
			else:
				column_data['f.align'] = 'left'

		if column_data['width.auto'] == '':
			if column_data['f.text_wrap'] or column_data['width.equal'] > 0:
				column_data['width.auto'] = False
			else:
				column_data['width.auto'] = True

		log.debug("column_data for " +  column_name + ": " + str(column_data))

	first_column_data = {k : v[1] for k, v in list(column_properties_info.items())}
	first_column_data.update(
		{
			'f.align' : 'right',
			'xlsx.type' : 'int',
			'width.auto': True
		}
	)

	new_columns = [('№', first_column_data)] + list([x for x in columns if x[1]['allowed']])

	return new_columns



def generate_report(
		report_name,				 # : unicode
		source_of_rows,			  # : str
		fields_for_select_related,   # : list[str]
		only_fields,				 # : list[str]
		filter_,					 # : dict (maps str to str)
		exclude,					 # : dict (maps str to str)
		order_by_list,			   # : list[str]
		columns,
		out_stream,				  # : opened stream or may be xlsx worksheet
		show_datetime,			   # : bool
		show_debug_info_on_columns,  # : bool
		filetype,					# : str ('xlsx' or 'csv')
		row_formats,				  # : dit (maps str to xlsxwriter.format.Format)
		process_by_month=''           # : str
		):


	if filetype == 'xlsx':
		out = XLSX_row_writer(out_stream)
	else:
		assert filetype == 'csv'
		out = CSV_row_writer(out_stream)

	def replaced_if_empty(value, replace_val='-'):
		return value or replace_val

	def mk_row_of_config_properties(left_header, property_, columns):
		lst = [left_header]
		lst.extend([replaced_if_empty(c_val[property_]) for _, c_val in columns[1:]])
		return lst

	def get_value(
			item,
			value_getter_str,
			eval_str,
			may_be_none=False,
			output_for_none='',
			column_no=-1
			):
				if value_getter_str[0] == '.':
					value = item
					for component in value_getter_str[1:].split('.'):
						if component.endswith('()'):
							try:
								value = getattr(value, component[:-2])()
							except AttributeError:
								log.critical('Colomn_no={}, component={}'.format(str(column_no), component))
								raise
						else:
							value = getattr(value, component)
						if may_be_none and value is None:
							break
							# return '-'
				else:
					assert not may_be_none
					if value_getter_str.endswith('()'):
						value = globals()[value_getter_str[:-2]](item)
					else:
						log.error("column_no=" + str(column_no) + " [" + value_getter_str + "] '" + str(item) + "'")
						value = globals()[value_getter_str]

				if value is None:
					value = output_for_none
				elif eval_str:
					# todo: maybe correctness of the experssion should be checked.
					eval_str_with_substitution = str(eval_str).format(val=value)
					value = eval(eval_str_with_substitution)

				return value


	#####################
	# Prepare query set #
	#####################

	if source_of_rows.endswith('()'):
		iterable_of_rows = globals()[source_of_rows[:-2]]()
		# - may be an instance of django.db.models.query.QuerySet
		# or any similar iterable.
		query_set_debug_str = source_of_rows
	else:
		main_model = getattr(models, source_of_rows)
		iterable_of_rows = main_model.objects  # here really 'django.db.models.manager.Manager' not iterable
		query_set_debug_str = source_of_rows + ".objects"

	if not any((fields_for_select_related, only_fields, filter_, exclude, order_by_list)):
		if isinstance(iterable_of_rows, Manager):
			iterable_of_rows = iterable_of_rows.all()
			query_set_debug_str += ".all()"
		else:
			pass  # for any iterable of rows (also QuerySet)
	else:
		assert isinstance(iterable_of_rows, QuerySet) or \
			isinstance(iterable_of_rows, Manager)
		query_set = iterable_of_rows
		if fields_for_select_related:
			query_set = query_set.select_related(*fields_for_select_related)
			query_set_debug_str += ".select_related(" + ", ".join(fields_for_select_related) + ")"
		if only_fields:
			query_set = query_set.only(*only_fields)
			query_set_debug_str += ".only(" + ", ".join(only_fields) + ")"
		if filter_:
			query_set = query_set.filter(**filter_)
			query_set_debug_str += ".filter(" + str(filter_) + ")"
		if exclude:
			query_set = query_set.exclude(**exclude)
			query_set_debug_str += ".exclude(" + str(exclude) + ")"
		if order_by_list:
			query_set = query_set.order_by(*order_by_list)
			query_set_debug_str += ".order_by(" + ", ".join(order_by_list) + ")"

		iterable_of_rows = query_set
		del query_set

	log.debug(query_set_debug_str)

	if show_datetime:
		if filetype == 'xlsx':
			log.debug('out_stream.set_row({}, None, {}'.format(out.current_row(), row_formats['sheet_datetime']))
			out_stream.set_row(out.current_row(), None, row_formats['sheet_datetime'])
		out.write(['Время создания отчета: ' + generate_datetime_now_string()], 'str', None)

	#################
	# Report header #
	#################
	fmt_list = None  # TODO



	if filetype == 'xlsx':
		log.debug('out_stream.set_row({}, None, {})'.format(out.current_row(), str(row_formats['header'])))
		out_stream.set_row(out.current_row(), None, row_formats['header'])

	out.write(list(map(itemgetter(0), columns)), 'str', fmt_list)


	if show_debug_info_on_columns:
		out.write(mk_row_of_config_properties('val', 'value', columns), 'str', fmt_list)
		if is_there_column_property('eval', columns):
			out.write(mk_row_of_config_properties('eval', 'eval', columns), 'str', fmt_list)
		if is_there_column_property('value2', columns):
			out.write(mk_row_of_config_properties('val2', 'value2', columns), 'str', fmt_list)
		if is_there_column_property('eval2', columns):
			out.write(mk_row_of_config_properties('eval2', 'eval2', columns), 'str', fmt_list)

#	out_stream.write('\t' + '\t'.join(map(lambda x: x[1]['value'], columns)) + '\n')
#	log.debug("columns: " + '\n'.join(map(unicode, columns)))
#	out_stream.write('\t' + '\t'.join(map(lambda x: x[1].get('value2', '-'), columns)) + '\n')
#	out_stream.write('\t' + '\t'.join(
#	   replaced_if_empty(c_val['value2']) for _, c_val in columns
#	  ) + '\n'
# )
	# End of report header
	########################

	types_list = [column_data['xlsx.type'] for _, column_data in columns]

	columns = columns[1:]   # We must exclude column for line numbers

	out.start_calculate_widths()

	assert isinstance(iterable_of_rows, QuerySet) or process_by_month == ''
	# ^ If intrable_of_rows is a list (for example), not a QuerySet, we can not
	# apply to it any more filters.
	# But we must filter by months, if process_by_month != ''.

	line_no = 0

	if process_by_month == '':
		months = [-1]
	else:
		months = list(range(1, 13))

	for month in months:
		if month == -1:
			iterable_of_rows_for_portion = iterable_of_rows
		else:
			iterable_of_rows_for_portion = iterable_of_rows.filter(**{process_by_month: month})
		for item in iterable_of_rows_for_portion:
			line_no += 1
			row = [str(line_no)]
			for column_no, (column_name, column_data) in enumerate(columns):
				may_be_none = column_data['may_be_none']
				output_for_none = column_data['output_for_none']
				try:
					tmp = get_value(
						item,
						column_data['value'],
						column_data['eval'],
						may_be_none,
						output_for_none,
						column_no
						)
					if isinstance(tmp, str):
						value = str(tmp)
					else:
						value = str(tmp)
				except (UnicodeDecodeError, TypeError, UnicodeEncodeError):
					print('===',  column_no, '===', tmp)
					raise

				value2_getter = column_data['value2']
				if value2_getter:
					value2 = str(
						get_value(
							item,
							value2_getter,
							column_data['eval2'],
							may_be_none,
							output_for_none,
							column_no
							)
					)
					if value2 != value:
						value += ('; ' + value2)
#						print "+++", "value2 != value: " + str(value2) + "!=" + str(value)
						log.warning("value2 != value: " + str(value2) + "!=" + str(value))
						if filetype == 'xlsx':
							# log.warning("I can show different value and value2 only in csv file, not xlsx")
							raise NotEqualValuesError(
								sheet_name=report_name,
								column_name=column_name,
								id_=item.id,	 # works only if there is such a field !!!
								values=str(value)
							)
						else:
							assert filetype == 'csv'
				row.append(value)

			out.write(row, types_list, fmt_list)
	return out, line_no

# /def generate_report(


def config_dict_to_xlsx_dict(config_dict, prefix):
	p_len = len(prefix)
	'''
	for k, v in  config_dict.items():
		if k.startswith(prefix) and k != prefix + '*':
			log.debug("--" + str(k[p_len:].split('!')[0]) + " : " + str(v))
			assert(str(v) != '')
	'''

	return {
	 k[p_len:].split('!')[0] : v for k, v in list(config_dict.items())
	 if k.startswith(prefix) and k != prefix + '*' and v != ''
	}



def mk_one_table(command_self, main_config_data, config_file_name, filetype, output):
	# config_file_name = CONFIG_FILE_NAME
	log.info('mk_one_table: ' + config_file_name)

	# command_self - may be usefull only when called via manage.py. Now unused


	"""
	if filetype == 'csv':
		report_file_name = CONFIG_FILE_DIR[:21] + config_file_basename[:-3] + 'csv'
		command_self.stdout.write(report_file_name)
	else:
		assert filetype == 'xlsx'
	"""

	assert (filetype == 'xlsx') == \
		isinstance(output, xlsxwriter.workbook.Workbook)

	try:
		with open(config_file_name, 'rt') as _:
			pass
	except IOError:
		log.critical("Config file '" + config_file_name + "' not found")
		raise ReadConfigError

	##########################
	# Processing of config data common for xlsx and csv
	##########################

	config_data = read_table_config(config_file_name)
	# log.debug(unicode(config_data))


	global_section, global_data = config_data[0]
	assert global_section == str(GLOBAL_SECT)

	main_model = global_data['main_model']
	row_generator = global_data['row_generator']
	assert (main_model == '') != (row_generator == '')
	source_of_rows = main_model or (row_generator + '()')

	assert 'fields_for_select_related' in global_data
	fields_for_select_related = global_data['fields_for_select_related'].split()
	assert 'only_fields' in global_data
	only_fields = global_data['only_fields'].split()
	assert 'filter' in global_data
	# log.debug('filter: [' + global_data['filter'] + ']')
	filter_ = eval(global_data['filter'])
	assert type(filter_) == dict

	assert 'process_by_month' in global_data
	process_by_month =  global_data['process_by_month']

	assert 'exclude' in global_data
	# log.debug('exclude: [' + global_data['exclude'] + ']')
	exclude = eval(global_data['exclude'])
	assert type(exclude) == dict

	assert 'order_by' in global_data
	order_by_list = global_data['order_by'].split()

	show_datetime = main_config_data['general']['show_datetime']
	show_debug_info_on_columns = main_config_data['general']['show_debug_info_on_columns']
	current_role = main_config_data['general']['role']
	assert current_role in ALL_ROLES

	if filetype == 'xlsx':
		sheet_name = global_data['sheet_name']
		assert sheet_name != ''

	if config_data[1][0] == str(DEFAULT_SECT):
		config_data.pop(1)

	# End of processing config data #
	#################################

	columns = prepare_config_data_for_columns(config_data[1:], current_role)
	new_sheet = xlsxwriter.worksheet.Worksheet()

	if filetype == 'xlsx':
		list_of_formats = []
		for column_name, column_data in columns:
			log.debug('+ column_name: ' + column_name)
			log.debug('+ column_data: ' + str(column_data))
			fmt_properties = config_dict_to_xlsx_dict(column_data, 'f.')
			if fmt_properties:
				log.debug('fmt_tmp = output.add_format({})'.format(str(fmt_properties)))
				fmt_tmp = output.add_format(fmt_properties)
				log.debug('fmt_tmp={}'.format(str(fmt_tmp)))
				list_of_formats.append(fmt_tmp)
			else:
				list_of_formats.append(None)


		# Set format for some rows:
		row_formats = {}
		header_format_dict = config_dict_to_xlsx_dict(global_data, 'header.f.')
		log.debug('header_format = output.add_format({})'.format(header_format_dict))
		row_formats['header'] = output.add_format(header_format_dict)
		log.debug(str(row_formats['header']))
		log.debug("output.add_format({'align' : 'left'})")
		format_align_left = output.add_format({'align' : 'left'})
		row_formats['sheet_datetime'] = format_align_left
		log.debug(str(row_formats['sheet_datetime']))


		# Add worksheet
		log.debug('output = output.add_worksheet({})'.format(sheet_name))
		new_sheet = output.add_worksheet(sheet_name)

		for col_no, fmt in enumerate(list_of_formats):
			log.debug('output.set_column({}, {}, {}, {})'.format(col_no, col_no, None, fmt))
			new_sheet.set_column(col_no, col_no, None, fmt)

	else:
		assert filetype == 'csv'
		row_formats = None


	report_name = sheet_name if filetype == 'xlsx' else str(os.path.basename(config_file_name))

	out_object, number_of_records = generate_report(
				report_name,
				source_of_rows,			  # : str
				fields_for_select_related,   # : list[str]
				only_fields,				 # : list[str]
				filter_,					 # : dict (maps str to str)
				exclude,					 # : dict (maps str to str)
				order_by_list,			   # : list[str]
				columns,
				new_sheet,					  # opened stream (or may be excel worksheet)
				show_datetime,			   # : bool
				show_debug_info_on_columns,  # : bool
				filetype,					# : str ('xlsx' or 'csv')
				row_formats,				  # : dict (maps str to xlsxwriter.format.Format)
				process_by_month=process_by_month  # : str
		)


	if filetype == 'xlsx':
		data_widths = out_object.get_widths() # pytype: disable=attribute-error
		out_object.stop_calculate_widths() # pytype: disable=attribute-error

		widths_list = [width_for_column(column_data, data_width)
				for (_, column_data), data_width in zip (columns, data_widths)
			]

#		out_object.write(['Debug output for autofit feature:'], 'str', format_align_left)
#		out_object.write(['+' if c_data['width.auto'] else '-' for _, c_data in columns], 'str')
#		out_object.write(map(str, data_widths), 'str')
#		out_object.write(map(str, widths_list), 'str')


#		width_list = [column_data['width.equal'] for _, column_data in columns]
		for col_no, width in enumerate(widths_list):
			if width > 0:
				log.debug('output.set_column({}, {}, {})'.format(col_no, col_no, width))
				new_sheet.set_column(col_no, col_no, width)

		stat_info = (eval(global_data['id_for_statistics']), number_of_records)
	else:
		assert filetype == 'csv'
		stat_info = None

	log.info('mk_one_table: finished')
	return stat_info


def mk_table_set(command_self, main_config_data, table_config_list, datetime_string, user=models.USER_ADMIN):
	"""Make one table set (one xlsx file or several csv files)"""

	global klb_year
	klb_year = main_config_data['general']['year']
	year_dir = str(klb_year) + '/'

	role = main_config_data['general']['role']

	output_file_type = main_config_data['general']['filetype']
	sleep_time = main_config_data['general']['sleep']


	output_file_name_with_datetime = main_config_data['general']['output_file_prefix'] \
		+ datetime_string

#	log.info("output_file_type: "  + output_file_type)

	if output_file_type == 'csv':
		for config_file_name in table_config_list:
			report_file_name = output_file_name_with_datetime + '-' + os.path.basename(config_file_name)[:-3] + 'csv'
			report_file_name = settings.MEDIA_ROOT.rstrip('/') + '/' + OUTPUT_DIR_RELATIVE_PATH + year_dir + report_file_name
			if command_self is not None:
				command_self.stdout.write(report_file_name)
			with codecs.open(report_file_name, 'wt', encoding='utf-8') as output:
				mk_one_table(command_self, main_config_data, config_file_name, 'csv', output)

			time.sleep(sleep_time)

			report_object = None
	else:
		assert output_file_type  == 'xlsx'
		xlsx_file_name = output_file_name_with_datetime + '.xlsx'
		assert xlsx_file_name != ''
		xlsx_relative_file_name = os.path.join(OUTPUT_DIR_RELATIVE_PATH, year_dir, xlsx_file_name)
		xlsx_file_name = os.path.join(settings.MEDIA_ROOT, xlsx_relative_file_name)

		absolute_dir_path = os.path.join(settings.MEDIA_ROOT, OUTPUT_DIR_RELATIVE_PATH, year_dir)
		if not os.path.exists(absolute_dir_path):
			os.mkdir(absolute_dir_path)

		wb_options = {
			k[5:]: v for k, v in list(main_config_data['xlsx.workbook.options'].items())
		}
		with xlsxwriter.Workbook(xlsx_file_name, wb_options) as wb:
			log.debug('xlsxwriter.Workbook({}, {})'.format(xlsx_file_name,  wb_options))
			tmp_dict = {
					k[5:]: v for k, v in 
					list(main_config_data['xlsx.workbook.properties'].items())
				}

			log.debug('wb.set_properties({})'.format(tmp_dict))
			wb.set_properties(tmp_dict)

			stat_info_list = []
			for config_file_name in table_config_list:
				log.debug('will mk_one_table' + os.path.basename(config_file_name))
				stat_info = mk_one_table(command_self, main_config_data, config_file_name, 'xlsx', wb)
				stat_info_list.append(stat_info)
				time.sleep(sleep_time)


		report_object = models.Klb_report(
				year=klb_year,
				file=xlsx_relative_file_name,
				is_public=(role == 'client'),
				created_by=user
			)
		report_object.save()

		for stat_info in stat_info_list:
			stat_object = models.Klb_report_stat(
					klb_report=report_object,
					value=stat_info[1],
					stat_type=stat_info[0]
				)
			stat_object.save()

	log.info('End of table set')
	return xlsx_relative_file_name if output_file_type == 'xlsx' else None


def prepare_main_config_data(main_config_dir):

	assert os.path.isdir(main_config_dir)

	main_config_dir = main_config_dir.rstrip('/') + '/'

	main_config_data = read_main_config(
			main_config_dir + NAME_OF_MAIN_CONFIG,
			main_config_properties_info
		)
	log.debug(str(main_config_data))

	##################################
	# get list of table config files #
	##################################
	table_configs = main_config_data['general']['table_configs'].split()

	table_config_set = reduce(
			operator.or_, [set(glob.glob(main_config_dir + p)) for p in table_configs]
		)

	table_config_list = sorted(table_config_set)

	dt_string = datetime.datetime.now().strftime(main_config_data['general']['output_file_dt_format'])

	return main_config_data, table_config_list, dt_string



def mk_table_set_wrapper(role, year, user=models.USER_ADMIN):
	"""Function for call via button push"""

	assert role in ('client', 'editor')

	main_config_data, table_config_list, dt_string = prepare_main_config_data(CONFIG_FILE_DIR)
	main_config_data['general']['role'] = role
	main_config_data['general']['year'] = year

	main_config_data['general']['show_debug_info_on_columns'] = (role == 'editor')
	main_config_data['general']['output_file_prefix'] = role

	try:
		try:
			relative_file_name = mk_table_set(
					None,
					main_config_data,
					table_config_list,
					dt_string,
					user=user
				)
		except NotEqualValuesError as e:
			log.critical(e.__str__())
			return False, e.__str__()
		else:
			return True, None
	except BaseException as ex:
		log.critical(ex.__str__())
		return False, ex.__str__()


def main_test1(command_self, main_config_dir=CONFIG_FILE_DIR):
	"""Function for test runs via manage.py

	Perform actions defined by main.conf in main_config_dir and all *.ini specified there

	(By default all *.ini in that directory)
	"""

	main_config_data, table_config_list, dt_string = prepare_main_config_data(main_config_dir)

	main_config_data['general']['year'] = 2018


	if main_config_data['general']['reports_for_editors_and_clients']:
		main_config_data['general']['show_debug_info_on_columns'] = True
		main_config_data['general']['role'] = 'editor'
		main_config_data['general']['output_file_prefix'] = 'editor'
		mk_table_set(command_self, main_config_data, table_config_list, dt_string)

		main_config_data['general']['show_debug_info_on_columns'] = False
		main_config_data['general']['role'] = 'client'
		main_config_data['general']['output_file_prefix'] = 'client'
		mk_table_set(command_self, main_config_data, table_config_list, dt_string)
	else:
		mk_table_set(command_self, main_config_data, table_config_list, dt_string)


def main_test2(command_self):
	"""Another function for test runs via manage.py

	It imitates two button pushes.
	"""

	mk_table_set_wrapper('editor', 2018)
	mk_table_set_wrapper('client', 2018)

def generate_klb_reports(roles=('editor', 'client')):
	today = datetime.date.today()
	for year in (models_klb.CUR_KLB_YEAR, models_klb.NEXT_KLB_YEAR):
		if 0 < year <= today.year:
			for role in roles:
				result, error = mk_table_set_wrapper(role, year)
				if result:
					print('Report for role {} and year {} is successfully created'.format(role, year))
				else:
					print('Report for role {} and year {} was not created! Reason: {}'.format(role, year, error))

@group_required('admins')
def make_report(request, year, role):
	year = results_util.int_safe(year)
	if not models.is_active_klb_year(year):
		messages.warning(request, 'Сейчас нельзя создавать слепки КЛБМатча за {} год'.format(year))
		return redirect('results:reports')

	if role != 'client':
		role = 'editor'

	result, error = mk_table_set_wrapper(role, year, request.user)
	if result:
		messages.success(request, 'Слепок КЛБМатча за {} год успешно создан'.format(year))
	else:
		messages.warning(request, 'Слепок не создан. Причина: {}'.format(error))
	return redirect('results:klb_reports', year=year)
