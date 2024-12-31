from django.db import connection
import starrating.models
from starrating.constants import RADIX
from tools.dj_sql_tools import sql_delete, sql_translate
from tools.dj_meta import get_model_by_name
from .localtools import mk_aggr_structure_for_group
from starrating.aggr.aggr_utils import get_methods_specification, level_of_model


##################################################
# Some development and debug tools for Sr-system #
##################################################

def delete_aggregate_ratings(method):
	"""Delete all agregate rating records (X_by_param and X_overall, for X=user as well)

	If method == -1 deletes values created by all methods"""

	if isinstance(method, starrating.models.Method):
		method = method.id
	else:
		assert isinstance(method, int)

	if method == -1:
		for method_obj in starrating.models.Method.objects.all():
			method_obj.is_actual = False
			method_obj.save()
	else:
		where_str = "method_id=" + str(method)
		method_obj = starrating.models.Method.objects.get(id=method)
		method_obj.is_actual = False
		method_obj.save()

	inner_list = ('by_param', 'overall')
	if method == -1:
		inner_list = ('by_param_updated', 'overall_updated') + inner_list

	for x in 'User', 'Race', 'Event', 'Series', 'Organizer':
		for y in inner_list:
			model_name = "{}_{}".format(x, y)
			print("will delete",  model_name, "method=", method)
			if method == -1:
				sql_delete("starrating." + model_name)
			else:
				sql_delete("starrating." + model_name, where_str)

	for y in ('by_param', 'overall'):
		if method == -1:
			model_name = 'Root_{}_updated'.format(y)
			sql_delete("starrating." + model_name)
		for f in 'sum_int', 'sum_float', 'weight', 'user_count':
			model = get_model_by_name('starrating.Root_{}'.format(y))
			qs = model.objects.all()
			if  method != -1:
				qs = qs.filter(method_id=method)
			qs.update(**{f: 0})


def make_sentinel_root_data(method):
	if method == -1:
		for m_id in starrating.models.Method.objects.all().values_list(
			'pk', flat=True
		):
			make_sentinel_root_data(m_id)
		return

	lst = list(starrating.models.Root.objects.all())
	assert len(lst) <= 1
	if lst:
		root_id = lst[0].id
	else:
		root = starrating.models.Root()
		root.save()
		root_id = root.id
	assert root_id == 0

	starrating.models.Root_by_param.objects.filter(method_id=method).delete()
	starrating.models.Root_overall.objects.filter(method_id=method).delete()

	root_ov = starrating.models.Root_overall(
		rated_id=root_id,
		method_id=method,
		user_count=0,
		sum_int=0,
		sum_float=0,
	)
	root_ov.save()

	parameters = starrating.models.Parameter.objects.filter(to_calculate=True).values_list('id', flat=True)
	for par in parameters:
		starrating.models.Root_by_param.objects.create(
			overall_id=root_ov.id,
			parameter_id=par,
			method_id=method,
			user_count=0,
			sum_int=0,
			sum_float=0,
		)


def delete_sentinel_root_data(method_id):
	if method_id == -1:
		for m_id in starrating.models.Method.objects.all().values_list(
			'id', flat=True
		):
			delete_sentinel_root_data(m_id)
	else:
		starrating.models.Root_by_param.objects.filter(method_id=method_id).delete()
		starrating.models.Root_overall.objects.filter(method_id=method_id).delete()


