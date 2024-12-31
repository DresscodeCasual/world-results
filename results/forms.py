import os

from django.db.models import F, Q
from django.contrib.auth.models import Group
from django.contrib.auth import get_user_model
from django.conf import settings
from django.urls import reverse
from django import forms

from . import forms_common, models, models_klb, results_util

class CustomClearableFileInput(forms.widgets.ClearableFileInput):
	template_with_initial = (
		'%(initial_text)s: <a href="%(initial_url)s">%(initial)s</a> '
		'%(clear_template)s<br />%(input_text)s: %(input)s'
	)
	template_with_clear = '%(clear)s <label for="%(clear_checkbox_id)s">%(clear_checkbox_label)s</label>'

class UserProfileForm(forms_common.ModelFormWithCity):
	lname = forms.CharField(
		label='Фамилия *',
		max_length=100,
		widget=forms.TextInput(attrs={'size': 30}),
		required=True)
	fname = forms.CharField(
		label='Имя *',
		max_length=100,
		widget=forms.TextInput(attrs={'size': 30}),
		required=True)
	email = forms.EmailField(
		label='Адрес электронной почты *',
		max_length=200,
		widget=forms.EmailInput(attrs={'size': 30}),
		required=True)
	is_new_city = forms.BooleanField(
		label='Моего города нет в списке (в таком случае заполните форму ниже)',
		required=False)
	region = forms_common.RegionOrCountryField()
	new_city = forms.CharField(
		label='Название города',
		max_length=100,
		required=False)
	user = None
	def __init__(self, *args, **kwargs):
		city = kwargs.pop('city')
		self.user = kwargs.pop('user')

		initial = kwargs.get('initial', {})
		initial['lname'] = self.user.last_name
		initial['fname'] = self.user.first_name
		initial['email'] = self.user.email
		if city:
			initial['region'] = city.region.id
		kwargs['initial'] = initial
		super().__init__(*args, **kwargs)
		self.fields['gender'].choices = results_util.GENDER_CHOICES_RUS
		if self.instance.agrees_with_policy:
			del self.fields['agrees_with_policy']
		else:
			self.fields['agrees_with_policy'].required = True
		if self.instance.agrees_with_data_dissemination:
			del self.fields['agrees_with_data_dissemination']
		else:
			self.fields['agrees_with_data_dissemination'].required = True
	def clean_email(self):
		email = self.cleaned_data.get('email', '')
		if email == self.user.email:
			return email
		forms_common.validate_email(email)
		users_with_same_email = get_user_model().objects.filter(Q(username=email) | Q(email=email)).exclude(pk=self.user.id)
		if users_with_same_email.exists():
			body = f'Пользователь {results_util.detailed_user_desc(self.user)} попытался изменить свой электронный адрес на {email}.' \
				+ '\n\nЭтот адрес уже указан у следующих пользователей:'
			for i, user in enumerate(users_with_same_email):
				body += f'\n{i+1}. {results_util.detailed_user_desc(user)}'
			body += '\n\nМы не дали пользователю изменить адрес и написали, что напишем ему сами, если будет нужно.'
			models.send_panic_email(
				subject='Attempt to change email to the one that another user has',
				body=body,
				to_all=True,
			)
			raise forms.ValidationError(
				f'Электронный адрес {email} уже указан у другого пользователя, так что Вы не можете его указать. <br/> Администраторы сайта уже знают об этой проблеме; '
				+ 'они напишут Вам, если нужно. <br/> Вы можете и сами написать нам на info@probeg.org, если всё-таки хотите поменять адрес.')
		return email
	def clean_birthday(self):
		birthday = self.cleaned_data.get('birthday')
		if birthday:
			if birthday >= results_util.TODAY:
				raise forms.ValidationError('Вы указали дату рождения в будущем')
			if birthday < models.DATE_MIN:
				raise forms.ValidationError('Вы указали дату рождения слишком далеко в прошлом')
		return birthday
	def clean_avatar(self):
		avatar = self.cleaned_data['avatar']
		if avatar:
			if avatar.size > settings.MAX_UPLOAD_SIZE:
				raise forms.ValidationError(
					f'Вы можете загрузить аватар размером до {settings.MAX_UPLOAD_SIZE_MB} МБ. Ваш – размером {avatar.size} байт.')
		return avatar
	def clean_gender(self):
		gender = self.cleaned_data.get('gender')
		if gender not in (results_util.GENDER_MALE, results_util.GENDER_FEMALE):
			raise forms.ValidationError('Пожалуйста, укажите ваш пол. Это важно для нас для более точного анализа результатов')
		return gender
	def clean_strava_account(self):
		strava_account = self.cleaned_data.get('strava_account')
		if strava_account:
			if len(strava_account) > 50:
				raise forms.ValidationError('Имя пользователя Стравы не может быть длиннее 50 символов')
			for symbol in ('/', '.', ' '):
				if symbol in strava_account:
					raise forms.ValidationError(f'Имя или номер пользователя Стравы не может содержать символ "{symbol}"')
		return strava_account
	def clean(self):
		cleaned_data = super().clean()
		if 'avatar-clear' in cleaned_data:
			if self.instance.avatar and os.path.isfile(self.instance.avatar.path):
				self.instance.avatar.delete(False)
			if self.instance.avatar_thumb and os.path.isfile(self.instance.avatar_thumb.path):
				self.instance.avatar_thumb.delete(False)
		if cleaned_data.get("is_new_city"):
			region = cleaned_data.get("region")
			new_city = cleaned_data.get("new_city")
			if not region:
				raise forms.ValidationError('Город не сохранён. Укажите страну или регион.')
			if cleaned_data.get("new_city").strip() == "":
				raise forms.ValidationError('Город не сохранён. Название города не может быть пустым.')
			city = models.City.objects.filter(region=region, name=new_city).first()
			if not city:
				city = models.City.objects.create(region=region, name=new_city, created_by=self.user)
				models.log_obj_create(self.user, city, action=models.ACTION_CREATE, field_list=['region', 'name', 'created_by'])
			self.instance.city = city
	class Meta:
		model = models.User_profile
		fields = ['email', 'lname', 'fname', 'midname', 'gender', 'birthday', 'club_name',
			'is_new_city', 'region', 'city_id', 'new_city', 'is_public', 'ok_to_send_news', 'ok_to_send_results', 'avatar',
			'agrees_with_policy', 'agrees_with_data_dissemination',
			'strava_account', 'hide_parkruns_in_calendar',
			]
		labels = {
			'city_id': 'Город',
			'gender': 'Пол *'
		}
		widgets = {
			'avatar': CustomClearableFileInput(),
			'birthday': forms_common.CustomDateInput(),
			'midname': forms.TextInput(attrs={'size': 30}),
			'strava_account': forms.TextInput(attrs={'size': 30}),
			'club_name': forms.TextInput(attrs={'size': 30}),
		}

