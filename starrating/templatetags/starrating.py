from django.utils.timezone import now
from django import template
from django.urls import reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from math import trunc

from results.models import Race, Event, Series, Organizer, DEFAULT_WHEN_TO_ASK_FILL_MARKS
from .. models import Group

from .. constants import LEVELS_LIST, LEVEL_NAME_TO_NO, MAX_RATING_VALUE, \
	FULL_STAR, EMPTY_STAR, HALF_STAR, ADMIN_CAN_LEAVE_RATING_FOR_ANY_USER

register = template.Library()

from ..aggr.aggr_utils import get_parent_object
from ..utils.show_rating import get_sr_overall_data
from ..utils.leave_rating import find_first_race_id_to_rate


def value_to_stars(value):
	if not ((1 <= value <= MAX_RATING_VALUE) or (0 <= value < 0.00000001)):
		return ''
	rounded_value = trunc((value * 2) + 0.5)
	n_full_stars = rounded_value // 2
	n_half_stars = rounded_value % 2
	n_empty_stars = MAX_RATING_VALUE - n_full_stars - n_half_stars

	out_str = FULL_STAR * n_full_stars + HALF_STAR * n_half_stars + EMPTY_STAR * n_empty_stars

	if value < 1:
		out_str = '<span style="color:gray">{}</span>'.format(out_str)

	return mark_safe(out_str)


@register.filter
def as_stars(value):
	return value_to_stars(value)


@register.simple_tag(takes_context=True)
def overall_rating(context, sr_data, show_link_to_details):
	# sr_data should be a dict returned by starrating.utils.show_rating.get_sr_data
	if not sr_data:
		return ''

	out_str = format_html(
		'<p><span style="color:orange">{} {}',
		value_to_stars(sr_data['avg']),
		'{:.1f}'.format(sr_data['avg']),
		# ' ({}/{})'.format(sr_data['sum_val'], sr_data['weight']) if context['is_admin'] else '',
	)

	if sr_data['level'] == 'group':
		out_str += mark_safe('</span>')
	else:
		out_str += format_html(
			', число оценивших&nbsp;—&nbsp;{} </span>',
			# because of {%spaceless%} space ^ must be within html tags
			sr_data['user_count']
		)

	if sr_data['level'] == 'group' or not show_link_to_details:
		return out_str + mark_safe('</p>')

	out_str += mark_safe(' ')
	out_str += format_html(
		' <a href="{}">(подробнее)</a>',
		reverse(
			'starrating:rating_details',
			kwargs=dict(level=sr_data['level'], id_=sr_data['id'])
		)
	)

	if context.get('is_admin') and (sr_data['level'] != 'group'):
		out_str += format_html(
			'&nbsp;<a href="{}"><span class="for-admin">все&nbsp;оценки</span></a>&nbsp;',
			reverse(
				'starrating:editor_rating_details',
				kwargs=dict(level=sr_data['level'], id_=sr_data['id'])
			)
		)

	return out_str + mark_safe('</p>')

# obj can be organizer, series, event, race
@register.simple_tag(takes_context=True)
def show_overall_rating(context, obj, show_link_to_details):
	return overall_rating(context, get_sr_overall_data(obj, True), show_link_to_details)

def rating_in_results_table(obj, arg):
	assert arg in ('admin', 'homepage')

	reverse_kwargs = dict(race_id=obj.race_id)
	if arg == 'admin':
		reverse_kwargs['user_id'] = obj.user_id
		my_marks_name = 'starrating:my_marks_for_user'
		add_marks_name = 'starrating:add_marks_for_user'
	else:
		my_marks_name = 'starrating:my_marks'
		add_marks_name = 'starrating:add_marks'

	if obj.sr_group_is_empty is None:
		if obj.is_race_new or obj.is_user_new:
			if arg == 'admin' and not ADMIN_CAN_LEAVE_RATING_FOR_ANY_USER:
				out_str = 'Пока нет'
			else:
				out_str = format_html(
					'<a href="{}">Оценить</a>',
					reverse(add_marks_name, kwargs=reverse_kwargs)
				)
		else:
			out_str = mark_safe('Поздно оценивать')
	elif obj.sr_group_is_empty == False:
		if not obj.sum_value:
			out_str = mark_safe('Оценка в процессе обработки...')
		else:
			avg_value = float(obj.sum_value)/obj.weight
			out_str = format_html(
				'<a href="{}">{} {}{}</a>',
				reverse(my_marks_name, kwargs=reverse_kwargs),
				value_to_stars(avg_value),
				'{:.1f}'.format(avg_value),
				' ({}/{})'.format(obj.sum_value, obj.weight) if arg == 'admin' else ''
			)
	else:
		assert obj.sr_group_is_empty == True
		if obj.sr_user_review_id is None:
			out_str = mark_safe('Оценка не поставлена')
		else:
			out_str = format_html(
				'<a href="{}">Только отзыв</a>',
				reverse(my_marks_name, kwargs=reverse_kwargs)
			)

	return out_str