def create_all_zero_records_for_metod(method):
	"""Fills all rating-aggregete models and User_overall.
	
	It fills models:
		from User_overall till Organizer_overall
	and
		from Race_by_param till Organizer_by_param
	according to existing and unhidden primary ratings (in Primary)
	"""

	delete_aggregate_ratings(method)

	make_sentinel_root_data(method)

	method_obj = starrating.models.Method.objects.get(id=method)
	method_obj.is_actual = True
	method_obj.save()

	method_spec = get_methods_specification(force=True)[method]

	sql_commands = []

	sql_organizer_overall = """
	INSERT into {{m:starrating.Organizer_overall}}
		(rated_id, method_id, id, weight, parent_id, user_count, {sum_field_name})
	(
	SELECT DISTINCT
		{{f:Organizer.id}}, {method}, {{f:Organizer.id}} * {radix} + {method}, 0, {method}, 0, 0
	FROM {{m:Organizer}}, {{m:Series}}, {{m:Event}}, {{m:Race}}, {{m:starrating.Group}}, {{m:starrating.Primary}}
	WHERE
		{{f:Organizer.id}} = {{f:Series.organizer_id}} and
		{{f:Series.id}} = {{f:Event.series_id}} and
		{{f:Event.id}} = {{f:Race.event_id}} and
		{{f:Race.id}} = {{f:starrating.Group.race_id}} and
		{{f:starrating.Group.id}} = {{f:starrating.Primary.group_id}} and
		{{f:starrating.Primary.is_hidden}} = 0
	)
	""".format(method=method, radix=RADIX,
		sum_field_name=method_spec[level_of_model('Organizer_overall')]['overall_field']
	)
	sql_commands.append(sql_organizer_overall)

	sql_series_overall = """
	INSERT into {{m:starrating.Series_overall}}
		(rated_id, method_id, id, weight, parent_id, user_count, {sum_field_name})
	(
	SELECT DISTINCT
		{{f:Series.id}},
		{method},
		{{f:Series.id}} * {radix} + {method},
		0,
		{{f:Series.organizer_id}} * {radix} + {method},
		0,
		0
	FROM {{m:Series}}, {{m:Event}}, {{m:Race}}, {{m:starrating.Group}}, {{m:starrating.Primary}}
	WHERE
		{{f:Series.id}} = {{f:Event.series_id}} and
		{{f:Event.id}} = {{f:Race.event_id}} and
		{{f:Race.id}} = {{f:starrating.Group.race_id}} and
		{{f:starrating.Group.id}} = {{f:starrating.Primary.group_id}} and
		{{f:starrating.Primary.is_hidden}} = 0
	)
	""".format(method=method, radix=RADIX,
		sum_field_name=method_spec[level_of_model('Series_overall')]['overall_field']
	)
	sql_commands.append(sql_series_overall)

	sql_event_overall = """
	INSERT into {{m:starrating.Event_overall}}
		(rated_id, method_id, id, parent_id, weight, user_count, {sum_field_name})
	(
	SELECT DISTINCT
		{{f:Event.id}}, {method}, {{f:Event.id}} * {radix} + {method}, {{f:Event.series_id}}*{radix}+{method}, 0, 0, 0
	FROM {{m:Event}}, {{m:Race}}, {{m:starrating.Group}}, {{m:starrating.Primary}}
	WHERE
		{{f:Event.id}} = {{f:Race.event_id}} and
		{{f:Race.id}} = {{f:starrating.Group.race_id}} and
		{{f:starrating.Group.id}} = {{f:starrating.Primary.group_id}} and
		{{f:starrating.Primary.is_hidden}} = 0
	)
	""".format(method=method, radix=RADIX,
		sum_field_name=method_spec[level_of_model('Event_overall')]['overall_field']
	)
	sql_commands.append(sql_event_overall)

	sql_race_overall = """
	INSERT into {{m:starrating.Race_overall}}
		(rated_id, method_id, id, parent_id, weight, user_count, {sum_field_name})
	(
	SELECT DISTINCT
		{{f:Race.id}}, {method}, {{f:Race.id}}*{radix} + {method}, {{f:Race.event_id}}*{radix} + {method}, 0, 0, 0
	FROM {{m:Race}}, {{m:starrating.Group}}, {{m:starrating.Primary}}
	WHERE 
		{{f:Race.id}} = {{f:starrating.Group.race_id}} and 
		{{f:starrating.Group.id}} = {{f:starrating.Primary.group_id}} and
		{{f:starrating.Primary.is_hidden}} = 0
	)
	""".format(method=method, radix=RADIX,
		sum_field_name=method_spec[level_of_model('Race_overall')]['overall_field']
	)
	sql_commands.append(sql_race_overall)

	sql_user_overall = """
	INSERT into {{m:starrating.User_overall}}
		(rated_id, method_id, id, parent_id, weight, user_count, {sum_field_name})
	(
	SELECT DISTINCT
		{{f:starrating.Group.id}}, {method}, {{f:starrating.Group.id}}*{radix} + {method}, {{f:starrating.Group.race_id}}*{radix} + {method}, 0, 1, 0
	FROM {{m:starrating.Group}}, {{m:starrating.Primary}}
	WHERE
		{{f:starrating.Group.id}} = {{f:starrating.Primary.group_id}} and
		{{f:starrating.Primary.is_hidden}} = 0
	)
	""".format(method=method, radix=RADIX,
		sum_field_name=method_spec[level_of_model('User_overall')]['overall_field']
	)
	sql_commands.append(sql_user_overall)

	sql_organizer_by_param = """
	INSERT INTO {{m:starrating.Organizer_by_param}}
		(overall_id, method_id, parameter_id, id, weight, parent_id, user_count, {sum_field_name})
	(
	SELECT DISTINCT
		{{f:starrating.Organizer_overall.id}},
		{method},
		{{f:starrating.Primary.parameter_id}},
		{{f:starrating.Organizer_overall.id}} * {radix} + {{f:starrating.Primary.parameter_id}},
		0,
		{method} * {radix} + {{f:starrating.Primary.parameter_id}},
		0,
		0
	FROM {{m:starrating.Organizer_overall}}, {{m:Series}}, {{m:Event}}, {{m:Race}}, {{m:starrating.Group}}, {{m:starrating.Primary}}
	WHERE
		{{f:starrating.Organizer_overall.method_id}} = {method} and
		{{f:starrating.Organizer_overall.rated_id}} = {{f:Series.organizer_id}} and
		{{f:Series.id}} = {{f:Event.series_id}} and
		{{f:Event.id}}  = {{f:Race.event_id}} and
		{{f:Race.id}}   = {{f:starrating.Group.race_id}} and
		{{f:starrating.Group.id}} = {{f:starrating.Primary.group_id}} and
		{{f:starrating.Primary.is_hidden}} = 0
	)
	""".format(method=method, radix=RADIX,
		sum_field_name=method_spec[level_of_model('Series_by_param')]['by_param_field']
	)
	sql_commands.append(sql_organizer_by_param)

	sql_series_by_param = """
	INSERT INTO {{m:starrating.Series_by_param}}
		(overall_id, method_id, parameter_id, id, weight, parent_id, user_count, {sum_field_name})
	(
	SELECT DISTINCT
		{{f:starrating.Series_overall.id}},
		{method},
		{{f:starrating.Primary.parameter_id}},
		{{f:starrating.Series_overall.id}} * {radix} + {{f:starrating.Primary.parameter_id}},
		0,
		{{f:starrating.Race_overall.parent_id}} * {radix} + {{f:starrating.Primary.parameter_id}},
		0,
		0
	FROM {{m:starrating.Series_overall}}, {{m:Event}}, {{m:Race}}, {{m:starrating.Group}}, {{m:starrating.Primary}}
	WHERE
		{{f:starrating.Series_overall.method_id}} = {method} and
		{{f:starrating.Series_overall.rated_id}} = {{f:Event.series_id}} and
		{{f:Event.id}} = {{f:Race.event_id}} and
		{{f:Race.id}} = {{f:starrating.Group.race_id}} and
		{{f:starrating.Group.id}} = {{f:starrating.Primary.group_id}} and
		{{f:starrating.Primary.is_hidden}} = 0
	)
	""".format(method=method, radix=RADIX,
		sum_field_name=method_spec[level_of_model('Series_by_param')]['by_param_field']
	)
	sql_commands.append(sql_series_by_param)

	sql_event_by_param = """
	INSERT INTO {{m:starrating.Event_by_param}}
		(overall_id, method_id, parameter_id, id, weight, parent_id, user_count, {sum_field_name})
	(
	SELECT DISTINCT
		{{f:starrating.Event_overall.id}},
		{method},
		{{f:starrating.Primary.parameter_id}},
		{{f:starrating.Event_overall.id}} * {radix} + {{f:starrating.Primary.parameter_id}},
		0,
		{{f:starrating.Event_overall.parent_id}} * {radix} + {{f:starrating.Primary.parameter_id}},
		0,
		0
	FROM {{m:starrating.Event_overall}}, {{m:Race}}, {{m:starrating.Group}}, {{m:starrating.Primary}}
	WHERE
		{{f:starrating.Event_overall.method_id}} = {method} and
		{{f:starrating.Event_overall.rated_id}} = {{f:Race.event_id}} and
		{{f:Race.id}} = {{f:starrating.Group.race_id}} and
		{{f:starrating.Group.id}} = {{f:starrating.Primary.group_id}} and
		{{f:starrating.Primary.is_hidden}} = 0
	)
	""".format(method=method, radix=RADIX,
		sum_field_name=method_spec[level_of_model('Event_by_param')]['by_param_field']
	)
	sql_commands.append(sql_event_by_param)

	sql_race_by_param = """
	INSERT INTO {{m:starrating.Race_by_param}}
		(overall_id, method_id, parameter_id, id, weight, parent_id, user_count, {sum_field_name})
	(
	SELECT DISTINCT
		{{f:starrating.Race_overall.id}},
		{method},
		{{f:starrating.Primary.parameter_id}},
		{{f:starrating.Race_overall.id}} * {radix} + {{f:starrating.Primary.parameter_id}},
		0,
		{{f:starrating.Race_overall.parent_id}} * {radix} +  {{f:starrating.Primary.parameter_id}},
		0,
		0
	FROM {{m:starrating.Race_overall}}, {{m:starrating.Group}}, {{m:starrating.Primary}}
	WHERE
		{{f:starrating.Race_overall.method_id}} = {method} and
		{{f:starrating.Race_overall.rated_id}} = {{f:starrating.Group.race_id}} and
		{{f:starrating.Group.id}} = {{f:starrating.Primary.group_id}} and
		{{f:starrating.Primary.is_hidden}} = 0
	)
	""".format(method=method, radix=RADIX,
		sum_field_name=method_spec[level_of_model('Race_by_param')]['by_param_field']
	)
	sql_commands.append(sql_race_by_param)

	sql_user_by_param = """
		INSERT INTO {{m:starrating.User_by_param}}
		(overall_id, method_id, parameter_id, id, on_primary_id, {sum_field_name}, weight, parent_id, user_count)
		(
		SELECT
			{{f:starrating.Group.id}} * {radix} + {method},
			{method},
			{{f:starrating.Primary.parameter_id}},
			({{f:starrating.Group.id}}*{radix}+{method}) * {radix} + {{f:starrating.Primary.parameter_id}},\
			{{f:starrating.Primary.id}},
			{{f:starrating.Primary.value}},
			1,
			({{f:starrating.Group.race_id}}*{radix}+{method}) * {radix} + {{f:starrating.Primary.parameter_id}},
			1
		FROM
			{{m:starrating.Primary}}, {{m:starrating.Group}}
		WHERE
			{{f:starrating.Primary.is_hidden}} = 0 and
			{{f:starrating.Primary.group_id}} = {{f:starrating.Group.id}}
		)
	""".format(radix=RADIX, method=method,
		sum_field_name=method_spec[level_of_model('User_by_param')]['by_param_field']
	)
	sql_commands.append(sql_user_by_param)

	with connection.cursor() as cursor:
		for s in sql_commands:
			sql_str = sql_translate(s, default_app='results')
			print('====')
			print(sql_str)
			print('\n===')
