from django.urls import reverse
from django.contrib.auth.models import User
from django.db.models import Count, Q
from django.utils import timezone
from django.conf import settings
from collections import Counter
import datetime
import logging
import re
import io
from typing import List, Optional, Tuple

from results import models, models_klb, results_util
from editor import klb_letters, monitoring, runner_stat
from dbchecks import dbchecks

def update_race_size_stat(debug=False):
	bad_races = []
	n_races_added = 0
	thousand_max = models.Race.objects.order_by('-pk').values_list('pk', flat=True)[0] // 1000
	for thousand in range(0, thousand_max + 1):
		if debug:
			print(thousand)
		for race in models.Race.objects.filter(event__start_date__lte=datetime.date.today(),
				pk__range=(1000*thousand, 1000*(thousand+1) - 1)).select_related(
				'event', 'race_size', 'distance').annotate(n_results=Count('result')).order_by('id'):
			if hasattr(race, 'race_size'):
				race_size = race.race_size
				if race.n_results < race_size.n_results - 1:
					bad_races.append((race, race_size.last_update, race_size.n_results, race.n_results))
				race_size.n_results = race.n_results
				race_size.save()
			else:
				models.Race_size.objects.create(race=race, n_results=race.n_results)
				n_races_added += 1
	if debug:
		for race, last_update, old_n_results, n_results in bad_races:
			print('{}, {} (id {}): {} было {} результатов, сейчас {} результатов'.format(
				race.name_with_event(), race.event.date(), race.id, last_update, old_n_results, n_results))
		print('Учтено новых дистанций:', n_races_added)
	res = ''
	if bad_races:
		res += f'\n\nДистанции, на которых уменьшилось число результатов ({len(bad_races)}):'
		for race, last_update, old_n_results, n_results in bad_races:
			res += (f'\n{race.name_with_event()}, {race.event.date(with_nobr=False)}, {results_util.SITE_URL}{race.get_absolute_url()}:'
				+ f' {last_update} было {old_n_results} результатов, сейчас {n_results} результатов')
	return res

def best_result2value(distance, result): # Converts value from best_result field to centiseconds or meters
	result = result.strip()
	if result == '':
		return 0
	if distance.distance_type in models.TYPES_MINUTES:
		if result[-1] != 'м':
			return 0
		return results_util.int_safe(result[:-1].strip())
	else:
		res = re.match(r'^(\d{1,3}):(\d{2}):(\d{2})$', result)
		if res:
			return ((int(res.group(1)) * 60 + int(res.group(2))) * 60 + int(res.group(3))) * 100
		else:
			return 0

def update_course_records(series, to_clean=True, debug=False):
	races = models.Race.objects.filter(Q(load_status=models.RESULTS_LOADED) | ~Q(winner_male=None) | ~Q(winner_female=None) | ~Q(winner_nonbinary=None),
		event__series=series).select_related('distance', 'distance_real')
	if to_clean:
		races.update(is_course_record_male=False, is_course_record_female=False, is_course_record_nonbinary=False)

	gender_codes = dict(results_util.GENDER_CODES)
	del gender_codes[results_util.GENDER_UNKNOWN]

	best_result_by_gender_distance = {} # (gender, distance) -> result
	for race in races.filter(is_for_handicapped=False, distance_real=None).order_by('event__start_date'):
		distance = race.distance_real if race.distance_real else race.distance

		for gender in gender_codes.keys():
			best_result = race.result_set.filter(gender=gender, is_improbable=False).exclude(place_gender=None).order_by('place_gender', 'lname', 'fname').first()
			if not best_result:
				continue
			setattr(race, f'winner_{gender_codes[gender]}', best_result)
			if distance.distance_type in models.TYPES_MINUTES:
				if ((gender, distance) not in best_result_by_gender_distance) or (best_result_by_gender_distance[(gender, distance)].result < best_result.result):
					best_result_by_gender_distance[(gender, distance)] = best_result
			else:
				if ((gender, distance) not in best_result_by_gender_distance) or (best_result_by_gender_distance[(gender, distance)].result > best_result.result):
					best_result_by_gender_distance[(gender, distance)] = best_result
		race.save()

	for gender_distance, result in best_result_by_gender_distance.items():
		gender, distance = gender_distance
		field_is_record = f'is_course_record_{gender_codes[gender]}'
		setattr(result.race, field_is_record, True)
		result.race.save()

def get_runners_by_name_and_birthyear(lname, fname, year):
	runners = models.Runner.objects.filter(lname=lname, fname=fname, birthday__year=year)
	runners_with_extra_name_ids = models.Extra_name.objects.filter(lname=lname, fname=fname, runner__birthday__year=year).values_list(
		'runner_id', flat=True)
	return runners.union(models.Runner.objects.filter(pk__in=set(runners_with_extra_name_ids)))

