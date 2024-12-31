from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.db.models.query import Prefetch
from django.db.models import Q, Sum
from django.shortcuts import render

from collections import OrderedDict
import datetime
from typing import Any, Dict, Set

from results import forms, models, models_klb, results_util

RECORDS_ON_PAGE = 100

def get_page_num(request):
	page_vals = (request.POST if request.method == 'POST' else request.GET).getlist('page')
	for page_val in page_vals:
		if page_val.strip() != '':
			return results_util.int_safe(page_val)
	return 1

def get_results_with_splits_ids(results):
	result_ids = set(results.values_list('pk', flat=True))
	return set(models.Split.objects.filter(result_id__in=result_ids).values_list('result_id', flat=True).order_by().distinct())

def paginate_and_render(request, template, context, queryset, show_all=False, page=None, add_results_with_splits=False):
	if show_all:
		qs = list(queryset)
		context['page_enum'] = list(zip(list(range(1, len(qs) + 1)), qs))
	else:
		paginator = Paginator(queryset, RECORDS_ON_PAGE)
		if page is None:
			page = get_page_num(request)
		# context['page_number'] = (unicode(request.POST.lists()) + ' page: {}'.format(page)) if request.method == 'POST' else '@'
		try:
			qs_page = paginator.page(page)
		except PageNotAnInteger:
			# If page is not an integer, deliver first page.
			qs_page = paginator.page(1)
		except EmptyPage:
			# If page is out of range (e.g. 9999), deliver last page of results.
			qs_page = paginator.page(paginator.num_pages)
		first_index = (qs_page.number - 1) * RECORDS_ON_PAGE + 1
		last_index = min(qs_page.number * RECORDS_ON_PAGE, paginator.count)
		context.update({
			'page_enum': list(zip(list(range(first_index, last_index + 1)), qs_page)),
			'page': qs_page,
			'paginator': paginator,
			'first_index': str(first_index),
			'last_index': str(last_index),
			'show_first_page': (qs_page.number > 3),
			'show_last_page': (qs_page.number < paginator.num_pages - 2),
			'show_left_ellipsis': (qs_page.number > 4),
			'show_right_ellipsis': (qs_page.number < paginator.num_pages - 3),
			'show_minus_two_page': (qs_page.number > 2),
			'show_plus_two_page': (qs_page.number < paginator.num_pages - 1),
		})
		if add_results_with_splits:
			context['results_with_splits'] = get_results_with_splits_ids(queryset[first_index - 1:last_index])
	return render(request, template, context)

def user_edit_vars(user, series=None, club=None):
	context = {}
	context['is_admin'] = False
	context['is_editor'] = False
	context['is_extended_editor'] = False
	context['to_show_rating'] = True
	if user.is_authenticated:
		if models.is_admin(user):
			context['is_admin'] = True
		else:
			if series:
				if models.Series_editor.objects.filter(user=user, series=series).exists():
					context['is_editor'] = True
					if hasattr(user, 'user_profile'):
						context['is_extended_editor'] = user.user_profile.is_extended_editor
			elif club:
				context['is_editor'] = models.Club_editor.objects.filter(user=user, club=club).exists()
			else:
				context['is_editor'] = user.groups.filter(name="editors").exists()
			context['is_club_leader'] = user.club_editor_set.exists()
	return context

def get_first_form_error(form): # In case that there are errors
	key, val = list(form.errors.items())[0]
	if key in form.fields:
		key = form.fields[key].label
		return '{}: {}'.format(key, val[0])
	else:
		return str(val[0])

def add_race_dependent_attrs(results):
	return results.select_related('race__distance', 'race__distance_real', 'category_size', 'result_on_strava',
		'race__event__series__city__region__country', 'race__event__series__city_finish__region__country', 'race__event__series__country',
		'race__event__city__region__country', 'race__event__city_finish__region__country')

def prefetch_record_results(results):
	return results.prefetch_related(
		Prefetch('record_result_set',
			queryset=models.Record_result.objects.filter(Q(cur_place=1) | Q(cur_place_electronic=1) | Q(was_record_ever=True)).select_related(
				'age_group', 'country')
		)
	)

