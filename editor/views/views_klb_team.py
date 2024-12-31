from django.shortcuts import get_object_or_404, render, redirect
from django.contrib.auth.decorators import login_required
from django.urls import reverse
from django.conf import settings
from django.contrib.auth.models import User
from django.contrib import messages
from django.db.models import Q

import datetime
from typing import Any

from results import models, models_klb, results_util
from editor import forms, runner_stat
from .views_common import group_required, check_rights, changes_history
from .views_klb_stat import update_team_score, fill_match_places

@login_required
def did_not_run(request, team_id, with_marked=False):
	team = get_object_or_404(models.Klb_team, pk=team_id)
	context, has_rights, target = check_rights(request, club=team.club)
	if not has_rights:
		return target

	user_ids = set(team.klb_participant_set.exclude(klb_person__runner__user=None).values_list('klb_person__runner__user_id', flat=True))
	today = datetime.date.today()

	if 'mark_submit' in request.POST:
		n_errors = 0
		n_marked = 0
		for key, value in list(request.POST.items()):
			if key.startswith('calendar'):
				item_id = results_util.int_safe(key[len('calendar'):])
				item = models.Calendar.objects.filter(pk=item_id, marked_as_checked=False, user_id__in=user_ids,
					event__start_date__year=team.year, event__start_date__lt=today).first()
				if not item:
					n_errors += 1
					continue
				item.marked_as_checked = True
				item.save()
				n_marked += 1
		if n_marked:
			messages.success(request, 'Помечено записей как учтённых: {}'.format(n_marked))
		if n_errors:
			messages.warning(request, 'Не получилось пометить записей: {}. Если это будет повторяться, пожалуйста, напишите нам!'.format(n_errors))
		return redirect(reverse('editor:klb_team_did_not_run', kwargs={'team_id': team.id}))

	calendar_items = set()
	for user in User.objects.filter(pk__in=user_ids).order_by('last_name', 'first_name'):
		user_participated_event_ids = set(user.result_set.filter(race__event__start_date__year=team.year).values_list('race__event_id', flat=True))
		calendar_set = user.calendar_set.filter(event__start_date__year=team.year, event__start_date__lt=today).select_related(
			'race__distance', 'event__city__region__country', 'event__series__city__region__country', 'user__user_profile')
		if not with_marked:
			calendar_set = calendar_set.filter(marked_as_checked=False)
		for item in calendar_set:
			if item.event.id not in user_participated_event_ids:
				calendar_items.add(item)
	context['page_title'] = 'Команда «{}» в КЛБМатче–{}: Участники команды без результатов с планировавшихся забегов'.format(team.name, team.year)
	context['team'] = team
	context['calendar_items'] = sorted(calendar_items, key=lambda x:(x.event.start_date, x.user.last_name, x.user.first_name))
	context['with_marked'] = with_marked
	return render(request, 'klb/did_not_run.html', context)

@login_required
def klb_team_contact_info(request, team_id, ordering=models.ORDERING_NAME):
	ordering = results_util.int_safe(ordering)
	team = get_object_or_404(models.Klb_team, pk=team_id)
	context, has_rights, target = check_rights(request, club=team.club)
	if not has_rights:
		return target
	context['page_title'] = 'КЛБМатч–{}, команда {}: контактные данные участников'.format(team.year, team.name)
	context = team.update_context_for_team_page(context, request.user, ordering=ordering)
	context['all_emails'] = ', '.join(participant.email for participant in context['participants'] if participant.email)
	context['is_active_klb_year'] = models.is_active_klb_year(team.year)
	return render(request, 'klb/team_contact_info.html', context)