def get_runners_by_name_and_birthday(lname, fname, midname, birthday):
	runners = models.Runner.objects.filter(lname=lname, fname=fname, birthday_known=True, birthday=birthday)
	if midname:
		runners = runners.filter(midname__in=('', midname))
	runners_with_extra_name = models.Extra_name.objects.filter(lname=lname, fname=fname, runner__birthday_known=True, runner__birthday=birthday)
	if midname:
		runners_with_extra_name = runners_with_extra_name.filter(midname__in=('', midname))
	runners_with_extra_name_ids = runners_with_extra_name.values_list('runner_id', flat=True)
	return runners.union(models.Runner.objects.filter(pk__in=set(runners_with_extra_name_ids)))

def get_new_results_text(results_by_race):
	res = ''
	n_results = 0
	races = sorted(results_by_race.keys(), key=lambda race: (race.event.name, race.distance.distance_type, -race.distance.length))
	for race in races:
		event = race.event
		start_date = results_util.date2str(event.start_date, with_nbsp=False)
		res += f'\n{event.name}, {race.get_precise_name()}, {start_date}, {results_util.SITE_URL}{race.get_absolute_url()} :\n'
		for result, runner, comment in sorted(results_by_race[race], key=lambda x: (x[0].lname, x[0].fname, x[0].midname)):
			n_results += 1
			res += (f'{n_results}. Результат с id {result.id} ({result}, {result.strName()}) '
				+ f'— к бегуну {runner.name()} {results_util.SITE_URL}{runner.get_absolute_url()} {comment}\n')
	return res

def attach_results_with_birthday(robot, admin, debug=False):
	n_results = 0
	n_results_for_klb = 0
	n_results_with_user = 0
	n_midnames_filled = 0
	n_winners_touched = 0
	touched_runners = set()
	new_results_by_race = {}
	mail_body = ''
	mail_errors = ''
	mail_summary = ''
	name_birthday_tuples = set(models.Result.objects.filter(runner=None, birthday_known=True, source=models.RESULT_SOURCE_DEFAULT, bib_given_to_unknown=False).exclude(
		lname='').exclude(fname='').values_list('lname', 'fname', 'midname', 'birthday'))
	if debug:
		print('Different tuples:', len(name_birthday_tuples))
	mail_header = (f'\nСегодня у нас {len(name_birthday_tuples)} различных наборов (ФИО, дата рождения) у результатов,'
			+ ' не присоединённых ни к какому бегуну.')
	for lname, fname, midname, birthday in sorted(name_birthday_tuples):
		if n_results > 999:
			break
		runners = get_runners_by_name_and_birthday(lname, fname, midname, birthday)
		runners_count = runners.count()
		if runners_count > 1:
			mail_errors += (f'\nЕсть больше одного бегуна {lname} {fname} {midname} {birthday.isoformat()}. Непонятно, к кому присоединять такие результаты. '
				+ results_util.SITE_URL + results_util.reverse_runners_by_name(lname, fname))
			if len(mail_errors) > 5000:
				break
		elif runners_count == 1:
			runner = runners[0]
			for result in models.Result.objects.filter(runner=None, birthday_known=True, source=models.RESULT_SOURCE_DEFAULT,
					lname=lname, fname=fname, midname=midname, birthday=birthday, bib_given_to_unknown=False).select_related('race__event'):
				n_results += 1
				race = result.race
				event = race.event
				event_date = event.start_date
				result.runner = runner
				field_list = ['runner']
				comment = ''
				if runner.user:
					result.user = runner.user
					result.add_for_mail()
					field_list.append('user')
					n_results_with_user += 1
					user_url = ''
					if hasattr(runner.user, 'user_profile'):
						user_url = results_util.SITE_URL + runner.user.user_profile.get_absolute_url()
					comment += f' Добавляем результат пользователю {runner.user.get_full_name()} {user_url} .'
				if result.midname and not runner.midname:
					runner.midname = result.midname
					comment += f' Поставили бегуну отчество {result.midname} от результата.'
					n_midnames_filled += 1
					runner.save()
					models.log_obj_create(robot, runner, models.ACTION_UPDATE, field_list=['midname'],
						comment='Автоматически при добавлении результата с id {}'.format(result.id), verified_by=admin)
				result.save()
				touched_runners.add(runner)
				is_for_klb = False
				klb_participant = None
				if runner.klb_person and models.is_active_klb_year(event_date.year):
					klb_participant = runner.klb_person.klb_participant_set.filter(year=event_date.year).first()
				if klb_participant and (result.get_klb_status() == models.KLB_STATUS_OK) \
						and ( (klb_participant.date_registered == None) or (klb_participant.date_registered <= event_date) ) \
						and ( (klb_participant.date_removed == None) or (klb_participant.date_removed >= event_date) ) \
						and not runner.klb_person.klb_result_set.filter(race__event=event).exists():
					is_for_klb = True
				models.log_obj_create(robot, event, models.ACTION_RESULT_UPDATE, field_list=field_list,
					child_object=result, comment='Автоматически по имени и дате рождения', is_for_klb=is_for_klb,
					verified_by=None if is_for_klb else admin)
				if is_for_klb:
					n_results_for_klb += 1
					comment += ' Добавляем результат в КЛБМатч.'
				if result.place_gender == 1:
					race.fill_winners_info()
					n_winners_touched += 1
				if race not in new_results_by_race:
					new_results_by_race[race] = []
				new_results_by_race[race].append((result, runner, comment))
	runner_stat.update_runners_and_users_stat(touched_runners)
	if n_results:
		mail_body = '\n\nПрисоединяем следующие результаты с датой рождения к бегунам:\n\n' + get_new_results_text(new_results_by_race)
		mail_summary += (f'\n\nИтого присоединено результатов: {n_results}. В том числе:\n'
			+ f'Отправлены на модерацию в КЛБМатч: {n_results_for_klb}.\nПривязаны к пользователям: {n_results_with_user}.')
		if n_midnames_filled:
			mail_summary += f'\n\nЗаполнены отчества бегунам на основании протоколов: {n_midnames_filled}.'
		n_users_for_letters = len(set(models.Result_for_mail.objects.filter(
			user__isnull=False, user__is_active=True, user__user_profile__email_is_verified=True, user__user_profile__ok_to_send_results=True,
			is_sent=False).exclude(user__email='').values_list('user_id', flat=True)))
		mail_summary += f'\n\nПользователей, которым надо написать письма о новых результатах: {n_users_for_letters}.'

	yesterday = datetime.date.today() - datetime.timedelta(days=1)
	letters_sent_yesterday = models.Message_from_site.objects.filter(message_type=models.MESSAGE_TYPE_RESULTS_FOUND, date_posted__date__gte=yesterday)
	n_letters_errors = letters_sent_yesterday.filter(is_sent=0).count()
	mail_summary += f'\nОтправлено писем о новых результатах вчера: {letters_sent_yesterday.count()}, ошибок возникло: {n_letters_errors}.'

	if n_winners_touched:
		mail_summary += f'\n\nПривязано результатов победителей забегов: {n_winners_touched}.'
	if mail_errors:
		mail_errors = '\n\nОшибки при присоединении результатов к бегунам по дате рождения:\n\n' + mail_errors
	if debug:
		print(f'Finished! Total results number: {n_results}, for KLB: {n_results_for_klb}')
	return mail_header, mail_errors, mail_body, mail_summary