class UserNameForm(forms.ModelForm):
	def clean_lname(self):
		res = self.cleaned_data.get('lname', '').strip().title()
		if not res:
			raise forms.ValidationError('Фамилия не может быть пустой.')
		return res
	def clean_fname(self):
		res = self.cleaned_data.get('fname', '').strip().title()
		if not res:
			raise forms.ValidationError('Имя не может быть пустым.')
		return res
	def clean_midname(self):
		return self.cleaned_data.get('midname', '').strip().title()
	def clean_comment(self):
		return self.cleaned_data.get('comment', '').strip()
	def clean(self):
		cleaned_data = super().clean()
		lname = cleaned_data.get('lname', '')
		fname = cleaned_data.get('fname', '')
		midname = cleaned_data.get('midname', '')
		if self.instance.runner.extra_name_set.filter(lname=lname, fname=fname, midname=midname).exists():
			raise forms.ValidationError('Вы уже добавляли точно такое же имя.')
	class Meta:
		model = models.Extra_name
		fields = ['lname', 'fname', 'midname', 'comment']


try:
	COUNTRY_TUPLES = models.Country.objects.filter(pk__in=forms_common.COUNTRIES_WITH_EVENTS_IDS).filter(value__gte=2).order_by('value', 'name')
except:
	COUNTRY_TUPLES = []

class CountryRegionForm(forms_common.FormWithCity):
	country = forms.ChoiceField(
		label="Страна",
		choices=[('', '(любая)'), ('RU', 'Россия')]
			+ [(country.id, country.name) for country in COUNTRY_TUPLES],
		required=False)
	region = forms.ModelChoiceField(
		label="Или регион (для России, Украины, Беларуси)",
		queryset=models.Region.objects.none(), # TODO models.Region.objects.filter(is_active=True).order_by('name'),
		empty_label="(любой)",
		required=False)
	def clean(self):
		cleaned_data = super().clean()
		country_or_district = cleaned_data.pop('country', None)
		if country_or_district:
			if country_or_district.startswith('district'):
				district_id = country_or_district[len('district'):]
				cleaned_data['district'] = models.District.objects.filter(pk=results_util.int_safe(district_id)).first()
				if not cleaned_data['district']:
					raise forms.ValidationError(f'Не найден федеральный округ с id {district_id}')
			else:
				cleaned_data['country'] = models.Country.objects.filter(pk=country_or_district).first()
				if not cleaned_data['country']:
					raise forms.ValidationError(f'Не найдена страна с id {country_or_district}')
		return cleaned_data

DATE_REGION_ALL = 0
DATE_REGION_PAST = 1
DATE_REGION_FUTURE = 2
DATE_REGION_NEXT_WEEK = 3
DATE_REGION_NEXT_MONTH = 4
DATE_REGION_DEFAULT = DATE_REGION_ALL
class EventForm(CountryRegionForm):
	race_name = forms.CharField(
		label='Название забега или часть названия',
		max_length=100,
		required=False)
	date_region = forms.ChoiceField(
		label='Когда',
		choices=(
			(DATE_REGION_ALL, 'в прошлом и в будущем'),
			(DATE_REGION_FUTURE, 'сегодня и позже'),
			(DATE_REGION_PAST, 'сегодня и раньше'),
			(DATE_REGION_NEXT_WEEK, 'в ближайшую неделю'),
			(DATE_REGION_NEXT_MONTH, 'в ближайший месяц'),
		),
		initial=DATE_REGION_DEFAULT)
	date_from = forms.DateField(
		label="Не раньше",
		widget=forms_common.CustomDateInput,
		required=False)
	date_to = forms.DateField(
		label="Не позже",
		widget=forms_common.CustomDateInput,
		required=False)
	distance_from = forms.DecimalField(
		label="Дистанция не меньше (км)",
		min_value=0.,
		max_digits=8,
		decimal_places=3,
		required=False)
	distance_to = forms.DecimalField(
		label="Не больше (км)",
		min_value=0.,
		max_digits=8,
		decimal_places=3,
		required=False)
	hide_parkruns = forms.BooleanField(
		label="Скрыть паркраны и другие еженедельные забеги на 5 км",
		required=False)
	only_with_results = forms.BooleanField(
		label="Только забеги с уже загруженными результатами",
		required=False)
	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self.label_suffix = ''
		self.order_fields(['date_region', 'country', 'region', 'city_id', 'race_name',
			'date_from', 'date_to', 'distance_from', 'distance_to', 'hide_parkruns'])
	def clean(self):
		cleaned_data = super().clean()
		if (cleaned_data.get('date_from')) and cleaned_data['date_from'] < models.DATE_MIN:
			cleaned_data['date_from'] = models.DATE_MIN
		if cleaned_data.get('date_to'):
			if cleaned_data['date_to'] < models.DATE_MIN:
				cleaned_data['date_to'] = models.DATE_MIN
			elif cleaned_data['date_to'] > models.DATE_MAX:
				cleaned_data['date_to'] = models.DATE_MAX
		return cleaned_data

class RunnerForm(forms_common.RoundedFieldsForm):
	lname = forms.CharField(
		max_length=100,
		widget=forms.TextInput(attrs={'placeholder': 'Фамилия'}),
		required=False)
	fname = forms.CharField(
		max_length=100,
		widget=forms.TextInput(attrs={'placeholder': 'Имя'}),
		required=False)
	birthday_from = forms.DateField(
		label="Родился не раньше",
		widget=forms_common.CustomDateInput,
		required=False)
	birthday_to = forms.DateField(
		label="не позже",
		widget=forms_common.CustomDateInput,
		required=False)
	is_user = forms.BooleanField(
		label="Зарегистрирован на сайте",
		required=False)