def get_runner_dict(request, year, runner, prev_year_participant, club_member, incorrect_emails, incorrect_phones):
	data = {}
	data['runner'] = runner

	if prev_year_participant:
		data['prev_year_participant'] = prev_year_participant
	elif runner.klb_person: # In case that he participated for some different club
		data['prev_year_participant'] = runner.klb_person.klb_participant_set.filter(year=year - 1).exclude(team=None).first()

	profile = None
	if hasattr(runner, 'user') and hasattr(runner.user, 'user_profile') and runner.user.user_profile.is_public:
		profile = runner.user.user_profile
		data['profile'] = profile

	cur_year_participant = None
	if runner.klb_person:
		cur_year_participant = runner.klb_person.klb_participant_set.filter(year=year).first()
	if cur_year_participant:
		data['is_cur_year_participant'] = True
		data['cur_year_team'] = cur_year_participant.team
	else:
		data['is_cur_year_participant'] = False

		data['email'] = ''
		data['phone_number'] = ''
		if prev_year_participant:
			data['email'] = prev_year_participant.email
			data['phone_number'] = prev_year_participant.phone_number
		elif club_member:
			data['email'] = club_member.email
			data['phone_number'] = club_member.phone_number

		if profile:
			if not data['email']:
				data['email'] = profile.user.email
			if not data['phone_number']:
				data['phone_number'] = profile.phone_number
		email_from_POST = request.POST.get('email_{}'.format(runner.id), '')
		if email_from_POST:
			data['email'] = email_from_POST

		phone_number_from_POST = request.POST.get('phone_number_{}'.format(runner.id), '')
		if phone_number_from_POST:
			data['phone_number'] = phone_number_from_POST

		if runner.id in incorrect_emails:
			data['email_incorrect'] = True
		if runner.id in incorrect_phones:
			data['phone_number_incorrect'] = True
	return data

@login_required
def klb_team_add_old_participants(request, team_id):
	team = get_object_or_404(models.Klb_team, pk=team_id)
	club = team.club
	context_vars, has_rights, target = check_rights(request, club=club)
	context: dict[str, Any] = context_vars
	if not has_rights:
		return target
	if not models.is_active_klb_year(team.year, context['is_admin']):
		messages.warning(request, 'Вы уже не можете добавлять людей в команду за {} год. Тот матч давно в прошлом.'.format(team.year))
		return redirect(team)
	prev_year = models_klb.first_match_year(team.year - 1)

	context['max_email_length'] = models.MAX_EMAIL_LENGTH
	context['max_phone_number_length'] = models.MAX_PHONE_NUMBER_LENGTH

	prev_year_participants = models.Klb_participant.objects.filter(team__club=club, year=prev_year).select_related(
		'klb_person__runner__user__user_profile', 'team').order_by('team__name', 'klb_person__lname', 'klb_person__fname')
	prev_year_participants_runner_ids = set(prev_year_participants.values_list('klb_person__runner__id', flat=True))

	club_members = club.club_member_set.filter(Q(date_removed=None) | Q(date_removed__year__gte=prev_year), runner__birthday__isnull=False,
		runner__birthday_known=True).exclude(runner__gender=models.GENDER_UNKNOWN).exclude(runner__lname='').exclude(runner__fname='').exclude(
		runner_id__in=prev_year_participants_runner_ids).exclude(runner__city=None).select_related('runner__user__user_profile')

	runner_ids = prev_year_participants_runner_ids | set(club_members.values_list('runner_id', flat=True))

	if not runner_ids:
		messages.warning(request,
			f'Ваш клуб не участвовал в КЛБМатче–{models_klb.year_string(prev_year)}, и в клубе за последний год никто не состоял. Некого добавлять')
		return redirect(team)

	incorrect_emails = set()
	incorrect_phones = set()
	if 'frmAddOldParticipants_submit' in request.POST:
		n_persons_added = 0
		n_persons_wrong_data = 0
		cur_year_person_ids = set(models.Klb_participant.objects.filter(year=team.year).values_list('klb_person_id', flat=True))
		move_limit = models_klb.get_team_limit(team.year) - team.klb_participant_set.count()
		today = datetime.date.today()
		for key, val in list(request.POST.items()):
			if key.startswith("add_"):
				if n_persons_added >= move_limit:
					messages.warning(request, 'Вы достигли максимального числа людей в команде. Больше не добавляем.')
					break
				runner_id = results_util.int_safe(key[len("add_"):])
				runner = models.Runner.objects.filter(pk=runner_id).first()
				if runner is None:
					messages.warning(request, f'Участник забегов с id {runner_id} не найден. Пропускаем')
					continue
				if runner_id not in runner_ids:
					messages.warning(request, f'У Вас нет прав добавить участника забегов {runner.name()} (id {runner.id}). Пропускаем')
					continue
				person = runner.klb_person
				if person and (person.id in cur_year_person_ids):
					person_team = person.klb_participant_set.filter(year=team.year).first().team
					if person_team:
						messages.warning(request, '{} {} (id {}) уже заявлен в КЛБМатч–{} в команду {}. Пропускаем'.format(
							person.fname, person.lname, person.id, models_klb.year_string(team.year), person_team.name))
					else:
						messages.warning(request, '{} {} (id {}) уже заявлен в КЛБМатч–{} как индивидуальный участник. Пропускаем'.format(
							person.fname, person.lname, person.id, models_klb.year_string(team.year)))
					continue
				ok_to_add = True
				email = ''
				phone_number = ''
				email = request.POST.get('email_{}'.format(runner.id), '').strip()
				if email and not models.is_email_correct(email):
					incorrect_emails.add(runner.id)
					n_persons_wrong_data += 1
					ok_to_add = False
				phone_number = request.POST.get('phone_number_{}'.format(runner.id), '').strip()
				if phone_number and not models.is_phone_number_correct(phone_number):
					incorrect_phones.add(runner.id)
					n_persons_wrong_data += 1
					ok_to_add = False
				if (email == '') and (phone_number == ''):
					messages.warning(request, '{} {} (id {}) — не указаны ни электронный адрес, ни телефон. Пропускаем'.format(
						runner.fname, runner.lname, runner.id, team.year))
					ok_to_add = False
				if ok_to_add:
					if not person:
						person = runner.create_klb_person(request.user, comment='При добавлении члена клуба в КЛБМатч')
					participant, club_member, is_changed = person.create_participant(team, request.user, email=email, phone_number=phone_number,
						comment='При добавлении участников предыдущего матча и членов клуба', add_to_club=request.POST.get('and_to_club_members'))
					if is_changed:
						runner_stat.update_runner_stat(club_member=club_member)

					n_persons_added += 1
		if n_persons_added:
			messages.success(request, f'Добавлено участников в команду с сегодняшнего дня: {n_persons_added}')
			update_team_score(team, to_clean=False, to_calc_sum=True)
		if n_persons_wrong_data:
			messages.warning(request, f'Не добавлено из-за ошибок в почтах и телефонах: {n_persons_wrong_data}. Подробности указаны ниже в табличке')
		# return redirect(team)

	context['runners_to_add'] = []
	for participant in prev_year_participants:
		context['runners_to_add'].append(get_runner_dict(
			request, team.year, participant.klb_person.runner, participant, None, incorrect_emails, incorrect_phones))
	for club_member in club_members:
		context['runners_to_add'].append(get_runner_dict(
			request, team.year, club_member.runner, None, club_member, incorrect_emails, incorrect_phones))
	context['runners_to_add'].sort(key=lambda x:(x['runner'].lname, x['runner'].fname))

	context['page_title'] = f'КЛБМатч–{team.year}: команда «{team.name}»'
	context['year'] = team.year
	context = team.update_context_for_team_page(context, request.user, ordering=models.ORDERING_NAME)
	return render(request, 'klb/team_add_old_participants.html', context)

