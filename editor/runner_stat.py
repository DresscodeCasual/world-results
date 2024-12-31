import datetime
from typing import Iterable, List, Optional, Tuple

from django.contrib.auth.models import User

from results import models, results_util

# Returns the real length in meters and real time in centiseconds covered by the runner.
def length_time(result: models.Result) -> Tuple[int, int]:
	if result.race.distance.distance_type in models.TYPES_MINUTES:
		# 1 minute = 6000 centiseconds
		return result.result, result.race.distance.length * 6000
	time = 0 if (result.status == models.STATUS_COMPLETED) else result.result
	if result.race.distance_real:
		return result.race.distance_real.length, time
	return result.race.distance.length, time

def needed_for_next_step(next_val: int, lengths: Iterable[int]) -> int:
	return next_val - sum(length >= next_val * 1000 for length in lengths)

# Calculates https://en.wikipedia.org/wiki/Arthur_Eddington#Eddington_number_for_cycling.
# Returns the Eddington number and the amount of runs to achieve number+1.
def eddington(lengths: List[int]) -> Tuple[int, int]:
	if not lengths:
		return 0, 1
	lengths_desc = sorted(lengths, reverse=True)
	for i, length in enumerate(lengths_desc):
		if length < (i + 1) * 1000:
			return i, needed_for_next_step(i + 1, lengths_desc[:i])
	return len(lengths), needed_for_next_step(len(lengths) + 1, lengths)

# Returns two values:
# * list of lengths of all completed distances,
# * total time to complete them (when known) in deciseconds.
def update_distance_stat(
			distance: models.Distance,
			runner: Optional[models.Runner]=None,
			user: Optional[User]=None,
			club_member: Optional[models.Club_member]=None,
			year: Optional[int]=None,
		) -> Tuple[List[int], int]:
	if runner:
		result_set = runner.result_set
		person = runner
	elif user:
		result_set = user.result_set
		person = user.user_profile if hasattr(user, 'user_profile') else models.User_profile(user=user)
	elif club_member:
		result_set = club_member.runner.result_set
		person = club_member.runner
	else:
		raise Exception('Exactly one of runner, user, club_member must be not None.')

	to_calc_age_coef_data = club_member and (distance.distance_type not in models.TYPES_MINUTES) \
		and (person.gender != models.GENDER_UNKNOWN) and person.birthday

	result_set = result_set.filter(
		race__distance=distance,
		race__exclude_from_stat=False,
		do_not_count_in_stat=False,
		status__in=(models.STATUS_FINISHED, models.STATUS_COMPLETED),
	)
	if year:
		result_set = result_set.filter(race__event__start_date__year=year)
	if club_member:
		if club_member.date_registered:
			result_set = result_set.filter(race__event__start_date__gte=club_member.date_registered)
		if club_member.date_removed:
			result_set = result_set.filter(race__event__start_date__lte=club_member.date_removed)
	results = result_set.select_related('race__event', 'race__distance', 'race__distance_real').order_by(
		'-result' if (distance.distance_type in models.TYPES_MINUTES) else 'result')

	lengths = []
	results_with_time = []
	total_time = 0
	for result in results:
		length, time = length_time(result)
		lengths.append(length)
		if time:
			results_with_time.append(result)
			total_time += time
	if not lengths:
		return [], 0

	stat = models.User_stat(runner=runner, user=user, club_member=club_member, distance=distance, year=year)
	stat.n_starts = len(lengths)
	results_sum = 0
	# Let's find best race with real distance not less than official distance.
	if results_with_time: # Or maybe we have only result with status=models.STATUS_COMPLETED.
		value_best = None
		results_sum = 0

		value_best_age_coef = None
		time_age_coef_best = None
		results_age_coef_sum = 0

		for result in results_with_time:
			results_sum += result.result
			if (value_best is None) and ( (result.race.distance_real is None) or (result.race.distance_real.length > result.race.distance.length) ):
				value_best = result

			if to_calc_age_coef_data: # So the distance is measured in meters
				result_year = result.race.event.start_date.year
				result_age_coef = result.result * models.Coefficient.get_klb_coefficient(result_year, person.gender,
					result_year - person.birthday.year, distance.length)
				results_age_coef_sum += result_age_coef
				if (
						( (value_best_age_coef is None) or (time_age_coef_best > result_age_coef) )
					and ( (result.race.distance_real is None) or (result.race.distance_real.length > result.race.distance.length) )
					):
					value_best_age_coef = result
					time_age_coef_best = result_age_coef

		if value_best is None:
			value_best = results_with_time[0]
		if to_calc_age_coef_data and (value_best_age_coef is None):
			value_best_age_coef = results_with_time[0]
			time_age_coef_best = results_with_time[0].result # Not exact but let it be...

		race_best = value_best.race
		stat.best_result = value_best
		stat.value_best = value_best.result
		stat.pace_best = race_best.get_pace(stat.value_best)

		stat.value_mean = int(round(results_sum / len(results_with_time)))
		stat.pace_mean = distance.get_pace(stat.value_mean)
		if (distance.distance_type not in models.TYPES_MINUTES) and (stat.value_mean > 6000):
			stat.value_mean = int(round(stat.value_mean, -2))

		if to_calc_age_coef_data:
			race_age_coef_best = value_best_age_coef.race # pytype: disable=attribute-error
			stat.best_result_age_coef = value_best_age_coef
			stat.value_best_age_coef = time_age_coef_best
			stat.value_mean_age_coef = int(round(results_age_coef_sum / len(results_with_time)))

	try:
		stat.save()
	except Exception as e:
		# Sometimes it causes Duplicate entry errors.
		pass
		# fields = []
		# if runner:
		# 	fields.append(f'runner {runner.id}')
		# if user:
		# 	fields.append(f'user {user.id}')
		# if club_member:
		# 	fields.append(f'club_member {club_member}')
		# if distance:
		# 	fields.append(f'distance {distance}')
		# if year:
		# 	fields.append(f'year {year}')
		# if stat.pace_best:
		# 	fields.append(f'pace_best {stat.pace_best}')
		# models.send_panic_email('Problem when saving stat', f'For {", ".join(fields)}: {repr(e)}')
	return lengths, total_time

