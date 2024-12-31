import logging
from django.db.models import F, Max
import results.models
from starrating import models
from starrating.constants import RADIX, DJANGO_MAX_INT
from tools.math3 import isclose
from tools.other import log_if_logger
from dbchecks.dbchecks import Relationship_checker, Sql_empty_checker, Equality_checker, \
	check_relationships2, Not_null_checker, Queryset_empty_checker, \
	check_relationships2_for_app, Set_equality_checker
from .aggr_utils import updated_queryset, get_upd_model, get_model_by_name

##########################################
# Some checks for structure of SR-models #
##########################################

count = error_count = warn_count = upd_count = 0

def check_all_primary_are_used_by_method(
			method,
			logger=None,
			log_level_ok=logging.DEBUG,
			log_level_error=logging.ERROR,
			log_level_info=logging.INFO,
			result_list=None,
			comment=None,
			nothing_if_ok=True
		):

	log_if_logger(
			logger,
			log_level_info,
			"check_all_primary_are_used_by_method({}) started".format(method)
		)

	if result_list is None:
		lst = []
	else:
		lst = result_list

	# This is too slow, not used here
	sql_str = """
		SELECT id
		FROM (SELECT id from {{m:starrating.Primary}} WHERE is_hidden = 0) P
		LEFT JOIN
			(
				SELECT on_primary_id
				FROM {{m:starrating.User_by_param}}
				WHERE method_id={method}
			) UPM
		ON UPM.on_primary_id = P.id
		WHERE UPM.on_primary_id is NULL
		""".format(method=method)

#		SELECT {{f:starrating.Primary.id}}
	sql_str = """
		FROM {{m:starrating.Primary}}
		WHERE
			{{f:starrating.Primary.is_hidden}} = 0 and
			{{f:starrating.Primary.group_id}} NOT IN (SELECT id FROM {{m:starrating.Group_new}}) and
			{{f:starrating.Primary.id}} NOT IN
				(SELECT on_primary_id FROM {{m:starrating.User_by_param}} WHERE method_id={method})
		""".format(method=method)

	checker = Sql_empty_checker(sql_str).run()
	checker.log(
			logger,
			log_level_ok,
			log_level_error,
			"check_all_primary_are_used_by_method({})".format(method)
		)
	if not checker.is_ok:
		lst.append({
				'checker': 'all_primary_are_used_by_method',
				'counts': checker.count,
				'sql':  checker.sql_translated_listing_command()
			})
	elif not nothing_if_ok:
		lst.append({'checker': 'all_primary_are_used_by_method'})

	if result_list is None:
		return lst

# /def check_all_primary_are_used_by_method(method)


