# pytype: disable=attribute-error
from django.apps import apps
from django.apps.config import AppConfig
from django.db.models import F
from django.db import models

import logging
from typing import Any, Dict, List, Optional, Set, Tuple

from tools import dj_sql_tools
from tools.dj_meta import get_full_model_name, get_model_by_name
from tools.other import log_if_logger
from tools.dj_other import cast_to_queryset

class Abstract_checker(object):
	def shortcut1(self, logger, log_level_ok, log_level_error, result_list, comment=None, nothing_if_ok=True):
		assert not self.executed
		self.run()
		message = comment if comment else ''
		self.log(logger, log_level_ok, log_level_error, message)
		self.result_to_list(result_list, comment, nothing_if_ok)
		return self

class Abstract_ORM_checker(Abstract_checker):
	def run(self):
		self._count = self.qs.count()
		self.executed = True
		return self

	@property
	def is_ok(self):
		assert self.executed
		return self._count == 0

	@property
	def count(self):
		assert self.executed
		return self._count

	def get_result_as_queryset(self, limit=None):  # limit: None - use default_limit, 0 - unlimited.
		assert self.executed
		if limit == 0:
			return self.qs
		else:
			if limit is None:
				limit = self.default_limit
			return self.qs.all()[:limit]

	def get_result(self, fields_to_show=None, limit=None):  # limit: None - use default_limit limit, 0 - unlimited.
		assert self.executed
		if fields_to_show is None:
			fields_to_show = self.default_field_list
		elif 'pk' not in fields_to_show:
			fields_to_show.append('pk')
		return self.get_result_as_queryset(limit).values(*fields_to_show)

	def get_result2(self, fields_to_show=None, limit=None):  # limit: None - use default_limit limit, 0 - unlimited.
		assert self.executed
		result = list(self.get_result(fields_to_show, limit))
		for item in result:
			assert '_unicode' not in item
			item['_unicode'] = str(self.main_model.objects.get(pk=item['pk']))
		return result

	def sql_listing_command(self, field_list=None, limit=None):
		assert self.executed
		qs = self.qs
		if field_list is None:
			field_list = self.default_field_list
		elif field_list == 'all':
			field_list = [f.name for f in self.main_model._meta.get_fields() if f.concrete]
		if field_list == []:
			qs = self.qs
		else:
			qs = self.qs.only(*field_list)
		if limit is not None:
			qs = qs.all()[:limit]
		return str(qs.query)

	def log(self, logger, log_level_ok, log_level_error, message=''):  # message not used yet !
		assert self.executed
		if self.is_ok:
			logger.log(log_level_ok, ' '.join((type(self).__name__ + ':', self.check_subject, 'OK')))
		else:
			logger.log(log_level_error, ' '.join((type(self).__name__ + ':', self.check_subject,  str(self.count))))
		return self

	def result_to_list(self, lst, comment=None, nothing_if_ok=True):
		assert self.executed
		checker = type(self).__name__
		subject = self.check_subject
		result = {'checker' : checker, 'subject': subject}
		if comment is not None:
			result['comment'] = comment
		if self.is_ok:
			if not nothing_if_ok:
				lst.append(result)
		else:
			result['count'] = self.count
			result['sql'] = self.sql_listing_command()
			lst.append(result)
		return self

	@property
	def check_subject(self):
		return self.subject

	def get_python_code(self):
		# Should be overriden in subclasees
		raise NotImplementedError


class Abstract_exclude_checker(Abstract_ORM_checker):
	def _exclude_params(self):  # -> unicode
		# Should be overriden in subclasees
		raise NotImplementedError

	@property
	def check_subject(self):
		return '{}.{}: {}'.format(
				self.main_model._meta.app_label,
				self.main_model.__name__,
				self._exclude_params()
			)

	def get_python_code(self):
		assert issubclass(self.main_model, models.Model)
		module_name = self.main_model._meta.app_config.models_module.__name__
		import_commands = 'import ' + module_name
		if self.value2_is_field_name:
			import_commands += '; from django.db.models import F'

		query_command = 'qs = {}.{}.objects.exclude({})'.format(
				module_name,
				self.main_model.__name__,
				self._exclude_params()
			)
		return import_commands, query_command