# Counts the number of results in the whole database with given first name with all genders
# and returns a string like 'М: 0, Ж: 5, неизв.: 1'.
def genders_for_name(fname: str) -> str:
	results = models.Result.objects.filter(fname=fname)
	parts = [
		f'М: {results.filter(gender=results_util.GENDER_MALE).count()}',
		f'Ж: {results.filter(gender=results_util.GENDER_FEMALE).count()}',
	]
	n_unknown = results.filter(gender=results_util.GENDER_UNKNOWN).count()
	if n_unknown > 0:
		parts.append(f'неизв.: {n_unknown}')
	return ', '.join(parts)

def create_new_runners_with_birthdays(robot, admin, debug=False):
	errors_midnames = ''
	errors_same_name = ''
	errors_unknown_gender = ''
	mail_body = ''
	mail_summary = ''
	free_official_results = models.Result.objects.filter(runner=None, birthday_known=True, source=models.RESULT_SOURCE_DEFAULT, bib_given_to_unknown=False)
	name_birthday_tuples_counter = Counter([(a.lower(), b.lower(), c) for a, b, c in free_official_results.exclude(
		lname='').exclude(fname='').values_list('lname', 'fname', 'birthday')])
	name_birthday_tuples = set([k for k, v in list(name_birthday_tuples_counter.items()) if (v > 1)])
	runner_tuples = set([(a.lower(), b.lower(), c) for a, b, c in models.Runner.objects.filter(birthday_known=True).values_list(
		'lname', 'fname', 'birthday')])
	n_good_tuples = n_similar_runnes_errors = n_errors_unknown_gender = 0
	report_success = ''
	report_errors = ''
	for lname, fname, birthday in sorted(name_birthday_tuples - runner_tuples):
		if n_good_tuples >= 100:
			break
		results = free_official_results.filter(lname=lname, fname=fname, birthday=birthday)
		cur_midname = ''
		midname_error = False
		midnames = set(results.values_list('midname', flat=True))
		for midname in midnames:
			midname = midname.lower()
			if midname == '':
				continue
			if cur_midname.startswith(midname):
				continue
			if midname.startswith(cur_midname):
				cur_midname = midname
				continue
			midname_error = True
		runners_by_name_url = results_util.SITE_URL + results_util.reverse_runners_by_name(lname, fname)
		if midname_error:
			if debug:
				print('Data:', lname, fname, birthday)
				print('Midnames:', ', '.join(sorted(midnames)))
			errors_midnames += f'\n{lname} {fname} ({birthday}) ' + ', '.join(sorted(midnames)) + ' ' + runners_by_name_url
			continue
		# print lname.title(), fname.title(), cur_midname.title(), unicode(birthday), unicode(results.count())
		n_similar_runners = get_runners_by_name_and_birthyear(lname, fname, birthday.year).count()
		if n_similar_runners:
			n_similar_runnes_errors += 1
			errors_same_name += f'\n{n_similar_runnes_errors}. {lname} {fname} ({birthday}) ' + runners_by_name_url
			continue
		gender = models.Runner_name.objects.filter(name=fname).first()
		if gender is None:
			n_errors_unknown_gender += 1
			errors_unknown_gender += f'\n{n_errors_unknown_gender}. {lname} {fname} ({genders_for_name(fname)}) ' + runners_by_name_url
			continue
		runner = models.Runner.objects.create(
			lname=lname.title(),
			fname=fname.title(),
			midname=cur_midname.title(),
			birthday=birthday,
			birthday_known=True,
			gender=gender.gender,
			created_by=robot,
			)
		models.log_obj_create(robot, runner, models.ACTION_CREATE, comment='Создание нового бегуна по дате рождения', verified_by=admin)
		n_results_touched = 0
		for result in list(results):
			n_results_touched += 1
			result.runner = runner
			result.save()
			models.log_obj_create(robot, result.race.event, models.ACTION_RESULT_UPDATE, field_list=['runner'], child_object=result,
				comment='Создание нового бегуна по дате рождения', verified_by=admin)
		runner_stat.update_runner_stat(runner=runner)
		n_good_tuples += 1
		mail_body += (f'\n{n_good_tuples}. {results_util.SITE_URL}{runner.get_absolute_url()} — {runner.get_lname_fname()} '
			+ f'({runner.birthday}, {runner.get_gender_display()[0]}) , привязано результатов: {n_results_touched}')

		namesakes = models.Runner.objects.exclude(pk=runner.pk).filter(lname=runner.lname, fname=runner.fname)
		if namesakes.exists():
			mail_body += f'\nБегуны с теми же именем и фамилией ({namesakes.count()}): '+ runners_by_name_url

	if n_good_tuples:
		mail_body = '\n\nСоздаём новых бегунов по дате рождения:\n\n' + mail_body
		mail_summary += f'\n\nИтого создано новых бегунов: {n_good_tuples}.'
	mail_errors = ''
	if errors_midnames:
		mail_errors += '\n\nПротиворечивые отчества у бегунов:\n\n' + errors_midnames
	if errors_same_name:
		mail_errors += '\n\nУже есть бегуны с такими же именем и годом рождения:\n\n' + errors_same_name
	if errors_unknown_gender:
		mail_errors += '\n\nНе получилось определить пол бегуна по имени:\n\n' + errors_unknown_gender
	if debug:
		print(f'Done! Good tuples: {n_good_tuples}, bad tuples: {n_similar_runnes_errors}')
	return '', mail_errors, mail_body, mail_summary

