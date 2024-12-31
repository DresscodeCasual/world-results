from django.conf import settings
from django.urls import reverse
from django.db.models import Q
import datetime
import time

from typing import Optional

from results import models, models_klb, results_util
from .views import views_klb_stat, views_mail

def print_teams_without_captains(year=models_klb.CUR_KLB_YEAR):
	club_in_match_ids = set(models.Klb_team.objects.filter(year=year).values_list('club_id', flat=True))
	clubs_with_captain_ids = set(models.Club_editor.objects.values_list('club_id', flat=True))
	for club_id in club_in_match_ids - clubs_with_captain_ids:
		club = models.Club.objects.get(pk=club_id)
		print(club.id, club.name)

# To be called on 1st day of the month
def send_letters_to_not_paid_individuals(year=models_klb.CUR_KLB_YEAR, limit=None, test_mode=True) -> str:
	today = datetime.date.today()
	if today.day > 7:
		return f'Пишем не оплатившим участие индивидуалам только в первые 7 дней месяца. Сейчас ничего не делаем.'
	payment_deadline = datetime.date(today.year, today.month, 7)
	date_of_deletion = payment_deadline + datetime.timedelta(days=1)
	participants = models.Klb_participant.objects.filter(year=year, team=None, paid_status=models.PAID_STATUS_NO).select_related(
			'klb_person__runner__user__user_profile').order_by('-score_sum')
	res = f'\n\nОтчёт об отправке писем не заплатившим индивидуальным участникам КЛБМатча-{models_klb.year_string(year)}'
	if test_mode:
		res += '\nЭто — тестовый режим. Шлём письма только админам.'
	res += f'\nНе оплатили участие {participants.count()} человек.'
	if limit:
		participants = participants[:limit]
		res += f'\nШлём письма только первым {limit} людям.'
	n_sent = 0
	n_errors = 0
	for i, participant in enumerate(participants):
		runner = participant.klb_person.runner
		user = runner.user
		if user is None:
			models.send_panic_email(
				'Individual KLB participant has no user',
				f'Problem occured with klb_participant {participant.id}: there is no associated user.'
			)
			continue
		if not hasattr(user, 'user_profile'):
			models.send_panic_email(
				'Individual KLB participant has no user_profile',
				f'Problem occured with klb_participant {participant.id}, user {user.id}: there is no associated user_profile.'
			)
			continue
		context = {}
		context['test_mode'] = test_mode
		context['participant'] = participant
		context['senior_age'] = results_util.SENIOR_AGE_MALE if (participant.klb_person.gender == results_util.GENDER_MALE) \
			else results_util.SENIOR_AGE_FEMALE
		context['regulations_link'] = models_klb.get_regulations_link(year)
		context['participation_price'] = models_klb.get_participation_price(year)
		context['date_registered'] = results_util.date2str(participant.date_registered, with_nbsp=False)
		context['payment_deadline'] = results_util.date2str(payment_deadline, with_nbsp=False)
		context['date_of_deletion'] = results_util.date2str(date_of_deletion, with_nbsp=False)
		res += f'\n{i+1}. {runner.get_name_and_id()} (пользователь {user.get_full_name()}, id {user.id}) {user.email}'
		result = views_mail.send_newsletter(user, models.USER_ADMIN, 'klb/individual_not_paid', f'КЛБМатч–{models_klb.year_string(year)} — оплата участия',
			target=settings.EMAIL_INFO_USER if test_mode else '',
			cc='' if test_mode else settings.EMAIL_INFO_USER,
			create_table_update=not test_mode,
			context=context)
		if result['success']:
			n_sent += 1
		else:
			res += f'\nНе получилось отправить письмо: {result["error"]}'
			n_errors += 1
	res += f'\nИтого отправили писем: {n_sent}, возникло ошибок: {n_errors}'
	return res