class Sql_empty_checker(dj_sql_tools.Sql_command):
	"""
	>>> ec = Sql_empty_checker("from {m:Distance}", 'results')
	>>> ec.untranslated
	('SELECT COUNT(*) from {m:Distance}', 'results', None)
	>>> ec.translated
	u'SELECT COUNT(*) from `dist`'
	>>> ec.is_ok
	Traceback (most recent call last):
	AssertionError
	>>> ec.run() # doctest: +ELLIPSIS
	<dbchecks.dbchecks.Sql_empty_checker object at ...>
	>>> ec.is_ok
	False
	>>> ec.count
	1L
	>>> ec.sql_listing_command()
	(u'SELECT * from {m:Distance}', 'results', None)
	>>> ec.sql_listing_command([], 5)
	(u'SELECT * from {m:Distance} LIMIT 5', 'results', None)
	>>> ec.sql_listing_command(['distance_type', 'length', 'name'], 0)
	(u'SELECT {f:distance_type}, {f:length}, {f:name} from {m:Distance}', 'results', None)
	>>> ec = Sql_empty_checker("from {m:_} where {f:id}=0", 'results', 'Distance')
	>>> ec.sql_translated_listing_command(['distance_type', 'length', 'name'], 0)
	u'SELECT `dist`.`dj_type`, `dist`.`dj_length`, `dist`.`dj_name` from `dist` where `dist`.`id`=0'
	>>> ec = Sql_empty_checker("from {m:_} where {f:id}=0", 'results', 'Distance')
	>>> ec.untranslated
	('SELECT COUNT(*) from {m:_} where {f:id}=0', 'results', 'Distance')
	>>> ec.translated
	u'SELECT COUNT(*) from `dist` where `dist`.`id`=0'
	>>> ec.run() # doctest: +ELLIPSIS
	<dbchecks.dbchecks.Sql_empty_checker object at ...>
	>>> ec.is_ok
	True
	>>> ec.count
	0L
	"""

	def __init__(self, sql_command, default_app=None, default_model=None):
		sql_command = sql_command.lstrip()
		assert sql_command[:4].upper() == "FROM"
		self.given_sql_command = (sql_command, default_app, default_model)
		sql_command = "SELECT COUNT(*) " + sql_command
		super(Sql_empty_checker, self).__init__(sql_command, default_app, default_model)

	def run(self):
		super(Sql_empty_checker, self).run()
		assert len(self.result) == 1
		assert len(self.result[0]) == 1
		return self

	@property
	def is_ok(self):
		assert self.executed
		return self.result == ((0,),)

	@property
	def count(self):
		assert self.executed
		return self.result[0][0]

	def sql_listing_command(self, field_list=None, limit=None) -> Tuple[str, str, str]:
		if not field_list:
			field_list_in_str = '*'
		else:
			field_list_in_str = ', '.join([''.join(('{f:', item, '}')) for item in field_list])
			
		limit_str = 'LIMIT ' + str(limit) if limit else ''
		return (
				' '.join(('SELECT', field_list_in_str, self.given_sql_command[0], limit_str)).rstrip(),
				self.given_sql_command[1],
				self.given_sql_command[2]
			)

	def sql_translated_listing_command(self, field_list=None, limit=None):
		return dj_sql_tools.sql_translate(*self.sql_listing_command(field_list, limit)) 

	def log(self, logger, log_level_ok, log_level_error, message=''):
		assert self.executed
		checker_name = type(self).__name__
		if message:
			message = '({})'.format(message)
		if self.is_ok:
			log_level = log_level_ok
			count_str = ''
		else:
			log_level = log_level_error
			count_str = ' count: {}'.format(self.count)
			
		log_message = '{}{} {}. SQL_command: {}'.format(
			checker_name,
			count_str,
			message,
			self.sql_translated_listing_command()
		)
		log_level = log_level_ok if self.is_ok else log_level_error
		logger.log(log_level, log_message)
		return self


