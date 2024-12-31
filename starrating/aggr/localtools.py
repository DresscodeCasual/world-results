from django.db.models import Subquery, OuterRef
from django.db import transaction

from tools.dj_meta import get_model_by_name
from tools.dj_other import queryset_to_dict
from tools.flock_mutex import Flock_mutex
from results.models import Race, Event, Series, Organizer

from starrating.models import \
	Root, Group, Group_new, \
	Aggregate_abstract_model, Overall_abstract_model, Overall_updated_abstract_model, \
	User_overall, User_overall_updated, User_by_param_updated, By_param_abstract_model
from starrating.constants import RADIX, LEVELS_LIST, LEVEL_NO_TO_NAME
from starrating.aggr.aggr_utils import get_actual_methods, level_of_model, \
	get_methods_specification, \
	get_parent_object, get_dependent_model, get_base_model, get_upd_model
from starrating.constants import METHOD_DIRECT_SUMM, METHOD_REWEIGHTING, \
	LOCK_FILE_FOR_RATED_TREE_MODIFICATIONS

from os import getpid

def mk_empty_aggr_records(start_object, method=None, parameter=None, kwargs_for_user_by_param=None):
	"""
	Recursive function to create recorods in order dictated by Foreign Key constraints.
	
	The call result is creation of get_dependent_model(type(start_object)) instance and all
	objects required for it by Foreign Key constraints.
	"""

	# print "< mk_empty_aggr_records", type(start_object), start_object.id, method, parameter
	assert isinstance(start_object, (Group, Race, Event, Series, Organizer, Root, Overall_abstract_model))
	assert (parameter is not None) == isinstance(start_object, Overall_abstract_model)
	assert (method is not None) == isinstance(start_object, (Group, Race, Event, Series, Organizer, Root))
	assert (method is None) != (parameter is None)
	assert (kwargs_for_user_by_param is not None) == isinstance(start_object, User_overall)
	assert (method is None) or isinstance(method, int)
	assert (parameter is None) or isinstance(parameter, int)

	model_to_create = get_dependent_model(type(start_object))
	id_to_create = start_object.id * RADIX + (method or parameter)

	obj_to_create = model_to_create.objects.filter(id=id_to_create).first()
	if obj_to_create is not None:
		assert not isinstance(start_object, (Group, User_overall))
		return obj_to_create

	parent = mk_empty_aggr_records(get_parent_object(start_object), method, parameter)

	kwargs = dict(
		parent=parent,
		based_on=start_object
	)
	if method:
		kwargs['method_id'] = method
	else:
		kwargs['parameter_id'] = parameter
		kwargs['method_id'] = method = start_object.method_id
	if isinstance(start_object, User_overall):
		kwargs.update(kwargs_for_user_by_param)
	# user_count and weight are set to zero by default (because the real data
	# will be in User_*_updated models

	method_spec = get_methods_specification()[method][level_of_model(model_to_create)]
	if issubclass(model_to_create, Overall_abstract_model):
		sum_field_name = method_spec['overall_field']
	else:
		assert issubclass(model_to_create, By_param_abstract_model)
		sum_field_name = method_spec['by_param_field']
	kwargs[sum_field_name] = 0

	new_obj = model_to_create(**kwargs)
	new_obj.save()
	assert new_obj.id == id_to_create
	# print "> mk_empty_aggr_records", type(start_object), start_object.id, method, parameter
	return new_obj


