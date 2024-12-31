from django.db.models import Q, F, Count
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

from collections import Counter, defaultdict
import datetime
import io
import json
import os
import re
import urllib.parse

from results import models, models_klb, results_util
from results.views import views_user
from editor import parse_strings, runner_stat
from editor.scrape import nyrr, util
from editor.views import views_klb_stat, views_parkrun, views_result, views_stat

def extract_all_org_emails():
	three_years_back = datetime.date.today() - datetime.timedelta(days=1000)
	events = models.Event.objects.filter(
		Q(city__region__country_id='RU') | Q(city=None, series__city__region__country_id='RU'),
		start_date__gte=three_years_back)
	serieses = models.Series.objects.filter(
		pk__in=set(events.values_list('series_id', flat=True)))
	res = dict()
	for series in serieses:
		for field in ['director', 'contacts']:
			match = re.findall(r'[\w\.-]+@[\w\.-]+\.\w+', getattr(series, field))
			for email in match:
				em = email.lower()
				if em in res:
					res[em].add((series.id, series.name))
				else:
					res[em] = set([(series.id, series.name)])
	for event in events.select_related('series'):
		for field in ['email', 'contacts']:
			match = re.findall(r'[\w\.-]+@[\w\.-]+\.\w+', getattr(event, field))
			for email in match:
				em = email.lower()
				if em in res:
					res[em].add((event.series.id, event.series.name))
				else:
					res[em] = set([(event.series.id, event.series.name)])
	for a, b in sorted(res.items()):
		sample = next(iter(b))
		print(f'{a}#{len(b)}#{sample[0]}#{sample[1]}') # pytype: disable=unsupported-operands

def events_by_creator():
	year=2021
	all_events = models.Event.objects.filter(start_date__year=year)
	admins = set(Group.objects.get(name='admins').user_set.values_list('pk', flat=True))
	events_by_admins = all_events.filter(created_by__in=admins).count()
	events_by_robot = all_events.filter(created_by_id=4).count()
	events_by_none = all_events.filter(created_by=None).count()
	remaining = all_events.count() - events_by_none - events_by_robot - events_by_admins
	print('Все забеги в 2021:', all_events.count())
	print('Созданы админами:', events_by_admins)
	print('Созданы роботом присоединителем (паркраны):', events_by_robot)
	print('Неизвестно кем созданы:', events_by_none)
	print('Созданы пользователями:', remaining)
	for user in Group.objects.get(name='admins').user_set.all():
		print(user.get_full_name(), user.event_set.filter(start_date__year=year).count())

def all_klb_participants_emails(year=models_klb.CUR_KLB_YEAR):
	emails = set(models.Klb_participant.objects.filter(year=year).exclude(email='').values_list('email', flat=True))
	for email in sorted(emails):
		print(email)
	print(len(emails))


def return_participants_back():
	year = 2022
	club = models.Club.objects.get(pk=20)
	final_team = models.Klb_team.objects.get(pk=1309)
	for action in models.Table_update.objects.filter(row_id=1198, action_type=models.ACTION_PERSON_MOVE, added_time__gte=datetime.date(2022, 11, 1)).order_by(
			'child_id'):
		participant = models.Klb_participant.objects.get(pk=action.child_id)
		print(action.added_time, action.row_id, participant.team_id, participant.klb_person.runner.name())
		participant.team = final_team
		participant.clean()
		participant.save()
		models.log_obj_create(models.USER_ADMIN, final_team, models.ACTION_PERSON_MOVE, child_object=participant,
			field_list=['team'],
			comment='При перемещении участников между командами - исправление ошибки')

def most_records(distance: models.Distance):
	races_longer_than_ids = set(models.Race.objects.filter(distance=distance, distance_real__length__gte=distance.length).values_list('pk', flat=True))
	results = models.Result.objects.filter(Q(race__distance_real=None) | Q(race_id__in=races_longer_than_ids), status=models.STATUS_FINISHED, race__distance=distance).exclude(
		runner=None).order_by('race__event__start_date').values('runner_id', 'result')
	n_results = Counter() # by runner
	n_records = Counter() # by runner
	cur_best = {}
	for result in results:
		n_results[result['runner_id']] += 1
		if result['result'] < cur_best.get(result['runner_id'], 1000000000):
			cur_best[result['runner_id']] = result['result']
			n_records[result['runner_id']] += 1
	# for runner_id, count in n_records.most_common(30):
	# 	runner = models.Runner.objects.get(pk=runner_id)
	# 	print(f'{count-1} {n_results[runner_id]} {(count-1) / n_results[runner_id]} http://probeg.org{runner.get_absolute_url()} {runner.name()}')

	shares = [(runner_id, count-1, (count-1) / n_results[runner_id]) for runner_id, count in n_records.items() if (n_results[runner_id] >= 9)]
	print(len(shares))
	for runner_id, count, share in sorted(shares, key=lambda x: -x[2])[:20]:
		runner = models.Runner.objects.get(pk=runner_id)
		print(f'{share:.0%} {count} {n_results[runner_id]} http://probeg.org{runner.get_absolute_url()} {runner.name()}')