class Relationship_checker(Abstract_checker):
	def __init__(self, model, field):   # model may be a model class or a model name
		self.executed = False
		model = get_model_by_name(model)
		self.model = model
		self.app_label = model._meta.app_label
		if isinstance(field, str):
			assert not field.endswith('_id')
			self.field_name = field + '_id'
			field = model._meta.get_field(field)
		else:
			self.field_name = field.name + '_id'
		self.field = field

		assert not field.auto_created
		assert field.concrete

		if field.many_to_one:
			self.relationship_type = 'FK'
		else:
			assert field.one_to_one
			self.relationship_type = 'o2o'

		self.sql_command_0 = None
		if not field.null:
			self.sql_command_0 = """
FROM {{m:{model_name}}}
WHERE {{f:{model_name}.{field_name}}} IS NULL
			""".format(model_name=self.model.__name__, field_name=self.field_name)
			self.e_checker_0 = Sql_empty_checker(self.sql_command_0, self.app_label)
		else:
			self.e_checker_0 = None

		self.sql_command_1 = """
FROM {{m:{model_name}}}
WHERE ( {{f:{model_name}.{field_name}}} NOT IN
       (SELECT {{f:{related_app}.{related_model}.id}} FROM {{m:{related_app}.{related_model}}})
      )
		""".format(
				model_name=self.model.__name__,
				field_name=self.field_name,
				related_app=self.field.related_model._meta.app_label,
				related_model=self.field.related_model.__name__
			)
		if field.null:
			self.sql_command_1 += "     AND {{f:{model_name}.{field_name}}} IS NOT NULL".format(
					model_name=self.model.__name__, field_name=self.field_name
				)
			
		self.e_checker_1 = Sql_empty_checker(self.sql_command_1, self.app_label)

	def run(self):
		self.count_0 = -1
		if self.e_checker_0 is not None:
			self.e_checker_0.run()
			self.count_0 = self.e_checker_0.count

		self.e_checker_1.run()
		self.count_1 = self.e_checker_1.count
		
		self.executed = True
		
		return self

	@property
	def is_ok(self):
		assert self.executed
		return self.count_0 <=0 and self.count_1 == 0

	@property
	def counts(self):
		assert self.executed
		return self.count_0, self.count_1

	def sql_translated_listing_command(self, field_list=None, limit=None):
		assert self.executed
		command = ''
		if self.count_0 > 0:
			command = self.e_checker_0.sql_translated_listing_command(field_list, limit)
			if self.count_1 > 0:
				command += ' UNION '
		if self.count_1 > 0:
			command += self.e_checker_1.sql_translated_listing_command(field_list, limit)
		if command == '':
			command = None
		return command

	def log(self, logger, log_level_ok, log_level_error, message=''): # message not used yet !
	
		assert self.executed
		full_field_name = '.'.join((self.model._meta.app_label, self.model.__name__, self.field_name))
		if self.is_ok:
			logger.log(log_level_ok, ' '.join((self.relationship_type + '_checker:', full_field_name, 'OK')))
		else:
			logger.log(log_level_error, ' '.join((self.relationship_type + '_checker:', full_field_name, str(self.counts))))
		return self

	def result_to_list(self, lst, comment=None, nothing_if_ok=True):
		assert self.executed
		checker = type(self).__name__
		subject =  get_full_model_name(self.model) + '.' + self.field_name
		result = {'checker' : checker, 'subject': subject}
		if comment is not None:
			result['comment'] = comment
		if self.is_ok:
			if not nothing_if_ok:
				lst.append(result)
		else:
			result['counts'] = self.counts
			result['sql'] = self.sql_translated_listing_command()
			lst.append(result)
		return self


def check_relationships(model, logger=None, log_level_ok=logging.DEBUG, log_level_error=logging.ERROR):
	# model may be a model class or a model name
	model = get_model_by_name(model)
	results = {}
	for field in model._meta.get_fields():
		if field.many_to_one or (field.one_to_one and field.concrete):
			checker = Relationship_checker(model, field).run()
			if not checker.is_ok:
				results[field.name] = (checker.counts, checker.sql_translated_listing_command())
			if logger:
				checker.log(logger, log_level_ok, log_level_error)
	return results


def check_relationships2(
			model,    # model may be a model class or a model name
			logger=None, log_level_ok=logging.DEBUG, log_level_error=logging.ERROR, log_level_info=logging.INFO,
			result_list=None, nothing_if_ok=True
		):
	model = get_model_by_name(model)
	log_if_logger(logger, log_level_info, 'check_relationships2 of ' + model.__name__)
	if result_list is None:
		lst = []
	else:
		lst = result_list
	for field in model._meta.get_fields():
		if field.many_to_one or (field.one_to_one and field.concrete):
			Relationship_checker(model, field).shortcut1(
					logger, log_level_ok, log_level_error,
					lst, None, nothing_if_ok
				)
	if result_list is None:
		return lst