def send_letters_for_not_paid_teams(year=models_klb.CUR_KLB_YEAR, limit=None, test_mode=True) -> str:
	today = datetime.date.today()
	if today.day > 7:
		return f'Пишем не оплатившим участие командам только в первые 7 дней месяца. Сейчас ничего не делаем.'
	payment_deadline = datetime.date(today.year, today.month, 7)
	date_of_deletion = datetime.date(today.year, today.month, 8)

	non_paid_team_ids = set(models.Klb_participant.objects.filter(
		year=year, team__isnull=False, paid_status=models.PAID_STATUS_NO).values_list('team_id', flat=True))
	res = f'\n\nОтчёт об отправке писем не заплатившим командам КЛБМатча-{models_klb.year_string(year)}'
	if test_mode:
		res += '\nЭто — тестовый режим. Шлём письма только админам.'
	res += f'\nНе оплатили участие {len(non_paid_team_ids)} команд.'
	n_captains = 0
	n_teams_wo_captains = 0
	n_sent = 0
	n_errors = 0
	teams = models.Klb_team.objects.filter(pk__in=non_paid_team_ids).select_related('club').order_by('pk')
	if limit:
		teams = teams[:limit]
		res += f'\nШлём письма только первым {limit} командам.'
	for i, team in enumerate(teams):
		context = {}
		context['team'] = team
		context['test_mode'] = test_mode
		context['n_not_paid'] = team.klb_participant_set.filter(paid_status=models.PAID_STATUS_NO).count()
		context['senior_age_male'] = results_util.SENIOR_AGE_MALE
		context['senior_age_female'] = results_util.SENIOR_AGE_FEMALE
		context['regulations_link'] = models_klb.get_regulations_link(year)
		context['participation_price'] = models_klb.get_participation_price(year)
		context['payment_deadline'] = results_util.date2str(payment_deadline, with_nbsp=False)
		context['date_of_deletion'] = results_util.date2str(date_of_deletion, with_nbsp=False)
		context['last_month_to_not_pay'] = results_util.months[models_klb.get_last_month_to_pay_for_teams(year)]
		captains = team.club.editors.order_by('pk')
		if not captains.exists():
			res += f'У команды {team.name} (id {team.id}) нет ни одного капитана!'
			n_teams_wo_captains += 1
		for captain in captains:
			res += f'\n{i+1}. {team.name} (id {team.id}) {captain.get_full_name()} {captain.email}'
			result = views_mail.send_newsletter(captain, models.USER_ADMIN, 'klb/team_not_paid',
				f'КЛБМатч-{models_klb.year_string(year)} — оплата участия команды «{team.name}»',
				target=settings.EMAIL_INFO_USER if test_mode else '',
				cc='' if test_mode else settings.EMAIL_INFO_USER,
				create_table_update=not test_mode, context=context)
			if result['success']:
				n_sent += 1
			else:
				res += f'\nНе получилось отправить письмо: {result["error"]}'
				n_errors += 1
			time.sleep(1)
	res += f'\nИтого отправили писем: {n_sent}, возникло ошибок: {n_errors}, команд без капитанов: {n_teams_wo_captains}'
	return res

def send_letters_to_unpaid_team_participants(year=models_klb.CUR_KLB_YEAR, test_mode=True, limit=None):
	today = datetime.date.today()
	first_legal_reg_date = datetime.date(today.year, today.month, 1)
	clubs_exceptions = set() # set([20]) # Урал-100, отсрочка до февраля 2021
	clubs_with_captain_ids = set(models.Club_editor.objects.values_list('club_id', flat=True)) - clubs_exceptions
	participants = models.Klb_participant.objects.filter(
		Q(date_registered=None) | Q(date_registered__lt=first_legal_reg_date),
		is_senior=False, klb_person__disability_group=0,
		year=year, team__isnull=False, team__club_id__in=clubs_with_captain_ids,
		paid_status=models.PAID_STATUS_NO).exclude(email='').select_related(
		'klb_person__runner__user__user_profile', 'klb_person__runner__city__region__country', 'team').order_by('pk')
	print('Number of unpaid team participants with emails: {}'.format(participants.count()))
	n_sent = 0
	n_errors = 0
	if limit:
		participants = participants[:limit]
	for participant in participants:
		context = {}
		context['team'] = participant.team
		context['test_mode'] = test_mode
		context['page_title'] = 'КЛБМатч — оплата участия'
		context['participant'] = participant
		context['club_editors'] = participant.team.club.editors
		context['n_other_not_paid'] = participant.team.klb_participant_set.filter(paid_status=models.PAID_STATUS_NO).count() - 1
		context['registration_deadline'] = '15 января'
		result = views_mail.send_newsletter(None, models.USER_ADMIN, 'klb/team_member_not_paid', 'КЛБМатч — оплата участия',
			target=settings.EMAIL_INFO_USER if test_mode else participant.email,
			cc='' if test_mode else settings.EMAIL_INFO_USER,
			create_table_update=not test_mode,
			context=context, runner=participant.klb_person.runner)
		if result['success']:
			print('participant {} (id {}), {}, team {}'.format(participant.klb_person.runner.name(), participant.id, participant.email,
				participant.team.name))
			n_sent += 1
		else:
			print('ERROR participant {} (id {}), {}: {}'.format(participant.klb_person.runner.name(), participant.id, participant.email,
				result['error']))
			n_errors += 1
		time.sleep(6)
	print('Done! Messages sent: {}, errors: {}'.format(n_sent, n_errors))

