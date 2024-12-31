from django.contrib.auth.models import User
from tinymce.widgets import TinyMCE
from django.db.models import Q
from django import forms
from django_select2 import forms as s2forms

from collections import OrderedDict
from typing import Any, Dict
import datetime
import os
import re

from results import forms_common, models, models_klb, results_util
from editor import xlsx_reports

def validate_date(value):
	if value and value < models.DATE_MIN:
		raise forms.ValidationError('Вы не можете вводить даты до 1900 года. Если это правда нужно, напишите нам')
	if value and value > models.DATE_MAX:
		raise forms.ValidationError('Вы не можете вводить даты после 2099 года. Если это правда нужно, напишите нам')

try:
	ACTIVE_REGIONS = models.Region.objects.filter(is_active=1).order_by('name')
except:
	ACTIVE_REGIONS = models.Region.objects.none()

class ResultValueField(forms.IntegerField):
	def __init__(self, *args, **kwargs):
		kwargs['widget'] = forms.TextInput()
		super(ResultValueField, self).__init__(*args, **kwargs)
	def to_python(self, value):
		if value is None:
			return None
		if value == '':
			return None
		if value == '0':
			return 0
		if self.distance_type in models.TYPES_MINUTES:
			res = results_util.int_safe(value)
			if res:
				return res
			raise forms.ValidationError(f'Недопустимый результат в метрах: {value}')
		else:
			res = models.string2centiseconds(value)
			if res:
				return res
			raise forms.ValidationError(f'Недопустимый результат в секундах: {value}')
	def prepare_value(self, value):
		if value is None:
			return ''
		if value == 0:
			return '0'
		if self.distance_type in models.TYPES_MINUTES:
			return value
		if isinstance(value, int):
			return models.centisecs2time(value)
		return value
		# raise forms.ValidationError(f'Недопустимое значение результата: {value}')

class CityWidget(s2forms.ModelSelect2Widget):
	search_fields = [
		'name__icontains',
		'name_orig__icontains',
		'region__name__icontains',
	]
	def get_queryset(self):
		return super().get_queryset().order_by('-population')
	def label_from_instance(self, obj):
		return obj.NameForEditorAjax()

class RegionWidget(s2forms.ModelSelect2Widget):
	search_fields = [
		'name__icontains',
	]

# When searching through all cities list
class CitySearchForm(forms.Form):
	country = forms.ModelChoiceField(
		label='Страна',
		queryset=models.Country.objects.all().order_by('value', 'name'),
		empty_label='(любая)',
		required=False)
	region = forms.ModelChoiceField(
		label='Регион',
		queryset=ACTIVE_REGIONS,
		empty_label='(любой)',
		required=False)
	detailed = forms.BooleanField(
		label='Подробно',
		required=False)

# When viewing/changing/creating city
class CityForm(forms.ModelForm):
	class Meta:
		model = models.City
		fields = ['region', 'raion', 'city_type', 'name', 'name_orig', 'url_wiki', 'population', 'skip_region', 'geo']
		widgets = {
			'region': RegionWidget(attrs={
				'data-placeholder': 'Any substring of the region name',
				'data-width': '50%',
				'data-allow-clear': 1,
				'data-minimum-input-length': 3,
			}),
			'raion': forms.TextInput(attrs={'size': 50}),
			'city_type': forms.TextInput(attrs={'size': 50}),
			'name': forms.TextInput(attrs={'size': 50}),
			'name_orig': forms.TextInput(attrs={'size': 50}),
			'url_wiki': forms.TextInput(attrs={'size': 100}),
		}

# When going to change old city to new one
class ForCityForm(forms_common.FormWithCity):
	region = forms_common.RegionOrCountryField()
	def __init__(self, *args, **kwargs):
		city_required = kwargs.pop('city_required', True)
		super(ForCityForm, self).__init__(*args, **kwargs)
		self.fields['city_id'].required = city_required
		self.order_fields(['region', 'city_id'])
		for field in self.fields:
			self.fields[field].widget.attrs.update({'class': 'form-control'})

# When viewing/changing/creating distance
class DistanceForm(forms.ModelForm):
	def clean(self):
		cleaned_data = super(DistanceForm, self).clean()
		distance_type = cleaned_data.get('distance_type')
		length = cleaned_data.get('length')
		if length > 9999999:
			raise forms.ValidationError('Слишком большая длина дистанции.')
	class Meta:
		model = models.Distance
		fields = ['distance_type', 'length', 'name', 'popularity_value']

# When going to change old city to new one
class ForDistanceForm(forms.Form):
	new_distance = forms.ModelChoiceField(
		label='Дистанция',
		queryset=models.Distance.objects.order_by('distance_type', 'length'),
		required=False,
	)

# When searching through all series list
class SeriesSearchForm(forms_common.FormWithCity):
	country = forms.ModelChoiceField(
		label='Страна',
		queryset=models.Country.objects.none(), # TODO .filter(pk__in=forms_common.COUNTRIES_WITH_EVENTS_IDS).order_by('value', 'name'),
		empty_label='(любая)',
		required=False)
	region = forms.ModelChoiceField(
		label='Регион',
		queryset=ACTIVE_REGIONS,
		empty_label='(любой)',
		required=False)
	series_name = forms.CharField(
		label='Часть названия серии',
		max_length=100,
		required=False)
	with_events = forms.BooleanField(
		label='и все их пробеги',
		required=False)
	date_from = forms.DateField(
		label='не раньше',
		widget=forms_common.CustomDateInput,
		initial=datetime.date(datetime.datetime.now().year, 1, 1),
		required=False)
	date_to = forms.DateField(
		label='не позже',
		widget=forms_common.CustomDateInput,
		initial=datetime.date(datetime.datetime.now().year, 12, 31),
		required=False)

