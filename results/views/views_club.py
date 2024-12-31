from django.shortcuts import get_object_or_404, render, redirect
from django.contrib.auth.decorators import login_required
from django.db.models.query import Prefetch
from django.http import FileResponse
from django.contrib import messages
from django.db.models import Q

from collections import OrderedDict
import datetime
from typing import Any
import xlsxwriter

from results import models, models_klb, forms, results_util
from . import views_common

def get_club_records_context(club, year=None):
	context = {}
	distances = [models.Distance.objects.get(pk=i) for i in results_util.DISTANCES_FOR_CLUB_STATISTICS]

	members = club.club_member_set.all()
	if year:
		members = members.filter(Q(date_registered=None) | Q(date_registered__year__lte=year), Q(date_removed=None) | Q(date_removed__year__gte=year))
	runner_ids = set(members.values_list('runner_id', flat=True))
	gender_names = {results_util.GENDER_MALE:'male', results_util.GENDER_FEMALE:'female'}

	result_dicts = {}
	for distance in distances:
		result_dicts[distance] = {}
		minus = '-' if (distance.distance_type in models.TYPES_MINUTES) else ''
		for gender in (results_util.GENDER_MALE, results_util.GENDER_FEMALE):
			result_dicts[distance][gender] = {}
			stats = models.User_stat.objects.filter(club_member__in=members, club_member__runner__gender=gender, distance=distance).select_related(
				'club_member__runner', 'best_result__race__event__series__city__region__country', 'best_result__runner',
				'best_result_age_coef__race__event__series__city__region__country')
			if year:
				stats = stats.filter(year=year)
			else:
				stats = stats.filter(year=None)
			result_dicts[distance][gender]['abs'] = list(stats.order_by(minus + 'value_best')[:3])
			if distance.distance_type not in models.TYPES_MINUTES:
				result_dicts[distance][gender]['age'] = list(stats.exclude(value_best_age_coef=None).order_by(minus + 'value_best_age_coef')[:3])

	for method in ('abs', 'age'):
		for gender in (results_util.GENDER_MALE, results_util.GENDER_FEMALE):
			lines = OrderedDict()
			for distance in distances:
				if (distance.distance_type in models.TYPES_MINUTES) and (method == 'age'):
					continue
				if result_dicts[distance][gender][method]:
					lines[distance] = result_dicts[distance][gender][method]
			if lines:
				context['records_{}_{}'.format(method, gender_names[gender])] = lines

	winners = OrderedDict()
	for distance in distances:
		line = {}
		for gender in (results_util.GENDER_MALE, results_util.GENDER_FEMALE):
			if len(result_dicts[distance][gender]['abs']) > 0:
				line[gender_names[gender]] = result_dicts[distance][gender]['abs'][0]
		if line:
			winners[distance] = line

	context['winners'] = winners
	context['form'] = forms.ClubRecordsForm(club=club, initial={'year': year if year else 0})
	return context

def club_details(request, club_id):
	club = get_object_or_404(models.Club, pk=club_id)
	user = request.user
	context = views_common.user_edit_vars(user, club=club)
	context['club'] = club
	teams_by_year = OrderedDict()
	teams = club.klb_team_set.order_by('-year', 'name')
	for team in teams:
		if team.year not in teams_by_year:
			teams_by_year[team.year] = []
		row = {'team': team}
		if team.place:
			row['n_teams'] = models.Klb_team.get_teams_number(year=team.year)
			if team.place_medium_teams:
				row['n_medium_teams'] = models.Klb_team.get_medium_teams_number(year=team.year)
			elif team.place_small_teams:
				row['n_small_teams'] = models.Klb_team.get_small_teams_number(year=team.year)
		teams_by_year[team.year].append(row)
	context['teams_by_year'] = teams_by_year
	context['page_title'] = 'Клуб любителей бега {}'.format(club.name)
	context['club_names'] = club.club_name_set.order_by('name')
	if club.city:
		context['page_title'] += ' ({})'.format(club.strCity())
	if context['is_admin'] or context['is_editor']:
		if datetime.date.today().year <= models_klb.last_match_year(models_klb.CUR_KLB_YEAR):
			context['cur_year_team_name'] = club.get_next_team_name(models_klb.CUR_KLB_YEAR)
			context['CUR_KLB_YEAR'] = models_klb.CUR_KLB_YEAR
		if models.is_active_klb_year(models_klb.NEXT_KLB_YEAR, context['is_admin']):
			context['next_year_team_name'] = club.get_next_team_name(models_klb.NEXT_KLB_YEAR)
			context['NEXT_KLB_YEAR'] = models_klb.NEXT_KLB_YEAR
	if user.is_authenticated and hasattr(user, 'runner'):
		context['is_active_member'] = user.runner.id in club.get_active_members_or_klb_participants_runner_ids()

	context.update(get_club_records_context(club=club))
	return render(request, 'club/club_details.html', context)