def check_relationships2_for_app(
			app, # may be app_label or appinfo
			logger=None, log_level_ok=logging.DEBUG, log_level_error=logging.ERROR, log_level_info=logging.INFO,
			result_list=None, nothing_if_ok=True
		):
	if isinstance(app, str):
		app_config = apps.get_app_config(app)
	else:
		assert isinstance(app, AppConfig)
		app_config = app

	log_if_logger(logger, log_level_info, 'BEGIN: check_relationships2_for_app of ' + app_config.label)
	if result_list is None:
		lst = []
	else:
		lst = result_list

	for model in app_config.get_models():
		check_relationships2(model, logger, log_level_ok, log_level_error, log_level_info, result_list, nothing_if_ok)

	log_if_logger(logger, log_level_info, 'END: check_relationships2_for_app of ' + app_config.label)

	if result_list is None:
		return lst


def check_all_relationships(logger=None, log_level_ok=logging.DEBUG, log_level_error=logging.ERROR, log_level_info=logging.INFO):
	results = {}
	for app_config in apps.get_app_configs():
		logger.log(log_level_info, 'Check relationships: started {} app'.format(app_config.label))
		for model in app_config.get_models():
			full_model_name = app_config.label + '.' + model.__name__
			logger.log(log_level_info, 'Check relationships: started {} model'.format(full_model_name))
			result = check_relationships(model, logger, log_level_ok, log_level_error)
			if result:
				results[full_model_name] = result
	return results


def check_all_relationships2(logger=None, log_level_ok=logging.DEBUG, log_level_error=logging.ERROR, log_level_info=logging.INFO):
	result = check_all_relationships(logger, log_level_ok, log_level_error)
	flatten_result = {}
	for model_name, model_result in list(result.items()):
		for field_name, field_result in list(model_result.items()):
			assert model_name + '.' + field_name not in flatten_result
			flatten_result[model_name + '.' + field_name] = field_result
	return flatten_result


class Not_null_checker(Abstract_exclude_checker):
	"""
	>>> ec = Not_null_checker('Event', 'city')
	>>> ec.check_subject
	u'results.Event: city__isnull=False'
	>>> ec.executed
	False
	>>> ec.run() # doctest: +ELLIPSIS
	<dbchecks.dbchecks.Not_null_checker object at ...>
	>>> ec.is_ok
	True
	>>> ec.count
	0
	>>> import results.models
	>>> ec = Not_null_checker(results.models.Event, 'city')
	>>> ec.check_subject
	u'results.Event: city__isnull=False'
	>>> ec.executed
	False
	>>> ec.run() # doctest: +ELLIPSIS
	<dbchecks.dbchecks.Not_null_checker object at ...>
	>>> ec.is_ok
	True
	>>> ec.count
	0
	"""

	default_limit = 5

	def __init__(self, main_model, field):   # main_model may be a model class or a model name
		main_model = get_model_by_name(main_model)
		self.qs = main_model.objects.exclude(
			**{field + '__isnull' : False}
		)
		self.field = field
		self.main_model = main_model
		self.executed = False
		self.default_field_list = ['pk']

	def _exclude_params(self):  # -> unicode
		return '{}__isnull=False'.format(self.field)


