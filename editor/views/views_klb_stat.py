# TODO -> ../klb_stat.py
from django.db.models import F, Sum
import datetime
import decimal
import re
import xlsxwriter
from collections import Counter

from results import models, models_klb, results_util
from editor import runner_stat
from typing import Optional, Tuple
from . import views_common

def length2bonus(length: int, year: int) -> decimal.Decimal:
	if length < models_klb.get_min_distance_for_bonus(year):
		return decimal.Decimal(0)
	return results_util.quantize(min(decimal.Decimal(length) / models_klb.get_bonus_score_denominator(year), models_klb.get_max_bonus_for_one_race(year)))

def roundup_centiseconds(centiseconds):
	seconds = centiseconds // 100
	if centiseconds % 100: # TODO: Remove in 2017
		seconds += 1
	return seconds

def distance2meters(distance_raw):
	distance_raw = distance_raw.strip()
	if distance_raw.endswith(' км'):
		distance_raw = distance_raw[:-3]
	res = re.match(r'^(\d{1,4})[\. ](\d{3})$', distance_raw) # 12.345 or 12 345
	if res:
		return True, int(res.group(1)) * 1000 + int(res.group(2))
	res = re.match(r'^(\d{1,4})\.(\d{2})$', distance_raw) # 12.34
	if res:
		return True, int(res.group(1)) * 1000 + int(res.group(2)) * 10
	res = re.match(r'^(\d{1,4})\.(\d{1})$', distance_raw) # 12.3
	if res:
		return True, int(res.group(1)) * 1000 + int(res.group(2)) * 100
	res = re.match(r'^(\d{1,4})$', distance_raw) # 12
	if res:
		return True, int(res.group(1)) * 1000
	res = re.match(r'^(\d{1,4})\.(\d{4})$', distance_raw) # 12.3456
	if res:
		return True, int(res.group(1)) * 1000 + int(round(int(res.group(2)) / 10))
	return False, 0

# Returns only sport score, no ITRA or other tunings
def get_sport_score(result_year: int, birth_year: int, gender: int, length: int, centiseconds: int) -> decimal.Decimal:
	if result_year <= 2021:
		class_year = 2017 if (result_year <= 2017) else 2018 # There are only 2017 and 2018 for now
		classes = models.Sport_class.objects.filter(year=class_year, gender=gender, length__lte=length).order_by('-length').first()
		return results_util.quantize(3 ** ( 2 + (classes.master_value - (centiseconds / 100)) / (classes.third_class_value - classes.master_value) ))
	if result_year > 2022:
		result_year = 2022 # FIXME

	if length <= 10000:
		top3_small_dist_time = models.Top_world_result.get_average_result(result_year, gender, results_util.DIST_5KM_ID)
		small_dist = 5000
		top3_average_dist_time = models.Top_world_result.get_average_result(result_year, gender, results_util.DIST_10KM_ID)
		average_dist = 10000
		top3_big_dist_time = models.Top_world_result.get_average_result(result_year, gender, results_util.DIST_HALFMARATHON_ID)
		big_dist = 21098
	if (length > 10000) and (length <= 42200):
		top3_small_dist_time = models.Top_world_result.get_average_result(result_year, gender, results_util.DIST_10KM_ID)
		small_dist = 10000
		top3_average_dist_time = models.Top_world_result.get_average_result(result_year, gender, results_util.DIST_HALFMARATHON_ID)
		average_dist = 21098
		top3_big_dist_time = models.Top_world_result.get_average_result(result_year, gender, results_util.DIST_MARATHON_ID)
		big_dist = 42195
	if (length > 42200) and (length <= 100000):
		top3_small_dist_time = models.Top_world_result.get_average_result(result_year, gender, results_util.DIST_HALFMARATHON_ID)
		small_dist = 21098
		top3_average_dist_time = models.Top_world_result.get_average_result(result_year, gender, results_util.DIST_MARATHON_ID)
		average_dist = 42195
		top3_big_dist_time = models.Top_world_result.get_average_result(result_year, gender, results_util.DIST_100KM_ID)
		big_dist = 100000
	if (length > 100000):
		top3_small_dist_time = models.Top_world_result.get_average_result(result_year, gender, results_util.DIST_MARATHON_ID)
		small_dist = 42195
		top3_average_dist_time = models.Top_world_result.get_average_result(result_year, gender, results_util.DIST_100KM_ID)
		average_dist = 100000
		top3_big_dist_time = 24 * 60 * 60 * 100
		big_dist = models.Top_world_result.get_average_result(result_year, gender, results_util.DIST_24HOURS_ID)
	coef_a = (top3_big_dist_time - top3_small_dist_time) * (average_dist - small_dist) - (top3_average_dist_time - top3_small_dist_time) * (big_dist - small_dist)
	coef_a /= ((big_dist ** 2) - (small_dist ** 2)) * (average_dist - small_dist) - ((average_dist ** 2) - (small_dist ** 2)) * (big_dist - small_dist)
	coef_b = (top3_average_dist_time - top3_small_dist_time - coef_a * ((average_dist ** 2) - (small_dist ** 2))) / (average_dist - small_dist)
	coef_c = top3_small_dist_time - coef_a * (small_dist ** 2) - coef_b * small_dist
	top3_world_result = coef_a * (length ** 2) + coef_b * length + coef_c
	return results_util.quantize(3 ** (2 + 3.33 - 3 * centiseconds / top3_world_result))

