from time import sleep
import logging
from os import getpid

import django.db.utils
from django.db import connection

from starrating.constants import PAUSE_BETWEEN_GROUP_NEW_CHECKS, DEFAULT_UPDATE_PAUSE, \
	LOOP_COUNT_FOR_FORCE_CHECK, LEVELS_LIST, LEVEL_NO_TO_NAME, PAUSE_AFTER_MYSQL_ERROR
from starrating.aggr.aggr_utils import get_actual_methods
from .localtools import create_all_zero_records_for_new_groups, process_updated_models

log = logging.getLogger('sr_updater')

assert LOOP_COUNT_FOR_FORCE_CHECK > 1

_OPERATION_MODES = ('loop', 'one_pass', 'one_level')
def updater2(
		methods=(),
		mode='loop',
		only_one_group=False,
		pause=DEFAULT_UPDATE_PAUSE,
		pause2=PAUSE_BETWEEN_GROUP_NEW_CHECKS,
	):
	assert mode in _OPERATION_MODES
	assert isinstance(methods, (list, tuple))

	pid = getpid()
	log.info(
		'updater start: metods={} mode={} only_one_group={} pause={} pause2={}'.format(
			methods, mode, 1 if only_one_group else 0, pause, pause2
		)
	)
	if mode == 'loop':
		log.info(
			'updater: LOOP_COUNT_FOR_FORCE_CHECK={}'.format(LOOP_COUNT_FOR_FORCE_CHECK)
		)

	if not methods:
		methods = tuple(get_actual_methods())
		log.debug('updater; actual methods: {}'.format(methods))

	must_be_new_data = create_all_zero_records_for_new_groups(methods, only_one_group, log)
	if must_be_new_data:
		if mode == 'one_level':
			log.info('updater (mode=one_level) returns: True, level=0')
			return True, 0
		if not only_one_group:
			sleep(pause2)
			while create_all_zero_records_for_new_groups(methods, only_one_group, log):
				sleep(pause2)

	loopcount = 0

	while True:
		if loopcount == LOOP_COUNT_FOR_FORCE_CHECK:
			loopcount = 1
		else:
			loopcount += 1
		log.debug(
			'updater in main while-loop: loopcount={}, must_be_new_data={}'.format(
				loopcount,
				1 if must_be_new_data else 0,
			)
		)
		if must_be_new_data or loopcount == 1:
			# must_be_new_data титтк когда группа дала данные
			loopcount = 1
			for level in LEVELS_LIST:
				# inv: все предыдущие уровни (модели в списке) - пусты
				# must_be_new_data титтк когда предыдущие уровни дали данные
				#
				# (if not must_be_new_data - данные могут быть как осатки старыз процессов...)
				#
				log.debug(
					'updater[{}] in "for level" loop: level={}={}, must_be_new_data={}'.format(
						pid,
						level,
						LEVEL_NO_TO_NAME[level],
						1 if must_be_new_data else 0,
					)
				)
				if process_updated_models(level, methods, log):
					if mode == 'one_level':
						log.info('updater[{}] (mode=one_level) returns: True, level={}={}'.format(
								pid,
								level,
								LEVEL_NO_TO_NAME[level],
							)
						)
						return True, level
					must_be_new_data = True
				else:
					assert not must_be_new_data
				if mode == 'loop' and not only_one_group and \
						create_all_zero_records_for_new_groups(methods, only_one_group):
					must_be_new_data = True
					break
				else:
					pass
			else:  # this else is a part of for-statement, not of if-statement !
				# Here we have passed all levels
				must_be_new_data = False
				assert loopcount == 1
				if mode == 'one_level':
					log.info(
						'updater[{}] (mode=one_level) returns False (no data found)'.format(pid)
					)
					return False
				elif mode == 'one_pass':
					log.info(
						'updater[{}] (mode=one_pass) finished, returns None'.format(pid)
					)
					return None
				else:
					assert mode == 'loop'
					# Next, we will wait for a new group (in else below)
		else:
			assert mode == 'loop'
			log.debug(
				'updater[{}]:  mode=loop; loop "for level" was skipped, waiting for new groups {} s'.format(
					pid,
					pause,
				)
			)
			sleep(pause)
			if create_all_zero_records_for_new_groups(methods, only_one_group, log):
				must_be_new_data = True


def updater(*args, **kwargs):
	pid = getpid()
	while True:
		try:
			updater2(*args, **kwargs)
		except django.db.utils.OperationalError as e:
			log.error('updater[{}] error {}'.format(pid, repr(e)), exc_info=True)
			connection.close()
			log.info(' updater[{}] is waiting after error {} s'.format(pid, PAUSE_AFTER_MYSQL_ERROR))
			sleep(PAUSE_AFTER_MYSQL_ERROR)
		except Exception as e:
			log.error('updater[{}] unexpexted error {}'.format(pid, repr(e)), exc_info=True)
			raise
		else:
			break