class ResultForm(CountryRegionForm):
	race_name = forms.CharField(
		label='Название забега или часть названия',
		max_length=100,
		required=False)
	date_from = forms.DateField(
		label="Не раньше",
		widget=forms_common.CustomDateInput,
		required=False)
	date_to = forms.DateField(
		label="Не позже",
		widget=forms_common.CustomDateInput,
		required=False)
	distance_from = forms.IntegerField(
		label="Дистанция не меньше (км)",
		min_value=0,
		required=False)
	distance_to = forms.IntegerField(
		label="Не больше (км)",
		min_value=0,
		required=False)
	result_from = forms.IntegerField(
		label="Результат не меньше (сек)",
		min_value=0,
		required=False)
	result_to = forms.IntegerField(
		label="Не больше (сек)",
		min_value=0,
		required=False)
	lname = forms.CharField(
		label='Фамилия',
		max_length=100,
		required=False)
	fname = forms.CharField(
		label='Имя',
		max_length=100,
		required=False)
	midname = forms.CharField(
		label='Отчество',
		max_length=100,
		required=False)
	club = forms.CharField(
		label='Клуб',
		max_length=100,
		required=False)
	disconnected = forms.BooleanField(
		label="Не привязанные к людям",
		required=False)
	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self.order_fields(['country', 'region', 'city_id', 'race_name',
			'date_from', 'date_to', 'distance_from', 'distance_to',
			'result_from', 'result_to', 'lname', 'fname', 'midname', 'club', 'disconnected'])

class ResultFilterForm(forms_common.RoundedFieldsForm):
	name = forms.CharField(
		label='',
		max_length=100,
		widget=forms.TextInput(attrs={'placeholder': 'Имя, клуб, результат'}),
		required=False)
	with_strava = forms.BooleanField(
		label='Со ссылкой на трек',
		required=False)
	def __init__(self, race, *args, **kwargs):
		super().__init__(*args, **kwargs)
		total_count = race.n_participants

		if race.load_status == models.RESULTS_LOADED:
			gender_choices = [('', f'All genders ({race.n_participants})')]
			if race.n_participants_male:
				gender_choices.append((2, f'Men ({race.n_participants_male})'))
			if race.n_participants_female:
				gender_choices.append((1, f'Women ({race.n_participants_female})'))
			if race.n_participants_nonbinary:
				gender_choices.append((3, f'Nonbinary ({race.n_participants_nonbinary})'))
		else:
			gender_choices = [('', 'All genders'), ('2', 'Men'), ('1', 'Women'), ('1', 'Nonbinary')]
		self.fields['gender'] = forms.ChoiceField(
			label='',
			choices=gender_choices,
			required=False,
		)

		if race.load_status == models.RESULTS_LOADED:
			category_choices = [('', f'All age groups ({total_count})')]
			for category_size in race.category_size_set.filter(size__gt=0).order_by('name'):
				category_choices.append((category_size.id, f'{category_size.name} ({category_size.size})'))
		else:
			category_choices = [('', 'All age groups')]
			for category_size in race.category_size_set.order_by('name'):
				category_choices.append((category_size.id, category_size.name))
		if len(category_choices) > 1:
			self.fields['category'] = forms.ChoiceField(
				label='',
				choices=category_choices,
				required=False,
			)

class RunnerResultFilterForm(forms.Form):
	name = forms.CharField(
		label='',
		max_length=100,
		widget=forms.TextInput(attrs={'placeholder': 'Название'}),
		required=False)
	def __init__(self, results, n_results, *args, **kwargs):
		super().__init__(*args, **kwargs)
		all_series = {}
		distances = {}
		for result in results.select_related('race__event__series', 'race__distance'):
			series = result.race.event.series
			if series.id in all_series:
				all_series[series.id]['count'] += 1
			else:
				all_series[series.id] = {'name': series.name, 'count': 1}
			distance = result.race.distance
			if distance.id in distances:
				distances[distance.id]['count'] += 1
			else:
				distances[distance.id] = {'name': distance.name, 'count': 1}
		series_choices = [('', f'Все серии ({n_results})')]
		for series_id, values in sorted(list(all_series.items()), key=lambda x: (-x[1]['count'], x[1]['name'])):
			series_choices.append((series_id, f'{values["name"]} ({values["count"]})'))
		self.fields['series'] = forms.ChoiceField(
			choices=series_choices,
			required=False
		)
		distance_choices = [('', f'Все дистанции ({n_results})')]
		for distance_id, values in sorted(list(distances.items()), key=lambda x: (-x[1]['count'], x[1]['name'])):
			distance_choices.append((distance_id, f'{values["name"]} ({values["count"]})'))
		self.fields['distance'] = forms.ChoiceField(
			choices=distance_choices,
			required=False
		)

# When going to add series for some editor
class SeriesEditorForm(forms.Form):
	series_id = forms.IntegerField(
		label="id серии для редактирования",
		min_value=1,
		required=True)

# When searching through all series list
class NewsSearchForm(forms_common.FormWithCity):
	country = forms.ModelChoiceField(
		label="Страна",
		queryset=COUNTRY_TUPLES,
		empty_label="(любая)",
		required=False)
	region = forms.ModelChoiceField(
		label="Регион",
		queryset=models.Region.objects.none(), # TODO models.Region.objects.filter(is_active=True).order_by('name'),
		empty_label="(любой)",
		required=False)
	news_text = forms.CharField(
		label='Часть текста или названия',
		max_length=100,
		required=False)
	published_by_me = forms.BooleanField(
		label="Созданные мной",
		required=False)
	date_from = forms.DateField(
		label="Не раньше",
		widget=forms_common.CustomDateInput,
		required=False)
	date_to = forms.DateField(
		label="Не позже",
		widget=forms_common.CustomDateInput,
		required=False)

