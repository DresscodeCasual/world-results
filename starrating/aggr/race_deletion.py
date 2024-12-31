# -*- coding: utf-8 -*-

import logging
from django.db import transaction
from tools.flock_mutex import Flock_mutex
from starrating.constants import LOCK_FILE_FOR_RATED_TREE_MODIFICATIONS


def delete_race_and_ratings(race, *args, **kwargs):

	from .rated_tree_modifications import make_temporary_clone
	# ^ here to aviod cyclic import ^

	assert type(race).__name__ == 'Race'

	log = logging.getLogger('structure_modification')
	log_prefix = 'race.delete(): id={}'.format(race.id)
	log.debug('{} before flock'.format(log_prefix))
	with Flock_mutex(LOCK_FILE_FOR_RATED_TREE_MODIFICATIONS):
		log.debug('{} trnsctn start'.format(log_prefix))
		try:
			with transaction.atomic():
				for overall_node in race.sr_overall.all():
					make_temporary_clone(overall_node, delete_original=True)
					# Linked Race_by_param, User_overall, User_by_param and corresponding *_update
					# instances will be deleted by CASCADE mechanism

				for group in race.group_set.all():
					group.delete()
					# Linked Group_new, Primary and User_review instances will be deleted
					# by CASCADE mechanism

				race.result_set.all().delete()
				super(type(race), race).delete(*args, **kwargs)
			log.debug('{} trnsctn end'.format(log_prefix))
		except Exception as e:
			log.error('{} Unexpected error: {}'.format(log_prefix, repr(e)), exc_info=True)
			raise
		else:
			log.info('{} OK'.format(log_prefix))
