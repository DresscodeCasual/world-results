from collections import OrderedDict
from calendar import monthrange
import datetime
import decimal
import bleach
import time
import os
import io
from PIL import Image
import re
from typing import Any, Dict, List, Optional, Tuple

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.gis.db import models as gis_models
from django.core import mail
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.mail import EmailMultiAlternatives, send_mail
from django.core.validators import validate_email, MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q, F, Max, Count
from django.db.models.signals import pre_delete
from django.dispatch import receiver
from django.forms import SplitDateTimeField
from django.urls import reverse
from django.utils import timezone


from . import custom_fields
from . import links, models_klb, results_util
from .transliteration_v5 import transliterate

import starrating.aggr.race_deletion

ADMIN_ID = 1

INFO_WARNING_MAIL= f'info+warning@{settings.MAIN_HOST}'
SITE_NAME = 'World Results'

# Letters with this header will NOT reach Asana when sent to info@
INFO_MAIL_HEADER = f'{SITE_NAME} <{settings.EMAIL_INFO_USER}>'
# This should be different from info@ for these letters to reach Asana
ROBOT_MAIL_HEADER = f'World Results Robot <{settings.EMAIL_HOST_USER}>'

LOG_FILE_SOCIAL = results_util.LOG_DIR / 'social_networks.log'
LOG_PANIC_EMAILS = results_util.LOG_DIR / 'panic_emails.log'

try:
	USER_ADMIN = get_user_model().objects.get(pk=ADMIN_ID)
	USER_ROBOT_CONNECTOR = get_user_model().objects.get(pk=3)
except:
	USER_ADMIN = None
	USER_ROBOT_CONNECTOR = None

CLUB_ID_FOR_ADMINS = 88 # Элара
SAMPLE_EDITOR_ID = 53 # https://probeg.org/user/53/

DATE_MIN = datetime.date(1896, 1, 1)
DATE_MAX = datetime.date(datetime.date.today().year + 50, 12, 31)

MAX_URL_LENGTH = 600

today = datetime.date.today()

MIN_RUNNER_AGE = 0
MAX_RUNNER_AGE = 120

VK_POSSIBLE_PREFIXES = ('http://vk.com/', 'http://www.vk.com/', 'https://vk.com/', 'https://www.vk.com/', )
FB_POSSIBLE_PREFIXES = ('http://facebook.com/', 'http://www.facebook.com/', 'https://facebook.com/', 'https://www.facebook.com/', )
IN_POSSIBLE_PREFIXES = ('http://instagram.com/', 'http://www.instagram.com/', 'https://instagram.com/', 'https://www.instagram.com/', )
TG_POSSIBLE_PREFIXES = ('https://t.me/', )

def secs2time(value: int, fill_hours: bool=True) -> str:
	seconds = value % 60
	value //= 60
	minutes = value % 60
	value //= 60
	hours = value
	return (str(hours).zfill(2) if fill_hours else str(hours)) + ':' + str(minutes).zfill(2) + ':' + str(seconds).zfill(2)

def centisecs2time(value: int, round_hundredths: bool=False, show_zero_hundredths: bool=False, timing: Optional[int]=None) -> str:
	hundredths_digit = value % 10
	value //= 10
	tenths_digit = value % 10
	value //= 10

	if (tenths_digit or hundredths_digit) and round_hundredths:
		hundredths_digit = 0
		tenths_digit = 0
		value += 1

	seconds = value % 60
	value //= 60
	minutes = value % 60
	value //= 60
	hours = value
	res = str(hours) + ':' + str(minutes).zfill(2) + ':' + str(seconds).zfill(2)

	if round_hundredths:
		return res
	if hundredths_digit or show_zero_hundredths or (timing == TIMING_ELECTRONIC):
		return res + ',' + str(tenths_digit * 10 + hundredths_digit).zfill(2)
	if tenths_digit or (timing == TIMING_HAND):
		return res + ',' + str(tenths_digit)
	return res
def tuple2centiseconds(hours: int, minutes: int, seconds: int, centiseconds: int = 0) -> int:
	return ((hours * 60 + minutes) * 60 + seconds) * 100 + centiseconds
def string2centiseconds(result: str) -> int:
	res = re.match(r'^(\d{1,3}):(\d{1,2}):(\d{1,2})$', result) # Hours:minutes:seconds
	if res:
		hours = int(res.group(1))
		minutes = int(res.group(2))
		seconds = int(res.group(3))
		if (minutes < 60) and (seconds < 60):
			return tuple2centiseconds(hours, minutes, seconds)
	res = re.match(r'^(\d{1,2}):(\d{1,2})$', result) # minutes:seconds
	if res:
		minutes = int(res.group(1))
		seconds = int(res.group(2))
		if (minutes < 60) and (seconds < 60):
			return tuple2centiseconds(0, minutes, seconds)
	res = re.match(r'^(\d{1,2}):(\d{1,2}):(\d{1,2})[\.,](\d{1,2})$', result) # Hours:minutes:seconds[.,]centiseconds
	if res:
		hours = int(res.group(1))
		minutes = int(res.group(2))
		seconds = int(res.group(3))
		centiseconds = int(res.group(4))
		if len(res.group(4)) == 1:
			centiseconds *= 10
		if (minutes < 60) and (seconds < 60):
			return tuple2centiseconds(hours, minutes, seconds, centiseconds)
	res = re.match(r'^(\d{1,2})[\.:,](\d{1,2})[\.,](\d{1,2})$', result) # minutes[:.,]seconds[.,]centiseconds
	if res:
		minutes = int(res.group(1))
		seconds = int(res.group(2))
		centiseconds = int(res.group(3))
		if len(res.group(3)) == 1:
			centiseconds *= 10
		if (minutes < 60) and (seconds < 60):
			return tuple2centiseconds(0, minutes, seconds, centiseconds)
	res = re.match(r'^(\d{1,2})[\.,](\d{1,2})$', result) # seconds[.,]centiseconds
	if res:
		seconds = int(res.group(1))
		centiseconds = int(res.group(2))
		if len(res.group(2)) == 1:
			centiseconds *= 10
		if seconds < 60:
			return tuple2centiseconds(0, 0, seconds, centiseconds)
	return 0

def meters2string(length, with_nbsp=True):
	if length:
		separator = '&nbsp;' if with_nbsp else ' '
		return f'{length}{separator}м'
	return ''

def total_length2string(length, with_nbsp=True):
	if length:
		res = []
		meters = length % 1000
		kilometers = length // 1000
		separator = '&nbsp;' if with_nbsp else ' '
		if kilometers:
			res.append(f'{kilometers}{separator}км')
		if meters:
			res.append(f'{meters}{separator}м')
		return ' '.join(res)
	return ''
def total_time2string(centiseconds, with_br=True):
	if centiseconds:
		value = centiseconds
		hundredths = value % 100
		value //= 100
		seconds = value % 60
		value //= 60
		minutes = value % 60
		value //= 60
		hours = value % 24
		days = value // 24
		time_str = f'{str(hours).zfill(2)}:{str(minutes).zfill(2)}:{str(seconds).zfill(2)}'
		if hundredths:
			time_str += ',' + str(hundredths).zfill(2)
		res = []
		if days:
			days_form = 'сутки' if (days == 1) else 'суток'
			res.append(f'{days} {days_form}')
		res.append(time_str)
		return ('<br/>' if with_br else ' ').join(res)
	return ''

def is_admin(user):
	return user.groups.filter(name='admins').exists() if user else False

def replace_symbols(s):
	res = s
	for s_old, s_new in [(' - ', ' — '), ('<<', '«'), ('>>', '»'), ('&lt;&lt;', '«'), ('&gt;&gt;', '»'), (' ,', ','), (' .', '.')]:
		res = res.replace(s_old, s_new)
	return results_util.fix_quotes(res)

MAX_EMAIL_LENGTH = 100
def is_email_correct(email):
	try:
		validate_email(email)
		return len(email) <= MAX_EMAIL_LENGTH
	except:
		return False

MAX_PHONE_NUMBER_LENGTH = 50
MAX_POSTAL_ADDRESS_LENGTH = 200
def is_phone_number_correct(phone):
	if not isinstance(phone, str):
		return False
	if re.match(r'^[\+8][0123456789 -–—\(\)]{10,19}$', phone) is None:
		return False
	return 10 <= sum(c.isdigit() for c in phone) <= 15

def get_runner_ids_for_user(user): # Returns the set with all runners' id that belong to clubs runned by user
	club_ids = set(user.club_editor_set.values_list('club_id', flat=True))
	return set(Club_member.objects.filter(club_id__in=club_ids).values_list('runner_id', flat=True))

def make_thumb(image_field, thumb_field, max_width, max_height):
	if not image_field:
		if thumb_field:
			thumb_field.delete()
		return True
	image_path, image_ext = os.path.splitext(image_field.path)
	ext_cleaned = image_ext[1:].lower()
	if ext_cleaned in ['jpg', 'jpeg']:
		PIL_TYPE = 'jpeg'
		FILE_EXTENSION = 'jpg'
	elif ext_cleaned == 'png':
		PIL_TYPE = 'png'
		FILE_EXTENSION = 'png'
	elif ext_cleaned == 'gif':
		PIL_TYPE = 'gif'
		FILE_EXTENSION = 'gif'
	else:
		return False

	# from https://stackoverflow.com/questions/23922289/django-pil-save-thumbnail-version-right-when-image-is-uploaded
	image = Image.open(image_field)
	image.thumbnail((max_width, max_height), Image.ANTIALIAS)
	thumb_temp = io.BytesIO()
	try:
		image.save(thumb_temp, PIL_TYPE)
	except OSError: # If 'cannot write mode RGBA as JPEG' happens
		image_rgb = image.convert('RGB')
		image_rgb.save(thumb_temp, PIL_TYPE)
	thumb_temp.seek(0)

	thumb_path = f'{image_path}_thumb.{FILE_EXTENSION}'
	thumb_field.save(thumb_path, ContentFile(thumb_temp.read()), save=True)
	thumb_temp.close()
	return True

def write_log(s, debug=False):
	try:
		with io.open(results_util.LOG_FILE_ACTIONS, 'a', encoding='utf8') as f:
			f.write(s + '\n')
	except:
		print(f'Could not log the string "{s}"!')
	if debug:
		print(s)
	return s

def send_panic_email(subject: str, body: str, to_all: bool=False, to_top: bool=False):
	if to_all:
		target = INFO_WARNING_MAIL
	# elif to_top:
	# 	target = TOP_WARNING_MAIL
	else:
		target = 'alexey.chernov@gmail.com'
	with io.open(LOG_PANIC_EMAILS, 'a', encoding='utf8') as f:
		f.write(f'\n\n\n{datetime.datetime.now()}\n{subject}\n{body}')
	try:
		USE_PANIC_ADDRESS = False
		if USE_PANIC_ADDRESS:
			# panic@ is now banned too :(
			# with mail.get_connection(username=f'panic@{settings.MAIN_HOST}', password=settings.PANIC_PASSWORD) as connection:
			with results_util.get_connection(EMAIL_INFO_USER) as connection:
				send_mail(
					subject,
					f'{body}\n\n Your robot',
					f'panic@{settings.MAIN_HOST}',
					[target],
					fail_silently=False,
					connection=connection,
				)
		else:
			send_mail(
				subject,
				f'{body}\n\n Your robot',
				settings.EMAIL_HOST_USER,
				[target],
				fail_silently=True,
			)
	except:
		pass

# Updates the fields of any model object, if t_json has different values from current.
# Returns whether at least one field changed.
def update_obj_if_needed(obj, t_json, comment='') -> bool:
	needs_to_save = False
	table_update = None
	for field in obj.__class__._meta.get_fields():
		for field_name in (field.name, field.name + '_id'):
			if field_name in t_json:
				json_value = t_json[field_name]
				if (json_value is None) and (field.__class__.__name__ == 'CharField'):
					json_value = ''
				if getattr(obj, field_name) != json_value:
					if table_update is None:
						table_update = Table_update.objects.create(
							model_name=obj.__class__.__name__,
							row_id=obj.id,
							action_type=ACTION_UPDATE,
							comment=comment
						)
					Field_update.objects.create(
						table_update=table_update,
						field_name=field_name,
						new_value=json_value or '',
					)
					setattr(obj, field_name, json_value)
					needs_to_save = True
	if needs_to_save:
		obj.save()
	return needs_to_save

# Should be enough in most cases.
# Returns whether the object was changed.
def update_obj_if_needed_simple(obj, new_vals: dict[str, any], user=USER_ROBOT_CONNECTOR, comment: str='') -> bool:
	updated_fields = []
	for key, val in new_vals.items():
		if getattr(obj, key) != val:
			updated_fields.append(key)
			setattr(obj, key, val)
	if updated_fields:
		obj.save()
		log_obj_create(user, obj, ACTION_UPDATE, field_list=updated_fields, verified_by=user)
		return True
	return False

class CustomDateTimeField(models.DateTimeField):
	def formfield(self, **kwargs):
		defaults = {'form_class': SplitDateTimeField,
					'input_date_formats': ['%d.%m.%Y']}
		defaults.update(kwargs)
		return super().formfield(**defaults)

DEFAULT_COUNTRY_SORT_VALUE = 10
class Country(models.Model):
	id = models.CharField(verbose_name='id (домен первого уровня)', max_length=3, primary_key=True)
	name = models.CharField(verbose_name='Название', max_length=50, db_index=True)
	value = models.SmallIntegerField(verbose_name='Приоритет при сортировке', default=DEFAULT_COUNTRY_SORT_VALUE)
	code = models.CharField(verbose_name='Трёхбуквенный код', max_length=3, db_index=True)
	has_regions = models.BooleanField(verbose_name='Есть ли регионы страны в БД', default=False)
	class Meta:
		indexes = [
			models.Index(fields=['value', 'name']),
		]
	def __str__(self):
		return self.name

class District(models.Model):
	""" Федеральные округи и их аналоги. Пока будут только в России """
	country = models.ForeignKey(Country, verbose_name='Страна', default='RU', on_delete=models.PROTECT)
	name = models.CharField(verbose_name='Название на английском', max_length=100, db_index=True)
	name_orig = models.CharField(verbose_name='Название на языке страны, где находится', max_length=100)
	class Meta:
		verbose_name = 'Федеральный округ в России'
		constraints = [
			models.UniqueConstraint(fields=['country', 'name'], name='district_country_name'),
		]
		indexes = [
			models.Index(fields=['country', 'name_orig']),
		]
	def __str__(self):
		return self.name

class Region(models.Model):
	country = models.ForeignKey(Country, verbose_name='Страна', on_delete=models.PROTECT)
	district = models.ForeignKey(District, verbose_name='Федеральный округ', default=None, null=True, on_delete=models.PROTECT)
	name = models.CharField(verbose_name='Название на английском', max_length=60, db_index=True)
	name_orig = models.CharField(verbose_name='Название на языке страны, где находится', max_length=100, default='')
	is_active = models.BooleanField(verbose_name='Существует ли сейчас', default=True)
	population = models.IntegerField(verbose_name='Население', default=None, null=True)
	class Meta:
		constraints = [
			models.UniqueConstraint(fields=['country', 'name'], name='region_country_name'),
		]
		indexes = [
			models.Index(fields=['country', 'is_active', 'name']),
			models.Index(fields=['country', 'is_active', 'name_orig']),
		]
	def __str__(self):
		return self.name

class City(models.Model):
	region = models.ForeignKey(Region, verbose_name='Регион (для России, Украины, Беларуси)', on_delete=models.PROTECT)
	raion = models.CharField(verbose_name='Для маленьких населённых пунктов: Район, округ, улус, повят, уезд, county', max_length=100, blank=True)
	city_type = models.CharField(verbose_name='Для маленьких населённых пунктов: Тип населённого пункта', max_length=100, blank=True)
	name = models.CharField(verbose_name='Название на английском', max_length=100, db_index=True)
	name_orig = models.CharField(verbose_name='Название на языке оригинала', max_length=100, db_index=True, blank=True)
	url_wiki = models.URLField(verbose_name='Ссылка на страницу в Википедии', max_length=200, blank=True)
	skip_region = models.BooleanField(verbose_name='Крупный город, не показывать регион, даже если он указан', default=False)
	geo = gis_models.PointField(verbose_name='Координаты центра города', geography=True, default=None, null=True) # Возможно, пара DecimalField(max_digits=22, decimal_places=16) будет практичнее
	population = models.IntegerField(verbose_name='Население', default=None, null=True)
	simplemaps_id = models.IntegerField(verbose_name='ID на сайте simplemaps.com', default=None, null=True, unique=True)
	created_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name='Создал город в базе', related_name='city_created_set',
		on_delete=models.SET_NULL, default=None, null=True, blank=True)
	added_time = models.DateTimeField(verbose_name='Время занесения в БД', auto_now_add=True)
	def clean(self):
		self.raion = self.raion.strip()
		self.city_type = self.city_type.strip()
		self.name = self.name.strip()
		self.name_orig = self.name_orig.strip()
	class Meta:
		indexes = [
			models.Index(fields=['region', 'name']),
			models.Index(fields=['region', 'raion', 'city_type', 'name']),
			models.Index(fields=['region', 'name_orig']),
		]
		constraints = [
			models.UniqueConstraint(fields=['region', 'raion', 'name'], name='region_raion_name'),
		]
	def name_full(self, with_region=False, with_nbsp=True): # This adds region only when city is small, i.e. self.raion != ''
		if self.skip_region:
			return self.name
		res = ''
		if with_region and self.region.is_active and (self.raion or not self.skip_region):
			res += self.region.name + ', '
		if self.raion:
			res += self.raion + ', '
		if self.city_type:
			res += self.city_type + ('&nbsp;' if with_nbsp else ' ')
		res += self.name
		return res
	def nameWithCountry(self, with_region=True, with_nbsp=True):
		res = self.name_full(with_region=with_region, with_nbsp=with_nbsp)
		if (not self.region.is_active) and self.name_orig:
			res += ' (' + self.name_orig + ')'
		res = self.region.country.name + ', ' + res
		return res
	# Examples:
	# Санкт-Петербург – Москва (Россия, так что страну не пишем)
	# Санкт-Петербург (Россия) – Нью-Йорк (США) (страны разные, так что пишем обе)
	# Лос-Анжелес – Нью-Йорк (США) (страна одна, пишем её только в конце)
	# Павлоград (Украина)
	# Санкт-Петербург
	def nameWithFinish(self, city_finish, with_nbsp=True):
		if city_finish:
			if self.region.country == city_finish.region.country:
				return self.name_full(with_nbsp=with_nbsp) + ' – ' + city_finish.nameWithCountry(with_nbsp=with_nbsp)
			return self.nameWithCountry(with_nbsp=with_nbsp) + ' – ' + city_finish.nameWithCountry(with_nbsp=with_nbsp)
		# So start=finish
		return self.nameWithCountry(with_nbsp=with_nbsp)
	def get_name_for_ajax_select(self):
		return self.nameWithCountry(with_nbsp=False) # TODO
	def NameForEditorAjax(self) -> str:
		details = [self.region.country.name]
		if self.region.name != self.region.country.name:
			details.append(self.region.name)
		if self.raion:
			details.append(self.raion)
		if self.population:
			details.append(f'population: {self.population}')
		return f'{self.name} ({", ".join(details)})'
	def has_dependent_objects(self):
		return self.series_city_set.exists() or self.series_city_finish_set.exists() or \
			self.event_city_set.exists() or self.event_city_finish_set.exists() or self.user_profile_set.exists() or \
			self.club_set.exists() or self.city_conversion_set.exists() or self.result_set.exists() or \
			self.runner_set.exists()
	def get_reverse_url(self, target):
		return reverse(target, kwargs={'city_id': self.id})
	def get_editor_url(self):
		return self.get_reverse_url('editor:city_details')
	def get_history_url(self):
		return self.get_reverse_url('editor:city_changes_history')
	def get_races_url(self):
		return self.get_reverse_url('results:races')
	def __str__(self):
		return self.name

class Country_conversion(models.Model):
	country = models.ForeignKey(Country, on_delete=models.PROTECT)
	country_raw = models.CharField(max_length=50, db_index=True, unique=True)
	class Meta:
		verbose_name = 'Соответствие между написаниями стран и странами в БД'

class Region_conversion(models.Model):
	country = models.ForeignKey(Country, default=None, null=True, on_delete=models.PROTECT)
	region = models.ForeignKey(Region, default=None, null=True, on_delete=models.PROTECT)
	country_raw = models.CharField(max_length=50, blank=True)
	district_raw = models.CharField(max_length=50, blank=True)
	region_raw = models.CharField(max_length=60, blank=True)
	class Meta:
		verbose_name = 'Соответствие между написаниями регионов и регионами в БД. Не используется'
		indexes = [
			models.Index(fields=['country_raw', 'region_raw']),
		]
		constraints = [
			models.UniqueConstraint(fields=['country_raw', 'district_raw', 'region_raw'], name='country_district_region'),
		]

class City_conversion(models.Model):
	country = models.ForeignKey(Country, default=None, null=True, on_delete=models.PROTECT)
	region = models.ForeignKey(Region, default=None, null=True, on_delete=models.PROTECT)
	city = models.ForeignKey(City, default=None, null=True, on_delete=models.PROTECT)
	country_raw = models.CharField(max_length=50, blank=True)
	district_raw = models.CharField(max_length=50, blank=True)
	region_raw = models.CharField(max_length=60, blank=True)
	city_raw = models.CharField(max_length=40, blank=True)
	class Meta:
		verbose_name = 'Соответствие между написаниями городов и городами в БД. Не используется'
		indexes = [
			models.Index(fields=['region_raw', 'city_raw']),
		]
		constraints = [
			models.UniqueConstraint(fields=['country_raw', 'district_raw', 'region_raw', 'city_raw'], name='country_district_region_city'),
		]

def validate_social_urls(obj):
	if hasattr(obj, 'url_vk') and obj.url_vk and not obj.url_vk.startswith(VK_POSSIBLE_PREFIXES):
		raise ValidationError({'url_vk': 'VK address must start with ' + ', '.join(VK_POSSIBLE_PREFIXES)})
	if hasattr(obj, 'url_facebook') and obj.url_facebook and not obj.url_facebook.startswith(FB_POSSIBLE_PREFIXES):
		raise ValidationError({'url_facebook': 'Facebook address must start with ' + ', '.join(FB_POSSIBLE_PREFIXES)})
	if hasattr(obj, 'url_instagram') and obj.url_instagram and not obj.url_instagram.startswith(IN_POSSIBLE_PREFIXES):
		raise ValidationError({'url_instagram': 'Instagram address must start with' + ', '.join(IN_POSSIBLE_PREFIXES)})
	if hasattr(obj, 'url_telegram') and obj.url_telegram and not obj.url_telegram.startswith(TG_POSSIBLE_PREFIXES):
		raise ValidationError({'url_telegram': 'Telegram address must start with ' + ', '.join(TG_POSSIBLE_PREFIXES)})

FAKE_ORGANIZER_ID = 2
FAKE_ORGANIZER_NAME = 'Unknown organizer'

class Series(models.Model):
	id = models.AutoField(primary_key=True)
	name = models.CharField(verbose_name='Название серии латиницей', max_length=250, blank=False)
	name_orig = models.CharField(verbose_name='Название серии на языке оригинала, если отличается от name', max_length=250, blank=True)
	country = models.ForeignKey(Country, verbose_name='Страна для серий, забеги которых проходят в разных городах одной страны',
		default=None, null=True, blank=True, on_delete=models.PROTECT)
	city = models.ForeignKey(City, verbose_name='Город старта', default=None, null=True, blank=True,
		on_delete=models.PROTECT, related_name='series_city_set')
	city_finish = models.ForeignKey(City, verbose_name='Город финиша (если отличается от старта)', default=None, null=True, blank=True,
		on_delete=models.PROTECT, related_name='series_city_finish_set')
	editors = models.ManyToManyField(settings.AUTH_USER_MODEL, through='Series_editor', through_fields=('series', 'user'),
		related_name='series_to_edit_set')
	platforms = models.ManyToManyField('Platform', through='Series_platform', through_fields=('series', 'platform'),
		related_name='series_set')
	organizer = models.ForeignKey('Organizer', verbose_name='Организатор', default=FAKE_ORGANIZER_ID, blank=True,
		on_delete=models.PROTECT)

	country_raw = models.CharField(verbose_name='Страна (необработанная)', max_length=100, blank=True)
	region_raw = models.CharField(verbose_name='Регион (необработанный)', max_length=100, blank=True)
	city_raw = models.CharField(verbose_name='Город (необработанный)', max_length=100, blank=True)

	start_place = models.CharField(verbose_name='Место старта', max_length=100, blank=True)
	surface_type = models.SmallIntegerField(verbose_name='Тип забега', choices=results_util.SURFACE_TYPES, default=results_util.SURFACE_DEFAULT)
	director = models.CharField(verbose_name='Организатор', max_length=250, blank=True, db_index=True)
	contacts = models.CharField(verbose_name='Координаты организаторов', max_length=250, blank=True)
	url_site = custom_fields.MyURLField(verbose_name='Сайт серии', max_length=MAX_URL_LENGTH, blank=True, db_index=True)
	url_vk = models.URLField(verbose_name='Страница ВКонтакте', max_length=100, blank=True)
	url_facebook = models.URLField(verbose_name='Страница в фейсбуке', max_length=100, blank=True)
	url_instagram = models.URLField(verbose_name='Страница в инстраграме', max_length=100, blank=True)
	url_wiki = models.URLField(verbose_name='Страница о серии в Википедии', max_length=200, blank=True)
	url_telegram = models.URLField(verbose_name='Канал о серии в Telegram', max_length=200, blank=True)
	is_weekly = models.BooleanField(verbose_name='Эта серия — паркран или что-то похожее. Скрывать в календаре вместе с паркранами', db_index=True, default=False)
	create_weekly = models.BooleanField(verbose_name='Создавать ли новые забеги еженедельно', default=False)
	is_for_masters = models.BooleanField(verbose_name='Это соревнование для ветеранов', default=False, db_index=True)
	# Пока используется только для загрузки старых паркранов
	latest_loaded_event = models.DateField(verbose_name='Дата последнего загруженного забега', default=None, null=True, blank=True, db_index=True)

	comment = models.CharField(verbose_name='Комментарий', max_length=250, blank=True)
	comment_private = models.CharField(verbose_name='Комментарий администраторам (не виден посетителям)',
		max_length=250, blank=True)
	last_update = models.DateTimeField(verbose_name='Дата последнего обновления', auto_now=True)
	created_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name='Создал серию в базе', related_name='series_created_set',
		on_delete=models.SET_NULL, default=None, null=True, blank=True)
	class Meta:
		verbose_name = 'Серия забегов'
		indexes = [
			models.Index(fields=['country', 'name']),
			models.Index(fields=['country', 'city', 'name']),
		]
		constraints = [
			models.UniqueConstraint(fields=['name', 'city'], name='name_city'),
		]
	def clean(self):
		self.name = self.name.strip()
		self.name = replace_symbols(self.name)
		if self.name == '':
			raise ValidationError('Series name cannot be empty.')
		if self.city_finish and not self.city:
			raise ValidationError('If you set the finish city, you must also set the start city.')
		if self.city:
			self.country = self.city.region.country
		self.contacts = self.contacts.strip()
		self.url_site = self.url_site.strip()
		self.comment = self.comment.strip()
		self.comment_private = self.comment_private.strip()

		if self.name.startswith(results_util.RUSSIAN_PARKRUN_SITE):
			self.is_weekly = True
		validate_social_urls(self)
	def strCityCountry(self, with_nbsp=True):
		if self.city:
			return self.city.nameWithFinish(self.city_finish, with_nbsp=with_nbsp)
		if self.country:
			return self.country.name
		return 'Unknown'
	def getCountry(self):
		if self.city:
			return self.city.region.country
		return self.country
	def has_dependent_objects(self):
		return self.event_set.exists() or self.document_set.exists() or self.series_name_set.exists()
	def get_url_logo(self):
		doc = self.document_set.filter(document_type=DOC_TYPE_LOGO).first()
		if doc:
			return doc.url_source if doc.url_source else doc.upload.name
		return ''
	def is_russian_parkrun(self):
		return self.url_site.startswith(results_util.RUSSIAN_PARKRUN_SITE)
	def has_news_reviews_photos(self):
		return Document.objects.filter(event__series_id=self.id, document_type__in=[DOC_TYPE_PHOTOS, DOC_TYPE_IMPRESSIONS]).exists() \
			or News.objects.filter(event__series_id=self.id).exists()
	def get_reverse_url(self, target):
		return reverse(target, kwargs={'series_id': self.id})
	def get_absolute_url(self):
		return self.get_reverse_url('results:series_details')
	def get_editor_url(self):
		return self.get_reverse_url('editor:series_details')
	def get_history_url(self):
		return self.get_reverse_url('editor:series_changes_history')
	def get_update_url(self):
		return self.get_reverse_url('editor:series_update')
	def get_delete_url(self):
		return self.get_reverse_url('editor:series_delete')
	def get_create_event_url(self):
		return self.get_reverse_url('editor:event_create')
	def get_clone_url(self):
		return self.get_reverse_url('editor:series_create')
	def get_documents_update_url(self):
		return self.get_reverse_url('editor:series_documents_update')
	def get_update_strikes_url(self):
		return self.get_reverse_url('editor:series_update_strikes')
	def get_add_platform_url(self):
		return self.get_reverse_url('editor:series_platform_add')
	def get_children(self):
		return self.event_set.all()
	def __str__(self):
		res = self.name
		fields = []
		if self.city:
			fields.append(self.city.name_full())
		if self.country:
			fields.append(self.country.name)
		if fields:
			res += ' (' + ', '.join(fields) + ')'
		return res
	@classmethod
	def get_russian_parkruns(cls):
		return cls.objects.filter(url_site__startswith=results_util.RUSSIAN_PARKRUN_SITE)
	@classmethod
	def get_russian_parkrun_ids(cls):
		return set(cls.get_russian_parkruns().values_list('pk', flat=True))

class Platform(models.Model):
	id = models.CharField(max_length=20, primary_key=True)
	name = models.CharField(verbose_name='Название платформы', max_length=30, unique=True)
	def __str__(self):
		return self.name

class Runner_platform(models.Model):
	platform = models.ForeignKey(Platform, on_delete=models.PROTECT)
	runner = models.ForeignKey('Runner', on_delete=models.CASCADE)
	# If we ever meet non-integer IDs, we'll replace in with CharField.
	value = models.BigIntegerField(verbose_name='Идентификатор бегуна на данной платформе')
	updated_from_source = models.BooleanField(verbose_name='Заполнены ли данные о бегуне, указанные на этой платформе', db_index=True, default=False)
	added_time = models.DateTimeField(auto_now_add=True)
	def get_absolute_url(self) -> str:
		if self.platform_id == 'athlinks':
			return f'https://www.athlinks.com/athletes/{self.value}'
		if self.platform_id == 'nyrr':
			nyrr_runner = Nyrr_runner.objects.filter(pk=self.value).first()
			if nyrr_runner:
				return f'https://results.nyrr.org/runner/{nyrr_runner.sample_platform_id}/races'
			return ''
		if self.platform_id == 's95':
			return f'https://s95.by/athletes/{self.value}'
		if self.platform_id == 'parkrun':
			# return f'https://www.parkrun.ru/results/athleteresultshistory/?athleteNumber={self.value}'
			return f'https://www.parkrun.org.uk/parkrunner/{self.value}'
		if self.platform_id == '5verst':
			return f'https://5verst.ru/userstats/{self.value}'
		if self.platform_id == 'vfla':
			return f'https://vfla.lsport.net/Registry/Person/{self.value}'
		if self.platform_id == 'worldathletics':
			return f'https://www.worldathletics.org/athletes/_/{self.value}'
		if self.platform_id == 'arrs':
			return f'https://more.arrs.run/runner/{self.value}'
		if self.platform_id == 'duv':
			return f'https://statistik.d-u-v.org/getresultperson.php?runner={self.value}'
		return ''
	class Meta:
		verbose_name = 'Идентификатор бегуна на данной платформе'
		constraints = [
			models.UniqueConstraint(fields=['platform', 'runner'], name='platform_runner'),
			models.UniqueConstraint(fields=['platform', 'value'], name='runner_platform_value'),
		]
	def merge_nyrr_platforms(self, runner):
		if self.platform_id != 'nyrr':
			raise Exception(f'merge_nyrr_platforms called for Runner_platform {self.id} which is for platform {self.platform_id}')
		for runner_platform in list(runner.runner_platform_set.filter(platform_id='nyrr')):
			if runner_platform.id == self.id:
				raise Exception(f'merge_nyrr_platforms called for runner {runner.get_name_and_id()} which has the same runner_platform_id {self.id}')
			nyrr_runner_id = runner_platform.value
			n_results_touched = Nyrr_result.objects.filter(nyrr_runner_id=nyrr_runner_id).update(nyrr_runner_id=self.value)
			Nyrr_runner.objects.get(pk=nyrr_runner_id).delete()
			runner_platform.delete()
			write_log(f'{datetime.datetime.now()} Deleting NYRR runner_platform {nyrr_runner_id} in favor of {self.value}: updated {n_results_touched} Nyrr_result records')