@login_required
def klb_team_move_participants(request, team_id):
	team = get_object_or_404(models.Klb_team, pk=team_id)
	club = team.club
	context, has_rights, target = check_rights(request, club=club)
	if not has_rights:
		return target
	if not models.is_active_klb_year(team.year, context['is_admin']):
		messages.warning(request, f'Вы уже не можете добавлять людей в команду за {team.year} год. Тот матч давно в прошлом.')
		return redirect(team)
	last_day_to_move = models_klb.get_last_day_to_move_between_teams(team.year)
	if not context['is_admin']:
		if datetime.date.today() > last_day_to_move:
			messages.warning(request, f'Перемещать людей между командами можно только до {results_util.date2str(last_day_to_move, with_nbsp=False)}.')
			return redirect(team)
	other_teams = club.klb_team_set.filter(year=team.year).exclude(pk=team.id)
	if not other_teams.exists():
		messages.warning(request, f'В Матч–{team.year} вы заявили всего одну команду. Перемещать людей неоткуда.')
		return redirect(team)

	if 'frmMoveParticipants_submit' in request.POST:
		participant_ids = set(models.Klb_participant.objects.filter(team__in=list(other_teams)).values_list('id', flat=True))
		persons_moved = 0
		move_limit = models_klb.get_team_limit(team.year) - team.klb_participant_set.count()
		touched_teams = set()
		today = datetime.date.today()
		for key, val in list(request.POST.items()):
			if key.startswith("move_"):
				if persons_moved >= move_limit:
					messages.warning(request, 'Вы достигли максимального числа людей в команде. Больше не перемещаем.')
					break
				participant_id = results_util.int_safe(key[len("move_"):])
				participant = models.Klb_participant.objects.filter(pk=participant_id).first()
				if participant is None:
					messages.warning(request, f'Участник КЛБМатчей с id {participant_id} не найден. Пропускаем')
					continue
				if participant.id in participant_ids:
					touched_teams.add(participant.team)
					touched_teams.add(team)
					participant.team = team
					participant.clean()
					participant.save()
					models.log_obj_create(request.user, team, models.ACTION_PERSON_MOVE, child_object=participant,
						field_list=['team'],
						comment='При перемещении участников между командами')
					persons_moved += 1
		messages.success(request, 'Перемещено участников в команду {}: {}'.format(team.name, persons_moved))
		for touched_team in touched_teams:
			update_team_score(touched_team, to_clean=True, to_calc_sum=True)
		return redirect(team)

	context['other_teams_participants'] = models.Klb_participant.objects.filter(team__in=list(other_teams)).select_related(
		'team', 'klb_person').order_by('team__name', 'klb_person__lname', 'klb_person__fname')
	context['team_limit'] = models_klb.get_team_limit(team.year)
	context['medium_team_limit'] = models_klb.get_medium_team_limit(team.year)
	context['small_team_limit'] = models_klb.get_small_team_limit(team.year)
	context['page_title'] = 'Команда в КЛБМатче: {}, {} год'.format(team.name, team.year)
	context['last_day_to_move'] = results_util.date2str(last_day_to_move)
	context = team.update_context_for_team_page(context, request.user, ordering=models.ORDERING_NAME)
	return render(request, 'klb/team_move_participants.html', context)