def empty_dumb_club_names():
	for name in ('нет клуба/no club', 'нет клуба', 'лично', '-'):
		results = models.Result.objects.filter(club_name=name)
		print(f'«{name}» - {results.count()}')
		print(results.update(club_name=''))

def CreatePopularDistances():
	for i in range(1, 100):
		models.Distance.objects.create(
			distance_type=models.TYPE_METERS,
			length=i * 1000,
			name=f'{i} km',
			popularity_value=1 if i in (5,10,15,20,25,30,35,40) else 0,
		)
	for i in range(1, 10):
		models.Distance.objects.create(
			distance_type=models.TYPE_METERS,
			length=int(round(i * models.MILE_IN_METERS)),
			name=f'{i} mile{"s" if i > 1 else ""}',
		)
	models.Distance.objects.create(
		distance_type=models.TYPE_METERS,
		length=42195,
		name='marathon',
		popularity_value=1,
	)
	models.Distance.objects.create(
		distance_type=models.TYPE_METERS,
		length=21098,
		name='half marathon',
		popularity_value=1,
	)

def CreateNYRRSeries():
	city = models.City.objects.get(region__name='New York', name='New York')
	organizer = models.Organizer.objects.get(
		name='New York Road Runners',
		url_site='https://www.nyrr.org/',
		url_facebook='https://www.facebook.com/NewYorkRoadRunners/',
		url_instagram='https://www.instagram.com/nyrr/',
	)
	for name, start_place in (
	):
		if not models.Series.objects.filter(name=name).exists():
			models.Series.objects.create(
				name=name,
				city=city,
				organizer=organizer,
				start_place=start_place,
				surface_type=results_util.SURFACE_ROAD,
				url_site='https://nyrr.org',
			)
	print('Done!')

def CreateNYRRSeriesNames():
	models.Series_name.objects.filter(platform_id='nyrr').delete()
	for series_name, event_name in (
	):
		series = models.Series.objects.filter(name=series_name).first()
		models.Series_name.objects.create(
			platform_id='nyrr',
			event_name=event_name,
			name=series_name,
			series=series,
		)
	print('Done!')

def fill_nyrr_event_ids():
	fixed = 0
	for row in models.Scraped_event.objects.filter(platform_id='nyrr', platform_event_id=''):
		if row.url_site.startswith('https://results.nyrr.org/event/') and row.url_site.endswith('/finishers'):
			row.platform_series_id = row.platform_event_id = row.url_site.removeprefix('https://results.nyrr.org/event/').removesuffix('/finishers')
			fixed += 1
			row.save()
		else:
			print(f'Wrong url: {row.url_site}')
	print(fixed)

def FillNyrrClubs():
	n_fixed = 0
	for race in models.Race.objects.filter(event__series_id=94).exclude(pk=8).exclude(pk=2):
		if race.event.platform_id != 'nyrr':
			raise Exception(f'Race {race.id}: wrong platform {race.event.platform_id}')
		platform_event_id = race.event.id_on_platform
		scraper = nyrr.NyrrScraper(url=f'https://results.nyrr.org/event/{platform_event_id}/finishers', platform_series_id=platform_event_id, platform_event_id=platform_event_id)
		with io.open(scraper.StandardFormPath(), encoding="utf8") as json_in:
			standard_form_dict = json.load(json_in)

		print(f'Event {platform_event_id}: {len(standard_form_dict["races"][0]["results"])} results')

		for result_dict in standard_form_dict["races"][0]["results"]:
			club = result_dict.get('club_raw')
			if not club:
				continue
			platform_result_id = result_dict['id_on_platform']
			result = models.Result.objects.get(id_on_platform=platform_result_id)
			if result.club_name:
				if (result.club_name != club):
					raise Exception(f'Race {race.id}, result {result.id}: different clubs, {result.club_name} in DB, {club} in json')
				continue
			result.club_name = club
			result.save()
			n_fixed += 1

	print(f'{n_fixed} fixed')