class Series_platform(models.Model):
	platform = models.ForeignKey(Platform, on_delete=models.PROTECT)
	series = models.ForeignKey(Series, on_delete=models.CASCADE)
	value = models.CharField(verbose_name='Идентификатор серии на данной платформе', max_length=50)
	added_time = models.DateTimeField(auto_now_add=True)
	def get_absolute_url(self) -> str:
		if self.platform_id == 'athlinks':
			return f'https://www.athlinks.com/event/{self.value}'
		return ''
	class Meta:
		verbose_name = 'Идентификатор серии на данной платформе'
		constraints = [
			models.UniqueConstraint(fields=['platform', 'series'], name='platform_series'),
			models.UniqueConstraint(fields=['platform', 'value'], name='series_platform_value'),
		]

class Series_editor(models.Model):
	user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
	series = models.ForeignKey(Series, on_delete=models.CASCADE)
	added_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
		related_name='editors_added_by_user')
	added_time = models.DateTimeField(auto_now_add=True)
	class Meta:
		verbose_name = 'Пользователь, имеющий права на работу с серией забегов'
		ordering = ['series__name']

DEFAULT_EVENT_LENGTH = datetime.timedelta(hours=4)
class Event(models.Model):
	series = models.ForeignKey(Series, on_delete=models.CASCADE)
	name = models.CharField(verbose_name='Название забега', max_length=250, db_index=True)
	number = models.SmallIntegerField(verbose_name='Номер забега в серии', default=None, null=True, blank=True)
	city = models.ForeignKey(City, verbose_name='Город старта', default=None, null=True, blank=True,
		on_delete=models.PROTECT, related_name='event_city_set')
	city_finish = models.ForeignKey(City, verbose_name='Город финиша', default=None, null=True, blank=True,
		on_delete=models.PROTECT, related_name='event_city_finish_set')
	surface_type = models.SmallIntegerField(verbose_name='Surface', choices=results_util.SURFACE_TYPES, default=results_util.SURFACE_DEFAULT)
	platform = models.ForeignKey(Platform, on_delete=models.PROTECT, null=True, blank=True)
	id_on_platform = models.CharField(verbose_name='ID забега на платформе, с которой взяты данные', max_length=40, blank=True)

	country_raw = models.CharField(verbose_name='Страна (необработанная)', max_length=100, blank=True)
	region_raw = models.CharField(verbose_name='Регион (необработанный)', max_length=100, blank=True)
	city_raw = models.CharField(verbose_name='Город (необработанный)', max_length=100, blank=True)

	start_date = models.DateField(verbose_name='Дата старта')
	finish_date = models.DateField(verbose_name='Дата финиша (только если отличается от старта)', db_index=True, default=None, null=True, blank=True)
	start_place = models.CharField(verbose_name='Место старта', max_length=100, blank=True)
	start_time = models.TimeField(verbose_name='Время старта, если известно', null=True, blank=True)

	announcement = models.TextField(verbose_name='Дополнительная информация', blank=True)
	url_registration = custom_fields.MyURLField(verbose_name='URL страницы с регистрацией', max_length=MAX_URL_LENGTH, blank=True)
	email = models.CharField(verbose_name='E-mail организаторов', max_length=MAX_EMAIL_LENGTH, blank=True)
	director = models.CharField(verbose_name='Организатор', max_length=250, blank=True, db_index=True)
	contacts = models.CharField(verbose_name='Другие контакты организаторов', max_length=255, blank=True)
	url_site = custom_fields.MyURLField(verbose_name='Сайт/страница именно этого забега', max_length=MAX_URL_LENGTH, blank=True)
	url_vk = models.URLField(verbose_name='Страница забега ВКонтакте', max_length=MAX_URL_LENGTH, blank=True)
	url_facebook = models.URLField(verbose_name='Страница забега на Facebook', max_length=MAX_URL_LENGTH, blank=True)
	url_wiki = models.URLField(verbose_name='Страница о забеге в Википедии', max_length=MAX_URL_LENGTH, blank=True)
	url_itra = models.URLField(verbose_name='Страница забега на сайте ITRA', max_length=MAX_URL_LENGTH, blank=True)

	cancelled = models.BooleanField(verbose_name='Забег отменён', db_index=True, default=False)
	comment = models.CharField(verbose_name='Комментарий', max_length=250, blank=True)
	comment_private = models.CharField(verbose_name='Комментарий для администраторов (виден только админам)', max_length=250, blank=True)
	invisible = models.BooleanField(verbose_name='Забег не должен быть виден пользователям', default=False)
	ask_for_protocol_sent = models.BooleanField(verbose_name='Мы уже писали организаторам запрос на протокол', default=False)
	not_for_klb = models.BooleanField(verbose_name='Забег НЕ подлежит учёту в КЛБМатче', default=False)

	source = models.CharField(verbose_name='Источник информации (виден всем)', max_length=100, blank=True)
	source_private = models.CharField(verbose_name='Источник информации (виден только админам)', max_length=100, blank=True)
	date_added = models.DateField(verbose_name='Дата появления забега в календаре', auto_now_add=True)
	last_update = models.DateTimeField(auto_now=True)
	created_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name='Кто добавил забег на сайт',
		on_delete=models.SET_NULL, default=None, null=True, blank=True)
	def clean(self):
		self.name = self.name.strip()
		self.name = replace_symbols(self.name)
		if self.city and (self.city == self.series.city) and (self.city_finish is None) and (self.series.city_finish is None):
			self.city = None
		if self.city and (self.city == self.series.city) and (self.city_finish == self.series.city_finish):
			self.city = None
			self.city_finish = None
		if self.start_date:
			if not DATE_MIN <= self.start_date <= DATE_MAX:
				raise ValidationError('Incorrect event date')
			if self.finish_date == self.start_date:
				self.finish_date = None
			if self.finish_date and (self.finish_date < self.start_date):
				raise ValidationError('The finish date cannot be before the start date')

		self.name = results_util.fix_quotes(self.name)

		self.contacts = self.contacts.strip()
		self.announcement = self.announcement.strip()
		self.email = self.email.strip()
		self.contacts = self.contacts.strip()
		self.url_site = self.url_site.strip()
		self.url_vk = self.url_vk.strip()
		self.url_facebook = self.url_facebook.strip()
		self.comment = self.comment.strip()
		self.comment_private = self.comment_private.strip()

		if self.surface_type and (self.surface_type == self.series.surface_type):
			self.surface_type = results_util.SURFACE_DEFAULT
		validate_social_urls(self)
	class Meta:
		indexes = [
			models.Index(fields=['series', 'start_date', 'name']),
			models.Index(fields=['city', 'name']),
			models.Index(fields=['start_date', 'name']),
		]
		constraints = [
			models.UniqueConstraint(fields=['series', 'start_date', 'start_time', 'city'], name='series_start_date_city'),
			models.UniqueConstraint(fields=['platform', 'id_on_platform'], condition=Q(platform_id__in=('athlinks', 'nyrr')), name='event_platform_id_on_platform'),
		]
	def date(self, str_format='%B %d, %Y', with_time=False, with_nobr=True):
		if self.finish_date and str_format.startswith('%B %d'):
			if self.start_date.year == self.finish_date.year:
				if self.start_date.month == self.finish_date.month:
					res = f'{self.start_date.strftime("%B %d")}–{self.finish_date.strftime("%d, %Y")}'
				else:
					res = f'{self.start_date.strftime('%B %d')} – {self.finish_date.strftime(str_format)}'
				return ('<span class="nobr">' + res + '</span>') if with_nobr else res
		res = self.start_date.strftime(str_format)
		if with_time:
			res += ', ' + self.start_time
		if self.finish_date:
			res += ' – ' + self.finish_date.strftime(str_format)
		return res
	def dateFull(self, with_time=False, with_nbsp=True):
		if not self.start_date:
			return 'unknown'
		if not with_time or not self.start_time:
			return results_util.dates2str(self.start_date, self.finish_date, with_nbsp=with_nbsp)
		res = f'{results_util.date2str(self.start_date, with_nbsp=with_nbsp)}, {self.start_time}'
		if self.finish_date:
			res += ' – ' + results_util.date2str(self.finish_date, with_nbsp=with_nbsp)
		return res
	def dateWoYear(self):
		return self.date(str_format='%d.%m')
	def dateWithTime(self):
		return self.dateFull(with_time=True)
	def get_url_logo(self):
		doc = self.document_set.filter(document_type=DOC_TYPE_LOGO).first()
		if doc:
			return doc.url_source if doc.url_source else doc.upload.name
		return ''
	def getCountry(self):
		if self.city:
			return self.city.region.country
		if self.series.city:
			return self.series.city.region.country
		if self.series.country:
			return self.series.country
		return None
	def strCountry(self):
		country = self.getCountry()
		return country.name if country else 'Неизвестно'
	def strCityCountry(self, with_nbsp=True):
		if not self.city:
			return self.series.strCityCountry(with_nbsp=with_nbsp)
		# So self.city is not None
		return self.city.nameWithFinish(self.city_finish, with_nbsp=with_nbsp)
	def is_in_future(self):
		if self.start_date is None:
			return False
		return datetime.date.today() <= self.start_date
	def is_in_past(self):
		if self.start_date is None:
			return False
		return datetime.date.today() >= self.start_date
	def get_surface_type(self):
		if self.surface_type:
			return self.surface_type
		return self.series.surface_type
	def get_surface_type_name(self):
		if self.surface_type:
			return self.get_surface_type_display()
		return self.series.get_surface_type_display()
	def can_be_edited(self): # We allow series editors to edit events that are not older than 1 year
		return (self.start_date >= datetime.date.today() - datetime.timedelta(days=90))
	def has_races_wo_results(self): # Should we draw button 'I have a result on this event'?
		return (datetime.date.today() >= self.start_date) and self.race_set.exclude(loaded__in=RESULTS_SOME_OR_ALL_OFFICIAL).exists()
	def ordered_race_set(self):
		return self.race_set.select_related('distance').order_by('distance__distance_type', '-distance__length', 'precise_name')
	def has_races_with_results(self): # Should we draw button 'Create a news with results for this event'?
		return self.race_set.filter(loaded=RESULTS_LOADED, n_participants_finished__gt=0).exists()
	def has_news_reviews_photos(self):
		return self.document_set.filter(document_type__in=[DOC_TYPE_PHOTOS, DOC_TYPE_IMPRESSIONS]).exists() or self.news_set.exists()
	def city_id_for_link(self): # What city_id to use for link from races list?
		if self.city and not self.city_finish:
			return self.city.id
		if (not self.city) and self.series.city and not self.series.city_finish:
			return self.series.city.id
		return 0
	def email_correct(self):
		return is_email_correct(self.email)
	def first_email(self): # Return just first email if there are a few. For 'Add to calendar' button
		if self.email:
			return self.email.split(',')[0].strip()
		return ''
	def site(self):
		if self.url_site:
			return self.url_site
		return self.series.url_site
	def vk(self):
		if self.url_vk:
			return self.url_vk
		return self.series.url_vk
	def fb(self):
		if self.url_facebook:
			return self.url_facebook
		return self.series.url_facebook
	def getCity(self):
		if self.city:
			return self.city
		return self.series.city
	def getCityFinish(self):
		if self.city_finish:
			return self.city_finish
		if self.city:
			return None
		return self.series.city_finish
	def get_age_on_event_date(self, birthday):
		return results_util.get_age_on_date(self.start_date, birthday)
	def has_dependent_objects(self):
		return self.race_set.exists() or self.document_set.exists() or self.news_set.exists() or self.klb_result_set.exists()
	def get_xls_protocols(self):
		return self.document_set.filter(Q_IS_XLS_FILE, document_type__in=DOC_PROTOCOL_TYPES)
	def add_to_calendar(self, race, user: get_user_model()) -> Tuple[bool, str]:
		if Calendar.objects.filter(event=self, user=user).exists():
			return False, 'This event is already present in your calendar.'
		Calendar.objects.create(event=self, race=race, user=user)
		return True, ''
	def remove_from_calendar(self, user: get_user_model()) -> Tuple[bool, str]:
		items = Calendar.objects.filter(event=self, user=user)
		if items.exists():
			items.delete()
			return True, ''
		return False, 'This event isn\'t present in your calendar.'
	def get_documents_for_right_column(self):
		return self.document_set.exclude(document_type__in=DOC_TYPES_NOT_FOR_RIGHT_COLUMN).select_related('scraped_event').order_by('document_type', 'comment')
	def get_reverse_url(self, target):
		return reverse(target, kwargs={'event_id': self.id})
	def get_absolute_url(self):
		return self.get_reverse_url('results:event_details')
	def get_editor_url(self):
		return self.get_reverse_url('editor:event_details')
	def get_clone_url(self):
		return self.get_reverse_url('editor:event_create')
	def get_delete_url(self):
		return self.get_reverse_url('editor:event_delete')
	def get_protocol_details_url(self, protocol=None):
		if protocol:
			return reverse('editor:protocol_details', kwargs={'event_id': self.id, 'protocol_id': protocol.id})
		return self.get_reverse_url('editor:protocol_details')
	def get_change_series_url(self):
		return self.get_reverse_url('editor:event_change_series')
	def get_history_url(self):
		return self.get_reverse_url('editor:event_changes_history')
	def get_make_news_url(self):
		return self.get_reverse_url('editor:event_details_make_news') + '#news'
	def get_remove_races_with_no_results_url(self):
		return self.get_reverse_url('editor:remove_races_with_no_results')
	def get_documents_update_url(self):
		return self.get_reverse_url('editor:event_documents_update')
	def get_add_to_calendar_url(self):
		return self.get_reverse_url('results:add_event_to_calendar')
	def get_remove_from_calendar_url(self):
		return self.get_reverse_url('results:remove_event_from_calendar')
	def get_age_group_records_url(self):
		return self.get_reverse_url('results:event_age_group_records')
	def get_platform_url(self):
		if self.platform_id == 'nyrr':
			return links.NyrrEventURL(self.id_on_platform)
		if self.platform_id == 'trackshackresults':
			return links.TrackShackResultsEventURL(self.id_on_platform)
		if self.platform_id == 'athlinks' and (series_platform := self.series.series_platform_set.filter(platform_id='athlinks').first()):
			return links.AthlinksEventURL(series_platform.value, self.id_on_platform)
		if self.platform_id == 'mikatiming' and (series_platform := self.series.series_platform_set.filter(platform_id='mikatiming').first()):
			return links.MikatimingEventURL(series_platform.value, self.id_on_platform)
		return ''
	def get_start_time_iso(self):
		res = self.start_date.isoformat()
		if self.start_time:
			res += ' ' + self.start_time.isoformat()
		return res
	def get_finish_time_iso(self):
		if self.finish_date:
			return self.finish_date.isoformat()
		if self.start_time:
			res = datetime.datetime.combine(self.start_date, self.start_time) + DEFAULT_EVENT_LENGTH
			return res.isoformat(chr(32))
		return self.start_date.isoformat()
	def show_age_group_records_tab(self):
		return self.is_in_past() and Record_result.objects.filter(Q(cur_place=1) | Q(cur_place_electronic=1) | Q(was_record_ever=True),
			race__event=self).exists()
	def __str__(self):
		return self.name if self.name else self.series.name
	@classmethod
	def get_visible_events(cls, year=None):
		res = cls.objects.filter(
			series__series_type__in=(SERIES_TYPE_RUN, SERIES_TYPE_DO_NOT_SHOW), # For parkruns
			cancelled=False,
			invisible=False)
		if year:
			res = res.filter(start_date__year=year)
		return res
	@classmethod
	def get_events_by_countries(cls, year, country_ids):
		return cls.get_visible_events(year).filter(
			Q(city__region__country_id__in=country_ids) | ( Q(city=None) & Q(series__city__region__country_id__in=country_ids) ))
	def get_children(self):
		return self.race_set.all()

TYPE_TRASH = 0
TYPE_METERS = 1
TYPE_MINUTES_RUN = 2
TYPE_STEPS = 4
TYPE_FLOORS = 5
TYPE_RELAY = 7
TYPE_NORDIC_WALKING = 9
TYPE_RACEWALKING = 10
TYPE_CANICROSS = 11
TYPE_MINUTES_RACEWALKING = 12
TYPE_MINUTES_NORDIC_WALKING = 13
TYPE_HURDLING = 15
TYPE_STEEPLECHASE = 16
TYPE_JUMP = 17
TYPE_THROW = 18
DIST_TYPES = (
	(TYPE_TRASH, 'strange'),
	(TYPE_METERS, 'meters'),
	(TYPE_MINUTES_RUN, 'minutes (running)'),
	(TYPE_STEPS, 'steps'),
	(TYPE_FLOORS, 'floors'),
	(TYPE_RELAY, 'эстафета'),
	(TYPE_NORDIC_WALKING, 'скандинавская ходьба'),
	(TYPE_RACEWALKING, 'спортивная ходьба'),
	(TYPE_CANICROSS, 'каникросс'),
	(TYPE_MINUTES_RACEWALKING, 'минуты (спортивная ходьба)'),
	(TYPE_MINUTES_NORDIC_WALKING, 'минуты (скандинавская ходьба)'),
	(TYPE_HURDLING, 'бег с барьерами'),
	(TYPE_STEEPLECHASE, 'стипль-чез'),
	(TYPE_JUMP, 'прыжки'),
	(TYPE_THROW, 'метания и толкания'),
)

TYPES_MINUTES = (TYPE_MINUTES_RUN, TYPE_MINUTES_RACEWALKING, TYPE_MINUTES_NORDIC_WALKING, TYPE_JUMP, TYPE_THROW)
TYPES_FOR_RUNNER_STAT = (
	TYPE_MINUTES_RUN,
	TYPE_MINUTES_RACEWALKING,
	TYPE_METERS,
	TYPE_RACEWALKING,
	TYPE_HURDLING,
	TYPE_STEEPLECHASE,
)

MILE_IN_METERS = 1609.344

class Distance(models.Model):
	distance_type = models.SmallIntegerField(verbose_name='Тип дистанции', default=1, choices=DIST_TYPES)
	length = models.IntegerField(verbose_name='Длина дистанции (обычно в метрах, километрах или минутах)', default=0, db_index=True)
	name = models.CharField(verbose_name='Название дистанции (можно оставить пустым)', max_length=100, blank=True)
	popularity_value = models.SmallIntegerField(verbose_name='Приоритет', default=0)
	created_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name='Кто добавил дистанцию в БД',
		on_delete=models.SET_NULL, default=None, null=True, blank=True)
	added_time = models.DateTimeField(verbose_name='Время занесения в БД', auto_now_add=True)
	class Meta:
		indexes = [
			models.Index(fields=['popularity_value', 'distance_type', 'length']),
		]
		constraints = [
			models.UniqueConstraint(fields=['distance_type', 'length'], name='type_length'),
		]
	def clean(self):
		self.name = self.name.strip()
		if not self.name:
			self.name = self.nameFromType()
	def nameFromType(self, avoid_km=False):
		if self.distance_type == TYPE_METERS:
			return results_util.length2m_or_km(self.length, avoid_km=avoid_km)
		if self.distance_type in TYPES_MINUTES:
			tmp = self.length
			minutes = tmp % 60
			tmp //= 60
			hours = tmp
			res = []
			if hours:
				res.append(f'{hours} hours')
			if minutes:
				res.append(f'{minutes} minutes')
			if self.distance_type == TYPE_MINUTES_RACEWALKING:
				return 'race walking' + ' '.join(res)
			return ' '.join(res)
		if self.distance_type == TYPE_STEPS:
			return str(self.length) + ' floors'
		if self.distance_type == TYPE_FLOORS:
			return str(self.length) + ' floors'
		if self.distance_type == TYPE_NORDIC_WALKING:
			return 'nordic walking ' + results_util.length2m_or_km(self.length, avoid_km=avoid_km)
		if self.distance_type == TYPE_RACEWALKING:
			return 'race walking ' + results_util.length2m_or_km(self.length, avoid_km=avoid_km)
		if self.distance_type == TYPE_CANICROSS:
			return 'canicross ' + results_util.length2m_or_km(self.length, avoid_km=avoid_km)
		if self.distance_type == TYPE_HURDLING:
			return f'{self.length} m (hurdles)'
		if self.distance_type == TYPE_STEEPLECHASE:
			return f'{self.length} m (steeple chase)'
		return ''
	def get_name(self, surface_type):
		if (self.distance_type in (TYPE_METERS, TYPE_RACEWALKING, TYPE_NORDIC_WALKING, TYPE_CANICROSS, TYPE_BICYCLE)) \
			and (surface_type in (SURFACE_STADIUM, SURFACE_INDOOR, SURFACE_INDOOR_NONSTANDARD)):
			return self.nameFromType(avoid_km=True)
		return self.name
	def strResult(self, value, round_hundredths=False, for_best_result=False, timing=None):
		if self.distance_type in TYPES_MINUTES:
			res = str(value)
			if for_best_result:
				if len(res) >= BEST_RESULT_LENGTH:
					return res
				if len(res) == BEST_RESULT_LENGTH - 1:
					return res + 'm'
			return res + ' m'
		return centisecs2time(value, round_hundredths=round_hundredths, timing=timing)
	def get_pace(self, value): # In seconds per km
		if self.length == 0:
			return None
		if value == 0:
			return None
		if self.distance_type in TYPES_MINUTES:
			return int(round(self.length * 60 * 1000 / value))
		return int(round(value * 10 / self.length))
	def has_dependent_objects(self):
		return self.race_set.exists() or self.distance_real_set.exists() or self.split_set.exists()
	def get_reverse_url(self, target):
		return reverse(target, kwargs={'distance_id': self.id})
	def get_editor_url(self):
		return self.get_reverse_url('editor:distance_details')
	def get_update_url(self):
		return self.get_reverse_url('editor:distance_update')
	def get_delete_url(self):
		return self.get_reverse_url('editor:distance_delete')
	def get_history_url(self):
		return self.get_reverse_url('editor:distance_changes_history')
	def __str__(self):
		return self.name
	@classmethod
	def get_all_by_popularity(cls):
		return cls.objects.all().order_by('-popularity_value', 'distance_type', 'length')

RESULTS_NOT_LOADED = 0
RESULTS_LOADED = 1
RESULTS_SOME_UNOFFICIAL = 2
RESULTS_SOME_OFFICIAL = 3
LOADED_TYPES = (
	(RESULTS_NOT_LOADED, 'результатов нет'),
	(RESULTS_LOADED, 'загружены целиком'),
	(RESULTS_SOME_UNOFFICIAL, 'есть неофициальные результаты — добавленные пользователями'),
	(RESULTS_SOME_OFFICIAL, 'загружена часть официальных результатов'),
)
RESULTS_SOME_OR_ALL_OFFICIAL = (RESULTS_LOADED, RESULTS_SOME_OFFICIAL)

TIMING_UNKNOWN = 0
TIMING_ELECTRONIC = 1
TIMING_HAND = 2
TIMING_STRANGE = 3
TIMING_TYPES = (
	(TIMING_UNKNOWN, 'неизвестен'),
	(TIMING_ELECTRONIC, 'электронный'),
	(TIMING_HAND, 'ручной'),
	(TIMING_STRANGE, 'что-то странное'),
)

BEST_RESULT_LENGTH = 10
class Race(models.Model):
	event = models.ForeignKey(Event, verbose_name='Забег', on_delete=models.CASCADE)
	distance = models.ForeignKey(Distance, verbose_name='Официальная дистанция', on_delete=models.PROTECT)
	distance_real = models.ForeignKey(Distance, verbose_name='Фактическая дистанция (если отличается)',
		on_delete=models.PROTECT, related_name='distance_real_set', default=None, null=True, blank=True)
	precise_name = models.CharField(verbose_name='Уточнение названия', max_length=75, blank=True)
	surface_type = models.SmallIntegerField(verbose_name='Тип забега (укажите, только если отличается от всего забега)',
		choices=results_util.SURFACE_TYPES, default=results_util.SURFACE_DEFAULT)
	platform = models.ForeignKey(Platform, on_delete=models.CASCADE, null=True, blank=True)
	id_on_platform = models.CharField(verbose_name='ID старта на платформе, с которой взяты данные', max_length=40)

	n_participants = models.IntegerField(verbose_name='Число участников', default=None, null=True, blank=True)
	n_participants_male = models.IntegerField(verbose_name='Число участников-мужчин', default=None, null=True, blank=True)
	n_participants_female = models.IntegerField(verbose_name='Число участников-женщин', default=None, null=True, blank=True)
	n_participants_nonbinary = models.IntegerField(verbose_name='Число участников иного пола', default=None, null=True, blank=True)
	n_participants_finished = models.IntegerField(verbose_name='Число финишировавших', default=None, null=True, blank=True)
	n_participants_finished_male = models.IntegerField(verbose_name='Число финишировавших мужчин', default=None, null=True, blank=True)
	n_participants_finished_female = models.IntegerField(verbose_name='Число финишировавших женщин', default=None, null=True, blank=True)
	n_participants_finished_nonbinary = models.IntegerField(verbose_name='Число финишировавших иного пола', default=None, null=True, blank=True)

	winner_male = models.OneToOneField('Result', on_delete=models.SET_NULL, related_name='winner_male_race', null=True, blank=True)
	winner_female = models.OneToOneField('Result', on_delete=models.SET_NULL, related_name='winner_female_race', null=True, blank=True)
	winner_nonbinary = models.OneToOneField('Result', on_delete=models.SET_NULL, related_name='winner_nonbinary_race', null=True, blank=True)
	is_course_record_male = models.BooleanField(verbose_name='Рекорд ли трассы для мужчин', default=False, blank=True)
	is_course_record_female = models.BooleanField(verbose_name='Рекорд ли трассы для женщин', default=False, blank=True)
	is_course_record_nonbinary = models.BooleanField(verbose_name='Рекорд ли трассы для небинарных участников', default=False, blank=True)

	comment = models.CharField(verbose_name='Комментарий', max_length=250, blank=True)
	comment_private = models.CharField(verbose_name='Комментарий администраторам (не виден посетителям)',
		max_length=250, blank=True)
	gps_track = models.URLField(verbose_name='Ссылка на трек на Страве', max_length=300, blank=True)

	start_date = models.DateField(verbose_name='Дата старта (если отличается от даты старта забега)', null=True, blank=True)
	start_time = models.TimeField(verbose_name='Время старта (если отличается от времени старта забега)', null=True, blank=True)
	finish_date = models.DateField(verbose_name='Дата финиша (если отличается от даты старта)', null=True, blank=True, db_index=True)

	elevation_meters = models.IntegerField(verbose_name='Общий подъём в метрах', default=None, null=True, blank=True)
	descent_meters = models.IntegerField(verbose_name='Общий спуск в метрах', default=None, null=True, blank=True)
	altitude_start_meters = models.IntegerField(verbose_name='Высота старта', default=None, null=True, blank=True)
	altitude_finish_meters = models.IntegerField(verbose_name='Высота финиша',
		default=None, null=True, blank=True)

	geo = gis_models.PointField(verbose_name='Координаты центра города', geography=True, default=None, null=True) # Возможно, пара DecimalField(max_digits=22, decimal_places=16) будет практичнее
	load_status = models.SmallIntegerField(verbose_name='Состояние загрузки результатов', default=RESULTS_NOT_LOADED, choices=LOADED_TYPES)
	loaded_from = models.CharField(max_length=200, blank=True)
	created_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name='Кто добавил забег на сайт',
		on_delete=models.SET_NULL, default=None, null=True, blank=True)

	has_no_results = models.BooleanField(verbose_name='Результатов нет и не будет', default=False, blank=True)
	is_for_handicapped = models.BooleanField(verbose_name='Для спортсменов с ограниченными возможностями',
		default=False, blank=True)
	is_virtual = models.BooleanField(verbose_name='Виртуальный забег, результаты не загружаем', default=False, blank=True)
	exclude_from_stat = models.BooleanField(verbose_name='Сумма нескольких других дистанций забега. Не учитывать в статистике бегунов', default=False, blank=True)
	timing = models.SmallIntegerField(verbose_name='Вид хронометража', default=TIMING_UNKNOWN, choices=TIMING_TYPES, db_index=True)
	certificate = models.ForeignKey('Course_certificate', verbose_name='Сертификат трассы', on_delete=models.PROTECT, default=None, null=True, blank=True)
	itra_score = models.SmallIntegerField(verbose_name='Очки ITRA', default=0)
	def clean(self):
		if not hasattr(self, 'distance'): # It's strange that this check is needed, but otherwise 'Race has no distance' error is raised.
			raise ValidationError('Вы добавляете новую дистанцию, но не указали её длину.')
		if not 0 <= self.itra_score <= 6:
			raise ValidationError('ITRA score must be between 0 and 6.')
		if self.itra_score:
			if self.get_surface_type() not in (SURFACE_SOFT, SURFACE_MOUNTAIN):
				raise ValidationError('Очки ITRA могут стоять только у кроссов, трейлов и горного бега')

		if self.distance_real:
			if self.distance_real == self.distance:
				raise ValidationError('Официальная и фактическая дистанции не могут совпадать.')
			if self.distance_real.distance_type != self.distance.distance_type:
				raise ValidationError('Типы официальной и фактической дистанций не могут отличаться.')

		if self.surface_type and (self.surface_type == self.event.get_surface_type()):
			self.surface_type = results_util.SURFACE_DEFAULT
	class Meta:
		verbose_name = 'Дистанция в рамках забега'
		indexes = [
			models.Index(fields=['event', 'distance', 'id']),
			models.Index(fields=['event', 'load_status']),
			models.Index(fields=['start_date', 'start_time']),
		]
		constraints = [
			models.UniqueConstraint(fields=['event', 'distance', 'precise_name'], name='event_distance_name'),
		]
	def get_official_results(self):
		return self.result_set.filter(source=RESULT_SOURCE_DEFAULT).order_by('status', 'place', 'result', 'lname', 'fname', 'midname')
	def fill_winners_info(self, to_save=True):
		results = self.get_official_results()
		self.winner_male = results.filter(gender=results_util.GENDER_MALE, is_improbable=False).exclude(place_gender=None).order_by('place_gender', 'lname', 'fname').first()
		self.winner_female = results.filter(gender=results_util.GENDER_FEMALE, is_improbable=False).exclude(place_gender=None).order_by('place_gender', 'lname', 'fname').first()
		self.winner_nonbinary = results.filter(gender=results_util.GENDER_NONBINARY, is_improbable=False).exclude(place_gender=None).order_by('place_gender', 'lname', 'fname').first()
		if to_save:
			self.save()
	def get_men_percent(self):
		if self.n_participants_finished and self.n_participants_finished_male:
			return min(100, int(self.n_participants_finished_male * 100 / self.n_participants_finished))
		return 100
	def get_women_percent(self):
		if self.n_participants_finished and self.n_participants_finished_female:
			return min(100, int(self.n_participants_finished_female * 100 / self.n_participants_finished))
		return 0
	def get_precise_name(self):
		res = str(self.distance)
		if self.precise_name:
			res += f' ({self.precise_name})'
		return res
	def distance_with_heights(self):
		res = self.get_precise_name()
		heights = []
		if self.elevation_meters:
			heights.append(f'+{self.elevation_meters}m')
		if self.descent_meters:
			heights.append(f'-{self.descent_meters}m')
		return res + ((' (' + ', '.join(heights) + ')') if heights else '')
	def distance_with_details(self, details_level=1):
		res = str(self.distance)
		details = []
		if self.precise_name:
			details.append(self.precise_name)
		if details_level:
			if self.is_virtual:
				details.append('virtual')
			if self.elevation_meters:
				details.append(f'+{self.elevation_meters}&nbsp;m')
			if self.descent_meters:
				details.append(f'-{self.descent_meters}&nbsp;m')
			if self.surface_type:
				details.append(f'surface: {self.get_surface_type_display()}')
			if self.itra_score:
				details.append(f'ITRA {self.itra_score}')
			elif self.n_participants:
				details.append(f'{self.n_participants}&nbsp;participant{"s" if (self.n_participants > 1) else ""}')
				if self.load_status in (RESULTS_NOT_LOADED, RESULTS_SOME_UNOFFICIAL):
					details.append('results aren\'t loaded')
			elif self.load_status == RESULTS_SOME_OFFICIAL:
				details.append('a part of results is loaded')
			elif self.load_status == RESULTS_SOME_UNOFFICIAL:
				n_unof = self.get_unofficial_results().count()
				if n_unof:
					details.append(f'{n_unof}&nbsp;unofficial result{"s" if (n_unof > 1) else ""}')
			if self.certificate_id:
				details.append('WA-AIMS certificate')
			if details_level >= 2:
				if self.start_date:
					if self.start_time:
						details.append('start on {} at&nbsp;{}'.format(self.start_date.strftime('%d.%m.%Y'), self.start_time.strftime("%H:%M")))
					else:
						details.append('start on {}'.format(self.start_date.strftime('%d.%m.%Y')))
				elif self.start_time:
					details.append(f'start at&nbsp;{self.start_time.strftime("%H:%M")}')
		if details:
			res += ' (' + ', '.join(details) + ')'
		return res
	def distance_with_start_date(self):
		return self.distance_with_details(details_level=2)
	def get_pace(self, value): # In seconds per km
		if self.distance_real:
			return self.distance_real.get_pace(value)
		return self.distance.get_pace(value)
	def parse_result(self, value):
		if self.distance.distance_type in TYPES_MINUTES:
			return results_util.int_safe(value)
		else:
			return string2centiseconds(value)
	def get_surface_type(self):
		if self.surface_type:
			return self.surface_type
		return self.event.get_surface_type()
	def get_start_date(self):
		return self.start_date if self.start_date else self.event.start_date
	def get_age_on_event_date(self, birthday):
		return results_util.get_age_on_date(self.get_start_date(), birthday)
	def get_reverse_url(self, target):
		return reverse(target, kwargs={'race_id': self.id})
	def get_absolute_url(self):
		return self.get_reverse_url('results:race_details')
	def get_details_url(self):
		return self.get_reverse_url('results:race_details_tab_editor')
	def get_unoff_details_url(self):
		return self.get_reverse_url('results:race_details_tab_unofficial')
	def get_add_to_club_details_url(self):
		return self.get_reverse_url('results:race_details_tab_add_to_club')
	def get_set_marks_url(self):
		return self.get_reverse_url('starrating:add_marks')
	def get_update_url(self):
		return self.get_reverse_url('editor:race_update')
	def get_editor_url(self):
		return self.event.get_editor_url() + '#races'
	def get_reg_editor_url(self):
		return self.get_reverse_url('editor:reg_race_details')
	def get_results_editor_url(self):
		return self.get_reverse_url('editor:race_details')
	def get_update_stat_url(self):
		return self.get_reverse_url('editor:race_update_stat')
	def get_add_unoff_result_url(self):
		return self.get_reverse_url('editor:race_add_unoff_result')
	def get_ajax_runners_list_url(self):
		return self.get_reverse_url('editor:runners_list')
	def get_reload_weekly_race_url(self):
		return self.get_reverse_url('editor:reload_weekly_race')
	def get_result_list_url(self):
		return self.get_reverse_url('editor:race_result_list')
	def get_delete_off_results_url(self):
		return self.get_reverse_url('editor:race_delete_off_results')
	def get_platform_url(self): # TODO
		# if (self.platform_id == 'athlinks') and self.athlinks_id and self.event.athlinks_id and self.event.series.athlinks_id:
		# 	return f'https://www.athlinks.com/event/{self.event.series.athlinks_id}/results/Event/{self.event.athlinks_id}/Course/{self.athlinks_id}/Results'
		return ''
	def get_unofficial_results(self):
		# return self.get_results_by_source(RESULT_SOURCE_USER)
		res = self.result_set.exclude(source=RESULT_SOURCE_DEFAULT).select_related('runner__klb_person', 'user__user_profile', 'result_on_strava')
		if self.distance.distance_type in TYPES_MINUTES:
			res = res.order_by('status', '-result')
		else:
			res = res.order_by('status', 'result')
		return res
	def __str__(self):
		return self.distance_with_details(details_level=0)
	def name_with_event(self):
		return str(self.event) + ' (' + str(self.distance) + ')'
	@classmethod
	def get_races_by_countries(cls, year, country_ids):
		return Race.objects.filter(event__in=Event.get_events_by_countries(year, country_ids))
	def delete(self, *args, **kwargs):
		starrating.aggr.race_deletion.delete_race_and_ratings(self, *args, **kwargs)