class MessageToInfoForm(forms_common.RoundedFieldsModelForm):
	sender_name = forms.CharField(
		label='Ваше имя',
		max_length=100,
		required=False)
	body_hidden = forms.CharField(
		widget=forms.HiddenInput(),
		required=False)
	def __init__(self, request, *args, **kwargs):
		self.user = request.user
		self.target = request.GET.get('target')
		initial = kwargs.get('initial', {})
		if request.user.is_authenticated:
			initial['sender_name'] = request.user.first_name + ' ' + request.user.last_name
			initial['reply_to'] = request.user.email
		if 'advert' in request.GET:
			advert = results_util.int_safe(request.GET['advert'])
			if advert == 1:
				initial['title'] = 'Рекламное место на странице календаря забегов'
			if advert == 2:
				initial['title'] = 'Оплата через сайт'
		elif 'runner' in request.GET:
			runner = models.Runner.objects.filter(pk=request.GET['runner']).first()
			if runner:
				initial['title'] = runner.name_with_midname()
		elif 'event_id' in request.GET:
			event = models.Event.objects.filter(pk=request.GET['event_id']).first()
			if event:
				initial['title'] = f'{event.name} ({event.dateFull(with_nbsp=False)}) — ошибка на странице'
				initial['body'] = initial['body_hidden'] = f'\n\nСтраница забега: {models.SITE_URL}{event.get_absolute_url()}'
		kwargs['initial'] = initial
		super().__init__(*args, **kwargs)
		self.fields['body'].required = True
		self.fields['title'].required = True
	def clean_attachment(self):
		attachment = self.cleaned_data['attachment']
		if attachment:
			if attachment.size > settings.MAX_USER_UPLOAD_SIZE:
				raise forms.ValidationError(
					f'Вы можете загрузить файл размером до {settings.MAX_UPLOAD_SIZE_MB} МБ. Ваш – размером {attachment.size} байт.')
		return attachment
	def clean(self):
		cleaned_data = super().clean()
		if cleaned_data.get('body', '') == cleaned_data.get('body_hidden', ''):
			raise forms.ValidationError('Пожалуйста, напишите хоть что-нибудь в теле письма.')
		if not cleaned_data.get('title'):
			cleaned_data['title'] = 'Письмо на ПроБЕГ. Тема не указана'
		if self.user.is_authenticated and hasattr(self.user, 'user_profile'):
			user_page = models.SITE_URL + self.user.user_profile.get_absolute_url()
		else:
			user_page = ''
		cleaned_data['body'] = (f'Отправитель: {cleaned_data.get("sender_name", "(не указан)")} {user_page}'
			+ f'\nОбратный адрес: {cleaned_data.get("reply_to", "(не указан)")}\n\n{cleaned_data.get("body", "")}')
		self.instance.message_type = models.MESSAGE_TYPE_TO_INFO
		if self.target == 'records':
			self.instance.message_type = models.MESSAGE_TYPE_TO_RECORDS
		if self.user.is_authenticated:
			self.instance.created_by = self.user
		return cleaned_data
	class Meta:
		model = models.Message_from_site
		fields = ['sender_name', 'reply_to', 'title', 'body', 'body_hidden', 'attachment']
		widgets = {
			'body': forms.Textarea(attrs={'rows': 6})
		}

class MessageFromInfoForm(forms_common.RoundedFieldsModelForm):
	def __init__(self, *args, **kwargs):
		initial = kwargs.get('initial', {})
		initial['body'] = ''
		self.user = kwargs.pop('request').user
		self.table_update = kwargs.pop('table_update', None)
		event = kwargs.pop('event', None)
		user = kwargs.pop('user', None)
		to_participants = kwargs.pop('to_participants', False)
		wo_protocols = kwargs.pop('wo_protocols', False)
		wrong_club = kwargs.pop('wrong_club', False)
		if self.table_update: # We're writing letter to author of this table update
			event_name = ''
			if self.table_update.model_name == 'Event':
				event = models.Event.objects.filter(pk=self.table_update.row_id).first()
				if event:
					event_name = event.name
					if wrong_club:
						initial['body'] = get_wrong_club_letter_text(self.table_update, event)
			elif self.table_update.model_name == 'Series':
				series = models.Series.objects.filter(pk=self.table_update.row_id).first()
				if series:
					event_name = series.name
			initial['title'] = f'[Ticket {self.table_update.id}] {event_name}'
			initial['target_email'] = self.table_update.user.email
			initial['table_update'] = self.table_update
		elif event:
			initial['title'] = f'{event.name} ({event.date(with_nobr=False)})'
			if to_participants: # We're writing letter to all participants of some event
				initial['target_email'] = ', '.join(event.calendar_set.filter(
					user__is_active=True, user__user_profile__email_is_verified=True).values_list('user__email', flat=True).order_by('user__email'))
				participate_verb = 'планировали' if event.is_in_past() else 'планируете'
				initial['body'] = (f' Добрый день!\n\nВы указали на сайте {settings.MAIN_PAGE}, что {participate_verb} участвовать в забеге {event.name} '
					+ f'({event.date(with_nobr=False)}, {event.strCityCountry(with_nbsp=False)}).'
					+ '\n\nСообщаем, что'
					+ f'\n\nСтраница забега на нашем сайте: {models.SITE_URL}{event.get_absolute_url()}')
			else: # We're writing letter to event organizers
				initial['target_email'] = event.email
				if wo_protocols:
					races_wo_results = event.race_set.filter(has_no_results=False).exclude(load_status=models.RESULTS_LOADED).order_by(
						'distance__distance_type', '-distance__length')
					if races_wo_results.exists():
						initial['title'] += ' — протокол забега'
						initial['body'] = (' Добрый день!\n\nМы будем рады выложить для всех желающих протокол забега '
							+ f'«{event.name}», прошедшего {event.date(with_nobr=False)}, ')
						if races_wo_results.count() == 1:
							initial['body'] += f'на дистанцию {races_wo_results[0].distance.name}.'
						else:
							initial['body'] += f'на дистанции {", ".join(x.distance.name for x in races_wo_results)}.'
						initial['body'] += ('\nСможете ли прислать его в любом формате '
							+ '(лучше всего — в формате xls или xlsx, но любой другой тоже подойдёт)?'
							+ '\n\nПохоже, никто кроме вас тут не сможет нам помочь.'
							+ '\nМы разместим ссылки на протоколы на странице нашего календаря забегов '
							+ models.SITE_URL + event.get_absolute_url() + '.'
							+ '\n\nИли, возможно, протокол просто не составлялся или забегов на эти дистанции вообще не было?'
							+ ' Тогда, пожалуйста, сообщите нам об этом.\n\nСпасибо!')
						if not event.ask_for_protocol_sent:
							event.ask_for_protocol_sent = True
							event.save()
						models.log_obj_create(self.user, event, models.ACTION_UPDATE, field_list=['ask_for_protocol_sent'],
							comment='При создании письма организаторам')

		elif user: # We're writing to some exact user
			initial['target_email'] = user.email
			initial['body'] = f' {user.first_name}, добрый день!'
		initial['body'] += f'\n\n---\n{self.user.get_full_name()},\nКоманда сайта {settings.MAIN_PAGE}'
		kwargs['initial'] = initial
		super().__init__(*args, **kwargs)
	def clean_title(self):
		title = self.cleaned_data['title'].strip()
		if title == '':
			raise forms.ValidationError('Тема сообщения не может быть пустой.')
		return title
	def clean_target_email(self):
		target_email = self.cleaned_data['target_email'].strip()
		if target_email == '':
			raise forms.ValidationError('Вы не указали адрес, куда отправлять сообщение.')
		return target_email
	def clean(self):
		cleaned_data = super().clean()
		self.instance.message_type = models.MESSAGE_TYPE_PERSONAL
		self.instance.table_update = self.table_update
		self.instance.created_by = self.user
		self.instance.bcc = settings.EMAIL_INFO_USER
		return cleaned_data
	class Meta:
		model = models.Message_from_site
		fields = ['target_email', 'title', 'body', 'attachment', 'table_update']
		widgets = {
			'body': forms.Textarea(attrs={'rows': 7}),
			'table_update': forms.HiddenInput,
		}