# When viewing/changing/creating series
class SeriesForm(forms.ModelForm):
	country = forms.ModelChoiceField(
		label='Страна города старта (для остальных стран)',
		queryset=models.Country.objects.filter(value__gt=2).order_by('value', 'name'),
		empty_label='не указана',
		required=False)
	def __init__(self, *args, **kwargs):
		super(SeriesForm, self).__init__(*args, **kwargs)
		if (self.instance.id is None) or not self.instance.is_weekly:
			# We need this field only if we're editing existing Russian parkrun or a similar event
			del self.fields['create_weekly']
	class Meta:
		model = models.Series
		fields = ['name', 'country', 'city', 'start_place', 'city_finish', 'surface_type',
			'director', 'contacts', 'url_site', 'comment', 'comment_private',
			'url_vk', 'url_facebook', 'url_instagram', 'url_wiki', 'url_telegram',
			'is_for_masters', 'is_weekly', 'create_weekly',
		]
		widgets = {
			'name': forms.TextInput(attrs={'size': 100}),
			'city': CityWidget(attrs={
				'data-placeholder': 'Any substring of the city name',
				'data-width': '50%',
				'data-allow-clear': 1,
				'data-minimum-input-length': 3,
			}),
			'city_finish': CityWidget(attrs={
				'data-placeholder': 'Any substring of the city name',
				'data-width': '50%',
				'data-allow-clear': 1,
				'data-minimum-input-length': 3,
			}),
			'director': forms.TextInput(attrs={'size': 100}),
			'contacts': forms.TextInput(attrs={'size': 100}),
			'url_site': forms.TextInput(attrs={'size': 100}),
			'url_events': forms.TextInput(attrs={'size': 100}),
			'url_vk': forms.TextInput(attrs={'size': 100}),
			'url_facebook': forms.TextInput(attrs={'size': 100}),
			'url_instagram': forms.TextInput(attrs={'size': 100}),
			'url_wiki': forms.TextInput(attrs={'size': 100}),
			'url_telegram': forms.TextInput(attrs={'size': 100}),
			'start_place': forms.TextInput(attrs={'size': 50}),
			
			'comment': forms.TextInput(attrs={'size': 100}),
			'comment_private': forms.TextInput(attrs={'size': 100}),
		}
	def clean(self):
		cleaned_data = super(SeriesForm, self).clean()
		name = cleaned_data.get('name')
		city = cleaned_data['city']
		if city and models.Series.objects.filter(name=name, city=city).exclude(pk=self.instance.id).exists():
			raise forms.ValidationError(
				'Серия с таким названием в этом городе уже есть. Пожалуйста, выберите другое название или напишите нам на info@probeg.org')

# When changing event
class EventForm(forms.ModelForm):
	def __init__(self, *args, **kwargs):
		user = kwargs.pop('user')
		super(EventForm, self).__init__(*args, **kwargs)
		self.fields['city'].label += ' (укажите, только если отличается от города серии)'
		if 'city_finish' in self.fields:
			self.fields['city_finish'].label += ' (укажите, только если отличается от старта и от города финиша серии)'
		self.fields['surface_type'].label += ' (укажите, только если отличается от покрытия серии)'
		if not models.is_admin(user):
			self.fields['date_added_to_calendar'].disabled = True
	def clean_url_itra(self):
		url_itra = self.cleaned_data.get('url_itra', '')
		if url_itra and not url_itra.startswith('https://itra.run/'):
			raise forms.ValidationError('Адрес должен начинаться на https://itra.run/')
		return url_itra
	def clean(self):
		cleaned_data = super(EventForm, self).clean()
		series = self.instance.series
		if 'city_finish' in self.fields:
			if cleaned_data.get('city_finish') and not cleaned_data.get('city'):
				raise forms.ValidationError('Нельзя указать город финиша, не указав город старта.')
		if (not cleaned_data['city']) and (not series.city):
			raise forms.ValidationError('Не указан город серии, так что нужно указать город пробега.')
		if (cleaned_data['surface_type'] == results_util.SURFACE_DEFAULT) and (series.surface_type == results_util.SURFACE_DEFAULT):
			raise forms.ValidationError('Нужно указать тип забега либо у серии, либо у забега.')
		start_date = cleaned_data.get('start_date')
		if series.event_set.filter(
					start_date=start_date,
					start_time=cleaned_data.get('start_time'),
					city=cleaned_data.get('city'),
				).exclude(pk=self.instance.id).exists():
			raise forms.ValidationError(f'В этой серии уже есть забег с датой {start_date} и с теми же временем старта и городом.')
	class Meta:
		model = models.Event
		fields = ['name', 'number', 'city', 'city_finish', 'surface_type',
			'start_date', 'finish_date', 'start_place', 'start_time',
			'announcement', 'url_registration',
			'email', 'contacts', 'url_site', 'url_vk', 'url_facebook', 'url_wiki', 'url_itra',
			'cancelled', 'comment', 'comment_private', 'invisible',
			'platform', 'id_on_platform',
			'source', 'source_private',
			]
		widgets = {
			'name'			: forms.TextInput(attrs={'size': 100}),
			'url_registration': forms.TextInput(attrs={'size': 100}),
			'email'		   : forms.TextInput(attrs={'size': 100}),
			'contacts'		: forms.TextInput(attrs={'size': 100}),
			'start_place'	 : forms.TextInput(attrs={'size': 50}),
			'url_site'		: forms.TextInput(attrs={'size': 100}),
			'url_vk'		  : forms.TextInput(attrs={'size': 100}),
			'url_facebook'	: forms.TextInput(attrs={'size': 100}),
			'url_wiki'		: forms.TextInput(attrs={'size': 100}),
			'url_itra'		: forms.TextInput(attrs={'size': 100}),
			'comment'		 : forms.TextInput(attrs={'size': 100}),
			'comment_private' : forms.TextInput(attrs={'size': 100}),
			'id_on_platform'  : forms.TextInput(attrs={'size': 100}),
			'source'		  : forms.TextInput(attrs={'size': 100}),
			'source_private'  : forms.TextInput(attrs={'size': 100}),
			
			'start_date': forms_common.CustomDateInput,
			'finish_date': forms_common.CustomDateInput,
			'start_time': forms_common.CustomTimeInput,
			'announcement': TinyMCE(attrs={'cols': 60, 'rows': 10}),
			'city': CityWidget(attrs={
				'data-placeholder': 'Any substring of the city name',
				'data-width': '50%',
				'data-allow-clear': 1,
				'data-minimum-input-length': 3,
			}),
			'city_finish': CityWidget(attrs={
				'data-placeholder': 'Any substring of the city name',
				'data-width': '50%',
				'data-allow-clear': 1,
				'data-minimum-input-length': 3,
			}),
		}

# When going to change old series to new one
class ForSeriesForm(forms.Form):
	new_series_id = forms.IntegerField(
		label='id новой серии',
		min_value=0,
		required=False)

# When going to change old event to new one
class ForEventForm(forms.Form):
	new_event_id = forms.IntegerField(
		label='id нового забега',
		min_value=0,
		required=False)

