from django.shortcuts import get_object_or_404, render, redirect
from django.db.models import Q
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.urls import reverse
import datetime

from results import models, models_klb, results_util
from editor import runner_stat
from editor.forms import ClubForm, ClubMemberForm, RunnerForClubForm
from .views_common import group_required, check_rights, changes_history
from .views_user_actions import log_form_change
from .views_klb_stat import fill_match_places

@login_required
def club_details(request, club_id=None, club=None, frmClub=None):
	if club is None:
		club = get_object_or_404(models.Club, pk=club_id)
	context, has_rights, target = check_rights(request, club=club)
	if not has_rights:
		return target

	frmClub = None
	if 'frmClub_submit' in request.POST:
		frmClub = ClubForm(request.POST, request.FILES, instance=club, is_admin=context['is_admin'])
		if frmClub.is_valid():
			club = frmClub.save()
			if 'logo' in frmClub.changed_data:
				if not club.make_thumbnail():
					messages.warning(request, "Не получилось уменьшить эмблему клуба.")
				if club.logo:
					club.url_logo = '{}/{}'.format(results_util.SITE_URL, club.logo_thumb.name)
				elif club.url_logo and not club.logo:
					club.url_logo = ''
				club.save()
			log_form_change(request.user, frmClub, action=models.ACTION_UPDATE, exclude=['region'])
			messages.success(request, 'Клуб «{}» успешно обновлён. Изменены следующие поля: {}'.format(club.name, ", ".join(frmClub.changed_data)))
			return redirect(club.get_editor_url())
		else:
			messages.warning(request, "Клуб не обновлён. Пожалуйста, исправьте ошибки в форме.")
	elif ('clubName_add' in request.POST) and context['is_admin']:
		name = request.POST.get('new_club_name', '').strip()
		if not name:
			messages.warning(request, 'Вы указали пустое имя')
		elif (club.name.lower() == name.lower()) or club.club_name_set.filter(name__iexact=name).exists():
			messages.warning(request, 'Имя «{}» уже и так есть у выбранного клуба'.format(name))
		else:
			models.Club_name.objects.create(club=club, name=name, added_by=request.user)
			messages.success(request, 'Имя «{}» успешно добавлено'.format(name))
		return redirect(club)

	if frmClub is None:
		initial = {}
		if club.city:
			initial['city'] = club.city
			initial['region'] = club.city.region.id
		frmClub = ClubForm(instance=club, initial=initial, is_admin=context['is_admin'])
	context['club'] = club
	context['form'] = frmClub
	context['page_title'] = 'Клуб {} (id {})'.format(club.name, club.id) if club.id else 'Создание нового клуба'
	return render(request, "editor/club_details.html", context)

@group_required('admins')
def club_delete(request, club_id):
	club = get_object_or_404(models.Club, pk=club_id)
	context, has_rights, target = check_rights(request, club=club)
	if not has_rights:
		return target
	has_dependent_objects = club.has_dependent_objects()
	ok_to_delete = False
	form = None
	if 'frmForClub_submit' in request.POST:
		if has_dependent_objects:
			messages.warning(request, "Нельзя удалять клуб с командами.")
		else:
			ok_to_delete = True
	else:
		messages.warning(request, "Вы не указали клуб для удаления.")

	if ok_to_delete:
		n_deleted_members = 0
		for club_member in list(club.club_member_set.all()):
			models.log_obj_delete(request.user, club, child_object=club_member, action_type=models.ACTION_CLUB_MEMBER_DELETE, comment='При удалении клуба')
			club_member.delete()
			n_deleted_members += 1
		models.log_obj_delete(request.user, club)
		messages.success(request, f'Клуб «{club}» успешно удалён. Удалено членов клуба: {n_deleted_members}')
		club.delete()
		if has_dependent_objects:
			pass
		else:
			return redirect('results:clubs')
	return club_details(request, club_id=club_id, club=club)

@group_required('admins')
def club_name_delete(request, club_id, club_name_id):
	club = get_object_or_404(models.Club, pk=club_id)
	club_name = get_object_or_404(club.club_name_set, pk=club_name_id)
	messages.success(request, 'Имя «{}» успешно удалено'.format(club_name.name))
	club_name.delete()
	return redirect(club)

