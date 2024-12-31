from django.urls import reverse
from django.db import models

from tools.dj_meta import MetaModelMixin
from .constants import RADIX, LEVELS_PAIRS, METHOD_DIRECT_SUMM, METHOD_REWEIGHTING, METHOD_NO_CALCULATION

from results.models import FAKE_ORGANIZER_ID


class Sr_abstract_model(models.Model, MetaModelMixin):
	class Meta:
		abstract = True

	def save(self, *args, **kwargs):
		if not (isinstance(self, Organizer_overall) and self.rated_id == FAKE_ORGANIZER_ID):
			self.full_clean()
		super(Sr_abstract_model, self).save(*args, **kwargs)

	def __str__(self):
		return ("pk={}".format(self.pk))


class Root(Sr_abstract_model):
	class Meta:
		verbose_name = 'Model for sentinel fake Root (super the Organizer model)'

	id = models.PositiveSmallIntegerField(primary_key=True)

	def save(self, *args, **kwargs):
		self.id = 0
		super(Root, self).save(*args, **kwargs)


class Method(Sr_abstract_model):
	order_for_db_structure="sr20"
	id = models.PositiveSmallIntegerField(primary_key=True)

	name = models.CharField(max_length=30, unique=True)
	description = models.CharField(max_length=200)

	is_actual = models.BooleanField(
			verbose_name='is_actual (хранить ли агр. оценки)',
			default=True
		)

	class Meta:
		verbose_name='Метод агрегирования (усреднения) оценок'

	def __str__(self):
		return "{}. {}".format(str(self.id), self.name)

	def save(self, *args, **kwargs):
		assert self.id % 2 == 1
		# ^ even values are reserved for temporary records used during
		# tree modification (see starrating.aggr.rated_tree_modifications module)
		super(Method, self).save(*args, **kwargs)


class Aggregate_values_abstract_model(Sr_abstract_model):
	class Meta:
		abstract = True

	def __str__(self):
		return 'pk={}, w={}, uc={}'.format(self.pk, self.weight, self.user_count)


# Each record uses only one of the following two fields:
	sum_int = models.IntegerField(
			verbose_name='Сумма агрегируемых оценок',
			null=True,
			blank=True,
			default=None
		)
	sum_float = models.FloatField(
			verbose_name='Сумма агрегируемых оценок',
			null=True,
			blank=True,
			default=None
		)

	weight = models.IntegerField(
			blank=True,
			default=0
		)
	user_count = models.SmallIntegerField(
			verbose_name='Сколько пользователей поставили оценки',
			null=True,
			blank=True,
			default=0,
		)


class Aggregate_abstract_model(Aggregate_values_abstract_model):
	class Meta:
		abstract = True

	id = models.PositiveIntegerField(
			verbose_name='Идентификатор (вычисляемый)',
			primary_key=True
		)

	method = models.ForeignKey(Method, on_delete=models.PROTECT)


class Overall_abstract_model(Aggregate_abstract_model):
	class Meta:
		abstract = True
		unique_together = (("rated", "method"),)

	def save(self, *args, **kwargs):
		if self.id is None:
			self.id = self.rated_id * RADIX + self.method_id
		super(Overall_abstract_model, self).save(*args, **kwargs)
		if self.rated_id is None:
			assert isinstance(self, User_overall) != ((self.id - self.method_id) % 2 == 1)  # xor
		else:
			assert self.id == self.rated_id * RADIX + self.method_id

	@property
	def based_on(self):
		return self.rated

	@based_on.setter
	def based_on(self, x):
		self.rated = x

	@property
	def based_on_id(self):
		return self.rated_id

	@based_on_id.setter
	def based_on_id(self, x):
		self.rated_id = x


class Parameter(Sr_abstract_model):
	order_for_db_structure="sr10"
	id = models.PositiveSmallIntegerField(primary_key=True)
	name = models.CharField(max_length=30, unique=True)
	description = models.CharField(max_length=500)
	to_rate = models.BooleanField(default=True)
	to_show = models.BooleanField(default=True)
	to_calculate = models.BooleanField(default=True)
	order = models.SmallIntegerField(
			verbose_name='order (для сортировки)',
			default=99
		)
	def __str__(self):
		return str(self.id) + ". " + self.name


class By_param_abstract_model(Aggregate_abstract_model):
	class Meta:
		abstract = True
		unique_together = (("overall", "parameter"),)

	parameter = models.ForeignKey(Parameter, on_delete=models.PROTECT)

	def save(self,*args, **kwargs):
		if self.id is None:
			self.id = self.overall_id * RADIX + self.parameter_id
		super(By_param_abstract_model, self).save(*args, **kwargs)
		assert self.id == self.overall_id * RADIX + self.parameter_id

	@property
	def based_on(self):
		return self.overall

	@based_on.setter
	def based_on(self, x):
		self.overall = x

	@property
	def based_on_id(self):
		return self.overall_id

	@based_on_id.setter
	def based_on_id(self, x):
		self.overall_id = x