# When going to change old runner to new one
class ForRunnerForm(forms.Form):
	new_runner_id = forms.IntegerField(
		label='id нового бегуна',
		min_value=0,
		required=False)

# When viewing/changing/creating race
class RaceForm(forms.ModelForm):
	distance = forms.ModelChoiceField(
		label='Официальная дистанция',
		queryset=models.Distance.objects.none(),
		required=True)
	distance_real = forms.ModelChoiceField(
		label='Фактическая дистанция (если отличается)',
		queryset=models.Distance.objects.none(),
		required=False)
	def __init__(self, *args, **kwargs):
		super(RaceForm, self).__init__(*args, **kwargs)
		distances = models.Distance.get_all_by_popularity()
		self.fields['distance'].queryset = distances
		self.fields['distance_real'].queryset = distances
	class Meta:
		model = models.Race
		fields = ['distance', 'distance_real', 'precise_name',
			'comment', 'comment_private', 'has_no_results', 'is_for_handicapped', 'exclude_from_stat', 'gps_track',
			'start_date', 'start_time', 'finish_date', 'surface_type',
			'elevation_meters', 'descent_meters', 'altitude_start_meters', 'altitude_finish_meters',
			'event', 'created_by', 'itra_score', 'timing',
		]
		widgets = {
			'start_date': forms_common.CustomDateInput(),
			'start_time': forms_common.CustomTimeInput(),
			'finish_date': forms_common.CustomDateInput(),
			'event': forms.HiddenInput(),
			'created_by': forms.HiddenInput(),
		}
		labels = {
			'precise_name': 'Уточнение названия (скобки не нужны)',
		}

class DocumentForm(forms.ModelForm):
	try_to_load = forms.BooleanField(
		label='Попытаться загрузить с указанного URL к нам на сервер',
		required=False)
	def __init__(self, *args, **kwargs):
		super(DocumentForm, self).__init__(*args, **kwargs)
		if self.instance.series_id:
			self.fields['hide_local_link'].widget = forms.HiddenInput()
	def clean(self):
		cleaned_data = super(DocumentForm, self).clean()
		if cleaned_data['document_type'] == models.DOC_TYPE_UNKNOWN:
			raise forms.ValidationError('Пожалуйста, укажите тип документа')
		if (cleaned_data.get('upload') == False) and self.instance.upload:
			if os.path.isfile(self.instance.upload.path):
				self.instance.upload.delete(False)
		if cleaned_data.get('is_on_our_google_drive'):
			if cleaned_data.get('upload'):
				raise forms.ValidationError('Раз документ лежит на нашем Google Drive, не нужно сохранять ещё и резервную копию')
			GOOGLE_DRIVE_URL_PREFIX = 'https://drive.google.com/file/d/'
			url_source = cleaned_data.get('url_source', '')
			if not url_source:
				raise forms.ValidationError('Вы поставили галочку про наш Google Drive, но не указали URL документа. Так нельзя')
			if not url_source.startswith(GOOGLE_DRIVE_URL_PREFIX):
				raise forms.ValidationError(f'{url_source} — точно ссылка на файл на нашем Google Drive? Она должна начинаться на {GOOGLE_DRIVE_URL_PREFIX}')
	class Meta:
		model = models.Document
		fields = [
				'document_type', 'upload', 'url_source', 'try_to_load', 'comment', 'event', 'series', 'author', 'hide_local_link',
				'is_on_our_google_drive', 'created_by', 'author_runner'
			]
		widgets = {
			'url_source': forms.URLInput(attrs={'size': '75%'}), # , validators=[URLValidatorWithUnderscores()]
			'event': forms.HiddenInput(),
			'created_by': forms.HiddenInput(),
			'author_runner': forms.NumberInput(attrs={'size': 7}),
		}

class NewsForm(forms.ModelForm):
	def __init__(self, *args, **kwargs):
		is_admin = kwargs.pop('is_admin')
		super().__init__(*args, **kwargs)
		if not is_admin:
			del self.fields['is_for_blog']
	class Meta:
		model = models.News
		fields = ['title', 'content', 'author', 'image', 'event', 'date_posted', 'is_for_social', 'created_by', 'manual_preview', 'is_for_blog',]
		widgets = {
			'manual_preview': forms.TextInput(attrs={'style': 'width: 100%;'}),
			'content': TinyMCE(attrs={'cols': 60, 'rows': 10}),
			#'date_posted': forms_common.CustomDateTimeInput,
			'event': forms.HiddenInput(),
			'created_by': forms.HiddenInput(),
		}

class SeriesDocumentForm(forms.ModelForm): # TODO. Doesn't work - has_changed is always true!
	try_to_load = forms.BooleanField(
		label='Попытаться загрузить к нам на сервер',
		required=False)
	document_type = forms.ChoiceField(
		label='Страна',
		choices=models.DOCUMENT_TYPES,
		required=True)
	class Meta:
		model = models.Document
		fields = ['document_type', 'upload', 'url_source', 'try_to_load', 'comment', 'event', 'series']

class ResultForm(forms.ModelForm):
	class Meta:
		model = models.Result
		fields = ['lname', 'fname', 'midname', 'result', 'gun_result', 'wind', 'status',
			'bib', 'country_raw', 'city_raw', 'club_name',
			'birthday', 'birthday_known', 'age', 'gender',
			'comment', 'place', 'place_category', 'place_gender',
			'do_not_count_in_stat', 'bib_given_to_unknown', 'is_improbable',
			]
		widgets = {
			'lname': forms.TextInput(attrs={'size': 10}),
			'fname': forms.TextInput(attrs={'size': 10}),
			'midname': forms.TextInput(attrs={'size': 10}),
			'result': forms.NumberInput(attrs={'size': 7}),
			'gun_result': forms.NumberInput(attrs={'size': 7}),
			'wind': forms.NumberInput(attrs={'size': 7}),
			'bib': forms.TextInput(attrs={'size': 5}),
			'country_raw': forms.TextInput(attrs={'size': 10}),
			'city_raw': forms.TextInput(attrs={'size': 10}),
			'club_name': forms.TextInput(attrs={'size': 10}),
			'birthday': forms_common.CustomDateInput(),
			'comment': forms.TextInput(attrs={'size': 6}),
			'age': forms.NumberInput(attrs={'style': 'width: 50px;'}),
			'place': forms.NumberInput(attrs={'style': 'width: 50px;'}),
			'place_category': forms.NumberInput(attrs={'style': 'width: 50px;'}),
			'place_gender': forms.NumberInput(attrs={'style': 'width: 50px;'}),
		}

