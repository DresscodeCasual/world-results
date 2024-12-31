from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import get_object_or_404, render

import datetime
from collections import Counter

from results import models, forms, results_util
from . import views_common

@login_required
def runners(request, lname='', fname=''):
	context = views_common.user_edit_vars(request.user)
	runners = models.Runner.objects.select_related('user__user_profile', 'city__region__country')
	if not context['is_admin']:
		runners = runners.filter(n_starts__gt=0).prefetch_related('runner_platform_set__platform')
	list_title = 'Runners'
	conditions = []
	initial = {}
	ordering = 'length_cur_year' # 'finishes_cur_year'
	form = None

	lname = results_util.decode_slashes(lname.strip())
	fname = results_util.decode_slashes(fname.strip())
	if lname or fname:
		initial['lname'] = lname
		initial['fname'] = fname
	elif any(s in request.GET for s in ['btnSearchSubmit', 'page', 'ordering']):
		form = forms.RunnerForm(request.GET)
		if form.is_valid():
			lname = form.cleaned_data['lname'].strip()
			fname = form.cleaned_data['fname'].strip()

			birthday_from = form.cleaned_data['birthday_from']
			if birthday_from:
				runners = runners.filter(Q(birthday_known=True, birthday__gte=birthday_from)
					| Q(birthday_known=False, birthday__year__gt=birthday_from.year))
				conditions.append('born on or after ' + birthday_from.isoformat())

			birthday_to = form.cleaned_data['birthday_to']
			if birthday_to:
				runners = runners.filter(Q(birthday_known=True, birthday__lte=birthday_to)
					| Q(birthday_known=False, birthday__year__lt=birthday_to.year))
				conditions.append('born on or before ' + birthday_to.isoformat())

			if context['is_admin']:
				if form.cleaned_data['is_user']:
					if context['is_admin']:
						runners = runners.filter(user__isnull=False)
					else:
						runners = runners.filter(user__user_profile__is_public=True)
					list_title += ', registered at the site'
			else:
				runners = runners.filter(private_data_hidden=False)
			if 'ordering' in request.GET:
				ordering = request.GET['ordering']
	if form is None:
		form = forms.RunnerForm(initial=initial)

	lname = lname.replace('/', '')
	fname = fname.replace('/', '')
	if lname:
		conditions.append(f'with last name «{lname}*»')
	if fname:
		conditions.append(f'with first name «{fname}*»')
	runners = views_common.filter_runners_by_name(runners, lname, fname, '')

	ordering_list = []
	if ordering == 'finishes_all':
		ordering_list.append('-n_starts')
	elif ordering == 'length_all':
		ordering_list.append('-total_length')
	elif ordering == 'time_all':
		ordering_list.append('-total_time')
	elif ordering == 'eddington':
		ordering_list.append('-eddington')
	elif ordering == 'finishes_cur_year':
		ordering_list.append('-n_starts_cur_year')
	elif ordering == 'length_cur_year':
		ordering_list.append('-total_length_cur_year')
	elif ordering == 'time_cur_year':
		ordering_list.append('-total_time_cur_year')
	elif ordering == 'eddington_cur_year':
		ordering_list.append('-eddington_cur_year')
	elif ordering == 'name':
		ordering_list.append('lname')
		ordering_list.append('fname')
	elif ordering == 'city':
		ordering_list.append('city__name')
	elif ordering == 'birthday':
		ordering_list.append('birthday')
	for x in ['lname', 'fname']:
		if x not in ordering_list:
			ordering_list.append(x)
	runners = runners.order_by(*ordering_list)

	context['list_title'] = list_title + ' ' + ', '.join(conditions)
	context['form'] = form
	context['page_title'] = 'Runners Database'
	context['ordering'] = ordering
	context['lname'] = lname
	context['fname'] = fname
	context['cur_stat_year'] = results_util.CUR_YEAR_FOR_RUNNER_STATS
	context['cur_year'] = datetime.date.today().year
	return views_common.paginate_and_render(request, 'results/runners.html', context, runners)