class Equality_checker(Abstract_exclude_checker):
	# TODO: check value2 is not NULL

	"""
	>>> ec = Equality_checker('Event', 'city', 'city_finish')
	>>> ec.check_subject
	u'results.Event: city=F("city_finish")'
	>>> ec.executed
	False
	>>> ec.run() # doctest: +ELLIPSIS
	<dbchecks.dbchecks.Equality_checker object at ...>
	>>> ec.is_ok
	True
	>>> ec.count
	0
	>>> import results.models
	>>> ec = Equality_checker(results.models.Event, 'city', 'city_finish')
	>>> ec.check_subject
	u'results.Event: city=F("city_finish")'
	>>> ec.executed
	False
	>>> ec.run() # doctest: +ELLIPSIS
	<dbchecks.dbchecks.Equality_checker object at ...>
	>>> ec.is_ok
	True
	>>> ec.count
	0
	>>> ec.sql_listing_command('all')
	u'SELECT `ProbegYear`.`id`, `ProbegYear`.`NameP`, `ProbegYear`.`dj_number`, `ProbegYear`.`Probeg_id`, `ProbegYear`.`dj_country_id`, `ProbegYear`.`dj_city_id`, `ProbegYear`.`dj_city_finish_id`, `ProbegYear`.`dj_surface_type`, `ProbegYear`.`countryp`, `ProbegYear`.`fedokrugp`, `ProbegYear`.`oblp`, `ProbegYear`.`cityp`, `ProbegYear`.`DateS`, `ProbegYear`.`DateF`, `ProbegYear`.`DataZ`, `ProbegYear`.`Year`, `ProbegYear`.`Month`, `ProbegYear`.`PlaceS`, `ProbegYear`.`TimeS`, `ProbegYear`.`Anons`, `ProbegYear`.`url_registration`, `ProbegYear`.`Detail`, `ProbegYear`.`Bill`, `ProbegYear`.`Plan`, `ProbegYear`.`LabelP`, `ProbegYear`.`AdressP`, `ProbegYear`.`AdressPP`, `ProbegYear`.`AdressPr`, `ProbegYear`.`Email`, `ProbegYear`.`Adress`, `ProbegYear`.`Site`, `ProbegYear`.`Tel`, `ProbegYear`.`Facebook`, `ProbegYear`.`Dists`, `ProbegYear`.`otmenen`, `ProbegYear`.`Komm`, `ProbegYear`.`dj_comment_private`, `ProbegYear`.`LastIzm`, `ProbegYear`.`unvisible`, `ProbegYear`.`GroupsProbeg`, `ProbegYear`.`RACEID`, `ProbegYear`.`unklbmatch`, `ProbegYear`.`dj_ask_for_protocol_sent`, `ProbegYear`.`dj_source`, `ProbegYear`.`Date_In_Calend`, `ProbegYear`.`dj_created_by` FROM `ProbegYear` WHERE NOT (`ProbegYear`.`dj_city_id` = (`ProbegYear`.`dj_city_finish_id`) AND `ProbegYear`.`dj_city_id` IS NOT NULL)'
	>>> ec.sql_listing_command()
	u'SELECT `ProbegYear`.`id`, `ProbegYear`.`dj_city_id`, `ProbegYear`.`dj_city_finish_id` FROM `ProbegYear` WHERE NOT (`ProbegYear`.`dj_city_id` = (`ProbegYear`.`dj_city_finish_id`) AND `ProbegYear`.`dj_city_id` IS NOT NULL)'
	>>> ec.sql_listing_command(["id", "name"])
	u'SELECT `ProbegYear`.`id`, `ProbegYear`.`NameP` FROM `ProbegYear` WHERE NOT (`ProbegYear`.`dj_city_id` = (`ProbegYear`.`dj_city_finish_id`) AND `ProbegYear`.`dj_city_id` IS NOT NULL)'
	>>> ec.get_python_code()
	(u'import results.models; from django.db.models import F', u'qs = results.models.Event.objects.exclude(city=F("city_finish"))')
	>>> print ec.get_python_code()[0]
	import results.models; from django.db.models import F
	>>> print(ec.get_python_code()[1])
	qs = results.models.Event.objects.exclude(city=F("city_finish"))
	>>> ec = Equality_checker(results.models.Event, u'name', u'Event name here', False)
	>>> ec.check_subject
	u"results.Event: name=u'Event name here'"
	>>> ec.run() # doctest: +ELLIPSIS
	<dbchecks.dbchecks.Equality_checker object at ...>
	>>> print ec.get_python_code()[0]
	import results.models
	>>> print ec.get_python_code()[1]
	qs = results.models.Event.objects.exclude(name=u'Event name here')
	>>> ec = Equality_checker(results.models.Event, u'id', 10, False)
	>>> ec.run() # doctest: +ELLIPSIS
	<dbchecks.dbchecks.Equality_checker object at ...>
	>>> print ec.get_python_code()[0]
	import results.models
	>>> print ec.get_python_code()[1]
	qs = results.models.Event.objects.exclude(id=10)
	"""

	default_limit = 5
	# Exceptions is the list of primary IDs of the model to ignore
	def __init__(self, main_model, value1, value2, value2_is_field_name=True, exceptions: Optional[Set]=None):  # main_model may be a model class or a model name
		# TODO Check working with russian text in value2
		#	(self.get_python_code does not work).
		main_model = get_model_by_name(main_model)
		if value2_is_field_name:
			self.exclude_dict = {value1: F(value2)}
		else:
			self.exclude_dict = {value1: value2}
		self.qs = main_model.objects.exclude(**self.exclude_dict)
		if exceptions:
			self.qs = self.qs.exclude(pk__in=exceptions)
		self.main_model = main_model
		self.value1 = value1
		self.value2 = value2
		self.value2_is_field_name = value2_is_field_name
		self.executed = False
		self.default_field_list = ['pk', value1]
		if value2_is_field_name:
			self.default_field_list.append(value2)

	def _exclude_params(self):  # -> unicode
		if self.value2_is_field_name:
			value2_str = 'F("{}")'.format(self.value2)
		else:
			value2_str = '{}'.format(repr(self.value2))
		return '{}={}'.format(self.value1, value2_str)