class UserSearchForm(forms_common.RoundedFieldsForm):
	lname = forms.CharField(
		label='',
		widget=forms.TextInput(attrs={'placeholder': 'Фамилия'}),
		max_length=100,
		required=False)
	fname = forms.CharField(
		label='',
		widget=forms.TextInput(attrs={'placeholder': 'Имя'}),
		max_length=100,
		required=False)
	midname = forms.CharField(
		label='',
		widget=forms.TextInput(attrs={'placeholder': 'Отчество'}),
		max_length=100,
		required=False)
	email = forms.CharField(
		label='',
		widget=forms.TextInput(attrs={'placeholder': 'E-mail'}),
		max_length=100,
		required=False)
	birthday_from = forms.DateField(
		label='Родился не раньше',
		widget=forms_common.CustomDateInput,
		required=False)
	birthday_to = forms.DateField(
		label='не позже',
		widget=forms_common.CustomDateInput,
		required=False)

OBJECT_TYPES = OrderedDict([
	('', 'все'),
	('Series', 'серии'),
	('Event', 'пробеги'),
	('City', 'города'),
	('News', 'новости вне забегов'),
	('Distance', 'дистанции'),
	('Club', 'клубы'),
	('Klb_team', 'команды'),
	('Extra_name', 'имена пользователей'),
	('User_profile', 'профили пользователей'),
])
# When searching through all changes in Table_update
class ActionSearchForm(forms_common.FormWithCity):
	country = forms.ModelChoiceField(
		label='Страна',
		queryset=models.Country.objects.filter(pk__in=forms_common.COUNTRIES_WITH_EVENTS_IDS).order_by('value', 'name'),
		empty_label='(любая)',
		required=False)
	region = forms.ModelChoiceField(
		label='Регион',
		queryset=ACTIVE_REGIONS,
		empty_label='(любой)',
		required=False)
	unverified = forms.BooleanField(
		label='Только неодобренные',
		initial=True,
		required=False)
	user = forms.ModelChoiceField(
		label='Совершённые пользователем с ID',
		queryset=User.objects.all(),
		empty_label='(любым)',
		widget=forms.NumberInput(),
		required=False)
	object_type = forms.ChoiceField(
		label='Тип объекта',
		choices=list(OBJECT_TYPES.items()),
		required=False)
	action_type = forms.ChoiceField(
		label='Действие',
		choices=models.ACTION_TYPES,
		required=False)
	date_from = forms.DateField(
		label='Не раньше',
		widget=forms_common.CustomDateInput(),
		required=False)
	date_to = forms.DateField(
		label='Не позже',
		widget=forms_common.CustomDateInput(),
		required=False)

class SocialPageForm(forms.ModelForm):
	class Meta:
		model = models.Social_page
		fields = ['page_type', 'page_id', 'name', 'district', 'url', 'access_token', 'is_for_all_news', 'token_secret']
		widgets = {
			'page_id': forms.TextInput(attrs={'size': 10}),
			'name': forms.TextInput(attrs={'size': 30}),
			'url': forms.TextInput(attrs={'size': 30}),
			'access_token': forms.TextInput(attrs={'size': 10}),
			'token_secret': forms.TextInput(attrs={'size': 10}),
		}

class RunnerForm(forms_common.ModelFormWithCity):
	region = forms_common.RegionOrCountryField()
	def __init__(self, *args, **kwargs):
		super(RunnerForm, self).__init__(*args, **kwargs)
		if self.instance.user:
			self.fields['club_name'].disabled = True
			self.fields['club_name'].label += ' (можно изменить только у соотв. пользователя)'
		self.fields['gender'].choices = results_util.GENDER_CHOICES_RUS[1:]
		self.fields['gender'].initial = results_util.GENDER_MALE
	def clean(self):
		cleaned_data = super(RunnerForm, self).clean()
		birthday = cleaned_data.get('birthday')
		birthday_known = cleaned_data.get('birthday_known', False)
		if birthday and (not birthday_known) and ( (birthday.month > 1) or (birthday.day > 1)):
			raise forms.ValidationError(
				'Вы не забыли поставить галочку «Известен ли день рождения»? Если неизвестен, укажите день рождения 1 января')
		if birthday_known and (birthday is None):
			cleaned_data['birthday_known'] = False
			self.cleaned_data = cleaned_data
	class Meta:
		model = models.Runner
		fields = ['user', 'lname', 'fname', 'midname', 'gender', 'birthday', 'birthday_known', 'birthday_min', 'birthday_max',
			'deathday', 'region', 'city_id', 'club_name', 'url_wiki', 'comment', 'comment_private', 'private_data_hidden',
		]
		widgets = {
			'user': forms.NumberInput(),
			'birthday': forms_common.CustomDateInput(),
			'birthday_min': forms_common.CustomDateInput(),
			'birthday_max': forms_common.CustomDateInput(),
			'deathday': forms_common.CustomDateInput(),
			'url_wiki': forms.TextInput(attrs={'size': 50}),
			'comment': forms.TextInput(attrs={'size': 50}),
			'comment_private': forms.TextInput(attrs={'size': 50}),
		}

class RunnerLinkForm(forms.ModelForm):
	def clean(self):
		cleaned_data = super(RunnerLinkForm, self).clean()
		link = cleaned_data.get('link', '')
		if self.instance.runner.runner_link_set.filter(link=link).exists():
			raise forms.ValidationError(f'У этого бегуна уже есть ссылка на страницу {link}')
		description = cleaned_data.get('description', '')
		if self.instance.runner.runner_link_set.filter(description=description).exists():
			raise forms.ValidationError(f'У этого бегуна уже есть ссылка с описанием «{description}»')
	class Meta:
		model = models.Runner_link
		fields = ['link', 'description']
		widgets = {
			'link': forms.TextInput(attrs={'size': 50}),
			'description': forms.TextInput(attrs={'size': 50}),
		}