# def attach_results_with_correct_year(): # Will we ever use it?..
# 	free_official_results = models.Result.objects.filter(runner=None, birthday_known=False, birthday__isnull=False,
# 		source=models.RESULT_SOURCE_DEFAULT).exclude(lname='').exclude(fname='')
# 	name_birthday_tuples = set([(a.lower(), b.lower(), c.year) for a, b, c in free_official_results.values_list('lname', 'fname', 'birthday')])
# 	n_good_tuples = 0
# 	n_results_attached = 0
# 	n_errors = 0
# 	f = open('/var/www/vhosts/probeg.org/httpdocs/names.txt', 'w')
# 	i = 0
# 	for lname, fname, year in name_birthday_tuples:
# 		i += 1
# 		if (i % 5000) == 0:
# 			print i, 'Good tuples:', n_good_tuples, ', results attached:', n_results_attached
# 		is_good_tuple = False
# 		runners = models.Runner.objects.filter(lname__iexact=lname, fname__iexact=fname, birthday__year=year)
# 		if runners.count() != 1:
# 			continue
# 		runner = runners[0]
# 		Q_year = Q(birthday=None) | ~Q(birthday__year=year)
# 		if runner.birthday_known:
# 			Q_year |= Q(birthday_known=True) & ~Q(birthday=runner.birthday)
# 		if models.Result.objects.filter(Q_year, lname__iexact=lname, fname__iexact=fname).exists():
# 			continue
# 		results = free_official_results.filter(lname__iexact=lname, fname__iexact=fname, birthday__year=year)
# 		midname = runner.midname.lower()
# 		for result in results:
# 			result_midname = result.midname.lower()
# 			if result_midname.startswith(midname) or midname.startswith(result_midname):
# 				is_good_tuple = True
# 				n_results_attached += 1
# 		if is_good_tuple:
# 			n_good_tuples += 1
# 	print 'Done! Good tuples:', n_good_tuples, ', results attached:', n_results_attached