def get_participants_for_team_or_year(team, year=None):
	if team:
		return team.klb_participant_set.all()
	# Otherwise, return individual participants for given year
	return models.Klb_participant.objects.filter(team=None, year=year)

def create_fake_payment_for_seniors(first_legal_reg_date, team, year):
	unpaid_seniors = get_participants_for_team_or_year(team, year).filter(
		Q(date_registered=None) | Q(date_registered__lt=first_legal_reg_date),
		Q(is_senior=True) | Q(klb_person__disability_group__gt=0),
		paid_status=models.PAID_STATUS_NO).select_related('klb_person__runner').order_by(
		'klb_person__runner__lname', 'klb_person__runner__fname')
	n_unpaid_seniors = unpaid_seniors.count()
	if n_unpaid_seniors:
		payment = models.Payment_moneta.objects.create(
			amount=0,
			is_dummy=True,
			is_paid=True,
			user=models.USER_ROBOT_CONNECTOR,
			description='Автоматический платёж при удалении неоплаченных участников команды {}'.format(
				team.name if team else '«Индивидуальные участники»'),
		)
		payment.transaction_id = models.PAYMENT_DUMMY_PREFIX + str(payment.id)
		payment.save()
		message = 'Неоплаченные пенсионеры и инвалиды помечены как участвующие бесплатно:\n'
		for i, participant in enumerate(unpaid_seniors):
			participant.payment = payment
			participant.paid_status = models.PAID_STATUS_FREE
			participant.save()
			models.log_obj_create(models.USER_ROBOT_CONNECTOR, participant.klb_person, models.ACTION_KLB_PARTICIPANT_UPDATE,
				child_object=participant, field_list=['paid_status', 'payment'],
				comment='Платёж {}'.format(payment.id), verified_by=models.USER_ROBOT_CONNECTOR)
			message += '{}. {} {}{}\n'.format(i + 1, participant.klb_person.runner.name(), results_util.SITE_URL,
				participant.klb_person.get_absolute_url())
		message += '\nСоздан фиктивный платёж для бесплатного участия неоплаченных пенсионеров и инвалидов: {}{}\n\n'.format(
			results_util.SITE_URL, payment.get_absolute_url())
	else:
		message = 'Неоплаченных пенсионеров и инвалидов в команде не было.\n\n'
	return message