def mk_aggr_structure_for_group(group, method_id):
	# print "mk_aggr_structure_for_group", group, method_id
	if isinstance(group, int):
		group = Group.objects.get(id=group)
	else:
		assert isinstance(group, Group)

	primary_list = list(
		group.primary_set.filter(
			is_hidden=False,
			parameter__to_calculate=True,
		).values_list('id', 'parameter_id', 'value')
	)

	if len(primary_list) <= 0:
		print("g: {} m: {}".format(group, method_id))
	assert len(primary_list) > 0, "I hope this will not be called for an empty group"
	

	if primary_list:
		user_overall = mk_empty_aggr_records(group, method=method_id)
		sum_val = 0
		count_par = 0
		for primary_id, par, val in primary_list:
			sum_val += val
			count_par += 1
			kwargs_for_user_by_param = dict(
				# user_count=0,
				# weight=0,  # Zero is default value for user_count and weight
				on_primary_id=primary_id,
			)
			user_by_param = mk_empty_aggr_records(
				user_overall,
				parameter=par,
				kwargs_for_user_by_param=kwargs_for_user_by_param
			)
			User_by_param_updated.objects.create(
				id=user_by_param,
				user_count=1,
				sum_int=val,
				weight=1,
			)

		User_overall_updated.objects.create( # This may be method dependent !!!
			id=user_overall,
			user_count=1,
			sum_int=sum_val,
			weight=count_par,  # Так можно потом работать в направлении child
# 			No, it should be done later!
#			user_count=None,
#			sum_int=0,
#			weight=None,
		)


def create_all_zero_records_for_new_groups(method_ids=(), only_one_group=False, log=None):
	# print "create_all_zero_records_for_new_groups", method_ids
	assert isinstance(method_ids, (list, tuple))
	if log:
		pid = getpid()
		log.debug(
			'create_all_zero_records_for_new_groups[{}] start: methods_ids={}, only_one_group={},'.format(
				pid,
				method_ids,
				1 if only_one_group else 0,
			)
		)
	if not method_ids:
		method_ids = tuple(get_actual_methods())
		if log:
			log.debug('actual methods: {}'.format(method_ids))

	if log:
		group_id_list = []
		MAX_LIST_LENGTH = 100

	group_count = 0
	for group_id in Group_new.objects.all().values_list('id', flat=True):
		with Flock_mutex(LOCK_FILE_FOR_RATED_TREE_MODIFICATIONS):
			with transaction.atomic():
				for m_id in method_ids:
					mk_aggr_structure_for_group(group_id, method_id=m_id)
				Group_new.objects.filter(id_id=group_id).delete()
		result = True
		group_count += 1
		if log:
			if group_count <= MAX_LIST_LENGTH:
				group_id_list.append(group_id)
		if only_one_group:
			break
	if log:
		log.debug(
			'create_all_zero_records_for_new_groups[{}] result: group_count={}'.format(
				pid,
				group_count,
			)
		)
		if group_count > 0:
			log.info(
				'processed groups: {}{}'.format(
					' '.join([str(x) for x in group_id_list]),
					' ... {}'.format(
						group_id
					) if len(group_id_list)==MAX_LIST_LENGTH and group_id!=group_id_list[-1] else ''
				)
			)

	return group_count


def calc_simple_sum(target_name, upd_record, old_data, new_data, src_name=None):
	if src_name is None:
		src_name = target_name

	delta = new_data[src_name] - old_data[src_name]

	target_val = getattr(upd_record, target_name)
	if target_val is None:
		target_val = delta
	else:
		target_val += delta
	setattr(upd_record, target_name, target_val)


def calc_overall_current(
		old_data,    # dict indexed by parameter_id
		new_data,    # dict indexed by parameter_id
		bp_sum_field_name,
		ov_sum_field_name,
		calc_method,   # METHOD_DIRECT_SUMM or METHOD_REWEIGHTING
		ov_record,
		upd_model,
		direction='child',
):
	if direction == 'by_param':
		raise NotImplementedError
	assert direction == 'child'
	# do nothing, was calculated previously


def calc_overall_parent(
		old_data,
		new_data,
		current_sum_field_name,
		parent_sum_field_name,
		calc_method,   # METHOD_DIRECT_SUMM or METHOD_REWEIGHTING
		parent_record,
		upd_model,
		direction='child',
):
	# user_count is direction-independent
	upd_record = get_upd_record(parent_record, upd_model=upd_model)
	calc_simple_sum(
		target_name='user_count',
		upd_record=upd_record,
		old_data=old_data, new_data=new_data,
	)

	if direction == 'by_param':
		raise NotImplementedError
	assert direction == 'child'

	if calc_method == METHOD_DIRECT_SUMM:
		calc_simple_sum(
			target_name='weight',
			upd_record=upd_record,
			old_data=old_data, new_data=new_data,
		)
		calc_simple_sum(
			target_name=parent_sum_field_name, src_name=current_sum_field_name,
			upd_record=upd_record,
			old_data=old_data, new_data=new_data,
			)
	else:
		assert calc_method == METHOD_REWEIGHTING
		raise NotImplementedError

	upd_record.save()