class ClubForm(forms_common.ModelFormWithCity):
	region = forms_common.RegionOrCountryField()
	is_actual = forms.BooleanField(
		label='Отметьте, если вся информация о клубе актуальна',
		required=False)
	def __init__(self, *args, **kwargs):
		is_admin = kwargs.pop('is_admin')
		super(ClubForm, self).__init__(*args, **kwargs)
		if not is_admin:
			del self.fields['is_active']
	def clean(self):
		cleaned_data = super(ClubForm, self).clean()
		if 'is_actual' in cleaned_data:
			self.instance.last_update_time = datetime.datetime.now()
	class Meta:
		model = models.Club
		fields = ['name', 'city_id', 'url_site', 'logo', 'birthday', 'n_members',
			'email', 'url_vk', 'url_facebook',
			'training_timetable', 'training_cost',
			'is_active', 'is_member_list_visible',
			]
		widgets = {
			'birthday': forms_common.CustomDateInput(),
			'name': forms.TextInput(attrs={'style': 'width: 100%;'}),
			'url_site': forms.TextInput(attrs={'style': 'width: 100%;'}),
			'email': forms.TextInput(attrs={'style': 'width: 100%;'}),
			'other_contacts': forms.TextInput(attrs={'style': 'width: 100%;'}),
			'url_vk': forms.TextInput(attrs={'style': 'width: 100%;'}),
			'url_facebook': forms.TextInput(attrs={'style': 'width: 100%;'}),
			'training_timetable': forms.TextInput(attrs={'style': 'width: 100%;'}),
			'training_cost': forms.TextInput(attrs={'style': 'width: 100%;'}),
		}

class KlbPersonForm(forms.ModelForm):
	# region = forms_common.RegionOrCountryField()
	class Meta:
		model = models.Klb_person
		fields = ['nickname', 'email', 'phone_number', 'postal_address', 'skype', 'ICQ', 'disability_group', 'comment', ]

class KlbParticipantForm(forms_common.RoundedFieldsModelForm):
	def __init__(self, *args, **kwargs):
		self.year = kwargs.pop('year')
		super(KlbParticipantForm, self).__init__(*args, **kwargs)
		self.fields['team'].queryset = models.Klb_team.objects.filter(year=self.year,
			n_members__lte=models_klb.get_team_limit(self.year)).exclude(number=models.INDIVIDUAL_RUNNERS_CLUB_NUMBER).order_by('name')
		self.fields['team'].empty_label = 'Индивидуальный участник'
		if self.year <= 2017:
			del self.fields['email']
			del self.fields['phone_number']
		if self.instance.id:
			self.fields['team'].widget.attrs.update({'disabled': 'disabled'})
	def clean(self):
		cleaned_data = super(KlbParticipantForm, self).clean()
		if self.year >= 2018:
			if (not cleaned_data.get('email')) and (not cleaned_data.get('phone_number')):
				raise forms.ValidationError('Нужно заполнить хотя бы что-то одно из электронной почты и телефона участника')
	def clean_email(self):
		email = self.cleaned_data.get('email', '')
		forms_common.validate_email(email)
		return email
	def clean_phone_number(self):
		phone_number = self.cleaned_data.get('phone_number', '')
		forms_common.validate_phone_number(phone_number)
		return phone_number
	def get_city(self):
		city_id = self['city'].value()
		if city_id:
			return models.City.objects.filter(pk=city_id).first()
		return None
	class Meta:
		model = models.Klb_participant
		fields = ['team', 'city', 'date_registered', 'date_removed', 'email', 'phone_number']
		widgets = {
			'date_registered': forms_common.CustomDateInput(),
			'date_removed': forms_common.CustomDateInput(),
		}

class KlbParticipantForTeamCaptainForm(forms_common.RoundedFieldsModelForm):
	def clean(self):
		cleaned_data = super(KlbParticipantForTeamCaptainForm, self).clean()
		if (not cleaned_data.get('email')) and (not cleaned_data.get('phone_number')):
			raise forms.ValidationError('Нужно заполнить хотя бы что-то одно из электронной почты и телефона участника')
	def clean_email(self):
		email = self.cleaned_data.get('email', '')
		forms_common.validate_email(email)
		return email
	def clean_phone_number(self):
		phone_number = self.cleaned_data.get('phone_number', '')
		forms_common.validate_phone_number(phone_number)
		return phone_number
	class Meta:
		model = models.Klb_participant
		fields = ['email', 'phone_number', ]

class SplitForm(forms_common.ModelFormWithCity):
	result_str = forms.CharField(
		label='Время (чч:мм:сс или чч:мм:сс,хх)',
		max_length=11,
		required=True)
	def __init__(self, *args, **kwargs):
		self.distance = kwargs.pop('distance')
		super(SplitForm, self).__init__(*args, **kwargs)
		self.fields['distance'].queryset = models.Distance.get_all_by_popularity().filter(distance_type=self.distance.distance_type)
		if self.instance.value:
			if self.distance.distance_type in models.TYPES_MINUTES:
				self.fields['result_str'].initial = self.instance.value
			else:
				self.fields['result_str'].initial = models.total_time2string(self.instance.value)
	def clean(self):
		cleaned_data = super(SplitForm, self).clean()
		if 'result_str' in self.changed_data:
			if self.distance.distance_type in models.TYPES_MINUTES:
				cleaned_data['value'] = results_util.int_safe(cleaned_data['result_str'])
				if cleaned_data['value'] == 0:
					raise forms.ValidationError('Укажите просто целое число пройденных метров')
			else:
				cleaned_data['value'] = models.string2centiseconds(cleaned_data['result_str'])
				if cleaned_data['value'] == 0:
					raise forms.ValidationError('Укажите результат в формате чч:мм:сс,хх или чч:мм:сс')
	class Meta:
		model = models.Split
		fields = ['result', 'distance', 'value', 'result_str',]
		widgets = {
			'result': forms.HiddenInput(),
			'value': forms.HiddenInput(),
		}

class SplitFormSet(forms.BaseModelFormSet):
	def clean(self):
		'''Checks that no two splits have the same distance.'''
		super(SplitFormSet, self).clean()
		if any(self.errors):
			# Don't bother validating the formset unless each form is valid on its own
			return
		distances = []
		for form in self.forms:
			distance = form.cleaned_data.get('distance')
			if distance and (distance in distances):
				raise forms.ValidationError('Не может быть двух промежуточных результатов с равными дистанциями.')
			distances.append(distance)