def FixNyrrRunnerIDs():
	# MIN_RESULT_ID = 1000000
	# cur_nyrr_runner_ids = [None] + sorted(set(models.Runner_platform.objects.filter(platform_id='nyrr', value__gt=MIN_RESULT_ID).values_list('value', flat=True)))
	# print(len(cur_nyrr_runner_ids))
	# with io.open('/home/chernov/pairs.txt', 'w', encoding='utf8') as f_out:
	# 	for i in range(1, len(cur_nyrr_runner_ids)):
	# 		f_out.write(f'{i} {cur_nyrr_runner_ids[i]}\n')

	# new_nyrr_runner_ids = {cur_nyrr_runner_ids[i]: i for i in range(1, len(cur_nyrr_runner_ids))}
	# results_updated = runner_platform_updated = nyrr_result_updated = 0
	# for i in range(1, len(cur_nyrr_runner_ids)):
	# 	if models.Nyrr_runner.objects.filter(pk=i).exists():
	# 		print(f'Nyrr_runner with id {i} already exists')
	# 		return
	# 	print(f'{cur_nyrr_runner_ids[i]} -> {i}')
	# 	runner = models.Runner_platform.objects.get(platform_id='nyrr', value=cur_nyrr_runner_ids[i]).runner
	# 	models.Nyrr_runner.objects.create(pk=i, fname=runner.fname, lname=runner.lname, sample_platform_id=cur_nyrr_runner_ids[i])
	# 	results_updated += models.Result.objects.filter(runner_id_on_platform=cur_nyrr_runner_ids[i]).update(runner_id_on_platform=i)
	# 	runner_platform_updated += models.Runner_platform.objects.filter(platform_id='nyrr', value=cur_nyrr_runner_ids[i]).update(value=i)
	# 	nyrr_result_updated += models.Nyrr_result.objects.filter(nyrr_runner_id=cur_nyrr_runner_ids[i]).update(nyrr_runner_id=i)
	# print(f'{results_updated} results updated, {runner_platform_updated} runner_platform, {nyrr_result_updated} nyrr_result')

	
	with open('/home/chernov/pairs.txt') as file:
		new_nyrr_runner_ids = {}
		for line in file:
			new_id, old_id = [int(s) for s in line.split()]
			new_nyrr_runner_ids[old_id] = new_id
			# if len(new_nyrr_runner_ids) >= 10:
			# 	break
	# print(new_nyrr_runner_ids)

	n_fixed = 0
	for race in models.Race.objects.filter(pk=9).order_by('pk'):
		if race.event.platform_id != 'nyrr':
			raise Exception(f'Race {race.id}: wrong platform {race.event.platform_id}')
		platform_event_id = race.event.id_on_platform
		scraper = nyrr.NyrrScraper(url=f'https://results.nyrr.org/event/{platform_event_id}/finishers', platform_series_id=platform_event_id, platform_event_id=platform_event_id)
		with io.open(scraper.StandardFormPath(), encoding="utf8") as json_in:
			scraper.standard_form_dict = json.load(json_in)

		for result_dict in scraper.standard_form_dict["races"][0]["results"]:
			if 'runner_id_on_platform' not in result_dict:
				if result_dict['fname_raw'] != 'Anonymous':
					raise util.NonRetryableError(f'{result_dict}: no runner_id_on_platform')
				continue
			new_runner_id = new_nyrr_runner_ids[result_dict["runner_id_on_platform"]]
			print(f'Race {race.id}, {platform_event_id}, result {result_dict["id_on_platform"]}: {result_dict["runner_id_on_platform"]} -> {new_runner_id}')
			result_dict['runner_id_on_platform'] = new_runner_id
			n_fixed += 1
		scraper.DumpStandardForm()
	print(f'{n_fixed} fixed')

def UnrecognizedDistances():
	for race in models.Race.objects.filter(distance__length=0).order_by('precise_name'):
		print(f'{race.precise_name}####{race.loaded_from}')

def FixDistancesOfLengthZero(): # TODO
	for race in list(models.Race.objects.filter(distance__length=0, distance__distance_type=models.TYPE_METERS).order_by('precise_name')):
		length = util.FixLength(parse_strings.parse_meters(length_raw=0, name=race.precise_name))
		if length > 0:
			race.distance = models.Distance.objects

def DeleteResultsWithRunners():
	for series_id in (548, 549):
		for result in models.Result.objects.filter(race__event__series_id=series_id).select_related('runner'):
			if runner := result.runner:
				runner.delete()
			result.delete()
		for race in models.Race.objects.filter(event__series_id=series_id):
			race.load_status = 0
			race.save()

def PrintRussianCities():
	for city in models.City.objects.filter(region__country_id='RU').select_related('region'):
		print(';'.join([str(city.id), city.name, city.name_orig, city.url_wiki, str(city.simplemaps_id), city.region.name]))