MAX_CATEGORY_LENGTH = 100
# We extract the category of a result to a separate model to store here the number of finishers for each category.
class Category_size(models.Model):
	race = models.ForeignKey(Race, on_delete=models.CASCADE)
	name = models.CharField(verbose_name='Название группы', max_length=MAX_CATEGORY_LENGTH, blank=True)
	size = models.IntegerField(verbose_name='Число участников в группе', default=None, null=True, blank=True, db_index=True)
	class Meta:
		indexes = [
			models.Index(fields=['race', 'size']),
		]
		constraints = [
			models.UniqueConstraint(fields=['race', 'name'], name='category_size_race_name'),
		]

def validate_image(fieldfile_obj):
	filesize = fieldfile_obj.file.size
	LIMIT_MB = 5
	if filesize > LIMIT_MB*1024*1024:
		raise ValidationError(f'Размер файла не может быть больше {LIMIT_MB} мегабайт')
def file_extension(filename, default='jpg'):
	if not '.' in filename:
		return default
	extension = filename.split('.')[-1].lower()
	if 2 <= len(extension) <= 5:
		return extension
	else:
		return default
def logo_name(instance, filename):
	new_name = 'dj_media/clubs/logo/' + str(instance.id) + '.' + file_extension(filename)
	fullname = os.path.join(settings.MEDIA_ROOT, new_name)
	try:
		os.remove(fullname)
	except:
		pass
	return new_name
def logo_thumb_name(instance, filename):
	new_name = 'dj_media/clubs/logo/' + str(instance.id) + '_thumb.' + file_extension(filename)
	fullname = os.path.join(settings.MEDIA_ROOT, new_name)
	try:
		os.remove(fullname)
	except:
		pass
	return new_name
INDIVIDUAL_RUNNERS_CLUB_NUMBER = 75
class Club(models.Model):
	name = models.CharField(verbose_name='Название', max_length=100, db_index=True, blank=False)
	city = models.ForeignKey(City, verbose_name='Город', default=None, null=True, blank=True, on_delete=models.PROTECT)
	editors = models.ManyToManyField(settings.AUTH_USER_MODEL, through='Club_editor', through_fields=('club', 'user'),
		related_name='clubs_to_edit_set')
	is_active = models.BooleanField(verbose_name='Показывать ли клуб на странице клубов', default=True, blank=True)
	is_member_list_visible = models.BooleanField(verbose_name='Виден ли всем список членов',
		default=False, blank=True)

	url_site = models.CharField(verbose_name='Сайт клуба', max_length=200, blank=True)
	logo = models.ImageField(verbose_name='Файл с эмблемой (не больше 2 мегабайт)', max_length=255, upload_to=logo_name, validators=[validate_image], blank=True)
	logo_thumb = models.ImageField(max_length=255, upload_to=logo_thumb_name, blank=True)
	url_vk = models.URLField(verbose_name='Страничка ВКонтакте', max_length=100, blank=True)
	url_facebook = models.URLField(verbose_name='Страничка в фейсбуке', max_length=100, blank=True)

	birthday = models.DateField(verbose_name='Дата рождения клуба', default=None, null=True, blank=True)
	n_members = models.IntegerField(verbose_name='Число членов', default=None, null=True, blank=True)
	email = models.EmailField(verbose_name='E-mail', max_length=MAX_EMAIL_LENGTH, blank=True)
	phone_number = models.CharField(verbose_name='Телефон', max_length=MAX_PHONE_NUMBER_LENGTH, blank=True)
	training_timetable = models.CharField(verbose_name='Расписание регулярных тренировок', max_length=100, blank=True)
	training_cost = models.CharField(verbose_name='Стоимость тренировок', max_length=100, blank=True)

	created_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name='Кто добавил в БД', on_delete=models.SET_NULL,
		default=None, null=True, blank=True)
	added_time = models.DateTimeField(verbose_name='Время занесения в БД', auto_now_add=True, null=True, blank=True)
	last_update_time = models.DateTimeField(verbose_name='Дата последнего обновления', null=True, blank=True)
	comment_private = models.CharField(verbose_name='Комментарий администраторам (не виден посетителям)',
		max_length=250, blank=True)
	class Meta:
		constraints = [
			models.UniqueConstraint(fields=['city', 'name'], name='club_city_name'),
		]
	def clean(self):
		validate_social_urls(self)
	def make_thumbnail(self):
		return make_thumb(self.logo, self.logo_thumb, 140, 140)
	def strCity(self):
		if self.city:
			return self.city.nameWithCountry()
		return ''
	def get_active_members_list(self):
		today = datetime.date.today()
		return self.club_member_set.filter(
				Q(date_registered=None) | Q(date_registered__lte=today),
				Q(date_removed=None) | Q(date_removed__gte=today),
			)
	def get_reverse_url(self, target):
		return reverse(target, kwargs={'club_id': self.id})
	def get_absolute_url(self):
		return self.get_reverse_url('results:club_details')
	def get_editor_url(self):
		return self.get_reverse_url('editor:club_details')
	def get_delete_url(self):
		return self.get_reverse_url('editor:club_delete')
	def get_history_url(self):
		return self.get_reverse_url('editor:club_changes_history')
	def get_planned_starts_url(self):
		return self.get_reverse_url('results:planned_starts')
	def get_club_records_url(self):
		return self.get_reverse_url('results:club_records')
	def get_members_list_url(self):
		return self.get_reverse_url('results:club_members')
	def get_all_members_list_url(self):
		return self.get_reverse_url('results:club_members_all')
	def get_add_new_member_url(self):
		return self.get_reverse_url('editor:club_add_new_member')
	def get_update_records_url(self):
		return self.get_reverse_url('editor:club_update_records')
	def __str__(self):
		res = self.name
		if self.city:
			res += f' ({self.city.name})'
		return res

class Club_editor(models.Model):
	user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
	club = models.ForeignKey(Club, on_delete=models.CASCADE)
	added_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
		related_name='club_editors_added_by_user')
	added_time = models.DateTimeField(auto_now_add=True)
	class Meta:
		constraints = [
			models.UniqueConstraint(fields=['user', 'club'], name='user_club'),
		]

class Club_name(models.Model):
	""" Alternatve names of clubs, to recognize them in protocols. """
	club = models.ForeignKey(Club, on_delete=models.CASCADE)
	name = models.CharField(verbose_name='Название', max_length=100, db_index=True, blank=False)
	added_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
	added_time = models.DateTimeField(auto_now_add=True)
	class Meta:
		constraints = [
			models.UniqueConstraint(fields=['club', 'name'], name='club_name'),
		]

def get_name_condition(lname, fname, midname):
	if midname:
		return Q(lname=lname, fname=fname, midname=midname) | Q(lname=lname, fname=fname, midname='') \
			| Q(lname=fname, fname=lname, midname=midname) | Q(lname=fname, fname=lname, midname='')
	else:
		return Q(lname=lname, fname=fname) | Q(lname=fname, fname=lname)
class Extra_name(models.Model):
	runner = models.ForeignKey('Runner', verbose_name='Бегун', on_delete=models.CASCADE)
	lname = models.CharField(verbose_name='Фамилия', max_length=100)
	fname = models.CharField(verbose_name='Имя', max_length=100)
	midname = models.CharField(verbose_name='Отчество (необязательно)', max_length=100, blank=True)
	comment = models.CharField(verbose_name='Комментарий', max_length=1000, blank=True)
	added_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
	added_time = models.DateTimeField(verbose_name='Время занесения в БД', auto_now_add=True)
	class Meta:
		indexes = [
			models.Index(fields=['runner', 'lname', 'fname', 'midname']),
		]
	def get_name_condition(self):
		return get_name_condition(self.lname, self.fname, self.midname)
	def __str__(self):
		res = self.fname
		if self.midname != '':
			res += ' ' + self.midname
		res += ' ' + self.lname
		return res

AVATAR_SIZE = (200, 400)
def avatar_name(instance, filename):
	new_name = 'dj_media/avatar/' + str(instance.user.id) + '.' + file_extension(filename)
	fullname = os.path.join(settings.MEDIA_ROOT, new_name)
	try:
		os.remove(fullname)
	except:
		pass
	return new_name
def avatar_thumb_name(instance, filename):
	new_name = 'dj_media/avatar/' + str(instance.user.id) + '_thumb.' + file_extension(filename)
	fullname = os.path.join(settings.MEDIA_ROOT, new_name)
	try:
		os.remove(fullname)
	except:
		pass
	return new_name

DEFAULT_WHEN_TO_ASK_FILL_MARKS = datetime.date(1900, 1, 1)

class User_profile(models.Model):
	user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
	midname = models.CharField(verbose_name='Отчество', max_length=100, blank=True)
	gender = models.SmallIntegerField(verbose_name='Пол', default=results_util.GENDER_UNKNOWN, choices=results_util.GENDER_CHOICES)
	comment = models.CharField(verbose_name='Комментарий', max_length=1000, blank=True)
	city = models.ForeignKey(City, verbose_name='Город', default=None, null=True, blank=True, on_delete=models.PROTECT)
	birthday = models.DateField(verbose_name='День рождения', db_index=True, default=None, null=True, blank=True)
	is_public = models.BooleanField(verbose_name='Показывать другим посетителям мою страницу пользователя на сайте (дату рождения и другие личные данные никто видеть не будет)',
		default=True, blank=True)
	avatar = models.ImageField(verbose_name='Аватар (не больше 2 мегабайт)', max_length=255, upload_to=avatar_name,
		validators=[validate_image], blank=True)
	avatar_thumb = models.ImageField(max_length=255, upload_to=avatar_thumb_name, blank=True)
	email_is_verified = models.BooleanField(verbose_name='Адрес электронной почты подтверждён', default=False, blank=True)
	email_verification_code = models.CharField(verbose_name='Код для проверки электронного адреса',
		max_length=results_util.VERIFICATION_CODE_LENGTH, blank=True)

	unsubscribe_verification_code = models.CharField(verbose_name='Код для отписки от рассылок',
		max_length=results_util.VERIFICATION_CODE_LENGTH, default=results_util.generate_verification_code, blank=True)
	ok_to_send_news = models.BooleanField(verbose_name='Хочу получать письма с новостями сайта (не чаще раза в две недели)', default=True,
		blank=True)
	ok_to_send_results = models.BooleanField(verbose_name='Хочу получать письма о появлении в базе новых моих результатов', default=True,
		blank=True)
	ok_to_send_on_related_events = models.BooleanField(verbose_name='Хочу получать письма о появлении в календаре забегов, в которых участвовал(а) в последние 2 года',
		default=True, blank=True)

	agrees_with_policy = models.BooleanField(verbose_name='Согласен на обработку моих персональных данных *', default=False)
	agrees_with_data_dissemination = models.BooleanField(verbose_name='Согласен на распространение моих персональных данных *', default=False)
	hide_parkruns_in_calendar = models.BooleanField(verbose_name='По умолчанию скрывать паркраны на страницах календаря', default=False, blank=True)
	strava_account = models.CharField(verbose_name='Аккаунт в Strava (имя или число после strava.com/athletes/)', max_length=50, blank=True)

	n_starts = models.SmallIntegerField(verbose_name='Число финишей', default=None, null=True, blank=True)
	total_length = models.IntegerField(verbose_name='Общая пройденная дистанция в метрах', default=None, null=True, blank=True)
	total_time = models.BigIntegerField(verbose_name='Общее время на забегах в сотых секунды', default=None, null=True, blank=True)
	has_many_distances = models.BooleanField(verbose_name='Имеет ли больше разных дистанций, чем отображаем по умолчанию', default=False)

	is_extended_editor = models.BooleanField(verbose_name='Может редактировать старые забеги', default=False)

	is_active_paid_account = models.BooleanField(verbose_name='Оплачен ли аккаунт на сегодня', default=False)
	paid_until = models.DateField(verbose_name='Дата окончания действия оплаты аккаунта', default=None, null=True, blank=True)
	club_name = models.CharField(verbose_name='Клуб', max_length=50, blank=True)

	to_ask_fill_marks = models.BooleanField(verbose_name='Предлагать ли оценивать все забеги', default=True)
	when_to_ask_fill_marks = models.DateField(verbose_name='Дата, раньше которой не предлагать оценивать все забеги',
		default=DEFAULT_WHEN_TO_ASK_FILL_MARKS)
	def clean(self):
		self.midname = self.midname.strip()
	def make_thumbnail(self):
		return make_thumb(self.avatar, self.avatar_thumb, 200, 400)
	def get_name_condition(self):
		return get_name_condition(self.user.last_name, self.user.first_name, self.midname)
	def create_runner(self, creator, comment=''):
		user = self.user
		runner = Runner.objects.create(
			user=user,
			lname=user.last_name,
			fname=user.first_name,
			midname=self.midname,
			gender=self.gender,
			birthday=self.birthday,
			birthday_known=(self.birthday is not None),
			city=self.city,
			created_by=creator,
		)
		log_obj_create(creator, runner, ACTION_CREATE, comment=comment, verified_by=creator)
		return runner
	def can_add_results_to_others(self):
		if is_admin(self.user) or self.user.club_editor_set.exists():
			return True
		return self.get_active_klb_participants_with_teams().exists()
	def get_club_set_to_add_results(self):
		club_ids = set()
		club_editor_set = self.user.club_editor_set
		if club_editor_set.exists():
			club_ids = set(self.user.club_editor_set.values_list('club_id', flat=True))
		return Club.objects.filter(pk__in=club_ids).order_by('name') if club_ids else []
	def is_female(self):
		return self.gender == GENDER_FEMALE
	def has_password(self):
		return self.user.password[0] != '!'
	def get_avatar_url(self):
		if self.avatar:
			return f'/{self.avatar.name}'
		return ''
	def get_avatar_thumb_url(self):
		if self.avatar_thumb:
			return f'/{self.avatar_thumb.name}'
		return ''
	def get_total_length(self):
		return total_length2string(self.total_length)
	def get_total_time(self):
		return total_time2string(self.total_time)
	def get_strava_link(self):
		return f'https://www.strava.com/athletes/{self.strava_account}'
	def get_reverse_url(self, target):
		return reverse(target, kwargs={'user_id': self.user.id})
	def get_absolute_url(self):
		return self.get_reverse_url('results:user_details')
	def get_history_url(self):
		return self.get_reverse_url('editor:user_changes_history')
	def get_absolute_url_full(self):
		return self.get_reverse_url('results:user_details_full')
	def get_update_stat_url(self):
		return self.get_reverse_url('editor:user_update_stat')
	def get_find_results_url(self):
		return self.get_reverse_url('results:find_results')
	def get_our_editor_url(self):
		return self.get_reverse_url('results:my_details')
	def get_strava_links_url(self):
		return self.get_reverse_url('results:my_strava_links')
	def get_add_series_editor_url(self):
		return self.get_reverse_url('editor:user_add_series_editor')
	def get_remove_series_editor_url(self):
		return self.get_reverse_url('editor:user_remove_series_editor')
	def get_merge_url(self):
		return self.get_reverse_url('editor:user_merge')
	def get_editor_url(self):
		return f'/admin/auth/user/{self.user.id}'
	def get_profile_editor_url(self):
		return f'/admin/results/user_profile/{self.id}'
	def __str__(self):
		return self.user.get_full_name()

ACTION_CREATE = 0
ACTION_UPDATE = 1
ACTION_DELETE = 2
ACTION_DOCUMENT_CREATE = 3
ACTION_DOCUMENT_UPDATE = 4
ACTION_DOCUMENT_DELETE = 5
ACTION_NEWS_CREATE = 6
ACTION_NEWS_UPDATE = 7
ACTION_NEWS_DELETE = 8
ACTION_RACE_CREATE = 9
ACTION_RACE_UPDATE = 10
ACTION_RACE_DELETE = 11
ACTION_UNKNOWN = 12
ACTION_RESULTS_LOAD = 13
ACTION_RESULT_CREATE = 14
ACTION_RESULT_UPDATE = 15
ACTION_RESULT_DELETE = 16
ACTION_SOCIAL_POST = 17
ACTION_RESULT_CLAIM = 18
ACTION_RESULT_UNCLAIM = 19
ACTION_UNOFF_RESULT_CREATE = 20
ACTION_MERGE_FAILED = 21
ACTION_SPLIT_CREATE = 22
ACTION_SPLIT_UPDATE = 23
ACTION_SPLIT_DELETE = 24
ACTION_RESULT_MESSAGE_SEND = 31
ACTION_NEWSLETTER_SEND = 34
ACTION_CLUB_MEMBER_CREATE = 52
ACTION_CLUB_MEMBER_UPDATE = 53
ACTION_CLUB_MEMBER_DELETE = 54
ACTION_MARKS_CREATE = 55
ACTION_MARKS_DELETE = 56
ACTION_RUNNER_LINK_CREATE = 60
ACTION_RUNNER_LINK_DELETE = 61
ACTION_EXTRA_NAME_CREATE = 62
ACTION_EXTRA_NAME_DELETE = 63
ACTION_RUNNER_PLATFORM_CREATE = 64
ACTION_RUNNER_PLATFORM_DELETE = 65
ACTION_SERIES_PLATFORM_CREATE = 66
ACTION_SERIES_PLATFORM_DELETE = 67
ACTION_TYPES = (
	('', 'Любое'),
	(ACTION_CREATE, 'Создание'),
	(ACTION_UPDATE, 'Изменение'),
	(ACTION_DELETE, 'Удаление'),
	(ACTION_DOCUMENT_CREATE, 'Создание документа'),
	(ACTION_DOCUMENT_UPDATE, 'Изменение документа'),
	(ACTION_DOCUMENT_DELETE, 'Удаление документа'),
	(ACTION_NEWS_CREATE, 'Создание новости'),
	(ACTION_NEWS_UPDATE, 'Изменение новости'),
	(ACTION_NEWS_DELETE, 'Удаление новости'),
	(ACTION_RACE_CREATE, 'Создание дистанции'),
	(ACTION_RACE_UPDATE, 'Изменение дистанции'),
	(ACTION_RACE_DELETE, 'Удаление дистанции'),
	(ACTION_UNKNOWN, 'Непонятное действие'),
	(ACTION_RESULTS_LOAD, 'Загрузка результатов дистанции'),
	(ACTION_RESULT_CREATE, 'Создание результата'),
	(ACTION_RESULT_UPDATE, 'Изменение результата'),
	(ACTION_RESULT_DELETE, 'Удаление результата'),
	(ACTION_SOCIAL_POST, 'Публикация в соцсети новости'),
	(ACTION_RESULT_CLAIM, 'Присвоение результата'),
	(ACTION_RESULT_UNCLAIM, 'Отсоединение результата'),
	(ACTION_UNOFF_RESULT_CREATE, 'Добавление неофициального результата'),
	(ACTION_MERGE_FAILED, 'Не удалось объединить с бегуном'),
	(ACTION_SPLIT_CREATE, 'Создание промежуточного результата'),
	(ACTION_SPLIT_UPDATE, 'Изменение промежуточного результата'),
	(ACTION_SPLIT_DELETE, 'Удаление промежуточного результата'),
	(ACTION_RESULT_MESSAGE_SEND, 'Отправка новых результатов в письме'),
	(ACTION_NEWSLETTER_SEND, 'Отправка письма с рассылкой'),
	(ACTION_CLUB_MEMBER_CREATE, 'Создание члена клуба'),
	(ACTION_CLUB_MEMBER_UPDATE, 'Изменение члена клуба'),
	(ACTION_CLUB_MEMBER_DELETE, 'Удаление члена клуба'),
	(ACTION_MARKS_CREATE, 'Добавление оценок на дистанции'),
	(ACTION_MARKS_DELETE, 'Удаление оценок на дистанции'),
	(ACTION_RUNNER_LINK_CREATE, 'Добавление ссылки на страницу о бегуне'),
	(ACTION_RUNNER_LINK_DELETE, 'Удаление ссылки на страницу о бегуне'),
	(ACTION_EXTRA_NAME_CREATE, 'Добавление дополнительного имени бегуна'),
	(ACTION_EXTRA_NAME_DELETE, 'Удаление дополнительного имени бегуна'),
	(ACTION_RUNNER_PLATFORM_CREATE, 'Добавление ID бегуна на платформе'),
	(ACTION_RUNNER_PLATFORM_DELETE, 'Удаление ID бегуна на платформе'),
	(ACTION_SERIES_PLATFORM_CREATE, 'Добавление ID серии на платформе'),
	(ACTION_SERIES_PLATFORM_DELETE, 'Удаление ID серии на платформе'),
)
RESULT_ACTIONS = (
	ACTION_RESULT_CREATE,
	ACTION_RESULT_UPDATE,
	ACTION_RESULT_DELETE,
	ACTION_RESULT_CLAIM,
	ACTION_RESULT_UNCLAIM,
	ACTION_UNOFF_RESULT_CREATE,
)
UPDATE_COMMENT_FIELD_NAME = 'action_comment'
class Table_update(models.Model):
	model_name = models.CharField(verbose_name='Название модели таблицы', max_length=40)
	row_id = models.IntegerField(verbose_name='id строки в таблице', default=0)
	child_id = models.IntegerField(verbose_name='id затронутого документа или новости', default=None, null=True, blank=True, db_index=True)
	action_type = models.SmallIntegerField(verbose_name='Действие', choices=ACTION_TYPES, db_index=True)
	user = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name='Совершивший действие',
		on_delete=models.SET_NULL, null=True, blank=True)
	is_verified = models.BooleanField(verbose_name='Проверен администратором', default=True, blank=True, db_index=True)
	verified_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name='Одобрил', related_name='table_update_verified_set',
		on_delete=models.SET_NULL, default=None, null=True, blank=True)
	verified_time = models.DateTimeField(verbose_name='Время одобрения', default=None, null=True, blank=True)
	added_time = models.DateTimeField(verbose_name='Время занесения в БД', auto_now_add=True)
	class Meta:
		indexes = [
			models.Index(fields=['user', 'added_time', 'action_type', 'model_name']),
			models.Index(fields=['verified_by', 'added_time', 'action_type', 'model_name']),
			models.Index(fields=['row_id', 'is_verified', 'action_type']),
		]
	def append_comment(self, comment):
		if comment:
			field_update, _ = Field_update.objects.get_or_create(table_update=self, field_name=UPDATE_COMMENT_FIELD_NAME)
			field_update.new_value += '; ' + comment
			field_update.save()
	def add_field(self, field_name, value):
		Field_update.objects.create(table_update=self, field_name=field_name, new_value=str(value)[:MAX_VALUE_LENGTH])
	def verify(self, user, comment='') -> Tuple[bool, str]:
		if self.is_verified:
			return False, f'Действие с id {self.id} уже одобрил администратор {self.verified_by.get_full_name()}.'
		self.is_verified = True
		self.verified_by = user
		self.verified_time = datetime.datetime.now()
		self.save()
		self.append_comment(comment)
		return True, ''
	def get_field(self, field):
		return self.field_update_set.filter(field_name=field).first()
	def get_loaded_from(self):
		return self.get_field('loaded_from')
	def get_comment(self):
		return self.get_field('comment')
	def get_absolute_url(self):
		return reverse('editor:action_details', kwargs={'table_update_id': self.id})
	def __str__(self):
		return f'Объект {self.model_name} с id {self.row_id}'

MAX_VALUE_LENGTH = 255
class Field_update(models.Model):
	table_update = models.ForeignKey(Table_update, verbose_name='Обновление таблицы',
		on_delete=models.CASCADE, null=True, default=None, blank=True)
	field_name = models.CharField(verbose_name='Название изменённого поля', max_length=40)
	new_value = models.CharField(verbose_name='Новое значение поля', max_length=MAX_VALUE_LENGTH, blank=True)

# Manual creation for unofficial series and result, for result claim
def log_obj_create(user, obj, action, field_list: Optional[list[str]]=None, child_object: Any=None, comment='', verified_by=None):
	child_id = child_object.id if child_object else None
	obj_with_attrs = child_object if child_object else obj # When adding result, we need its attributes, not event's
	if verified_by:
		is_verified = True
	else:
		is_verified = is_admin(user)
	table_update = Table_update.objects.create(model_name=obj.__class__.__name__, child_id=child_id,
		row_id=obj.id, action_type=action, user=user, is_verified=is_verified, verified_by=verified_by)
	log_empty_fields = True
	if field_list is None:
		log_empty_fields = False # We log them only if the field_set is provided
		field_list = [f.name for f in obj_with_attrs.__class__._meta.get_fields()]
	for field in field_list:
		if hasattr(obj_with_attrs, field) and (log_empty_fields or getattr(obj_with_attrs, field)):
			Field_update.objects.create(table_update=table_update, field_name=field,
				new_value=str(getattr(obj_with_attrs, field))[:MAX_VALUE_LENGTH])
	if comment:
		Field_update.objects.create(table_update=table_update, field_name=UPDATE_COMMENT_FIELD_NAME,
			new_value=comment[:MAX_VALUE_LENGTH])
	if (action == ACTION_RESULT_UPDATE) and ('runner' in field_list):
		Strike_queue.objects.get_or_create(series_id=obj.series_id, distance_id=child_object.race.distance_id)
def log_obj_delete(user, obj, child_object=None, action_type=ACTION_DELETE, comment='', verified_by=None):
	child_id = child_object.id if child_object else None
	is_verified = (verified_by is not None) or is_admin(user)
	table_update = Table_update.objects.create(model_name=obj.__class__.__name__, row_id=obj.id, action_type=action_type,
		user=user, is_verified=is_verified, verified_by=verified_by, child_id=child_id)
	if comment:
		Field_update.objects.create(table_update=table_update, field_name=UPDATE_COMMENT_FIELD_NAME,
			new_value=comment[:MAX_VALUE_LENGTH])

STATUS_FINISHED = 0
STATUS_DNF = 1
STATUS_DSQ = 2
STATUS_DNS = 3
STATUS_UNKNOWN = 4
STATUS_COMPLETED = 5