N_RESULTS_ON_USER_PAGE_DEFAULT = 100
def get_filtered_results_dict(request, has_many_distances, is_in_klb, show_full_page, runner=None, user=None, series_id=None):
	context = {}
	result_set = runner.result_set if runner else user.result_set
	results = add_race_dependent_attrs(result_set).select_related('klb_result').order_by(
		'-race__event__start_date', '-race__event__start_time', '-race__start_date', '-race__start_time')
	if user:
		results = results.prefetch_related(Prefetch('race__event__document_set',
			to_attr='docs',
			queryset=models.Document.objects.filter(
				document_type__in=(models.DOC_TYPE_PHOTOS, models.DOC_TYPE_IMPRESSIONS),
				created_by=user)))
		context['has_docs'] = user.document_set.filter(
			document_type__in=(models.DOC_TYPE_PHOTOS, models.DOC_TYPE_IMPRESSIONS)).exists()
	elif runner:
		results = results.prefetch_related(Prefetch('race__event__document_set',
			to_attr='docs',
			queryset=models.Document.objects.filter(
				document_type__in=(models.DOC_TYPE_PHOTOS, models.DOC_TYPE_IMPRESSIONS),
				author_runner=runner)))
		context['has_docs'] = runner.document_set.filter(
			document_type__in=(models.DOC_TYPE_PHOTOS, models.DOC_TYPE_IMPRESSIONS)).exists()


	context['n_results_total'] = results.count() # When filters show 0 results, we need to show filters anyway!

	filtered_results = prefetch_record_results(results)
	if context['n_results_total'] > 0:
		initial = {}
		if series_id:
			initial['series'] = series_id
			filtered_results = filtered_results.filter(race__event__series_id=series_id)
		context['resultFilterForm'] = forms.RunnerResultFilterForm(result_set, context['n_results_total'], initial=initial)

		if 'btnFilter' in request.GET:
			context['resultFilterForm'] = forms.RunnerResultFilterForm(result_set, context['n_results_total'], data=request.GET)
			if context['resultFilterForm'].is_valid():
				series = context['resultFilterForm'].cleaned_data.get('series')
				if series:
					filtered_results = filtered_results.filter(race__event__series_id=series)

				distance = context['resultFilterForm'].cleaned_data.get('distance')
				if distance:
					filtered_results = filtered_results.filter(race__distance_id=distance)

				name = context['resultFilterForm'].cleaned_data.get('name')
				if name:
					filtered_results = filtered_results.filter(Q(race__event__name__icontains=name) | Q(race__event__series__name__icontains=name))

	if is_in_klb:
		result_ids = filtered_results.values_list('pk', flat=True)
		context['klb_pending_result_ids'] = set(models.Table_update.objects.filter(
			action_type__in=(models.ACTION_UNOFF_RESULT_CREATE, models.ACTION_RESULT_UPDATE),
			is_verified=False, is_for_klb=True, child_id__in=result_ids).values_list('child_id', flat=True))

	context['results_with_splits'] = get_results_with_splits_ids(filtered_results)

	context['show_full_page'] = show_full_page
	if (not show_full_page) and (context['n_results_total'] > N_RESULTS_ON_USER_PAGE_DEFAULT) and ('btnFilter' not in request.GET):
		context['show_full_page_link'] = True
		filtered_results = filtered_results.all()[:N_RESULTS_ON_USER_PAGE_DEFAULT]
		context['N_RESULTS_ON_USER_PAGE_DEFAULT'] = N_RESULTS_ON_USER_PAGE_DEFAULT

	stat_set = (runner if runner else user).user_stat_set.filter(year=None)
	context['distances'] = stat_set.select_related('distance').order_by('distance__distance_type', '-distance__length')
	if has_many_distances and not show_full_page:
		context['distances'] = context['distances'].filter(is_popular=True)
	context['best_result_ids'] = set(stat_set.values_list('best_result_id', flat=True))

	context['results'] = filtered_results

	return context

def get_clubs_managed_by_user(user, is_admin: bool) -> Set[int]:
	res = set()
	if user.is_authenticated:
		res = set(user.club_editor_set.values_list('club_id', flat=True))
	if is_admin:
		res |= set([63, 66]) # Здоровье и IRC - чтобы админы знали, как это выглядит для редакторов клубов
	return res

