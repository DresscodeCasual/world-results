import datetime

from django import forms

from . import models, results_util

try:
	COUNTRIES_WITH_EVENTS_IDS = (set(models.Series.objects.values_list('country_id', flat=True).distinct())
		| set(models.Series.objects.values_list('country_id', flat=True).distinct())) - set([None])

	DISTANCE_SURFACE_CHOICES = (
		('на воздухе', [
			(f'{dist_id}_{surface_type}',
			 f'{models.Distance.objects.get(pk=dist_id).name} ({results_util.SURFACE_TYPES_DICT[surface_type]})')
			 for dist_id, surface_type in results_util.DISTANCES_FOR_COUNTRY_OUTDOOR_RECORDS]
		),
		('в помещении', [
			(f'{dist_id}_{results_util.SURFACE_INDOOR}',
			models.Distance.objects.get(pk=dist_id).name + ' (манеж)')
			 for dist_id in results_util.DISTANCES_FOR_COUNTRY_INDOOR_RECORDS]
		)
	)
except:
	COUNTRIES_WITH_EVENTS_IDS = set()
	DISTANCE_SURFACE_CHOICES = []

def validate_email(value):
	if value and not models.is_email_correct(value):
		raise forms.ValidationError('Некорректный адрес электронной почты')
def validate_phone_number(value):
	if value and not models.is_phone_number_correct(value):
		raise forms.ValidationError('Некорректный номер телефона. Номер должен начинаться на 8 или на +, чтобы мы могли позвонить по нему из России')
def validate_birthday(value):
	if value:
		if value >= datetime.date.today():
			raise forms.ValidationError('Вы указали дату рождения в будущем')
		if value < models.DATE_MIN:
			raise forms.ValidationError('Вы указали слишком раннюю дату рождения')

class CustomDateInput(forms.widgets.TextInput):
	input_type = 'date'
class CustomDateTimeInput(forms.widgets.TextInput):
	input_type = 'datetime'
class CustomTimeInput(forms.widgets.TextInput):
	input_type = 'time'

class ModelFormWithCity(forms.ModelForm):
	city_id = forms.CharField(
		label='Город',
		required=False,
		widget=forms.Select(choices=[]))
	def clean(self):
		cleaned_data = super().clean()
		city_id = cleaned_data.get('city_id')
		cleaned_data['city'] = models.City.objects.filter(pk=city_id).first() if city_id else None
		self.instance.city = cleaned_data['city']
		return cleaned_data

class FormWithCity(forms.Form):
	city_id = forms.CharField(
		label="Город",
		required=False,
		widget=forms.Select(choices=[]))
	def __init__(self, *args, **kwargs):
		city_required = kwargs.pop('city_required', False)
		super().__init__(*args, **kwargs)
		if city_required:
			self.fields['city_id'].required = True
	def clean(self):
		cleaned_data = super().clean()
		if 'city_id' in self.fields: # Because maybe we deleted this field in __init__
			city_id = results_util.int_safe(cleaned_data.get('city_id'))
			cleaned_data['city'] = models.City.objects.filter(pk=city_id).first() if city_id else None
		return cleaned_data

class RoundedFieldsForm(forms.Form):
	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		for field in self.fields:
			self.fields[field].widget.attrs['class'] = self.fields[field].widget.attrs.get('class', '') + ' form-control'

class RoundedFieldsModelForm(forms.ModelForm):
	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		for field in self.fields:
			widget = self.fields[field].widget
			if widget.__class__.__name__ not in ('RadioSelect', 'RadioSelectWithoutUl', 'CheckboxInput', 'CheckboxSelectMultiple'):
				widget.attrs.update({'class': 'form-control'})

class RoundedFieldsVerticalForm(forms.Form):
	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		for field in self.fields:
			widget = self.fields[field].widget
			if widget.__class__.__name__ not in ('RadioSelect', 'RadioSelectWithoutUl', 'CheckboxInput', 'CheckboxSelectMultiple'):
				widget.attrs.update({'class': 'form-control'})

class UserModelChoiceField(forms.ModelChoiceField):
	def label_from_instance(self, obj):
		return obj.get_full_name()

CHOICES_REGIONS_BY_COUNTRY = []
CHOICES_OTHER_COUNTRIES = []
try:
	for country in models.Country.objects.filter(value__lt=models.DEFAULT_COUNTRY_SORT_VALUE).order_by('value', 'name'):
		CHOICES_REGIONS_BY_COUNTRY.append((
			country.name,
			[(region['id'], region['name_full'])
				for region in country.region_set.filter(active=True).order_by('name').values('id', 'name_full')]
		))

	CHOICES_OTHER_COUNTRIES = [(region['id'], region['name_full'])
		for region in models.Region.objects.filter(country__value=models.DEFAULT_COUNTRY_SORT_VALUE).order_by('name').values('id', 'name_full')
	]
except:
	pass

class RegionOrCountryField(forms.ChoiceField):
	def __init__(self, *args, **kwargs):
		if 'label' not in kwargs:
			kwargs['label'] = 'Регион (для России, Украины, Беларуси) или страна'
		if 'required' not in kwargs:
			kwargs['required'] = False
		super().__init__(*args, **kwargs)
		self.choices = [['', 'Не выбран']] + CHOICES_REGIONS_BY_COUNTRY + CHOICES_OTHER_COUNTRIES
	def clean(self, value):
		if value:
			value = super().clean(value)
			return models.Region.objects.filter(pk=value).first()
		if self.required:
			raise forms.ValidationError('Пожалуйста, выберите регион или страну')
		return None