def check_relationship_structure_of_aggregate_models(
			fast=False,
			logger=None,
			log_level_ok=logging.DEBUG,
			log_level_error=logging.ERROR,
			log_level_info=logging.INFO,
			nothing_if_ok = True
		):

	'''
	TODO for rated_tree_modifications

	Нет методов с нечетными номерами

	При наличии updated-записей с нижележащими должны быть согласованы они, а не
	основные записи  -> check_method_9()

	У overall rated=None только если есть задание на удаление

	Согласованность заданий на удаление: все нули в overall_updated и by_param_updated

	Поправить
	Equality_checker(models.Event_overall, 'rated__series_id', 'parent__rated_id').shortcut1(**shortcut1_args)
	с учетом rated=None

	'''

	base_model_names = ['User', 'Race', 'Event', 'Series', 'Organizer', 'Root']

	result_list = []
	shortcut1_args = dict(
			logger=logger,
			log_level_ok=log_level_ok,
			log_level_error=log_level_error,
			result_list=result_list,
			nothing_if_ok=nothing_if_ok
		)

	log_if_logger(logger, log_level_info, 'check_relationship_structure_of_aggregate_models started')

	# Checking max ids
	max_rated_id = max([
		get_model_by_name('results.'+bmn).objects.aggregate(max_id=Max('id'))['max_id']
		for bmn in base_model_names if bmn not in ('User', 'Root')
	])

	max_group_id = models.Group.objects.aggregate(max_id=Max('id'))['max_id']
	safe_max_id = DJANGO_MAX_INT // (RADIX * RADIX) * 3 // 4
	log_if_logger(
		logger,
		log_level_info,
		'checking max_ids: max_rated_id={}, max_group_id={}, safe_max_id={}'.format(
			max_rated_id, max_group_id, safe_max_id
		)
	)
	if max_group_id > safe_max_id:
		message = 'max_group_id={} > safe_max_id={}'.format(max_group_id, safe_max_id)
		log_if_logger(logger, log_level_error, message)
		result_list.append(dict(subject='max_group_id check', comment=message))
	if max_rated_id > safe_max_id:
		message = 'max_rated_id={} > safe_max_id={}'.format(max_rated_id, safe_max_id)
		log_if_logger(logger, log_level_error, message)
		result_list.append(dict(subject='max_rated_id check', comment=message))

	app_name = 'starrating'

	if fast:
		log_if_logger(logger, log_level_info, "Fast mode: race and user fields of Result are not checked")
	else:
		log_if_logger(logger, log_level_info, "Non-fast mode: will check race and user fields of Result...")
		Relationship_checker(results.models.Result, 'race').shortcut1(**shortcut1_args)
		Relationship_checker(results.models.Result, 'user').shortcut1(**shortcut1_args)

	check_relationships2_for_app(app_name, log_level_info=log_level_info, **shortcut1_args)

	log_if_logger(logger, log_level_info, 'For actual methods will call check_all_primary_are_used_by_method')
	for method in models.Method.objects.filter(is_actual=True).values_list('id', flat=True):
		check_all_primary_are_used_by_method(
				method,
				**shortcut1_args
			)

	Queryset_empty_checker(
		models.User_overall.objects.filter(
			rated__in=models.Group_new.objects.all().values('id')
		).only(
			'id', 'method', 'rated_id'
		),
		'No User_overall records for new groups'
	).shortcut1(**shortcut1_args)

	Equality_checker(models.User_by_param_updated, 'id__sum_int', 0, False).shortcut1(**shortcut1_args)
	Equality_checker(models.User_by_param_updated, 'id__user_count', 0, False).shortcut1(**shortcut1_args)
	Equality_checker(models.User_by_param_updated, 'id__weight', 0, False).shortcut1(**shortcut1_args)

	Equality_checker(
			models.Organizer_overall,
			'method__is_actual',
			True,
			value2_is_field_name=False
		).shortcut1(**shortcut1_args)

	for model in base_model_names:
		check_relationships2(model, log_level_info=log_level_info, **shortcut1_args)

	for x in base_model_names:
		for y in 'by_param', 'overall':
			model = "{}_{}".format(x, y)
			Not_null_checker(model, 'user_count').shortcut1(**shortcut1_args)
			if x != 'Root':
				Equality_checker(model, 'method_id', 'parent__method_id').shortcut1(**shortcut1_args)

	for x in base_model_names:
		model = "{}_by_param".format(x)
		if x != 'Root':
			Equality_checker(model, 'parameter_id', 'parent__parameter_id').shortcut1(**shortcut1_args)
			Equality_checker(model, 'overall__parent_id', 'parent__overall_id').shortcut1(**shortcut1_args)
		Equality_checker(model, 'method_id', 'overall__method_id').shortcut1(**shortcut1_args)
		Equality_checker(
			model,
			'id',
			F('overall_id') * RADIX + F('parameter_id'),
			False
		).shortcut1(**shortcut1_args)
		Equality_checker(model, 'parameter__to_calculate', True, value2_is_field_name=False).shortcut1(**shortcut1_args)

		model = "{}_overall".format(x)
		Equality_checker(
			model,
			'id',
			F('rated_id') * RADIX + F('method_id'),
			False
		).shortcut1(**shortcut1_args)

	for x in base_model_names:
		model_by_param_updated = "{}_by_param_updated".format(x)
		model_overall_updated = "{}_overall_updated".format(x)
		Set_equality_checker(
			model_by_param_updated, 'id__overall_id',
			model_overall_updated, 'id_id',
			'{} and {} consistency'.format(
				model_by_param_updated,
				model_overall_updated
			)
		).shortcut1(**shortcut1_args)

	Equality_checker(
			models.Primary,
			'id',
			F('group_id') * RADIX + F('parameter_id'),
			False
		).shortcut1(**shortcut1_args)

	Equality_checker(
			models.User_by_param,
			'on_primary_id',
			(F('id') - F('id') % (RADIX*RADIX)) / (RADIX*RADIX) * RADIX + F('parameter_id'),
			False
		).shortcut1(**shortcut1_args)

	Equality_checker(models.Root_overall, 'rated_id', 0, False).shortcut1(**shortcut1_args)
	Equality_checker(models.Series_overall, 'rated__organizer_id', 'parent__rated_id').shortcut1(**shortcut1_args)
	Equality_checker(models.Event_overall, 'rated__series_id', 'parent__rated_id').shortcut1(**shortcut1_args)
	Equality_checker(models.Race_overall, 'rated__event_id', 'parent__rated_id').shortcut1(**shortcut1_args)
	Equality_checker(models.User_overall, 'rated__race_id', 'parent__rated_id').shortcut1(**shortcut1_args)

	Equality_checker(models.User_by_param, 'overall__rated_id', 'on_primary__group_id').shortcut1(**shortcut1_args)
	Equality_checker(models.User_by_param, 'parameter_id', 'on_primary__parameter_id',).shortcut1(**shortcut1_args)
	Equality_checker(models.User_by_param, 'on_primary__is_hidden', False, value2_is_field_name=False).shortcut1(**shortcut1_args)

	Equality_checker(models.Primary, 'group__is_empty', False, value2_is_field_name=False).shortcut1(**shortcut1_args)
	Queryset_empty_checker(
		models.Group.objects.filter(
			is_empty=False
		).exclude(
			id__in=models.Primary.objects.all().values('group_id').distinct()
		),
		'Group: all groups marked non-empty realy has related records in the Primary model'
	).shortcut1(**shortcut1_args)