# Returns centiseconds for age 20-30, score, bonus score
def get_klb_score(result_year: int, birth_year: int, gender: int, length: int, centiseconds: int, itra_score: Optional[int]=0, debug: Optional[bool]=False) \
		-> Tuple[int, decimal.Decimal, decimal.Decimal]:
	if debug:
		print(f'length: {length}, centiseconds: {centiseconds}')
	bonus_score = length2bonus(length, result_year)

	clean_score = decimal.Decimal(0)
	if itra_score and (result_year >= 2019):
		clean_score = decimal.Decimal(itra_score / 2)

	if not (models_klb.get_min_distance_for_score(result_year) <= length <= models_klb.get_max_distance_for_score(result_year)):
		return centiseconds, clean_score, bonus_score

	# models.write_log(f'Running get_klb_coefficient for {result_year}, {gender}, {result_year - birth_year}, {length}')
	age_coef = models.Coefficient.get_klb_coefficient(result_year, gender, result_year - birth_year, length)
	# models.write_log(f'Result: {age_coef}')
	if result_year <= 2021:
		centiseconds = 100 * roundup_centiseconds(centiseconds)
	centiseconds_with_coef = int(round(centiseconds * age_coef))
	return centiseconds_with_coef, clean_score + get_sport_score(result_year, birth_year, gender, length, centiseconds_with_coef), bonus_score

def get_bonus_score_for_klb_result(klb_result):
	result = klb_result.result
	distance, was_real_distance_used = result.race.get_distance_and_flag_for_klb()
	meters = result.result if (distance.distance_type == models.TYPE_MINUTES_RUN) else distance.length
	year = result.race.start_date.year if result.race.start_date else result.race.event.start_date.year
	return length2bonus(meters, year)

def get_klb_scores_for_result(klb_result, debug=False):
	bonus_score = get_bonus_score_for_klb_result(klb_result)
	if klb_result.race.is_multiday:
		return 0, 0, bonus_score
	year = klb_result.race.event.start_date.year
	person = klb_result.klb_person
	race = klb_result.race
	distance = race.distance
	distance_length = distance.length if (klb_result.was_real_distance_used == models.DISTANCE_FOR_KLB_FORMAL) else race.distance_real.length
	if distance.distance_type in models.TYPES_MINUTES:
		length = klb_result.result.result
		centiseconds = distance_length * 6000
	else:
		length = distance_length
		if 21097 <= length <= 21099:
			length = 21100
		elif (year <= 2017) and (42195 <= length <= 42199):
			length = 42200
		elif (year >= 2018) and (42196 <= length <= 42200):
			length = 42195
		centiseconds = klb_result.result.result
	if centiseconds == 0: # It means there is some mistake
		return 0, 0, bonus_score
	return get_klb_score(year, person.birthday.year, person.gender, length, centiseconds, itra_score=race.itra_score, debug=debug)

def get_klb_score_for_result(klb_result, debug=False):
	return get_klb_scores_for_result(klb_result, debug=debug)[1]

def fill_klb_results_for_car(): # Some strange event in Sumy, Ukraine
	race = models.Race.objects.get(pk=29635)
	team = models.Klb_team.objects.get(pk=627)
	prev_score = team.score
	n_results_changed = 0
	for klb_result in list(race.klb_result_set.all()):
		if klb_result.klb_score == 0:
			person = klb_result.klb_person
			klb_result.klb_score = get_klb_score(race.event.start_date.year, person.birthday.year, person.gender,
				length=klb_result.result.result, centiseconds=klb_result.result.time_for_car, debug=False)[1]
			klb_result.save()
			n_results_changed += 1
	team.refresh_from_db()
	models.Klb_team_score_change.objects.create(
		team=team,
		race=race,
		clean_sum=team.score - team.bonus_score,
		bonus_sum=team.bonus_score,
		delta=team.score - prev_score,
		n_persons_touched=n_results_changed,
		comment='Обработка странной дистанции в КЛБМатч',
		added_by=models.USER_ROBOT_CONNECTOR,
	)
	print('Done! Results changed:', n_results_changed)