class UnofficialResultForm(forms_common.RoundedFieldsModelForm):
	distance = forms.ModelChoiceField(
		label="Дистанция",
		queryset=models.Distance.objects.none(),
		empty_label=None,
		required=True)
	strava_link = forms.CharField(
		label='Ссылка на пробежку на Strava вида strava.com/activities/... или strava.app.link/... (необязательно)',
		max_length=100,
		required=False)
	def __init__(self, *args, **kwargs):
		self.event = kwargs.pop('event')
		super().__init__(*args, **kwargs)
		distances = self.event.race_set.exclude(load_status__in=(models.RESULTS_LOADED, models.RESULTS_SOME_OFFICIAL)).values_list('distance_id', flat=True)
		self.fields['distance'].queryset = models.Distance.objects.filter(pk__in=distances).order_by('distance_type', '-length')
		self.fields['comment'].required = True
		self.fields['result_raw'].required = True
	def clean(self):
		cleaned_data = super().clean()
		if 'distance' not in cleaned_data:
			raise forms.ValidationError('Пожалуйста, выберите дистанцию.')
		distance = cleaned_data['distance']
		race = self.event.race_set.exclude(load_status=models.RESULTS_LOADED).filter(distance=distance).first()
		if race is None:
			raise forms.ValidationError('Пожалуйста, выберите дистанцию из доступных.')
		self.instance.race = race
		result_raw = cleaned_data.get('result_raw', '')
		if distance.distance_type in models.TYPES_MINUTES:
			result = results_util.int_safe(result_raw)
		else:
			result = models.string2centiseconds(result_raw)
		if result == 0:
			raise forms.ValidationError('Пожалуйста, введите результат в указанном формате.')

		strava_link = cleaned_data.get('strava_link')
		if strava_link:
			strava_number, tracker, is_private_activity = results_util.maybe_strava_activity_number(strava_link)
			if not strava_number:
				user = self.instance.user
				user_url = user.user_profile.get_absolute_url() if hasattr(user, 'user_profile') else ''
				panic_message = f'{user.get_full_name()} {models.SITE_URL}{user_url} tried to add Strava link {strava_link} to race {models.SITE_URL}{race.get_absolute_url()}.'
				if is_private_activity:
					panic_message += '\nMost probably this is just a private activity.'
				models.send_panic_email('Incorrect Strava link', panic_message)
				if is_private_activity:
					raise forms.ValidationError(
						f'Похоже, ссылка {strava_link} ведёт на тренировку, доступную только зарегистрированным пользователям Стравы.'
						+ ' Мы не смогли её обработать. Если вы всё равно хотите её добавить, откройте тренировку в браузере и скопируйте оттуда —'
						+ f'ссылка должна иметь вид https://{results_util.STRAVA_ACTIVITY_PREFIX}...')
				raise forms.ValidationError('Некорректная ссылка на пробежку в Strava. Нужная ссылка должна содержать'
					+ f' {results_util.STRAVA_ACTIVITY_PREFIX}<число> или {results_util.STRAVA_ACTIVITY_PREFIX}<буквы и цифры> или {results_util.GARMIN_ACTIVITY_PREFIX}<число>.')
			cleaned_data['strava_number'] = strava_number
			cleaned_data['tracker'] = tracker
		self.instance.result = result
		return cleaned_data
	class Meta:
		model = models.Result
		fields = ['distance', 'result_raw', 'comment', 'strava_link']
		labels = {
			'comment': 'Адрес страницы с результатами мероприятия или, если её нет, комментарий',
			'result_raw': 'Результат (если время – чч:мм:сс или чч:мм:сс,хх, если расстояние – число в метрах)',
		}

class UnofficialSeriesForm(forms_common.ModelFormWithCity):
	region = forms_common.RegionOrCountryField(
		required=True,
		label='* State (for USA) or country')
	new_city = forms.CharField(
		label='The city isn\'t present yet? Then enter its name',
		max_length=100,
		required=False)
	i_am_organizer = forms.BooleanField(
		label='I am one of the organizers of this event. Please provide me the permissions to edit this series',
		required=False)
	attachment = forms.FileField(
		label=f'You can attach a file up to {settings.MAX_USER_UPLOAD_SIZE_MB} MB',
		required=False)
	distances_raw = forms.CharField(
		label='* Distances, comma separated (e.g. «marathon», «half marathon», «10 km», «5 miles»)',
		max_length=100,
		required=True)
	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		for field in self.fields:
			if field == 'i_am_organizer':
				self.fields[field].widget.attrs.update({'class': 'checkbox'})
			else:
				self.fields[field].widget.attrs.update({'class': 'form-control'})
		self.fields['name'].required = True
		self.fields['surface_type'].required = True
		self.fields['surface_type'].choices = models.SURFACE_TYPES[1:-1]
	def clean_name(self):
		name = self.cleaned_data['name'].strip()
		if name == '':
			raise forms.ValidationError('Event name cannot be empty')
		if name.endswith(('.', ',')):
			raise forms.ValidationError('Event name cannot end with a punctuation mark')
		if ('http://' in name) or ('https://' in name):
			raise forms.ValidationError('This is the URL of the event site, not the event name')
		return models.replace_symbols(name)
	def clean_attachment(self):
		attachment = self.cleaned_data['attachment']
		if attachment:
			if attachment.size > settings.MAX_USER_UPLOAD_SIZE:
				raise forms.ValidationError(
					f'You can attach a file up to {settings.MAX_USER_UPLOAD_SIZE_MB} MB. Your file is {attachment.size} bytes which is too much.')
		return attachment
	def clean(self):
		cleaned_data = super().clean()
		user = self.instance.created_by
		if not (cleaned_data.get('url_site', '').strip() or cleaned_data.get('comment_private', '').strip()):
			raise forms.ValidationError('Please either specify the event site or leave some comment.')
		distances_raw = cleaned_data.get('distances_raw', '').strip()
		if not distances_raw:
			raise forms.ValidationError('Please enter the distance(s) of this event, comma-separated.')
		if '1,' in distances_raw:
			raise forms.ValidationError('We are sorry our robot doesn\'t understand the distances you entered.')
		if cleaned_data['city'] and cleaned_data['new_city'].strip():
			raise forms.ValidationError('Please either choose an existing city, or enter the name if it is not present yet.')
		if cleaned_data['city'] is None: # Creating new city
			new_city = cleaned_data['new_city'].strip()
			if not new_city:
				raise forms.ValidationError('Please either choose an existing city, or enter the name if it is not present yet.')
			region = cleaned_data.get('region')
			if not region:
				raise forms.ValidationError('Please specify the country or state of the new city.')
			if models.City.objects.filter(region=region, name=new_city).exists():
				city = models.City.objects.filter(region=region, name=new_city).first()
			else:
				city = models.City.objects.create(
					region=region,
					name=new_city,
					created_by=user,
				)
				models.log_obj_create(user, city, action=models.ACTION_CREATE, field_list=['region', 'name', 'created_by'])
			cleaned_data['city'] = city

		old_series = models.Series.objects.filter(name=cleaned_data.get('name', ''), city=cleaned_data['city']).first()
		if old_series:
			raise forms.ValidationError(f'There is already a series <a href="{old_series.get_absolute_url()}">{cleaned_data["name"]}</a> in {cleaned_data["city"].name}.'
				+ ' in our database. Probably this is what you are looking for?')

		series = models.Series.objects.create(
			name=cleaned_data.get('name', ''),
			city=cleaned_data['city'],
			url_site=cleaned_data.get('url_site', ''),
			comment_private=cleaned_data['comment_private'],
			created_by=user,
			surface_type=cleaned_data['surface_type'],
			)
		series.clean()
		series.save()
		models.log_obj_create(user, series, action=models.ACTION_CREATE, field_list=['name', 'city', 'url_site', 'comment_private', 'created_by'])
		self.instance.series = series

		if cleaned_data.get('i_am_organizer'):
			models.Series_editor.objects.create(series=series, user=user, added_by=user)
			group = Group.objects.get(name='editors')
			user.groups.add(group)
		return cleaned_data
	class Meta:
		model = models.Event
		fields = ['name', 'region', 'city', 'new_city', 'surface_type',
			'start_date', 'finish_date', 'start_time', 'url_site', 'distances_raw', 'comment_private', 'attachment',
			]
		labels = {
			'name': '* Название забега',
			'start_date': '* Дата старта',
			'surface_type': '* Вид забега',
			'city': '* Город',
		}
		widgets = {
			'start_date': forms_common.CustomDateInput,
			'finish_date': forms_common.CustomDateInput,
			'start_time': forms_common.CustomTimeInput,
		}