#	Equality_checker(models.User_by_param, 'sum_int', 'on_primary__value').shortcut1(**shortcut1_args)
	Queryset_empty_checker(
		updated_queryset(models.User_by_param, 'sum_int', 's').exclude(
			s=F('on_primary__value')
		),
		'User_by_param: (update.sum_int or sum_int) == F("on_primary__value")'
	).shortcut1(**shortcut1_args)

#	Equality_checker(models.User_by_param, 'user_count', 1, value2_is_field_name=False).shortcut1(**shortcut1_args)
	Queryset_empty_checker(
		updated_queryset(models.User_by_param, 'user_count', 'u').exclude(u=1),
		'User_by_param: (update.user_count or user_count) == 1'
	).shortcut1(**shortcut1_args)

#	Equality_checker(models.User_by_param, 'weight', 1, value2_is_field_name=False).shortcut1(**shortcut1_args)
	Queryset_empty_checker(
		updated_queryset(models.User_by_param, 'weight', 'w').exclude(w=1),
		'User_by_param: (update.weight or weight) == 1'
	).shortcut1(**shortcut1_args)

#	Equality_checker(models.User_overall, 'user_count', 1, value2_is_field_name=False).shortcut1(**shortcut1_args)
	Queryset_empty_checker(
		updated_queryset(models.User_overall, 'user_count', 'u').exclude(u=1),
		'User_overall: (update.user_count or user_count) == 1'
	).shortcut1(**shortcut1_args)

	Set_equality_checker(
		'auth.User', 'id',
		'results.User_profile', 'user_id',
		'Sets of user_ids in auth.User and results.User_profile are equal',
	).shortcut1(**shortcut1_args)

	log_if_logger(logger, log_level_info, 'check_relationship_structure_of_aggregate_models finished')

	return result_list

	# May be todo: there are no records without childs; there are no overall recorde w/o by_param...

# /def check_relationship_structure_of_aggregate_models()


#####################################
# Some very slow checks for SR-data #
#####################################

SHOW_EACH = 10