RESULT_SOURCE_DEFAULT = 0
RESULT_SOURCE_USER = 2
RESULT_SOURCES = (
	(RESULT_SOURCE_DEFAULT, 'из протокола'),
	(RESULT_SOURCE_USER, 'от пользователя'),
)
MAX_RESULT_COMMENT_LENGTH = 200
MAX_BIB_LENGTH = 10
class Result(models.Model):
	race = models.ForeignKey(Race, verbose_name='Дистанция', on_delete=models.CASCADE)
	user = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name='Пользователь', on_delete=models.SET_NULL, default=None, null=True, blank=True)
	runner = models.ForeignKey('Runner', verbose_name='id бегуна', on_delete=models.SET_NULL, null=True, default=None, blank=True)
	id_on_platform = models.CharField(verbose_name='ID результата на платформе, откуда загружен', max_length=30, blank=True, db_index=True)
	runner_id_on_platform = models.BigIntegerField(verbose_name='ID бегуна на платформе, откуда загружен', default=None, null=True, blank=True, db_index=True)
	country = models.ForeignKey(Country, verbose_name='Страна', on_delete=models.PROTECT, default=None, null=True, blank=True)
	city = models.ForeignKey(City, verbose_name='Город', on_delete=models.PROTECT, default=None, null=True, blank=True)
	club = models.ForeignKey(Club, verbose_name='Клуб', on_delete=models.PROTECT, default=None, null=True, blank=True)
	club_name = models.CharField(verbose_name='Клуб (название)', max_length=100, blank=True)

	name_raw = models.CharField(verbose_name='Имя целиком (сырое)', max_length=100, blank=True)
	lname_raw = models.CharField(verbose_name='Фамилия (сырая)', max_length=100, blank=True)
	fname_raw = models.CharField(verbose_name='Имя (сырое)', max_length=70, blank=True)
	midname_raw = models.CharField(verbose_name='Отчество (сырое)', max_length=50, blank=True)
	result_raw = models.CharField(verbose_name='Результат (сырой)', max_length=20, blank=True)
	gun_time_raw = models.CharField(verbose_name='Грязное время (сырое)', max_length=20, blank=True)
	country_raw = models.CharField(verbose_name='Страна (сырая)', max_length=100, blank=True)
	region_raw = models.CharField(verbose_name='Регион (сырой)', max_length=100, blank=True)
	city_raw = models.CharField(verbose_name='Город (сырой)', max_length=100, blank=True)
	club_raw = models.CharField(verbose_name='Клуб (сырой)', max_length=100, blank=True)
	birthyear_raw = models.SmallIntegerField(verbose_name='Год рождения (сырой)', default=None, null=True, blank=True)
	birthday_raw = models.DateField(verbose_name='Дата рождения (сырая)', default=None, null=True, blank=True)
	age_raw = models.SmallIntegerField(verbose_name='Возраст (сырой)', default=None, null=True, blank=True)
	place_raw = models.IntegerField(verbose_name='Место в абсолютном зачёте (сырое)', default=None, null=True, blank=True)
	place_gender_raw = models.IntegerField(verbose_name='Место среди своего пола (сырое)', default=None, null=True, blank=True)
	place_category_raw = models.IntegerField(verbose_name='Место в своей группе (сырое)', default=None, null=True, blank=True)
	comment_raw = models.CharField(verbose_name='Комментарий (сырой)', max_length=200, blank=True)
	status_raw = models.CharField(verbose_name='Статус (сырой)', max_length=10, choices=results_util.RESULT_STATUSES)
	bib_raw = models.CharField(verbose_name='Стартовый номер (сырой)', max_length=MAX_BIB_LENGTH, blank=True)
	category_raw = models.CharField(verbose_name='Группа (сырая)', max_length=MAX_CATEGORY_LENGTH, blank=True)
	gender_raw = models.CharField(verbose_name='Пол (сырой)', max_length=10, blank=True)

	result = models.IntegerField(verbose_name='Результат', default=0) # in centiseconds/meters/steps/...
	gun_result = models.IntegerField(verbose_name='Грязное время', default=None, null=True, blank=True) # in centiseconds
	time_for_car = models.IntegerField(verbose_name='Время для странных дистанций', default=None, null=True, blank=True) # in centiseconds
	status = models.SmallIntegerField(verbose_name='Статус', default=0, choices=results_util.RESULT_STATUSES)
	category_size = models.ForeignKey(Category_size, verbose_name='Ссылка на размер группы',
		on_delete=models.PROTECT, default=None, null=True, blank=True)
	place = models.IntegerField(verbose_name='Место в абсолютном зачёте', default=None, null=True, blank=True)
	place_gender = models.IntegerField(verbose_name='Место среди своего пола', default=None, null=True, blank=True)
	place_category = models.IntegerField(verbose_name='Место в своей группе', default=None, null=True, blank=True)
	comment = models.CharField(verbose_name='Комментарий', max_length=MAX_RESULT_COMMENT_LENGTH, blank=True)

	bib = models.CharField(verbose_name='Стартовый номер', max_length=MAX_BIB_LENGTH, blank=True)
	birthday = models.DateField(verbose_name='День или год рождения', default=None, null=True, blank=True, db_index=True)
	# If true, we know exact date of birth (otherwise birthday must be 01.01.)
	birthday_known = models.BooleanField(verbose_name='Известен ли день рождения', default=False, db_index=True)
	age = models.SmallIntegerField(verbose_name='Возраст', default=None, null=True, blank=True, db_index=True)
	lname = models.CharField(verbose_name='Фамилия', max_length=100, blank=True)
	fname = models.CharField(verbose_name='Имя', max_length=70, blank=True, db_index=True)
	midname = models.CharField(verbose_name='Отчество', max_length=50, blank=True, db_index=True)
	gender = models.SmallIntegerField(verbose_name='Пол', default=results_util.GENDER_UNKNOWN, choices=results_util.GENDER_CHOICES)
	do_not_count_in_stat = models.BooleanField(verbose_name='Не учитывать в статистике бегуна', default=False, db_index=True)
	bib_given_to_unknown = models.BooleanField(verbose_name='С этим номером бежал кто-то другой, не знаем, кто', default=False, db_index=True)
	is_improbable = models.BooleanField(verbose_name='Неправдоподобно высокий результат. Не учитывать в рекордах', default=False, db_index=True)
	wind = models.DecimalField(verbose_name='Сила ветра, м/с', max_digits=4, decimal_places=2, default=None, null=True, blank=True)

	source = models.SmallIntegerField(verbose_name='Источник результата', default=RESULT_SOURCE_DEFAULT, choices=RESULT_SOURCES)
	loaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name='Загрузил в БД',
		on_delete=models.SET_NULL, default=None, null=True, blank=True, related_name='results_loaded_by_user')
	added_time = models.DateTimeField(verbose_name='Время занесения в БД', auto_now_add=True, db_index=True)
	last_update = models.DateTimeField(verbose_name='Время последнего обновления', auto_now=True)
	class Meta:
		indexes = [
			models.Index(fields=['lname', 'fname', 'midname']),
			models.Index(fields=['lname', 'fname', 'birthday', 'birthday_known', 'source', 'runner']),
			models.Index(fields=['race', 'status', 'place', 'result', 'lname', 'fname', 'midname', 'gender', 'category_size']),
			models.Index(fields=['race', 'status', 'place', 'result', 'lname', 'fname', 'midname', 'category_size']),
			models.Index(fields=['race', 'status', 'place_gender']),
			models.Index(fields=['race', 'status', 'place_category']),
			models.Index(fields=['race', 'source', 'gender', 'place_gender', 'lname', 'fname']),
			models.Index(fields=['race', 'source', 'status', 'result', 'category_size']),
			models.Index(fields=['race', 'lname', 'fname', 'midname']),
			models.Index(fields=['race', 'gender', 'place_gender']),
			models.Index(fields=['birthday_known', 'birthday']),
			models.Index(fields=['loaded_by', 'added_time']),
		]
	def clean(self):
		if self.birthday is None:
			self.birthday_known = False
	def add_for_mail(self, old_user=None):
		if self.user is None:
			return 0
		if self.status != STATUS_FINISHED:
			return 0
		if old_user and (old_user == self.user):
			return 0
		if self.user.result_for_mail_set.filter(result=self, is_sent=False).exists():
			return 0
		Result_for_mail.objects.create(user=self.user, result=self)
		return 1
	def try_add_birthday_to_runner(self, action_user):
		runner = self.runner
		if self.birthday_known:
			if not runner.birthday_known:
				runner.birthday = self.birthday
				runner.birthday_known = True
				runner.save()
				log_obj_create(action_user, runner, ACTION_UPDATE, field_list=['birthday', 'birthday_known'],
					comment=f'При добавлении результата с id {self.id}')
		elif self.birthday:
			if runner.birthday is None:
				runner.birthday = self.birthday
				runner.birthday_known = False
				runner.save()
				log_obj_create(action_user, runner, ACTION_UPDATE, field_list=['birthday'],
					comment=f'При добавлении результата с id {self.id}')
	# We want to add result 'self' to runner 'runner'.
	# If self.runner != None, we try to replace runner with self.runner
	def claim_for_runner(self, action_user, runner, comment='', allow_merging_runners=False):
		self.refresh_from_db()
		runner.refresh_from_db()
		if self.runner == runner: # Great! No work is needed
			if self.user != runner.user:
				self.user = runner.user
				self.save()
				log_obj_create(action_user, self.race.event, ACTION_RESULT_UPDATE, field_list=['user'],
					child_object=self, comment=comment)
			return True, ''
		if self.user and runner.user and (self.user != runner.user):
			return False, f'Результат {self} на забеге {self.race.name_with_event()} уже засчитан другому пользователю — с id {self.user.id}.'
		from_same_race = self.race.result_set.filter(runner=runner).first()
		if from_same_race:
			return False, 'Этому бегуну уже засчитан результат {} на забеге {}. Нельзя иметь два результата на одном забеге.'.format(
				from_same_race, self.race.name_with_event())
		if runner.user:
			from_same_race = self.race.result_set.filter(user=runner.user).first()
			if from_same_race:
				return False, 'Этому пользователю уже засчитан результат {} на забеге {}. Нельзя иметь два результата на одном забеге.'.format(
					from_same_race, self.race.name_with_event())
		if self.runner:
			if not allow_merging_runners:
				return False, 'Для присоединения результата {} бегуна {} со старта {} (id {}) нужно сначала объединить этого бегуна '.format(
					self.id, self.runner.get_name_and_id(), self.race.name_with_event(), self.race.id) \
					+ ' с бегуном {}'.format(runner.get_name_and_id())
			# So, self.runner != runner
			old_runner = self.runner
			res, msgError = runner.merge(old_runner, action_user)
			if res:
				log_obj_delete(action_user, old_runner, comment='При слиянии с бегуном {}'.format(runner.get_name_and_id()))
				old_runner.delete()
			return res, msgError
		# So, the result has no runner yet
		self.runner = runner
		field_list = ['runner']
		if runner.user:
			self.user = runner.user
			field_list.append('user')
		self.save()
		log_obj_create(action_user, self.race.event, ACTION_RESULT_UPDATE, field_list=field_list,
			child_object=self, comment=comment)
		if self.user and (self.user != action_user):
			self.add_for_mail()
		self.try_add_birthday_to_runner(action_user)
		return True, ''
	def unclaim_from_user(self, comment=''): # Returns <was result deleted?>
		user = self.user
		if self.source == RESULT_SOURCE_USER:
			log_obj_create(user, self.race.event, ACTION_RESULT_DELETE, child_object=self,
				comment=f'При отклеивании результата от пользователя с id {user.id if user else ""}. Комментарий: "{comment}"')
			self.delete()
			return True
		else:
			self.user = None
			self.save()
			log_obj_create(user, self.race.event, ACTION_RESULT_UPDATE, field_list=['user'], child_object=self,
				comment=f'При отклеивании результата от пользователя с id {user.id if user else ""}. Комментарий: "{comment}"')
			return False
	def unclaim_from_runner(self, user, comment=''): # When deleting from KLBMatch
		field_list = []
		runner = self.runner
		if runner:
			self.runner = None
			field_list.append('runner')
		if self.user:
			self.user = None
			field_list.append('user')
		if field_list:
			self.save()
			log_obj_create(user, self.race.event, ACTION_RESULT_UPDATE, field_list=field_list, child_object=self,
				comment='При удалении из КЛБМатча отсоединён от бегуна с id {}'.format(runner.id if runner else ''))
	def strClub(self):
		return self.club.name if self.club else self.club_name
	def clubLink(self):
		if self.club:
			return f'<a href="{self.club.get_absolute_url()}">{self.club.name}</a>'
		else:
			return self.club_name
	def strCity(self): # TODO
		if self.city:
			return self.city.nameWithCountry()
		else:
			fields = []
			if self.city_raw:
				fields.append(self.city_raw)
			if self.region_raw:
				fields.append(self.region_raw)
			if self.country_raw:
				fields.append(self.country_raw)
			return ', '.join(fields)
	def strCityRaw(self):
		fields = []
		if self.city_raw:
			fields.append(self.city_raw)
		if self.region_raw:
			fields.append(self.region_raw)
		if self.country_raw:
			fields.append(self.country_raw)
		return ', '.join(fields)
	def strCountry(self):
		if self.country:
			return self.country.name
		else:
			return self.country_name
	def strName(self):
		if self.lname or self.fname:
			if self.midname:
				return self.fname + ' ' + self.midname + ' ' + self.lname
			else:
				return self.fname + ' ' + self.lname
		elif self.runner:
			return self.runner.name()
		else:
			return '' # self.name_raw
	def strBirthday(self, with_nbsp=True, short_format=False):
		if self.birthday_known:
			return results_util.date2str(self.birthday, with_nbsp=with_nbsp, short_format=short_format)
		elif self.birthday:
			return str(self.birthday.year)
		else:
			return ''
	def strBirthdayShort(self):
		return self.strBirthday(short_format=True)
	def strBirthday_raw(self):
		if self.birthday_raw:
			return results_util.date2str(self.birthday_raw)
		elif self.birthyear_raw:
			return str(self.birthyear_raw)
		else:
			return ''
	def strPace(self):
		if self.status == STATUS_FINISHED:
			value = self.race.get_pace(self.result)
			if value:
				seconds = value % 60
				minutes = value // 60
				return f'{minutes}:{str(seconds).zfill(2)}/km'
		return ''
	def get_place(self):
		if not self.place:
			return ''
		res = str(self.place)
		if self.race.n_participants_finished:
			res += f'&nbsp;of&nbsp;{self.race.n_participants_finished}'
		return res
	def get_gender_place(self):
		if not self.gender or not self.place_gender:
			return ''
		res = str(self.place_gender)
		gender_size = 0
		if self.gender == results_util.GENDER_MALE:
			gender_size = self.race.n_participants_finished_male
		elif self.gender == results_util.GENDER_FEMALE:
			gender_size = self.race.n_participants_finished_female
		elif self.gender == results_util.GENDER_NONBINARY:
			gender_size = self.race.n_participants_finished_nonbinary
		if gender_size:
			res += f'&nbsp;of&nbsp;{gender_size}'
		return res
	def get_category_place(self):
		if not self.place_category:
			return ''
		res = str(self.place_category)
		if self.category_size and self.category_size.size:
			res += f'&nbsp;of&nbsp;{self.category_size.size}'
		return res
	def get_runner_age(self):
		if self.runner and self.runner.birthday_known:
			return self.race.get_age_on_event_date(self.runner.birthday)
		return None
	def get_reverse_url(self, target):
		return reverse(target, kwargs={'result_id': self.id})
	def get_absolute_url(self):
		return self.get_reverse_url('results:result_details')
	def get_runner_or_user_url(self):
		if self.user and self.user.is_active and self.user.user_profile and self.user.user_profile.is_public:
			return self.user.user_profile.get_absolute_url()
		if self.runner:
			return self.runner.get_absolute_url()
		return ''
	def get_editor_url(self):
		return self.get_reverse_url('editor:result_details')
	def get_claim_url(self):
		return self.get_reverse_url('results:claim_result')
	def get_unclaim_url(self):
		return self.get_reverse_url('results:unclaim_result')
	def get_unclaim_with_race_url(self):
		return reverse('results:unclaim_result', kwargs={'result_id': self.id, 'race_id': self.race.id})
	def get_delete_unofficial_url(self):
		return self.get_reverse_url('results:delete_unofficial_result')
	def get_delete_url(self):
		return self.get_reverse_url('editor:result_delete')
	def get_splits_update_url(self):
		return self.get_reverse_url('editor:result_splits_update')
	def get_gun_time(self):
		return self.race.distance.strResult(self.gun_result) if self.gun_result else ''
	def is_electronic(self): # For TYPE_METERS only
		if self.race.timing == TIMING_ELECTRONIC:
			return True
		if self.race.timing == TIMING_HAND:
			return False
		return (self.result % 10) > 0
	def full_comment(self):
		parts = []
		if self.comment:
			parts.append(self.comment)
		if self.is_improbable:
			parts.append('Improbably good result.')
		if self.bib_given_to_unknown:
			parts.append('As we understand, someone else ran with this bib')
		return '<br/>'.join(parts)
	def __str__(self):
		return self.race.distance.strResult(self.result, timing=self.race.timing) \
			if (self.status == STATUS_FINISHED) else self.get_status_display()

class Lost_result(models.Model):
	''' Если при перезагрузке протокола удаляем официальный результат, который был привязан к бегуну и/или пользователю,
	и не нашли сразу нового результата, к которому сделать те же привязки, то кладем данные о результате сюда '''
	user = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name='Пользователь',
		on_delete=models.SET_NULL, default=None, null=True, blank=True)
	runner = models.ForeignKey('Runner', verbose_name='id бегуна',
		on_delete=models.SET_NULL, default=None, null=True, blank=True)
	race = models.ForeignKey(Race, verbose_name='Дистанция', on_delete=models.CASCADE)
	result = models.IntegerField(verbose_name='Результат', default=0) # in centiseconds/meters/steps/...
	status = models.SmallIntegerField(verbose_name='Статус', default=0, choices=results_util.RESULT_STATUSES)
	lname = models.CharField(verbose_name='Фамилия', max_length=100, blank=True)
	fname = models.CharField(verbose_name='Имя', max_length=100, blank=True)
	midname = models.CharField(verbose_name='Отчество', max_length=100, blank=True)
	strava_link = models.BigIntegerField(verbose_name='Ссылка на пробежку на Страве')
	loaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name='Загрузил в БД',
		on_delete=models.SET_NULL, default=None, null=True, blank=True, related_name='lost_results_loaded_by_user')
	added_time = models.DateTimeField(verbose_name='Время занесения в БД', auto_now_add=True)
	class Meta:
		indexes = [
			models.Index(fields=['race', 'lname', 'fname', 'status', 'result']),
		]
	def __str__(self):
		if self.status == STATUS_FINISHED:
			return self.race.distance.strResult(self.result)
		else:
			return self.get_status_display()

class Unclaimed_result(models.Model):
	""" Если кто-то указал, что этот результат не относится к бегуну и не надо его показывать при поиске """
	user = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name='Пользователь',
		on_delete=models.CASCADE, default=None, null=True, blank=True) # TODO: delete
	runner = models.ForeignKey('Runner', verbose_name='Бегун', on_delete=models.CASCADE, default=None, null=True, blank=True) # TODO: make non-null
	result = models.ForeignKey(Result, verbose_name='Результат', on_delete=models.CASCADE)
	added_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name='Добавил в БД',
		on_delete=models.SET_NULL, default=None, null=True, blank=True, related_name='unclaimed_results_added_by_user')
	added_time = models.DateTimeField(verbose_name='Время занесения в БД', auto_now_add=True)

class Result_not_for_runner(models.Model):
	''' Если мы решили, что бежал точно не этот бегун, и нужно запретить присоединять этот результат к этому бегуну '''
	runner = models.ForeignKey('Runner', verbose_name='Бегун', on_delete=models.CASCADE)
	result = models.ForeignKey(Result, verbose_name='Результат', on_delete=models.SET_NULL, null=True)
	value = models.IntegerField(verbose_name='Значение результата') # На случай, если объект Result будет удалён
	race = models.ForeignKey(Race, verbose_name='Дистанция', on_delete=models.CASCADE) # На тот же случай
	added_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name='Добавил в БД', on_delete=models.SET_NULL, null=True)
	added_time = models.DateTimeField(verbose_name='Время занесения в БД', auto_now_add=True)
	class Meta:
		constraints = [
			models.UniqueConstraint(fields=['runner', 'result'], name='runner_result'),
		]

class Result_for_mail(models.Model):
	''' Для свежепривязанных результатов, о которых хотим послать письмо пользователю '''
	user = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name='Пользователь', on_delete=models.CASCADE)
	result = models.ForeignKey(Result, verbose_name='Результат', on_delete=models.CASCADE)
	is_sent = models.BooleanField(verbose_name='Отправлено ли письмо пользователю', default=False, db_index=True)
	added_time = models.DateTimeField(verbose_name='Время занесения в БД', auto_now_add=True)
	sent_time = models.DateTimeField(verbose_name='Время отправки письма', default=None, null=True, blank=True)

class Result_on_strava(models.Model):
	result = models.OneToOneField(Result, verbose_name='Результат', on_delete=models.CASCADE)
	link = models.BigIntegerField(verbose_name='Ссылка на пробежку на Страве')
	tracker = models.SmallIntegerField(verbose_name='Тип ссылки на пробежку', default=results_util.TRACKER_TYPE_STRAVA, choices=results_util.TRACKER_TYPES, db_index=True)
	added_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name='Добавил в БД',
		on_delete=models.SET_NULL, default=None, null=True, blank=True, related_name='results_on_strava_added_by_user')
	added_time = models.DateTimeField(verbose_name='Время занесения в БД', auto_now_add=True)
	def __str__(self):
		if not self.link:
			return ''
		if self.tracker == results_util.TRACKER_TYPE_STRAVA:
			return f'https://{results_util.STRAVA_ACTIVITY_PREFIX}{self.link}'
		if self.tracker == results_util.TRACKER_TYPE_GARMIN:
			return f'https://{results_util.GARMIN_ACTIVITY_PREFIX}{self.link}'
		return ''

class Split(models.Model):
	result = models.ForeignKey(Result, verbose_name='Итоговый результат', on_delete=models.CASCADE)
	distance = models.ForeignKey(Distance, verbose_name='Промежуточная дистанция', on_delete=models.PROTECT)
	value = models.IntegerField(verbose_name='Значение', default=0) # in centiseconds/meters/steps/...
	class Meta:
		constraints = [
			models.UniqueConstraint(fields=['result', 'distance'], name='result_distance'),
		]
	def __str__(self):
		return self.distance.strResult(self.value)

class City_change(models.Model):
	model = models.CharField(max_length=100, blank=True)
	row_id = models.IntegerField(default=0)
	field_name = models.CharField(max_length=100, blank=True)
	id_old = models.IntegerField(default=0)
	name_old = models.CharField(max_length=100, blank=True)
	id_new = models.IntegerField(default=0)
	name_new = models.CharField(max_length=100, blank=True)
	user_id = models.IntegerField(default=0)
	user_email = models.CharField(max_length=MAX_EMAIL_LENGTH, blank=True)
	timestamp = models.DateTimeField(auto_now=True)

THUMBNAIL_SIZE = (240, 150)
def seconds_from_1970():
	return int(time.time())
def get_image_name(instance, thumb=False, full_path=False):
	res = 'new/img/' + str(instance.image_name)
	if thumb:
		res += '_1'
	res += instance.image_extension
	if full_path:
		res = os.path.join(settings.MEDIA_ROOT, res)
	return res
def create_image_name(instance, filename, thumb=False):
	obj_name = 'thumbnail' if thumb else 'image'
	write_log('{} NEWS_IMAGE_CREATE Trying to upload {} {} for news {}, event {}.'.format(
		datetime.datetime.now(), obj_name,
		filename, instance.title, instance.event))
	if not instance.image_name:
		instance.image_name = seconds_from_1970()
	if not instance.image_extension:
		instance.image_extension = '.' + file_extension(filename, 'jpg')
	filename = get_image_name(instance, thumb=thumb)
	full_name = get_image_name(instance, thumb=thumb, full_path=True)
	write_log(f'File to create {obj_name} is {filename}. Full name is "{full_name}". Does it exist? {os.path.exists(full_name)}')
	try:
		if os.path.exists(full_name):
			os.remove(full_name)
	except:
		pass
	return filename
def create_image_thumb_name(instance, filename):
	return create_image_name(instance, filename, thumb=True)
IMAGE_ALIGN_CHOICES = (
	('l', 'картинка слева'),
	('r', 'картинка справа'),
	('n', 'не показывать картинку'),
)
NEWS_PREVIEW_LIMIT = 1000
class News(models.Model): # News on our site
	id = models.AutoField(primary_key=True)
	event = models.ForeignKey(Event, on_delete=models.SET_NULL, null=True, default=None, blank=True)
	date_posted = CustomDateTimeField(verbose_name='Время публикации', default=timezone.now, db_index=True)

	title = models.CharField(verbose_name='Название', max_length=255, blank=True)
	content = models.TextField(max_length=60000, verbose_name='Текст новости', blank=True)
	preview = models.TextField(max_length=2000, verbose_name='Автоматически сделанное превью', blank=True)
	manual_preview = models.CharField(max_length=400, verbose_name='Краткое содержание для ленты новостей (макс. 400 символов, отображается одновременно с названием новости)',
		blank=True)
	author = models.CharField(verbose_name='Автор', max_length=100, blank=False)
	# Made by CPanel
	image_name = models.IntegerField(default=0)
	# .jpg, .jpeg, .png, .gif or ''
	image_extension = models.CharField(max_length=5, blank=True)
	# l - to left edge, r - to rigth, n - no image, '' - rare value
	image_align = models.CharField(verbose_name='Как разместить картинку', max_length=1,
		choices=IMAGE_ALIGN_CHOICES, default='l')
	# Link to image:	 http://probeg.org/new/img/{{image_name}}{{image_extension}}
	# Link to thumbnail: http://probeg.org/new/img/{{image_name}}_1{{image_extension}}
	image = models.ImageField(verbose_name='Фотография', max_length=255, upload_to=create_image_name,
		blank=True)
	image_thumb = models.ImageField(verbose_name='Фотография-иконка', max_length=255, upload_to=create_image_thumb_name,
		blank=True)
	created_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name='Создал новость',
		on_delete=models.SET_NULL, default=None, null=True, blank=True)
	is_for_social = models.BooleanField(verbose_name='Только для соцсетей', default=False)
	is_for_blog = models.BooleanField(verbose_name='Относится к блогу сайта', default=False)
	def clean(self):
		self.content = replace_symbols(self.content)
		self.title = replace_symbols(self.title)
		self.preview = replace_symbols(self.preview)
		self.manual_preview = replace_symbols(self.manual_preview)
		if len(self.title) > 1:
			if (self.title[-1] == '.') and (self.title[-2] != '.'):
				self.title = self.title[:-1]
		if not self.image_name:
			self.image_name = seconds_from_1970()
		if self.image and not self.image_extension:
			self.image_extension = '.' + file_extension(self.image.name)
		if not self.manual_preview:
			self.make_preview()
	def clean_image_align(self):
		if not self.image_thumb:
			self.image_align = 'n'
		else:
			self.image_align = 'l'
	def delete_images(self):
		try:
			if self.image_thumb:
				self.image_thumb.delete()
			if self.image_extension: # Otherwise it seems there should be no image files
				full_name = get_image_name(self, full_path=True)
				if os.path.exists(full_name):
					os.remove(full_name)
				full_thumb_name = get_image_name(self, thumb=True, full_path=True)
				if os.path.exists(full_thumb_name):
					os.remove(full_thumb_name)
				self.image_extension = ''
		except:
			write_log('{} NEWS_IMAGE_DELETE Error when deleting images for news «{}», id {}.'.format(
				datetime.datetime.now(), self.title, self.id))
	def make_thumbnail(self):
		return make_thumb(self.image, self.image_thumb, 240, 150)
	def image_size(self):
		if self.image:
			try:
				return self.image.size
			except:
				return -1 # u'Ошибка. Возможно, файл не существует'
		else:
			return 0
	def plain_content(self):
		return bleach.clean(self.content.replace('<br', ' <br'), tags=[], attributes={}, styles=[], strip=True)
	def make_preview(self):
		plain_content = self.plain_content()
		cur_stop = -1
		if len(plain_content) < NEWS_PREVIEW_LIMIT:
			self.preview = plain_content
		else:
			plain_content = plain_content[:NEWS_PREVIEW_LIMIT]
			cur_stop = max([plain_content.rfind(symbol) for symbol in '.?!'])
			self.preview = plain_content[:cur_stop + 1] + '..'
	class Meta:
		indexes = [
			models.Index(fields=['event', 'date_posted']),
			models.Index(fields=['is_for_blog', 'date_posted']),
		]
	def twitter_max_length(self):
		return 92 if self.image else 116
	def get_reverse_url(self, target):
		return reverse(target, kwargs={'news_id': self.id})
	def get_absolute_url(self):
		if self.event:
			return reverse('results:event_details', kwargs={'event_id': self.event.id}) + '#news' + str(self.id)
		else:
			return self.get_reverse_url('results:news_details')
	def get_editor_url(self):
		if self.event:
			return reverse('editor:event_details', kwargs={'event_id': self.event.id, 'news_id': self.id}) + '#news'
		else:
			return self.get_reverse_url('editor:news_details')
	def get_history_url(self):
		return self.get_reverse_url('editor:news_changes_history')
	def get_social_post_url(self):
		return self.get_reverse_url('editor:news_post')
	def get_image_url(self):
		return '/{}'.format(self.image.name) if self.image else ''
	def get_image_thumb_url(self):
		return '/{}'.format(self.image_thumb.name) if self.image_thumb else ''
	def __str__(self):
		return self.title
@receiver(pre_delete, sender=News)
def pre_news_delete(sender, instance, **kwargs):
	if instance.image:
		try:
			instance.image.delete(False)
		except:
			pass
	if instance.image_thumb:
		try:
			instance.image_thumb.delete(False)
		except:
			pass

DOC_TYPE_UNKNOWN = 0
DOC_TYPE_REGULATION = 1
DOC_TYPE_ANNOUNCEMENT = 3
DOC_TYPE_POSTER = 4
DOC_TYPE_COURSE = 5
DOC_TYPE_LOGO = 6
DOC_TYPE_PROTOCOL = 7
DOC_TYPE_PROTOCOL_START = 8
DOC_TYPE_PHOTOS = 9
DOC_TYPE_HOW_TO_GET = 12
DOC_TYPE_IMPRESSIONS = 13
DOC_TYPE_APPLICATION_FORM = 15
DOC_TYPE_PRELIMINARY_PROTOCOL = 16
DOC_TYPE_TIMETABLE = 17
DOC_TYPE_REGISTRATION = 18
DOCUMENT_TYPES = (
	(DOC_TYPE_UNKNOWN, 'Document of unknown type'),
	(DOC_TYPE_REGULATION, 'Regulation'),
	(DOC_TYPE_ANNOUNCEMENT, 'Announcement'),
	(DOC_TYPE_POSTER, 'Poster'),
	(DOC_TYPE_COURSE, 'Course map'),
	(DOC_TYPE_LOGO, 'Logo'),
	(DOC_TYPE_PROTOCOL, 'Protocol'),
	(DOC_TYPE_PRELIMINARY_PROTOCOL, 'Preliminary protocol'),
	(DOC_TYPE_PROTOCOL_START, 'Start list'),
	(DOC_TYPE_PHOTOS, 'Photos or video'),
	(DOC_TYPE_HOW_TO_GET, 'How to get there'),
	(DOC_TYPE_IMPRESSIONS, 'Report'),
	(DOC_TYPE_APPLICATION_FORM, 'Sign up form'),
	(DOC_TYPE_TIMETABLE, 'Schedule'),
	(DOC_TYPE_REGISTRATION, 'Registration'),
)
SERIES_DOCUMENT_TYPES = (
	(DOC_TYPE_UNKNOWN, 'Document of unknown type'),
	(DOC_TYPE_LOGO, 'Logo'),
)
DOCUMENT_SUFFIXES = {
	DOC_TYPE_UNKNOWN: 'XX',
	DOC_TYPE_REGULATION: 'Pl',
	DOC_TYPE_ANNOUNCEMENT: 'An',
	DOC_TYPE_POSTER: 'Af',
	DOC_TYPE_COURSE: 'Sh',
	DOC_TYPE_LOGO: 'Lo',
	DOC_TYPE_PROTOCOL: 'Pr',
	DOC_TYPE_PROTOCOL_START: 'Ps',
	DOC_TYPE_PHOTOS: 'Ph',
	DOC_TYPE_HOW_TO_GET: 'Sd',
	DOC_TYPE_IMPRESSIONS: 'Im',
	DOC_TYPE_APPLICATION_FORM: 'Ap',
	DOC_TYPE_PRELIMINARY_PROTOCOL: 'PrelPr',
	DOC_TYPE_TIMETABLE: 'Ti',
	DOC_TYPE_REGISTRATION: 'Re',
}
DOC_PROTOCOL_TYPES = (DOC_TYPE_PROTOCOL, DOC_TYPE_PRELIMINARY_PROTOCOL)
Q_IS_XLS_FILE = Q(upload__iendswith='.xls') | Q(upload__iendswith='.xlsx')
DOC_TYPES_NOT_FOR_RIGHT_COLUMN = (DOC_TYPE_UNKNOWN, DOC_TYPE_LOGO, DOC_TYPE_PHOTOS, DOC_TYPE_IMPRESSIONS)
MAX_EVENT_NAME_LENGTH = 20
def create_document_file_name(date, suffix, name, city_name, series_id, extension, sample=None):
	if sample:
		suffix += '_sample' + str(sample)
	return '{0}_{1}_{2}_{3}_{4}.{5}'.format(
			date, suffix, name, city_name, series_id, extension).replace(' ', '_')
