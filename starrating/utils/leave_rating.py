from django.db import transaction
import logging

from ..models import Parameter, Group, Primary, Group_new, User_review
from results import models
from ..constants import MAX_RATING_VALUE, MIN_DISTANCE_FOR_RATE_NUTRITION, TIMEDELTA_FOR_ASK_TO_LEAVE_RATING

from django.utils.timezone import now
from datetime import timedelta

PARAMETERS = {}
try:
	for param in Parameter.objects.all():
		PARAMETERS[param.id] = param
except:
	pass

def get_params_to_rate_for_race(race):    #  -> QuerySet
	params = Parameter.objects.filter(to_rate=True)

	if isinstance(race, models.Race):
		dist_type = race.distance.distance_type
		dist_length = race.distance.length
	else:
		assert isinstance(race, int)
		dist_type, dist_length = models.Race.objects.filter(id=race).values_list(
				'distance__distance_type', 'distance__length')[0]

	if dist_type == models.TYPE_METERS and dist_length < MIN_DISTANCE_FOR_RATE_NUTRITION:
			params = params.exclude(name="Питание")

	return params

log = logging.getLogger('sr_views')


def leave_rating(race_id, user_id, action_user, marks, review, show_user_name, to_move_to_next_race):
	assert isinstance(show_user_name, bool)
	assert isinstance(review, str)

	# log.debug("leave_rating r:{} u:{} marks: {}".format(race_id, user_id, marks))
	race = models.Race.objects.get(pk=race_id)
	with transaction.atomic():
		group = Group.objects.create(user_id=user_id, race_id=race_id, is_empty=(not marks))
		table_update = models.Table_update.objects.create(model_name=models.Event.__name__, row_id=race.event_id, child_id=race_id,
			action_type=models.ACTION_MARKS_CREATE, user=action_user, is_verified=True)
		for par, value in list(marks.items()):
			assert value in range(1, MAX_RATING_VALUE + 1)
			# log.debug("leave_rating par:{} value:{}".format(par, value))
			Primary.objects.create(
				parameter_id=par,
				value=value,
				group=group
				)
			table_update.add_field(PARAMETERS[par].name, value)
		#import time
		#log.info("begin sleep")
		#time.sleep(30)
		#log.info("end sleep")
		if marks:
			Group_new.objects.create(id=group)
		if review:
			User_review.objects.create(
				group=group,
				content=review,
				show_user_name=show_user_name,
			)
			table_update.add_field('Обзор', review)
	log.debug("leave_rating r:{} u:{} marks:{} group_id={}".format(
		race_id, user_id, marks, group.id
	))

	if to_move_to_next_race:
		profile_object = models.User_profile.objects.get(user_id=user_id)
		when_to_ask_fill_marks = profile_object.when_to_ask_fill_marks
		if when_to_ask_fill_marks == models.DEFAULT_WHEN_TO_ASK_FILL_MARKS:
			profile_object.when_to_ask_fill_marks = when_to_ask_fill_marks + timedelta(days=1)
			profile_object.save()

	return group.id


def find_first_race_id_to_rate(user_id):
	return models.Result.objects.filter(
		user_id=user_id
	).exclude(
		race_id__in=Group.objects.filter(
			user_id=user_id
		).values_list('race_id', flat=True)
	).order_by(
		'-race__event__start_date', 'race_id'
	).values_list(
		'race_id', flat=True
	).first()


def postpone_adding_marks(user_id):
	profile_object = models.User_profile.objects.get(user_id=user_id)
	profile_object.when_to_ask_fill_marks = now().date() + TIMEDELTA_FOR_ASK_TO_LEAVE_RATING
	profile_object.save()


def stop_adding_marks(user_id):
	profile_object = models.User_profile.objects.get(user_id=user_id)
	profile_object.to_ask_fill_marks = False
	profile_object.save()
