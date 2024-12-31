from collections import defaultdict

from django.db.models import F, Case, When

from results.models import Race, Event, Series, Organizer
from tools.dj_other import cast_to_queryset
from tools.dj_meta import get_model_by_name

from starrating.constants import LEVEL_NAME_TO_NO
from starrating.models import Method_specification, Method, Root, Group, User_overall,\
	Aggregate_abstract_model, Overall_abstract_model, By_param_abstract_model, \
	Updated_abstract_model, Overall_updated_abstract_model


def updated_queryset(model_or_queryset, field_to_update, new_field_name):  # -> QuerySet
	return cast_to_queryset(model_or_queryset).annotate(
		**{
			new_field_name:
				Case(
					When(update__id_id__isnull=True, then=F(field_to_update)),
					default=F('update__' + field_to_update)
				)
		}
	)


def get_actual_methods():
	return Method.objects.filter(is_actual=True).values_list('pk', flat=True)


_methods_spec = None

def get_methods_specification(force=False):
	global _methods_spec

	if _methods_spec is not None and not force:
		return _methods_spec

	_methods_spec = defaultdict(dict)
	qs = list(Method_specification.objects.filter(
		method__is_actual=True
	).values())
	for item in qs:
		method_id = item['method_id']
		level = item['level']
		assert level not in _methods_spec[method_id]
		_methods_spec[method_id][level] = {
			k: v for k, v in list(item.items()) if k not in ('method_id', 'level', 'id')
		}
	return _methods_spec


def level_of_model(model):
	model = get_model_by_name(model)
	model_name = model.__name__
	model_name_prefix = model_name[:model_name.find('_')]
	return LEVEL_NAME_TO_NO[model_name_prefix]


def get_parent_object(obj):
	if isinstance(obj, Aggregate_abstract_model):
		return obj.parent
	elif isinstance(obj, Group):
		return obj.race
	elif isinstance(obj, Race):
		return obj.event
	elif isinstance(obj, Event):
		return obj.series
	elif isinstance(obj, Series):
		return obj.organizer or Organizer.objects.fake_object
	elif isinstance(obj, Organizer):
		return Root.objects.get(id=0) # this is the sole root instance (a sentinel)
	else:
		return None


def get_dependent_model(model):
	if model is Group:
		return User_overall
	elif issubclass(model, (Overall_abstract_model, Overall_updated_abstract_model)):
		model_name = model.__name__.replace('_overall', '_by_param')
		return get_model_by_name(model_name)
	else:
		assert issubclass(model, (Race, Event, Series, Organizer, Root))
		model_name = model.__name__ + '_overall'
		return get_model_by_name(model_name)


def get_base_model(model):
	assert issubclass(model, Updated_abstract_model)
	assert model.__name__.endswith('_updated')
	return get_model_by_name(
		model.__name__.replace('_updated', '')
	)


def get_upd_model(model):
	assert issubclass(model, Aggregate_abstract_model)
	assert not model.__name__.endswith('updated')
	return get_model_by_name(model.__name__ + '_updated')


def get_sumfield_name(obj_or_model, method_id=None):
	if isinstance(obj_or_model, Aggregate_abstract_model):
		assert method_id is None, "method is saved in the object itself"
		model = type(obj_or_model)
		method_id = obj_or_model.method_id
	else:
		assert issubclass(obj_or_model, Aggregate_abstract_model)
		model = obj_or_model
		assert isinstance(method_id, int)

	if issubclass(model, By_param_abstract_model):
		spec_key = 'by_param_field'
	else:
		assert issubclass(model, Overall_abstract_model)
		spec_key = 'overall_field'

	level = level_of_model(model)

	return get_methods_specification()[method_id][level][spec_key]