def get_upd_record(node, upd_model=None, to_try_existant=True):
	"""
	Если таковая уже есть, использует ее. Иначе создает новую и копирует в нее
	данные из основной модели
	"""
	assert isinstance(node, Aggregate_abstract_model)
	# ^ may be *_overall or *_by_param model instance
	pk = node.pk
	if upd_model is None:
		upd_model = get_upd_model(type(node))

	try:
		if to_try_existant:
			obj = upd_model.objects.get(pk=pk)
		else:
			raise upd_model.DoesNotExist
	except upd_model.DoesNotExist:
		base_model = get_base_model(upd_model)
		base_obj_dict = list(base_model.objects.filter(pk=pk).values())[0]
		upd_fields = [f.name for f in upd_model._meta.get_fields()]
		new_dict = {k: v for k, v in list(base_obj_dict.items()) if k in upd_fields}
		new_dict['pk'] = new_dict['id']
		del new_dict['id']
		obj = upd_model(**new_dict)

	return obj


def calc_by_param_parent(
		old_data,    # dict indexed by parameter_id
		new_data,    # dict indexed by parameter_id
		current_sum_field_name,
		parent_sum_field_name,
		calc_method,   # METHOD_DIRECT_SUMM or METHOD_REWEIGHTING
		parent_records, # dict indexed by parameter_id
		upd_model,
):
	#print "call calc_by_param_parent"
	assert len(new_data) == len(old_data)

	# user_count
	for par in old_data:
		# upd_record = upd_model(pk=parent_records[par].pk)
		upd_record = get_upd_record(parent_records[par], upd_model=upd_model)
		calc_simple_sum(
			target_name='user_count',
			upd_record=upd_record,
			old_data=old_data[par], new_data=new_data[par],
		)
		'''
		# user_count
			delta = new_data[par]['user_count'] - old_data[par]['user_count']
			assert delta >= 0
			parent_records[par].user_count += delta
	'''
		if calc_method == METHOD_DIRECT_SUMM:
			calc_simple_sum(
				target_name='weight',
				upd_record=upd_record,
				old_data=old_data[par], new_data=new_data[par],
			)
			calc_simple_sum(
				target_name=parent_sum_field_name, src_name=current_sum_field_name,
				upd_record=upd_record,
				old_data=old_data[par], new_data=new_data[par],
			)
		else:
			assert calc_method == METHOD_REWEIGHTING
			raise NotImplementedError
		upd_record.save()