def get_runners_for_result(result: models.Result, only_with_exact_birthday: bool=False):
	if not all([result.fname, result.lname]):
		return models.Runner.objects.none()
	extra_name_runner_ids = set(models.Extra_name.objects.filter(
			Q(lname=result.lname, fname=result.fname) | Q(lname=result.fname, fname=result.lname),
			midname__in=('', result.midname)
		).values_list('runner_id', flat=True))
	runners = models.Runner.objects.filter(
			Q(lname=result.lname, fname=result.fname, midname__in=('', result.midname))
			| Q(lname=result.fname, fname=result.lname, midname__in=('', result.midname))
			| Q(pk__in=extra_name_runner_ids)
		)
	if only_with_exact_birthday:
		runners = runners.filter(birthday_known=True)
		if result.birthday_known:
			runners = runners.filter(birthday=result.birthday)
		elif result.birthday:
			runners = runners.filter(birthday__year=result.birthday.year)
		elif result.age:
			birthyear = result.race.event.start_date.year - result.age
			runners = runners.filter(birthday__year__range=(birthyear - 1, birthyear + 1))
	else:
		if result.birthday_known:
			runners = runners.filter(
				Q(birthday=result.birthday)
				| Q(birthday_known=None, birthday__year=result.birthday.year)
				| Q(birthday=None))
		elif result.birthday:
			runners = runners.filter(Q(birthday__year=result.birthday.year) | Q(birthday=None))
		elif result.age:
			birthyear = result.race.event.start_date.year - result.age
			runners = runners.filter(Q(birthday__year__range=(birthyear - 1, birthyear + 1)) | Q(birthday=None))
	return runners.select_related('city__region__country', 'klb_person').order_by('-birthday_known', 'lname', 'fname', 'midname', 'birthday')

# Returns registrants that someone else registered and that are appropriate for provided result
def get_appropriate_registrants(registrants, result: models.Result, race_year: int, could_register_himself=False):
	res = registrants.filter(lname=result.lname, fname=result.fname)
	if not could_register_himself:
		res = res.filter(registers_himself=False)
	if result.midname:
		res = res.filter(Q(midname=result.midname) | Q(midname=''))
	if result.birthday_known:
		return res.filter(birthday=result.birthday)
	if result.birthday:
		return res.filter(birthday__year=result.birthday.year)
	if result.age:
		birthyear = race_year - result.age
		return res.filter(birthday__year__range=(birthyear - 1, birthyear + 1))
	return res

def get_new_klb_reports_data():
	new_klb_reports_count = models.Klb_report.objects.filter(was_reported=False).count()
	if new_klb_reports_count:
		return '\n\nСоздано новых слепков КЛБМатча: {}. Их полный список: {}{}'.format(
			new_klb_reports_count, results_util.SITE_URL, reverse('results:klb_reports'))
	else:
		return ''

def mark_old_payments_as_inactive():
	three_days_ago = timezone.now() - datetime.timedelta(days=3)
	n_payments_marked = models.Payment_moneta.objects.filter(is_active=True, is_paid=False, added_time__lte=three_days_ago).update(is_active=False)
	if n_payments_marked:
		n_participants_marked = models.Klb_participant.objects.filter(payment__is_active=False).update(payment=None, wants_to_pay_zero=False)
		return '\n\nНеоплаченных платежей помечено как неактивные: {}, затронуто участников КЛБМатча: {}'.format(n_payments_marked, n_participants_marked)
	return ''

def get_db_checks_report():
	logger = logging.getLogger('dbchecks')

	res = ''
	# Checking ForeignKeys and OneToOneFields #
	for model_name, data in list(dbchecks.check_all_relationships2(logger).items()):
		res += '\n\nЗаписи в таблице {} с некорректными ссылками на другие таблицы: {}, {}'.format(model_name, data[0][0], data[0][1])
		res += '\nЗапрос, который их выдаёт: {}'.format(data[1])

	# Checking equality
	check_list = [
		# https://probeg.org/klb/person/7383/ по ошибке оказался в двух командах в матче-2017
		(models.Klb_person, 'birthday', 'runner__birthday', {7383}),
		(models.Klb_person, 'gender', 'runner__gender', set()),
		(models.Klb_result, 'event_raw_id', 'race__event_id', set()),
		(models.Klb_result, 'race_id', 'result__race_id', set()),
		(models.Klb_result, 'klb_person_id', 'klb_participant__klb_person_id', set()),
		(models.Klb_result, 'klb_person__runner__id', 'result__runner_id', set(models.Klb_result.objects.filter(is_error=True).values_list('pk', flat=True))),
	]

	for model_name, data in list(dbchecks.check_equality_by_list(check_list, logger).items()):
		res += '\n\nРасхождения в значениях полей {} — всего {}. Первые:'.format(model_name, data[0])
		for i, item in enumerate(data[1][:5]):
			res += '\n{}. '.format(i + 1)
			for key, val in list(item.items()):
				res += '{}: {}\n'.format(key, val)
		res += '\nЗапрос, который их выдаёт: {}'.format(data[2])
		res += '\nКод на Python:'
		for line in data[3]:
			res += '\n' + line
	return res

def delete_past_reg_tries():
	today = datetime.date.today()
	old_reg_tries = models.Registrant.objects.filter(race__event__start_date__lt=today, is_reg_complete=False).select_related('race__event__registration')
	n_old_reg_tries = old_reg_tries.count()
	if n_old_reg_tries:
		race_ids = set(old_reg_tries.values_list('race_id', flat=True))
		for registrant in list(old_reg_tries):
			models.log_obj_delete(models.USER_ROBOT_CONNECTOR, registrant.race.event.registration, child_object=registrant, action_type=models.ACTION_REGISTRANT_DELETE,
				comment='Удаление незавершённой регистрации на уже прошедший забег', verified_by=models.USER_ROBOT_CONNECTOR)
			registrant.delete()
		for reg_race_details in models.Reg_race_details.objects.filter(race_id__in=race_ids):
			reg_race_details.update_n_registered()
	return n_old_reg_tries