# joblist is a list of tuples with 4 elements:
# * Model name
# * First field to compare
# * Second field to compare
# * List of primary IDs of exceptions
def check_equality_by_list(joblist: List[Tuple[models.Model, str, str, Optional[Set]]], logger=None, log_level_ok=logging.DEBUG, log_level_error=logging.ERROR,
			log_level_info=logging.INFO) -> Dict[str, Tuple[int, List[Any], str, Tuple[str, str]]]:
	results = {}
	for check in joblist:
		assert isinstance(check, (tuple, list))
		main_model, value1, value2, exceptions = check
		if isinstance(main_model, str):
			main_model = apps.get_model(main_model)
		assert issubclass(main_model, models.Model)
		checker = Equality_checker(main_model, value1, value2, True, exceptions=exceptions).run()
		assert checker.check_subject not in results
		if checker.is_ok:
			# results[checker.check_subject] = True
			pass
		else:
			results[checker.check_subject] = (
					checker.count,
					checker.get_result2(),
					checker.sql_listing_command(),
					checker.get_python_code(),
				)
		if logger:
			checker.log(logger, log_level_ok, log_level_error)

	# return {item[0]: item[1] for item in list(results.items()) if item[1] != True}
	return results


class Queryset_empty_checker(Abstract_ORM_checker):
	# exclude_param_str - only human readeble
	"""
	>>> import results.models
	>>> qs = results.models.Event.objects.exclude(city=F("city_finish"))
	>>> ec = Queryset_empty_checker(qs, 'Event: city=F("city_finish")')
	>>> ec.check_subject
	'Event: city=F("city_finish")'
	>>> ec.executed
	False
	>>> ec.run() # doctest: +ELLIPSIS
	<dbchecks.dbchecks.Queryset_empty_checker object at ...>
	>>> ec.is_ok
	True
	>>> ec.count
	0
	>>> ec.sql_listing_command('all')
	Traceback (most recent call last):
	AttributeError: 'Queryset_empty_checker' object has no attribute 'main_model'
	>>> ec.sql_listing_command()
	u'SELECT `ProbegYear`.`id`, `ProbegYear`.`NameP`, `ProbegYear`.`dj_number`, `ProbegYear`.`Probeg_id`, `ProbegYear`.`dj_country_id`, `ProbegYear`.`dj_city_id`, `ProbegYear`.`dj_city_finish_id`, `ProbegYear`.`dj_surface_type`, `ProbegYear`.`countryp`, `ProbegYear`.`fedokrugp`, `ProbegYear`.`oblp`, `ProbegYear`.`cityp`, `ProbegYear`.`DateS`, `ProbegYear`.`DateF`, `ProbegYear`.`DataZ`, `ProbegYear`.`Year`, `ProbegYear`.`Month`, `ProbegYear`.`PlaceS`, `ProbegYear`.`TimeS`, `ProbegYear`.`Anons`, `ProbegYear`.`url_registration`, `ProbegYear`.`Detail`, `ProbegYear`.`Bill`, `ProbegYear`.`Plan`, `ProbegYear`.`LabelP`, `ProbegYear`.`AdressP`, `ProbegYear`.`AdressPP`, `ProbegYear`.`AdressPr`, `ProbegYear`.`Email`, `ProbegYear`.`Adress`, `ProbegYear`.`Site`, `ProbegYear`.`Tel`, `ProbegYear`.`Facebook`, `ProbegYear`.`Dists`, `ProbegYear`.`otmenen`, `ProbegYear`.`Komm`, `ProbegYear`.`dj_comment_private`, `ProbegYear`.`LastIzm`, `ProbegYear`.`unvisible`, `ProbegYear`.`GroupsProbeg`, `ProbegYear`.`RACEID`, `ProbegYear`.`unklbmatch`, `ProbegYear`.`dj_ask_for_protocol_sent`, `ProbegYear`.`dj_source`, `ProbegYear`.`Date_In_Calend`, `ProbegYear`.`dj_created_by` FROM `ProbegYear` WHERE NOT (`ProbegYear`.`dj_city_id` = (`ProbegYear`.`dj_city_finish_id`) AND `ProbegYear`.`dj_city_id` IS NOT NULL)'
	>>> ec.sql_listing_command(["id", "name"])
	u'SELECT `ProbegYear`.`id`, `ProbegYear`.`NameP` FROM `ProbegYear` WHERE NOT (`ProbegYear`.`dj_city_id` = (`ProbegYear`.`dj_city_finish_id`) AND `ProbegYear`.`dj_city_id` IS NOT NULL)'
	>>> ec.get_python_code()
	Traceback (most recent call last):
	NotImplementedError
	"""

	def __init__(self, qs, check_subject):
		self.qs = qs
		assert isinstance(check_subject, str)
		self.subject = check_subject
		self.executed = False
		self.default_field_list = []