def DeleteDuplicateNyrrRunners():
	sample_ids = Counter(models.Nyrr_runner.objects.values_list('sample_platform_id', flat=True))
	repeating = [item for item, count in sample_ids.items() if count>1]
	n_deleted = n_merged = 0
	for sample_id in repeating:
		runner_to_keep = None
		for nyrr_runner in list(models.Nyrr_runner.objects.filter(sample_platform_id=sample_id)):
			runner_ids = list(models.Runner_platform.objects.filter(platform_id='nyrr', value=nyrr_runner.id).values_list('runner_id', flat=True))
			if not runner_ids:
				n_nyrr_results_deleted = models.Nyrr_result.objects.filter(nyrr_runner_id=nyrr_runner.id).delete()
				print(f'sample ID {sample_id}, nyrr_runner {nyrr_runner.id}: no runners. {n_nyrr_results_deleted} Nyrr_result records deleted')
				nyrr_runner.delete()
				n_deleted += 1
				continue
			for runner_id in runner_ids:
				runner = models.Runner.objects.get(pk=runner_id)
				if runner.result_set.exists():
					if runner_to_keep:
						if (runner.lname == runner_to_keep.lname) and (runner.fname == runner_to_keep.fname):
							success, err = runner_to_keep.merge(runner, allow_merge_nyrr=True)
							if success:
								n_merged += 1
								models.log_obj_delete(models.USER_ROBOT_CONNECTOR, runner,
									comment=f'When merging with runner {runner_to_keep.get_name_and_id()} from DeleteDuplicateNyrrRunners')
								runner.delete()
							else:
								print(f'sample ID {sample_id}, nyrr_runner {nyrr_runner.id}: '
									+ f'could not merge runners {runner_to_keep.get_name_and_id()} and {runner.get_name_and_id()}: {err}')
						else:
							print(f'sample ID {sample_id}, nyrr_runner {nyrr_runner.id}: '
								+ f'names of runners {runner_to_keep.get_name_and_id()} and {runner.get_name_and_id()} are different')
					else:
						runner_to_keep = runner
				else:
					models.log_obj_delete(models.USER_ROBOT_CONNECTOR, runner)
					runner.delete()
					n_deleted += 1
	print(f'Done! There were {len(repeating)} repeating sample_ids. Deleted {n_deleted} runners, merged {n_merged}.')

# For some Nyrr_result records, corresponding Nyrr_runner is already deleted (by DeleteDuplicateNyrrRunners). We should delete such records.
def DeleteRedundandNyrrResults():
	DeleteDuplicateNyrrRunners()
	existing_nyrr_runner_ids = set(models.Nyrr_runner.objects.all().values_list('id', flat=True))
	nyrr_runner_ids_from_result = set(models.Nyrr_result.objects.values_list('nyrr_runner_id', flat=True))
	non_existent_nyrr_runner_ids = nyrr_runner_ids_from_result - existing_nyrr_runner_ids
	print(len(nyrr_runner_ids_from_result), len(non_existent_nyrr_runner_ids))
	n_deleted = 0
	for nyrr_runner_id in non_existent_nyrr_runner_ids:
		res = models.Nyrr_result.objects.filter(nyrr_runner_id=nyrr_runner_id).delete()
		print(res)
		n_deleted += res[0]
	print(f'Deleted {n_deleted} records from Nyrr_result')

def WTC2024():
	year = 2024
	people = defaultdict(lambda: [''] * 14)
	for i, event_id in enumerate(
		('24WASH', 'H2024', '24BKH', '24QUEENS', '24CHAMPS5M', '24HARLEM', '24FAM', '24BX10M', '24SIHALF', 'M2024', )):
		race = models.Event.objects.get(platform_id='nyrr', id_on_platform=event_id).race_set.all()[0]
		top_runners = 5
		if event_id == 'M2024':
			top_runners = 3
		elif event_id == '24CHAMPS5M':
			top_runners = 10
		for j, result in enumerate(race.result_set.filter(club_name='Westchester TC', gender=results_util.GENDER_MALE).order_by('place')):
			if not result.place:
				raise Exception(f'Race {race.id}: no places!')
			res = 'Finished'
			if j < top_runners:
				res = 'Top'
			elif j < top_runners + 3:
				res = '3 after Top'
			people[f'{result.fname} {result.lname}'][i+3] = res
	for name in people.keys():
		people[name][0] = sum((1 if (j == 'Top'        ) else 0) for j in people[name][3:])
		people[name][1] = sum((1 if (j == '3 after Top') else 0) for j in people[name][3:]) + people[name][0]
		people[name][2] = sum((1 if (j == 'Finished'   ) else 0) for j in people[name][3:]) + people[name][1]
		print('&'.join([name] + [str(x) for x in people[name]]))
