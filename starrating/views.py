from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.db.models import OuterRef, Subquery
from django.http import HttpResponseForbidden
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils.datastructures import MultiValueDictKeyError
import logging

from editor.views.views_common import group_required
from results import results_util
from results.models import Result, Race, Event, Series, Organizer
from results.views.views_common import user_edit_vars, paginate_and_render, RECORDS_ON_PAGE
from starrating.models import Group, Primary, Parameter, Method, User_review, User_overall
from starrating.aggr.rated_tree_modifications import delete_group
from .utils.show_rating import get_sr_overall_data, get_sr_by_param_data

from .utils.leave_rating import get_params_to_rate_for_race, leave_rating, \
	find_first_race_id_to_rate, \
	postpone_adding_marks as lr_postpone_adding_marks, stop_adding_marks as lr_stop_adding_marks

import django_tables2 as tables
from django_tables2 import RequestConfig
from .constants import MAX_RATING_VALUE, RATING_VALUES_DESCRIPTIONS, CURRENT_METHOD, \
	LEVEL_NAME_TO_NO, LEVEL_NO_TO_NAME, \
	MSG_WHEN_TO_ASK_TO_LEAVE_RATING, ADMIN_CAN_LEAVE_RATING_FOR_ANY_USER

from tools.dj_meta import get_model_by_name
from tools.dj_other import queryset_to_dict
from collections import OrderedDict
from functools import reduce

log = logging.getLogger('sr_views')

def check_user_rights_for_marks(this_user_id, user_id_for_marks, for_current_user, is_admin):
	assert isinstance (user_id_for_marks, int)
	assert isinstance (for_current_user, bool)
	if for_current_user:
		if user_id_for_marks == this_user_id:
			return 0  # ok
		else:
			return 'check_user_rights_for_marks: for_current_user == True, but user_id_for_marks != request.user.id: {}!={}'\
					.format(user_id_for_marks, this_user_id)
	else:
		if is_admin:
			if ADMIN_CAN_LEAVE_RATING_FOR_ANY_USER:
				return 0  # ok
			else:
				return 'ADMIN_CAN_LEAVE_RATING_FOR_ANY_USER = False'
		else:
			return 'is_admin is false'


def check_before_add_marks(race_id, user_id, for_current_user):
	"""
	returns:
		If ok:
			0
		else:
			(message, redirect_url_name)
			If redirect_url_name is None, do not redirect, write message into htmlpage.
	"""
	if Result.objects.filter(user_id=user_id, race_id=race_id).exists():
		if Group.objects.filter(user_id=user_id, race_id=race_id).exists():
			if for_current_user:
				redirect_path = reverse('starrating:my_marks', args=[race_id])
			else:
				redirect_path = reverse('starrating:my_marks_for_user', kwargs={'race_id': race_id, 'user_id': user_id})
			return (
					'Оценки были поставлены ранее',
					redirect_path
				)
		else:
			return 0
	else:
		if for_current_user:
			return (
				'Вы не участвовали в забеге на этой дистанции, поэтому ваши оценки не принимаются',
				reverse('results:home')
			)
		else:
			return (
				'Пользователь не участвовал в забеге на этой дистанции, поэтому его оценки не принимаются',
				None
			)