def delete_who_did_not_pay():
	now = timezone.now()
	registrants_not_paid = models.Registrant.objects.filter(Q(is_paid=False) | Q(is_reg_complete=False),
		race__event__registration__delete_unpaid_registrations=True, time_to_delete__lt=now).select_related('race__event__registration')
	n_registrants_not_paid = registrants_not_paid.count()
	if n_registrants_not_paid:
		race_ids = set(registrants_not_paid.values_list('race_id', flat=True))
		for registrant in list(registrants_not_paid):
			models.log_obj_delete(models.USER_ROBOT_CONNECTOR, registrant.race.event.registration, child_object=registrant, action_type=models.ACTION_REGISTRANT_DELETE,
				comment='Удаление неоплаченной регистрации', verified_by=models.USER_ROBOT_CONNECTOR)
			registrant.delete()
		for reg_race_details in models.Reg_race_details.objects.filter(race_id__in=race_ids):
			reg_race_details.update_n_registered()
	return n_registrants_not_paid

def clean_regs():
	res = f'\n\nУдалено незаконченных попыток регистрации на забеги, которые уже прошли: {delete_past_reg_tries()}' \
		+ f'\nУдалено неоплаченных регистраций на забегах, где их нужно удалять: {delete_who_did_not_pay()}'
	event_ids = set(models.Event.get_events_with_open_reg().values_list('pk', flat=True))
	n_wrong_registrants_number = 0
	example = ''
	for reg_race_details in models.Reg_race_details.objects.filter(race__event_id__in=event_ids):
		if reg_race_details.n_registered != reg_race_details.race.registrant_set.filter(is_reg_complete=True).count():
			n_wrong_registrants_number += 1
			example = reg_race_details.race.get_absolute_url()
	if n_wrong_registrants_number:
		res += f'\nРегистраций с неверным числом зарегистрированных: {n_wrong_registrants_number}. Первая: {results_util.SITE_URL}{example}'
	return res

def find_future_events_wo_distances():
	today = datetime.date.today()
	future_event_ids = set(models.Event.objects.filter(start_date__gte=today).values_list('pk', flat=True))
	future_event_with_races_ids = set(models.Race.objects.filter(event__start_date__gte=today).values_list('event_id', flat=True))
	events_wo_distances = future_event_ids - future_event_with_races_ids
	if not events_wo_distances:
		return ''
	res = f'\n\nУ {len(events_wo_distances)} будущих забегов не указано ни одной дистанции:'
	for i, event in enumerate(models.Event.objects.filter(pk__in=events_wo_distances).order_by('start_date', 'name')):
		res += f'\n{i+1}. {results_util.SITE_URL}{event.get_absolute_url()} - {event.start_date}, {event.name}'
	return res

def make_connections(debug=False):
	mail_header = 'Доброе утро!\n\nНа связи Робот Присоединитель.'
	mail_errors = ''
	mail_body = ''
	mail_summary = ''

	mail_errors += find_future_events_wo_distances()

	h, e, b, s = attach_results_with_birthday(models.USER_ROBOT_CONNECTOR, models.USER_ROBOT_CONNECTOR, debug=debug)
	mail_header += h
	mail_errors += e
	mail_body += b
	mail_summary += s
	if debug:
		print('attach_results_with_birthday - done')

	h, e, b, s = create_new_runners_with_birthdays(models.USER_ROBOT_CONNECTOR, models.USER_ROBOT_CONNECTOR, debug=debug)
	mail_header += h
	mail_errors += e
	mail_body += b
	mail_summary += s
	if debug:
		print('create_new_runners_with_birthdays - done')

	mail_errors += monitoring.check_users_and_runners_links(models.USER_ROBOT_CONNECTOR)
	if debug:
		print('check_users_and_runners_links - done')

	mail_errors += update_race_size_stat(debug=debug)
	if debug:
		print('update_race_size_stat - done')

	mail_body += get_new_klb_reports_data()
	if debug:
		print('get_new_klb_reports_data - done')

	mail_body += mark_old_payments_as_inactive()
	if debug:
		print('mark_old_payments_as_inactive - done')

	mail_errors += get_db_checks_report()
	if debug:
		print('get_db_checks_report - done')

	mail_summary += clean_regs()

	today = datetime.date.today()
	if (today.month == 1) or (today.month > models_klb.get_last_month_to_pay_for_teams(models_klb.CUR_KLB_YEAR)):
		if today.day == 1:
			mail_body += klb_letters.send_letters_to_not_paid_individuals(limit=5, test_mode=True)
			mail_body += klb_letters.send_letters_for_not_paid_teams(limit=5, test_mode=True)
		elif today.day == 2:
			mail_body += klb_letters.send_letters_to_not_paid_individuals(test_mode=False)
			mail_body += klb_letters.send_letters_for_not_paid_teams(test_mode=False)
		elif today.day == 7:
			res = klb_letters.delete_unpaid_participants(test_mode=True)
			if res:
				mail_errors += f'\n\nОшибка из delete_unpaid_participants: {res}\n'
		elif today.day == 8:
			res = klb_letters.delete_unpaid_participants(test_mode=False)
			if res:
				mail_errors += f'\n\nОшибка из delete_unpaid_participants: {res}\n'

	mail_summary += '\n\nНа сегодня это всё. До связи!\nВаш робот'
	message_from_site = models.Message_from_site.objects.create(
		message_type=models.MESSAGE_TYPE_FROM_ROBOT,
		title='Новости от Робота Присоединителя',
		body=mail_header + '\n\n' + mail_errors + '\n\n' + mail_body + '\n\n' + mail_summary,
	)
	message_from_site.try_send()
	if message_from_site.is_sent:
		models.Klb_report.objects.filter(was_reported=False).update(was_reported=True)