def clubs(request, view=0):
	context = views_common.user_edit_vars(request.user)
	view = results_util.int_safe(view)
	context['page_title'] = 'Клубы любителей бега'
	clubs = models.Club.objects.exclude(pk=models.INDIVIDUAL_RUNNERS_CLUB_NUMBER).select_related(
		'city__region__country').prefetch_related(
			Prefetch('klb_team_set', queryset=models.Klb_team.objects.filter(year=models_klb.CUR_KLB_YEAR).order_by('name')), 'editors'
		).order_by('name')
	if not context['is_admin']:
		clubs = clubs.filter(is_active=True)
	if view == 1:
		clubs = clubs.filter(email='')
	context['clubs'] = clubs
	context['user_is_authenticated'] = request.user.is_authenticated
	context['CUR_KLB_YEAR'] = models_klb.CUR_KLB_YEAR
	return render(request, 'club/clubs.html', context)

def club_records(request, club_id, year=None):
	if 'year' in request.POST:
		year = results_util.int_safe(request.POST['year'])
		if year < models.FIRST_YEAR_FOR_STAT_UPDATE:
			return redirect('results:club_records', club_id=club_id)
		if year > datetime.date.today().year:
			return redirect('results:club_records', club_id=club_id)
		return redirect('results:club_records', club_id=club_id, year=year)

	club = get_object_or_404(models.Club, pk=club_id)
	user = request.user
	context = views_common.user_edit_vars(user, club=club)
	context['club'] = club

	year = results_util.int_safe(year)
	context['year'] = year
	context.update(get_club_records_context(club=club, year=year))
	context['page_title'] = 'Лучшие результаты клуба «{}» за {}'.format(club.name, f'{year} год' if year else 'все годы')
	context['template_name'] = 'club/club_records.html'
	return render(request, 'results/base_template.html', context)

def club_members(request, club_id, ordering='name', current_members=True):
	club = get_object_or_404(models.Club, pk=club_id)
	user = request.user
	context: dict[str, Any] = views_common.user_edit_vars(user, club=club)
	if not (context['is_admin'] or context['is_editor'] or club.is_member_list_visible):
		messages.warning(request, 'Эта страница пока видна только руководителю клуба')
		return redirect(club)

	if ('btnCreateSheet' in request.POST) and (context['is_admin'] or context['is_editor']):
		fname = create_club_members_sheet(club, current_members=current_members)
		response = FileResponse(open(fname, 'rb'), content_type='application/vnd.ms-excel')
		response['Content-Disposition'] = 'attachment; filename="{}"'.format(fname.split('/')[-1])
		return response

	context['club'] = club
	context['page_title'] = f'Члены клуба «{club.name}»'
	context['current_members'] = current_members
	context['cur_stat_year'] = results_util.CUR_YEAR_FOR_RUNNER_STATS
	context['self_link'] = club.get_members_list_url() if current_members else club.get_all_members_list_url()
	context['ordering'] = ordering

	members = club.club_member_set.all()
	if current_members:
		members = members.exclude(date_removed__lt=datetime.date.today())

	order_by = []
	if ordering == 'name':
		order_by += ['runner__lname', 'runner__fname', 'runner__midname']
	elif ordering == 'birthday':
		order_by.append('runner__birthday')
	elif ordering == 'date_registered':
		order_by.append('date_registered')
	elif ordering == 'date_removed':
		order_by.append('date_removed')
	elif ordering == 'city':
		order_by.append('runner__city__name')
	elif ordering == 'n_starts_cur_year':
		order_by.append('-runner__n_starts_cur_year')
	elif ordering == 'total_length_cur_year':
		order_by.append('-runner__total_length_cur_year')
	elif ordering == 'total_time_cur_year':
		order_by.append('-runner__total_time_cur_year')
	elif ordering == 'n_starts':
		order_by.append('-runner__n_starts')
	elif ordering == 'total_length':
		order_by.append('-runner__total_length')
	elif ordering == 'total_time':
		order_by.append('-runner__total_time')
	for order in ['runner__lname', 'runner__fname', 'runner__midname']:
		if order not in order_by:
			order_by.append(order)

	context['members'] = members.order_by(*order_by).select_related('runner__city__region__country', 'runner__user__user_profile')

	context['show_personal_data'] = context['is_admin'] or context['is_editor']
	if context['show_personal_data']:
		context['all_emails'] = ', '.join(member.email for member in context['members'] if member.email)

	return render(request, 'club/club_members.html', context)