@login_required
def add_marks(request, race_id, user_id=None, to_move_to_next_race=False, test_mode=False):
	context = user_edit_vars(request.user)
	context['to_move_to_next_race'] = to_move_to_next_race
	context['test_mode'] = test_mode
	if user_id is None:
		user_id = request.user.id
		for_current_user = True
	else:
		user_id = int(user_id)
		for_current_user = False
		if to_move_to_next_race and (user_id == request.user.id):
			for_current_user = True
			# because for this mode we do not have 2 different urls with and without user

	log_prefix = 'add_marks: race:{}, for_user:{}, to_next_race:{}'.format(
		race_id, user_id, int(to_move_to_next_race)
	)
	if not for_current_user:
		log_prefix += ' by_user:{}'.format(request.user.id)

	log.debug(log_prefix)

	check_res = check_user_rights_for_marks(
		request.user.id, user_id, for_current_user, context['is_admin']
	)
	if check_res != 0:
		log.error(log_prefix + ' ' + check_res)
		raise PermissionDenied

	user = get_object_or_404(User, pk=user_id)
	race = get_object_or_404(Race, pk=race_id)
	event = race.event

	check_res = check_before_add_marks(race.id, user.id, for_current_user)
	if check_res != 0:
		message, redirect_path = check_res
		log.error(
			'{} {}, redirect to: {}'.format(log_prefix, message, redirect_path)
		)
		if redirect_path is None:
			return HttpResponseForbidden('<body><p>403 Forbidden</p><p>' + message + '</p></body>')
		else:
			messages.warning(request, message)
			return redirect(redirect_path)

	parameters = get_params_to_rate_for_race(race.id).only('name', 'description')
	assert len(parameters) > 0
	context.update({
					'page_title': '{}, {}, {}: простановка оценок забегу'.format(event.name, event.dateFull(), race),
					'race' : race,
					'event' : event,
					'series' : event.series,
					'parameters' : parameters,
					'for_user': user,
					'for_current_user': 1 if for_current_user else 0,
					'values': list(range(-1, MAX_RATING_VALUE + 1)),
					'RATING_VALUES_DESCRIPTIONS': RATING_VALUES_DESCRIPTIONS,
		})

	return render(request, 'add_marks.html', context)


def move_to_next_race_helper(request, user_id):
	next_race_id = find_first_race_id_to_rate(user_id)
	if next_race_id is None:
		messages.info(request, 'Вы поставили оценки всем своим забегам. Ура, спасибо!')
		return redirect('results:home')
	else:
		return redirect('starrating:add_marks2_for_user', race_id=next_race_id, user_id=user_id)