class UnofficialEventForm(forms_common.RoundedFieldsModelForm):
	attachment = forms.FileField(
		label=f'Вы можете приложить файл до {settings.MAX_USER_UPLOAD_SIZE_MB} МБ',
		required=False)
	distances_raw = forms.CharField(
		label='* Distances, comma separated (e.g. «marathon», «half marathon», «10 km», «5 miles»)',
		max_length=100,
		required=True)
	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self.fields['name'].required = False
	def clean_name(self):
		name = self.cleaned_data['name'].strip()
		if name == '':
			name = self.instance.series.name
		return name
	def clean_attachment(self):
		attachment = self.cleaned_data['attachment']
		if attachment:
			if attachment.size > settings.MAX_USER_UPLOAD_SIZE:
				raise forms.ValidationError(
					f'Вы можете загрузить файл размером до {settings.MAX_UPLOAD_SIZE_MB} МБ. Ваш – размером {attachment.size} байт.')
		return attachment
	def clean(self):
		cleaned_data = super().clean()
		series = self.instance.series
		if 'start_date' not in cleaned_data:
			raise forms.ValidationError('Пожалуйста, укажите дату старта мероприятия.')
		if not cleaned_data.get('distances_raw', '').strip():
			raise forms.ValidationError('Укажите дистанции, которые были на забеге, через запятую')
		if series.event_set.filter(start_date=cleaned_data['start_date']).exists():
			raise forms.ValidationError(f'В серии «{series.name}» уже есть забег, проходящий {cleaned_data["start_date"]}.')
		url_site = cleaned_data.get('url_site', '').strip()
		comment_private = cleaned_data.get('comment_private', '').strip()
		if (url_site == '') and (comment_private == ''):
			raise forms.ValidationError('Или укажите сайт события, или напишите комментарий.')
		self.instance.source = 'Через форму «Добавить событие» на сайте'
		return cleaned_data
	class Meta:
		model = models.Event
		fields = ['name', 'start_date', 'finish_date', 'start_place', 'start_time',
			'url_site', 'distances_raw', 'comment_private', 'attachment',
			]
		widgets = {
			'start_date': forms_common.CustomDateInput(),
			'finish_date': forms_common.CustomDateInput(),
			'start_time': forms_common.CustomTimeInput(),
		}

class AddReviewForm(forms.Form):
	event_id = forms.IntegerField(
		widget=forms.HiddenInput(),
		required=True)
	doc_type = forms.ChoiceField(
		label='Что вы прикладываете',
		widget=forms.RadioSelect(),
		choices=(
			(models.DOC_TYPE_IMPRESSIONS, 'Отчёт о забеге'),
			(models.DOC_TYPE_PHOTOS, 'Ссылка на фотоальбом с забега (не меньше 10 фотографий)'),
		),
		initial=1)
	url = forms.URLField(
		label='Ссылка на отчёт или фотоальбом',
		required=False)
	author = forms.CharField(
		label='Автор отчёта или фотографий',
		max_length=100,
		required=True)
	attachment = forms.FileField(
		label=f'Или приложите файл с отчётом (не больше {settings.MAX_USER_UPLOAD_SIZE_MB} МБ)',
		required=False)
	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		for field in self.fields:
			if field != 'doc_type':
				self.fields[field].widget.attrs.update({'class': 'form-control'})
	def clean_attachment(self):
		attachment = self.cleaned_data['attachment']
		if attachment:
			content_type = attachment.content_type
			if content_type not in ['application/pdf', 'application/msword']:
				raise forms.ValidationError('Вы можете загрузить только файлы в формате DOC или PDF.')
			if attachment.size > settings.MAX_USER_UPLOAD_SIZE:
				raise forms.ValidationError(
					f'Вы можете загрузить файл размером до {settings.MAX_USER_UPLOAD_SIZE_MB} МБ. Ваш – размером {attachment.size} байт.')
		return attachment
	def clean_url(self):
		url = self.cleaned_data['url']
		if 'disk.yandex.ru/client' in url:
			raise forms.ValidationError('Вы ввели адрес, который начинается на disk.yandex.ru/client.'
				+ ' Фотографии по такому адресу доступны только вам. Пожалуйста, укажите ссылку, по которой фотографии доступны всем.')
		if 'probeg.org/dj_media/uploads' in url:
			raise forms.ValidationError('Вы ввели адрес документа, который и так выложен у нас на сайте. Вряд ли это отчёт о забеге.')
		number, _, _ = results_util.maybe_strava_activity_number(url)
		if number:
			raise forms.ValidationError('Похоже, это ссылка на чью-то пробежку в трекере, а не отчёт о забеге. Если это — Ваша пробежка, Вы можете привязать её'
				+ ' к своему результату, нажав на своё имя справа сверху и затем на «Проставить ссылки на Страву».')
		return url
	def clean(self):
		cleaned_data = super().clean()
		url = cleaned_data.get('url', '').strip()
		attachment = cleaned_data.get('attachment')
		if (not url) and (not attachment):
			raise forms.ValidationError('Пожалуйста, укажите ссылку или приложите файл с отчётом.')
		if url and attachment:
			raise forms.ValidationError('Пожалуйста, укажите что-нибудь одно – или ссылку, или файл с отчётом.')
		if (cleaned_data['doc_type'] == models.DOC_TYPE_PHOTOS) and attachment:
			raise forms.ValidationError('К сожалению, загрузить фотографии к нам на сайт нельзя – у нас не так много места. '
				+ 'Пожалуйста, воспользуйтесь любым фотохостингом и опубликуйте у нас ссылку на альбом.')
		if (attachment is None) and models.Document.objects.filter(
				event_id=cleaned_data.get('event_id', 0),
				document_type=cleaned_data['doc_type'],
				url_source=cleaned_data['url']
				):
			raise forms.ValidationError('Эта ссылка уже есть на странице этого забега.')
		return cleaned_data