#			cursor.execute("EXPLAIN " + sql_str)
#			row = cursor.fetchall()
#			print row
			cursor.execute(sql_str)
			row = cursor.fetchall()
			print(row)


def create_all_zero_records_for_metod_one_by_one(method):
	method_obj = starrating.models.Method.objects.get(id=method)
	method_obj.is_actual = True
	method_obj.save()

	import random
	groups = list(starrating.models.Group.objects.all().values_list('id', flat=True))
	random.seed(123)
	random.shuffle(groups)
	for group in groups:
		mk_aggr_structure_for_group(group, method_id=method)


def make_fake_aggregate_values_for_method(method):
	"""Is needed for test purposes: we must have records for more then 2 methods"""
	with connection.cursor() as cursor:
		for x in 'Race', 'Event', 'Series', 'Organizer':
			for y in 'by_param', 'overall':
				sql_command = """
				UPDATE {{m:starrating.{x}_{y}}}
				SET
					sum_int = 20,
					sum_float = 21,
					weight = {method} * 10,
					user_count = 10
				WHERE {{f:starrating.{x}_{y}.method_id}}={method}
				""".format(x=x, y=y, method=method)
				
				sql_command = sql_translate(sql_command)
				print('====')
				print(sql_command)
				print('\n===')
				cursor.execute(sql_command)
				row = cursor.fetchall()
				print(row)