@login_required
def save_marks(request):
	context = user_edit_vars(request.user)
	debug_out = ""
	if request.method != 'POST':
		log.error('save_marks: method must be POST, not ' + request.method)
		raise PermissionDenied
	this_user_id = request.user.id
	user_for_marks = int(request.POST['for_user'])
	for_current_user = int(request.POST['for_current_user'])
	race_id = int(request.POST['race_id'])
	to_move_to_next_race = ('to_move_to_next_race' in request.POST)
	test_mode = ('test_mode' in request.POST)

	log_prefix = 'save_marks: race:{}, for_user:{}, to_next_race:{}'.format(
		race_id, user_for_marks, int(to_move_to_next_race)
	)
	if not for_current_user:
		log_prefix += ' by_user:{}'.format(this_user_id)

	if test_mode:
		log_prefix += ' test_mode'

	if for_current_user in (0, 1):
		for_current_user = bool(for_current_user)
	else:
		log.error(
			'{} bad for_current_user value: {}'.format(
				log_prefix, for_current_user
			)
		)
		raise PermissionDenied

	check_res = check_user_rights_for_marks(
		this_user_id, user_for_marks, for_current_user, context['is_admin']
	)
	if check_res != 0:
		log.error(log_prefix + ' ' + check_res)
		raise PermissionDenied

	check_res = check_before_add_marks(race_id, user_for_marks, for_current_user)
	if check_res != 0:
		message, redirect_path = check_res
		log.error(
			'{} {}, redirect to: {}'.format(log_prefix, message, redirect_path)
		)
		if redirect_path is None:
			return HttpResponseForbidden('<body><p>403 Forbidden</p><p>' + message + '</p></body>')
		else:
			messages.warning(request, message)
			return redirect(redirect_path)

	parameters = list(
		get_params_to_rate_for_race(race_id).values_list(
			'pk', flat=True
		)
	)

	marks = {}
	bad_marks = {}
	for par in parameters:
		try:
			value = int(request.POST['q' + str(par)])
		except MultiValueDictKeyError:
			log.error(
				'{}. No mark for parameter {}'.format(log_prefix, par)
			)
			messages.warning(request, "Не все оценки проставлены")
			return redirect(reverse(
					'starrating:add_marks_for_user',
					kwargs={'race_id': race_id, 'user_id': user_for_marks}
					)
				)
		except ValueError:
			log.error(
				'{}. Mark value is not int: {}, par:{}'.format(
					log_prefix,
					repr(request.POST['q' + str(par)]),
					par
				)
			)
			raise
		else:
			if value not in list(range(MAX_RATING_VALUE + 1)):
				bad_marks[par] = value
			else:
				marks[par] = value

	if bad_marks:
		param_dict = queryset_to_dict(Parameter.objects.all(), 'pk')
		param_names = tuple(param_dict[x].name for x in bad_marks)
		log.error(
			'{}. Mark value(s) not in range ({{par:value}}): {}'.format(
				log_prefix, bad_marks
			)
		)
		context['param_names'] = param_names
		# context['param_dict'] = param_dict
		return render(request, 'save_marks_error.html', context)

	non_zero_marks = {k: v for k, v in list(marks.items()) if v != 0}

	if 'show_my_name' in request.POST:
		show_user_name = request.POST['show_my_name']
		if show_user_name == '1':
			show_user_name = True
		else:
			log.error(
				'{}. Ivalid show_my_name value: "{}"'.format(log_prefix, show_user_name)
			)
			raise PermissionDenied
	else:
		show_user_name = False
	review = request.POST['review'].strip()
	if review == '' and show_user_name:
		log.error(log_prefix + '. Review is empty, but show_my_name == 1')
		raise PermissionDenied

	debug_out += "\nshow_my_name: '{}'\n".format(show_user_name)
	debug_out += "review: '{}'\n".format(review)

	try:
		leave_rating(race_id, user_for_marks, request.user, non_zero_marks, review, show_user_name, to_move_to_next_race)
	except Exception as e:
		log.error(
			'{}. Exception on saving. User will be asked to retry. Exception data follows:\n {}: {}'.format(
				log_prefix, type(e).__name__, str(e)
			)
		)
		messages.warning(request, 'К сожалению, что-то пошло не так и нам не удалось сохранить оценки. Попробуйте снова')
		if for_current_user and not to_move_to_next_race:
			return redirect('starrating:add_marks', race_id)
		else:
			if to_move_to_next_race:
				url_name = 'starrating:add_marks2_for_user'
			else:
				url_name = 'starrating:add_marks_for_user'
			return redirect(url_name, race_id=race_id, user_id=user_for_marks)

	if for_current_user:
		if non_zero_marks:
			msg = 'Ваши оценки '
			if review:
				msg += 'и отзыв записаны.'
			else:
				msg += 'записаны.'
		else:
			if review:
				msg = 'Ваш отзыв записан.'
			else:
				msg = None
				log.error(
					'{}. There are neither marks nor review.'.format(log_prefix, )
				)
	else:
		whose = 'пользователя {} (id {})'.format(
			User.objects.get(pk=user_for_marks).get_full_name(), user_for_marks
		)
		if non_zero_marks:
			msg = 'Оценки '
			if review:
				msg += 'и отзыв '
			msg += whose + ' записаны.'
		else:
			if review:
				msg = 'Отзыв {} записан'.format(whose)
			else:
				msg = None
				log.error(
					'{}. There are neither marks nor review.'.format(log_prefix, )
				)

	if to_move_to_next_race and msg:
		msg += ' Переходим к следующему забегу.'

	if msg:
		messages.info(request, 'Спасибо! ' + msg)

	if to_move_to_next_race:
		return move_to_next_race_helper(request, user_for_marks)
	else:
		if for_current_user:
			return redirect('results:home')
		else:
			return redirect('results:user_details', user_for_marks)