class Root_overall(Overall_abstract_model):
	order_for_db_structure="sr2001"

	rated = models.ForeignKey(
		'starrating.Root',
		on_delete=models.PROTECT,
		related_name="sr_overall",
	)


class Organizer_overall(Overall_abstract_model):
	order_for_db_structure="sr2005"

	rated = models.ForeignKey(
		'results.Organizer',
		on_delete=models.PROTECT,
		related_name="sr_overall",
		null=True,
		blank=True,
	)

	parent = models.ForeignKey(
			Root_overall,
			on_delete=models.PROTECT,
			related_name='child'
	)


class Series_overall(Overall_abstract_model):
	order_for_db_structure="sr2010"

	rated = models.ForeignKey(
		'results.Series',
		on_delete=models.PROTECT,
		related_name="sr_overall",
		null=True,
		blank=True,
	)

	parent = models.ForeignKey(
			Organizer_overall,
			on_delete=models.PROTECT,
			related_name='child')


class Root_by_param(By_param_abstract_model):
	order_for_db_structure="sr2013"

	overall = models.ForeignKey(Root_overall, on_delete=models.PROTECT, related_name='by_param')


class Organizer_by_param(By_param_abstract_model):
	order_for_db_structure="sr2015"

	overall = models.ForeignKey(Organizer_overall, on_delete=models.CASCADE, related_name='by_param')

	parent = models.ForeignKey(
			Root_by_param,
			on_delete=models.PROTECT,
			related_name='child'
		)


class Series_by_param(By_param_abstract_model):
	order_for_db_structure="sr2020"

	overall = models.ForeignKey(Series_overall, on_delete=models.CASCADE, related_name='by_param')

	parent = models.ForeignKey(
			Organizer_by_param,
			on_delete=models.PROTECT,
			related_name='child'
		)


class Event_overall(Overall_abstract_model):
	order_for_db_structure="sr30"
	rated = models.ForeignKey(
		'results.Event',
		on_delete=models.PROTECT,
		related_name="sr_overall",
		null=True,
		blank=True,
	)

	parent = models.ForeignKey(
			Series_overall,
			on_delete=models.PROTECT,
			verbose_name='Оценки объекта-родителя (серии)',
			related_name='child')


class Event_by_param(By_param_abstract_model):
	order_for_db_structure="sr40"

	overall = models.ForeignKey(Event_overall, on_delete=models.CASCADE, related_name='by_param')

	parent = models.ForeignKey(
			Series_by_param,
			on_delete=models.PROTECT,
			verbose_name='Оценки объекта-родителя (серии)',
			related_name='child'
		)


class Race_overall(Overall_abstract_model):
	order_for_db_structure="sr50"
	rated = models.ForeignKey(
		'results.Race',
		on_delete=models.PROTECT,
		related_name="sr_overall",
		null=True,
		blank=True,
	)

	parent = models.ForeignKey(
			Event_overall,
			on_delete=models.PROTECT,
			verbose_name='Оценки объекта-родителя (забега-event)',
			related_name='child'
		)


class Race_by_param(By_param_abstract_model):
	order_for_db_structure="sr60"

	overall = models.ForeignKey(Race_overall, on_delete=models.CASCADE, related_name='by_param')
	parent = models.ForeignKey(
			Event_by_param,
			on_delete=models.PROTECT,
			verbose_name='Оценки объекта-родителя (забега-event)',
			related_name='child'
		)


class Group(Sr_abstract_model):
	order_for_db_structure="sr70"
	user = models.ForeignKey('auth.User', on_delete=models.PROTECT)
	race = models.ForeignKey('results.Race', on_delete=models.PROTECT)
	created = models.DateTimeField(verbose_name='Когда пользователь оценивал забег', auto_now_add=True)
	is_empty = models.BooleanField(
			verbose_name='True, если пользователь отказался оценивать забег',
			default=True
		)     # нужно ли? Также неясно, что должно быть здесь, если оценок нет, а отзыв есть...
	class Meta:
		verbose_name = 'Объединяет в группу оценки, поставленных данным пользователем старту (race)'
		unique_together = (("user", "race"),)
	def get_reverse_url(self, target):
		return reverse(target, kwargs={'group_id': self.id})
	def get_delete_url(self):
		return self.get_reverse_url('starrating:group_delete')
	def __str__(self):
		return "{}. race: {}, user: {}. {}".format(self.id, self.race_id, self.user_id, self.user.last_name)


