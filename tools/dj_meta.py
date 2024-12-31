from django.apps import apps
from django.db import models
from collections import defaultdict

class DJ_meta_Exception(Exception):
	pass

class DJ_meta_NoSuchModelName(DJ_meta_Exception):
	pass

class DJ_meta_MoreThenOneSuchModelName(DJ_meta_Exception):
	pass


class MetaModelMixin(object):
	"A mix-in for model classes"

	class Meta:
		abstract = True

	@classmethod
	def full_name(cls):
		return cls._meta.app_label + '.' + cls.__name__ # pytype: disable=attribute-error

	@classmethod
	def get_related_model(cls, fieldname):
		return cls._meta.get_field(fieldname).related_model # pytype: disable=attribute-error


_modelnames_dict = defaultdict(set)  # used as multivalued dict (AKA multimap)
#  see https://docs.python.org/3.1/library/collections.html#defaultdict-examples
#      https://stackoverflow.com/questions/1731971/is-there-a-multimap-implementation-in-python


def app_label_by_model_name(model_name):
	"""
	Returns application label of the model - if there is one and only one such model in all installedd applications.
	
	Otherwise raises an exception
	
	>>> app_label_by_model_name('User')
	'auth'
	>>> app_label_by_model_name('Race')
	u'results'
	>>> app_label_by_model_name('Race_by_param')
	u'starrating'
	>>> app_label_by_model_name('No_such_model')
	Traceback (most recent call last):
	DJ_meta_NoSuchModelName
	>>> app_label_by_model_name('Group')
	'auth'
	"""

	if not _modelnames_dict:
		for app_config in apps.get_app_configs():
			app_label = app_config.label
			for model in app_config.get_models():
				_modelnames_dict[model.__name__].add(app_label)

	apps_set = _modelnames_dict[model_name]
	len_apps_set = len(apps_set)
	if len_apps_set == 0:
		raise DJ_meta_NoSuchModelName
	elif len_apps_set > 1:
		raise DJ_meta_MoreThenOneSuchModelName(" ".join([model_name+':'] + list(apps_set)))
	else:
		return list(apps_set)[0]


def get_full_model_name(model):
	"""
	Returns full model name. Argument may be model class or model name (short or full)
	
	Model name may be full (in fomat app_label.model_name) or short.
	If th short name is not unique in the project, an exception will be raised
	
	>>> get_full_model_name('auth.User')
	'auth.User'
	>>> get_full_model_name('User')
	'auth.User'
	>>> get_full_model_name(User)
	'auth.User'
	>>> get_full_model_name('.bad.nonchecked.name.')
	'.bad.nonchecked.name.'
	>>> get_full_model_name('No_such_model')
	Traceback (most recent call last):
	DJ_meta_NoSuchModelName
	"""

	if isinstance(model, str):
		if '.' not in model:
			model = app_label_by_model_name(model) + '.' + model
		return model
	else:
		assert issubclass(model, models.Model)
		return model._meta.app_label + '.' + model.__name__


def get_model_by_name(model):
	"""
	Returns model class of the model. Argument may be model class or model name (short or full)
	
	Model name may be full (in fomat app_label.model_name) or short.
	If the short name is not unique in the project, an exception will be raised.
	
	
	>>> get_model_by_name(User)
	<class 'django.contrib.auth.models.User'>
	>>> get_model_by_name('User')
	<class 'django.contrib.auth.models.User'>
	>>> get_model_by_name(u'User')
	<class 'django.contrib.auth.models.User'>
	>>> get_model_by_name('auth.User')
	<class 'django.contrib.auth.models.User'>
	>>> get_model_by_name('.bad.nonchecked.name.')
	Traceback (most recent call last):
	ValueError: too many values to unpack
	>>> get_model_by_name('bad.name')
	Traceback (most recent call last):
	LookupError: No installed app with label 'bad'.
	>>> get_model_by_name('No_such_model')
	Traceback (most recent call last):
	DJ_meta_NoSuchModelName

	"""
	
	if isinstance(model, str):
		return apps.get_model(get_full_model_name(model))
	else:
		assert issubclass(model, models.Model)
		return model
