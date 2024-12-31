from django.template.defaultfilters import stringfilter
from django.contrib.auth.models import Group
from django import template

from results import models, models_klb, results_util

register = template.Library()

@register.filter
def is_checkbox(field):
	return field.field.widget.__class__.__name__ == 'CheckboxInput'

@register.filter
def is_radio(field):
	return field.field.widget.__class__.__name__ == 'RadioSelect'

@register.filter
def is_multicheckbox(field):
	return field.field.widget.__class__.__name__ == 'CheckboxSelectMultiple'

@register.filter
def klass(field):
	return field.field.widget.__class__.__name__

@register.filter(is_safe=True)
def label_with_classes(value, arg):
	return value.label_tag(attrs={'class': arg})

@register.filter(is_safe=True)
def label_with_col_classes(value, arg):
	return value.label_tag(attrs={'class': "col-sm-{} control-label".format(arg)})

@register.filter(is_safe=True)
def has_posts_in_social_page(news, page):
	return news.social_post_set.filter(social_page=page).exists()

@register.filter
@stringfilter
def add_prefix(value):
	if value and (value[:4] != "http"):
		return '{}/{}'.format(results_util.SITE_URL, value)
	return value

@register.filter
def has_group(user, group_name):
	return (Group.objects.filter(name=group_name).first() in user.groups.all()) if user else False

@register.filter
def secs2time(value):
	return models.secs2time(value)

@register.filter
def centisecs2time(value, round_hundredths=False):
	return models.centisecs2time(value, round_hundredths)

@register.filter
def date_rus(value):
	return results_util.date2str(value, with_nbsp=False)

@register.filter
def subtract(value, arg):
	return value - arg

@register.filter
def pace(value):
	seconds = value % 60
	minutes = value // 60
	return '{}:{}/km'.format(minutes, str(seconds).zfill(2))

@register.filter
def inverse(value):
	return -value

@register.filter
def div(value, arg):
	return value // arg

@register.filter(is_safe=True)
def label_with_classes(value, arg):
	return value.label_tag(attrs={'class': arg})

@register.filter
def get_team(runner, year):
	return runner.klb_person.get_team(year) if (runner and runner.klb_person) else None

@register.filter(is_safe=True)
def get_social_url(auth):
	if auth.provider == 'vk-oauth2':
		return 'https://vk.com/id{}'.format(auth.uid)
	if auth.provider == 'twitter':
		return 'https://twitter.com/intent/user?user_id={}'.format(auth.uid)
	return ''

@register.filter(is_safe=True)
def get_social_editor_url(auth):
	return '/admin/social_django/usersocialauth/{}/change/'.format(auth.id)
	
@register.simple_tag
def get_verbose_field_name(instance, field_name):
	return instance._meta.get_field(field_name).verbose_name
	
@register.filter
def wo_last_word(value):
	return ' '.join(value.split()[:-1])

@register.filter
def wo_first_and_last_word(value):
	return ' '.join(value.split()[1:-1])
	
@register.filter
def shorten_weekly_event_name(value):
	parts = value.split()
	if parts[-1][0] == '№':
		parts = parts[:-1]
	return ' '.join(parts)
	
@register.filter
def percent(whole, part): # For e.g. 'с трёх забегов'
	if (whole > 0) and (part is not None):
		return min(100, int(part * 100 / whole))
	return 100

@register.filter
def age_on_event(runner, event):
	return results_util.get_age_on_date(event.start_date, runner.birthday)

@register.filter
def ending(value, word_type):
	return results_util.ending(value, word_type)

@register.filter
def year_for_klbmatch(value):
	return models_klb.year_string(value)

@register.filter
def last_day_to_pay(year):
	return models_klb.get_last_day_to_pay(year)

@register.filter
def format_date_for_match(value):
	if value.year in (2020, 2021):
		return value.strftime('%d.%m.%Y')
	return value.strftime('%d.%m')

@register.filter(is_safe=True)
def case(value, arg):
	if arg == 'dative':
		return results_util.months_dative_case[value]
	return value

@register.filter
def encode_slashes(value):
	return results_util.encode_slashes(value)