@login_required
def abstain(request, race_id, user_id):
	user_id_for_marks = int(user_id)
	context = user_edit_vars(request.user)
	user = get_object_or_404(User, pk=user_id_for_marks)
	race = get_object_or_404(Race, pk=race_id)
	this_user_id = request.user.id
	for_current_user = (this_user_id == user_id_for_marks)


	log_prefix = 'abstain: race:{}, for_user:{}'.format(
		race_id, user_id_for_marks
	)
	if not for_current_user:
		log_prefix += ' by_user:{}'.format(this_user_id)

	log.debug(log_prefix)

	if request.method != 'GET':
		log.error('{}: method must be GET, not {}'.format(log_prefix, request.method))
		raise PermissionDenied

	check_res = check_user_rights_for_marks(
		this_user_id, user_id_for_marks, for_current_user, context['is_admin']
	)
	if check_res != 0:
		log.error(log_prefix + ' ' + check_res)
		raise PermissionDenied

	check_res = check_before_add_marks(race_id, user_id_for_marks, for_current_user)
	if check_res != 0:
		message, redirect_path = check_res
		log.error(
			'{} {}, redirect to: {}'.format(log_prefix, message, redirect_path)
		)
		if redirect_path is None:
			return HttpResponseForbidden('<body><p>403 Forbidden</p><p>' + message + '</p></body>')
		else:
			messages.warning(request, message)
			return redirect(redirect_path)

	leave_rating(
		race_id,
		user_id_for_marks,
		request.user,
		marks=dict(),
		review='',
		show_user_name=False,
		to_move_to_next_race=True,
	)

	return move_to_next_race_helper(request, user_id_for_marks)


@login_required
def postpone_adding_marks(request, user_id):
	user_id_for_marks = int(user_id)
	context = user_edit_vars(request.user)
	log_prefix = 'postpone_adding_marks: for_user:{}'.format(
		user_id_for_marks
	)
	this_user_id = request.user.id
	for_current_user = (user_id_for_marks == request.user.id)
	if not for_current_user:
		log_prefix += ' by_user:{}'.format(this_user_id)

	log.debug(log_prefix)

	check_res = check_user_rights_for_marks(
		this_user_id, user_id_for_marks, for_current_user, context['is_admin']
	)
	if check_res != 0:
		log.error(log_prefix + ' ' + check_res)
		raise PermissionDenied

	lr_postpone_adding_marks(user_id_for_marks)
	messages.info(
		request,
		'Спасибо! Следующий раз мы напомним ' + MSG_WHEN_TO_ASK_TO_LEAVE_RATING
	)
	return redirect('results:home')


@login_required
def stop_adding_marks(request, user_id):
	user_id_for_marks = int(user_id)
	context = user_edit_vars(request.user)
	log_prefix = 'stop_adding_marks: for_user:{}'.format(
		user_id_for_marks
	)
	this_user_id = request.user.id
	for_current_user = (user_id_for_marks == request.user.id)
	if not for_current_user:
		log_prefix += ' by_user:{}'.format(this_user_id)

	log.debug(log_prefix)

	check_res = check_user_rights_for_marks(
		this_user_id, user_id_for_marks, for_current_user, context['is_admin']
	)
	if check_res != 0:
		log.error(log_prefix + ' ' + check_res)
		raise PermissionDenied

	lr_stop_adding_marks(user_id_for_marks)
	return redirect('results:home')


@login_required
def my_marks(request, race_id=None, user_id=None):
	context = user_edit_vars(request.user)
	this_user_id = request.user.id
	if user_id is None:
		user_id = this_user_id
		for_current_user = True
	else:
		for_current_user = False
		user_id = int(user_id)

	race_id = int(race_id)

	log_prefix = 'my_marks: race:{}, for_user:{}'.format(
		race_id, user_id
	)
	if not for_current_user:
		log_prefix += ' by_user:{}'.format(this_user_id)

	check_res = check_user_rights_for_marks(
		this_user_id, user_id, for_current_user, context['is_admin']
	)
	if check_res != 0:
		log.error(log_prefix + ' ' +  check_res)
		raise PermissionDenied

	group_lst = Group.objects.filter(
			race_id=race_id,
			user_id=user_id
		).values_list('pk', flat=True)[:1]
	if not group_lst:
		log.error(log_prefix + '. There is no rating')
		messages.warning(request, "Оценки не поставлены")
		if for_current_user:
			return redirect('starrating:add_marks', race_id=race_id)
		else:
			return redirect('starrating:add_marks_for_user', race_id=race_id, user_id=user_id)

	group_id = group_lst[0]

	return rating_details(request, 'group', group_id)


