import datetime

from django import forms

from . import forms_common, models, results_util

DISTANCE_IDS = set(results_util.DISTANCES_FOR_COUNTRY_INDOOR_RECORDS) | {x[0] for x in results_util.DISTANCES_FOR_COUNTRY_OUTDOOR_RECORDS}
class DistanceDayForm(forms_common.RoundedFieldsForm):
	event_date = forms.DateField(
		label='Дата соревнований',
		widget=forms_common.CustomDateInput,
		initial=datetime.date.today,
		required=False,
	)
	distance = forms.ModelChoiceField(
		label='Дистанция',
		queryset=models.Distance.objects.filter(pk__in=DISTANCE_IDS, distance_type=models.TYPE_METERS).order_by('length'),
		required=True,
	)
	gender = forms.ChoiceField(
		label='Пол участников',
		choices=results_util.GENDER_CHOICES[1:],
		initial=results_util.GENDER_MALE,
	)

# def get_runner_value(d: Dict[str, Any]) -> Optional[Any]:
# 	for key, val in d:
# 		if key.ends

class AgeGroupResultForm(forms_common.RoundedFieldsForm):
	runner = forms.ChoiceField(
		label="Человек из базы спортсменов",
		widget=forms.Select(attrs={'class': 'runners-list input-100', 'style': 'min-width: 400px;'}),
		required=False,
	)
	runner_name = forms.CharField(
		label='Фамилия Имя, если нет в базе',
		widget=forms.TextInput(attrs={'style': 'min-width: 250px;'}),
		max_length=40,
		required=False,
	)
	birthday = forms.DateField(
		label='Дата рождения, если нет в базе',
		widget=forms_common.CustomDateInput(),
		required=False,
	)
	result = forms.CharField(
		label='Результат (мм:сс,хх)',
		max_length=11,
		required=False,
	)
	age = forms.IntegerField(
		label="Возраст",
		required=False,
		disabled=True,
	)
	coefficient = forms.DecimalField(
		label='Возрастной коэффициент',
		max_digits=2,
		decimal_places=4,
		required=False,
		disabled=True,
	)
	result_normed = forms.CharField(
		label='Приведённый результат',
		max_length=11,
		required=False,
		disabled=True,
	)
	def __init__(self, *args, **kwargs):
		self.event_date = kwargs.pop('event_date', None)
		self.gender = kwargs.pop('gender', None)
		self.distance = kwargs.pop('distance', None)
		request = kwargs.pop('request', None)
		super().__init__(*args, **kwargs)
		runner_id = None
		if self.fields['runner'].initial:
			runner_id = self.fields['runner'].initial
		elif 'runner' in self.data:
			runner_id = kwargs['data'].get('runner')
		elif request:
			form_index = kwargs['prefix'][5:]
			runner_key = f'form-{form_index}-runner'
			if runner_key in request.POST:
				runner_id = request.POST[runner_key]
		if runner_id:
			runner = models.Runner.objects.filter(pk=runner_id).first()
			if runner:
				self.fields['runner'].choices = [(runner_id, runner.get_name_for_ajax_select())]
		for field in self.fields:
			if not self.fields[field].disabled:
				self.fields[field].widget.attrs.update({'placeholder': self.fields[field].label})
	def clean_runner(self):
		runner_id = self.cleaned_data.get('runner')
		if not runner_id:
			return None
		runner = models.Runner.objects.filter(pk=runner_id).first()
		if not runner:
			raise forms.ValidationError(f'Бегун с id {runner_id} не найден в базе участников забегов.')
		if not runner.birthday_known:
			raise forms.ValidationError(f'У бегуна с id {runner_id} в базе участников забегов не указана дата рождения. Заполните имя и дату правее.')
		return runner
	def clean_result(self):
		if 'result' not in self.cleaned_data:
			return None
		# result_str = self.cleaned_data.get('result', '')
		# if not result_str:
		# 	return None
		# result = models.string2centiseconds(result_str)
		result = models.string2centiseconds(self.cleaned_data['result'])
		if result <= 0:
			raise forms.ValidationError('Введите результат в формате чч:мм:сс,хх или мм:сс,хх.')
		return result
	def clean(self):
		cleaned_data = super().clean()
		runner = cleaned_data.get('runner')
		if runner:
			if not runner.birthday:
				raise forms.ValidationError('Вы выбрали бегуна, у которого не указана дата рождения. Странно, что вам это удалось. Пожалуйста, введите вместо этого его имя и дату рождения')
			if cleaned_data.get('runner_name'):
				raise forms.ValidationError('Раз вы выбрали человека из выпадающего списка, не нужно отдельно писать его имя')
			if cleaned_data.get('birthday'):
				raise forms.ValidationError('Раз вы выбрали человека из выпадающего списка, не нужно отдельно писать его дату рождения')
			birthday = runner.birthday
		else:
			if not cleaned_data.get('runner_name'):
				raise forms.ValidationError('Раз вы не выбрали человека из выпадающего списка, напишите его имя')
			birthday = cleaned_data.get('birthday')
			if not birthday:
				raise forms.ValidationError('Раз вы не выбрали человека из выпадающего списка, напишите его дату рождения')
		cleaned_data['age'] = results_util.get_age_on_date(self.event_date, birthday)
		if cleaned_data['age'] < 30:
			coef = 1
		else:
			coef = models.Masters_age_coefficient.objects.filter(
				year=models.CUR_AGE_COEFS_YEAR,
				gender=self.gender,
				age=cleaned_data['age'],
				distance=self.distance,
			)
			if not coef.exists():
				raise forms.ValidationError(f'Не найден коэффициент: {coef.query}')
			coef = coef.first().value
		cleaned_data['coefficient'] = coef
		if 'result' in cleaned_data:
			cleaned_data['result_str'] = models.centisecs2time(cleaned_data['result'], show_zero_hundredths=True)
			cleaned_data['result_normed'] = models.centisecs2time(int(round(cleaned_data['result'] * coef)), show_zero_hundredths=True)
		return cleaned_data
