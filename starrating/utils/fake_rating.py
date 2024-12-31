# -*- coding: utf-8 -*-
# import logging
# from logging import debug, info, warning, error, exception, critical
import results.models
import starrating.models
import random
from starrating.utils.db_init import delete_all_ratings
from starrating.utils.leave_rating import get_params_to_rate_for_race
from .. constants import MAX_RATING_VALUE
from .leave_rating import leave_rating

###################################################
# Gemerators of sample and random primary ratings #
###################################################

PERCENT_FOR_PRIMARY_RATING = 40.0
PERCENT_FOR_RATING_GROUP = 10.0

random.seed(123)

def generate_primary_rating_for_group(
			group,
			percent=PERCENT_FOR_PRIMARY_RATING,
			must_be_not_less_then_one=True,
			hidden='no'  # must be 'no', 'all', or 'some', if 'some', then  percent is ignored.
		):

	def generate_one_primary_rating():
		# nonlocal marks_count
		marks_count[0] += 1  # [] because python 2 does not know nonlocal statement :(
		starrating.models.Primary(
			parameter_id=pid,
			group_id=gid,
			value=random.randrange(1, MAX_RATING_VALUE + 1),
			is_hidden=is_hidden
				).save()

	marks_count = [0] # [] because python 2 does not know nonlocal statement :(
	gid = group.id

	if hidden == 'no':
		is_hidden = False
	elif hidden == 'all':
		is_hidden = True
	else:
		assert  hidden == 'some'
		is_hidden = False

	rid = starrating.models.Group.objects.get(id=gid).race_id
	ratings_count = 0
	for pid in get_params_to_rate_for_race(rid).values_list('id', flat=True):
		if hidden == 'some' or random.random() < percent / 100.0:
			generate_one_primary_rating()
			if hidden == 'some':
				is_hidden = not is_hidden
			ratings_count += 1
	if ratings_count == 0 and must_be_not_less_then_one:
		pid = get_params_to_rate_for_race(rid).values_list('id', flat=True)[0]
		generate_one_primary_rating()

	group.is_empty = (marks_count[0] == 0)
	group.save()

class id_generator():
	def __init__(self, start=1):
		self.start=start-1
		
	def get(self):
		self.start += 1
		return self.start


def generate_sample_primary_ratings(percent_for_primary_rating=PERCENT_FOR_PRIMARY_RATING):

	delete_all_ratings()
	random.seed(1234)
	group_id_gen = id_generator()

	### Groups with >= 1 primary rating, all unhidden
	# events: 22945, 18781 (дважды), 12993, 23156, 11124. In groups w/o rating: 23147. With hidden rating: 22890
	# series: 2661, 1420 (дважды через общ. event)), 2809 (дважды), 2811. In groups w/o rating  2163. With hidden rating: 372

	# Виктор Гордюшенко 
	g = starrating.models.Group(id=group_id_gen.get(), user_id=2502, race_id=43804) # мар / XXX Серебряноборский марафон, 24 ноября 2018 22945 / 2661 / None
	g.save()
	generate_primary_rating_for_group(g)

	# Вячеслав Зверев
	g = starrating.models.Group(id=group_id_gen.get(), user_id=706, race_id=34957)  # 10 км, Bella Run пробег «Михалёвская двадцатка» 18781, / Мещерский марафон 1420 / None
	g.save()
	generate_primary_rating_for_group(g)

	#Виктор Пронин - the same race
	g = starrating.models.Group(id=group_id_gen.get(), user_id=145, race_id=34957)  # 10 км, Bella Run пробег «Михалёвская двадцатка» 18781, / Мещерский марафон 1420 / None
	g.save()
	generate_primary_rating_for_group(g)

	# Алексей Чернов
	g = starrating.models.Group(id=group_id_gen.get(), user_id=1, race_id=22859)  # 5 км / parkrun Битца №58 12993  / 2809 / None
	g.save()
	generate_primary_rating_for_group(g)

	# Дмитрий Захаров
	g = starrating.models.Group(id=group_id_gen.get(), user_id=2319, race_id=43609)  # 5 км / parkrun Битца №175 23156  / 2809 / None
	g.save()
	generate_primary_rating_for_group(g)

	# Наталья Махова
	g = starrating.models.Group(id=group_id_gen.get(), user_id=237, race_id=34958)  # 20 км / Bella Run пробег «Михалёвская двадцатка» 18781  / 1420 / None
	g.save()
	generate_primary_rating_for_group(g)

	# Groups without primary ratings:
	# Виктор Гордюшенко 
	starrating.models.Group(id=group_id_gen.get(), user_id=2502, race_id=43569).save() # мар. / 83 Пробег-Марафон «Битцевская прямая», 23147 / 2163

	# Groups with only hidden primary ratings:
	# Вячеслав Смирнов
	g = starrating.models.Group(id=group_id_gen.get(), user_id=709, race_id=43088)  # 20 км / Осенний марафон МИЭТ «Осень-2018  22890 / 372 / None
	g.save()
	generate_primary_rating_for_group(g, hidden='all')

	# Groups with hidden and unhidden primary ratings:
	g = starrating.models.Group(id=group_id_gen.get(), user_id=1, race_id=20458)  # 5 км / parkrun Парк Горького №30 11124 / 2811 / None
	g.save()
	generate_primary_rating_for_group(g, hidden='some')