def get_lists_for_club_membership(user, runner: models.Runner, is_admin: bool) -> Dict[str, Any]:
	context = {}
	runner_clubs = runner.club_member_set.select_related('club').order_by('club__name')
	runner_current_club_ids = set()
	today = datetime.date.today()

	clubs_managed_by_user = get_clubs_managed_by_user(user, is_admin)
	is_admin_or_self = is_admin or (user.id == runner.user_id)

	if runner_clubs:
		current_clubs = runner_clubs.filter(Q(date_removed=None) | Q(date_removed__gte=today))
		context['current_clubs'] = [(club_member, is_admin_or_self or (club_member.club_id in clubs_managed_by_user)) for club_member in current_clubs]

	if clubs_managed_by_user:
		runner_all_club_ids = set(runner_clubs.values_list('club_id', flat=True))
		context['clubs_to_add'] = models.Club.objects.filter(pk__in=clubs_managed_by_user - runner_all_club_ids).order_by('name')
	if is_admin_or_self or clubs_managed_by_user:
		clubs_was_member_before = runner_clubs.filter(date_removed__lt=today)
		context['clubs_was_member_before'] = [(club_member, is_admin_or_self or (club_member.club_id in clubs_managed_by_user)) for club_member in clubs_was_member_before]
	return context

def get_dict_for_klb_participations_block(runner, is_admin):
	context = {}
	klb_person = runner.klb_person
	if klb_person:
		context['klb_person'] = klb_person
		context['cur_klb_participations'] = OrderedDict()
		for year in [models_klb.CUR_KLB_YEAR, models_klb.NEXT_KLB_YEAR]:
			if models.is_active_klb_year(year, is_admin):
				participant = klb_person.klb_participant_set.filter(year=year).first()
				if participant:
					context['cur_klb_participations'][year] = participant
	return context

# If either fname or lname is given
def filter_runners_by_one_word(runners, name):
	runners_with_good_extra_names = set(models.Extra_name.objects.filter(
		Q(lname__istartswith=name) | Q(fname__istartswith=name)).values_list('runner_id', flat=True)
	)
	return runners.filter(Q(lname__istartswith=name) | Q(fname__istartswith=name) | Q(pk__in=runners_with_good_extra_names))

# Currently midname here is non-empty only if noth lname and fname are specified
def filter_runners_by_name(runners, lname, fname, midname):
	if not (lname or fname):
		return runners
	if not lname:
		return filter_runners_by_one_word(runners, fname)
	if not fname:
		return filter_runners_by_one_word(runners, lname)

	# So both lname and fname are set
	extra_names = models.Extra_name.objects.filter(
		Q(lname__istartswith=lname, fname__istartswith=fname) | Q(lname__istartswith=fname, fname__istartswith=lname))
	if midname:
		extra_names = extra_names.filter(Q(midname='') | Q(midname__istartswith=midname))
	runners_with_good_extra_names = set(extra_names.values_list('runner_id', flat=True)
	)
	return runners.filter(
		  Q(lname__istartswith=lname, fname__istartswith=fname, midname__istartswith=midname)
		| Q(lname__istartswith=fname, fname__istartswith=lname, midname__istartswith=midname)
		| Q(pk__in=runners_with_good_extra_names)
	)

def add_related_to_events(events):
	return events.select_related('series__city__region__country', 'city__region__country', 'series__country').prefetch_related(
		Prefetch('race_set',     queryset=models.Race.objects.select_related('distance', 'certificate').order_by('distance__distance_type',
			'-distance__length', 'precise_name')),
		Prefetch('document_set',   queryset=models.Document.objects.filter(document_type=models.DOC_TYPE_IMPRESSIONS), to_attr='review_set'),
		Prefetch('document_set',    queryset=models.Document.objects.filter(document_type=models.DOC_TYPE_PHOTOS), to_attr='photo_set'),
		Prefetch('news_set',     queryset=models.News.objects.order_by('-date_posted')),
		Prefetch('document_set', queryset=models.Document.objects.exclude(
			document_type__in=[models.DOC_TYPE_PHOTOS, models.DOC_TYPE_IMPRESSIONS]).order_by('document_type', 'comment')),
	).annotate(sum_finishers=Sum('race__n_participants_finished'))