def calculate_aggregate_values_for_method(method):

# For starrating.Race_by_param we have to sql-queries - by REPLACE and by UPDATE
# The second is more efficient.

	sql_commands = []

	# By REPLACE - not really used here
	sql_calculate_race_by_param = """
	REPLACE INTO {{m:starrating.Race_by_param}}
		(overall_id, parameter_id, id, weight, starrating.Event_by_param_id, sum_int)
	(
	SELECT
		{{f:starrating.Race_overall.id}},
		{{f:starrating.Primary.parameter_id}},
		{{f:starrating.Race_overall.id}} * {radix} + {{f:starrating.Primary.parameter_id}},
		COUNT({{f:starrating.Primary.id}}),
		{{f:starrating.Race_overall.starrating.Event_overall_id}} * {radix} +  {{f:starrating.Primary.parameter_id}},
		SUM({{f:starrating.Primary.value}})
	FROM {{m:starrating.Race_overall}}, {{m:starrating.Group}}, {{m:starrating.Primary}}
	WHERE
		{{f:starrating.Race_overall.method_id}}={method} and
		{{f:starrating.Race_overall.rated_id}} = {{f:starrating.Group.race_id}} and
		{{f:starrating.Group.id}} = {{f:starrating.Primary.group_id}} and
		{{f:starrating.Primary.is_hidden}} = 0
	GROUP BY {{f:starrating.Group.race_id}}, {{f:starrating.Primary.parameter_id}}
	)
	""".format(method=method, radix=RADIX)

	# By UPDATE, but withount starrating.User_by_param - not really used here
	sql_calculate_race_by_param  = """
	UPDATE {{m:starrating.Race_by_param}}, {{m:starrating.Race_overall}}
	SET
		{{f:starrating.Race_by_param.weight}} = 
		(
		SELECT COUNT({{f:starrating.Primary.id}})
		FROM {{m:starrating.Primary}}, {{m:starrating.Group}}
		WHERE
			{{f:starrating.Primary.parameter_id}} = {{f:starrating.Race_by_param.parameter_id}} and
			{{f:starrating.Primary.group_id}} = {{f:starrating.Group.id}} and
			{{f:starrating.Group.race_id}} = {{f:starrating.Race_overall.rated_id}}
		),
		{{f:starrating.Race_by_param.sum_int}} =
		(
		SELECT SUM({{f:starrating.Primary.value}})
		FROM {{m:starrating.Primary}}, {{m:starrating.Group}}
		WHERE
			{{f:starrating.Primary.parameter_id}} = {{f:starrating.Race_by_param.parameter_id}} and
			{{f:starrating.Primary.group_id}} = {{f:starrating.Group.id}} and
			{{f:starrating.Group.race_id}} = {{f:starrating.Race_overall.rated_id}}
		)
	WHERE
		{{f:starrating.Race_by_param.overall_id}} = {{f:starrating.Race_overall.id}} and
		{{f:starrating.Race_overall.method_id}} = {method}
	""".format(method=method)