@group_required('admins')
def parameters(request):
	context =  {
		'qs': Parameter.objects.all(),
		'title': 'Parameter model'
	}
	context['h1'] = context['title']
	return render(request, 'abstract_with_tables2.html', context)


@group_required('admins')
def methods(request):
	context =  {
		'qs': Method.objects.all(),
		'title': 'Method model'
	}
	context['h1'] = context['title']
	return render(request, 'abstract_with_tables2.html', context)


@group_required('admins')
def editor_race_rating_old(request, race_id):
	f_list = ['id', 'user_id', 'user__first_name', 'user__last_name']
	primary_fields = ['value', 'is_hidden', 'parameter']
	prefetch_args = ['primary__{}'.format(f) for f in primary_fields]
	qs = Group.objects.filter(
		race_id=race_id
#	).prefetch_related(    # this does not help
#		*prefetch_args
	).order_by(
		'id'
	).values(*f_list)

#	print prefetch_args

	list_for_table = list(qs)

	parameters = Parameter.objects.all().order_by('order')

	for item in list_for_table:
		for p in parameters:
			fname = 'p{}'.format(p.id)
			try:
				primary = Primary.objects.only(*primary_fields).get(
					group_id=item['id'],
					parameter_id=p.id,
				)
			except Primary.DoesNotExist:
				item[fname] = '-'
			else:
				if primary.is_hidden:
					item[fname] = '({})'.format(primary.value)
				else:
					item[fname] = str(primary.value)

	column_kwargs = {col_name : {}  for col_name in f_list}
	f_list.extend(['p{}'.format(par.id) for par in parameters])
	for par in parameters:
		col_verbose_name = col_name = 'p{}'.format(par.id)
		if not par.to_rate:
			col_verbose_name += 'r'
		if not par.to_show:
			col_verbose_name += 's'
		column_kwargs[col_name] = {'verbose_name': col_verbose_name}

	UserRatingTable = type(
		str('UserRatingTable'),  # It's type must be string, not unicode
		(tables.Table,),
		{col_name : tables.Column(**column_kwargs[col_name]) for col_name in f_list}
	)

	table = UserRatingTable(list_for_table)
	RequestConfig(request).configure(table)
	context =  {
		'qs': table,
		'title': 'User rating for race_id={}'.format(race_id)
	}
	context['h1'] = context['title']

	return render(request, 'editor/starrating/race_marks.html', context)


@group_required('admins')
def editor_rating_details(request, level=None, id_=None):
	context = {}
	groups = Group.objects.order_by('user__last_name')
	if level == 'race':
		context['race'] = get_object_or_404(Race, pk=id_)
		context['event'] = context['race'].event
		context['series'] = context['event'].series
		groups = groups.filter(race=context['race'])
	elif level == 'event':
		context['event'] = get_object_or_404(Event, pk=id_)
		context['series'] = context['event'].series
		groups = groups.filter(race__event=context['event'])
	elif level == 'series':
		context['series'] = get_object_or_404(Series, pk=id_)
		groups = groups.filter(race__event__series=context['series'])
	elif level == 'organizer':
		context['organizer'] = get_object_or_404(Organizer, pk=id_)
		groups = groups.filter(race__event__series__organizer=context['organizer'])
	else:
		# We show all marks
		context['to_show_all_marks'] = True
		groups = Group.objects.order_by('-pk')

	paginator = Paginator(groups, RECORDS_ON_PAGE)
	page = results_util.int_safe(request.GET.get('page', 1))
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

	groups = groups[first_index:last_index + 1]
	group_ids = set(groups.values_list('id', flat=True))

	parameters = Parameter.objects.all().order_by('order')
	parameter_indices = list(parameters.values_list('id', flat=True))
	parameter_indices_rev = {parameter_indices[i]: i for i in range(len(parameter_indices))}

	groups_by_id = {group.id: group for group in groups}
	table = OrderedDict((group, {'marks': ['-'] * len(parameter_indices)}) for group in groups)
	# Here the table is full of dashes. We replace some of them by existing marks

	context['has_marks'] = False
	for primary in Primary.objects.filter(group_id__in=group_ids).select_related('group__race__event__series', 'group__race__distance'):
		context['has_marks'] = True
		value = '({})'.format(primary.value) if primary.is_hidden else str(primary.value)

		table[groups_by_id[primary.group_id]]['marks'][parameter_indices_rev[primary.parameter_id]] = value

	for user_review in User_review.objects.filter(group_id__in=group_ids):
		table[groups_by_id[user_review.group_id]]['review'] = user_review

	context['title'] = 'Все оценки пользователей'
	context['table'] = table
	context['parameters'] = parameters

	return render(request, 'editor/starrating/race_marks.html', context)