class Abstract_ORM_multi_checker(Abstract_ORM_checker):  # class where more then 1 request is needed
	def run(self):
		self._counts = tuple(qs.count() for qs in self.qs_list)
		self._count = sum(self._counts)
		self.executed = True
		return self

	# properties count and is_ok are inherited

	@property
	def counts(self):
		assert self.executed
		return self._counts

	def get_result_as_queryset(self, limit=None):
		raise NotImplementedError

	def get_result_as_querysets(self, limit=None):  # limit: None - use default_limit, 0 - unlimited.
		result_list = []
		for qs in self.qs_list:
			assert self.executed
			if limit == 0:
				result_list.append(qs)
			else:
				if limit is None:
					limit = self.default_limit
				result_list.append(qs.all()[:limit])
		return tuple(result_list)

	def get_result(self, fields_to_show=None, limit=None):  # limit: None - use default_limit limit, 0 - unlimited.
		raise NotImplementedError

	def get_result2(self, fields_to_show=None, limit=None):  # limit: None - use default_limit limit, 0 - unlimited.
		raise NotImplementedError

	def sql_listing_command(self, field_list=None, limit=None):
		raise NotImplementedError

	def sql_listing_commands(self, field_list=None, limit=None):
		return_list = []
		assert self.executed
		for qs in self.qs_list:
			if field_list is None:
				field_list = self.default_field_list
			elif field_list == 'all':
				field_list = [f.name for f in self.main_model._meta.get_fields() if f.concrete]
			if field_list != []:
				qs = qs.only(*field_list)
			if limit is not None:
				qs = qs.all()[:limit]
			return_list.append(str(qs.query))
		return tuple(return_list)

	def log(self, logger, log_level_ok, log_level_error, message=''):  # message not used yet !
		assert self.executed
		if self.is_ok:
			logger.log(log_level_ok, ' '.join((type(self).__name__ + ':', self.check_subject, 'OK')))
		else:
			logger.log(log_level_error, ' '.join((type(self).__name__ + ':', self.check_subject,  str(self.count))))
		return self

	def result_to_list(self, lst, comment=None, nothing_if_ok=True):
		assert self.executed
		checker = type(self).__name__
		subject = self.check_subject
		result = {'checker' : checker, 'subject': subject}
		if comment is not None:
			result['comment'] = comment
		if self.is_ok:
			if not nothing_if_ok:
				lst.append(result)
		else:
			result['count'] = self.counts
			result['sql'] = self.sql_listing_commands()
			lst.append(result)
		return self

	@property
	def check_subject(self):
		return self.subject

	def get_python_code(self):
		# Should be overriden in subclasees
		raise NotImplementedError


class Set_equality_checker(Abstract_ORM_multi_checker):
	def __init__(self, qs1, field1, qs2, field2, check_subject):   # qs1, qs2 may be QuerySet, Model, Manager
		assert isinstance(check_subject, str)
		self.subject = check_subject
		qs1 = cast_to_queryset(qs1)
		qs2 = cast_to_queryset(qs2)
		self.executed = False
		self.default_field_list = []
		self.qs_list = (
			qs1.exclude(**{field1 + '__in': qs2.values(field2)}),
			qs2.exclude(**{field2 + '__in': qs1.values(field1)}),
		)