@login_required
def klb_team_delete_participants(request, team_id):
	team = get_object_or_404(models.Klb_team, pk=team_id)
	club = team.club
	context, has_rights, target = check_rights(request, club=club)
	if not has_rights:
		return target
	if not models.is_active_klb_year(team.year, context['is_admin']):
		messages.warning(request, 'Вы уже не можете добавлять людей в команду за {} год. Тот матч давно в прошлом.'.format(team.year))
		return redirect(team)
	if 'delete_submit' in request.POST:
		participants_deleted = 0
		for key, val in list(request.POST.items()):
			if key.startswith("to_delete_"):
				person_id = results_util.int_safe(key[len("to_delete_"):])
				person = models.Klb_person.objects.filter(pk=person_id).first()
				if person is None:
					messages.warning(request, 'Участник КЛБМатчей с id {} не найден. Пропускаем'.format(person_id))
					continue
				participant = person.klb_participant_set.filter(year=team.year).first()
				if participant is None:
					messages.warning(request, 'Участник КЛБМатчей {} (id {}) и так не числится в команде. Пропускаем'.format(
						person, person.id))
					continue
				if person.klb_result_set.filter(race__event__start_date__year=team.year).exists():
					messages.warning(request, 'Участник КЛБМатчей {} (id {}) уже имеет результаты в зачёт КЛБМатча. Пропускаем'.format(
						person, person.id))
					continue
				models.log_klb_participant_delete(request.user, participant, verified_by=request.user)
				participant.delete()
				participants_deleted += 1
		messages.success(request, 'Удалено участников из команды: {}'.format(participants_deleted))
		update_team_score(team, to_clean=False, to_calc_sum=True)
	return redirect(team)