def check_simple_avg(node):
	global count
	global error_count
	global warn_count
	count += 1

	sum1 = node.sum_int if node.sum_int is not None else node.sum_float
	weight1 = node.weight

#	if type(node) == models.Race_by_param:
#		children = models.User_by_param.objects.filter(parent_id=node.id).only('sum_int', 'sum_float', 'weight')
#	else:
	if 1:
		children = node.child.all().only('sum_int', 'sum_float', 'weight')

	err_flag = False

	try:
		if children[0].sum_int is not None:
			sum2 = sum([float(x.sum_int)/x.weight for x in children])
		else:
			sum2 = sum([x.sum_float/x.weight for x in children])
	except TypeError:
		err_flag = True
		sum2 = 'x'
	except ZeroDivisionError:
		err_flag = True
		sum2 = '(x/0)'

	weight2 = len(children)

	if err_flag or not (isclose(sum1, sum2) and isclose(weight1, weight2)):
		error_count += 1
		print(type(node), node.id)
		print("Хранится: {}/{}; вычислено: {}/{}".format(sum1, weight1, sum2, weight2))
	elif count % SHOW_EACH == 0:
		print(count, type(node), node.id, "(was errors:", error_count, ") - OK")


def check_direct_sum(node):
	global count
	global error_count
	global warn_count
	count += 1

	sum1 = node.sum_int if node.sum_int is not None else node.sum_float
	weight1 = node.weight

	children = node.child.all().only('sum_int', 'sum_float', 'weight')

	err_flag = 0

	if sum1 is None:
		err_flag = 2  # error
		sum1 = 'x'

	if weight1 is None:
		err_flag = 2  # error
		weight1 = 'x'

	try:
		if children[0].sum_int is not None:
			sum2 = sum([x.sum_int for x in children])
		else:
			sum2 = sum([x.sum_float for x in children])
	except (TypeError, IndexError):
		if sum1 != 0 or err_flag == 2:
			err_flag = 2  # error
		else:
			err_flag = 1  # warning
		sum2 = 'x'

	weight2 = sum([x.weight for x in children])

	if err_flag or not (isclose(sum1, sum2) and isclose(weight1, weight2)):
		if err_flag == 1:
			warn_count += 1
		else:
			error_count += 1
		print(type(node), node.id, "WARNING" if err_flag == 1 else "ERROR")
		print("Хранится: {}/{}; вычислено: {}/{}".format(sum1, weight1, sum2, weight2))
	elif count % SHOW_EACH == 0:
		print(count, type(node), node.id, "(was errors:", error_count, ") - OK")


def check_direct_sum_int_upd(node, upd_node):
	global count
	global error_count
	global warn_count
	global upd_count
	count += 1

	children = node.child.all().only('sum_int', 'weight', 'user_count')

	if upd_node is not None:
		upd_count += 1
		node = upd_node

	sum1 = node.sum_int
	weight1 = node.weight
	user_count1 = node.user_count

	err_flag = False
	warn_flag = False
	warning = ''

	if sum1 is None:
		warn_flag = True
		warning += "sum_int is NULL "
		sum1 = 0

	if weight1 is None:
		err_flag = True
		weight1 = 'x'

	if user_count1 is None:
		err_flag = True
		user_count1 = 'x'

	try:
		sum2 = sum([x.sum_int for x in children])
	except TypeError:
		sum2 = sum([x.sum_int for x in children if x.sum_int is not None])
		warn_flag = True
		warning += "Some child's sum_int is NULL"
	try:
		weight2 = sum([x.weight for x in children])
	except TypeError:
		weight2 = 'x'
		err_flag = True
	try:
		user_count2 = sum([x.user_count for x in children])
	except TypeError:
		user_count2 = 'x'
		err_flag = True

	if err_flag or not ((sum1 == sum2) and (weight1 == weight2) and (user_count1 == user_count2)):
		error_count += 1
		print(type(node), node.id, "ERROR")
		print("Хранится: {}/{} ({}); вычислено: {}/{} ({})".format(
			sum1, weight1, user_count1, sum2, weight2, user_count2
		))
	elif warn_flag or not all([sum1, weight1, user_count1]):
		warn_count += 1
		print(type(node), node.id, "WARNINIG: " + warning)
		print("Хранится: {}/{} ({}); вычислено: {}/{} ({})".format(
			sum1, weight1, user_count1, sum2, weight2, user_count2
		))
	elif count % SHOW_EACH == 0:
		print(count, type(node), node.id, "(errors: {}, warnings: {}, updates: {}) - OK".format(
			error_count, warn_count, upd_count))