@login_required
def club_create(request):
	is_admin = request.user.groups.filter(name="admins").exists()
	club = models.Club(created_by=request.user, is_active=is_admin)
	form = None
	if 'check_speed' in request.POST:
		speed = results_util.int_safe(request.POST['check_speed'].strip())
		if speed != 36:
			messages.warning(request, 'Ответ неправильный. Подумайте ещё! Или просто побегайте.')
			return redirect('results:clubs')
	elif 'frmClub_submit' in request.POST:
		form = ClubForm(request.POST, instance=club, is_admin=is_admin)
		if form.is_valid():
			club = form.save()
			log_form_change(request.user, form, action=models.ACTION_CREATE)
			if is_admin:
				messages.success(request, 'Клуб «{}» успешно создан. Проверьте, всё ли правильно.'.format(club))
			else:
				messages.success(request, ('Клуб «{}» успешно создан. Пока он виден только вам. '
					+ 'Он будет добавлен на страницу клубов после одобрения администраторами.').format(club))
				models.Club_editor.objects.create(
					user=request.user,
					club=club,
					added_by=request.user,
				)
			return redirect(club.get_editor_url())
		else:
			messages.warning(request, "Клуб не создан. Пожалуйста, исправьте ошибки в форме.")
	return club_details(request, club=club, frmClub=form)

@login_required
def club_changes_history(request, club_id):
	club = get_object_or_404(models.Club, pk=club_id)
	_, has_rights, target = check_rights(request, club=club)
	if not has_rights:
		return target
	return changes_history(request, club, club.get_absolute_url())

@login_required
def add_cur_year_team(request, club_id):
	return add_team(request, club_id, models_klb.CUR_KLB_YEAR)

@login_required
def add_next_year_team(request, club_id):
	return add_team(request, club_id, models_klb.NEXT_KLB_YEAR)

FIRST_TEAM_NUMBER = 10000
def add_team(request, club_id, year):
	club = get_object_or_404(models.Club, pk=club_id)
	context, has_rights, target = check_rights(request, club=club)
	if not has_rights:
		return target
	if models.Klb_team.objects.filter(year=year, number=club.id).exists():
		last_team = models.Klb_team.objects.filter(year=year, number__gte=FIRST_TEAM_NUMBER).order_by('-number').first()
		if last_team:
			number = last_team.number + 1
		else:
			number = FIRST_TEAM_NUMBER
	else:
		number = club.id
	team = models.Klb_team.objects.create(
		club=club,
		number=number,
		year=year,
		name=club.get_next_team_name(year),
		added_by=request.user,
	)
	models.log_obj_create(request.user, team, models.ACTION_CREATE)
	answer = 'Команда успешно создана. Вы можете добавить в неё новых участников'
	if club.klb_team_set.filter(year=year - 1).exists():
		answer += ' или участников команд Вашего клуба из предыдущего Матча'
	messages.success(request, answer)
	fill_match_places(year)
	return redirect(team)

def get_cur_year_members(club):
	return club.club_member_set.exclude(date_removed__lt=datetime.date.today()).select_related(
		'runner__city__region__country', 'runner__user__user_profile').order_by('runner__lname', 'runner__fname')