def club_members_all(request, club_id, ordering=''):
	return club_members(request, club_id, ordering=ordering, current_members=False)


def create_club_members_sheet(club, current_members=True):
	fname = results_util.XLSX_FILES_DIR + '/club_{}_{}_members_{}.xlsx'.format(club.id, 'current' if current_members else 'all',
		datetime.datetime.now().strftime('%Y%m%d_%H%M%S'))
	workbook = xlsxwriter.Workbook(fname)
	worksheet = workbook.add_worksheet()
	bold = workbook.add_format({'bold': True})
	number_format = workbook.add_format({'num_format': '0.00'})


	members = club.club_member_set.select_related('runner__city__region__country', 'runner__user__user_profile').order_by('runner__lname', 'runner__fname')
	if current_members:
		today = datetime.date.today()
		members = members.exclude(date_removed__lt=today)
		title = f'Члены клуба «{club.name}» на {results_util.date2str(today, with_nbsp=False)}'
	else:
		title = f'Члены клуба «{club.name}» за всю историю'.format()

	worksheet.write(0, 0, title)
	# worksheet.write(1, 0, unicode(payments.query))

	row = 2
	worksheet.write(row, 11, f'В {results_util.CUR_YEAR_FOR_RUNNER_STATS} году', bold)
	worksheet.write(row, 14, 'Всего', bold)

	row = 3
	worksheet.write(row, 0, '№', bold)
	worksheet.write(row, 1, 'Фамилия', bold)
	worksheet.write(row, 2, 'Имя', bold)
	worksheet.write(row, 3, 'Отчество', bold)
	worksheet.write(row, 4, 'Страница на ПроБЕГе', bold)
	worksheet.write(row, 5, 'Дата рождения', bold)
	worksheet.write(row, 6, 'E-mail', bold)
	worksheet.write(row, 7, 'Телефон', bold)
	worksheet.write(row, 8, 'Населённый пункт', bold)
	worksheet.write(row, 9, 'Пришёл в клуб', bold)
	worksheet.write(row, 10, 'Ушёл из клуба', bold)
	worksheet.write(row, 11, 'Финишей', bold)
	worksheet.write(row, 12, 'Расстояние', bold)
	worksheet.write(row, 13, 'Время', bold)
	worksheet.write(row, 14, 'Финишей', bold)
	worksheet.write(row, 15, 'Расстояние', bold)
	worksheet.write(row, 16, 'Время', bold)

	worksheet.set_column(0, 0, 3.29)
	worksheet.set_column(1, 1, 14)
	worksheet.set_column(2, 2, 11)
	worksheet.set_column(3, 3, 16)
	worksheet.set_column(4, 4, 37)
	worksheet.set_column(5, 5, 16)
	worksheet.set_column(6, 6, 26)
	worksheet.set_column(7, 7, 13)
	worksheet.set_column(8, 8, 30)
	worksheet.set_column(9, 9, 14)
	worksheet.set_column(10, 10, 13.57)
	worksheet.set_column(11, 11, 9)
	worksheet.set_column(12, 12, 11.43)
	worksheet.set_column(13, 13, 17)
	worksheet.set_column(14, 14, 9)
	worksheet.set_column(15, 15, 11.43)
	worksheet.set_column(16, 16, 17)

	for i, member in enumerate(members):
		row += 1
		runner = member.runner
		worksheet.write(row, 0, i + 1)
		worksheet.write(row, 1, runner.lname)
		worksheet.write(row, 2, runner.fname)
		worksheet.write(row, 3, runner.midname)
		worksheet.write(row, 4, results_util.SITE_URL + runner.get_runner_or_user_url())
		worksheet.write(row, 5, runner.strBirthday(with_nbsp=False))
		worksheet.write(row, 6, member.email)
		worksheet.write(row, 7, member.phone_number)
		if runner.city:
			worksheet.write(row, 8, runner.city.nameWithCountry(with_nbsp=False))
		if member.date_registered:
			worksheet.write(row, 9, member.date_registered.strftime("%d.%m.%Y"))
		if member.date_removed:
			worksheet.write(row, 10, member.date_removed.strftime("%d.%m.%Y"))
		if runner.n_starts_cur_year:
			worksheet.write(row, 11, runner.n_starts_cur_year)
		worksheet.write(row, 12, runner.get_length_curyear(with_nbsp=False))
		worksheet.write(row, 13, runner.get_time_curyear(with_br=False))
		if runner.n_starts:
			worksheet.write(row, 14, runner.n_starts)
		worksheet.write(row, 15, runner.get_total_length(with_nbsp=False))
		worksheet.write(row, 16, runner.get_total_time(with_br=False))

	workbook.close()
	return fname