#	sql_commands.append(sql_calculate_race_by_param)

	# By UPDATE, with starrating.User_by_param
	sql_calculate_race_by_param  = """
	UPDATE {{m:starrating.Race_by_param}}, {{m:starrating.Race_overall}}
	SET
		{{f:starrating.Race_by_param.weight}} =
		(
		SELECT COUNT({{f:starrating.User_by_param.id}})
		FROM {{m:starrating.User_by_param}}
		WHERE {{f:starrating.User_by_param.parent_id}}={{f:starrating.Race_by_param.id}}
		),
		{{f:starrating.Race_by_param.sum_int}} =
		(
		SELECT SUM({{f:starrating.User_by_param.sum_int}})
		FROM {{m:starrating.User_by_param}}
		WHERE {{f:starrating.User_by_param.parent_id}}={{f:starrating.Race_by_param.id}}
		),
		{{f:starrating.Race_by_param.user_count}} =
		(
		SELECT SUM({{f:starrating.User_by_param.user_count}})
		FROM {{m:starrating.User_by_param}}
		WHERE {{f:starrating.User_by_param.parent_id}}={{f:starrating.Race_by_param.id}}
		)
	WHERE
		{{f:starrating.Race_by_param.overall_id}} = {{f:starrating.Race_overall.id}} and
		{{f:starrating.Race_overall.method_id}} = {method}
	""".format(method=method)
	sql_commands.append(sql_calculate_race_by_param)

	sql_calculate_event_by_param  = """
	UPDATE {{m:starrating.Event_by_param}}, {{m:starrating.Event_overall}}
	SET
		{{f:starrating.Event_by_param.weight}} =
		(
		SELECT COUNT({{f:starrating.Race_by_param.id}})
		FROM {{m:starrating.Race_by_param}}
		WHERE {{f:starrating.Race_by_param.parent_id}}={{f:starrating.Event_by_param.id}}
		),
		{{f:starrating.Event_by_param.sum_float}} =
		(
		SELECT SUM({{f:starrating.Race_by_param.sum_int}}*1.0 / {{f:starrating.Race_by_param.weight}})
		FROM {{m:starrating.Race_by_param}}
		WHERE {{f:starrating.Race_by_param.parent_id}}={{f:starrating.Event_by_param.id}}
		),
		{{f:starrating.Event_by_param.user_count}} =
		(
		SELECT SUM({{f:starrating.Race_by_param.user_count}})
		FROM {{m:starrating.Race_by_param}}
		WHERE {{f:starrating.Race_by_param.parent_id}}={{f:starrating.Event_by_param.id}}
		)
	WHERE
		{{f:starrating.Event_by_param.overall_id}} = {{f:starrating.Event_overall.id}} and
		{{f:starrating.Event_overall.method_id}} = {method}
	""".format(method=method)
	sql_commands.append(sql_calculate_event_by_param)

	sql_calculate_series_by_param  = """
	UPDATE {{m:starrating.Series_by_param}}, {{m:starrating.Series_overall}}
	SET
		{{f:starrating.Series_by_param.weight}} =
		(
		SELECT COUNT({{f:starrating.Event_by_param.id}})
		FROM {{m:starrating.Event_by_param}}
		WHERE {{f:starrating.Event_by_param.parent_id}}={{f:starrating.Series_by_param.id}}
		),
		{{f:starrating.Series_by_param.sum_float}} =
		(
		SELECT SUM({{f:starrating.Event_by_param.sum_float}}*1.0 / {{f:starrating.Event_by_param.weight}})
		FROM {{m:starrating.Event_by_param}}
		WHERE {{f:starrating.Event_by_param.parent_id}}={{f:starrating.Series_by_param.id}}
		),
		{{f:starrating.Series_by_param.user_count}} =
		(
		SELECT SUM({{f:starrating.Event_by_param.user_count}})
		FROM {{m:starrating.Event_by_param}}
		WHERE {{f:starrating.Event_by_param.parent_id}}={{f:starrating.Series_by_param.id}}
		)
	WHERE
		{{f:starrating.Series_by_param.overall_id}} = {{f:starrating.Series_overall.id}} and
		{{f:starrating.Series_overall.method_id}} = {method}
	""".format(method=method)
	sql_commands.append(sql_calculate_series_by_param)

