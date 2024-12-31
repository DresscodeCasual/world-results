# -*- coding: utf-8 -*-

# from __future__ import unicode_literals   

import django.apps
from django.db import connection
import re
from collections import namedtuple


def sql_translate(src_str, default_app=None, default_model=None):
	"""
	Makes sql query string retrieving real db table and column names by _meta interface.
	{m: DJANGO_MODEL_NAME} will be replaced with database table name
	{f: DJANGO_MODEL_NAME.DJANGO_FIELD_NAME} will be replaced with database column name
	{f: DJANGO_FIELD_NAME} will be replaced with database column name of the default model
	
	Some examples:

	>>> sql_translate("SELECT {f:Event.series_id} from {m:Event}", "results")
	u'SELECT `ProbegYear`.`Probeg_id` from `ProbegYear`'

	>>> sql_translate("SELECT {f:Event.series_id} from {m:Event}")
	Traceback (most recent call last):
	AssertionError

	>>> sql_translate("SELECT {f:series_id} from {m:Event}", "results", "Event")
	u'SELECT `ProbegYear`.`Probeg_id` from `ProbegYear`'

	>>> sql_translate("SELECT {f:series_id} from {m:Event}", "results")
	Traceback (most recent call last):
	AssertionError

	>>> sql_translate("SELECT {f:results.Event.series_id} from {m:results.Event}")
	u'SELECT `ProbegYear`.`Probeg_id` from `ProbegYear`'

	>>> sql_translate("SELECT {f:series_id} from {m:_}", "results", "Event")
	u'SELECT `ProbegYear`.`Probeg_id` from `ProbegYear`'

	>>> sql_translate("SELECT {f:series_id} from {m:_}", "results")
	Traceback (most recent call last):
	AssertionError

	>>> sql_translate("SELECT ProbegYear.Probeg_id from ProbegYear")
	u'SELECT ProbegYear.Probeg_id from ProbegYear'
	"""

	pattern = re.compile(r'\{[fm]:[^}]+\}')
	pattern_full = re.compile(r'\{[fm]:[ \t]*[_a-zA-Z][\w.]*\}$')
	set_to_process = set(pattern.findall(src_str))
	new_str = str(src_str)
	for item in set_to_process:
		try:
			del model_name
		except UnboundLocalError:
			pass
		assert pattern_full.match(item)
		m_or_f = item[1]
		item_name = item[3:-1].lstrip()
		if m_or_f == 'm':
			if item_name == '_':
				assert default_model is not None
				model_name = default_model
			else:
				model_name = item_name
				if '.' in item_name:
					assert item_name.count('.') == 1
			if '.' in model_name:
				full_model_name = model_name
			else:
				if model_name == 'User':
					full_model_name = 'auth.User'    # temporary dirty hack
				else:
					assert default_app is not None
					full_model_name = default_app + '.' + model_name
			model = django.apps.apps.get_model(full_model_name)
			new_str = new_str.replace(item, "`" + model._meta.db_table + "`")
		else:
			assert m_or_f == 'f'
			splitted = item_name.split('.')
			len_s = len(splitted)
			assert len_s <= 3
			field_name = splitted[-1]
			if len_s > 1:
				model_name = splitted[-2]
			else:
				assert default_model is not None
				model_name = default_model
			if len_s > 2:
				full_model_name = splitted[-3] + '.' + model_name
			elif '.' in model_name:
				full_model_name = model_name
			else:
				assert default_app is not None
				full_model_name = default_app + '.' + model_name
#			print "full_model_name: [" + full_model_name + "]"
			model = django.apps.apps.get_model(full_model_name)
			db_column = model._meta.get_field(field_name).db_column or field_name
#			print(model, model._meta.db_table, db_column)
			new_str = new_str.replace(item, "`" + model._meta.db_table + "`.`" + db_column + "`")
	return new_str


def sql_run_raw(sql_command):
	"""
	Executes sql command without any translation and returns the whole result as a pair: (header, body)

	Header is tuple of column names. Body is a tuple of tuples.

	An example:
	
	>>> sql_run_raw('describe  django_migrations')
	(('Field', 'Type', 'Null', 'Key', 'Default', 'Extra'), ((u'id', u'int(11)', u'NO', u'PRI', None, u'auto_increment'), (u'app', u'varchar(255)', u'NO', u'', None, u''), (u'name', u'varchar(255)', u'NO', u'', None, u''), (u'applied', u'datetime', u'NO', u'', None, u'')))
	"""

	with connection.cursor() as cursor:
		cursor.execute(sql_command)
		return (
			() if cursor.description is None else tuple(col[0] for col in cursor.description),
			cursor.fetchall()
		)