class User_overall(Overall_abstract_model):
	order_for_db_structure="sr80"

	rated = models.ForeignKey(
			Group,
			on_delete=models.PROTECT,
			null=True,
			blank=True,
			verbose_name='Ссылка на группу первичных оценок.',
			related_name='sr_overall' # Should be the same as in other *_overall
		)
	parent = models.ForeignKey(
			Race_overall,
			on_delete=models.CASCADE,
			verbose_name='Оценки объекта-родителя (старта-race)',
			related_name='child'
		)

	# sum_float = None # Temporary disabled for migration system be happy TODO

	sum_int = models.SmallIntegerField(
			verbose_name='Сумма агрегируемых оценок',
			null=True,
			blank=True,
			default=None
		)


class User_by_param(By_param_abstract_model):
	order_for_db_structure="sr65"

	on_primary = models.ForeignKey(
			'Primary',
			null=True,
			blank=True,
			on_delete=models.PROTECT,
			verbose_name='Ссылка на первичную оценку',
			related_name='by_method' # May be some other name?
		)

	overall = models.ForeignKey(User_overall, on_delete=models.CASCADE, blank=True, related_name='by_param')

	parent = models.ForeignKey(
			Race_by_param,
			on_delete=models.CASCADE,
			verbose_name='Оценки объекта-родителя (старта-race)',
			related_name='child'
		)

	sum_int = models.SmallIntegerField(
			verbose_name='Сумма агрегируемых оценок',
			null=True,
			blank=True,
			default=None
		)

	class Meta(By_param_abstract_model.Meta):
		verbose_name = 'User_by_param: хранит нескрытые первичные оценки (просто дублируя Primary) для каждого метода усреднения'
		unique_together = (("overall", "parameter"), ('on_primary', 'method'))


class Primary(Sr_abstract_model):
	order_for_db_structure="sr90"

	# overall = models.ForeignKey(User_overall, on_delete=models.CASCADE)
	# Disabled becouse User_overall depends upon Method

	parameter = models.ForeignKey(Parameter, on_delete=models.PROTECT)
	group = models.ForeignKey(Group, on_delete=models.CASCADE)
	id = models.PositiveIntegerField(
			verbose_name='Идентификатор (вычисляемый)',
			primary_key=True
		)
	value = models.SmallIntegerField()
	is_hidden = models.BooleanField(
			verbose_name='Если True (может быть установлено администратором), оценка нигде не учитывается',
			default=False
		)
	class Meta:
		verbose_name = 'Оценка, поставленная пользователем старту по данному параметру (первичная оценка)'
		unique_together = (("group", "parameter"),)

	def save(self, *args, **kwargs):
		if self.id is None:
			self.id = self.group_id * RADIX + self.parameter_id
		super(Primary, self).save(*args, **kwargs)
		assert self.id == self.group_id * RADIX + self.parameter_id


	def __str__(self):
		return "{}. p:{} g:{} r:{} u:{}.{} - {}".format(
				str(self.id),
				str(self.parameter_id),
				str(self.group_id),
				str(self.group.race_id),
				str(self.group.user_id),
				self.group.user.last_name,
				str(self.value)
			)


class User_review(Sr_abstract_model):
	order_for_db_structure="sr99"
	group = models.OneToOneField(
			Group,
			on_delete=models.CASCADE,
			related_name = "review",
			primary_key=True
		)
	content = models.CharField(verbose_name='Текст отзыва', max_length=2000)
	show_user_name = models.BooleanField()
	response = models.CharField(
			verbose_name='Комментарий организаторов',
			max_length=2000,
			blank=True,
			default = ""
		)
	class Meta:
		verbose_name = "Отзыв пользователя о старте (race) и ответ организаторов"


class Delme(Sr_abstract_model):  # Temporary class for test purposes
#	so = models.ForeignKey(Series_overall)
	so = models.ForeignKey(Series_overall, null=True, on_delete=models.SET_NULL)
	sp = models.ForeignKey(Series_by_param, on_delete=models.CASCADE)
	name = models.CharField(max_length=10, null=True)