def generate_random_primary_ratings(  # Very slow - about ten minutes
			percent_for_rating_group=PERCENT_FOR_RATING_GROUP,
			percent_for_primary_rating=PERCENT_FOR_PRIMARY_RATING
		):
	random.seed(123)
	delete_all_ratings()
	print("Old records deleted, Now will create new records.")
#	exit(0)

	res_qs = results.models.Result.objects.exclude(user=None).values_list(
			'user_id',
			'race_id',
			'race__distance__distance_type',
			'race__distance__length'
		).distinct()
	parameters = list(starrating.models.Parameter.objects.filter(to_rate=True))

	group_id_gen = id_generator()

	print("len(res_qs)",  len(res_qs))
	print("len(parameters)",   len(parameters))

	for result in res_qs:
		if random.random() >= percent_for_rating_group / 100.0:
			continue
		group = starrating.models.Group(
				id=group_id_gen.get(),
				user_id=result[0],
				race_id=result[1]
			)
		group.save()
		gid = group.id
		marks_count = 0
		for par in parameters:
			if (par.name == "Питание" and 
				result[2] == results.models.TYPE_METERS and
				result[3] < 10000):
					continue
			if random.random() < percent_for_primary_rating / 100.0:
				marks_count += 1
				starrating.models.Primary(
						group_id=gid,
						parameter=par,
						value=random.randrange(1, MAX_RATING_VALUE + 1),
					).save()
		group.is_empty = (marks_count == 0)
		group.save()


def leave_one_rating(parameters=None, values=None, empty=False, percent=25):
#	random.seed(123)
	if parameters or values:
		raise NotImplementedError
	while True:
		user_id, race_id = random.choice(
			results.models.Result.objects.exclude(user=None).values_list(
				'user_id',
				'race_id',
			).distinct()[:2000]
		)
		if starrating.models.Group.objects.filter(user_id=user_id, race_id=race_id).exists():
			continue
		else:
			if empty:
				marks = {}
			else:
				marks = {
					p: random.randrange(1, MAX_RATING_VALUE + 1)
					for p in get_params_to_rate_for_race(race_id).values_list('pk', flat=True)
					if random.random() < percent / 100.0
				}
			group_id = leave_rating(race_id, user_id, None, marks, '', False, False)
			print("leave_one_rating: r={}, u={}, m={}, group_id={}".format(race_id, user_id, marks, group_id))
			return group_id


def generate_sample_reviews(percent=50, percent_reply=50, percent_show=50):
	random.seed(123)
	for group in starrating.models.Group.objects.exclude(
		id__in=starrating.models.User_review.objects.all().values('pk')
	).select_related(
		'user',
		'race__distance',
		'race__event',
	).only(
		'user__first_name',
		'user__last_name',
		'race__distance__name',
		'race__distance__distance_type',
		'race__distance__length',
		'race__distance__name',
		'race__event__name',
	).order_by('pk'):
		if random.random() < percent / 100.0:
			base_text = ' пользователя {} {} {} о дистанции {} {} {}'.format(
				group.user.id,
				group.user.first_name,
				group.user.last_name,
				group.race.id,
				group.race.event.name,
				group.race.distance,
			)
			review_text = 'Отзыв' + base_text
			if random.random() < percent_reply / 100.0:
				reply_text = 'Ответ на отзыв' + base_text
			else:
				reply_text = ''

			starrating.models.User_review.objects.create(
				group=group,
				content=review_text,
				show_user_name=(random.random() < percent_show / 100.0),
				response=reply_text,
			)