def document_name(instance, filename):
	write_log('{} DOCUMENT_NAME_CREATE Trying to upload file {} of type {} for series {}, event {}.'.format(
		datetime.datetime.now(), filename, instance.document_type, instance.series, instance.event))
	if instance.id:
		old_instance = Document.objects.get(pk=instance.id)
		if old_instance.upload:
			if os.path.isfile(old_instance.upload.path):
				write_log('There already is some file {}, so we just delete it.'.format(old_instance.upload.name))
				os.remove(old_instance.upload.path)
			else:
				write_log('Error! There is some value {}, but no such file.'.format(old_instance.upload.name))
	if instance.event:
		date = instance.event.start_date.strftime('%y%m%d')
		subdir = str(instance.event.start_date.year)
	else:
		date = '000000'
		subdir = '0000'

	suffix = DOCUMENT_SUFFIXES[instance.document_type]

	if instance.event:
		name = str(instance.event)
		series_id = instance.event.series.id
		city = instance.event.getCity()
		city_name = city.name if city else ''
	elif instance.series:
		name = str(instance.series)
		series_id = instance.series.id
		city_name = instance.series.city.name if instance.series.city else ''
	else:
		name = ''
		series_id = 0
		city_name = ''
	name = transliterate(name)[:MAX_EVENT_NAME_LENGTH]
	city_name = transliterate(city_name)[:MAX_EVENT_NAME_LENGTH]
	extension = file_extension(filename, default='html')
	if extension == 'php':
		extension = 'html'

	media_dir = os.path.join('dj_media/uploads', subdir) # That's what the function needs to return
	full_dir = os.path.join(settings.MEDIA_ROOT, media_dir)
	if not os.path.exists(full_dir):
		os.mkdir(full_dir)

	file_name = create_document_file_name(date, suffix, name, city_name, series_id, extension)
	full_name = os.path.join(full_dir, file_name)
	sample = 1
	while os.path.exists(full_name):
		write_log(f'Oops, file {full_name} already exists. Trying next sample number...')
		sample += 1
		file_name = create_document_file_name(date, suffix, name, city_name, series_id, extension, sample=sample)
		full_name = os.path.join(full_dir, file_name)

	write_log(f'File name to create is {file_name}. Full name is "{full_name}".')
	return os.path.join(media_dir, file_name)
LOAD_TYPE_UNKNOWN = 0
LOAD_TYPE_LOADED = 1
LOAD_TYPE_DO_NOT_TRY = 2
LOAD_TYPE_NOT_LOADED = 3
TRY_TO_LOAD_CHOICES = (
	(LOAD_TYPE_UNKNOWN, 'Неизвестно'),
	(LOAD_TYPE_LOADED, 'Загружено к нам'),
	(LOAD_TYPE_DO_NOT_TRY, 'Не пытаться загружать'),
	(LOAD_TYPE_NOT_LOADED, 'Не загружено, нужно загрузить'),
)
DOC_HIDE_NEVER = 0
DOC_HIDE_ALWAYS = 2
DOC_HIDE_CHOICES = (
	(DOC_HIDE_NEVER, 'всегда'),
	(DOC_HIDE_ALWAYS, 'никогда (его будут видеть только админы)'),
)
class Document(models.Model):
	series = models.ForeignKey(Series, verbose_name='Серия', on_delete=models.CASCADE, null=True, default=None, blank=True)
	event = models.ForeignKey(Event, verbose_name='Забег', on_delete=models.CASCADE, null=True, default=None, blank=True)

	document_type = models.SmallIntegerField(verbose_name='Содержимое документа', default=DOC_TYPE_UNKNOWN, choices=DOCUMENT_TYPES, db_index=True)
	loaded_type = models.SmallIntegerField(verbose_name='Состояние загрузки', default=0, choices=TRY_TO_LOAD_CHOICES)
	upload = models.FileField(verbose_name='Файл для загрузки', max_length=255, upload_to=document_name, blank=True)
	hide_local_link = models.SmallIntegerField(verbose_name='Показывать ли всем ссылку на локальный файл', choices=DOC_HIDE_CHOICES,
		default=DOC_HIDE_NEVER)
	url_source = custom_fields.MyURLField(verbose_name='URL документа', max_length=MAX_URL_LENGTH, blank=True)
	comment = models.CharField(verbose_name='Комментарий (например, если есть несколько документов одного типа)', max_length=255, blank=True)
	is_processed = models.BooleanField(verbose_name='Обработан ли протокол полностью', default=False)
	is_on_our_google_drive = models.BooleanField(verbose_name='Лежит на нашем Google Drive, резервная копия не нужна', default=False)

	author = models.CharField(verbose_name='Автор (для отчётов и фотографий)', max_length=100, blank=True)
	author_runner = models.ForeignKey('Runner', verbose_name='ID автора — участника забегов (для отчётов и фотографий)',
		on_delete=models.SET_NULL, null=True, default=None, blank=True)
	last_update = models.DateTimeField(verbose_name='Время последнего изменения', auto_now=True)
	date_posted = models.DateTimeField(verbose_name='Время занесения в БД', auto_now_add=True)
	created_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name='Добавил документ',
		on_delete=models.SET_NULL, default=None, null=True, blank=True)
	class Meta:
		indexes = [
			models.Index(fields=['series', 'document_type']),
			models.Index(fields=['event', 'document_type', 'is_processed']),
		]
		constraints = [
			models.UniqueConstraint(fields=['event', 'url_source'], name='event_url_source'),
		]
	def clean(self):
		self.author = replace_symbols(self.author)
		self.comment = replace_symbols(self.comment)
	def file_size(self):
		if self.upload:
			try:
				return self.upload.size
			except:
				return -1 # u'Ошибка. Возможно, файл не существует'
		else:
			return 0
	def title(self):
		if self.author:
			return self.author
		if self.comment:
			return self.comment
		if self.url_source:
			return self.url_source
		return self.get_document_type_display() + ' ' + self.comment
	def get_editor_url(self):
		if self.event:
			return self.event.get_editor_url() + '#documents'
		if self.series:
			return self.series.get_editor_url() + '#documents'
		return '#'
	def get_upload_path(self):
		if not self.upload:
			return ''
		if self.upload.name.startswith('dj_media'):
			return self.upload.path
		return settings.MEDIA_ROOT_LEGACY + self.upload.name
	def get_upload_url(self):
		if not self.upload:
			return '#'
		return f'{settings.MAIN_PAGE}/{self.upload.name}'
	def get_main_url(self):
		if self.url_source:
			return self.url_source
		return self.get_upload_url()
	def get_mark_processed_url(self):
		return reverse('editor:protocol_mark_processed', kwargs={'protocol_id': self.id})
	def get_add_to_queue_url(self):
		return reverse('editor:add_protocol_to_queue', kwargs={'protocol_id': self.id})
	def mark_processed(self, user, comment=''):
		self.is_processed = True
		self.save()
		log_obj_create(user, self.event, ACTION_DOCUMENT_UPDATE, field_list=['is_processed'], child_object=self, comment=comment)
	def is_xls(self):
		return self.upload and self.upload.name.lower().endswith(('.xls', '.xlsx'))
	def is_xls_protocol(self):
		return self.is_xls() and (self.document_type in DOC_PROTOCOL_TYPES)
	def is_eligible_for_queue(self):
		return (self.document_type in DOC_PROTOCOL_TYPES) and self.url_source.startswith('https://www.athlinks.com/event/')
	def get_report_or_photo_doc_type(self):
		if self.document_type == DOC_TYPE_PHOTOS:
			return 'фотоальбом'
		if self.document_type == DOC_TYPE_IMPRESSIONS:
			return 'отчёт'
		return 'документ'
	def __str__(self):
		if self.document_type in (DOC_TYPE_PHOTOS, DOC_TYPE_IMPRESSIONS):
			return self.author if self.author else 'автор не указан'
		res = self.get_document_type_display()
		if self.comment:
			if self.document_type == DOC_TYPE_UNKNOWN:
				res = self.comment
			else:
				res += ' ' + self.comment
		if self.author:
			res += ' (' + self.author + ')'
		return res
@receiver(pre_delete, sender=Document)
def pre_document_delete(sender, instance, **kwargs):
	if instance.upload:
		doc_path = instance.get_upload_path()
		instance.upload.delete(False)
		if os.path.isfile(doc_path):
			if instance.event:
				obj_desc = (f'события {instance.event.name} (id {instance.event.id}) '
					+ f'из серии {instance.event.series.name} (id {instance.event.series.id})')
			else:
				obj_desc = f'серии {instance.series.name} (id {instance.series.id})'
			send_panic_email(
				'We could not delete a document file',
				f'Мы пытались удалить файл, хранящийся в {doc_path} , при удалении документа типа {instance.get_document_type_display()} '
				+ f'у {obj_desc}. Это не удалось.',
				to_all=True,
			)
	event = None
	if instance.event:
		event = instance.event
		write_log('Document with id {} of type {} from event {} is being deleted'.format(instance.id, instance.document_type, event.id))
	elif instance.series:
		series = instance.series
		write_log('Document with id {} of type {} from series {} is being deleted'.format(instance.id, instance.document_type, series.id))
	else:
		write_log('Document with id {} of type {} with no event or series is being deleted'.format(instance.id, instance.document_type))

SUBSCRIPTION_TYPE_MONTHLY = 0
SUBSCRIPTION_TYPE_YEARLY = 1
SUBSCRIPTION_TYPES = (
	(SUBSCRIPTION_TYPE_MONTHLY, 'на месяц'),
	(SUBSCRIPTION_TYPE_YEARLY, 'на год'),
)
class Subscription_order(models.Model): # Оплаты подписки на сайт
	user = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name='Какой аккаунт оплачен', on_delete=models.PROTECT)
	subscription_type = models.SmallIntegerField(verbose_name='Срок оплаты', choices=SUBSCRIPTION_TYPES)

	# payment = models.OneToOneField(Payment_moneta, verbose_name='Платёж, которым оплачено участие', on_delete=models.SET_NULL,
	# 	null=True, blank=True, default=None)
	created_time = models.DateTimeField(verbose_name='Дата создания', default=datetime.datetime.now, db_index=True)
	created_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name='Кто оплатил', on_delete=models.PROTECT, related_name='subscription_orders_created_by_user')

class Followship(models.Model): # Isn't used yet
	follower = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name='Следящий', related_name='follower_set',
		on_delete=models.CASCADE)
	target = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name='Цель', related_name='target_set',
		on_delete=models.CASCADE)
	added_time = models.DateTimeField(verbose_name='Время занесения в БД', auto_now_add=True)
	class Meta:
		constraints = [
			models.UniqueConstraint(fields=['follower', 'target'], name='follower_target'),
		]

class Calendar(models.Model):
	user = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name='Пользователь', related_name='calendar_set', on_delete=models.CASCADE)
	event = models.ForeignKey(Event, verbose_name='Забег', related_name='calendar_set', on_delete=models.CASCADE)
	race = models.ForeignKey(Race, verbose_name='Дистанция', related_name='calendar_set', on_delete=models.SET_NULL, default=None, null=True,
		blank=True)
	marked_as_checked = models.BooleanField(verbose_name='Отмечено как учтённое капитаном команды', default=False, db_index=True)
	added_time = models.DateTimeField(verbose_name='Время занесения в БД', auto_now_add=True)
	class Meta:
		constraints = [
			models.UniqueConstraint(fields=['user', 'event'], name='user_event'),
		]
		ordering = ['user__last_name', 'user__first_name']

SOCIAL_TYPE_FB = 1
SOCIAL_TYPE_VK = 2
SOCIAL_TYPE_TWITTER = 3
SOCIAL_PAGE_TYPES = (
	(SOCIAL_TYPE_FB, 'Facebook'),
	(SOCIAL_TYPE_VK, 'ВКонтакте'),
	(SOCIAL_TYPE_TWITTER, 'Twitter'),
)
class Social_page(models.Model):
	page_type = models.SmallIntegerField(verbose_name='Тип страницы', choices=SOCIAL_PAGE_TYPES)
	page_id = models.CharField(verbose_name='id страницы', max_length=30)
	name = models.CharField(verbose_name='Название страницы', max_length=100)
	district = models.ForeignKey(District, verbose_name='Федеральный округ', default=None, null=True, blank=True,
		on_delete=models.PROTECT)
	is_for_all_news = models.BooleanField(verbose_name='Для всех новостей?', default=False, blank=True)
	url = models.URLField(verbose_name='Ссылка на страницу', max_length=200, blank=True)
	access_token = models.CharField(verbose_name='Токен для доступа к странице', max_length=300)
	token_secret = models.CharField(verbose_name='Секретный токен для твиттера', max_length=200, blank=True)
	class Meta:
		ordering = ['name', 'page_type']
	def get_absolute_url(self):
		return self.url
	def get_history_url(self):
		return reverse('editor:social_page_history', kwargs={'page_id': self.id})
	def __str__(self):
		return self.name + ' (' + self.url + ')'

class Social_news_post(models.Model):
	news = models.ForeignKey(News, verbose_name='Новость', related_name='social_post_set',
		on_delete=models.CASCADE)
	social_page = models.ForeignKey(Social_page, verbose_name='Страница в соцсети', related_name='news_set',
		on_delete=models.CASCADE)
	post_id = models.CharField(verbose_name='id поста', max_length=30)
	tweet = models.CharField(verbose_name='Текст поста в твиттер', max_length=400, blank=True)
	created_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name='Опубликовал',
		on_delete=models.SET_NULL, default=None, null=True, blank=True)
	date_posted = models.DateTimeField(verbose_name='Время публикации', auto_now_add=True)
	class Meta:
		ordering = ['-date_posted']
	def get_absolute_url(self):
		if self.social_page.page_type == SOCIAL_TYPE_VK:
			return f'https://vk.com/wall-{self.social_page.page_id}_{self.post_id}'
		elif self.social_page.page_type == SOCIAL_TYPE_FB:
			return f'https://www.facebook.com/permalink.php?story_fbid={self.post_id}&id={self.social_page.page_id}'
		elif self.social_page.page_type == SOCIAL_TYPE_TWITTER:
			return self.social_page.url + '/status/' + self.post_id
		return ''
	def __str__(self):
		return self.social_page.name + ' (' + self.date_posted.isoformat() + ')'

MESSAGE_TYPE_PERSONAL = 0
MESSAGE_TYPE_NEWSLETTER = 1
MESSAGE_TYPE_RESULTS_FOUND = 2
MESSAGE_TYPE_FROM_ROBOT = 3
MESSAGE_TYPE_REG_COMPLETE = 4
MESSAGE_TYPE_REG_PAID = 5
MESSAGE_TYPE_CONFIRM_EMAIL = 6
MESSAGE_TYPE_PAYMENT_RECEIVED_TO_ADMINS = 7
MESSAGE_TYPE_TO_EVENT_PARTICIPANTS = 8
MESSAGE_TYPE_USER_ACTION_TO_ADMINS = 9
MESSAGE_TYPE_TO_INFO = 10
MESSAGE_TYPE_TO_ALEXEY = 11
MESSAGE_TYPE_TO_RECORDS = 12
MESSAGE_TYPES = (
	(MESSAGE_TYPE_PERSONAL, 'Личное письмо пользователю или организатору забега'),
	(MESSAGE_TYPE_NEWSLETTER, 'Новостная рассылка'),
	(MESSAGE_TYPE_RESULTS_FOUND, 'Найдены новые результаты пользователя'),
	(MESSAGE_TYPE_FROM_ROBOT, 'Письмо о действиях роботов'),
	(MESSAGE_TYPE_CONFIRM_EMAIL, 'Письмо для подтверждения электронного адреса пользователя'),
	(MESSAGE_TYPE_TO_EVENT_PARTICIPANTS, 'Письмо всем записавшимся у нас на забег'),
	(MESSAGE_TYPE_USER_ACTION_TO_ADMINS, 'Письмо админам о том, что пользователь добавил забег/серию/отчёт/фотоальбом'),
	(MESSAGE_TYPE_TO_INFO, 'Письмо посетителя админам о чём угодно'),
	(MESSAGE_TYPE_TO_ALEXEY, 'Письмо, которое идёт только Алексею Чернову'),
	(MESSAGE_TYPE_TO_RECORDS, 'Письмо на records@'),
)
def get_attachment_name(instance, filename):
	sample = 0
	while True:
		res = 'dj_media/attachments/' + datetime.datetime.today().strftime('%Y%m%d_%H%M%S_')
		if sample:
			res += '_sample{}'.format(sample)
		res += transliterate(filename)
		if os.path.exists(os.path.join(settings.MEDIA_ROOT, res)):
			sample += 1
		else:
			break
	return res
class Message_from_site(models.Model):
	table_update = models.ForeignKey(Table_update, verbose_name='Обновление таблицы',
		on_delete=models.SET_NULL, default=None, null=True, blank=True)
	sender_email = models.CharField(verbose_name='Имя и электронный адрес отправителя', max_length=MAX_EMAIL_LENGTH, blank=True)
	reply_to = models.EmailField(verbose_name='Ваш электронный адрес (на него мы отправим ответ)', max_length=MAX_EMAIL_LENGTH, blank=True)
	target_email = models.CharField(verbose_name='Куда (можно несколько адресов через запятую)', max_length=MAX_EMAIL_LENGTH * 10, blank=True)
	cc = models.CharField(verbose_name='Копия (можно несколько адресов через запятую)', max_length=MAX_EMAIL_LENGTH, blank=True)
	bcc = models.CharField(verbose_name='Скрытая копия (можно несколько адресов через запятую)', max_length=MAX_EMAIL_LENGTH, blank=True)
	title = models.CharField(verbose_name='Тема сообщения', max_length=255, blank=True)
	body = models.TextField(max_length=40000, verbose_name='Текст сообщения')
	body_html = models.TextField(max_length=40000, verbose_name='Текст сообщения в HTML')
	attachment = models.FileField(verbose_name='Вы можете приложить к письму файл (не больше {} МБ)'.format(settings.MAX_USER_UPLOAD_SIZE_MB),
		max_length=255, upload_to=get_attachment_name, blank=True)
	is_sent = models.BooleanField(verbose_name='Отправлено ли письмо', default=False, blank=True)
	message_type = models.SmallIntegerField(verbose_name='Тип письма', default=MESSAGE_TYPE_PERSONAL, choices=MESSAGE_TYPES)

	created_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name='Написал сообщение',
		on_delete=models.SET_NULL, default=None, null=True, blank=True)
	date_posted = models.DateTimeField(verbose_name='Время отправки', default=timezone.now)
	class Meta:
		indexes = [
			models.Index(fields=['is_sent', 'date_posted']),
		]
	def get_reverse_url(self, target):
		return reverse(target, kwargs={'message_id': self.id})
	def get_absolute_url(self):
		return self.get_reverse_url('editor:message_details')
	def get_unsubscribe_header(self):
		if self.message_type == MESSAGE_TYPE_NEWSLETTER:
			return {'List-Unsubscribe': f'<mailto:{settings.EMAIL_INFO_USER}?subject=unsubscribe-newsletters>'}
		if self.message_type == MESSAGE_TYPE_RESULTS_FOUND:
			return {'List-Unsubscribe': f'<mailto:{settings.EMAIL_INFO_USER}?subject=unsubscribe-results-found>'}
		return {}
	def set_fields_by_message_type(self):
		if self.message_type == MESSAGE_TYPE_PERSONAL:
			self.sender_email = INFO_MAIL_HEADER
		elif self.message_type == MESSAGE_TYPE_NEWSLETTER:
			self.sender_email = INFO_MAIL_HEADER
		elif self.message_type == MESSAGE_TYPE_RESULTS_FOUND:
			self.sender_email = INFO_MAIL_HEADER
		elif self.message_type == MESSAGE_TYPE_FROM_ROBOT:
			self.sender_email = INFO_MAIL_HEADER
			self.target_email = settings.EMAIL_INFO_USER
			self.created_by = USER_ROBOT_CONNECTOR
		elif self.message_type == MESSAGE_TYPE_CONFIRM_EMAIL:
			self.sender_email = INFO_MAIL_HEADER
		elif self.message_type == MESSAGE_TYPE_TO_EVENT_PARTICIPANTS:
			self.sender_email = INFO_MAIL_HEADER
		elif self.message_type == MESSAGE_TYPE_USER_ACTION_TO_ADMINS:
			self.sender_email = ROBOT_MAIL_HEADER
			self.target_email = settings.EMAIL_INFO_USER
		elif self.message_type == MESSAGE_TYPE_TO_INFO:
			self.sender_email = ROBOT_MAIL_HEADER
			self.target_email = settings.EMAIL_INFO_USER
			self.cc = self.reply_to
		elif self.message_type == MESSAGE_TYPE_TO_ALEXEY:
			self.sender_email = INFO_MAIL_HEADER
			self.target_email = 'alexey.chernov@gmail.com'
		self.save()
	def try_send(self, attach_file=True, connection=None):
		self.set_fields_by_message_type()

		to = self.target_email.split(',')
		cc = self.cc.split(',')
		bcc = self.bcc.split(',')
		if len(to) > 1: # If we have more than one recipient, we put them all to BCC field
			bcc += to
			to = []

		headers = self.get_unsubscribe_header()
		if self.reply_to:
			headers['Reply-To'] = self.reply_to # 'alexey.chernov@gmail.com'

		to_close_connection = False
		if connection is None:
			to_close_connection = True
			connection = results_util.get_mail_connection(self.sender_email)
			connection.open()

		message = EmailMultiAlternatives(
			subject=self.title,
			body=self.body,
			from_email=self.sender_email,
			to=to,
			cc=cc,
			bcc=bcc,
			headers=headers,
			connection=connection,
			)
		if self.body_html:
			message.attach_alternative(self.body_html, 'text/html')

		result = {}

		try:
			if self.attachment and attach_file:
				message.attach_file(self.attachment.path)
			result['success'] = message.send()
			if result['success']:
				self.is_sent = True
				self.save()
			else:
				result['error'] = 'Мы сохранили ваше сообщение, но отправить его не получилось.'
		except Exception as e:
			result['success'] = 0
			result['error'] = repr(e)

		if to_close_connection:
			connection.close()

		if 'error' in result:
			send_panic_email(
				'We could not send an email',
				f'Мы пытались отправить письмо с id {self.id} с адреса {self.sender_email} на {self.target_email}.\n\n'
				+ f'Возникшая ошибка: {result['error']}',
				to_all=True,
			)
		return result

class Statistics(models.Model):
	name = models.CharField(verbose_name='Название поля', max_length=30, db_index=True)
	value = models.IntegerField(verbose_name='Значение', default=0)
	date_added = models.DateField(verbose_name='Дата расчёта', auto_now_add=True)
	last_update = models.DateTimeField(verbose_name='Дата последнего обновления', auto_now=True)
	class Meta:
		constraints = [
			models.UniqueConstraint(fields=['name', 'date_added'], name='name_date_added'),
		]
	def __str__(self):
		return self.name + ' = ' + str(self.value)

class User_added_to_club(models.Model):
	''' События добавления пользователей сайта в клубы — чтобы их предупредить о произошедшем. '''
	user = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name='Пользователь', on_delete=models.CASCADE)
	club = models.ForeignKey(Club, verbose_name='Клуб', on_delete=models.CASCADE, default=None, null=True, blank=True)
	added_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name='Добавил в команду',
		on_delete=models.SET_NULL, default=None, null=True, blank=True, related_name='added_to_klb_team_by_user')
	added_time = models.DateTimeField(verbose_name='Время занесения в БД', auto_now_add=True)
	sent_time = models.DateTimeField(verbose_name='Время отправки письма', default=None, null=True, blank=True)

# Obj must have fields lname, fname, midname
def get_name(obj):
	if obj.midname:
		return '{} {} {}'.format(obj.fname, obj.midname, obj.lname)
	if obj.lname:
		return '{} {}'.format(obj.fname, obj.lname)
	return '(неизвестно)'

def fill_user_value(results, user, user_for_action, comment=''):
	res = 0
	for result in results.select_related('race__event'):
		result.user = user
		result.save()
		log_obj_create(user_for_action, result.race.event, ACTION_RESULT_UPDATE, field_list=['user'], child_object=result, comment=comment)
		res += 1
	return res