@login_required
def runner_details_login_required(request):
	pass

def runner_details(request, runner_id, series_id=None, show_full_page=False):
	runner = get_object_or_404(models.Runner, pk=runner_id)
	if (not runner.deathday) and (not request.user.is_authenticated):
		return runner_details_login_required(request)
	context = views_common.user_edit_vars(request.user)
	klb_person = runner.klb_person
	user = runner.user
	context['runner'] = runner

	context.update(views_common.get_lists_for_club_membership(request.user, runner, context['is_admin']))
	context.update(views_common.get_dict_for_klb_participations_block(runner, context['is_admin']))
	context.update(views_common.get_filtered_results_dict(
		request=request,
		runner=runner,
		has_many_distances=runner.has_many_distances,
		is_in_klb='klb_person' in context,
		series_id=series_id,
		show_full_page=show_full_page,
	))

	runner_name = f'{runner.fname} {runner.lname}' if (context['is_admin'] or not runner.private_data_hidden) else '(имя скрыто)'
	context['page_title'] = f'{runner_name}: все результаты'
	context['cur_stat_year'] = results_util.CUR_YEAR_FOR_RUNNER_STATS
	context['cur_year'] = datetime.date.today().year
	context['platforms'] = runner.runner_platform_set.order_by('platform_id', 'value').select_related('platform')
	if context['is_admin']:
		context['show_unclaim_unclaimed_by_user_link'] = (runner.user is not None) and runner.result_set.filter(user=None).exists()

	return render(request, 'results/runner_details.html', context)

def best_by_regions_visited(request, country_id: str):
	# distance_id = results_util.DISTANCE_CODES_INV.get(distance_code)
	# distance = None if (distance_id == -1) else get_object_or_404(models.Distance, pk=distance_id)
	country = get_object_or_404(models.Country, pk=country_id, pk__in=('RU', 'BY'))
	context = {}
	context['country'] = country
	context['page_title'] = f'Побегавшие в максимальном числе регионов {country.prep_case}'
	context['marathoners'] = country.regions_visited_set.filter(distance_id=results_util.DIST_MARATHON_ID).select_related('runner__user__user_profile').order_by(
		'-value', 'runner__lname', 'runner__fname')
	context['any_distance'] = country.regions_visited_set.filter(distance=None).select_related('runner__user__user_profile').order_by(
		'-value', 'runner__lname', 'runner__fname')
	return render(request, 'results/best_by_regions_visited.html', context)

def regions_for_runner(request, runner_id: int, country_id: str, distance_code: str):
	runner = get_object_or_404(models.Runner, pk=runner_id)
	distance_id = results_util.DISTANCE_CODES_INV.get(distance_code)
	distance = None if (distance_id == -1) else get_object_or_404(models.Distance, pk=distance_id)
	country = get_object_or_404(models.Country, pk=country_id, pk__in=('RU', 'BY'))
	context = {}
	distance_desc = 'всех дистанциях'
	if distance_id == results_util.DIST_MARATHON_ID:
		distance_desc == 'марафонах'
	elif distance:
		distance_desc == f'дистанции {distance}'
	context['page_desc'] = f'число финишей на {distance_desc} по регионам {country.prep_case}'
	context['page_title'] = runner.name() + ': ' + context['page_desc']
	context['runner'] = runner

	regions_dict = {region.id: region for region in country.region_set.all()}
	regions = Counter()
	results = runner.result_set.filter(
		Q(race__event__city__region__country=country) | Q(race__event__city=None, race__event__series__city__region__country=country),
		status=models.STATUS_FINISHED,
	)
	if distance:
		results = results.filter(race__distance=distance)
	context['total'] = 0
	for event_region, series_region in results.values_list('race__event__city__region_id', 'race__event__series__city__region_id'):
		region_id = event_region if event_region else series_region
		regions[regions_dict[region_id]] += 1
		context['total'] += 1
	context['regions'] = sorted(regions.most_common(100), key=lambda x: x[0].name)
	return render(request, 'results/regions_for_runner.html', context)