def process_update_record(obj):
	"""
	Requires:
	- на всех предыдущих уровнях уже посчитаны основые значения, _updated удалены
	- правильные by_param-значения для данного уровня уже записаны в _by_param_updated
	- если для overall данного уровня направление child - то их правильные значения
	  тоже уже записаны в _overall_updated
	  иначе, в _overall_updated могут (должны?) быть записаны NULL
	
	ДОДУМАЙ: user_count всегда вычисляется в направлении child!
	"""

	def copy_from_by_param_updated(overall_id, parameters):
		# TODO: копировать поля выборочно.
		sub_filter = by_param_updated_model.objects.filter(pk=OuterRef('pk'))
		by_param_model.objects.all().filter(
			overall_id=overall_id,
			parameter_id__in=parameters,
		).update(
			sum_int=Subquery(sub_filter.values('sum_int')),
			sum_float=Subquery(sub_filter.values('sum_float')),
			user_count=Subquery(sub_filter.values('user_count')),
			weight=Subquery(sub_filter.values('weight')),
		)

	def copy_from_overall_updated(overall_id):
		# TODO: копировать поля выборочно
		sub_filter = overall_updated_model.objects.filter(pk=OuterRef('pk'))
		# print type(overall_id)
		overall_model.objects.all().filter(pk=overall_id).update(
			sum_int=Subquery(sub_filter.values('sum_int')),
			sum_float=Subquery(sub_filter.values('sum_float')),
			user_count=Subquery(sub_filter.values('user_count')),
			weight=Subquery(sub_filter.values('weight')),
		)

	def delete_overall_updated(overall_id):
		overall_updated_model.objects.filter(pk=overall_id).delete()

	def delete_by_param_updated(overall_id):
		by_param_updated_model.objects.filter(id__overall_id=overall_id).delete()

	def get_as_values(qs, fields=()):
		assert len(qs) == 1
		return qs.values(*fields)[0]

	########################
	# End of sub-functions #
	########################

	assert isinstance(obj, Overall_updated_abstract_model)
	print("process_update_record", obj)
	level = level_of_model(type(obj))
	print("level=", level)

	has_parent = (level + 1) in LEVEL_NO_TO_NAME

	### Собираем модели и ids
	overall_updated_model = type(obj)
	overall_model = get_base_model(type(obj))
	by_param_updated_model = get_dependent_model(type(obj))
	by_param_model = get_base_model(by_param_updated_model)

	ov_id = obj.pk

	method_spec_this = get_methods_specification()[obj.id.method_id][level]

	if has_parent:
		overall_parent_model = type(obj.id.parent)
		by_param_parent_model = get_dependent_model(overall_parent_model)
		overall_parent_updated_model = get_upd_model(overall_parent_model)
		by_param_parent_updated_model = get_upd_model(by_param_parent_model)

		method_spec_parent = get_methods_specification()[obj.id.method_id][level+1]


	"""
	Надо в рамках транзакции
	* Вычисления на текущем уровне
		- by_param уже готов в _updated, вычислять не надо [НЕТ bp_current]
		- overall_updated:
			Если направление child, то уже готов в _updated, вычислять не надо
			Иначе их надо обновить на основе by_param_updated текущего уровня
			и результаты записать в _updated.    [ov_current]
	* Вычисления на уровне parent
		- by_param: обновить parent _updated.parent на основе текущего _update
			и записать результаты в parent _upated модель.   [pb_parent]
		- overall:
			- если направление указано child, аналогично предыдущему
			обновить parent _updated на основе текущего _update
			и записать результаты в parent _upated модель.
			- иначе создать parent _updated модель с NULL-значениями.
					Это все - [ov_parent]
	* скопировать by_param_updated и overall_updated в основную модель [copy_updated]
	* удалить by_param_updated и overall_updated (в любом порядке) [delete_updated]

	Зависимости:
		[delete_updated ov] after [copy_updated ov] after [ov_parent] after [ov_current]
		[delete_updated bp] after [copy_updated bp] after [bp_parent]
		Эти две цепочки могут выполнятся параллельно
			(зависимость ov_parent от bp_parent возможна, но в этом случае 
			реальные вычисления происходят на шаге, соответсвующим след. уровню.
			Поэтому здесь эту зависимость можно игнорировать)
	"""

	#####
	# считываем данные, с помощью которых будем апдейтить
	bp_data_fields = ('user_count', 'weight', method_spec_this['by_param_field'])
	ov_data_fields = ('user_count', 'weight', method_spec_this['overall_field'])

	if has_parent:
		bp_data_parent_fields = ('user_count', 'weight', method_spec_parent['by_param_field'])
		ov_data_parent_fields = ('user_count', 'weight', method_spec_parent['overall_field'])

	bp_new_data = queryset_to_dict(
		by_param_updated_model.objects.filter(id__overall_id=ov_id).values('id__parameter_id', *bp_data_fields),
		'id__parameter_id'
	)
	par_list = tuple(bp_new_data.keys())

	by_param_qs = by_param_model.objects.filter(
		overall_id=ov_id,
		parameter_id__in=par_list
	)
	bp_old_data = queryset_to_dict(
		by_param_qs.values('parameter_id', *bp_data_fields),
		'parameter_id'
	)
	assert tuple(bp_old_data.keys()) == par_list

	if has_parent:
		bp_parent_records = queryset_to_dict(
			obj.id.parent.by_param.all().filter(parameter_id__in=par_list),
			'parameter_id'
		)   # will be a dict of model instances indexed by parameter id

	overall_qs = overall_model.objects.filter(pk=ov_id)
	ov_old_data = get_as_values(overall_qs, ov_data_fields)
	ov_new_data = get_as_values(
		overall_updated_model.objects.filter(id__pk=ov_id),
		ov_data_fields + ('to_delete',),
	)

	# print "before transaction"
	with Flock_mutex(LOCK_FILE_FOR_RATED_TREE_MODIFICATIONS):
		with transaction.atomic():
			# overall sequence
			'''
			calc_overall_current(
				old_data=bp_old_data,
				new_data=bp_new_data,
				bp_sum_field_name=method_spec_this['by_param_field'],
				ov_sum_field_name=method_spec_this['overall_field'],
				calc_method=method_spec_this['overall_spec'],
				ov_record=obj,
				upd_model=overall_parent_updated_model,
				direction=method_spec_this['overall_dir'],
			)
			'''
			if has_parent:
				calc_overall_parent(
					old_data=ov_old_data,
					new_data=ov_new_data,
					current_sum_field_name=method_spec_this['overall_field'],
					parent_sum_field_name=method_spec_parent['overall_field'],
					calc_method=method_spec_parent['overall_spec'],
					parent_record=obj.id.parent,
					upd_model=overall_parent_updated_model,
					direction=method_spec_parent['overall_dir']
				)
			copy_from_overall_updated(ov_id)
			delete_overall_updated(ov_id)

			# by_param sequence
			if has_parent:
				calc_by_param_parent(
					old_data=bp_old_data,
					new_data=bp_new_data,
					current_sum_field_name=method_spec_this['by_param_field'],
					parent_sum_field_name=method_spec_parent['by_param_field'],
					calc_method=method_spec_parent['by_param_spec'],
					parent_records=bp_parent_records,
					upd_model=by_param_parent_updated_model,
				)
			copy_from_by_param_updated(ov_id, par_list)
			delete_by_param_updated(ov_id)
			if ov_new_data['to_delete']:
				# assert all_zero(ov_new_data) # TODO
				# assert all_zero(bp_new_data)
				by_param_qs.delete()
				overall_qs.delete()