class Runner(models.Model):
	user = models.OneToOneField(settings.AUTH_USER_MODEL, verbose_name='id пользователя сайта', on_delete=models.SET_NULL,
		default=None, null=True, blank=True)
	platforms = models.ManyToManyField('Platform', through=Runner_platform, through_fields=('runner', 'platform'),
		related_name='runner_set')
	klb_person = models.OneToOneField('Klb_person', verbose_name='id в КЛБМатче', on_delete=models.SET_NULL, default=None, null=True, blank=True)

	lname = models.CharField(verbose_name='Фамилия', max_length=100, blank=True)
	fname = models.CharField(verbose_name='Имя', max_length=100, blank=True, db_index=True)
	midname = models.CharField(verbose_name='Отчество', max_length=100, blank=True)
	birthday = models.DateField(verbose_name='День или год рождения', default=None, null=True, blank=True, db_index=True)
	# If true, we know exact date of birth (otherwise usually birthday should be 01.01.)
	birthday_known = models.BooleanField(verbose_name='Известен ли день рождения', default=False, db_index=True)
	birthday_min = models.DateField(verbose_name='Самый ранний возможный день рождения', default=None, null=True, blank=True, db_index=True)
	birthday_max = models.DateField(verbose_name='Самый поздний возможный день рождения', default=None, null=True, blank=True, db_index=True)
	gender = models.SmallIntegerField(verbose_name='Пол', default=results_util.GENDER_UNKNOWN, choices=results_util.GENDER_CHOICES)

	city = models.ForeignKey(City, verbose_name='Город', on_delete=models.PROTECT, default=None, null=True, blank=True)
	city_name = models.CharField(verbose_name='Город (строка)', max_length=100, blank=True)
	region_name = models.CharField(verbose_name='Регион (строка)', max_length=100, blank=True)
	country_name = models.CharField(verbose_name='Страна (строка)', max_length=50, blank=True)

	club_name = models.CharField(verbose_name='Клуб', max_length=100, blank=True)
	deathday = models.DateField(verbose_name='Дата смерти', default=None, null=True, blank=True, db_index=True)
	url_wiki = models.URLField(verbose_name='Страница о человеке в Википедии', max_length=200, blank=True)

	n_starts = models.SmallIntegerField(verbose_name='Число финишей', default=None, null=True, blank=True)
	total_length = models.IntegerField(verbose_name='Общая пройденная дистанция в метрах', default=None, null=True, blank=True)
	total_time = models.BigIntegerField(verbose_name='Общее время на забегах в сотых секунды', default=None, null=True, blank=True)

	n_starts_cur_year = models.SmallIntegerField(verbose_name='Число финишей в этом году', default=None, null=True, blank=True)
	total_length_cur_year = models.IntegerField(verbose_name='Общая пройденная дистанция в метрах в этом году', default=None, null=True, blank=True)
	total_time_cur_year = models.IntegerField(verbose_name='Общее время на забегах в сотых секунды в этом году', default=None, null=True, blank=True)
	has_many_distances = models.BooleanField(verbose_name='Имеет ли больше разных дистанций, чем отображаем по умолчанию', default=False)

	eddington = models.SmallIntegerField(verbose_name='Число Эддингтона', default=None, null=True, blank=True)
	eddington_cur_year = models.SmallIntegerField(verbose_name='Число Эддингтона в этом году', default=None, null=True, blank=True)
	eddington_for_next_level = models.SmallIntegerField(verbose_name='Нужно пробежек для следующего значения', default=None, null=True, blank=True)
	eddington_for_next_level_cur_year = models.SmallIntegerField(verbose_name='Нужно пробежек для следующего значения в этом году', default=None, null=True, blank=True)

	n_possible_results = models.IntegerField(verbose_name='Число результатов, похожих на этого бегуна', default=0, blank=True)
	comment = models.CharField(verbose_name='Комментарий (виден всем)', max_length=250, blank=True)
	comment_private = models.CharField(verbose_name='Комментарий администраторам (не виден посетителям)', max_length=250, blank=True)
	private_data_hidden = models.BooleanField(verbose_name='Нужно ли скрыть персональные данные человека', default=False, db_index=True)
	last_find_results_try = models.DateField(verbose_name='Когда в последний раз искали результаты пользователя',
		default=None, null=True, blank=True)

	created_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name='Создал бегуна', related_name='runners_created_set',
		on_delete=models.SET_NULL, default=None, null=True, blank=True)
	added_time = models.DateTimeField(verbose_name='Время создания в БД', auto_now_add=True, null=True, blank=True)
	class Meta:
		indexes = [
			models.Index(fields=['lname', 'fname', 'midname', 'private_data_hidden']),
			models.Index(fields=['lname', 'fname', 'birthday_known', 'birthday', 'midname']),
			models.Index(fields=['birthday_known', 'birthday']),
			models.Index(fields=['n_starts', 'lname', 'fname']),
			models.Index(fields=['total_length', 'lname', 'fname']),
			models.Index(fields=['total_time', 'lname', 'fname']),
			models.Index(fields=['n_starts_cur_year', 'lname', 'fname']),
			models.Index(fields=['total_length_cur_year', 'lname', 'fname']),
			models.Index(fields=['total_time_cur_year', 'lname', 'fname']),
			models.Index(fields=['eddington', 'lname', 'fname']),
			models.Index(fields=['eddington_cur_year', 'lname', 'fname']),
			models.Index(fields=['last_find_results_try', 'lname', 'fname', 'midname']),
		]
	def get_common_fields(self, runner):
		common_fields = []
		if self.user and runner.user:
			common_fields.append('user')
		my_platforms = set(self.platforms.values_list('id', flat=True))
		runner_platforms = set(runner.platforms.values_list('id', flat=True))
		common_fields += list(my_platforms.intersection(runner_platforms))
		return common_fields
	def get_result_set(self):
		return self.result_set.select_related('race__distance', 'race__distance_real',
			'race__event__series__city__region__country', 'race__event__city__region__country', 'race__event__series__country').order_by(
			'-race__event__start_date')
	# Moves all fields of runner to self. Returns <was merged?>, <error message>
	def merge(self, runner, action_user: settings.AUTH_USER_MODEL=USER_ROBOT_CONNECTOR, allow_merge_nyrr: bool=False) -> tuple[bool, str]:
		common_fields = self.get_common_fields(runner)
		if common_fields:
			if (len(common_fields) == 1) and (common_fields[0] == 'nyrr') and allow_merge_nyrr:
				runner_platform = self.runner_platform_set.filter(platform_id='nyrr').first()
				runner_platform.merge_nyrr_platforms(runner)
			else:
				write_log(f'{datetime.datetime.now()} RUNNER_MERGE Merging runner_id {self.id} with runner_id {runner.id} is impossible. Common fields: [{common_fields}].')
				log_obj_create(action_user, self, ACTION_MERGE_FAILED, field_list=common_fields, child_object=runner,
					comment=f'Поглощение бегуна с id {runner.id} не удалось. Разобраться и ответить пользователю!')
				send_panic_email(
					'Runners merging is impossible',
					f'Problem occured when user {action_user.get_full_name()} (id {action_user.id}) tried to merge runners '
					+ f'{self.name()} {settings.MAIN_PAGE}{self.get_absolute_url()} and {runner.name()} {settings.MAIN_PAGE}{runner.get_absolute_url()}: '
					+ f'they have common fields {common_fields}.',
				)
				if is_admin(action_user):
					return False, f'У обоих бегунов есть привязки к полям {common_fields}. Поглощение бегуна невозможно.'
				else:
					return False, 'You and the the result you wanted to add to your profile have intersecting fields. We are looking at the issue and will respond to you.'

		comment = f'При приклеивании бегуна {runner.name()} (id {runner.id}) к бегуну {self.name()} (id {self.id})'

		self_club_ids = set(self.club_member_set.values_list('club_id', flat=True))
		problem_club_members = list(runner.club_member_set.filter(club_id__in=self_club_ids))
		for club_member in problem_club_members:
			self_club_member = self.club_member_set.get(club_id=club_member.club_id)
			self_club_member.merge(action_user, club_member, comment=comment)
		for club_member in problem_club_members:
			log_obj_create(action_user, club_member.club, ACTION_CLUB_MEMBER_DELETE, child_object=club_member, field_list=[], comment=comment)
			club_member.delete()
		runner.club_member_set.update(runner=self)

		changed_fields = []
		problem_fields = []
		n_results_touched = 0
		if runner.user:
			self.user = runner.user
			n_results_touched += fill_user_value(self.result_set, self.user, action_user, comment=comment)
			runner.user = None
			changed_fields.append('user')
		elif self.user:
			n_results_touched += fill_user_value(runner.result_set, self.user, action_user, comment=comment)

		runner.runner_platform_set.update(runner=self)
		if runner.city:
			if self.city:
				problem_fields.append(f'city (old value: {self.city.name}, new value: {runner.city.name})')
			else:
				self.city = runner.city
				changed_fields.append('city')
		if runner.midname:
			if self.midname:
				problem_fields.append(f'midname (old value: {self.midname}, new value: {runner.midname})')
			else:
				self.midname = runner.midname
				changed_fields.append('midname')
		if self.birthday:
			if runner.birthday and (self.birthday != runner.birthday):
				problem_fields.append(f'birthday (old value: {self.strBirthday()}, new value: {runner.strBirthday()})')
		elif runner.birthday:
			self.birthday = runner.birthday
			self.birthday_known = runner.birthday_known
			changed_fields.append('birthday')
			changed_fields.append('birthday_known')
		else:
			if runner.birthday_min:
				if self.birthday_min:
					if runner.birthday_min > self.birthday_min:
						self.birthday_min = runner.birthday_min
						changed_fields.append('birthday_min')
				else:
					self.birthday_min = runner.birthday_min
					changed_fields.append('birthday_min')
			if runner.birthday_max:
				if self.birthday_max:
					if runner.birthday_max < self.birthday_max:
						self.birthday_max = runner.birthday_max
						changed_fields.append('birthday_max')
				else:
					self.birthday_max = runner.birthday_max
					changed_fields.append('birthday_max')
		runner.save()
		self.save()
		n_results_touched += Result.objects.filter(runner=runner).update(runner=self)
		write_log('{} RUNNER_MERGE Merging runner {} with runner {} completed, changed fields: {}, results touched: {}.'.format(
			datetime.datetime.now(), self.get_name_and_id(), runner.get_name_and_id(), changed_fields, n_results_touched))
		if problem_fields:
			write_log('Problems with fields: {}. Change them manually if needed.'.format(', '.join(problem_fields)))
		log_obj_create(action_user, self, ACTION_UPDATE, field_list=changed_fields,
			comment=f'Поглощение бегуна {runner.get_name_and_id()}. Затронуто результатов: {n_results_touched}')
		return True, ('Problem fields:' + '; '.join(problem_fields)) if problem_fields else ''
	# Update gender, birthday, city, midname from another Runner instance
	def update_if_needed(self, action_user: get_user_model(), runner, comment: str):
		changed_fields = []
		if self.midname.lower() != runner.midname.lower():
			self.midname = runner.midname
			changed_fields.append('midname')
		if (self.birthday != runner.birthday) or not self.birthday_known:
			self.birthday = runner.birthday
			changed_fields.append('birthday')
			if not self.birthday_known:
				self.birthday_known = True
				changed_fields.append('birthday_known')
		if self.city != runner.city:
			self.city = runner.city
			changed_fields.append('city')
		if (self.gender == results_util.GENDER_UNKNOWN) and (runner.gender != results_util.GENDER_UNKNOWN):
			self.gender = runner.gender
			changed_fields.append('gender')
		self.save()
		if changed_fields:
			log_obj_create(action_user, self, ACTION_UPDATE, field_list=changed_fields, comment=comment)
	def strBirthday(self, with_nbsp=True):
		if not self.birthday:
			return ''
		if self.birthday_known:
			return results_util.date2str(self.birthday, with_nbsp=with_nbsp)
		return f'{self.birthday.year}{'&nbsp;' if with_nbsp else ' '}г.'
	def get_age_today(self):
		if not self.birthday:
			return None
		today = datetime.date.today()
		return today.year - self.birthday.year - ((today.month, today.day) < (self.birthday.month, self.birthday.day))
	def name(self, with_midname=False):
		if self.midname and with_midname:
			return f'{self.fname} {self.midname} {self.lname}'
		return f'{self.fname} {self.lname}' if self.lname else '(unknown)'
	def get_lname_fname(self):
		return f'{self.lname} {self.fname}' if self.lname else '(unknown)'
	def name_with_midname(self):
		return self.name(with_midname=True)
	def get_name_for_ajax_select(self):
		return (f'{self.lname} {self.fname} {self.midname} (id {self.id}, {self.strBirthday(with_nbsp=False)}, '
			+ f'{self.city.nameWithCountry(with_nbsp=False) if self.city else ''}, {self.n_starts if self.n_starts else 0} стартов)')
	def get_name_condition(self):
		return get_name_condition(self.lname, self.fname, self.midname)
	def get_total_length(self, with_nbsp=True):
		return total_length2string(self.total_length, with_nbsp=with_nbsp)
	def get_total_time(self, with_br=True):
		return total_time2string(self.total_time, with_br=with_br)
	def get_length_curyear(self, with_nbsp=True):
		return total_length2string(self.total_length_cur_year, with_nbsp=with_nbsp)
	def get_time_curyear(self, with_br=True):
		return total_time2string(self.total_time_cur_year, with_br=with_br)
	def get_user_url(self):
		if self.user_id:
			return reverse('results:user_details', kwargs={'user_id': self.user_id})
		return ''
	def get_runner_or_user_url(self):
		if self.user and self.user.is_active and self.user.user_profile and self.user.user_profile.is_public:
			return self.user.user_profile.get_absolute_url()
		return self.get_absolute_url()
	def _get_possible_results(self, hide_linked_to_other_runners):
		q_names = self.get_name_condition()
		for name in self.extra_name_set.all():
			q_names |= name.get_name_condition()

		results = Result.objects.filter(q_names).exclude(runner=self).select_related('race__event__series__city__region__country',
			'race__event__city__region__country', 'runner', 'user__user_profile', 'category_size').order_by('-race__event__start_date')
		if self.user:
			unclaimed_result_ids = set(self.user.unclaimed_result_set.values_list('result_id', flat=True))
			results = results.filter(runner__user=None, user=None).exclude(pk__in=unclaimed_result_ids)
		if hide_linked_to_other_runners:
			results = results.filter(runner=None)

		if self.birthday is None:
			return results

		# Otherwise, we can be more precise
		birthday = self.birthday
		q_age = Q(birthday=None)
		if self.birthday_known:
			q_age |= Q(birthday_known=True, birthday=birthday) | Q(birthday_known=False, birthday__year=birthday.year)
		else:
			q_age |= Q(birthday__year=birthday.year)
		results = results.filter(q_age)
		max_difference = 1 if self.birthday_known else 2 # We are more strict if we know exact birthday
		new_results = []
		for result in results:
			if (result.birthday is None) and result.age:
				if abs(result.race.get_age_on_event_date(self.birthday) - result.age) <= max_difference:
					new_results.append(result)
			else:
				new_results.append(result)
		return new_results
	# Finds all possible results for runner and fills relevant fields in DB.
	def get_possible_results(self, hide_linked_to_other_runners=True) -> List[Result]:
		results = self._get_possible_results(hide_linked_to_other_runners=hide_linked_to_other_runners)
		self.last_find_results_try = datetime.date.today()
		self.n_possible_results = len(results)
		self.save()
		return results
	def a_if_needed(self):
		return 'а' if self.gender == results_util.GENDER_FEMALE else ''
	def get_reverse_url(self, target):
		return reverse(target, kwargs={'runner_id': self.id})
	def get_absolute_url(self):
		return self.get_reverse_url('results:runner_details')
	def get_absolute_url_full(self):
		return self.get_reverse_url('results:runner_details_full')
	def get_editor_url(self):
		return self.get_reverse_url('editor:runner_details')
	def get_history_url(self):
		return self.get_reverse_url('editor:runner_changes_history')
	def get_update_url(self):
		return self.get_reverse_url('editor:runner_update')
	def get_delete_url(self):
		return self.get_reverse_url('editor:runner_delete')
	def get_update_stat_url(self):
		return self.get_reverse_url('editor:runner_update_stat')
	def get_add_name_url(self):
		return self.get_reverse_url('editor:runner_name_add')
	def get_add_link_url(self):
		return self.get_reverse_url('editor:runner_link_add')
	def get_unclaim_unclaimed_by_user_url(self):
		return self.get_reverse_url('editor:unclaim_unclaimed_by_user')
	def get_find_results_url(self):
		return self.get_reverse_url('results:find_results')
	def get_add_platform_url(self):
		return self.get_reverse_url('editor:runner_platform_add')
	def get_name_and_id(self):
		return f'{self.lname} {self.fname} {self.midname} (id {self.id})'
	def get_extra_names(self):
		return self.extra_name_set.select_related('added_by').order_by('lname', 'fname', 'midname')
	def has_dependent_objects(self):
		return self.result_set.exists() or self.club_member_set.exists() or self.extra_name_set.exists() or self.record_result_set.exists() \
			or (self.klb_person is not None) or (self.user is not None)
	def __str__(self):
		return get_name(self)

# A link to some article about given runner.
class Runner_link(models.Model):
	runner = models.ForeignKey('Runner', verbose_name='Бегун', on_delete=models.CASCADE)
	link = custom_fields.MyURLField(verbose_name='Ссылка', max_length=MAX_URL_LENGTH, blank=False)
	description = models.CharField(verbose_name='Описание содержимого ссылки', max_length=200, blank=False)
	added_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
	added_time = models.DateTimeField(verbose_name='Время занесения в БД', auto_now_add=True)
	class Meta:
		constraints = [
			models.UniqueConstraint(fields=['runner', 'link'], name='runner_link'),
			models.UniqueConstraint(fields=['runner', 'description'], name='runner_description'),
		]
		ordering = ['runner', 'description', ]
	def __str__(self):
		return self.description

class Club_member(models.Model):
	runner = models.ForeignKey(Runner, verbose_name='ID участника забегов', on_delete=models.CASCADE)
	club = models.ForeignKey(Club, verbose_name='Клуб', on_delete=models.PROTECT)

	email = models.CharField(verbose_name='E-mail', max_length=MAX_EMAIL_LENGTH, blank=True)
	phone_number = models.CharField(verbose_name='Мобильный телефон', max_length=MAX_PHONE_NUMBER_LENGTH, blank=True)
	date_registered = models.DateField(verbose_name='Дата добавления в клуб', default=None, null=True)
	date_removed = models.DateField(verbose_name='Дата выхода из клуба', default=None, null=True, blank=True)

	added_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name='Кто добавил в таблицу', on_delete=models.SET_NULL, null=True, blank=True)
	added_time = models.DateTimeField(verbose_name='Время создания', auto_now_add=True, null=True, blank=True)
	last_update = models.DateTimeField(verbose_name='Последнее изменение', auto_now=True, null=True, blank=True)
	class Meta:
		constraints = [
			models.UniqueConstraint(fields=['club', 'runner'], name='club_runner'),
		]
	def merge(self, user, other, comment=''): # self.club_id must be equal to other.club_id
		fields_changed = []
		if other.date_registered is None:
			if self.date_registered:
				self.date_registered = None
				fields_changed.append('date_registered')
		elif self.date_registered and (other.date_registered < self.date_registered):
			self.date_registered = other.date_registered
			fields_changed.append('date_registered')
		if other.date_removed is None:
			if self.date_removed:
				self.date_removed = None
				fields_changed.append('date_removed')
		elif self.date_removed and (other.date_removed > self.date_removed):
			self.date_removed = other.date_removed
			fields_changed.append('date_removed')
		if fields_changed:
			log_obj_create(user, self.club, ACTION_CLUB_MEMBER_UPDATE, child_object=self, field_list=fields_changed, comment=comment)
			self.save()
	def is_already_removed(self):
		return self.date_removed and (self.date_removed < datetime.date.today())
	def print_date_registered(self):
		if self.date_registered is None:
			return ''
		if self.date_registered.month == 1 and self.date_registered.day == 1:
			return self.date_registered.year
		return self.date_registered.strftime('%d.%m.%Y')
	def print_date_removed(self):
		if self.date_removed is None:
			return ''
		if self.date_removed.month == 12 and self.date_removed.day == 31:
			return self.date_removed.year
		return self.date_removed.strftime('%d.%m.%Y')
	def get_reverse_url(self, target):
		return reverse(target, kwargs={'club_id': self.club_id, 'member_id': self.id})
	def get_editor_url(self):
		return self.get_reverse_url('editor:club_member_details')
	def get_delete_url(self):
		return self.get_reverse_url('editor:club_delete_member')
	def __str__(self):
		return  '{}, клуб {}'.format(self.runner.name(), self.club)

class User_stat(models.Model):
	# Exactly one value of (user, runner, club_member) must be not None
	user = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name='Пользователь', on_delete=models.CASCADE, null=True, default=None, blank=True)
	runner = models.ForeignKey(Runner, verbose_name='Бегун', on_delete=models.CASCADE, null=True, default=None, blank=True)
	club_member = models.ForeignKey(Club_member, verbose_name='Член клуба', on_delete=models.CASCADE, null=True, default=None, blank=True)
	distance = models.ForeignKey(Distance, verbose_name='Дистанция', on_delete=models.CASCADE)
	year = models.SmallIntegerField(verbose_name='Год', null=True, default=None, blank=True)

	n_starts = models.SmallIntegerField(verbose_name='Число участий')
	is_popular = models.BooleanField(verbose_name='Попадает ли в число популярных, если их слишком много', default=False)

	value_best = models.IntegerField(verbose_name='Личный рекорд', null=True, default=None, blank=True)
	pace_best = models.SmallIntegerField(verbose_name='Личный рекорд: темп (сек/км)', null=True, default=None, blank=True)
	best_result = models.ForeignKey(Result, default=None, null=True, blank=True, on_delete=models.SET_NULL)

	value_best_age_coef = models.IntegerField(verbose_name='Личный рекорд с учётом возрастного коэффициента', null=True, default=None, blank=True)
	best_result_age_coef = models.ForeignKey(Result, default=None, null=True, blank=True, on_delete=models.SET_NULL,
		related_name='best_result_age_coef_set')

	value_mean = models.IntegerField(verbose_name='Средний результат', null=True, default=None, blank=True)
	value_mean_age_coef = models.IntegerField(verbose_name='Средний результат с учётом возрастного коэффициента', null=True, default=None,
		blank=True)
	pace_mean = models.SmallIntegerField(verbose_name='Средний результат: темп (сек/км)', null=True, default=None, blank=True)

	last_update = models.DateTimeField(verbose_name='Дата последнего обновления', auto_now=True)
	def get_value_best(self):
		return self.distance.strResult(self.value_best)
	def get_value_best_age_coef(self):
		if self.value_best_age_coef is None:
			send_panic_email(
				'get_value_best_age_coef is called when value_best_age_coef is None',
				'Problem occured with user {}, runner {}, club_member {}'.format(self.user_id, self.runner_id, self.club_member_id)
			)
			return ''
		return self.distance.strResult(self.value_best_age_coef)
	def get_value_mean(self):
		return self.distance.strResult(self.value_mean)
	class Meta:
		constraints = [
			models.UniqueConstraint(fields=['user', 'distance', 'year'], name='user_distance_year'),
			models.UniqueConstraint(fields=['runner', 'distance', 'year'], name='runner_distance_year'),
			models.UniqueConstraint(fields=['club_member', 'distance', 'year'], name='club_member_distance_year'),
		]
	def __str__(self):
		return 'Статистика пользователя {} на дистанции {}'.format(self.user.get_full_name(), self.distance.name)

# Age factors from https://world-masters-athletics.com
CUR_AGE_COEFS_YEAR = 2022
class Masters_age_coefficient(models.Model):
	year = models.SmallIntegerField(verbose_name='Год')
	gender = models.SmallIntegerField(verbose_name='Пол')
	age = models.SmallIntegerField(verbose_name='Возраст')
	distance = models.ForeignKey(Distance, verbose_name='Дистанция', on_delete=models.PROTECT)
	value = models.DecimalField(verbose_name='Коэффициент', max_digits=7, decimal_places=4)
	class Meta:
		constraints = [
			models.UniqueConstraint(fields=['year', 'gender', 'age', 'distance'], name='year_gender_age_distance'),
		]

class Runner_name(models.Model):
	name = models.CharField(verbose_name='Имя', max_length=30, unique=True, blank=False)
	gender = models.SmallIntegerField(verbose_name='Пол', choices=results_util.GENDER_CHOICES[1:])
	@classmethod
	def gender_from_name(cls, name: str) -> int:
		runner_name = cls.objects.filter(name=name).first()
		if runner_name:
			return runner_name.gender
		return results_util.GENDER_UNKNOWN

class Age_category(models.Model):
	''' Пытаемся по названию возрастной группы определять диапазон возрастов тех, кто в неё попадает. Ненадёжно. '''
	name = models.CharField(verbose_name='Название группы', max_length=100, unique=True)
	birthyear_min = models.SmallIntegerField(verbose_name='Минимальный год рождения', default=None, null=True)
	birthyear_max = models.SmallIntegerField(verbose_name='Максимальный год рождения', default=None, null=True)
	age_min = models.SmallIntegerField(verbose_name='Минимальный возраст', default=None, null=True)
	age_max = models.SmallIntegerField(verbose_name='Максимальный возраст', default=None, null=True)
	is_bad = models.BooleanField(verbose_name='Безнадежное название', default=False)

def organizer_logo_name(instance, filename):
	new_name = 'dj_media/organizers/logo/' + str(instance.id) + '.' + file_extension(filename)
	fullname = os.path.join(settings.MEDIA_ROOT, new_name)
	try:
		os.remove(fullname)
	except:
		pass
	return new_name

class DefaultOrganizerManager(models.Manager):
	def get_queryset(self):
		return super(DefaultOrganizerManager, self).get_queryset().exclude(id=FAKE_ORGANIZER_ID)

	@property
	def fake_object(self):
		return super(DefaultOrganizerManager, self).get_queryset().all().get(id=FAKE_ORGANIZER_ID)

class Organizer(models.Model):
	objects = DefaultOrganizerManager()
	all_objects = models.Manager()

	name = models.CharField(verbose_name='Название организации или ФИО организатора', max_length=100, unique=True)
	url_site = custom_fields.MyURLField(verbose_name='Сайт организатора', max_length=MAX_URL_LENGTH, blank=True)
	url_vk = models.URLField(verbose_name='Страничка ВКонтакте', max_length=100, blank=True)
	url_facebook = models.URLField(verbose_name='Страничка в фейсбуке', max_length=100, blank=True)
	url_instagram = models.URLField(verbose_name='Страничка в инстраграме', max_length=100, blank=True)
	logo = models.ImageField(verbose_name='Логотип (не больше 2 мегабайт)', max_length=255, upload_to=organizer_logo_name,
		validators=[validate_image], blank=True)
	user = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name='Представитель организатора на ПроБЕГе',
		on_delete=models.SET_NULL, default=None, null=True, blank=True)

	director_name = models.CharField(verbose_name='Имя директора', max_length=50, blank=True)
	phone_number = models.CharField(verbose_name='Контактный телефон организации', max_length=20, blank=True)
	email = models.EmailField(verbose_name='E-mail организации', max_length=MAX_EMAIL_LENGTH, blank=True)

	created_time = models.DateTimeField(verbose_name='Дата создания', auto_now_add=True)
	created_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name='Кто добавил на сайт', related_name='organizers_created_set',
		on_delete=models.SET_NULL, default=None, null=True, blank=True)
	def get_reverse_url(self, target):
		return reverse(target, kwargs={'organizer_id': self.id})
	def get_absolute_url(self):
		return self.get_reverse_url('results:organizer_details')
	def get_editor_url(self):
		return self.get_reverse_url('editor:organizer_details')
	def get_add_series_url(self):
		return self.get_reverse_url('editor:organizer_add_series')
	def get_history_url(self):
		return self.get_reverse_url('editor:organizer_changes_history')
	def has_dependent_objects(self):
		return self.series_set.exists()
	def __str__(self):
		return self.name
	def get_children(self):
		return self.series_set.all()

class Useful_label(models.Model):
	name = models.CharField(verbose_name='Название', max_length=100, unique=True)
	priority = models.IntegerField(verbose_name='Приоритет', default=0)
	created_time = models.DateTimeField(verbose_name='Дата создания', auto_now_add=True)
	created_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name='Кто добавил на сайт',
		on_delete=models.SET_NULL, default=None, null=True, blank=True)
	class Meta:
		indexes = [
			models.Index(fields=['priority', 'name']),
		]
		ordering = ['priority', 'name']
	def __str__(self):
		return self.name

class Useful_link(models.Model):
	name = models.CharField(verbose_name='Название', max_length=100, unique=True)
	url = custom_fields.MyURLField(verbose_name='Ссылка', max_length=MAX_URL_LENGTH)
	labels = models.ManyToManyField(Useful_label, verbose_name='Метки', through='Link_label')
	created_time = models.DateTimeField(verbose_name='Дата создания', auto_now_add=True)
	created_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name='Кто добавил на сайт',
		on_delete=models.SET_NULL, default=None, null=True, blank=True)
	class Meta:
		ordering = ('name', )
	def get_reverse_url(self, target):
		return reverse(target, kwargs={'link_id': self.id})
	def get_editor_url(self):
		return self.get_reverse_url('editor:useful_link_details')
	def get_history_url(self):
		return self.get_reverse_url('editor:useful_link_changes_history')
	def __str__(self):
		return f'{self.name} ({self.url})'

class Link_label(models.Model):
	label = models.ForeignKey(Useful_label, on_delete=models.CASCADE)
	link = models.ForeignKey(Useful_link, on_delete=models.CASCADE)
	priority = models.IntegerField(verbose_name='Приоритет для данной ссылки внутри данной метки', default=0)
	created_time = models.DateTimeField(verbose_name='Дата создания', auto_now_add=True)
	created_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name='Кто добавил на сайт',
		on_delete=models.SET_NULL, default=None, null=True, blank=True)
	class Meta:
		constraints = [
			models.UniqueConstraint(fields=['label', 'link'], name='label_link'),
		]
		ordering = ('label', 'priority')

RECORD_AGE_GROUP_TYPE_YOUNG = 0
RECORD_AGE_GROUP_TYPE_ABSOLUTE = 1
RECORD_AGE_GROUP_TYPE_SENIOR = 2
RECORD_AGE_GROUP_TYPES = (
	(RECORD_AGE_GROUP_TYPE_YOUNG, 'Молодёжь'),
	(RECORD_AGE_GROUP_TYPE_ABSOLUTE, 'Абсолют'),
	(RECORD_AGE_GROUP_TYPE_SENIOR, 'Ветераны'),
)
AGE_GROUP_RECORDS_AGE_GAP = 5
class Record_age_group(models.Model):
	age_min = models.SmallIntegerField(verbose_name='Минимальный возраст', default=None, null=True, unique=True)
	age_group_type = models.SmallIntegerField(verbose_name='Тип возрастной группы', choices=RECORD_AGE_GROUP_TYPES,
		default=RECORD_AGE_GROUP_TYPE_SENIOR)
	class Meta:
		verbose_name = 'Возрастная группа для рекордов стран'
		ordering = ['age_group_type', 'age_min']
		indexes = [
			models.Index(fields=['age_group_type', 'age_min']),
		]
	def get_short_name(self, gender):
		if self.age_group_type == RECORD_AGE_GROUP_TYPE_ABSOLUTE:
			return ''
		gender_letter = results_util.GENDER_CHOICES[gender][1][0]
		if self.age_group_type == RECORD_AGE_GROUP_TYPE_YOUNG:
			return f'{gender_letter}<{self.age_min}'
		return f'{gender_letter}{self.age_min}–{self.age_min + AGE_GROUP_RECORDS_AGE_GAP - 1}'
	def get_full_name_in_prep_case(self, gender):
		if self.age_group_type == RECORD_AGE_GROUP_TYPE_ABSOLUTE:
			return ''
		return ' в группе ' + self.get_short_name(gender)
	def get_int_value(self):
		if self.age_min is None:
			return 0
		return self.age_min
	def __str__(self):
		if self.age_min is None:
			return 'Абсолют'
		if self.age_group_type == RECORD_AGE_GROUP_TYPE_YOUNG:
			return '<{}'.format(self.age_min)
		return str(self.age_min)
	def range(self):
		if self.age_min is None:
			return 'Абсолют'
		if self.age_group_type == RECORD_AGE_GROUP_TYPE_YOUNG:
			return '<{}'.format(self.age_min)
		return '{}–{}'.format(self.age_min, self.age_min + AGE_GROUP_RECORDS_AGE_GAP - 1)

RECORD_SURFACE_TYPES = (
	(results_util.SURFACE_DEFAULT, 'неизвестно'),
	(results_util.SURFACE_ROAD, 'шоссе'),
	(results_util.SURFACE_STADIUM, 'стадион'),
	(results_util.SURFACE_INDOOR, 'манеж с кругом 200 метров'),
)
RECORD_RESULT_ORDERING = ['country', 'gender', 'age_group', 'distance', 'surface_type', 'cur_place', 'was_record_ever', 'date']

def func_race_has_correct_surface(record_result): # or for Result_not_for_age_group_record
	if record_result.surface_type == results_util.SURFACE_DEFAULT:
		return True
	race = record_result.result.race if record_result.result else record_result.race
	race_surface_type = race.get_surface_type()
	if record_result.surface_type == results_util.SURFACE_INDOOR:
		if record_result.distance_id == results_util.DIST_60M_ID:
			return race_surface_type in (results_util.SURFACE_INDOOR, results_util.SURFACE_INDOOR_NONSTANDARD)
		return race_surface_type == results_util.SURFACE_INDOOR
	if record_result.surface_type in (results_util.SURFACE_ROAD, results_util.SURFACE_STADIUM):
		return race_surface_type == record_result.surface_type
	return False