def update_club_member_stat(club_member, distance, year):
	if year:
		years = [year]
	else: # We have to update all years when member was in club
		min_year = models.FIRST_YEAR_FOR_STAT_UPDATE
		if club_member.date_registered and club_member.date_registered.year > min_year:
			min_year = club_member.date_registered.year
		max_year = datetime.date.today().year
		if club_member.date_removed and club_member.date_removed.year < max_year:
			max_year = club_member.date_removed.year
		years = [None] + list(range(min_year, max_year + 1))
	for member_year in years:
		update_distance_stat(distance, club_member=club_member, year=member_year)

DISTANCE_LIMIT = 5
# Exactly one of runner, user, club_member must be not None
def update_runner_stat(runner=None, user=None, club_member=None, year=None, update_club_members=True):
	person = None
	person_for_stat = None
	club_members = []
	if runner:
		result_set = runner.result_set
		person = runner
		person_for_stat = runner
		if update_club_members:
			club_members = runner.club_member_set.all()
	elif user:
		result_set = user.result_set
		person = user
		if hasattr(user, 'user_profile'):
			person_for_stat = user.user_profile
		if update_club_members and hasattr(user, 'runner'):
			club_members = user.runner.club_member_set.all()
	elif club_member:
		result_set = club_member.runner.result_set
		person = club_member
		club_members = [club_member]

	if person is None:
		return

	all_lengths = []
	total_time = 0
	all_lengths_cur_year = []
	total_time_cur_year = 0
	cur_year = results_util.CUR_YEAR_FOR_RUNNER_STATS

	if runner or user:
		person.user_stat_set.all().delete()
	if update_club_members:
		for m in club_members:
			if year:
				m.user_stat_set.filter(year=year).delete()
			else:
				m.user_stat_set.all().delete()

	distance_ids = result_set.filter(
			status__in=(models.STATUS_FINISHED, models.STATUS_COMPLETED),
			race__distance__distance_type__in=models.TYPES_FOR_RUNNER_STAT,
		).order_by(
		'race__distance_id').values_list('race__distance_id', flat=True).distinct()
	for distance_id in distance_ids:
		distance = models.Distance.objects.get(pk=distance_id)
		if person_for_stat:
			lengths, sum_time = update_distance_stat(distance, runner=runner, user=user, club_member=club_member)
			all_lengths += lengths
			total_time += sum_time
			if runner:
				lengths, sum_time = update_distance_stat(distance, runner=runner, user=user, club_member=club_member, year=cur_year)
				all_lengths_cur_year += lengths
				total_time_cur_year += sum_time
		if update_club_members and (distance_id in results_util.DISTANCES_FOR_CLUB_STATISTICS):
			for m in club_members:
				update_club_member_stat(m, distance, year)

	if person_for_stat:
		person_for_stat.n_starts = len(all_lengths)
		person_for_stat.total_length = sum(all_lengths)
		person_for_stat.total_time = total_time
		if runner:
			person_for_stat.n_starts_cur_year = len(all_lengths_cur_year)
			person_for_stat.total_length_cur_year = sum(all_lengths_cur_year)
			person_for_stat.total_time_cur_year = total_time_cur_year
			person_for_stat.eddington, person_for_stat.eddington_for_next_level = eddington(all_lengths)
			person_for_stat.eddington_cur_year, person_for_stat.eddington_for_next_level_cur_year = eddington(all_lengths_cur_year)
		if distance_ids.count() > DISTANCE_LIMIT:
			for user_stat in person.user_stat_set.filter(year=None).order_by('-n_starts', '-distance__length')[:DISTANCE_LIMIT]:
				user_stat.is_popular = True
				user_stat.save()
			person_for_stat.has_many_distances = True
		else:
			person_for_stat.has_many_distances = False
		person_for_stat.save()