@group_required('editors')
def klb_team_change_name(request, team_id):
	team = get_object_or_404(models.Klb_team, pk=team_id)
	club = team.club
	context, has_rights, target = check_rights(request, club=club)
	if not has_rights:
		return target
	if not models.is_active_klb_year(team.year, True):
		messages.warning(request, f'Вы уже не можете менять название команды за {team.year} год. Тот матч закончился.')
		return redirect(team)
	if 'changeName_submit' in request.POST:
		name_new = request.POST.get('teamName', '').strip()
		if name_new == team.name:
			messages.warning(request, 'Вы не изменили название команды. Всё осталось по-прежнему.')
			return redirect(team)
		if name_new == '':
			messages.warning(request, 'Название команды не может быть пустым. Всё осталось по-прежнему.')
			return redirect(team)
		if not (name_new[0].isalpha() or name_new[0].isdigit()):
			messages.warning(request, 'Название команды должно начинаться с буквы или цифры. Всё осталось по-прежнему.')
			return redirect(team)
		if models.Klb_team.objects.filter(year=team.year, club__city=team.club.city, name__iexact=name_new).exclude(pk=team.id).exists():
			str_city = f'из города {team.club.city.name} ' if team.club.city else ''
			messages.warning(request, f'Команда с названием «{name_new}» {str_city}уже заявлена в КЛБМатч–{models_klb.year_string(team.year)}. Название не изменено.')
			return redirect(team)
		team.name = name_new
		team.save()
		models.log_obj_create(request.user, team, models.ACTION_UPDATE, field_list=['name'])
		messages.success(request, 'Название команды успешно изменено')
	return redirect(team)

@login_required
def klb_team_add_new_participant(request, team_id):
	team = get_object_or_404(models.Klb_team, pk=team_id)
	club = team.club
	context, has_rights, target = check_rights(request, club=club)
	if not has_rights:
		return target
	user = request.user
	if not models.is_active_klb_year(team.year, context['is_admin']):
		messages.warning(request, 'Вы уже не можете добавлять людей в команду за {} год. Тот матч давно в прошлом.'.format(team.year))
		return redirect(team)
	form = None
	to_create_runner = to_create_person = to_create_participant = False

	if 'step1_submit' in request.POST:
		form = forms.RunnerForKlbForm(user=user, year=team.year, data=request.POST)
		if form.is_valid():
			new_runner = form.instance
			runners = models.Runner.objects.filter(
				Q(birthday=None) | Q(birthday__year=new_runner.birthday.year, birthday_known=False)
				| Q(birthday=new_runner.birthday, birthday_known=True),
				lname=new_runner.lname,
				fname=new_runner.fname,
			).select_related('city__region__country', 'klb_person').order_by('-n_starts')
			if new_runner.midname:
				runners = runners.filter(midname__in=['', new_runner.midname])
			if runners.exists(): # We want to ask whether we should create new runner or use some of old ones
				context['runners'] = []
				for runner in runners:
					runner_dict = {}
					runner_dict['runner'] = runner
					info = []
					if runner.birthday_known:
						info.append('дата рождения {}'.format(runner.birthday.strftime("%d.%m.%Y")))
					elif runner.birthday:
						info.append(f'{runner.birthday.year} год рождения')
					if runner.city:
						info.append(runner.city.nameWithCountry())
					n_starts = runner.n_starts if runner.n_starts else 0
					info.append(f'{n_starts} результат{results_util.ending(runner.n_starts, 1)} в базе данных')
					if runner.klb_person:
						person = runner.klb_person
						n_klb_starts = person.klb_result_set.count()
						if n_klb_starts:
							info.append(f'{n_klb_starts} результат{results_util.ending(n_klb_starts, 1)} в зачёт КЛБМатчей')
						context['cur_year_participant'] = person.klb_participant_set.filter(year=team.year).first()
						runner_dict['cur_participant'] = person.klb_participant_set.filter(year=team.year).first()
					runner_dict['info'] = ', '.join(info)
					context['runners'].append(runner_dict)
			else: # There are no similar runners, so we can create him
				to_create_runner = True
		else:
			messages.warning(request, 'Пожалуйста, исправьте ошибки в форме')
	elif 'step2_submit' in request.POST:
		form = forms.RunnerForKlbForm(user=user, year=team.year, data=request.POST)
		if form.is_valid():
			new_runner = form.instance
			runner_id = results_util.int_safe(request.POST.get('runner_id', 0))
			if runner_id == -1: # This special value means we should create new runner
				to_create_runner = True
			else: # We should add some existing runner
				cur_year_person_ids = set(models.Klb_participant.objects.filter(year=team.year).values_list('klb_person_id', flat=True))
				runner = models.Runner.objects.filter(pk=runner_id).first()
				if runner:
					person = runner.klb_person
					if person:
						if person.id in cur_year_person_ids:
							person_team = person.klb_participant_set.filter(year=team.year).first().team
							if person_team:
								messages.warning(request, '{} {} (id {}) уже заявлен{} в КЛБМатч-{} в команду {}'.format(
									person.fname,
									person.lname,
									person.id,
									'а' if runner.gender == results_util.GENDER_FEMALE else '',
									models_klb.year_string(team.year),
									person_team.name))
							else:
								messages.warning(request, '{} {} (id {}) уже заявлен{} в КЛБМатч-{} как индивидуальный участник'.format(
									person.fname,
									person.lname,
									person.id,
									'а' if runner.gender == results_util.GENDER_FEMALE else '',
									models_klb.year_string(team.year)))
							return redirect(team)
						else:
							to_create_participant = True
					else: # So we should create new person for this runner. And maybe we can update runner?
						runner.update_if_needed(user, new_runner, comment='При добавлении отдельного участника в КЛБМатч')
						to_create_person = True
				else:
					messages.warning(request, 'К сожалению, выбранный Вами бегун (id {}) не найден. Попробуйте ещё раз'.format(runner_id))
		else:
			messages.warning(request, 'Пожалуйста, исправьте ошибки в форме')

	if to_create_runner:
		runner = form.save(commit=False)
		runner.birthday_known = True
		runner.created_by = user
		runner.save()
		models.log_obj_create(user, runner, models.ACTION_CREATE, comment='При добавлении нового участника в КЛБМатч', verified_by=user)
		to_create_person = True
	if to_create_person:
		person = runner.create_klb_person(user, comment='При добавлении нового участника в КЛБМатч')
		to_create_participant = True
	if to_create_participant:
		email = form.cleaned_data.get('email', '')
		phone_number = form.cleaned_data.get('phone_number', '')

		participant, club_member, is_changed = person.create_participant(team, user, email=email, phone_number=phone_number,
			comment='При добавлении нового участника в КЛБМатч-{}'.format(team.year), add_to_club=form.cleaned_data.get('and_to_club_members'))
		if is_changed:
			runner_stat.update_runner_stat(club_member=club_member)

		messages.success(request, '{} {} успешно добавлен{} в команду с {}'.format(
			runner.fname, runner.lname, 'а' if person.gender == results_util.GENDER_FEMALE else '', participant.date_registered.strftime("%d.%m.%Y")))
		update_team_score(team, to_clean=False, to_calc_sum=True)
		return redirect(team)

	if form is None:
		initial = {}
		if club.city:
			initial['city_id'] = club.city.id
			initial['region'] = club.city.region.id
		form = forms.RunnerForKlbForm(user=user, year=team.year, initial=initial)
	context['form'] = form
	context['page_title'] = 'Команда в КЛБМатче: {}, {} год'.format(team.name, team.year)
	context['year'] = team.year
	context = team.update_context_for_team_page(context, request.user, ordering=models.ORDERING_NAME)
	if 'runners' in context:
		template = 'klb/team_add_new_participants_step2.html'
	else:
		template = 'klb/team_add_new_participants_step1.html'
	return render(request, template, context)