class Record_result(models.Model):
	country = models.ForeignKey(Country, verbose_name='Страна', on_delete=models.PROTECT, null=True, blank=True)
	gender = models.SmallIntegerField(verbose_name='Пол', choices=results_util.GENDER_CHOICES[1:])
	age_group = models.ForeignKey(Record_age_group, verbose_name='Возрастная группа', on_delete=models.PROTECT)
	age_on_event_date = models.SmallIntegerField(verbose_name='Полных лет на день забега, или минимальное из двух возможных значений',
		default=None, null=True, blank=True)
	is_age_on_event_date_known = models.BooleanField(verbose_name='Известен ли точный возраст на день забега?', default=False)
	distance = models.ForeignKey(Distance, verbose_name='Дистанция', on_delete=models.PROTECT)
	protocol = models.ForeignKey(Document, verbose_name='Протокол забега', on_delete=models.SET_NULL, null=True, blank=True)
	surface_type = models.SmallIntegerField(verbose_name='Тип поверхности', choices=RECORD_SURFACE_TYPES)
	cur_place_electronic = models.SmallIntegerField(verbose_name='Текущее место среди результатов с электронным хронометражом',
		default=None, null=True, blank=True)

	cur_place = models.SmallIntegerField(verbose_name='Текущее место (только для первой тройки/десятки на сегодня)', default=None, null=True, blank=True)
	was_record_ever = models.BooleanField(verbose_name='Было ли какое-то время рекордным результатом?', default=False)
	is_official_record = models.BooleanField(verbose_name='Был ли когда-либо официальным рекордом по версии ВФЛА?', default=False)
	is_bad_record = models.BooleanField(verbose_name='Не годится в рекорды по каким-то причинам', default=False)
	is_world_record = models.BooleanField(verbose_name='Является ли действующим мировым рекордом', default=False)
	is_europe_record = models.BooleanField(verbose_name='Является ли действующим рекордом Европы', default=False)
	ignore_for_country_records = models.BooleanField(verbose_name='Не рассматривать для рекордов страны (для рекордов мира и Европы)', default=False)
	runner_place = models.SmallIntegerField(verbose_name='Место бегуна по лучшему результату за карьеру (ставится для лучшего результата человека)',
		default=None, null=True, blank=True)

	fname = models.CharField(verbose_name='Имя', max_length=100, blank=True)
	lname = models.CharField(verbose_name='Фамилия', max_length=100, blank=True)
	city = models.ForeignKey(City, verbose_name='Город бегуна', on_delete=models.PROTECT, default=None, null=True, blank=True)
	runner_country = models.ForeignKey(Country, verbose_name='Для мировых рекордов: страна бегуна', related_name='record_result_runner_set', on_delete=models.PROTECT, null=True, blank=True)
	value = models.IntegerField(verbose_name='Результат числом', default=None, null=True, blank=True)
	runner = models.ForeignKey(Runner, verbose_name='Бегун', on_delete=models.SET_NULL, null=True, default=None, blank=True)
	result = models.ForeignKey(Result, verbose_name='Результат', on_delete=models.SET_NULL, null=True, default=None, blank=True)
	event_city = models.CharField(verbose_name='Город, где установлен рекорд', max_length=100, blank=True)
	event_country = models.ForeignKey(Country, verbose_name='Страна, где установлен рекорд', related_name='record_result_event_set', on_delete=models.PROTECT, null=True, blank=True)

	race = models.ForeignKey(Race, verbose_name='Забег', on_delete=models.SET_NULL, null=True, default=None, blank=True)
	date = models.DateField(verbose_name='Дата или год старта', null=True, default=None, blank=True)
	is_date_known = models.BooleanField(verbose_name='Известна ли точная дата старта', default=False)
	timing = models.SmallIntegerField(verbose_name='Вид хронометража (если забег неизвестен)', default=TIMING_UNKNOWN, choices=TIMING_TYPES,
		db_index=True)

	comment = models.CharField(verbose_name='Комментарий', max_length=250, blank=True)
	is_from_shatilo = models.BooleanField(verbose_name='Взят из базы Шатило?', default=False)
	is_from_hinchuk = models.BooleanField(verbose_name='Взят из заметок Хинчук?', default=False)
	is_from_vfla = models.BooleanField(verbose_name='Взят с сайта ВФЛА?', default=False)
	is_approved_record_now = models.BooleanField(verbose_name='Считается ли нашей комиссией рекордом России сейчас', default=False)
	added_time = models.DateTimeField(verbose_name='Время занесения в БД', auto_now_add=True, db_index=True)
	created_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name='Кто добавил результат',
		on_delete=models.SET_NULL, default=None, null=True, blank=True)
	class Meta:
		verbose_name = 'Рекордный результат для какой-то страны в какой-то возрастной группе'
		ordering = RECORD_RESULT_ORDERING
		indexes = [
			models.Index(fields=RECORD_RESULT_ORDERING),
			models.Index(fields=['country', 'gender', 'age_group', 'distance', 'surface_type', 'date']),
			models.Index(fields=['country', 'gender', 'age_group', 'distance', 'surface_type', 'value', 'date']),
			models.Index(fields=['country', 'gender', 'age_group', 'distance', 'surface_type', 'is_world_record']),
			models.Index(fields=['country', 'gender', 'age_group', 'distance', 'surface_type', 'is_europe_record']),
		]
		constraints = [
			models.UniqueConstraint(fields=['country', 'gender', 'age_group', 'distance', 'surface_type', 'cur_place'], name='record_result_country_blah'),
		]
	def fill_and_save_if_needed(self, force=False):
		to_save = False
		if self.result:
			if force or (self.race is None):
				self.race = self.result.race
				to_save = True
			if force or not self.is_date_known:
				self.date = self.race.get_start_date()
				self.is_date_known = True
				to_save = True
			if force or not self.value:
				self.value = self.result.result
				to_save = True
			if self.result.runner:
				if force or not self.runner:
					self.runner = self.result.runner
					to_save = True
				if self.runner.city:
					if force or not self.city:
						self.city = self.runner.city
						to_save = True
			else:
				if (not self.lname) and self.result.lname:
					self.lname = self.result.lname
					to_save = True
				if (not self.fname) and self.result.fname:
					self.fname = self.result.fname
					to_save = True
			if self.runner and self.runner.birthday_known and (force or not self.age_on_event_date or not self.is_age_on_event_date_known):
				self.age_on_event_date = self.race.get_age_on_event_date(self.runner.birthday)
				self.is_age_on_event_date_known = True
				to_save = True
		elif self.race and not self.date:
			self.date = self.race.get_start_date()
			self.is_date_known = True
			to_save = True
		elif self.is_date_known:
			if self.runner and self.runner.birthday_known and (force or not self.age_on_event_date or not self.is_age_on_event_date_known):
				self.age_on_event_date = results_util.get_age_on_date(self.date, self.runner.birthday)
				self.is_age_on_event_date_known = True
				to_save = True
		if (not self.age_on_event_date) and self.runner and self.runner.birthday and self.date:
			self.age_on_event_date = self.date.year - self.runner.birthday.year - 1
			self.is_age_on_event_date_known = False
			to_save = True
		if self.race:
			if force or not self.event_city:
				self.event_city = self.race.event.strCityCountry()[:100]
				self.event_country = None
				to_save = True
		if to_save:
			self.save()
		return to_save
	def get_value(self):
		if self.value is None:
			return ''
		if self.distance.distance_type in TYPES_MINUTES:
			return meters2string(self.value)
		return centisecs2time(self.value, show_zero_hundredths=(self.distance.length < 5000) and (self.timing != TIMING_HAND))
	def get_date(self):
		if self.is_date_known:
			return results_util.date2str(self.date)
		if self.date:
			return f'{self.date.year}&nbsp;г.'
		return ''
	def get_timing_type(self): # 1 = hand timing, 2 = maybe hand timing, 0 = electronic or road race
		if self.distance.distance_type in TYPES_MINUTES:
			return 0
		if self.distance.length >= 5000:
			return 0
		if self.result:
			if self.result.race.timing == TIMING_ELECTRONIC:
				return 0
			if self.result.race.timing == TIMING_HAND:
				return 1
			if (self.result.race.timing == TIMING_UNKNOWN) and ((self.result.result % 10) != 0):
				return 0
			return 2
		if (self.value % 10) != 0:
			return 0
		if self.timing == TIMING_ELECTRONIC:
			return 0
		if self.timing == TIMING_HAND:
			return 1
		return 2
	def is_electronic(self): # For TYPE_METERS only
		return self.get_timing_type() == 0
	def get_reverse_url(self, target):
		return reverse(target, kwargs={'record_result_id': self.id})
	def get_editor_url(self):
		return self.get_reverse_url('editor:age_group_record_details')
	def get_admin_editor_url(self):
		return f'/admin/results/record_result/{self.id}/change/'
	def get_delete_url(self):
		return self.get_reverse_url('editor:age_group_record_delete')
	def get_add_to_cur_session_url(self):
		return self.get_reverse_url('editor:age_group_add_to_cur_session')
	def get_group_url(self):
		if self.distance_id in results_util.DISTANCES_FOR_COUNTRY_ULTRA_RECORDS:
			return reverse('results:ultra_record_details', kwargs={'country_id': self.country_id, 'gender_code': self.get_gender_code(),
				'distance_code': self.get_distance_code()})
		age = self.age_group.age_min
		return reverse('results:age_group_record_details', kwargs={'country_id': self.country_id, 'gender_code': self.get_gender_code(),
			'age': age if age else 0, 'distance_code': self.get_distance_code(), 'surface_code': self.get_surface_code()})
	def get_ultra_group_url(self):
		return reverse('results:ultra_record_details', kwargs={'country_id': self.country_id, 'gender_code': self.get_gender_code(),
			'distance_code': self.get_distance_code()})
	def get_gender_code(self):
		return results_util.GENDER_CODES.get(self.gender, '')
	def get_distance_code(self):
		return results_util.DISTANCE_CODES.get(self.distance_id, '')
	def get_surface_code(self):
		return results_util.SURFACE_CODES.get(self.surface_type, '')
	race_has_correct_surface = func_race_has_correct_surface
	def get_age_group(self): # Like 'Ж 40-44'
		return f'{results_util.GENDER_CHOICES[self.gender][1][0]} {self.age_group.range()}'
	def get_explanation(self):
		properties = []
		if self.cur_place == 1:
			properties.append(f'действующий рекорд')
		elif self.cur_place:
			properties.append(f'{self.cur_place}-й результат за всю историю')
		if self.cur_place_electronic == 1:
			properties.append(f'действующий рекорд с электронным хронометражом')
		elif self.cur_place_electronic:
			properties.append(f'{self.cur_place_electronic}-й результат с электронным хронометражом за всю историю')
		if self.was_record_ever and (self.cur_place != 1):
			properties.append('бывший рекорд страны')
		return ', '.join(properties)
	def get_explanation_short(self):
		if self.cur_place == 1:
			res = f'рекорд {self.country.prep_case}'
		elif self.cur_place_electronic == 1:
			res = f'эл. рекорд {self.country.prep_case}'
		elif self.was_record_ever:
			res = f'быв. рекорд {self.country.prep_case}'
		else:
			return ''
		age_group_desc = self.age_group.get_short_name(self.gender)
		if age_group_desc:
			return f'{res} в {age_group_desc}'
		return res
	def get_age_on_event_date(self):
		if self.is_age_on_event_date_known:
			return f'{self.age_on_event_date} {results_util.ending(self.age_on_event_date, 11)}'
		if self.age_on_event_date:
			return f'{self.age_on_event_date} или {self.age_on_event_date + 1} {results_util.ending(self.age_on_event_date + 1, 11)}'
		return 'неизвестен'
	def get_short_age_group_name(self):
		return self.age_group.get_short_name(self.gender)
	def get_event_city_country(self): # Only for records from unknown event
		return ', '.join([str(x) for x in [self.event_city, self.event_country] if x])
	def get_desc(self):
		return f'{self.get_age_group()}, {self.distance}, {self.get_surface_type_display()}, {str(self)}, {self.get_date()}'
	def electronic_matters(self): # Whether the distance of this result is small enough to distinguish electronic and hand results.
		return (self.distance.distance_type == TYPE_METERS) and (self.distance.length <= results_util.MAX_DISTANCE_FOR_ELECTRONIC_RECORDS)
	def is_wind_speed_relevant(self):
		return (self.distance.id in (results_util.DIST_100M_ID, results_util.DIST_200M_ID)) and (self.surface_type == results_util.SURFACE_STADIUM)
	def get_distance_name(self):
		return self.distance.get_name(self.surface_type)
	def __str__(self):
		if self.result:
			round_hundredths = self.distance_id in (results_util.DIST_MARATHON_ID, results_util.DIST_HALFMARATHON_ID)
			res = self.distance.strResult(self.result.result, round_hundredths=round_hundredths, timing=self.result.race.timing)
		else:
			res = self.get_value()
		return res[results_util.RECORD_RESULT_SYMBOLS_TO_CUT.get(self.distance_id, 0):]

class Possible_record_result(models.Model):
	country = models.ForeignKey(Country, verbose_name='Страна', on_delete=models.PROTECT)
	gender = models.SmallIntegerField(verbose_name='Пол', choices=results_util.GENDER_CHOICES[1:])
	age_group = models.ForeignKey(Record_age_group, verbose_name='Возрастная группа', on_delete=models.PROTECT)
	age_on_event_date = models.SmallIntegerField(verbose_name='Полных лет на день забега', default=None, null=True, blank=True)
	distance = models.ForeignKey(Distance, verbose_name='Дистанция', on_delete=models.PROTECT)
	surface_type = models.SmallIntegerField(verbose_name='Тип поверхности', choices=RECORD_SURFACE_TYPES)

	result = models.ForeignKey(Result, verbose_name='Результат', on_delete=models.CASCADE)
	can_be_prev_record = models.BooleanField(verbose_name='Мог ли этот результат быть рекордным какое-то время', default=False)
	is_electronic = models.BooleanField(verbose_name='Потенциальный результат в тройке среди электронных', default=False)
	added_time = models.DateTimeField(verbose_name='Время занесения в БД', auto_now_add=True, db_index=True)
	class Meta:
		verbose_name = 'Возможный рекордный результат для какой-то страны в какой-то возрастной группе'
		indexes = [
			models.Index(fields=['country', 'gender', 'age_group', 'distance', 'surface_type']),
		]
	race_has_correct_surface = func_race_has_correct_surface
	def __str__(self):
		return str(self.result)

class Result_not_for_age_group_record(models.Model):
	country = models.ForeignKey(Country, verbose_name='Страна', on_delete=models.PROTECT)
	gender = models.SmallIntegerField(verbose_name='Пол', choices=results_util.GENDER_CHOICES[1:])
	age_group = models.ForeignKey(Record_age_group, verbose_name='Возрастная группа', on_delete=models.PROTECT)
	distance = models.ForeignKey(Distance, verbose_name='Дистанция', on_delete=models.PROTECT)
	surface_type = models.SmallIntegerField(verbose_name='Тип поверхности', choices=RECORD_SURFACE_TYPES)
	result = models.ForeignKey(Result, verbose_name='Результат', default=None, null=True, blank=True, on_delete=models.CASCADE)
	comment = models.CharField(verbose_name='Доступный всем комментарий', max_length=100, blank=True)
	comment_private = models.CharField(verbose_name='Комментарий для админов', max_length=100, blank=True)
	created_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name='Кто добавил результат в плохие',
		on_delete=models.PROTECT, default=None, null=True, blank=True)
	class Meta:
		constraints = [
			models.UniqueConstraint(fields=['country', 'gender', 'age_group', 'distance', 'surface_type', 'result'], name='result_not_for_age_group_country_blah'),
		]
	race_has_correct_surface = func_race_has_correct_surface
	def get_mark_good_url(self):
		return reverse('editor:record_mark_good', kwargs={'bad_record_id': self.id})
	def get_editor_url(self):
		return f'/admin/results/result_not_for_age_group_record/{self.id}/change/'
	def __str__(self):
		return (f'{self.country} {self.get_gender_display()} {self.age_group.get_short_name(self.gender)} {self.distance} {self.result} '
			+ f'{self.result.runner}')

class Record_candidate_results_number(models.Model):
	country = models.ForeignKey(Country, verbose_name='Страна', on_delete=models.PROTECT)
	gender = models.SmallIntegerField(verbose_name='Пол', choices=results_util.GENDER_CHOICES[1:])
	age_group = models.ForeignKey(Record_age_group, verbose_name='Возрастная группа', on_delete=models.PROTECT)
	distance = models.ForeignKey(Distance, verbose_name='Дистанция', on_delete=models.PROTECT)
	surface_type = models.SmallIntegerField(verbose_name='Тип поверхности', choices=RECORD_SURFACE_TYPES)
	number = models.IntegerField(verbose_name='Число подходящих под условия результатов', default=None, null=True, blank=True)
	class Meta:
		constraints = [
			models.UniqueConstraint(fields=['country', 'gender', 'age_group', 'distance', 'surface_type'], name='record_candidate_country_blah'),
		]

class Record_category_comment(models.Model):
	country = models.ForeignKey(Country, verbose_name='Страна', on_delete=models.PROTECT)
	gender = models.SmallIntegerField(verbose_name='Пол', choices=results_util.GENDER_CHOICES[1:])
	age_group = models.ForeignKey(Record_age_group, verbose_name='Возрастная группа', on_delete=models.PROTECT)
	distance = models.ForeignKey(Distance, verbose_name='Дистанция', on_delete=models.PROTECT)
	surface_type = models.SmallIntegerField(verbose_name='Тип поверхности', choices=RECORD_SURFACE_TYPES)
	content = models.CharField(verbose_name='Текст комментария', max_length=1000)
	created_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name='Кто добавил результат в плохие',
		on_delete=models.PROTECT, default=None, null=True, blank=True)
	added_time = models.DateTimeField(verbose_name='Время занесения в БД', auto_now_add=True)
	class Meta:
		verbose_name = 'Комментарий к категории рекордов в возрастных группах'
	def get_editor_url(self):
		return '/admin/results/record_category_comment/{}'.format(self.id)
	def __str__(self):
		return self.content

class Function_call(models.Model):
	name = models.CharField(verbose_name='Название', max_length=100, db_index=True)
	args = models.CharField(verbose_name='Параметры', max_length=100)
	description = models.CharField(verbose_name='Описание функции', max_length=100)
	error = models.CharField(verbose_name='Ошибка выполнения', max_length=100)
	result = models.CharField(verbose_name='Возвращенное значение', max_length=1000)
	start_time = models.DateTimeField(verbose_name='Время запуска', db_index=True)
	running_time = models.DurationField(verbose_name='Время работы', default=None, null=True)
	message = models.ForeignKey(Message_from_site, verbose_name='Письмо об этом вызове', default=None, null=True, on_delete=models.PROTECT)
	class Meta:
		verbose_name = 'Попытка вызова функции'
	def __str__(self):
		return f'{self.name}({self.args})'

COURSE_CERTIFICATE_GRADES = (
	(1, 'A'),
	(2, 'B'),
	(3, 'C'),
)

class Course_certificate(models.Model):
	series = models.ForeignKey(Series, verbose_name='Серия забегов', on_delete=models.SET_NULL, null=True, blank=True)
	distance = models.ForeignKey(Distance, verbose_name='Дистанция', on_delete=models.PROTECT)
	measurer = models.CharField(verbose_name='Измеритель', max_length=100)
	grade = models.SmallIntegerField(verbose_name='Уровень', default=2, choices=COURSE_CERTIFICATE_GRADES)
	file_cert = models.FileField(verbose_name='Сертификат', upload_to='dj_media/course_certs/', default=None, null=True, blank=True)
	file_scheme = models.FileField(verbose_name='Схема трассы', upload_to='dj_media/course_certs/schemes/', default=None, null=True, blank=True)
	file_report = models.FileField(verbose_name='Подробный отчёт', upload_to='dj_media/course_certs/reports/', default=None, null=True, blank=True)
	date_measured = models.DateField(verbose_name='Дата измерения', null=True, blank=True)
	date_expires = models.DateField(verbose_name='Действителен до', null=True, blank=True)
	added_time = models.DateTimeField(verbose_name='Время занесения в БД', auto_now_add=True)
	created_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name='Кто добавил',
		on_delete=models.SET_NULL, default=None, null=True, blank=True)
	class Meta:
		verbose_name = 'Сертификат трассы IAAF-AIMS'
	def get_cert_number(self):
		if self.file_cert:
			return os.path.basename(self.file_cert.name).split('.')[0]
	def __str__(self):
		return f'{self.series.name if self.series else ''} {self.date_measured} — {self.date_expires}'

class Ad(models.Model):
	place = models.URLField(verbose_name='URL страницы с объявлением', max_length=100)
	company = models.CharField(verbose_name='Рекламодатель', max_length=100)
	added_time = models.DateTimeField(verbose_name='Время занесения в БД', auto_now_add=True)
	created_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name='Кто добавил',
		on_delete=models.SET_NULL, default=None, null=True, blank=True)
	class Meta:
		verbose_name = 'Рекламное объявление'
		constraints = [
			models.UniqueConstraint(fields=['place', 'company'], name='place_company'),
		]
	def __str__(self):
		return f'{self.company} ({self.place}, id {self.id})'

class Ad_click(models.Model):
	ad = models.ForeignKey(Ad, verbose_name='Объявление', on_delete=models.CASCADE, null=True, blank=True)
	referer = models.CharField(verbose_name='На какой странице кликнули', max_length=100)
	ip = models.CharField(verbose_name='IP пользователя', max_length=20)
	is_admin = models.BooleanField(verbose_name='Кликнул админ сайта?', default=False)
	click_time = models.DateTimeField(verbose_name='Время занесения в БД', auto_now_add=True)
	class Meta:
		verbose_name = 'Клик по рекламному объявлению на сайте'
	def __str__(self):
		return f'{self.click_time} (id {self.id})'

class Ad_clicks_by_day(models.Model):
	ad = models.ForeignKey(Ad, verbose_name='Объявление', on_delete=models.CASCADE, null=True, blank=True)
	date = models.DateField(verbose_name='Дата', default=None, null=True, blank=True)
	value = models.SmallIntegerField(verbose_name='Число кликов', default=0)
	class Meta:
		verbose_name = 'Число кликов по дням и за всегда'
		constraints = [
			models.UniqueConstraint(fields=['ad', 'date'], name='ad_date'),
		]
	def __str__(self):
		return f'{self.date} (id {self.id})'

MIN_FINISHES_FOR_STRIKE = 3 # We won't look at runners with 2 finishes.
MIN_FINISHES_FOR_STRIKE_PERCENT = 20 # We won't look at runners with less than 20% finishes.
MAX_STRIKES_FOR_SERIES = 100 # We create Strike objects for ~100 runners or less for each series.
class Strike(models.Model):
	series = models.ForeignKey(Series, verbose_name='Серия', on_delete=models.CASCADE)
	distance = models.ForeignKey(Distance, verbose_name='Дистанция', on_delete=models.CASCADE)
	runner = models.ForeignKey(Runner, verbose_name='Бегун', on_delete=models.CASCADE)
	total_participations = models.SmallIntegerField(verbose_name='Число финишей на дистанции')
	total_participations_in_row = models.SmallIntegerField(verbose_name='Число финишей подряд')
	is_annual_event = models.BooleanField(verbose_name='Правда ли, что забеги проходят не чаще раза в год')
	best_result = models.IntegerField(verbose_name='Лучший результат', null=True, default=None)
	average_result = models.IntegerField(verbose_name='Средний результат', null=True, default=None)
	first = models.ForeignKey(Race, verbose_name='Первое участие', related_name='first_strike', on_delete=models.CASCADE, null=True)
	last = models.ForeignKey(Race, verbose_name='Последнее участие', related_name='last_strike', on_delete=models.CASCADE, null=True)
	first_in_row = models.ForeignKey(Race, verbose_name='Первое участие в ряду', related_name='first_in_row_strike', on_delete=models.CASCADE, null=True)
	last_in_row = models.ForeignKey(Race, verbose_name='Последнее участие в ряду', related_name='last_in_row_strike', on_delete=models.CASCADE, null=True)
	class Meta:
		constraints = [
			models.UniqueConstraint(fields=['series', 'distance', 'runner'], name='series_distance_runner'),
		]
		indexes = [
			models.Index(fields=['series', 'distance', 'total_participations', 'total_participations_in_row']),
		]
	def get_value_best(self):
		return self.distance.strResult(self.best_result) if self.best_result else ''
	def get_value_mean(self):
		return self.distance.strResult(self.average_result) if self.average_result else ''

# Pairs (series, distance) for which we should recalculate strikes.
class Strike_queue(models.Model):
	series = models.ForeignKey(Series, verbose_name='Серия', on_delete=models.CASCADE)
	distance = models.ForeignKey(Distance, verbose_name='Дистанция', on_delete=models.CASCADE)
	class Meta:
		constraints = [
			models.UniqueConstraint(fields=['series', 'distance'], name='queue_series_distance'),
		]

# For strikes.
class Series_distance_data(models.Model):
	series = models.ForeignKey(Series, verbose_name='Серия', on_delete=models.CASCADE)
	distance = models.ForeignKey(Distance, verbose_name='Дистанция', on_delete=models.CASCADE)
	n_events = models.IntegerField(verbose_name='Забегов в серии с такой дистанцией и хоть частично загруженными результатами')
	first = models.ForeignKey(Event, verbose_name='Первый забег', related_name='first_distance_data', on_delete=models.CASCADE)
	last = models.ForeignKey(Event, verbose_name='Последний забег', related_name='last_distance_data', on_delete=models.CASCADE)
	class Meta:
		constraints = [
			models.UniqueConstraint(fields=['series', 'distance'], name='distance_data_series_distance'),
		]

class Regions_visited(models.Model):
	country = models.ForeignKey(Country, verbose_name='Страна', default='RU', on_delete=models.CASCADE)
	distance = models.ForeignKey(Distance, verbose_name='Дистанция', on_delete=models.CASCADE, null=True, default=None)
	runner = models.ForeignKey(Runner, verbose_name='Бегун', on_delete=models.CASCADE)
	place = models.SmallIntegerField(verbose_name='Место')
	n_finishes = models.SmallIntegerField(verbose_name='Число финишей')
	value = models.SmallIntegerField(verbose_name='Число регионов, в которых финишировал(а) на данной дистанции')
	class Meta:
		constraints = [
			models.UniqueConstraint(fields=['country', 'distance', 'runner'], name='country_distance_runner'),
		]
		indexes = [
			models.Index(fields=['country', 'distance', 'value']),
		]

DOWNLOAD_NOT_STARTED = 0
DOWNLOAD_SUCCESS = 1
DOWNLOAD_SUCCESS_WITH_WARNINGS = 2
DOWNLOAD_ERROR = 3
DOWNLOAD_IN_PROGRESS = 4
DOWNLOAD_ABANDONED = 5

DOWNLOAD_CHOICES = (
	(DOWNLOAD_NOT_STARTED, 'Загрузка ещё не началась'),
	(DOWNLOAD_SUCCESS, 'Загружен успешно'),
	(DOWNLOAD_SUCCESS_WITH_WARNINGS, 'Загружен с предупреждениями'),
	(DOWNLOAD_ERROR, 'Не удалось загрузить'),
	(DOWNLOAD_IN_PROGRESS, 'Загрузка продолжается'),
	(DOWNLOAD_ABANDONED, 'Перестали пытаться загружать'),
)

class Scraped_event(models.Model):
	platform = models.ForeignKey(Platform, on_delete=models.PROTECT)
	url_site = models.CharField(verbose_name='URL страницы с информацией о забеге', max_length=MAX_URL_LENGTH)
	url_results = models.CharField(verbose_name='URL страницы с результатами забега', max_length=MAX_URL_LENGTH)
	platform_series_id = models.CharField(verbose_name='ID серии на данной платформе, если есть', max_length=100)
	platform_event_id = models.CharField(verbose_name='ID забега на данной платформе, если есть', max_length=40)
	# For mikatiming: extra_data -> event, extra_data2 -> event_main_group
	extra_data = models.CharField(verbose_name='Дополнительный идентификатор забега, если нужен', max_length=30)
	extra_data2 = models.CharField(verbose_name='Дополнительный идентификатор забега-2, если нужен', max_length=30)
	event = models.ForeignKey(Event, on_delete=models.SET_NULL, null=True, default=None)
	start_date = models.DateField(verbose_name='Дата старта', null=True, default=None)
	protocol = models.OneToOneField(Document, verbose_name='Документ', on_delete=models.SET_NULL, null=True, default=None)
	added_time = models.DateTimeField(verbose_name='Время занесения в БД', auto_now_add=True, db_index=True)
	result = models.SmallIntegerField(verbose_name='Результат загрузки', choices=DOWNLOAD_CHOICES, default=DOWNLOAD_NOT_STARTED)
	last_attempt_finished = models.DateTimeField(verbose_name='Время завершения последней попытки', null=True, default=None)
	dont_retry_before = models.DateTimeField(verbose_name='С какого момента снова пробовать загрузить', null=True, default=None)
	class Meta:
		constraints = [
			models.UniqueConstraint(fields=['url_results', 'platform_event_id', 'extra_data'], name='url_results_extra_data'),
			# models.UniqueConstraint(fields=['url_results', 'extra_data'], name='url_results_extra_data'),
		]
		indexes = [
			models.Index(fields=['result', 'last_attempt_finished']),
			models.Index(fields=['platform', 'result', 'dont_retry_before', 'start_date', 'id', 'last_attempt_finished']),
		]

class Download_attempt(models.Model):
	scraped_event = models.ForeignKey(Scraped_event, verbose_name='Протокол в очереди', on_delete=models.CASCADE, null=True, default=None)
	start_time = models.DateTimeField(verbose_name='Во сколько началась обработка', auto_now_add=True)
	finish_time = models.DateTimeField(verbose_name='Во сколько закончилась обработка', null=True, default=None)
	result = models.SmallIntegerField(verbose_name='Результат загрузки', choices=DOWNLOAD_CHOICES, default=DOWNLOAD_IN_PROGRESS)
	status = models.CharField(verbose_name='Последний статус о процессе загрузки', max_length=1000)
	error = models.CharField(verbose_name='Текст ошибки', max_length=1000)
	class Meta:
		indexes = [
			models.Index(fields=['scraped_event', 'start_time']),
		]
	def UpdateStatus(self, message: str):
		self.status = (f'{datetime.datetime.now()}, pid {os.getpid()}: {message}')[:1000]
		print(self.status)
		self.save()

class Series_name(models.Model):
	platform = models.ForeignKey(Platform, on_delete=models.PROTECT)
	event_name = models.CharField(verbose_name='Название забега', max_length=150, unique=True)
	name = models.CharField(verbose_name='Название серии, к которой он относится', max_length=150)
	series = models.ForeignKey(Series, on_delete=models.PROTECT, null=True, blank=True, default=None)
	class Meta:
		verbose_name = 'Соответствие между именами забегов и серий для данной платформы'
	def __str__(self):
		res = f'({self.platform_id}) {self.event_name} -> {self.name}'
		if self.series_id:
			res += f' (series id {self.series_id})'
		return res

class Nyrr_runner(models.Model):
	fname = models.CharField(verbose_name='Имя', max_length=100)
	lname = models.CharField(verbose_name='Фамилия', max_length=100)
	sample_platform_id = models.BigIntegerField(verbose_name='Один из runnerId на платформе')
	class Meta:
		verbose_name = 'Бегун на платформе NYRR: площадка не возвращает их внутренние ID'

class Nyrr_result(models.Model):
	nyrr_runner_id = models.BigIntegerField(verbose_name='ID бегуна, показавшего результат с этим ID, в таблице Nyrr_runner', db_index=True)
	class Meta:
		verbose_name = 'Соответствие между ID результата на платформе (поле id в нашей таблице, поле runnerId на платформе) и объектом Nyrr_runner'

class Athlinks_series(models.Model):
	name = models.CharField(verbose_name='Имя', max_length=100)
	has_original_results = models.BooleanField(verbose_name='Загружают ли организаторы результаты последнего забега напрямую на athlinks')
	is_deleted = models.BooleanField(verbose_name='Когда-то имелась на сайте, но теперь удалена', default=True)
	last_check = models.DateTimeField(verbose_name='Время последний проверки метаданных')
	class Meta:
		verbose_name = 'Серии забегов на athlinks.com'

############### KLB

DISABILITY_GROUPS = ((0, 'нет'), (1, 'первая'), (2, 'вторая'), (3, 'третья'), )
class Klb_person(models.Model):
	id = models.AutoField(primary_key=True)
	ak_person_id = models.CharField(max_length=6, null=True, default=None)
	gender_raw = models.CharField(verbose_name='Пол (устар.)', max_length=1, blank=True)
	gender = models.SmallIntegerField(verbose_name='Пол', default=results_util.GENDER_UNKNOWN, db_index=True, choices=results_util.GENDER_CHOICES)

	country_raw = models.CharField(verbose_name='Страна (устар.)', max_length=100, blank=True)
	district_raw = models.CharField(verbose_name='Федеральный округ (устар.)', max_length=100, blank=True)
	region_raw = models.CharField(verbose_name='Регион (устар.)', max_length=100, blank=True)
	city_raw = models.CharField(verbose_name='Город (устар.)', max_length=100, blank=True)

	country = models.ForeignKey(Country, verbose_name='Страна', default="RU", null=True, on_delete=models.PROTECT)
	city = models.ForeignKey(City, verbose_name='Город', on_delete=models.PROTECT)

	email = models.CharField(verbose_name='E-mail', max_length=MAX_EMAIL_LENGTH, blank=True)
	phone_number = models.CharField(verbose_name='Мобильный телефон', max_length=MAX_PHONE_NUMBER_LENGTH, blank=True)
	skype = models.CharField(verbose_name='Skype', max_length=128, blank=True)
	ICQ = models.CharField(verbose_name='ICQ', max_length=100, blank=True)
	comment = models.CharField(verbose_name='Комментарий', max_length=250, blank=True)
	status = models.CharField(verbose_name='Статус (устар.)', max_length=15, default=None, null=True, blank=True) # Deprecated

	fname = models.CharField(verbose_name='Имя', max_length=100)
	lname = models.CharField(verbose_name='Фамилия', max_length=100)
	midname = models.CharField(verbose_name='Отчество', max_length=100, blank=True)
	birthday = models.DateField(verbose_name='Дата рождения', db_index=True)
	nickname = models.CharField(verbose_name='Ник', max_length=100, blank=True)
	postal_address = models.CharField(verbose_name='Почтовый адрес', max_length=MAX_POSTAL_ADDRESS_LENGTH, blank=True)
	disability_group = models.SmallIntegerField(verbose_name='Группа инвалидности', default=0, choices=DISABILITY_GROUPS)

	added_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name='Кто добавил в таблицу', on_delete=models.SET_NULL,
		null=True, blank=True, related_name="klb_persons_added_by_user")
	added_time = models.DateTimeField(verbose_name='Время создания', auto_now_add=True,
		null=True, blank=True)
	last_update = models.DateTimeField(verbose_name='Последнее изменение', auto_now=True,
		null=True, blank=True)
	def clean(self):
		if self.gender == GENDER_FEMALE:
			self.gender_raw = 'ж'
		elif self.gender == GENDER_MALE:
			self.gender_raw = 'м'
		if self.city:
			self.country = self.city.region.country
			self.city_raw = self.city.name_full(with_nbsp=False)
			if self.city.region.country.has_regions:
				self.region_raw = self.city.region.name
			else:
				self.region_raw = ""
			if self.city.region.district:
				self.district_raw = self.city.region.district.name
		else:
			self.city_raw = ""
			self.region_raw = ""
			self.district_raw = ""
		if self.country:
			self.country_raw = self.country.name
		else:
			self.country_raw = ""
	def update_person_contact_fields_and_prepare_letter(self, user, team, email, phone_number, prepare_letter=False, year=None,
			disability_group=None):
		# If we just added or updated Klb_participant
		if team and team.year < 2018: # No need to create a letter
			return
		year = team.year if team else year # team can be None here
		person_changed_fields = []
		if email and (self.email != email):
			self.email = email
			person_changed_fields.append('email')
		if phone_number and (self.phone_number != phone_number):
			self.phone_number = phone_number
			person_changed_fields.append('phone_number')
		if (disability_group is not None) and (disability_group != self.disability_group):
			self.disability_group = disability_group
			person_changed_fields.append('disability_group')
		if person_changed_fields:
			self.save()
			log_obj_create(user, self, ACTION_UPDATE, field_list=person_changed_fields, comment=f'При добавлении участника в КЛБМатч-{year}', verified_by=user)
		if prepare_letter and self.runner.user and (is_active_klb_year(year) or is_admin(self.runner.user)) and (self.runner.user != user):
			User_added_to_team_or_club.objects.create(
				user=self.runner.user,
				team=team,
				added_by=user,
			)
	def create_participant(self, team, creator, year=models_klb.CUR_KLB_YEAR, comment='', email='', phone_number='', add_to_club=False, disability_group=None):
		if team:
			year = team.year
			team_for_log = team
		else:
			team_for_log = Klb_team.objects.get(year=year, number=INDIVIDUAL_RUNNERS_CLUB_NUMBER)
		participant = Klb_participant(
			klb_person=self,
			year=year,
			team=team,
			date_registered=models_klb.participant_first_day(year, datetime.date.today()),
			email=email,
			phone_number=phone_number,
			city=self.city,
			added_by=creator,
		)
		participant.clean()
		participant.fill_age_group(commit=False)
		participant.save()
		log_obj_create(creator, self, ACTION_KLB_PARTICIPANT_CREATE, child_object=participant, comment=comment, verified_by=creator)
		log_obj_create(creator, team_for_log, ACTION_PERSON_ADD_TO_TEAM, child_object=participant, comment=comment, verified_by=creator)
		self.update_person_contact_fields_and_prepare_letter(creator, team_for_log, email, phone_number, prepare_letter=(team is not None),
			disability_group=disability_group)
		if add_to_club and team.club:
			last_match_year = models_klb.match_year_range(team.year)[1]
			club_member, is_changed = self.runner.add_to_club(creator, team.club, participant, datetime.date.today(),
				datetime.date(last_match_year, 12, 31))
			return participant, club_member, is_changed
		else:
			return participant, None, False
	def get_participant(self, year):
		return self.klb_participant_set.filter(year=models_klb.first_match_year(year)).first()
	def get_team(self, year):
		participant = self.get_participant(year)
		return participant.team if participant else None
	def has_dependent_objects(self):
		return self.klb_result_set.exists() or self.klb_participant_set.exists() or self.klb_team_score_change_person_set.exists()
	def get_name(self):
		return f'{self.fname} {self.lname}'
	def get_reverse_url(self, target):
		return reverse(target, kwargs={'person_id': self.id})
	def get_absolute_url(self):
		return self.get_reverse_url('results:klb_person_details')
	def get_editor_url(self):
		return self.get_reverse_url('editor:klb_person_details')
	def get_update_url(self):
		return self.get_reverse_url('editor:klb_person_update')
	def get_delete_url(self):
		return self.get_reverse_url('editor:klb_person_delete')
	def get_history_url(self):
		return self.get_reverse_url('editor:klb_person_changes_history')
	def get_refresh_url(self):
		return self.get_reverse_url('editor:klb_person_refresh_stat')
	# def get_participant_update_url(self):
	# 	return self.get_reverse_url('editor:klb_person_participant_update')
	def get_old_url(self, year):
		if year > 2010:
			return '{}/klb/{}/persresults.php?ID={}'.format(settings.MAIN_PAGE, year, self.id)
		return ''
	def get_full_name_with_birthday(self):
		return '{} {}{}{} ({})'.format(self.lname, self.fname, ' ' if self.midname else '', self.midname,
			results_util.date2str(self.birthday, with_nbsp=False, short_format=True))
	class Meta:
		db_table = "persons"
		indexes = [
			models.Index(fields=["lname", "fname", "midname", "birthday"]),
			models.Index(fields=["country", "city"]),
		]
	def __str__(self):
		return get_name(self)