@register.simple_tag(takes_context=True)
def user_overall_rating(context, sum_val, weight):
	if not weight:
		return ''

	avg = float(sum_val) / weight

	return format_html(
		'<span style="color:orange">{} {}{}</span>',
		mark_safe(value_to_stars(avg)),
		'{:.1f}'.format(avg),
		' ({}/{})'.format(sum_val, weight) if context['is_admin'] else '',
	)


def parent(node):
	assert isinstance(node, (Group, Race, Event, Series, Organizer))
	return get_parent_object(node)

def node2str(node):
	if isinstance(node, Event):
		return '{}, {}'.format(node.name, node.date())
	return str(node)

@register.simple_tag
def node_verbose_name(node, context_level):
	assert isinstance(node, (Group, Race, Event, Series, Organizer))
	assert context_level in LEVELS_LIST
	if isinstance(node, Group):
		level_no = 1
	else:
		level_no = LEVEL_NAME_TO_NO[type(node).__name__]

	if level_no >= context_level:
		return ''

	chain = []
	current_node = node

	debug_out = str(context_level) + ' '

	while LEVEL_NAME_TO_NO[type(current_node).__name__] != context_level:
		debug_out += type(current_node).__name__ + ' '
		chain.append(node2str(current_node))
		current_node = parent(current_node)

	out_str = ', '.join(chain[::-1])
	url_str = reverse(
		'results:{}_details'.format(type(node).__name__.lower()),
		args=[node.pk]
	)

	return format_html('(отзыв на <a href={}>{}</a>)', url_str, out_str)


@register.simple_tag(takes_context=True)
def rating_in_results_table_header(context):
	if not context['to_show_rating']:
		return ''

	if context.get('is_user_homepage'):
		text = 'Ваша оценка забегу'
	elif context.get('user_page') and context['is_admin']:
		text = 'Оценка участника забегу'
	else:
		return ''

	return format_html('<th class="no-sort text-center">{}</th>', text)


@register.simple_tag(takes_context=True)
def rating_in_results_table_data(context, result):
	if not context['to_show_rating']:
		return ''

	if context.get('is_user_homepage'):
		text = rating_in_results_table(result, 'homepage')
	elif context.get('user_page') and context['is_admin']:
		text = rating_in_results_table(result, 'admin')
	else:
		return ''

	return format_html('<td class="text-center">{}</td>', text)


@register.simple_tag(takes_context=True)
def button_for_rate_all_available_races(context):
	if not context['to_show_rating']:
		return ''

	if not (
			context.get('is_user_homepage')
			or
			(context['is_admin'] and ADMIN_CAN_LEAVE_RATING_FOR_ANY_USER)
		):
		return ''

	profile = context['profile']
	if not profile.to_ask_fill_marks or now().date() < profile.when_to_ask_fill_marks:
		return ''

	if profile.when_to_ask_fill_marks == DEFAULT_WHEN_TO_ASK_FILL_MARKS:
		message = 'Поставьте оценки забегам, в которых вы участвовали'
	else:
		message = 'Продолжите оценивать забеги, в которых вы участвовали'

	user_id = context['user'].id
	race_id = find_first_race_id_to_rate(user_id)

	if race_id is None:
		return ''

	return format_html(
		'<div class="alert alert-warning text-center" role="alert"><strong><a href="{}" class="underlined">{}</a></strong></div>',
		reverse(
			'starrating:add_marks2_for_user',
			kwargs=dict(user_id=user_id, race_id=race_id),
		),
		message,
	)
