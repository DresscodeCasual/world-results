from results import models

from starrating.models import Root_overall, Aggregate_abstract_model, Overall_abstract_model, \
	By_param_abstract_model

from starrating.constants import RADIX
from starrating.aggr.aggr_utils import get_upd_model, get_methods_specification, level_of_model, get_dependent_model, get_parent_object
from starrating.aggr.localtools import mk_empty_aggr_records, get_upd_record
from starrating.exceptions import UpdatedRecordExistsError


def is_there_any_update_record(overall_node):
	assert isinstance(overall_node, Overall_abstract_model)

	if get_upd_model(type(overall_node)).objects.filter(id=overall_node).exists():
		return True

	bp_updated_model = get_upd_model(get_dependent_model(type(overall_node)))
	if get_upd_model(
		get_dependent_model(type(overall_node))
	).objects.filter(id__overall=overall_node).exists():
		return True

	return False


def all_zeroes(overall_node):
	if any([
		getattr(overall_node, f) for f in get_aggr_values_fields(node=overall_node)
	]):
		return False

	by_param_fields = get_aggr_values_fields(
		model=get_dependent_model(type(overall_node)),
		method_id=overall_node.method_id,
	)
	for by_param_node in overall_node.by_param.all():
		if any([getattr(by_param_node, f) for f in by_param_fields]):
			return False

	return True


def get_aggr_values_fields(node=None, model=None, method_id=None):
	if model is None:
		assert method_id is None
		model = type(node)
		method_id = node.method_id # pytype: disable=attribute-error
	else:
		assert isinstance(method_id, int)
		assert node is None
	assert issubclass(model, Aggregate_abstract_model)

	method_spec = get_methods_specification()[method_id][level_of_model(model)]
	data_fields = ['user_count', 'weight']
	if issubclass(model, Overall_abstract_model):
		data_fields.append(method_spec['overall_field'])
	elif issubclass(model, By_param_abstract_model):
		data_fields.append(method_spec['by_param_field'])
	else:
		assert False, "model must be an subclass of Aggregate_abstract_model"

	return tuple(data_fields)


def set_zero_aggr_values(node):
	assert isinstance(node, Aggregate_abstract_model)
	fields = get_aggr_values_fields(node=node)
	for f in fields:
		setattr(node, f, 0)


def move_node_into_new_tree_place(overall_node, new_parent):
	'''
	This moves the node and creates recalculation tasks for updater at new place.
	
	This does NOT create recalculation tasks for updater at old tree place -
	it must be done by call of make_temporary_clone().
	'''
	
	assert overall_node.parent != new_parent

	new_overall_parent = mk_empty_aggr_records(new_parent, method=overall_node.method_id)
	# NB: This ^ call creates nothing if new_parent already has its overall node.

	overall_node.parent = new_overall_parent

	get_upd_record(overall_node, to_try_existant=False).save(force_insert=True)
	set_zero_aggr_values(overall_node)
	overall_node.save(force_update=True)

	for by_param_node in overall_node.by_param.all():
		by_param_node.parent = mk_empty_aggr_records(
			new_overall_parent,
			parameter=by_param_node.parameter_id,
		) # NB: This call creates nothing if that by param node already exists

		get_upd_record(by_param_node, to_try_existant=False).save(force_insert=True)
		set_zero_aggr_values(by_param_node)
		by_param_node.save(force_update=True)


def create_deletion_task(overall_node):
	# for this node and it's by_param nodes
	assert isinstance(overall_node, Overall_abstract_model)
	assert not isinstance(overall_node, Root_overall)
	fields = get_aggr_values_fields(node=overall_node)
	upd_model = get_upd_model(type(overall_node))
	upd_model.objects.create(
		pk=overall_node.id,
		to_delete=True,
		**{f: 0 for f in fields}
	)

	by_param_model = get_dependent_model(type(overall_node))
	fields = get_aggr_values_fields(model=by_param_model, method_id=overall_node.method_id)
	by_param_upd_model = get_upd_model(by_param_model)
	by_param_upd_model.objects.bulk_create([
		by_param_upd_model(pk=x, **{f: 0 for f in fields}) for x in
		by_param_model.objects.filter(overall=overall_node).values_list('id', flat=True)
	])