def fill_unknown_genders():
	n_names = 0
	for result in models.Result.objects.filter(source=models.RESULT_SOURCE_DEFAULT, gender=models.GENDER_UNKNOWN):
		name = models.Runner_name.objects.filter(name__iexact=result.fname).first()
		if name:
			# print result.fname, name.gender
			result.gender = name.gender
			result.save()
			n_names += 1
	print("Names corrected:", n_names)

def get_runner_quantity_in_series(series_id):
	# series = models.Series.objects.get(pk=series_id)
	names = Counter()
	for result in models.Result.objects.filter(race__event__series_id=series_id):
		names[(result.lname, result.fname)] += 1
	for name, count in names.most_common(3):
		print(name[0], name[1], count)
		for result in models.Result.objects.filter(race__event__series_id=series_id, lname=name[0], fname=name[1]):
			print(result.comment)

def connect_winner_runners():
	race_ids = set(models.Result.objects.filter(source=models.RESULT_SOURCE_DEFAULT, place_gender=1, runner__isnull=False).values_list(
		'race_id', flat=True))
	print('Races found:', len(race_ids))
	n_done = 0
	for race in models.Race.objects.filter(pk__in=race_ids).order_by('pk'):
		race.fill_winners_info()
		n_done += 1
		if (n_done % 200) == 0:
			print(race.id)
	print('Finished!', n_done)

def check_document_old_fields(to_repair=False): # Are there events with good documents but empty old fields?
	n_repaired = 0
	for doc_type, old_field_name in list(models.DOCUMENT_FIELD_NAMES.items()):
		if doc_type == models.DOC_TYPE_PRELIMINARY_PROTOCOL:
			continue
		events_with_docs_ids = set(models.Document.objects.filter(~(Q(url_source='') & (Q(upload=None) | Q(hide_local_link=models.DOC_HIDE_ALWAYS))),
			document_type=doc_type).values_list('event_id', flat=True))
		kwargs = {}
		kwargs[old_field_name] = ''
		bad_events = models.Event.objects.filter(pk__in=events_with_docs_ids, **kwargs)
		print(doc_type, models.DOCUMENT_TYPES[doc_type][1], bad_events.count())
		if to_repair:
			for event in bad_events:
				doc = event.document_set.filter(document_type=doc_type).first()
				if doc:
					doc.update_event_field()
					n_repaired += 1
		if bad_events:
			print('First:', bad_events[0].id, bad_events[0].name)
	if n_repaired:
		print('Repaired: {} fields'.format(n_repaired))

def fill_n_male_participants():
	n_fixed = 0
	for race in models.Race.objects.filter(n_participants__gt=0, loaded=models.RESULTS_LOADED).order_by('id'):
		results = race.get_official_results()
		participants = results.exclude(status=models.STATUS_DNS)
		if race.n_participants != participants.count():
			# print 'Race {} {}: {} real participants, {} saved in n_participants'.format(race.id, race, participants.count(), race.n_participants)
			race.n_participants = participants.count()
		# race.n_participants_male = participants.filter(gender=results_util.GENDER_MALE).count()
			race.save()
			n_fixed += 1
			if (n_fixed % 100) == 0:
				print(n_fixed, race.id)
	print('Done!', n_fixed)

def print_race_results_anonimized_csv_for_melekhov():
	# race = models.Race.objects.get(pk=race_id)
	series_ids = [1358, 1559, 1560, 1357, 1359, 185]
	races = models.Race.objects.filter(event__series_id__in=series_ids, is_for_handicapped=False, loaded=models.RESULTS_LOADED,
		event__start_date__range=(datetime.date(2009, 1, 1), datetime.date.today()))
	with io.open('all-for-melekhov.csv', 'w', encoding="cp1251") as output_file:
		output_file.write(
			'ID старта;Название;Дата;Дистанция;Фактическая дистанция;№ результата;Пол;Дата/год рождения;Возраст;Время;Время в сотых секунды\n')
		for race in races:
			results = race.result_set.exclude(age=None, birthday=None).filter(status=models.STATUS_FINISHED).order_by('result')
			for i, result in enumerate(results):
				output_file.write(';'.join(str(x) for x in [race.id, race.event.name, race.event.start_date, race.distance_with_heights(),
					race.distance_real if race.distance_real else '',
					i + 1, result.get_gender_display(), result.strBirthday(with_nbsp=False, short_format=True), result.age if result.age else '',
					result, result.result]) + '\n')