def update_runner_and_user_stat(runner: models.Runner, update_club_members: bool=False):
	update_runner_stat(runner=runner)
	if runner.user:
		update_runner_stat(user=runner.user, update_club_members=update_club_members)

# When running this, please check that runners and their users and their profiles are loaded from DB
def update_runners_and_users_stat(runners: Iterable[models.Runner]):
	for runner in runners:
		update_runner_and_user_stat(runner)

def update_race_runners_stat(race):
	n_runners = 0
	for result in race.result_set.filter(runner__isnull=False).select_related('runner', 'user'):
		update_runner_and_user_stat(result.runner)
		n_runners += 1
	return n_runners

def update_runners_stat(id_from=0, reset_cur_year_stat=False, debug=0):
	runners = models.Runner.objects.all()
	THOUSAND = 100
	if debug:
		print(f'{datetime.datetime.now()} update_runners_stat started')
	n_runners = 0
	first_thousand = (id_from // THOUSAND) + 1
	max_thousand = (runners.order_by('-pk').first().id // THOUSAND) + 1

	if reset_cur_year_stat:
		runners.update(n_starts_cur_year=None, total_length_cur_year=None, total_time_cur_year=None)

	for thousand in range(first_thousand, max_thousand + 1):
		for runner in runners.filter(id__range=(max(id_from, THOUSAND * (thousand - 1)), thousand * THOUSAND)).order_by('id'):
			update_runner_stat(runner=runner, update_club_members=False)
			if debug >= 2:
				print('Runner with id {} was updated'.format(runner.id))
			n_runners += 1
		if debug:
			print('{} Thousand finished: {}'.format(datetime.datetime.now(), thousand))
	if debug:
		print(f'{datetime.datetime.now()} update_runners_stat finished. Number of updated runners: {n_runners}')
	return n_runners

def update_users_stat():
	for user in User.objects.filter(user_profile__isnull=False):
		update_runner_stat(user=user)

def update_club_members_stat():
	n_members = 0
	for member in models.Club_member.objects.order_by('id'):
		update_runner_stat(club_member=member)
		n_members += 1
		if (member.id % 100) == 0:
			print(member.id)
	print("Done! Members updated:", n_members)