def make_temporary_clone(overall_node, delete_original):
	'''
	This function creates temporary clone needed only for updater's aggregate values recalculation.
	
	That clone will be deleted by updater (due to *_overall_updated record with deletion task)
	'''

	assert isinstance(overall_node, Overall_abstract_model)
	assert not isinstance(overall_node, Root_overall)
	assert isinstance(delete_original, bool)

	overall_original_id = overall_node.id
	overall_node_copy = type(overall_node).objects.get(id=overall_original_id)
	# ^ This requires sql query. May be copy.copy() or copy.deepcopy()
	# might be used instead, by I have not found documentation on using them
	# for Django model instances.

	overall_copy_id = overall_node_copy.rated_id * RADIX + overall_node_copy.method_id - 1
	overall_node_copy.id = overall_copy_id
	overall_node_copy.rated = None
	overall_node_copy.save(force_insert=True)

	for by_param_node in overall_node.by_param.all():
		by_param_original_id = by_param_node.id
		by_param_node.id = overall_copy_id * RADIX + by_param_node.parameter_id
		by_param_node.overall_id = overall_copy_id
		by_param_node.save(force_insert=True)

	create_deletion_task(overall_node_copy)

	if delete_original:
		type(overall_node).objects.get(id=overall_original_id).delete()
		# The on_delete=CASCADE mechanism will delete:
		# - linked by_param nodes
		# - if type(overall_node) == Race_overall:
		#	 - child User_overall and User_by_param nodes
		#	 - linked Race_*_updated User_*_updated records

def change_parent(node, new_parent):
	"""
	called by:
	views_event.event_change_series()
	views_organizer.add_series(), views_organizer.remove_series()
	"""

	assert isinstance(node, (models.Series, models.Event, models.Race))
	old_parent = get_parent_object(node)
	assert type(new_parent) is type(old_parent)
	assert new_parent != old_parent

	for overall_node in node.sr_overall.all():
		if is_there_any_update_record(overall_node):
			raise UpdatedRecordExistsError(
				'model {}, id={}'.format(type(overall_node).__name__, overall_node.id)
			)
		make_temporary_clone(overall_node, delete_original=False)
		move_node_into_new_tree_place(overall_node, new_parent)


def transfer_children_before_node_deletion(node, acceptor):
	"""
	called by:
	views_event.event_delete(), url: editor:event_delete
	views_series.series_delete(), url: editor:series_delete
	views_organizer.organizer_delete(), url пока нет.
	"""

	assert isinstance(node, (models.Event, models.Series, models.Organizer))
	assert (acceptor is None) or (type(acceptor) is type(node))
	assert node != acceptor

	for overall_node in node.sr_overall.all():
		if is_there_any_update_record(overall_node):
			raise UpdatedRecordExistsError(
				'model {}, id={}'.format(type(overall_node).__name__, overall_node.id)
			)
		if acceptor is None:
			assert not node.get_children().exists()
			assert all_zeroes(overall_node)
			overall_node.delete()
		else:
			for overall_child in overall_node.child.all():
				if is_there_any_update_record(overall_child):
					raise UpdatedRecordExistsError(
						'model {}, id={}'.format(type(overall_child).__name__, overall_child.id)
					)
				move_node_into_new_tree_place(overall_child, acceptor)
			make_temporary_clone(overall_node, delete_original=True)

def delete_group(action_user, group_node):
	for user_overall_node in list(group_node.sr_overall.all()):
		if is_there_any_update_record(user_overall_node):
			raise UpdatedRecordExistsError('model {}, id={}'.format(type(user_overall_node).__name__, user_overall_node.id))

		# чтобы не мешал удалять группу:
		user_overall_node.rated = None
		user_overall_node.save()

		# чтобы не мешали удалять primary:
		for by_param_node in list(user_overall_node.by_param.all()):
			by_param_node.on_primary = None
			by_param_node.save()

		# этот вызов создает задание для updater'а.
		create_deletion_task(user_overall_node)

	race = group_node.race
	models.Table_update.objects.create(model_name=models.Event.__name__, row_id=race.event_id, child_id=race.id,
		action_type=models.ACTION_MARKS_DELETE, user=action_user, is_verified=True)
	# Первичные оценки и отзывы будут удалены механизмом Cascade
	group_node.delete()
