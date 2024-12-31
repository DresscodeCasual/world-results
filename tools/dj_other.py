# -*- coding: utf-8 -*-
from django.db.models import Manager, Model
from django.db.models.query import QuerySet
from tools.dj_meta import get_model_by_name

def cast_to_queryset(model_or_queryset_or_manager):
	if isinstance(model_or_queryset_or_manager, QuerySet):
		return model_or_queryset_or_manager
	elif isinstance(model_or_queryset_or_manager, Manager):
		return model_or_queryset_or_manager.all()
	elif isinstance(model_or_queryset_or_manager, str):
		return get_model_by_name(model_or_queryset_or_manager).objects.all()
	else:
		assert issubclass(model_or_queryset_or_manager, Model)
		return model_or_queryset_or_manager.objects.all()


def queryset_to_dict(qs, key_field):
	# qs may be an iterable of model instances or of dicts
	# (as a queryset returned by values() method)
	#
	# Values of field key_field must be unique in qs

	res = {}
	for item in qs:
		try:
			key_value = item[key_field]
		except TypeError:
			key_value = getattr(item, key_field)

		assert not key_value in res
		res[key_value] = item
	return res