def fill_klb_results_for_car_2(): # Some strange event in Sumy, Ukraine
	race = models.Race.objects.get(pk=29635)
	team = models.Klb_team.objects.get(pk=627)
	prev_score = team.score
	n_results_changed = 0
	touched_persons = set()
	for klb_result in list(race.klb_result_set.all()):
		touched_persons.add(klb_result.klb_person)
		n_results_changed += 1
	update_persons_score(year=race.event.start_date.year, persons_to_update=touched_persons)
	team.refresh_from_db()
	models.Klb_team_score_change.objects.create(
		team=team,
		race=race,
		clean_sum=team.score - team.bonus_score,
		bonus_sum=team.bonus_score,
		delta=team.score - prev_score,
		n_persons_touched=n_results_changed,
		comment='Обработка странной дистанции в КЛБМатч',
		added_by=models.USER_ROBOT_CONNECTOR,
	)
	print('Done! Results changed:', n_results_changed)

def update_participant_score(participant, to_clean=True, to_calc_sum=True, to_update_team=False):
	year = participant.year
	results = participant.klb_person.klb_result_set.filter(race__event__start_date__year__range=models_klb.match_year_range(year))
	if to_clean:
		results.update(is_in_best=False, is_in_best_bonus=False)
	for result in results.order_by('-klb_score')[:models_klb.get_n_results_for_clean_score(year)]:
		result.is_in_best = True
		result.save()
	if models.is_active_klb_year(year):
		n_results_for_bonus_score = models_klb.get_n_results_for_bonus_score(year)
		if results.count() <= n_results_for_bonus_score:
			results.update(is_in_best_bonus=True)
		else:
			for result in results.order_by('-bonus_score')[:n_results_for_bonus_score]:
				result.is_in_best_bonus = True
				result.save()
		if to_calc_sum:
			participant.bonus_sum = results.filter(is_in_best_bonus=True).aggregate(Sum('bonus_score'))['bonus_score__sum']
			if participant.bonus_sum is None:
				participant.bonus_sum = 0
			participant.bonus_sum = min(participant.bonus_sum, models_klb.get_max_bonus_per_year(year))

			clean_sum = results.filter(is_in_best=True).aggregate(Sum('klb_score'))['klb_score__sum']
			if clean_sum is None:
				clean_sum = 0
			participant.score_sum = participant.bonus_sum + clean_sum
			participant.n_starts = results.count()
			participant.save()
		if to_update_team and participant.team:
			update_team_score(participant.team, to_calc_sum=True)

def update_participant_stat(participant, clean_stat=True, match_categories=None):
	year = participant.year
	if clean_stat:
		participant.klb_participant_stat_set.all().delete()
	klb_person = participant.klb_person
	result_ids = set(klb_person.klb_result_set.filter(event_raw__start_date__year__range=models_klb.match_year_range(year)).values_list(
		'result_id', flat=True))
	results = models.Result.objects.filter(pk__in=result_ids)
	if not results.exists():
		return
	n_marathons = 0
	n_ultramarathons = 0
	lengths = []
	for result in results:
		distance = result.race.get_distance_and_flag_for_klb()[0]
		meters = result.result if (distance.distance_type == models.TYPE_MINUTES_RUN) else distance.length
		lengths.append(meters)
		if 42195 <= meters <= 42200:
			n_marathons += 1
		elif meters > 42200:
			n_ultramarathons += 1
	if match_categories is None:
		match_categories = models.Klb_match_category.get_categories_by_year(year)
	stat_types = set(match_categories.values_list('stat_type', flat=True))
	if models.KLB_STAT_LENGTH in stat_types:
		participant.create_stat(models.KLB_STAT_LENGTH, sum(lengths))
	if models.KLB_STAT_N_MARATHONS in stat_types:
		participant.create_stat(models.KLB_STAT_N_MARATHONS, n_marathons)
	if models.KLB_STAT_N_ULTRAMARATHONS in stat_types:
		participant.create_stat(models.KLB_STAT_N_ULTRAMARATHONS, n_ultramarathons)
	if models.KLB_STAT_18_BONUSES in stat_types:
		participant.create_stat(models.KLB_STAT_18_BONUSES, sum(sorted(lengths)[-18:]))
	if (klb_person.gender == results_util.GENDER_MALE) and (models.KLB_STAT_N_MARATHONS_AND_ULTRA_MALE in stat_types):
		participant.create_stat(models.KLB_STAT_N_MARATHONS_AND_ULTRA_MALE, n_marathons + n_ultramarathons)
	if (klb_person.gender == results_util.GENDER_FEMALE) and (models.KLB_STAT_N_MARATHONS_AND_ULTRA_FEMALE in stat_types):
		participant.create_stat(models.KLB_STAT_N_MARATHONS_AND_ULTRA_FEMALE, n_marathons + n_ultramarathons)