def check_user_count(node):
	global count
	global error_count
	global warn_count
	count += 1

	user_count1 = node.user_count

	children = node.child.all().only('user_count')

	err_flag = False

	user_count2 = sum([x.user_count for x in children])

	if err_flag or user_count1 != user_count2:
		error_count += 1
		print(type(node), node.id)
		print("user_count. Хранится: {}; вычислено: {}".format(user_count1, user_count2))
	elif count % SHOW_EACH == 0:
		print(count, type(node), node.id, "(was errors:", error_count, ") - OK")


def check_avg_of_primaries_for_race_overall(node, upd_node):
	global count
	global error_count
	global warn_count
	count += 1

	all_primary = models.Primary.objects.filter(is_hidden=0, group__race_id=node.rated_id).only('value')

	if upd_node is not None:
		node = upd_node

	sum1 = node.sum_int if node.sum_int is not None else node.sum_float
	weight1 = node.weight

	sum2 = sum([x.value for x in all_primary])
	weight2 = len(all_primary)

	err_flag = False
	if sum1 is None:
		sum1 = 'x'
		err_flag = True
	if weight1 is None:
		weight1 = 'x'
		err_flag = True
	if err_flag or not (isclose(sum1, sum2) and isclose(weight1, weight2)):
		error_count += 1
		print(type(node), node.id)
		print("Хранится: {}/{}; вычислено: {}/{}".format(sum1, weight1, sum2, weight2))
	elif count % SHOW_EACH == 0:
		print(count, type(node), node.id, "(was errors:", error_count, ") - OK")


def check_method_1(show_each=None):
	global count
	global error_count
	global warn_count
	count = 0
	error_count = 0
	global SHOW_EACH
	SHOW_EACH = show_each or SHOW_EACH

	# Wrong number of arguments
	# for item in models.Race_overall.objects.filter(method_id=1).only('id', 'sum_int', 'sum_float', 'weight', 'rated_id'):
	# 	check_avg_of_primaries_for_race_overall(item)

	for x in 'Root', 'Organizer', 'Series', 'Event', 'Race':
		for y in 'overall', 'by_param':
			model_name = "{}_{}".format(x, y)
			if model_name == "Race_overall":
				continue   # Here another algorithn is applied
			model = getattr(models, model_name)
			for item in model.objects.filter(method_id=1).only('id', 'sum_int', 'sum_float', 'weight'):
				check_simple_avg(item)


def check_method_9(show_each=None):
	print('check_method_9')
	global count
	global error_count
	global warn_count
	global upd_count
	count = error_count = warn_count = upd_count = 0
	global SHOW_EACH
	SHOW_EACH = show_each or SHOW_EACH

#	for item in models.Race_overall.objects.filter(method_id=9).only('id', 'sum_int', 'sum_float', 'weight', 'rated_id'):
#		check_avg_of_primaries_for_race_overall(
#			item,
#			models.Race_overall_updated.objects.filter(pk=item.pk).first()
#		)

	for x in 'Root', 'Organizer', 'Series', 'Event', 'Race':
		for y in 'overall', 'by_param':
			model_name = "{}_{}".format(x, y)
#			if model_name == "Race_overall":
#				continue   # Here another algorithn is applied
			model = getattr(models, model_name)
			upd_model = get_upd_model(model)
			for item in model.objects.filter(method_id=9).only('id', 'sum_int', 'sum_float', 'weight'):
				check_direct_sum_int_upd(item, upd_model.objects.filter(pk=item.pk).first())

	print("END. (errors: {}, warnings: {}, updates: {}) - OK".format(
		error_count, warn_count, upd_count
	))