class Method_specification(Sr_abstract_model):
	DIRECT_SUMM = METHOD_DIRECT_SUMM
	REWEIGHTING = METHOD_REWEIGHTING
	NO_CALCULATION = METHOD_NO_CALCULATION
	CALCULATION_METHOD_CHOICES = (
		(DIRECT_SUMM, 'Value and weight are simple sums'),
		(REWEIGHTING, 'Value is sum of fractions, weight is count')
	)

	CALCULATION_METHOD_CHOICES_2 = CALCULATION_METHOD_CHOICES + (
		(NO_CALCULATION, 'No calculation (intended for User_by_param)'),
	)

	DIRECTION_CHOICES = (
		('by_param', 'by_param'),
		('child',  'child')
	)

	LEVEL_CHOICES = LEVELS_PAIRS

	FIELD_NAME_CHOICES = (
		('sum_int', 'sum_int'),
		('sum_float', 'sum_float'),
	)

	id = models.PositiveSmallIntegerField(primary_key=True)

	method = models.ForeignKey(Method, on_delete=models.PROTECT)

	level = models.SmallIntegerField(
		choices=LEVEL_CHOICES,
	)

	overall_spec = models.SmallIntegerField(
		choices=CALCULATION_METHOD_CHOICES
	)

	overall_dir = models.CharField(
		max_length=8,
		choices=DIRECTION_CHOICES,
	)

	overall_field = models.CharField(
		max_length=9,
		choices=FIELD_NAME_CHOICES
	)

	overall_use_correction = models.BooleanField()

	by_param_spec = models.SmallIntegerField(
		choices=CALCULATION_METHOD_CHOICES_2,
	)

	by_param_field = models.CharField(
		max_length=9,
		choices=FIELD_NAME_CHOICES
	)

	by_param_use_correction = models.BooleanField()

	class Meta:
		unique_together = (('level', 'method'),)

	def save(self, *args, **kwargs):
		if self.id is None:
			self.id = self.method_id * RADIX + self.level
		super(Method_specification, self).save(*args, **kwargs)
		assert self.id == self.method_id * RADIX + self.level


class Newdata_abstract_model(Sr_abstract_model):
	class Meta:
		abstract = True


class Group_new(Newdata_abstract_model):
	id = models.OneToOneField('starrating.Group', primary_key=True, on_delete=models.CASCADE, related_name='is_new', db_column='id')


'''
class User_overall_new(Newdata_abstract_model):
	master = models.OneToOneField(User_overall, primary_key=True, on_delete=models.CASCADE, related_name='is_new')


class Race_overall_new(Newdata_abstract_model):
4	master = models.OneToOneField(Race_overall, primary_key=True, on_delete=models.CASCADE, related_name='is_new')


class Event_overall_new(Newdata_abstract_model):
	master = models.OneToOneField(Event_overall, primary_key=True, on_delete=models.CASCADE, related_name='is_new')


class Series_overall_new(Newdata_abstract_model):
	master = models.OneToOneField(Series_overall, primary_key=True, on_delete=models.CASCADE, related_name='is_new')
'''

class Updated_abstract_model(Aggregate_values_abstract_model):
	class Meta:
		abstract = True


_updated_data_id_kwargs = dict(
		primary_key=True,
		on_delete=models.PROTECT,
		related_name='update',
		db_column='id'
	)

_updated_data_id_kwargs_2 = dict(_updated_data_id_kwargs)
_updated_data_id_kwargs_2['on_delete'] = models.CASCADE


class Overall_updated_abstract_model(Updated_abstract_model):
	class Meta:
		abstract = True

	to_delete = models.BooleanField(default=False)


class By_param_updated_abstract_model(Updated_abstract_model):
	class Meta:
		abstract = True


class User_overall_updated(Overall_updated_abstract_model):
	id = models.OneToOneField(User_overall, **_updated_data_id_kwargs_2)


class Race_overall_updated(Overall_updated_abstract_model):
	id = models.OneToOneField(Race_overall, **_updated_data_id_kwargs_2)


class Event_overall_updated(Overall_updated_abstract_model):
	id = models.OneToOneField(Event_overall, **_updated_data_id_kwargs)


class Series_overall_updated(Overall_updated_abstract_model):
	id = models.OneToOneField(Series_overall, **_updated_data_id_kwargs)


class Organizer_overall_updated(Overall_updated_abstract_model):
	id = models.OneToOneField(Organizer_overall, **_updated_data_id_kwargs)


class Root_overall_updated(Overall_updated_abstract_model):
	id = models.OneToOneField(Root_overall, **_updated_data_id_kwargs)


class User_by_param_updated(By_param_updated_abstract_model):
	id = models.OneToOneField(User_by_param, **_updated_data_id_kwargs_2)


class Race_by_param_updated(By_param_updated_abstract_model):
	id = models.OneToOneField(Race_by_param, **_updated_data_id_kwargs_2)


class Event_by_param_updated(By_param_updated_abstract_model):
	id = models.OneToOneField(Event_by_param, **_updated_data_id_kwargs)


class Series_by_param_updated(By_param_updated_abstract_model):
	id = models.OneToOneField(Series_by_param, **_updated_data_id_kwargs)


class Organizer_by_param_updated(By_param_updated_abstract_model):
	id = models.OneToOneField(Organizer_by_param, **_updated_data_id_kwargs)


class Root_by_param_updated(By_param_updated_abstract_model):
	id = models.OneToOneField(Root_by_param, **_updated_data_id_kwargs)