#	sql_calculate_organizer_by_param  - not implemented yet
#	sql_commands.append(sql_calculate_organizer_by_param)

	# With starrating.User_by_param
	sql_calculate_user_overall = """
	UPDATE {{m:starrating.User_overall}}
	SET
		{{f:starrating.User_overall.weight}} = 
			(
			SELECT COUNT({{f:starrating.User_by_param.id}})
			FROM {{m:starrating.User_by_param}}
			WHERE {{f:starrating.User_by_param.overall_id}} = {{f:starrating.User_overall.id}}
			),
		{{f:starrating.User_overall.sum_int}} = 
			(
			SELECT SUM({{f:starrating.User_by_param.sum_int}})
			FROM {{m:starrating.User_by_param}}
			WHERE {{f:starrating.User_by_param.overall_id}} = {{f:starrating.User_overall.id}}
			)
	WHERE {{f:starrating.User_overall.method_id}} = {method}
	""".format(method=method)
	sql_commands.append(sql_calculate_user_overall)

	# Without starrating.User_by_param, not used here
	sql_calculate_user_overall = """
	UPDATE {{m:starrating.User_overall}}
	SET
		{{f:starrating.User_overall.weight}} =
			(
			SELECT COUNT({{f:starrating.Primary.id}})
			FROM {{m:starrating.Primary}}
			WHERE
				{{f:starrating.User_overall.rated_id}} = {{f:starrating.Primary.group_id}} and
				{{f:starrating.Primary.is_hidden}} = 0
			),
		{{f:starrating.User_overall.sum_int}} =
			(
			SELECT SUM({{f:starrating.Primary.value}})
			FROM {{m:starrating.Primary}}
			WHERE
				{{f:starrating.User_overall.rated_id}} = {{f:starrating.Primary.group_id}} and
				{{f:starrating.Primary.is_hidden}} = 0
			)
	WHERE {{f:starrating.User_overall.method_id}} = {method}
	""".format(method=method)