def update_team_score(team, to_clean=True, to_calc_sum=False):
	participants = team.klb_participant_set.all()
	n_runners_for_club_clean_score = models_klb.get_n_runners_for_team_clean_score(team.year)
	if to_clean:
		if participants.count() <= n_runners_for_club_clean_score:
			participants.update(is_in_best=True)
		else:
			participants.update(is_in_best=False)
			for participant in participants.exclude(n_starts=0).annotate(
					clean_score=F('score_sum')-F('bonus_sum')).order_by('-clean_score', '-n_starts')[:n_runners_for_club_clean_score]:
				participant.is_in_best = True
				participant.save()
	if models.is_active_klb_year(team.year):
		if to_calc_sum:
			clean_score = participants.filter(is_in_best=True).aggregate(clean_score=Sum(F('score_sum')-F('bonus_sum')))['clean_score']
			if clean_score is None:
				clean_score = 0
			team.bonus_score = participants.aggregate(Sum('bonus_sum'))['bonus_sum__sum']
			if team.bonus_score is None:
				team.bonus_score = 0
			team.score = clean_score + team.bonus_score
		team.n_members = participants.count()
		team.n_members_started = participants.filter(n_starts__gt=0).count()
		team.save()

def fill_match_places(year, fill_age_places=False):
	place = 0
	place_small_teams = 0
	place_medium_teams = 0
	place_secondary_teams = 0
	models.Klb_team.objects.filter(year=year).update(place=None, place_small_teams=None, place_medium_teams=None, place_secondary_teams=None)
	small_team_limit = models_klb.get_small_team_limit(year)
	medium_team_limit = models_klb.get_medium_team_limit(year)
	for team in models.Klb_team.objects.filter(year=year).exclude(number=models.INDIVIDUAL_RUNNERS_CLUB_NUMBER).select_related('club').order_by(
			'-score', 'name'):
		team.n_members = team.klb_participant_set.count()
		place += 1
		team.place = place
		if team.n_members <= small_team_limit:
			place_small_teams += 1
			team.place_small_teams = place_small_teams
			if (year >= 2019) and team.name.startswith(team.club.name + '-') and not team.is_not_secondary_team:
				place_secondary_teams += 1
				team.place_secondary_teams = place_secondary_teams
		elif team.n_members <= medium_team_limit:
			place_medium_teams += 1
			team.place_medium_teams = place_medium_teams
		team.save()

	if fill_age_places:
		place = 0
		place_gender = {results_util.GENDER_FEMALE: 0, results_util.GENDER_MALE: 0}
		place_group = {}
		models.Klb_participant.objects.filter(year=year).update(place=None, place_gender=None, place_group=None)
		for participant in models.Klb_participant.objects.filter(year=year, score_sum__gt=0).select_related(
				'klb_person', 'age_group').order_by('-score_sum'):
			gender = participant.klb_person.gender
			group_id = participant.age_group.id

			place += 1
			place_gender[gender] += 1
			place_group[group_id] = place_group.get(group_id, 0) + 1

			participant.place = place
			participant.place_gender = place_gender[gender]
			participant.place_group = place_group[group_id]

			participant.save()
		models.Klb_age_group.objects.filter(year=year, gender=models.GENDER_UNKNOWN).update(
			n_participants=models.Klb_participant.objects.filter(year=year).count(),
			n_participants_started=place
		)
		for gender in [results_util.GENDER_FEMALE, results_util.GENDER_MALE]:
			models.Klb_age_group.objects.filter(year=year, birthyear_min=None, gender=gender).update(
				n_participants=models.Klb_participant.objects.filter(year=year, klb_person__gender=gender).count(),
				n_participants_started=place_gender[gender]
			)
		for group in models.Klb_age_group.objects.filter(year=year, birthyear_min__isnull=False):
			group.n_participants = models.Klb_participant.objects.filter(year=year, age_group=group).count()
			group.n_participants_started = place_group.get(group.id, 0)
			group.save()