class ClubAndNumberForm(forms.Form):
	n_persons = forms.IntegerField(
		initial=1,
		widget=forms.NumberInput(attrs={'size': 6}),
		min_value=1,
		max_value=50,
		required=True)
	club = forms.ModelChoiceField(
		label="Клуб",
		queryset=models.Club.objects.filter(
			pk__in=set(models.Klb_team.objects.filter(year=models_klb.CUR_KLB_YEAR).exclude(
				number=models.INDIVIDUAL_RUNNERS_CLUB_NUMBER).values_list('club_id', flat=True))).order_by('name'),
		empty_label='Индивидуальные участники',
		required=False)

class ClubsEditorForm(forms_common.RoundedFieldsForm):
	club = forms.ModelChoiceField(
		label="Клуб",
		queryset = models.Club.objects.order_by('name'),
		empty_label='Выберите клуб',
		required=True)
	def __init__(self, *args, **kwargs):
		user = kwargs.pop('user')
		super().__init__(*args, **kwargs)
		user_club_ids = set(user.club_editor_set.values_list('pk', flat=True))
		self.fields['club'].queryset = models.Club.objects.exclude(pk__in=user_club_ids).order_by('name')

PROTOCOL_ABSENT = 1
PROTOCOL_BAD_FORMAT = 2
EVENT_TYPE_CODES = {
	1: 'no_protocol',
	2: 'protocol_in_complicated_format',
}
EVENT_TYPE_CODES_INV = {v: k for k, v in EVENT_TYPE_CODES.items()}
DEFAULT_REGION_ID = 46
class ProtocolHelpForm(forms_common.RoundedFieldsForm):
	events_type = forms.ChoiceField(
		label="Забеги, на которых",
		choices=(
			(PROTOCOL_ABSENT, 'полного протокола у нас нет'),
			(PROTOCOL_BAD_FORMAT, 'есть протокол в неудобном формате'),
		),
		initial=1)
	year = forms.ChoiceField(
		label="Год",
		choices=[('all', 'за все годы')] + [(x, x) for x in range(1970, results_util.TODAY.year + 1)],
		initial=results_util.TODAY.year - 1)
	region = forms_common.RegionOrCountryField(
		required=False,
		initial=DEFAULT_REGION_ID)
	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self.fields['region'].choices[0][1] = 'Все'

RATING_N_FINISHERS = 0
RATING_N_FINISHERS_MALE = 1
RATING_N_FINISHERS_FEMALE = 2
RATING_BEST_MALE = 3
RATING_BEST_FEMALE = 4
RATING_TYPES = (
	(RATING_N_FINISHERS, 'Число финишировавших'),
	(RATING_N_FINISHERS_MALE, 'Число финишировавших мужчин'),
	(RATING_N_FINISHERS_FEMALE, 'Число финишировавших женщин'),
	(RATING_BEST_MALE, 'Результат победителя среди мужчин'),
	(RATING_BEST_FEMALE, 'Результат победителя среди женщин'),
)
RATING_TYPES_DEGREES = (
	(RATING_N_FINISHERS, 'числу финишировавших'),
	(RATING_N_FINISHERS_MALE, 'числу финишировавших мужчин'),
	(RATING_N_FINISHERS_FEMALE, 'числу финишировавших женщин'),
	(RATING_BEST_MALE, 'результату победителя среди мужчин'),
	(RATING_BEST_FEMALE, 'результату победителя среди женщин'),
)
RATING_TYPES_CODES = {
	RATING_N_FINISHERS: 'n_finishers',
	RATING_N_FINISHERS_MALE: 'n_finishers_men',
	RATING_N_FINISHERS_FEMALE: 'n_finishers_women',
	RATING_BEST_MALE: 'best_male_result',
	RATING_BEST_FEMALE: 'best_female_result',
}
RATING_TYPES_CODES_INV = {v: k for k, v in RATING_TYPES_CODES.items()}
RATING_TYPES_BY_FINISHERS = (RATING_N_FINISHERS, RATING_N_FINISHERS_MALE, RATING_N_FINISHERS_FEMALE)
RATING_TYPE_DEFAULT = RATING_N_FINISHERS

RATING_YEAR_ALL = 0
RATING_YEARS_RANGE = list(range(results_util.TODAY.year, 2006, -1))
RATING_YEARS = RATING_YEARS_RANGE + [RATING_YEAR_ALL]
RATING_YEAR_DEFAULT = (results_util.TODAY.year - 1) if (results_util.TODAY.month < 6) else results_util.TODAY.year

RATING_COUNTRY_ALL = 'ALL'
RATING_COUNTRY_IDS = (RATING_COUNTRY_ALL, )
RATING_COUNTRY_DEFAULT = 'RU'
def get_degree_from_country(country):
	return RATING_COUNTRIES_DEGREES['ALL']