class Sql_command(object):

	"""
	>>> sc = Sql_command("SELECT COUNT(*) FROM {m:results.Distance}")
	>>> sc.executed
	False
	>>> sc.translated
	u'SELECT COUNT(*) FROM `dist`'
	>>> sc.untranslated
	('SELECT COUNT(*) FROM {m:results.Distance}', None, None)
	>>> print sc.result
	None
	>>> print sc.column_names
	None
	>>> sc.run() # doctest: +ELLIPSIS
	<tools.dj_sql_tools.Sql_command object at ...>
	>>> sc.executed
	True
	>>> sc.result
	((1L,),)
	>>> sc.result_as_nt
	Traceback (most recent call last):
	ValueError: Type names and field names can only contain alphanumeric characters and underscores: 'COUNT(*)'
	>>> sc.result_as_dicts
	({'COUNT(*)': 1L},)
	>>> sc.column_names
	('COUNT(*)',)
	>>> sc.clear()
	>>> sc.executed
	False
	>>> print sc.result
	None
	>>> sc.result_as_dicts
	Traceback (most recent call last):
	AssertionError
	>>> sc.run() # doctest: +ELLIPSIS
	<tools.dj_sql_tools.Sql_command object at ...>
	>>> sc.result_as_dicts
	({'COUNT(*)': 1L},)

	Using named tuples (an example):
	>>> sc = Sql_command("SELECT COUNT(*) as cnt, MAX(dj_type) as max FROM {m:_}", "results", "Distance")
	>>> sc.run() # doctest: +ELLIPSIS
	<tools.dj_sql_tools.Sql_command object at ...>
	>>> sc.column_names
	('cnt', 'max')
	>>> nt = sc.result_as_nt
	>>> nt
	[SQL_res(cnt=1L, max=1)]
	>>> type(nt[0])
	<class 'tools.dj_sql_tools.SQL_res'>
	>>> nt[0][1]
	1
	>>> nt[0].max
	1

	SQL commands thouse do not return rows
	>>> sc = Sql_command('DROP TABLE IF EXISTS test_sql_comand').run()  # doctest: +ELLIPSIS
	>>> sc.column_names, sc.result
	((), ())
	>>> nt = sc.result_as_nt
	>>> nt
	[]
	>>> type(nt)
	<type 'list'>
	>>> dicts = sc.result_as_dicts
	>>> dicts
	()
	>>> type(dicts)
	<type 'tuple'>
	>>> sc = Sql_command('CREATE TABLE test_sql_comand (id smallint, name varchar(10))')
	>>> sc.run() # doctest: +ELLIPSIS
	<tools.dj_sql_tools.Sql_command object at ...>
	>>> sc.column_names, sc.result
	((), ())
	>>> sc = Sql_command("INSERT INTO test_sql_comand VALUES(5, 'qwe')").run()
	>>> sc.column_names, sc.result
	((), ())
	>>> sc = Sql_command("INSERT INTO test_sql_comand VALUES(6, 'abc')").run()
	>>> sc = Sql_command("SELECT * FROM test_sql_comand").run()
	>>> sc.column_names
	('id', 'name')
	>>> sc.result
	((5, u'qwe'), (6, u'abc'))
	>>> sc = Sql_command("UPDATE test_sql_comand SET name='x' WHERE id=6").run()
	>>> sc.column_names, sc.result
	((), ())
	>>> sc = Sql_command("SELECT * FROM test_sql_comand").run()
	>>> sc.column_names
	('id', 'name')
	>>> sc.result
	((5, u'qwe'), (6, u'x'))
	>>> sc = Sql_command("DELETE FROM test_sql_comand").run()
	>>> sc.column_names, sc.result
	((), ())
	>>> sc = Sql_command("SELECT * FROM test_sql_comand").run()
	>>> sc.column_names, sc.result
	(('id', 'name'), ())
	>>> sc = Sql_command("DROP TABLE test_sql_comand").run()
	>>> sc.column_names, sc.result
	((), ())
	"""

	def __init__(self, sql_command, default_app=None, default_model=None):
		self.untranslated = (sql_command, default_app, default_model)
		self.default_model = default_model
		self.default_app = default_app
		self.translated = sql_translate(sql_command, default_app, default_model)

		self.executed = False
		self.result = None
		self.column_names = None

	def run(self):
		self.column_names, self.result = sql_run_raw(self.translated)
		self.executed = True
		return self

	@property
	def result_as_nt(self):
		assert self.executed
		nt_result = namedtuple('SQL_res', self.column_names)
		return [nt_result(*row) for row in self.result]

	@property
	def result_as_dicts(self):
		assert self.executed
		return tuple(dict(list(zip(self.column_names, row))) for row in self.result)

	@property
	def count(self):
		assert self.executed
		return len(self.result)

	def clear(self):
		self.executed = False
		self.column_names = self.result = None

# end of class Sql_command


def sql_delete(model_name, where=None):
	sql_command = "DELETE FROM {{m:{}}}".format(model_name)
	if where is not None:
		sql_command += " WHERE " + where

	sql_command = sql_translate(sql_command, default_app='results')
	print('====')
	print(sql_command)
	print('\n===')
	with connection.cursor() as cursor:
			cursor.execute(sql_command)
			row = cursor.fetchall()
			print(row)


def sql_truncate(model_name):
	"""
	Fast deletion for a table not referenced in a foreign key constraint
	
	https://dev.mysql.com/doc/refman/5.5/en/truncate-table.html
	https://stackoverflow.com/questions/879327/quickest-way-to-delete-enormous-mysql-table
	"""

	sql_command = sql_translate("TRUNCATE {{m:{}}}".format(model_name), default_app='results')
	print('====')
	print(sql_command)
	print('\n===')
	with connection.cursor() as cursor:
			cursor.execute(sql_command)
			row = cursor.fetchall()
			print(row)