def fill_participants_stat_places(year, match_categories=None, debug=False):
	if match_categories is None:
		match_categories = models.Klb_match_category.get_categories_by_year(models_klb.first_match_year(year))
	for match_category in match_categories:
		counter = 0
		cur_place = 0
		cur_value = -1
		for stat in models.Klb_participant_stat.objects.filter(klb_participant__year=year, stat_type=match_category.stat_type,
				value__gt=0).order_by('-value'):
			counter += 1
			if stat.value != cur_value:
				cur_place = counter
				cur_value = stat.value
			stat.place = cur_place
			stat.save()
		match_category.n_participants_started = counter
		match_category.save()
	if debug:
		print('Participants categories values are updated!')

def fill_categories_n_participants(year):
	""" Just once, for old years """
	for match_category in models.Klb_match_category.get_categories_by_year(year):
		match_category.n_participants_started = models.Klb_participant_stat.objects.filter(
			klb_participant__year=year, stat_type=match_category.stat_type, value__gt=0).count()
		match_category.save()
	print('Done!')

# Update everything: participants score, teams score. teams places, age group places
def update_match(year, debug=False):
	if debug:
		print('{} Started KLBMatch-{} update'.format(datetime.datetime.now(), year))
	models.Klb_result.objects.filter(race__event__start_date__year__range=models_klb.match_year_range(year)).update(
		is_in_best=False, is_in_best_bonus=False)
	models.Klb_participant_stat.objects.filter(klb_participant__year=year).delete()
	match_categories = models.Klb_match_category.get_categories_by_year(year)
	for participant in models.Klb_participant.objects.filter(year=year):
		update_participant_score(participant, to_clean=False)
		update_participant_stat(participant, clean_stat=False, match_categories=match_categories)
	for team in models.Klb_team.objects.filter(year=year):
		update_team_score(team, to_calc_sum=True)
	fill_match_places(year=year, fill_age_places=models.is_active_klb_year(year))
	fill_participants_stat_places(year=year, match_categories=match_categories, debug=debug)
	if debug:
		print("Year {} is updated".format(year))
		print("Match is updated!")
		print('{} Finished KLBMatch-{} update'.format(datetime.datetime.now(), year))

def update_persons_score(year, persons_to_update=[], update_runners=False, debug=False):
	if debug:
		print(f'{datetime.datetime.now()} Started persons score update')
	match_year = models_klb.first_match_year(year)
	participants = models.Klb_participant.objects.filter(year=match_year, klb_person__in=persons_to_update)
	team_ids = set(participants.filter(team__isnull=False).values_list('team', flat=True))
	teams = models.Klb_team.objects.filter(pk__in=team_ids)
	for participant in participants:
		update_participant_score(participant, to_calc_sum=True)
	for team in teams:
		update_team_score(team, to_calc_sum=True)
	fill_match_places(year=match_year)
	if update_runners:
		runner_stat.update_runners_and_users_stat(person.runner for person in persons_to_update)
	if debug:
		print('Persons are updated!')
		print(f'{datetime.datetime.now()} Finished persons score update')

def update_participants_score(participants, update_runners=False):
	persons_sets = {} # We make separate sets for every year
	persons_sets[models_klb.CUR_KLB_YEAR] = set()
	if models_klb.NEXT_KLB_YEAR:
		persons_sets[models_klb.NEXT_KLB_YEAR] = set()
	for participant in participants:
		if models.is_active_klb_year(participant.year):
			persons_sets[participant.year].add(participant.klb_person)
	for year, persons in list(persons_sets.items()):
		if persons:
			update_persons_score(year=year, persons_to_update=persons, update_runners=update_runners)

def check_wrong_results(year): # Are there any illegal results in KLBMatch?
	person_ids = set(models.Klb_result.objects.filter(race__event__start_date__year=year).values_list('klb_person_id', flat=True))
	for person in models.Klb_person.objects.filter(pk__in=person_ids).order_by('pk'):
		participants = {}
		for participant in person.klb_participant_set.all():
			participants[participant.year] = participant
		for klb_result in person.klb_result_set.select_related('race__event').filter(race__event__start_date__year=year):
			race = klb_result.race
			event = race.event
			race_date = race.start_date if race.start_date else event.start_date
			participant = participants.get(race_date.year)
			if participant is None:
				print('Вообще не участвовал в этом году: {} {} (id {}), забег {}, {} (id {})'.format(person.fname,
					person.lname, person.id, event.name, race_date, event.id))
				continue
			if participant.date_registered and (participant.date_registered > race_date):
				print('{} {} ({}{}) заявлен в матч {}, а забег {} ({}{}) прошёл {}'.format(
					person.fname, person.lname, results_util.SITE_URL, person.get_absolute_url(), participant.date_registered,
					event.name, results_util.SITE_URL, event.get_absolute_url(), race_date))
				continue
			if participant.date_removed and (participant.date_removed < race_date):
				print('{} {} ({}{}) удалён из матча {}, а забег {} ({}{}) прошёл {}'.format(
					person.fname, person.lname, results_util.SITE_URL, person.get_absolute_url(), participant.date_removed,
					event.name, results_util.SITE_URL, event.get_absolute_url(), race_date))
				continue
	print('Finished!')