class RatingForm(forms.Form):
	country_id = forms.ChoiceField(
		label="Страна",
		# choices=list(models.Country.objects.filter(pk__in=RATING_COUNTRY_IDS).order_by('value').values_list('pk', 'name'))
		# 	+ [('ALL', 'Все страны'), ],
		initial='RU',
	)
	year = forms.ChoiceField(
		label="Год",
		choices=[(x, x) for x in RATING_YEARS_RANGE] + [(RATING_YEAR_ALL, 'за все годы')],
		initial=RATING_YEAR_DEFAULT,
	)
	distance_id = forms.ChoiceField(
		label="Дистанция",
		choices=list(models.Distance.objects.none().values_list( # TODO .filter(pk__in=results_util.DISTANCES_FOR_RATING).order_by('distance_type', '-length').values_list(
			'pk', 'name')) + [(results_util.DISTANCE_ANY, 'все дистанции'), (results_util.DISTANCE_WHOLE_EVENTS, 'события целиком')],
		initial=results_util.DIST_MARATHON_ID,
	)
	rating_type = forms.ChoiceField(
		label="Показатель",
		choices=RATING_TYPES,
		initial=RATING_TYPE_DEFAULT,
	)
	def clean(self):
		cleaned_data = super().clean()
		if (results_util.int_safe(cleaned_data['distance_id']) in (results_util.DISTANCE_ANY, results_util.DISTANCE_WHOLE_EVENTS)) \
				and (results_util.int_safe(cleaned_data['rating_type']) in (RATING_BEST_MALE, RATING_BEST_FEMALE)):
			cleaned_data['rating_type'] = RATING_TYPE_DEFAULT
		return cleaned_data

class AgeGroupRecordsForDistanceForm(forms_common.RoundedFieldsForm):
	country_id = forms.ChoiceField(
		label='Страна',
		choices=(('RU', 'Россия'), ),
	)
	distance_surface = forms.ChoiceField(
		label='Дистанция',
		choices=forms_common.DISTANCE_SURFACE_CHOICES
	)
	def __init__(self, *args, **kwargs):
		if 'initial' in kwargs:
			distance_id = kwargs['initial'].pop('distance_id')
			surface_type = kwargs['initial'].pop('surface_type')
			if distance_id and surface_type:
				kwargs['initial']['distance_surface'] = f'{distance_id}_{surface_type}'
		super().__init__(*args, **kwargs)

class AgeGroupRecordForm(AgeGroupRecordsForDistanceForm):
	gender = forms.ChoiceField(
		label='Пол',
		choices=results_util.GENDER_CHOICES_RUS[1:],
	)
	age = forms.ChoiceField(
		label="Возрастная группа",
		choices=[(age_group.age_min if age_group.age_min else 0, age_group) for age_group in models.Record_age_group.objects.none()], # TODO
		required=True,
	)
	def __init__(self, is_admin, *args, **kwargs):
		super().__init__(*args, **kwargs)
		if is_admin:
			self.fields['country_id'].choices = models.Country.objects.filter(pk__in=('RU', 'BY')).order_by('value').values_list('pk', 'name')

class ClubRecordsForm(forms.Form):
	year = forms.ChoiceField(
		label="Год",
		choices=[(RATING_YEAR_ALL, 'все годы')],
		initial=RATING_YEAR_ALL,
	)
	def __init__(self, *args, **kwargs):
		club = kwargs.pop('club')
		oldest_team = club.klb_team_set.order_by('year').first()
		super().__init__(*args, **kwargs)
		if oldest_team:
			self.fields['year'].choices = [(x, f'{x} год') for x in range(oldest_team.year, results_util.TODAY.year + 1)] \
				+ [(RATING_YEAR_ALL, 'все годы')]
			# self.fields['year'].initial = models_klb.CUR_KLB_YEAR

class EmailForm(forms_common.RoundedFieldsForm):
	email = forms.EmailField(
		label='Адрес электронной почты',
		max_length=models.MAX_EMAIL_LENGTH,
		widget=forms.EmailInput(attrs={'size': 30}),
		required=True)

class UsefulLinkSuggestForm(forms_common.RoundedFieldsModelForm):
	email = forms.EmailField(
		label='Ваш адрес электронной почты (необязательно, не будет отображаться, только для уточнения вопросов о ссылке)',
		max_length=models.MAX_EMAIL_LENGTH,
		widget=forms.EmailInput(),
		required=False)
	comment = forms.CharField(
		label='Комментарий (необязательно)',
		max_length=100,
		widget=forms.TextInput(),
		required=False)
	to_send_copy = forms.BooleanField(
		label='Отправьте мне копию письма с предложением ссылки',
		initial=True,
		required=False)
	def __init__(self, *args, **kwargs):
		user = kwargs.pop('user')
		if user.is_authenticated:
			initial = kwargs.get('initial', {})
			initial['email'] = user.email
			kwargs['initial'] = initial
		super().__init__(*args, **kwargs)
	class Meta:
		model = models.Useful_link
		fields = ['name', 'url', 'email', 'comment', 'to_send_copy', ]

class OrganizerForm(forms_common.RoundedFieldsModelForm):
	class Meta:
		model = models.Organizer
		fields = ['name', 'url_site', 'director_name', 'phone_number', 'email']

MIN_YEAR_FOR_RECORDS_BY_MONTH = 1992
class MonthYearForm(forms_common.RoundedFieldsForm):
	year = forms.ChoiceField(
		label="Год",
		choices=[(x, x) for x in range(MIN_YEAR_FOR_RECORDS_BY_MONTH, results_util.TODAY.year + 1)],
		initial=models_klb.CUR_KLB_YEAR,
	)
	month = forms.ChoiceField(
		label="month",
		choices=[(x, results_util.months[x]) for x in range(1, 13)],
		initial=results_util.TODAY.month,
	)

class AgeGroupResultForm(forms_common.RoundedFieldsForm):
	runner_id = forms.ChoiceField(
		label="Человек из базы спортсменов",
		choices=[],
	)
	runner_name = forms.CharField(
		label='Имя и фамилия, если нет в базе',
		max_length=40,
		required=False
	)
	age = forms.IntegerField(
		label="Возраст, если нет в базе",
		min_value=3,
		max_value=110,
		required=False,
	)
	result = forms.CharField(
		label='Результат (мм:сс,хх)',
		max_length=11,
		required=True,
	)
	coefficient = forms.DecimalField(
		label='Возрастной коэффициент',
		max_digits=2,
		decimal_places=4,
		disabled=True,
		required=False,
	)
	result = forms.CharField(
		label='Результат (мм:сс,хх)',
		max_length=11,
		required=False,
	)
	result = forms.CharField(
		label='Приведённый результат',
		max_length=11,
		required=False,
		disabled=True,
	)
	def clean(self):
		cleaned_data = super().clean()
		if cleaned_data.get('runner_id'):
			if cleaned_data.get('runner_name'):
				raise forms.ValidationError('Раз вы выбрали человека из выпадающего, не нужно отдельно писать его имя')
			if cleaned_data.get('age'):
				raise forms.ValidationError('Раз вы выбрали человека из выпадающего, не нужно отдельно писать его возраст')
		re