def get_results_for_melekhov(): # For avmelekhov@gmail.com at 2018-08-16
	series_ids = [1358, 1559, 1560, 1357, 1359, 185]
	races = models.Race.objects.filter(event__series_id__in=series_ids, is_for_handicapped=False,
		event__start_date__range=(datetime.date(2009, 1, 1), datetime.date.today()))
	n_finishers = 0
	with io.open('all_events.csv', 'w', encoding="cp1251") as output_file:
		output_file.write(
			'Название;Дата;Дистанция;Фактическая дистанция, если отличается;Загружены ли результаты;'
			+ 'Всего финишировало;В том числе у кого известны пол и возраст\n')
		for race in races.order_by('event__series_id', 'event__start_date', '-distance__length'):
			results = race.result_set.filter(status=models.STATUS_FINISHED)
			output_file.write(';'.join(str(x) for x in [race.event.name, race.event.start_date, race.distance_with_heights(),
				race.distance_real if race.distance_real else '',
				race.get_loaded_display(), results.count(), results.exclude(age=None, birthday=None).count()]) + '\n')
			if race.n_participants_finished:
				n_finishers += results.count() #race.n_participants_finished

def find_bad_paces():
	n_res = 0
	thousand_max = models.User_stat.objects.exclude(runner=None).order_by('-pk').first().id // 10000
	print(thousand_max)
	for thousand in range(0, thousand_max + 1):
		for stat in models.User_stat.objects.exclude(runner=None).exclude(value_best=None).filter(
				pk__range=(10000*thousand, 10000*(thousand + 1) - 1),
				distance__distance_type__in=(models.TYPE_METERS, models.TYPE_MINUTES_RUN, models.TYPE_MINUTES_RACEWALKING)
				).order_by('pk').select_related('best_result__race', 'distance'):
			pace_best = stat.distance.get_pace(stat.value_best)
			if pace_best > 10000:
				print(stat.runner.id, stat.distance, stat.best_result.race_id)
				n_res += 1
				if n_res == 20:
					return

def find_too_slow_results():
	results = models.Result.objects.filter(race__distance__distance_type=models.TYPE_METERS)
	for length, centiseconds in ((42000, 10*3600*100), (20000, 5*3600*100), (10000, 3*3600*100), (3000, 2*3600*100), (1000, 1800*100)):
		results_count = results.filter(race__distance__length__lte=length, result__gte=centiseconds).count()
		if results_count:
			print(length, centiseconds, results_count)

def load_splits(): # For exact result
	result = models.Result.objects.get(pk=3495676)
	result.split_set.all().delete()
	n_splits = 0
	with io.open('/home/admin/chernov/2019-06-11-nyrr-5k.csv', 'r') as input_file:
		for line in input_file:
			fields = line.split(';')
			length = results_util.int_safe(fields[0])
			if length == 0:
				print('Wrong length:', line)
				return
			distance = models.Distance.objects.get(distance_type=models.TYPE_METERS, length=length)
			res = re.match(r'^(\d{1,2}):(\d{2})\.(\d{2})(\d)$', fields[1]) # minutes[:.,]seconds[.,]centiseconds_lastdigit
			if res:
				hours = 0
				minutes = int(res.group(1))
				seconds = int(res.group(2))
				hundredths = int(res.group(3))
				thousandths = int(res.group(4))
				if thousandths:
					if hundredths < 99:
						hundredths += 1
					elif seconds < 59:
						hundredths = 0
						seconds += 1
					elif minutes < 59:
						hundredths = 0
						seconds = 0
						minutes += 1
					else:
						hundredths = 0
						seconds = 0
						minutes = 0
						hours += 1
				value = models.tuple2centiseconds(hours, minutes, seconds, hundredths)
				models.Split.objects.create(result=result, distance=distance, value=value)
				n_splits += 1
	print('Splits created:', n_splits)

def print_most_active_users():
	user_ids = []
	emails = []
	for user in User.objects.filter(is_superuser=False).annotate(Count('table_update')).order_by('-table_update__count')[:50]:
		print(('{} {} {}'.format(user.email, user.get_full_name(), user.table_update__count)))
		user_ids.append(user.id)
		if not models.is_admin(user):
			emails.append(user.email)
	print(user_ids)
	print((', '.join(emails)))

def new_users_by_month(): # For Dmitry Lykov
	import pytz
	settings_time_zone = pytz.timezone(settings.TIME_ZONE)
	for month in range(1, 12):
		start = datetime.datetime.combine(datetime.date(2020, month, 1), datetime.time.min).astimezone(settings_time_zone)
		end = datetime.datetime.combine(datetime.date(2020, month + 1, 1), datetime.time.min).astimezone(settings_time_zone)
		print(month, User.objects.filter(date_joined__range=(start, end), is_active=True).count())