@login_required
def klb_team_changes_history(request, team_id):
	team = get_object_or_404(models.Klb_team, pk=team_id)
	_, has_rights, target = check_rights(request, club=team.club)
	if not has_rights:
		return target
	return changes_history(request, team, team.get_absolute_url())

@login_required
def klb_team_delete(request, team_id):
	team = get_object_or_404(models.Klb_team, pk=team_id)
	year = team.year
	club = team.club
	context, has_rights, target = check_rights(request, club=club)
	if not has_rights:
		return target
	if year < models_klb.CUR_KLB_YEAR:
		messages.warning(request, 'Вы уже не можете удалять команды из КЛБМатча-{}. Тот матч давно в прошлом.'.format(year))
		return redirect(team)
	if club.klb_team_set.filter(year=year, number__gt=team.number).exists():
		messages.warning(request, 'Вы можете удалять только команду клуба с максимальным номером. Для более сложных действий,'
			+ f' пожалуйста, напишите письмо на {settings.EMAIL_INFO_USER}')
		return redirect(team)
	if team.klb_participant_set.exists():
		messages.warning(request, 'Вы не можете удалить команду, в которой есть хотя бы один участник')
		return redirect(team)
	models.log_obj_delete(request.user, team, action_type=models.ACTION_DELETE)
	messages.success(request, 'Команда «{}» успешно удалена из КЛБМатча-{}'.format(team.name, year))
	team.delete()
	fill_match_places(year)
	return redirect(club)