@login_required
def add_club_member(request, club_id):
	club = get_object_or_404(models.Club, pk=club_id)
	context, has_rights, target = check_rights(request, club=club)
	if not has_rights:
		return target
	user = request.user
	form = None
	to_create_runner = to_create_member = False
	new_runner = None

	if 'step1_submit' in request.POST:
		form = RunnerForClubForm(user=user, data=request.POST)
		if form.is_valid():
			new_runner = form.instance
			runners = models.Runner.objects.filter(
				Q(birthday=None) | Q(birthday__year=new_runner.birthday.year, birthday_known=False) | Q(birthday=new_runner.birthday, birthday_known=True),
				lname=new_runner.lname,
				fname=new_runner.fname,
				# n_starts__gt=0,
			).select_related('city__region__country').order_by('-n_starts')
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
						info.append('{} год рождения'.format(runner.birthday.year))
					if runner.city:
						info.append(runner.city.nameWithCountry())
					n_starts = runner.n_starts if runner.n_starts else 0
					info.append('{} результат{} в базе данных'.format(n_starts, results_util.ending(n_starts, 1)))
					runner_dict['info'] = ', '.join(info)

					runner_dict['club_member'] = runner.club_member_set.filter(club=club).first()
					context['runners'].append(runner_dict)
			else: # There are no similar runners, so we can create him/her
				to_create_runner = True
		else:
			messages.warning(request, 'Пожалуйста, исправьте ошибки в форме')
	elif 'step2_submit' in request.POST:
		form = RunnerForClubForm(user=user, data=request.POST)
		if form.is_valid():
			new_runner = form.instance
			runner_id = results_util.int_safe(request.POST.get('runner_id', 0))
			if runner_id == -1: # This special value means we should create new runner
				to_create_runner = True
			else: # We should add some existing runner
				runner = models.Runner.objects.filter(pk=runner_id).first()
				if runner:
					club_member = runner.club_member_set.filter(club=club).first()
					if club_member:
						if club_member.is_already_removed():
							messages.warning(request, '{} (id {}) уже был членом клуба «{}» до {}'.format(
								runner.name(), runner.id, club.name, club_member.date_removed))
						else:
							messages.warning(request, '{} (id {}) уже и так член клуба «{}»'.format(runner.name(), runner.id, club.name))
						return redirect(club)
					else:
						to_create_member = True
				else:
					messages.warning(request, 'К сожалению, выбранный Вами бегун (id {}) не найден. Попробуйте ещё раз'.format(runner_id))
		else:
			messages.warning(request, 'Пожалуйста, исправьте ошибки в форме')

	if to_create_runner:
		runner = form.save(commit=False)
		runner.birthday_known = True
		runner.created_by = user
		runner.save()
		models.log_obj_create(user, runner, models.ACTION_CREATE, comment='При добавлении нового участника в КЛБМатч')
		to_create_member = True
	if to_create_member:
		email = form.cleaned_data.get('email', '')
		phone_number = form.cleaned_data.get('phone_number', '')
		club_member = models.Club_member.objects.create(
			runner=runner,
			club=club,
			email=form.cleaned_data.get('email', ''),
			phone_number=form.cleaned_data.get('phone_number', ''),
			date_registered=form.cleaned_data['date_registered'],
			added_by=user,
		)
		if runner.user and (runner.user != user):
			models.User_added_to_team_or_club.objects.create(
				user=runner.user,
				club=club,
				added_by=user,
			)
		if not to_create_runner: # If this runner already existed, maybe we can update their data now
			runner.update_if_needed(user, new_runner, comment='При добавлении отдельного участника в клуб')
		runner_stat.update_runner_stat(club_member=club_member)
		models.log_obj_create(user, club, models.ACTION_CLUB_MEMBER_CREATE, child_object=club_member, comment='При добавлении нового участника в клуб')
		messages.success(request, f'{runner.name()} успешно добавлен{runner.a_if_needed()} в команду')
		return redirect(club)

	if form is None:
		initial = {}
		if club.city:
			initial['city_id'] = club.city.id
			initial['region'] = club.city.region.id
		form = RunnerForClubForm(user=user, initial=initial)
	context['club'] = club
	context['members'] = get_cur_year_members(club)
	context['cur_stat_year'] = results_util.CUR_YEAR_FOR_RUNNER_STATS
	context['form'] = form
	context['page_title'] = 'Добавление участника в клуб «{}»'.format(club.name)
	context['cur_klb_teams'] = club.klb_team_set.filter(year=models_klb.CUR_KLB_YEAR)
	if 'runners' in context:
		template = 'club/add_club_member_step2.html'
	else:
		template = 'club/add_club_member_step1.html'
	return render(request, template, context)

@login_required
def add_runner(request, club_id, runner_id):
	runner = get_object_or_404(models.Runner, pk=runner_id)
	return member_details(request, club_id, member_id=None, runner=runner)