def check_deleted_results():
	for year in range(2015, 2016):
		for participant in models.Klb_participant.objects.filter(year=year):
			person = participant.klb_person
			n_results_in_db = person.klb_result_set.filter(race__event__start_date__year=year).count()
			if n_results_in_db != participant.n_starts:
				print(year, person.id, person.runner.name(), n_results_in_db, participant.n_starts)
	print('Done!')

def check_bonuses(year, from_thousand=0):
	klb_results = models.Klb_result.objects.filter(klb_participant__year=year).select_related('result__race__distance')
	n_thousands = klb_results.count() // 1000
	for thousand in range(from_thousand, n_thousands + 1):
	# for thousand in range(0, 1):
		print(thousand)
		for klb_result in klb_results.order_by('pk')[thousand * 1000 : (thousand + 1) * 1000]:
			result = klb_result.result
			distance, was_real_distance_used = result.race.get_distance_and_flag_for_klb()
			meters = result.result if (distance.distance_type == models.TYPE_MINUTES_RUN) else distance.length
			new_score = length2bonus(meters, year)
			if klb_result.bonus_score != new_score:
				print (klb_result.id, klb_result.bonus_score, new_score)
				klb_result.bonus_score = new_score
				klb_result.save()
	print('Done!')

def match_participations_by_year(year):
	n_starts = Counter()
	for participant in models.Klb_participant.objects.filter(year=year):
		n_starts[participant.n_starts] += 1
	for key, val in list(n_starts.items()):
		print(key, val)

def create_age_groups(year):
	if year < 2010:
		print('{} is too small year'.format(year))
		return
	if models.Klb_age_group.objects.filter(year=year).exists():
		print('Looks like groups for year {} already exist'.format(year))
		return
	prev_year_groups = models.Klb_age_group.objects.filter(year=year - 1)
	if not prev_year_groups.exists():
		print('Looks like groups for previous year {} do not exist'.format(year))
		return
	n_groups = 0
	for prev_year_group in prev_year_groups:
		models.Klb_age_group.objects.create(
			year=year,
			birthyear_min=(prev_year_group.birthyear_min + 1) if prev_year_group.birthyear_min else None,
			birthyear_max=(prev_year_group.birthyear_max + 1) if prev_year_group.birthyear_max else None,
			gender=prev_year_group.gender,
			name=prev_year_group.name,
			order_value=prev_year_group.order_value,
		)
		n_groups += 1
	print("Done! We created {} groups for Match-{} on the model of Match-{}".format(n_groups, year, year - 1))

def fix_age_groups_once():
	for age_group in list(models.Klb_age_group.objects.filter(year=2020)):
		if age_group.birthyear_min:
			age_group.birthyear_min += 1
		if age_group.birthyear_max:
			age_group.birthyear_max += 1
		age_group.save()

def fill_age_groups(year):
	for participant in list(models.Klb_participant.objects.filter(year=year)):
		participant.fill_age_group()

def create_match_categories(year):
	if year < 2010:
		print('{} is too small year'.format(year))
		return
	if models.Klb_match_category.objects.filter(year=year).exists():
		print('Looks like match categories for year {} already exist'.format(year))
		return
	prev_year_groups = models.Klb_match_category.objects.filter(year=year - 1)
	if not prev_year_groups.exists():
		print('Looks like match categories for previous year {} do not exist'.format(year))
		return
	n_groups = 0
	for prev_year_group in prev_year_groups:
		models.Klb_match_category.objects.create(
			year = year,
			stat_type = prev_year_group.stat_type,
		)
		n_groups += 1
	print("Done! We created {} match categories for Match-{} on the model of Match-{}".format(n_groups, year, year - 1))

def create_all_for_new_match(year):
	if year < 2010:
		print('{} is too small year'.format(year))
		return
	if models.Klb_team.objects.filter(year=year, number=models.INDIVIDUAL_RUNNERS_CLUB_NUMBER).exists():
		print('Team for individuals already exists')
	else:
		team = models.Klb_team.objects.filter(number=models.INDIVIDUAL_RUNNERS_CLUB_NUMBER).order_by('-year').first()
		if team:
			team.id = None
			team.year = year
			team.save()
			print('Team for individuals was created!')
		else:
			print('We did not find team for individuals to clone')
	create_age_groups(year)
	create_match_categories(year)
	print(f'Age groups and categories for Match-{year} were created!')