class MySelectWidget(forms.Select):
	''' Subclass of Django's select widget that allows disabling options. '''
	def __init__(self, *args, **kwargs):
		self.disabled_choices = kwargs.pop('disabled_choices', set())
		super(MySelectWidget, self).__init__(*args, **kwargs)

	def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
		option_dict = super(MySelectWidget, self).create_option(name, value, label, selected, index, subindex=subindex, attrs=attrs)
		if value in self.disabled_choices:
			option_dict['attrs']['disabled'] = 'disabled'
		return option_dict

class KlbResultForm(forms.Form):
	runner_id = forms.ChoiceField(
		label='Участник матча',
		widget=MySelectWidget,
		required=False)
	time_str = forms.CharField(
		label='Результат (если время – чч:мм:сс или чч:мм:сс,хх, если расстояние – число в метрах)',
		max_length=20,
		required=True)
	# is_for_klb = forms.BooleanField(
	# 	label=u'Провести в КЛБМатч?',
	# 	required=False)
	def __init__(self, *args, **kwargs):
		self.race = kwargs.pop('race')
		is_admin = kwargs.pop('is_admin')
		race_is_for_klb = kwargs.pop('race_is_for_klb')
		choices = kwargs.pop('runner_choices')
		disabled_choices = kwargs.pop('disabled_choices')
		super(KlbResultForm, self).__init__(*args, **kwargs)

		self.fields['runner_id'].choices = choices
		self.fields['runner_id'].widget.disabled_choices = disabled_choices

		if race_is_for_klb:
			self.fields['is_for_klb'] = forms.BooleanField(
				label='Провести в КЛБМатч?',
				required=False
			)
			self.fields['is_for_klb'].widget.attrs.update({'class': 'chkbox'})
			if is_admin:
				self.fields['only_bonus_score'] = forms.BooleanField(
					label='Считать только бонусы?',
					required=False
				)
				self.fields['only_bonus_score'].widget.attrs.update({'class': 'gender'})
	def clean(self):
		cleaned_data = super(KlbResultForm, self).clean()
		if cleaned_data.get('runner_id'):
			runner = models.Runner.objects.filter(pk=cleaned_data['runner_id']).first()
			if runner:
				result = self.race.parse_result(cleaned_data.get('time_str', ''))
				if result == 0:
					raise forms.ValidationError('Пожалуйста, введите результат в указанном формате.')
				cleaned_data['runner'] = runner
				cleaned_data['result'] = result
				self.cleaned_data = cleaned_data

# When adding new people to KLB team
class RunnerForKlbForm(forms_common.ModelFormWithCity):
	region = forms_common.RegionOrCountryField(required=True)
	new_city_name = forms.CharField(
		label='Или введите новый населённый пункт, если нужного нет в регионе',
		max_length=100,
		required=False)
	email = forms.CharField(
		label='Адрес электронной почты',
		max_length=models.MAX_EMAIL_LENGTH,
		validators=[forms_common.validate_email],
		required=False)
	phone_number = forms.CharField(
		label='Мобильный телефон',
		max_length=models.MAX_PHONE_NUMBER_LENGTH,
		validators=[forms_common.validate_phone_number],
		required=False)
	and_to_club_members = forms.BooleanField(
		widget=forms.HiddenInput(),
		required=False)
	def __init__(self, *args, **kwargs):
		self.user = kwargs.pop('user', None)
		self.year = kwargs.pop('year', models_klb.CUR_KLB_YEAR)
		super(RunnerForKlbForm, self).__init__(*args, **kwargs)
		if self.year <= 2017:
			del self.fields['email']
			del self.fields['phone_number']	
		for field in self.fields:
			self.fields[field].widget.attrs.update({'class': 'form-control', 'width': '50%'})
		for field_name in ['lname', 'fname', 'gender', 'birthday']:
			self.fields[field_name].required = True
		self.fields['gender'].choices = results_util.GENDER_CHOICES_RUS[1:]
		self.fields['gender'].initial = results_util.GENDER_MALE
	def clean(self):
		cleaned_data = super(RunnerForKlbForm, self).clean()
		city = cleaned_data.get('city')
		new_city_name = cleaned_data.get('new_city_name', '').strip()
		if new_city_name and city:
			raise forms.ValidationError('Либо выберите город из выпадающего списка, либо введите название нового города, но не одновременно')
		if (not new_city_name) and (not city):
			raise forms.ValidationError('Либо выберите город из выпадающего списка, либо введите название нового города')
		if self.year >= 2018:
			if (not cleaned_data.get('email')) and (not cleaned_data.get('phone_number')):
				raise forms.ValidationError('Нужно заполнить хотя бы что-то одно из электронной почты и телефона участника')
		if new_city_name:
			region = cleaned_data['region']
			new_city = models.City.objects.filter(region=region, name=new_city_name).first()
			if not new_city:
				new_city = models.City.objects.create(region=region, name=new_city_name, created_by=self.user)
				models.log_obj_create(self.user, new_city, action=models.ACTION_CREATE, field_list=['region', 'name', 'created_by'])
			self.cleaned_data['city'] = new_city
			self.instance.city = new_city
	class Meta:
		model = models.Runner
		fields = ['lname', 'fname', 'midname', 'gender', 'birthday', 'email', 'phone_number', 'region', 'city_id', 'new_city_name', ]
		widgets = {
			'birthday': forms_common.CustomDateInput(),
		}
		labels = {
			'birthday': 'Дата рождения',
			'midname': 'Отчество (необязательно)',
		}

# For creating new runners from results
class RunnerNameForm(forms.ModelForm):
	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self.fields['gender'].choices = results_util.GENDER_CHOICES_RUS[1:]
	class Meta:
		model = models.Runner_name
		fields = ['name', 'gender']

class ModelHorizontalForm(forms.ModelForm):
	def __init__(self, *args, **kwargs):
		super(ModelHorizontalForm, self).__init__(*args, **kwargs)
		for field_name in self.fields:
			field = self.fields[field_name]
			if field.widget.__class__.__name__ == 'CheckboxInput':
				field.label_suffix = ''
			else:
				field.widget.attrs.update({'class': 'form-control'})

class RunnerPlatformForm(ModelHorizontalForm):
	class Meta:
		model = models.Runner_platform
		fields = ['platform', 'value']

class SeriesPlatformForm(ModelHorizontalForm):
	class Meta:
		model = models.Series_platform
		fields = ['platform', 'value']