@login_required
def planned_starts(request, club_id):
	club = get_object_or_404(models.Club, pk=club_id)
	user = request.user
	context = views_common.user_edit_vars(user, club=club)
	context['club'] = club

	if not (context['is_admin'] or context['is_editor']):
		if not (user.is_authenticated and hasattr(user, 'runner')
				and 
					(models.Klb_participant.objects.filter(year__gte=models_klb.CUR_KLB_YEAR, team__club=club, klb_person__runner=user.runner).exists()
					or models.Club_member.objects.filter(
						Q(date_removed=None) | Q(date_removed__gte=datetime.date.today()), club=club, runner=user.runner).exists()
					)):
			messages.warning(request, 'Эту страницу могут просматривать только члены активных команд клуба «{}»'.format(club.name))
			return redirect(club)

	user_ids = set(models.Klb_participant.objects.filter(team__club=club, year__gte=models_klb.CUR_KLB_YEAR).exclude(klb_person__runner__user=None).exclude(
		klb_person__runner__user__user_profile__is_public=False).values_list('klb_person__runner__user_id', flat=True))
	user_ids |= set(club.get_active_members_list().exclude(runner__user=None).exclude(runner__user__user_profile__is_public=False).values_list(
		'runner__user_id', flat=True))
	context['calendar_items'] = OrderedDict()

	for calendar in models.Calendar.objects.filter(user_id__in=user_ids, event__start_date__gte=datetime.date.today()).select_related(
			'event__series__city__region__country', 'event__city__region__country', 'race__distance').order_by(
			'event__start_date', 'user__last_name', 'user__first_name'):
		if calendar.event in context['calendar_items']:
			context['calendar_items'][calendar.event].append(calendar)
		else:
			context['calendar_items'][calendar.event] = [calendar]

	context['page_title'] = 'Планируемые старты членов команд клуба «{}»'.format(club.name)
	return render(request, 'club/planned_starts.html', context)

def about_club_membership(request):
	context = {}
	context['page_title'] = 'Что значит «члены клуба» на ПроБЕГе'

	user = request.user
	if user.is_authenticated:
		if hasattr(user, 'runner'):
			context['club_member_set'] = user.runner.club_member_set.order_by('club__name')
		club_editor = user.club_editor_set.first()
		if club_editor:
			context['club_for_edit'] = club_editor.club
	return render(request, 'club/about_club_membership.html', context)