def create_klb_coefs_for_2018():
	year_old = 2017
	year_new = 2018
	wrong_coefs = models.Sport_class.objects.filter(year=year_new)
	print('Wrong coefs to delete:', wrong_coefs.count())
	wrong_coefs.delete()
	old_coefs = models.Sport_class.objects.filter(year=year_old)
	print(year_old, "coefs total:", old_coefs.count())
	for coef in list(old_coefs.filter(length__gte=9500)):
		coef.id = None
		coef.year = 2018
		coef.save()
	print("Copied old to {}. Now {} coefs total:".format(year_new, year_old), models.Sport_class.objects.filter(year=year_old).count(),
		', {} coefs total:'.format(year_new), models.Sport_class.objects.filter(year=year_new).count())
	# In 2017 the step is 100 until 20000 and 200 after. We want to make step 10 until 25000
	new_step = 10
	classes = models.Sport_class.objects.filter(year=year_new)
	for start, stop, step in [(9500, 20000, 100), (20000, 25000, 200)]:
		for gender in (results_util.GENDER_FEMALE, results_util.GENDER_MALE):
			for length1 in range(start, stop, step):
				length2 = length1 + step
				class1 = classes.get(gender=gender, length=length1)
				class2 = classes.get(gender=gender, length=length2)
				# print('Class 1:', class1)
				# print('Class 2:', class2)
				for new_length in range(length1 + new_step, length2, new_step):
					new_class = models.Sport_class.objects.create(
						year=year_new,
						gender=gender,
						length=new_length,
						master_value=class1.master_value + int(round((class2.master_value - class1.master_value) * (new_length - length1) / (length2 - length1))),
						third_class_value=class1.third_class_value +
							int(round((class2.third_class_value - class1.third_class_value) * (new_length - length1) / (length2 - length1))),
					)
					# print('New class:', new_class)
	print('Done! {} classes now: '.format(year_new), models.Sport_class.objects.filter(year=year_new).count())

def fix_team_numbers(year):
	n_fixed = 0
	for p in models.Klb_participant.objects.filter(year=year):
		if p.calculate_team_number() != p.team_number:
			p.clean()
			p.save()
			n_fixed += 1
	print('Fixed numbers:', n_fixed)

def move_results_to_another_person(old_person_id, new_person_id): # Old person is a good one, new person is the one we're going to delete
	old_person = models.Klb_person.objects.get(pk=old_person_id)
	new_person = models.Klb_person.objects.get(pk=new_person_id)
	
	new_participants = new_person.klb_participant_set
	if new_participants.count() > 1:
		print('New person has too much participations:', new_participants.count())
		return
	if new_participants.count() == 0:
		print('New person has no participations')
		return
	new_participant = new_participants.first()
	year = new_participant.year
	if not models.is_active_klb_year(year):
		print('New participants year is not active now:', year)
		return
	if old_person.klb_participant_set.filter(year=year).exists():
		print('Both old and new persons participated in Match', year)
		return
	new_participant.klb_person = old_person
	new_participant.save()
	klb_results_touched = new_participant.klb_result_set.update(klb_person=old_person)
	results_touched = new_person.runner.result_set.update(runner=old_person.runner, user=old_person.runner.user)
	runner_stat.update_runner_stat(old_person.runner)
	print('Done! KLB results updated: {}, regular results updated: {}'.format(klb_results_touched, results_touched))

def print_different_scores():
	year = 2018
	for team in models.Klb_team.objects.filter(year=year).order_by('-score'):
		print(team.name + '\t' + str(team.score) + '\t',)
		for n_bonuses in (18, 15, 12, 10, 6):
			sum_bonuses = 0
			for participant in team.klb_participant_set.all():
				res = participant.klb_result_set.order_by('-bonus_score')[:n_bonuses].aggregate(Sum('bonus_score'))['bonus_score__sum']
				if res:
					sum_bonuses += res
			print(str(team.score - team.bonus_score + sum_bonuses) + '\t',)
		print()

def get_test_team_score(team, n_best_sport_results, bonuses_part):
	participants = team.klb_participant_set.all()
	participants_dict = {}
	for participant in participants:
		participants_dict[participant] = 0
		for result in participant.klb_result_set.order_by('-klb_score')[:n_best_sport_results]:
			participants_dict[participant] += result.klb_score
	clean_score = sum(sorted(list(participants_dict.values()), reverse=True)[:15])
	return clean_score, team.bonus_score / bonuses_part