class ClubMemberForm(forms_common.RoundedFieldsModelForm, forms_common.ModelFormWithCity):
	region = forms_common.RegionOrCountryField(required=False)
	birthday = forms.DateField(
		label='Дата рождения',
		widget=forms_common.CustomDateInput,
		required=True)
	def clean_email(self):
		email = self.cleaned_data.get('email', '')
		forms_common.validate_email(email)
		return email
	def clean_phone_number(self):
		phone_number = self.cleaned_data.get('phone_number', '')
		forms_common.validate_phone_number(phone_number)
		return phone_number
	def clean_date_registered(self):
		date_registered = self.cleaned_data.get('date_registered')
		validate_date(date_registered)
		return date_registered
	def clean_date_removed(self):
		date_removed = self.cleaned_data.get('date_removed')
		validate_date(date_removed)
		return date_removed
	def __init__(self, *args, **kwargs: Dict[str, Any]):
		if 'initial' not in kwargs:
			kwargs['initial'] = {}
		runner = kwargs['instance'].runner # pytype: disable=attribute-error
		if runner.birthday_known:
			kwargs['initial']['birthday'] = runner.birthday
		super().__init__(*args, **kwargs)
		if runner.birthday_known:
			self.fields['birthday'].disabled = True
		if runner.city:
			del self.fields['region']
			del self.fields['city_id']
	def clean(self):
		cleaned_data = super(ClubMemberForm, self).clean()
		date_registered = self.cleaned_data.get('date_registered')
		date_removed = self.cleaned_data.get('date_removed')
		if date_registered and date_removed and date_registered > date_removed:
			raise forms.ValidationError('Дата вступления в клуб не может быть больше даты выхода из клуба')
	class Meta:
		model = models.Club_member
		fields = ['email', 'phone_number', 'date_registered', 'date_removed', 'region', 'city_id', 'birthday']
		widgets = {
			'date_registered': forms_common.CustomDateInput(),
			'date_removed': forms_common.CustomDateInput(),
		}
		labels = {
			'birthday': 'Дата рождения. Её будем видеть только мы; это позволит точнее находить результаты бегуна'
		}

# When adding new people to club
class RunnerForClubForm(forms_common.ModelFormWithCity):
	region = forms_common.RegionOrCountryField(required=False)
	new_city_name = forms.CharField(
		label='Или введите новый населённый пункт, если нужного нет в регионе',
		max_length=100,
		required=False)
	email = forms.CharField(
		label='Адрес электронной почты',
		max_length=models.MAX_EMAIL_LENGTH,
		validators=[forms_common.validate_email],
		required=False)
	phone_number = forms.CharField(
		label='Мобильный телефон',
		max_length=models.MAX_PHONE_NUMBER_LENGTH,
		validators=[forms_common.validate_phone_number],
		required=False)
	date_registered = forms.DateField(
		label='Дата появления в клубе',
		widget=forms_common.CustomDateInput(),
		required=True)
	def __init__(self, *args, **kwargs):
		self.user = kwargs.pop('user', None)
		super(RunnerForClubForm, self).__init__(*args, **kwargs)
		for field in self.fields:
			self.fields[field].widget.attrs.update({'class': 'form-control', 'width': '50%'})
		for field_name in ['lname', 'fname', 'gender', 'birthday']:
			self.fields[field_name].required = True
		self.fields['gender'].choices = results_util.GENDER_CHOICES_RUS[1:]
		self.fields['gender'].initial = results_util.GENDER_MALE
	def clean_date_registered(self):
		date_registered = self.cleaned_data.get('date_registered')
		validate_date(date_registered)
		return date_registered
	def clean(self):
		cleaned_data = super(RunnerForClubForm, self).clean()
		city = cleaned_data.get('city')
		new_city_name = cleaned_data.get('new_city_name', '').strip()
		if new_city_name and city:
			raise forms.ValidationError('Либо выберите город из выпадающего списка, либо введите название нового города, но не одновременно')
		if new_city_name and not cleaned_data.get('region'):
			raise forms.ValidationError(
				'Укажите, в каком регионе (для России, Украины и Беларуси) или в какой стране находится этот населённый пункт')
		if new_city_name:
			region = cleaned_data['region']
			new_city = models.City.objects.filter(region=region, name=new_city_name).first()
			if not new_city:
				new_city = models.City.objects.create(region=region, name=new_city_name, created_by=self.user)
				models.log_obj_create(self.user, new_city, action=models.ACTION_CREATE, field_list=['region', 'name', 'created_by'])
			self.cleaned_data['city'] = new_city
			self.instance.city = new_city
	class Meta:
		model = models.Runner
		fields = [
			'lname', 'fname', 'midname', 'gender', 'birthday', 'email', 'phone_number', 'region', 'city_id', 'new_city_name', 'date_registered',
			]
		widgets = {
			'birthday': forms_common.CustomDateInput(),
		}
		labels = {
			'birthday': 'Дата рождения',
		}

# When viewing/changing/creating race organizer
class OrganizerForm(forms.ModelForm):
	def __init__(self, *args, **kwargs):
		super(OrganizerForm, self).__init__(*args, **kwargs)
		for field in self.fields:
			self.fields[field].widget.attrs.update({'class': 'form-control', 'width': '50%'})
	def clean(self):
		cleaned_data = super(OrganizerForm, self).clean()
		name = cleaned_data.get('name')
		if models.Organizer.objects.filter(name=name).exclude(pk=self.instance.id).exists():
			raise forms.ValidationError('Организатор с таким именем уже есть')
	class Meta:
		model = models.Organizer
		fields = ['name', 'url_site', 'url_vk', 'url_facebook', 'url_instagram', 'logo', 'user']
		widgets = {
			'user': forms.NumberInput(),
		}

# When going to change old runner to new one
class ForOrganizerForm(forms.Form):
	new_organizer_id = forms.IntegerField(
		label='id нового организатора',
		min_value=0,
		required=False)
	def clean(self):
		cleaned_data = super().clean()
		new_organizer_id = cleaned_data.get('new_organizer_id')
		cleaned_data['new_organizer'] = models.Organizer.objects.filter(pk=new_organizer_id).first()
		if not cleaned_data['new_organizer']:
			raise forms.ValidationError(f'Организатор с id {new_organizer_id} не найден')
		return cleaned_data

