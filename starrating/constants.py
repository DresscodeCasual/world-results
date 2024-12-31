# -*- coding: utf-8 -*-



import datetime
import os.path

from django.conf import settings


MAX_RATING_VALUE = 5

RADIX = 100  # Some dependent id (primary keys) are computed as id_1 * RADIX + id_2
DJANGO_MAX_INT = 2147483647

MIN_DISTANCE_FOR_RATE_NUTRITION = 10000

TIMEDELTA_FOR_ASK_TO_LEAVE_RATING = datetime.timedelta(7) # a week
MSG_WHEN_TO_ASK_TO_LEAVE_RATING = 'через неделю'

# These timedeltas are effectively disabled:
TIMEDELTA_TO_RATE_A_RACE = datetime.timedelta(days=1000 * 365)
TIMEDELTA_FOR_USER_TO_RATE = TIMEDELTA_TO_RATE_A_RACE

CURRENT_METHOD = 9


#### Allow to leave and view rating
SHOW_RATING_TO_ALL = True
SHOW_RATING_TO_ADMIN = True  # not checked if SHOW_RATING_TO_ALL == True

ADMIN_CAN_LEAVE_RATING_FOR_ANY_USER = False

#### For starrating.aggr.updater.updater()
PAUSE_BETWEEN_GROUP_NEW_CHECKS = 1  # ordinary small (about 1 s)
DEFAULT_UPDATE_PAUSE = 5
LOOP_COUNT_FOR_FORCE_CHECK = 30
PAUSE_AFTER_MYSQL_ERROR = 30

LEVELS_PAIRS = (
	(1, 'User'),
	(2, 'Race'),
	(3, 'Event'),
	(4, 'Series'),
	(5, 'Organizer'),
	(6, 'Root'),
)

LEVELS_LIST = tuple(x[0] for x in LEVELS_PAIRS)

LEVELS_PAIRS_0 = ((0, 'Group_Primary'),) + LEVELS_PAIRS
LEVELS_LIST_0 = tuple(x[0] for x in LEVELS_PAIRS_0)

LEVEL_NO_TO_NAME = dict(LEVELS_PAIRS_0)
LEVEL_NAME_TO_NO = dict([reversed(item) for item in LEVELS_PAIRS_0])

RATING_VALUES_DESCRIPTIONS = (
		"не хочу оценивать",
		"ужасно",
		"плохо",
		"нормально",
		"хорошо",
		"отлично"
	)

assert len(RATING_VALUES_DESCRIPTIONS) == MAX_RATING_VALUE + 1


METHOD_NO_CALCULATION = 0
METHOD_DIRECT_SUMM = 1
METHOD_REWEIGHTING = 2


FULL_STAR = '<i class="fa fa-star"></i>'        # https://fontawesome.com/v4.7.0/icon/star
EMPTY_STAR = '<i class="fa fa-star-o"></i>'     # https://fontawesome.com/v4.7.0/icon/star-o
HALF_STAR = '<i class="fa fa-star-half-o"></i>' # https://fontawesome.com/v4.7.0/icon/star-half-o


LOCK_FILE_FOR_RATED_TREE_MODIFICATIONS = os.path.join(
	settings.BASE_DIR,
	'logs/lock_file',
)