def try_different_match_formulas():
	now = datetime.datetime.now()
	fname = results_util.XLSX_FILES_DIR + '/klb_formulas_{}.xlsx'.format(datetime.datetime.now().strftime('%Y%m%d_%H%M%S'))
	workbook = xlsxwriter.Workbook(fname)
	for n_best_sport_results in (3, 4, 5, 6):
		for bonuses_part in (1, 2, 3):
			worksheet = workbook.add_worksheet('{} лучших, бонусы делим на {}'.format(n_best_sport_results, bonuses_part))
			bold = workbook.add_format({'bold': True})
			number_format = workbook.add_format({'num_format': '0.000'})

			team_scores = {}
			for team in models.Klb_team.objects.filter(year=2018):
				team_scores[team] = get_test_team_score(team, n_best_sport_results, bonuses_part)

			for max_n_participants, first_row, place_field in ((100, 0, 'place'), (40, 15, 'place_small_teams'), (18, 30, 'place_medium_teams')):
				good_team_scores = [(k, v[0], v[1], v[0] + v[1]) for k, v in list(team_scores.items()) if k.n_members <= max_n_participants]

				first_teams = sorted(good_team_scores, key= lambda x: -x[3])[:10]

				row = first_row

				worksheet.write(row, 0, 'Место', bold)
				worksheet.write(row, 1, 'ID', bold)
				worksheet.write(row, 2, 'Команда', bold)
				worksheet.write(row, 3, 'Участников', bold)
				worksheet.write(row, 4, 'Спортивные', bold)
				worksheet.write(row, 5, 'Бонусы', bold)
				worksheet.write(row, 6, 'Сумма', bold)
				worksheet.write(row, 7, 'Текущее место', bold)
				worksheet.write(row, 8, 'Спортивные', bold)
				worksheet.write(row, 9, 'Бонусы', bold)
				worksheet.write(row, 10, 'Сумма', bold)

				# worksheet.set_column(0, 1, 3.29)
				# worksheet.set_column(2, 3, 17.29)
				# worksheet.set_column(4, 5, 31.86)
				# worksheet.set_column(6, 6, 40)
				# worksheet.set_column(7, 8, 10)
				# worksheet.set_column(9, 9, 11.57)
				# worksheet.set_column(10, 10, 9.29)

				# Iterate over the data and write it out row by row.
				for i, data in enumerate(first_teams):
					team = data[0]
					row += 1
					worksheet.write(row, 0, i + 1)
					worksheet.write(row, 1, team.id)
					worksheet.write(row, 2, team.name)
					worksheet.write(row, 3, team.n_members)
					worksheet.write(row, 4, data[1], number_format)
					worksheet.write(row, 5, data[2], number_format)
					worksheet.write(row, 6, data[3], number_format)
					worksheet.write(row, 7, getattr(team, place_field))
					worksheet.write(row, 8, team.score - team.bonus_score, number_format)
					worksheet.write(row, 9, team.bonus_score, number_format)
					worksheet.write(row, 10, team.score, number_format)

	workbook.close()
	return fname

@views_common.group_required('admins')
def get_test_formulas_file(request):
	from django.http import FileResponse
	fname = try_different_match_formulas()
	response = FileResponse(open(fname, 'rb'), content_type='application/vnd.ms-excel')
	response['Content-Disposition'] = 'attachment; filename="{}"'.format(fname.split('/')[-1])
	return response

def generate_reg_activity():
	dates = []
	years = list(range(2017, 2020))
	first_days = [datetime.date(year - 1, 12, 1) for year in years]
	gap = 5
	dates = []
	data = []
	last_day = datetime.date(years[0], 4, 1)
	while first_days[0] <= last_day:
		dates.append(first_days[0])
		print(first_days[0], end=" ")
		row = []
		for i in range(len(years)):
			row.append(models.Klb_participant.objects.filter(year=years[i], date_registered__gte=first_days[i],
				date_registered__lte=first_days[i] + datetime.timedelta(days=gap - 1)).count())
			first_days[i] += datetime.timedelta(days=gap)
		data.append(row)
		print(row)

def teams_with_professionals(year=2019):
	i = 1
	for klb_result in models.Klb_result.objects.filter(klb_participant__year=year, klb_score__gte=10, is_in_best=True,
			klb_participant__is_in_best=True).select_related(
			'klb_participant__team', 'klb_person__runner').order_by('klb_participant__team_id'):
		print(i, klb_result.klb_participant.team.name if klb_result.klb_participant.team else '',
			klb_result.klb_score, klb_result.klb_person.get_full_name_with_birthday())
		i += 1