class UsefulLabelForm(forms_common.RoundedFieldsModelForm):
	insert_before = forms.ChoiceField(
		label='Вставить перед',
		required=True)
	def __init__(self, *args, **kwargs):
		super(UsefulLabelForm, self).__init__(*args, **kwargs)
		other_labels = models.Useful_label.objects.all()
		if self.instance.id:
			other_labels = other_labels.exclude(pk=self.instance.id)
		self.fields['insert_before'].choices = [(0, 'в конец')] + [(label.id, label.name) for label in other_labels]
		self.fields['insert_before'].default = 0
	class Meta:
		model = models.Useful_label
		fields = ['name', 'insert_before']

class UsefulLinkForm(forms_common.RoundedFieldsModelForm):
	class Meta:
		model = models.Useful_link
		fields = ['name', 'url', 'labels', ]

class CountryConversionForm(forms_common.RoundedFieldsModelForm):
	def clean(self):
		cleaned_data = super().clean()
		same_country = models.Country.objects.filter(name=cleaned_data['country_raw']).first()
		if same_country:
			raise forms.ValidationError(f'Альтернативное название «{cleaned_data['country_raw']}» совпадает с названием страны {same_country.name}')
		existing = models.Country_conversion.objects.filter(country_raw=cleaned_data['country_raw']).first()
		if existing:
			raise forms.ValidationError(f'Альтернативное название «{cleaned_data['country_raw']}» уже указано у страны {existing.country.name}')
		return cleaned_data
	class Meta:
		model = models.Country_conversion
		fields = ['country', 'country_raw']

class RecordResultForm(forms.ModelForm):
	distance_surface = forms.ChoiceField(
		label='Дистанция',
		choices=forms_common.DISTANCE_SURFACE_CHOICES
	)
	country = forms.ModelChoiceField(
		label='Страна',
		queryset=models.Country.objects.order_by('value', 'name'),
		required=True,
	)
	value = ResultValueField(
		label='Результат',
		min_value=0,
		required=False,
	)
	def __init__(self, *args, **kwargs):
		distance_type = kwargs.pop('distance_type', None)
		if 'instance' in kwargs:
			instance = kwargs['instance']
			if instance.distance_id and instance.surface_type:
				if 'initial' not in kwargs:
					kwargs['initial'] = {}
				kwargs['initial']['distance_surface'] = f'{instance.distance_id}_{instance.surface_type}'
				distance_type = instance.distance.distance_type
		super(RecordResultForm, self).__init__(*args, **kwargs)
		self.fields['value'].label = 'Результат в метрах' if (distance_type in models.TYPES_MINUTES) else 'Результат в формате 1:23:45,67'
		self.fields['value'].distance_type = distance_type
		self.fields['distance'].required = False
		self.fields['surface_type'].required = False
		self.fields['gender'].choices = results_util.GENDER_CHOICES_RUS[1:]
	def clean(self):
		cleaned_data = super(RecordResultForm, self).clean()
		if not ((cleaned_data['country'] not in results_util.THREE_COUNTRY_IDS) or cleaned_data.get('is_world_record') or cleaned_data.get('is_europe_record')):
			raise forms.ValidationError('Все рекорды, кроме мировых и европейских, должны относиться к России, Беларуси или Украине')
		distance_id, surface_type = cleaned_data['distance_surface'].split('_')
		cleaned_data['distance'] = models.Distance.objects.get(pk=distance_id)
		cleaned_data['surface_type'] = results_util.int_safe(surface_type)
		return cleaned_data
	class Meta:
		model = models.Record_result
		fields = [
			'country', 'gender', 'age_group', 'distance', 'surface_type', 'distance_surface',
			'is_official_record', 'fname', 'lname', 'city', 'runner', 'result', 'value', 'race',
			'date', 'is_date_known', 'comment', 'timing',
			'is_from_shatilo', 'is_from_hinchuk', 'is_from_vfla',
			'is_world_record', 'is_europe_record', 'ignore_for_country_records',
		]
		widgets = {
			'runner': forms.NumberInput(attrs={'size': 7}),
			'result': forms.NumberInput(attrs={'size': 7}),
			'city': forms.NumberInput(attrs={'size': 7}),
			'cur_place': forms.NumberInput(attrs={'size': 7}),
			'race': forms.NumberInput(attrs={'size': 7}),
			'date': forms_common.CustomDateInput(),
			'distance': forms.HiddenInput(),
			'surface_type': forms.HiddenInput(),
		}
		labels = {
			'runner': 'Бегун',
			'result': 'ID результата',
			'race': 'ID забега (/race/...)',
			'timing': 'Хронометраж (смотрим на это поле, только если забег неизвестен)',
		}

MONTHS = (
	(1, 'январь'),
	(2, 'февраль'),
	(3, 'март'),
	(4, 'апрель'),
	(5, 'май'),
	(6, 'июнь'),
	(7, 'июль'),
	(8, 'август'),
	(9, 'сентябрь'),
	(10, 'октябрь'),
	(11, 'ноябрь'),
	(12, 'декабрь'),
)
MAX_YEAR = max(models_klb.CUR_KLB_YEAR, models_klb.NEXT_KLB_YEAR)
class MonthYearForm(forms_common.RoundedFieldsForm): # For the list of loaded protocols by month
	month = forms.ChoiceField(
		label='',
		choices=MONTHS,
		required=True)
	year = forms.ChoiceField(
		label='',
		choices=[(year, year) for year in range(MAX_YEAR - 5, MAX_YEAR + 1)],
		required=True)

class ProtocolQueueAddEventForm(forms_common.RoundedFieldsForm):
	url = forms.CharField(
		label='URL',
		required=True,
	)
	event_id = forms.IntegerField(
		label='ID забега (необязательно)',
		widget=forms.NumberInput(),
		required=False,
	)
	def clean_url(self):
		url = self.cleaned_data.get('url', '').strip()
		prefix = 'https://www.athlinks.com/event/'
		if not url.startswith(prefix):
				raise forms.ValidationError(f'URL должен начинаться на {prefix}')
		return url.strip('/')

class ProtocolQueueAddSeriesForm(forms_common.RoundedFieldsForm):
	url = forms.CharField(
		label='URL',
		required=True,
	)
	series_id = forms.IntegerField(
		label='ID серии',
		widget=forms.NumberInput(),
		required=True,
	)
	def clean_url(self):
		url = self.cleaned_data.get('url', '').strip()
		prefix = 'https://www.athlinks.com/event/'
		if not url.startswith(prefix):
				raise forms.ValidationError(f'URL должен начинаться на {prefix}')
		return url.strip('/')