@login_required
def member_details(request, club_id, member_id, runner=None, return_page='current'):
	club = get_object_or_404(models.Club, pk=club_id)
	if member_id:
		club_member = get_object_or_404(models.Club_member, club=club, pk=member_id)
		adding_new = False
	else:
		if club.club_member_set.filter(runner=runner).exists():
			messages.warning(request, '{} (id участника {}) уже состоит или состоял ранее в Вашем клубе. Вы можете изменить даты его вхождения в клуб'.format(
				runner.name(), runner.id))
			return redirect(club.get_members_list_url())
		club_member = models.Club_member(club=club, runner=runner, added_by=request.user, date_registered=datetime.date.today())
		adding_new = True

	context, has_rights, target = check_rights(request, club=club, show_warning=False)
	context['editing_myself'] = False
	if not has_rights:
		# The only exception when a non-admin and non-club-editor can edit a club membership is a user editing themselves
		if (not adding_new) and (request.user.id == club_member.runner.user_id):
			context['editing_myself'] = True
		else:
			messages.warning(request, 'У Вас нет прав на это действие.')
			return target
	
	if not context['editing_myself']:
		context['members_list_url'] = club.get_all_members_list_url() if (return_page == 'all') else club.get_members_list_url()
		context['cur_stat_year'] = results_util.CUR_YEAR_FOR_RUNNER_STATS

	if 'frmClubMember_submit' in request.POST:
		form = ClubMemberForm(request.POST, instance=club_member)
		if form.is_valid():
			club_member = form.save()
			action = models.ACTION_CLUB_MEMBER_CREATE if adding_new else models.ACTION_CLUB_MEMBER_UPDATE
			log_form_change(request.user, form, action=action, obj=club, child_id=club_member.id)
			runner_stat.update_runner_stat(club_member=club_member)
			if adding_new:
				if club_member.runner.user and (club_member.runner.user != request.user):
					models.User_added_to_team_or_club.objects.create(
						user=club_member.runner.user,
						club=club,
						added_by=request.user,
					)
				messages.success(request, f'{club_member.runner.name()} успешно добавлен{runner.a_if_needed()} в клуб')
			else:
				runner = club_member.runner
				changed_runner_fields = []
				messages.success(request, f'Данные члена клуба {runner.name()} успешно обновлены')
				if runner.city is None:
					city = form.cleaned_data.get('city')
					if city:
						runner.city = city
						changed_runner_fields.append('city')
						messages.success(request, f'У участника забегов теперь указан город')
				if not runner.birthday_known:
					birthday = form.cleaned_data.get('birthday')
					if birthday:
						if runner.birthday and (runner.birthday.year != birthday.year):
							messages.warning(request,
								f'Что-то не то: у участника забегов уже указан год рождения {runner.birthday.year}, а вы сейчас указали дату рождения с годом {birthday.year}.')
							messages.warning(request, 'Пожалуйста, напишите нам, если сейчас указан неправильный год рождения.')
						else:
							runner.birthday = birthday
							runner.birthday_known = True
							changed_runner_fields.append('birthday')
							changed_runner_fields.append('birthday_known')
							messages.success(request, f'У участника забегов теперь указана дата рождения')
				if changed_runner_fields:
					runner.save()
					models.log_obj_create(request.user, runner, models.ACTION_UPDATE, field_list=changed_runner_fields, comment='При правке члена клуба')
			return redirect(reverse('results:home') if context['editing_myself'] else context['members_list_url'])
		else:
			messages.warning(request, 'Данные члена клуба не обновлены. Пожалуйста, исправьте ошибки в форме.')
	else:
		form = ClubMemberForm(instance=club_member)

	context['club'] = club
	context['form'] = form
	context['adding_new'] = adding_new
	context['member'] = club_member
	context['runner'] = club_member.runner
	context['members'] = get_cur_year_members(club)
	if context['editing_myself']:
		context['page_title'] = f'Ваше членство в клубе «{club.name}»'
	if adding_new:
		context['page_title'] = f'Добавление участника {club_member.runner.name()} в клуб «{club.name}»'
	else:
		context['page_title'] = f'Редактирование участника {club_member.runner.name()} клуба «{club.name}»'

	return render(request, 'club/club_member_details.html', context)

@login_required
def delete_member(request, club_id, member_id):
	club = get_object_or_404(models.Club, pk=club_id)
	context, has_rights, target = check_rights(request, club=club)
	if not has_rights:
		return target
	club_member = get_object_or_404(models.Club_member, club=club, pk=member_id)
	models.log_obj_delete(request.user, club, child_object=club_member, action_type=models.ACTION_CLUB_MEMBER_DELETE, comment='Со страницы члена клуба')
	messages.success(request, f'{club_member.runner.name()} успешно удалён из клуба «{club.name}».')
	club_member.delete()
	return redirect(club.get_members_list_url())

def create_club_members(club): # Initial creation
	n_members_left = 0
	n_members_created = 0
	n_members_updated = 0
	runner_ids = set(models.Klb_participant.objects.filter(team__club=club).values_list('klb_person__runner__id', flat=True))
	for runner in models.Runner.objects.filter(id__in=runner_ids).order_by('pk'):
		participants = models.Klb_participant.objects.filter(team__club=club, klb_person__runner=runner).order_by('year')
		first_year = participants.first().year
		last_year = participants.last().year
		existing_club_members = runner.club_member_set.filter(club=club)
		if existing_club_members.count() == 1:
			existing_club_member = existing_club_members.first()
			if (existing_club_member.date_registered == datetime.date(first_year, 1, 1)) \
					and (existing_club_member.date_removed == datetime.date(last_year, 12, 31)):
				n_members_left += 1
				continue
		if existing_club_members.exists():
			n_members_updated += 1
			existing_club_members.delete()
		else:
			n_members_created += 1
		club_member = models.Club_member.objects.create(
			runner=runner,
			club=club,
			email=participants.last().email,
			phone_number=participants.last().phone_number,
			date_registered=datetime.date(first_year, 1, 1),
			date_removed=datetime.date(last_year, 12, 31),
			added_by=models.USER_ROBOT_CONNECTOR,
		)
		runner_stat.update_runner_stat(club_member=club_member)
	print('Done! For club {} we created {} members, updated {} members, left as is {} members.'.format(
		club.id, n_members_created, n_members_updated, n_members_left))

@login_required
def update_records(request, club_id):
	club = get_object_or_404(models.Club, pk=club_id)
	context, has_rights, target = check_rights(request, club=club)
	if not has_rights:
		return target
	n_members_updated = 0
	for club_member in club.club_member_set.all():
		runner_stat.update_runner_stat(club_member=club_member)
		n_members_updated += 1
	messages.success(request, f'Обновлены данные о лучших результатах {n_members_updated} членов клуба за все годы.')
	return redirect(club)