DISTANCE_FOR_KLB_UNKNOWN = 0
DISTANCE_FOR_KLB_FORMAL = 1
DISTANCE_FOR_KLB_REAL = 2
DISTANCE_FOR_KLB_CHOICES = (
	(DISTANCE_FOR_KLB_UNKNOWN, 'неизвестно'),
	(DISTANCE_FOR_KLB_FORMAL, 'основная дистанция'),
	(DISTANCE_FOR_KLB_REAL, 'фактическая дистанция'),
)
class Klb_result(models.Model):
	id = models.AutoField(primary_key=True)
	event_raw = models.ForeignKey(Event, on_delete=models.PROTECT)
	klb_person = models.ForeignKey(Klb_person, on_delete=models.PROTECT)
	klb_participant = models.ForeignKey('Klb_participant', on_delete=models.PROTECT, default=None, null=True)
	result = models.OneToOneField(Result, default=None, null=True, on_delete=models.SET_NULL)
	race = models.ForeignKey(Race, verbose_name='Дистанция', on_delete=models.PROTECT)

	distance_raw = models.CharField(max_length=20, blank=True)
	# time_raw = models.TimeField(default="00:00:00")
	# It's TimeField in original DB but django doesn't work with time > 24 hours
	time_raw = models.CharField(default="00:00:00", max_length=10, blank=True)
	time_seconds_raw = models.IntegerField(default=0)
	klb_score = models.DecimalField(verbose_name='Основные очки', default=0, max_digits=5, decimal_places=3)
	bonus_score = models.DecimalField(verbose_name='Бонусные очки', default=0, max_digits=5, decimal_places=3)
	klb_score_13 = models.SmallIntegerField(default=0) # Something old and strange
	for_klb = models.SmallIntegerField(default=1) # if equals 0, shouldn't be counted in KLBMatch
	was_real_distance_used = models.SmallIntegerField(verbose_name='По какой дистанции посчитаны баллы',
		default=DISTANCE_FOR_KLB_UNKNOWN, choices=DISTANCE_FOR_KLB_CHOICES)
	is_in_best = models.BooleanField(verbose_name='Попадает ли в число учитывающихся основных', default=False)
	is_in_best_bonus = models.BooleanField(verbose_name='Попадает ли в число учитывающихся бонусных', default=False)
	is_error = models.BooleanField(verbose_name='Засчитан ли по ошибке', default=False, db_index=True)
	only_bonus_score = models.BooleanField(verbose_name='Правда ли, что не нужно считать спортивные очки', default=False)

	last_update = models.DateTimeField(verbose_name='Время создания', auto_now_add=True)
	added_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name='Кто добавил в таблицу', on_delete=models.SET_NULL,
		null=True, blank=True, related_name="klb_results_added_by_user")
	class Meta:
		db_table = "KLBresults"
		constraints = [
			models.UniqueConstraint(fields=["klb_person", "race"], name='klb_person_race'),
		]
		indexes = [
			models.Index(fields=["klb_person", "is_in_best"]),
			models.Index(fields=["klb_person", "is_in_best_bonus"]),
			models.Index(fields=["race", "klb_score"]),
		]
	def clean(self):
		if self.result:
			self.event_raw = self.result.race.event
		elif self.race:
			self.event_raw = self.race.event
	def strResult(self):
		if self.result:
			return str(self.result)
		if self.race:
			distance = self.race.distance
			if distance.distance_type in TYPES_MINUTES:
				return self.distance_raw + ' м'
			else:
				return secs2time(self.time_seconds_raw)
		return 'неизвестно'
	def total_score(self):
		return self.klb_score + self.bonus_score
	def get_team(self):
		return self.klb_person.get_team(self.race.event.start_date.year)
	def __str__(self):
		return '{} {} (id {}): {}, {}'.format(
			self.klb_person.fname, self.klb_person.lname, self.klb_person.id, self.distance_raw, self.time_seconds_raw)

ORDERING_SCORE_SUM = 0
ORDERING_NAME = 1
ORDERING_BONUSES = 2
ORDERING_CLEAN_SCORE = 3
ORDERING_N_STARTS = 4
class Klb_team(models.Model):
	club = models.ForeignKey(Club, verbose_name='Клуб', on_delete=models.PROTECT)
	number = models.SmallIntegerField(verbose_name='Номер команды (не уникален)')
	year = models.SmallIntegerField(verbose_name='Год участия')
	name = models.CharField(verbose_name='Название команды', db_index=True, max_length=100)
	score = models.DecimalField(verbose_name='Очки + бонусы', default=0, max_digits=7, decimal_places=3)
	bonus_score = models.DecimalField(verbose_name='Бонусные очки', default=0, max_digits=7, decimal_places=3)
	n_members = models.SmallIntegerField(verbose_name='Число заявленных за команду', default=0)
	n_members_started = models.SmallIntegerField(verbose_name='Число стартовавших за команду', default=0)
	place = models.SmallIntegerField(verbose_name='Место в Матче', null=True, default=None)
	place_small_teams = models.SmallIntegerField(verbose_name='Место среди маленьких команд',
		null=True, default=None)
	place_medium_teams = models.SmallIntegerField(verbose_name='Место среди средних команд',
		null=True, default=None)
	place_secondary_teams = models.SmallIntegerField(verbose_name='Место среди команд-дублёров', null=True, default=None)
	is_not_secondary_team = models.BooleanField(verbose_name='Не хочет участвовать в первенстве дублёров', default=False, blank=True)
	added_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name='Кто добавил в таблицу', on_delete=models.SET_NULL,
		null=True, blank=True, related_name="klb_teams_added_by_user")
	added_time = models.DateTimeField(verbose_name='Время создания', auto_now_add=True,
		null=True, blank=True)
	last_update = models.DateTimeField(verbose_name='Последнее изменение', auto_now=True,
		null=True, blank=True)
	class Meta:
		db_table = "KLBcommand"
		constraints = [
			models.UniqueConstraint(fields=["club", "number", "year"], name='club_number_year'),
		]
		indexes = [
			models.Index(fields=["year", "place"]),
			models.Index(fields=["year", "place_small_teams"]),
			models.Index(fields=["year", "place_medium_teams"]),
			models.Index(fields=["year", "place_secondary_teams"]),
			models.Index(fields=["year", "score"]),
		]
	def get_reverse_url(self, target):
		return reverse(target, kwargs={'team_id': self.id})
	def get_absolute_url(self):
		return self.get_reverse_url('results:klb_team_details')
	def get_details_full_url(self):
		return self.get_reverse_url('results:klb_team_details_full')
	def get_score_changes_url(self):
		return self.get_reverse_url('results:klb_team_score_changes')
	def get_results_for_moderation_url(self):
		return self.get_reverse_url('results:klb_team_results_for_moderation')
	def get_refresh_stat_url(self):
		return self.get_reverse_url('results:klb_team_refresh_stat')
	def get_payment_url(self):
		return self.get_reverse_url('results:klb_team_payment')
	def get_contact_info_url(self):
		return self.get_reverse_url('editor:klb_team_contact_info')
	def get_did_not_run_url(self):
		return self.get_reverse_url('editor:klb_team_did_not_run')
	def get_add_old_participants_url(self):
		return self.get_reverse_url('editor:klb_team_add_old_participants')
	def get_delete_participants_url(self):
		return self.get_reverse_url('editor:klb_team_delete_participants')
	def get_add_new_participant_url(self):
		return self.get_reverse_url('editor:klb_team_add_new_participant')
	def get_move_participants_url(self):
		return self.get_reverse_url('editor:klb_team_move_participants')
	def get_change_name_url(self):
		return self.get_reverse_url('editor:klb_team_change_name')
	def get_history_url(self):
		return self.get_reverse_url('editor:klb_team_changes_history')
	def get_delete_url(self):
		return self.get_reverse_url('editor:klb_team_delete')
	def get_old_url(self):
		return '{}/klb/{}/team.php?detailcom={}'.format(settings.MAIN_PAGE, self.year, self.number)
	def get_diplom_url(self):
		if not models_klb.has_team_diplomas(self.year):
			return ''
		return f'{settings.MAIN_PAGE}/klb/{self.year}/diplom/dicom.php?IDKLB={self.number}'
	def get_clean_score(self):
		return self.score - self.bonus_score
	def get_next_team(self):
		if self.place is None:
			return None
		return Klb_team.objects.filter(year=self.year, place=self.place - 1).first()
	def get_prev_team(self):
		if self.place is None:
			return None
		return Klb_team.objects.filter(year=self.year, place=self.place + 1).first()
	def get_next_medium_team(self):
		if self.place_medium_teams is None:
			return None
		return Klb_team.objects.filter(year=self.year, place_medium_teams=self.place_medium_teams - 1).first()
	def get_prev_medium_team(self):
		if self.place_medium_teams is None:
			return None
		return Klb_team.objects.filter(year=self.year, place_medium_teams=self.place_medium_teams + 1).first()
	def get_next_small_team(self):
		if self.place_small_teams is None:
			return None
		return Klb_team.objects.filter(year=self.year, place_small_teams=self.place_small_teams - 1).first()
	def get_prev_small_team(self):
		if self.place_small_teams is None:
			return None
		return Klb_team.objects.filter(year=self.year, place_small_teams=self.place_small_teams + 1).first()
	def is_in_active_year(self):
		return is_active_klb_year(self.year)
	def update_context_for_team_page(self, context, user, ordering=ORDERING_CLEAN_SCORE):
		context['teams_number'] = Klb_team.get_teams_number(year=self.year)
		if self.place_medium_teams:
			context['medium_teams_number'] = Klb_team.get_medium_teams_number(year=self.year)
		elif self.place_small_teams:
			context['small_teams_number'] = Klb_team.get_small_teams_number(year=self.year)
		context['team'] = self
		context['participants'] = self.klb_participant_set.select_related('klb_person__runner__user__user_profile', 'payment')
		fields_for_order = []
		if ordering == ORDERING_BONUSES:
			fields_for_order.append('-bonus_sum')
		elif ordering == ORDERING_CLEAN_SCORE:
			context['participants'] = context['participants'].annotate(clean_sum=F('score_sum') - F('bonus_sum'))
			fields_for_order.append('-clean_sum')
		elif ordering == ORDERING_SCORE_SUM:
			fields_for_order.append('-score_sum')
		elif ordering == ORDERING_N_STARTS:
			fields_for_order.append('-n_starts')
		elif ordering == ORDERING_NAME:
			fields_for_order += ['klb_person__lname', 'klb_person__fname']
		for field in ['-n_starts', 'klb_person__lname', 'klb_person__fname']:
			if field not in fields_for_order:
				fields_for_order.append(field)

		context['participants'] = context['participants'].order_by(*fields_for_order)
		context['CUR_KLB_YEAR'] = models_klb.CUR_KLB_YEAR
		context['ordering'] = ordering
		context['n_runners_for_team_clean_score'] = models_klb.get_n_runners_for_team_clean_score(self.year)
		context['n_results_for_bonus_score'] = models_klb.get_n_results_for_bonus_score(self.year)
		if context['is_admin'] or context['is_editor']:
			cur_year_teams = self.club.klb_team_set.filter(year=self.year)
			context['has_old_participants_to_add'] = self.club.klb_team_set.filter(year=self.year - 1).exists() or self.club.club_member_set.exists()
			context['has_participants_to_delete'] = self.klb_participant_set.filter(n_starts=0).exists()
			context['can_be_deleted'] = is_active_klb_year(self.year, context['is_admin']) \
				and (not cur_year_teams.filter(number__gt=self.number).exists()) \
				and (not self.klb_participant_set.exists())
			today = datetime.date.today()
			context['can_add_participants'] = (self.klb_participant_set.count() < models_klb.get_team_limit(self.year)) and (today.year <= self.year)
			context['can_move_participants'] = context['can_add_participants'] and (cur_year_teams.count() > 1) \
				and (today <= models_klb.get_last_day_to_move_between_teams(self.year))
		return context
	def string_contains_team_or_club_name(self, s):
		s = s.lower()
		if (self.name.lower() in s) or (self.club.name.lower() in s):
			return True
		for club_name in self.club.club_name_set.values_list('name', flat=True):
			if club_name.lower() in s:
				return True
		return False
	def __str__(self):
		res = self.name
		if self.club.city:
			res += ' ({})'.format(self.club.city.name_full(with_nbsp=False))
		return res
	@classmethod
	def get_teams_number(cls, year):
		return cls.objects.filter(year=year, n_members__gt=0).exclude(number=INDIVIDUAL_RUNNERS_CLUB_NUMBER).count()
	@classmethod
	def get_large_teams_number(cls, year):
		return cls.objects.filter(year=year, n_members__gt=0, place_medium_teams=None, place_small_teams=None).exclude(
			number=INDIVIDUAL_RUNNERS_CLUB_NUMBER).count()
	@classmethod
	def get_medium_teams_number(cls, year):
		return cls.objects.filter(year=year, n_members__gt=0, place_medium_teams__isnull=False).count()
	@classmethod
	def get_small_teams_number(cls, year):
		return cls.objects.filter(year=year, n_members__gt=0, place_small_teams__isnull=False).count()

class Klb_report(models.Model):
	year = models.SmallIntegerField(verbose_name='Год КЛБМатча')
	file = models.FileField(verbose_name='Файл с данными', max_length=255)
	is_public = models.BooleanField(verbose_name='Доступен ли посетителям или только админам', default=False, blank=True)
	was_reported = models.BooleanField(verbose_name='Написали ли в письме админам, что этот слепок создан', default=False, blank=True)
	created_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name='Кто создал', on_delete=models.SET_NULL, null=True, blank=True)
	time_created = models.DateTimeField(verbose_name='Время создания', auto_now_add=True)
	class Meta:
		db_table = "dj_klb_report"
@receiver(pre_delete, sender=Klb_report)
def pre_klb_report_delete(sender, instance, **kwargs):
	if instance.file:
		instance.file.delete(False)

KLB_REPORT_STAT_TEAMS = 1
KLB_REPORT_STAT_PARTICIPANTS = 2
KLB_REPORT_STAT_RESULTS = 3
KLB_REPORT_STAT_GOOD_DISTANCES = 4
KLB_REPORT_STAT_BAD_DISTANCES = 5
KLB_REPORT_STATS = (
	(KLB_REPORT_STAT_TEAMS, 'Число команд'),
	(KLB_REPORT_STAT_PARTICIPANTS, 'Число участников'),
	(KLB_REPORT_STAT_RESULTS, 'Число учтённых результатов'),
	(KLB_REPORT_STAT_GOOD_DISTANCES, 'Дистанции с хотя бы одним результатом'),
	(KLB_REPORT_STAT_BAD_DISTANCES, 'Дистанции, не учтённые в матче'),
)
class Klb_report_stat(models.Model):
	klb_report = models.ForeignKey(Klb_report, verbose_name='Слепок', on_delete=models.CASCADE)
	stat_type = models.SmallIntegerField(verbose_name='Параметр', choices=KLB_REPORT_STATS)
	value = models.IntegerField(verbose_name='Значение', default=0)
	time_created = models.DateTimeField(verbose_name='Время создания', auto_now_add=True)
	class Meta:
		db_table = "dj_klb_report_stat"
		constraints = [
			models.UniqueConstraint(fields=['klb_report', 'stat_type'], name='klb_report_stat_type'),
		]

class Klb_age_group(models.Model):
	year = models.SmallIntegerField(verbose_name='Год матча')
	birthyear_min = models.SmallIntegerField(verbose_name='Минимальный год рождения', default=None, null=True)
	birthyear_max = models.SmallIntegerField(verbose_name='Максимальный год рождения', default=None, null=True)
	gender = models.SmallIntegerField(verbose_name='Пол', choices=results_util.GENDER_CHOICES)
	name = models.CharField(verbose_name='Название группы', max_length=40)
	n_participants = models.SmallIntegerField(verbose_name='Число участников', default=0)
	n_participants_started = models.SmallIntegerField(verbose_name='Число стартовавших участников', default=0)
	order_value = models.SmallIntegerField(verbose_name='Значение для сортировки', default=0)
	class Meta:
		db_table = "dj_klb_age_group"
		constraints = [
			models.UniqueConstraint(fields=["year", "gender", "birthyear_min"], name='year_gender_birthyear_min'),
			models.UniqueConstraint(fields=["year", "gender", "birthyear_max"], name='year_gender_birthyear_max'),
		]
		indexes = [
			models.Index(fields=["year", "order_value", "gender", "birthyear_min"]),
		]
	def get_absolute_url(self):
		return reverse('results:klb_age_group_details', kwargs={'age_group_id': self.id})
	def get_old_url(self):
		return f'{settings.MAIN_PAGE}/klb/{self.year}/memberso.php'
	def __str__(self):
		return self.name
	@classmethod
	def get_groups_by_year(cls, year):
		return cls.objects.filter(year=year).order_by('order_value', 'gender', '-birthyear_min')

PAID_STATUS_NO = 0
PAID_STATUS_FREE = 1
PAID_STATUS_FULL = 2
PAID_STATUSES = (
	(PAID_STATUS_NO, 'участие не оплачено'),
	(PAID_STATUS_FREE, 'участвует бесплатно'),
	(PAID_STATUS_FULL, 'участие оплачено'),
)

class Klb_participant(models.Model):
	id = models.AutoField(primary_key=True)
	klb_person = models.ForeignKey(Klb_person, verbose_name='ID участника КЛБМатча', on_delete=models.CASCADE)
	year = models.SmallIntegerField(verbose_name='Год матча')
	team_number = models.SmallIntegerField(verbose_name='Номер команды в этом году')
	team = models.ForeignKey(Klb_team, verbose_name='Команда', on_delete=models.PROTECT, default=None, null=True, blank=True)
	city = models.ForeignKey(City, verbose_name='Город', default=None, null=True, on_delete=models.PROTECT)
	date_registered = models.DateField(verbose_name='Дата добавления в команду', default=None, null=True)
	date_removed = models.DateField(verbose_name='Дата исключения из команды', default=None, null=True, blank=True)
	score_sum = models.DecimalField(verbose_name='Основные очки + бонус', default=0, max_digits=5, decimal_places=3)
	bonus_sum = models.DecimalField(verbose_name='Бонусные очки', default=0, max_digits=5, decimal_places=3)
	n_starts = models.SmallIntegerField(default=0)

	is_in_best = models.BooleanField(verbose_name='Попадает ли в число учитывающихся в этом году', default=False)
	place = models.SmallIntegerField(verbose_name='Место в индивидуальном зачёте', null=True, default=None)
	age_group = models.ForeignKey(Klb_age_group, verbose_name='Возрастная группа', on_delete=models.PROTECT,
		default=None, null=True, blank=True)
	place_group = models.SmallIntegerField(verbose_name='Место в возрастной группе', null=True, default=None)
	place_gender = models.SmallIntegerField(verbose_name='Место среди пола', null=True, default=None)

	email = models.CharField(verbose_name='E-mail', max_length=MAX_EMAIL_LENGTH, blank=True)
	phone_number = models.CharField(verbose_name='Мобильный телефон', max_length=MAX_PHONE_NUMBER_LENGTH, blank=True)
	phone_number_clean = models.CharField(verbose_name='Мобильный телефон (только цифры)', max_length=MAX_PHONE_NUMBER_LENGTH, blank=True)
	is_senior = models.BooleanField(verbose_name='Пенсионер ли', default=False)

	# payment = models.ForeignKey(Payment_moneta, verbose_name='Платёж, которым оплачено участие', on_delete=models.SET_NULL,
	# 	null=True, blank=True, default=None)
	is_paid_through_site = models.BooleanField(verbose_name='Сделан ли платёж через сайт', default=True)
	paid_status = models.SmallIntegerField(verbose_name='Оплачено ли участие', default=PAID_STATUS_NO, choices=PAID_STATUSES)
	wants_to_pay_zero = models.BooleanField(verbose_name='Хотят ли за него заплатить ноль', default=False)
	was_deleted_from_team = models.BooleanField(verbose_name='Был ли удалён из команды со всеми результатами', default=False)

	added_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name='Кто добавил в таблицу', on_delete=models.SET_NULL,
		null=True, blank=True, related_name="klb_participants_added_by_user")
	added_time = models.DateTimeField(verbose_name='Время создания', auto_now_add=True, null=True, blank=True)
	last_update = models.DateTimeField(verbose_name='Последнее изменение', auto_now=True, null=True, blank=True)
	class Meta:
		db_table = 'KLBppX'
		constraints = [
			models.UniqueConstraint(fields=['klb_person', 'year'], name='klb_person_year'),
		]
		indexes = [
			models.Index(fields=['klb_person', 'year', 'is_in_best']),
			models.Index(fields=['year', 'age_group', 'place_group']),
			models.Index(fields=['year', 'place']),
			models.Index(fields=['year', 'paid_status']),
			models.Index(fields=['phone_number_clean']),
			models.Index(fields=['team', 'paid_status']),
		]
	def calculate_team_number(self):
		if self.team:
			return self.team.number
		else:
			return INDIVIDUAL_RUNNERS_CLUB_NUMBER
	def clean(self):
		self.team_number = self.calculate_team_number()
		match_year_for_seniority = 2021 if (self.year == 2020) else self.year
		if self.klb_person.gender == GENDER_FEMALE:
			self.is_senior = self.klb_person.birthday.year <= (match_year_for_seniority - results_util.SENIOR_AGE_FEMALE)
		else:
			self.is_senior = self.klb_person.birthday.year <= (match_year_for_seniority - results_util.SENIOR_AGE_MALE)
		self.phone_number_clean = ''.join(c for c in self.phone_number if c.isdigit())
	def clean_sum(self):
		return self.score_sum - self.bonus_sum
	def get_next_overall(self):
		if self.place is None:
			return None
		return Klb_participant.objects.filter(year=self.year, place=self.place - 1).first()
	def get_prev_overall(self):
		if self.place is None:
			return None
		return Klb_participant.objects.filter(year=self.year, place=self.place + 1).first()
	def get_next_gender(self):
		if self.place_gender is None:
			return None
		return Klb_participant.objects.filter(year=self.year, klb_person__gender=self.klb_person.gender,
			place_gender=self.place_gender - 1).first()
	def get_prev_gender(self):
		if self.place_gender is None:
			return None
		return Klb_participant.objects.filter(year=self.year, klb_person__gender=self.klb_person.gender,
			place_gender=self.place_gender + 1).first()
	def get_next_group(self):
		if self.place_group is None:
			return None
		return Klb_participant.objects.filter(age_group=self.age_group, place_group=self.place_group - 1).first()
	def get_prev_group(self):
		if self.place_group is None:
			return None
		return Klb_participant.objects.filter(age_group=self.age_group, place_group=self.place_group + 1).first()
	def get_overall_group(self):
		return Klb_age_group.objects.filter(year=self.year, gender=results_util.GENDER_UNKNOWN).first()
	def get_gender_group(self):
		return Klb_age_group.objects.filter(year=self.year, gender=self.klb_person.gender, birthyear_min=None).first()
	def get_last_day_to_pay(self):
		if self.date_registered:
			day = monthrange(self.date_registered.year, self.date_registered.month)[1]
			return datetime.date(self.date_registered.year, self.date_registered.month, day)
		return None
	def create_stat(self, stat_type, value):
		if value:
			Klb_participant_stat.objects.create(klb_participant=self, stat_type=stat_type, value=value)
	def fill_age_group(self, commit=True):
		age_group = Klb_age_group.objects.filter(
				year=self.year,
				gender=self.klb_person.gender,
				birthyear_min__lte=self.klb_person.birthday.year,
				birthyear_max__gte=self.klb_person.birthday.year,
			).first()
		if age_group:
			if age_group == self.age_group:
				return 0
			else:
				self.age_group = age_group
				if commit:
					self.save()
				return 1
		else:
			return -1
	# Returns true; the club name set; last date when user changed the club
	# iff user is registered and set the name of her club or team not later than the date of event (or event_date is None)
	def did_user_set_correct_club(self, event_date: Optional[datetime.date] = None) -> Tuple[bool, str, Optional[datetime.date]]:
		user_club = ''
		club_name_last_changed = None
		if self.team and self.klb_person.runner.user and hasattr(self.klb_person.runner.user, 'user_profile'):
			profile = self.klb_person.runner.user.user_profile
			club_name_last_changed = profile.club_name_last_changed
			user_club = profile.club_name
			if (club_name_last_changed is None) or (event_date is None) or (club_name_last_changed <= event_date):
				user_club_lower = user_club.lower()
				if (self.team.name.lower() in user_club_lower) or (self.team.club.name.lower() in user_club_lower):
					return True, user_club, club_name_last_changed
				for club_name in self.team.club.club_name_set.all():
					if club_name.name.lower() in user_club_lower:
						return True, user_club, club_name_last_changed
		return False, user_club, club_name_last_changed
	def get_edit_contact_info_url(self):
		return reverse('editor:klb_participant_for_captain_details', kwargs={'participant_id': self.id})
	def get_diplom_url(self):
		if not models_klb.has_diplomas(self.year):
			return ''
		if self.year == 2015:
			return f'{settings.MAIN_PAGE}/klb/{self.year}/diplom.php?ID={self.klb_person_id}'
		return f'{settings.MAIN_PAGE}/klb/{self.year}/diplom/dip.php?ID={self.klb_person_id}'
	def __str__(self):
		return  f'{self.klb_person.fname} {self.klb_person.lname} (id {self.klb_person.id}): {self.year}'

KLB_STAT_LENGTH = 1
KLB_STAT_N_MARATHONS = 2
KLB_STAT_N_ULTRAMARATHONS = 3
KLB_STAT_18_BONUSES = 4
KLB_STAT_N_MARATHONS_AND_ULTRA_MALE = 5
KLB_STAT_N_MARATHONS_AND_ULTRA_FEMALE = 6
KLB_STAT_CHOICES = (
	(KLB_STAT_LENGTH, 'Общая преодолённая дистанция'),
	(KLB_STAT_N_MARATHONS, 'Число марафонов'),
	(KLB_STAT_N_ULTRAMARATHONS, 'Число сверхмарафонов'),
	(KLB_STAT_18_BONUSES, 'Пройденное расстояние на 18 самых длинных стартах'),
	(KLB_STAT_N_MARATHONS_AND_ULTRA_MALE, 'Общее число марафонов и сверхмарафонов (мужчины)'),
	(KLB_STAT_N_MARATHONS_AND_ULTRA_FEMALE, 'Общее число марафонов и сверхмарафонов (женщины)'),
)
KLB_STAT_CHOICES_DICT = dict(KLB_STAT_CHOICES)
class Klb_participant_stat(models.Model):
	klb_participant = models.ForeignKey(Klb_participant, verbose_name='Участник КЛБМатча',
		on_delete=models.CASCADE, null=True, default=None, blank=True)
	stat_type = models.SmallIntegerField(verbose_name='Тип величины', choices=KLB_STAT_CHOICES)
	value = models.IntegerField(verbose_name='Значение', default=0)
	place = models.SmallIntegerField(verbose_name='Место', null=True, default=None)
	class Meta:
		db_table = "dj_klb_participant_stat"
		constraints = [
			models.UniqueConstraint(fields=['klb_participant', 'stat_type'], name='klb_participant_stat_type'),
		]
		indexes = [
			models.Index(fields=["stat_type", "place"]),
		]
	def get_match_category(self):
		return Klb_match_category.get_categories_by_year(self.klb_participant.year).filter(stat_type=self.stat_type).first()
	def get_stat_url(self):
		category = self.get_match_category()
		if category:
			return category.get_absolute_url()
		return ''
	def __str__(self):
		if self.stat_type in [KLB_STAT_LENGTH, KLB_STAT_18_BONUSES]:
			return total_length2string(self.value)
		else:
			return str(self.value)

class Klb_team_score_change(models.Model):
	team = models.ForeignKey(Klb_team, verbose_name='Команда', on_delete=models.CASCADE)
	race = models.ForeignKey(Race, on_delete=models.CASCADE, default=None, blank=True, null=True)
	clean_sum = models.DecimalField(verbose_name='Чистые очки', default=0, max_digits=7, decimal_places=3)
	bonus_sum = models.DecimalField(verbose_name='Бонусные очки', default=0, max_digits=7, decimal_places=3)
	delta = models.DecimalField(verbose_name='Изменение с прошлого', default=0, max_digits=7, decimal_places=3)
	n_persons_touched = models.SmallIntegerField(verbose_name='Затронуто участников', default=0)
	comment = models.CharField(verbose_name='Комментарий', max_length=300, blank=True)
	added_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name='Администратор', on_delete=models.SET_NULL, null=True, blank=True)
	added_time = models.DateTimeField(verbose_name='Время создания', auto_now_add=True, null=True, blank=True)
	class Meta:
		db_table = "dj_klb_team_score_change"
		indexes = [
			models.Index(fields=["team", "added_time"]),
		]
	def total_sum(self):
		return self.clean_sum + self.bonus_sum
	def __str__(self):
		return  'Изменение у команды {} за {} год. Новые очки: {}, бонус: {}'.format(self.team.name, self.team.year, self.clean_sum, self.bonus_sum)
	@classmethod
	def get_last_score(cls, team):
		return cls.objects.filter(team=team).order_by('-added_time').first()

class Klb_team_score_change_person(models.Model):
	score_change = models.ForeignKey(Klb_team_score_change, verbose_name='Изменение очков', on_delete=models.CASCADE)
	old_score = models.DecimalField(verbose_name='Было очков', default=0, max_digits=7, decimal_places=3)
	new_score = models.DecimalField(verbose_name='Стало очков', default=0, max_digits=7, decimal_places=3)
	klb_person = models.ForeignKey(Klb_person, verbose_name='Участник матчей', on_delete=models.PROTECT)
	class Meta:
		db_table = "dj_klb_team_score_change_person"
		constraints = [
			models.UniqueConstraint(fields=['score_change', 'klb_person'], name='score_change_klb_person'),
		]
	def delta(self):
		return self.new_score - self.old_score

class Klb_match_category(models.Model):
	year = models.SmallIntegerField(verbose_name='Год')
	stat_type = models.SmallIntegerField(verbose_name='Тип величины', choices=KLB_STAT_CHOICES)
	n_participants_started = models.SmallIntegerField(verbose_name='Число стартовавших участников', default=0)
	class Meta:
		db_table = "dj_klb_match_category"
		constraints = [
			models.UniqueConstraint(fields=['year', 'stat_type'], name='year_stat_type'),
		]
	def get_absolute_url(self):
		return reverse('results:klb_match_category_details', kwargs={'match_category_id': self.id})
	def __str__(self):
		return self.get_stat_type_display()
	@classmethod
	def get_categories_by_year(cls, year):
		return cls.objects.filter(year=year).order_by('stat_type')