#	sql_commands.append(sql_calculate_user_overall)

	sql_calculate_race_overall = """
	UPDATE {{m:starrating.Race_overall}}
	SET
		{{f:starrating.Race_overall.weight}} =
			(
			SELECT SUM({{f:starrating.User_overall.weight}})
			FROM {{m:starrating.User_overall}}
			WHERE
				{{f:starrating.User_overall.parent_id}} = {{f:starrating.Race_overall.id}}
			),
		{{f:starrating.Race_overall.sum_int}} =
			(
			SELECT SUM({{f:starrating.User_overall.sum_int}})
			FROM {{m:starrating.User_overall}}
			WHERE
				{{f:starrating.User_overall.parent_id}} = {{f:starrating.Race_overall.id}}
			),
		{{f:starrating.Race_overall.user_count}} =
			(
			SELECT SUM({{f:starrating.User_overall.user_count}})
			FROM {{m:starrating.User_overall}}
			WHERE
				{{f:starrating.User_overall.parent_id}} = {{f:starrating.Race_overall.id}}
			)
	WHERE {{f:starrating.Race_overall.method_id}} = {method}
	""".format(method=method)
	sql_commands.append(sql_calculate_race_overall)

	sql_calculate_event_overall = """
	UPDATE {{m:starrating.Event_overall}}
	SET
		{{f:starrating.Event_overall.weight}} =
			(
			SELECT COUNT({{f:starrating.Race_overall.id}})
			FROM {{m:starrating.Race_overall}}
			WHERE
				{{f:starrating.Race_overall.parent_id}} = {{f:starrating.Event_overall.id}}
			),
		{{f:starrating.Event_overall.sum_float}} =
			(
			SELECT SUM({{f:starrating.Race_overall.sum_int}}*1.0 / {{f:starrating.Race_overall.weight}})
			FROM {{m:starrating.Race_overall}}
			WHERE
				{{f:starrating.Race_overall.parent_id}} = {{f:starrating.Event_overall.id}}
			),
		{{f:starrating.Event_overall.user_count}} =
			(
			SELECT SUM({{f:starrating.Race_overall.user_count}})
			FROM {{m:starrating.Race_overall}}
			WHERE
				{{f:starrating.Race_overall.parent_id}} = {{f:starrating.Event_overall.id}}
			)
	WHERE {{f:starrating.Event_overall.method_id}} = {method}
	""".format(method=method)
	sql_commands.append(sql_calculate_event_overall)

	sql_calculate_series_overall = """
	UPDATE {{m:starrating.Series_overall}}
	SET
		{{f:starrating.Series_overall.weight}} =
			(
			SELECT COUNT({{f:starrating.Event_overall.id}})
			FROM {{m:starrating.Event_overall}}
			WHERE
				{{f:starrating.Event_overall.parent_id}} = {{f:starrating.Series_overall.id}}
			),
		{{f:starrating.Series_overall.sum_float}} =
			(
			SELECT SUM({{f:starrating.Event_overall.sum_float}}*1.0 / {{f:starrating.Event_overall.weight}})
			FROM {{m:starrating.Event_overall}}
			WHERE
				{{f:starrating.Event_overall.parent_id}} = {{f:starrating.Series_overall.id}}
			),
		{{f:starrating.Series_overall.user_count}} =
			(
			SELECT SUM({{f:starrating.Event_overall.user_count}})
			FROM {{m:starrating.Event_overall}}
			WHERE
				{{f:starrating.Event_overall.parent_id}} = {{f:starrating.Series_overall.id}}
			)
	WHERE {{f:starrating.Series_overall.method_id}} = {method}
	""".format(method=method)
	sql_commands.append(sql_calculate_series_overall)

#	sql_calculate_organizer_overall -- not implemented yet
#	sql_commands.append(sql_calculate_organizer_overall)

	with connection.cursor() as cursor:
		for s in sql_commands:
			sql_str =  sql_translate(s)
			print('====')
			print(sql_str)
			print('\n===')
			cursor.execute(sql_str)
			row = cursor.fetchall()
			print(row)