chain_field_by_level = dict(
	group=     'group',
	race=      'group__race',
	event=     'group__race__event',
	series=    'group__race__event__series',
	organizer= 'group__race__event__series__organizer',
	root=      'group' # __race__event__series__organizer__root',
)

only_fields = dict(
	distance=['group__race__distance__' + x for x in ('distance_type', 'length', 'name')],
	user=['group__' + x for x in ('created',)],
	race=['group__race__' + x for x in ('distance_real', 'precise_name')],
	event=['group__race__event__' + x for x in ('name',)],
	series=['group__race__event__series__' + x for x in ('name',)],
	organizer=['group__race__event__series__organizer__' + x for x in ('name',)],
	root=[],
	auth_user=['group__user__' + x for x in ('first_name', 'last_name')],
	review=['content', 'show_user_name', 'response']
)

def rating_details(request, level, id_, method=CURRENT_METHOD):
	context = user_edit_vars(request.user)
	if not context['to_show_rating']:
		log.error(
			'rating_details PermissionDenied, level={}, id={}, user={}, is_admin={}'.format(
				level,
				id_,
				request.user.id,
				context['is_admin'],
			)
		)
		raise PermissionDenied

	if request.user.id == 1:
		messages.success(request, f'level: {level}')
	context['level'] = level
	if level == 'root' and not context['is_admin']:
		raise PermissionDenied

	if level == 'group':
		rated_model = get_model_by_name('starrating.Group')
		context['level_no'] = 1
	else:
		rated_model = get_model_by_name(level.title())
		context['level_no'] = LEVEL_NAME_TO_NO[level.title()]

	rated = get_object_or_404(rated_model, pk=id_)
	context[level] = context['rated'] = rated

	context['sr_overall'] = get_sr_overall_data(rated, context['to_show_rating'])
	context['sr_by_param'] = get_sr_by_param_data(rated, context['to_show_rating'])

	if level == 'group':
		context['review'] = User_review.objects.filter(pk=id_).first()

	if level == 'group':
		level_no = 1
	else:
		level_no = LEVEL_NAME_TO_NO[level.title()]
	only_list = reduce(
		lambda x, y: x + y,
		[only_fields[LEVEL_NO_TO_NAME[i].lower()] for i in range(1, level_no + 1)],
		[]
	) + only_fields['distance'] + only_fields['auth_user'] + only_fields['review']

	context['debug_only_list'] = only_list

	if level == 'root':
		User_review_filtered = User_review.objects.all()
	else:
		User_review_filtered = User_review.objects.filter(
		**{chain_field_by_level[level] + '_id' : id_}
		)

	context['page_title'] = str(rated)  # TODO

	reviews = User_review_filtered.select_related(
		'group',
		'group__user',
		'group__race__distance',
		chain_field_by_level[level],
	).only(
		*only_list
	).order_by(
		'-group__created'
	).annotate(
		sum_value=Subquery(
			User_overall.objects.filter(
				method=method,
				rated_id=OuterRef('pk')
			).values_list('sum_int')
		),
		weight=Subquery(
			User_overall.objects.filter(
				method=method,
				rated_id=OuterRef('pk')
			).values_list('weight')
		),
	)

	return paginate_and_render(request, 'starrating/race_marks.html', context, reviews)

@group_required('admins')
def group_delete(request, group_id):
	group = get_object_or_404(Group, pk=group_id)
	race = group.race
	delete_group(request.user, group)
	messages.success(request, 'Оценка успешно удалена')
	return redirect('starrating:editor_rating_details', level='race', id_=race.id)