def delete_unpaid_participants_for_team(first_legal_reg_date: datetime.date, team: Optional[models.Klb_team], delete_seniors: bool, test_mode: bool, year: Optional[int]=None):
	participants_to_delete = get_participants_for_team_or_year(team, year).filter(
		Q(date_registered=None) | Q(date_registered__lt=first_legal_reg_date),
		paid_status=models.PAID_STATUS_NO).select_related('klb_person__runner').order_by(
		'klb_person__runner__lname', 'klb_person__runner__fname')
	if not delete_seniors:
		participants_to_delete = participants_to_delete.filter(is_senior=False, klb_person__disability_group=0)
	if team:
		message = ('Сейчас мы попробуем удалить всех участников команды «{}» {} года {}{} , заявленных до {} включительно,'
					+ ' и их результаты.\n\n').format(
			team.name, models_klb.year_string(team.year), results_util.SITE_URL, team.get_absolute_url(), first_legal_reg_date - datetime.timedelta(days=1))
		cc = ','.join(team.club.editors.values_list('email', flat=True))
	else:
		message = ('Сейчас мы попробуем удалить всех индивидуальных участников {} года {}{} , заявленных до {} включительно,'
					+ ' и их результаты.\n\n').format(
			models_klb.year_string(year), results_util.SITE_URL, reverse('results:klb_match_summary', kwargs={'year': year}), first_legal_reg_date)
		cc = ''
	if test_mode:
		message += 'Это — тестовый запуск, на самом деле ничего не удаляем!\n\n'
		if cc:
			message += f'При боевом запуске копия этого письма уйдёт также капитанам команды: {cc}.\n\n'
	message += 'Участники:\n'
	for i, participant in enumerate(participants_to_delete):
		person = participant.klb_person
		message += '{}. {} {} {}{} , заявлен {}\n'.format(i + 1, person.fname, person.lname, results_util.SITE_URL, person.get_absolute_url(),
			participant.date_registered)

	participants_with_results = participants_to_delete.filter(n_starts__gt=0)
	n_participants_with_results = participants_with_results.count()
	results_to_delete = []
	if n_participants_with_results > 0:
		message += '\nИх результаты:\n\n'
		message += '№;id участника;имя;фамилия;id старта;дата старта;название;дистанция;id результата;результат;'
		message += 'спортивные очки;бонусы;дата добавления\n'
		for participant in participants_with_results:
			runner = participant.klb_person.runner
			for klb_result in participant.klb_result_set.all().select_related('race__event', 'race__distance', 'result').order_by(
					'race__event__start_date'):
				race = klb_result.race
				results_to_delete.append(klb_result)
				message += ';'.join(str(x) for x in
						[len(results_to_delete), participant.klb_person_id, runner.fname, runner.lname, race.id, race.event.date(with_nobr=False),
						race.event.name, race.distance, klb_result.result_id, klb_result.result, klb_result.klb_score,
						klb_result.bonus_score, klb_result.last_update]
					)
				message += '\n'
	message += '\nВсего участников: {}, результатов: {}.\n\n'.format(participants_to_delete.count(), len(results_to_delete))
	if not test_mode:
		to_delete_participants = True
		if results_to_delete:
			message += 'Пытаемся удалить результаты... '
			n_deleted = 0
			try:
				for klb_result in results_to_delete:
					models.log_obj_delete(models.USER_ROBOT_CONNECTOR, klb_result.race.event, child_object=klb_result,
						action_type=models.ACTION_KLB_RESULT_DELETE, comment='При удалении неоплаченных участников', verified_by=models.USER_ROBOT_CONNECTOR)
					klb_result.delete()
					n_deleted += 1
				message += 'Получилось. Удалено: {}.\n'.format(n_deleted)
			except Exception as e:
				to_delete_participants = False
				message += 'Не получилось; удалилось только {}. Участников не удаляем. Ошибка: {}\n\n'.format(n_deleted, repr(e))
		if to_delete_participants:
			message += 'Пытаемся удалить неоплаченных участников... '
			try:
				for participant in participants_to_delete:
					models.log_klb_participant_delete(models.USER_ROBOT_CONNECTOR, participant, comment='При удалении неоплаченных участников', verified_by=models.USER_ROBOT_CONNECTOR)
				participants_to_delete.delete()
				message += 'Получилось.\n'
				if team:
					views_klb_stat.update_team_score(team, to_calc_sum=True)
					message += 'Очки команды пересчитаны.\n\n'
				if not delete_seniors:
					message += create_fake_payment_for_seniors(first_legal_reg_date, team, year)
			except Exception as e:
				message += 'Возникла ошибка: {}\n\n'.format(repr(e))

	message += 'Ваш робот'
	if team:
		message_title = f'КЛБМатч-{models_klb.year_string(team.year)}: удаление неоплаченных участников из команды {team.name}'
	else:
		message_title = f'КЛБМатч-{models_klb.year_string(year)}: удаление неоплаченных индивидуальных участников'
	if test_mode:
		message_title += ' (тест)'
	message_from_site = models.Message_from_site.objects.create(
		message_type=models.MESSAGE_TYPE_FROM_ROBOT,
		title=message_title,
		body=message,
		cc='' if test_mode else cc,
	)
	message_from_site.try_send(attach_file=False)

def delete_unpaid_participants(year=models_klb.CUR_KLB_YEAR, delete_seniors=True, test_mode=True) -> str:
	if year < models_klb.CUR_KLB_YEAR:
		return f'Год {year} слишком ранний, чтобы удалять участников за неуплату. Ничего не делаем.'
	today = datetime.date.today()
	first_legal_reg_date = datetime.date(today.year, today.month, 1)

	team_participants_not_paid = models.Klb_participant.objects.filter(
		Q(date_registered=None) | Q(date_registered__lt=first_legal_reg_date),
		year=year, paid_status=models.PAID_STATUS_NO)

	exceptions = set()
	team_ids = set(team_participants_not_paid.values_list('team_id', flat=True)) - exceptions
	# team_ids = set([1077])
	n_teams_done = 0
	# for team_id in sorted(team_ids)[:5]:
	for team_id in team_ids:
		if team_id:
			delete_unpaid_participants_for_team(first_legal_reg_date, models.Klb_team.objects.get(pk=team_id), delete_seniors=delete_seniors, test_mode=test_mode)
		else: # Individual participants
			delete_unpaid_participants_for_team(first_legal_reg_date, None, delete_seniors=delete_seniors, test_mode=test_mode, year=year)
		n_teams_done += 1
	return ''