def process_updated_models(level, method_ids=(), log=None):
	assert level in LEVELS_LIST
	assert isinstance(method_ids, (list, tuple))
	if log:
		pid = getpid()
		log.debug(
			'process_updated_models[{}] start: level={}={}, method_ids={}'.format(
				pid,
				level,
				LEVEL_NO_TO_NAME[level],
				method_ids,
			)
		)
	if not method_ids:
		method_ids = tuple(get_actual_methods())
		if log:
			log.debug('actual methods: {}'.format(method_ids))

	base_name = 'starrating.' + LEVEL_NO_TO_NAME[level]

	model_overall_updated = get_model_by_name(base_name + '_overall_updated')
	model_overall = get_model_by_name(base_name + '_overall')
	model_by_param_updated = get_model_by_name(base_name + '_by_param_updated')
	model_by_param = get_model_by_name(base_name + '_by_param')

	fields_for_select_related = ['id__method']
	if level + 1 in LEVELS_LIST:
		fields_for_select_related.append('id__parent')
	updated_qs = model_overall_updated.objects.all().filter(
		id__method_id__in=method_ids
	).select_related(*fields_for_select_related)

	if log:
		id_list = []
		MAX_LIST_LENGTH = 100

	items_count = 0
	for item in updated_qs:
		process_update_record(item)
		items_count += 1
		if log:
			if items_count <= MAX_LIST_LENGTH:
				id_list.append(item.pk)
	if log:
		log.info(
			'process_updated_models[{}] (level={}={}) result: items_count={}'.format(
				pid,
				level,
				LEVEL_NO_TO_NAME[level],
				items_count,
			)
		)
		if items_count > 0:
			log.info(
				'processed {}_overall_updated ids: {}{}'.format(
					LEVEL_NO_TO_NAME[level],
					' '.join([str(x) for x in id_list]),
					' ... {}'.format(
						item.pk
					) if len(id_list)==MAX_LIST_LENGTH and item.pk != id_list[-1] else ''
				)
			)
	return items_count
