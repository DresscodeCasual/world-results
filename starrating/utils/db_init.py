# -*- coding: utf-8 -*-


from starrating import models
from tools.dj_sql_tools import sql_delete, Sql_command
from starrating.aggr.globaltools import delete_aggregate_ratings, delete_sentinel_root_data, \
	make_sentinel_root_data
from results.models import Organizer, Series, FAKE_ORGANIZER_ID, FAKE_ORGANIZER_NAME

##################################################
# Some development and debug tools for Sr-system #
##################################################

PARAMETERS_STR="""1	Информация	Доступность и понятность информации в интернете о забеге, дистанциях, месте старта
2	Старт	Организация предстартовой регистрации и старта
3	Разметка	Разметка дистанции, наличие промежуточных отсечек
4	Питание	Питание на дистанции
5	Финиш	Финишный городок, питание после финиша, сувениры участникам
6	Протоколы	Качество и скорость публикации протоколов
7	В целом	Удовольствие от мероприятия в целом"""


def make_rating_parameters():
	models.Parameter.objects.all().delete()
	for line in PARAMETERS_STR.split('\n'):
		pid, name, descr = line.split("\t")
		pid = int(pid)
		to_show = True
		to_rate = True
		'''
		if pid == 1:
			to_show = False
		elif pid == 2:
			to_show = False
			to_rate = False
		elif pid == 3:
			to_rate = False
		'''
		rp = models.Parameter(id=pid, name=name, description=descr, order=pid, to_show=to_show, to_rate=to_rate)
		print(pid, name, descr, to_show, to_rate)
		rp.save()


def make_methods():
	models.Method.objects.all().delete()
	models.Method.objects.create(
			id=1,
			name='По первичным-1, не реализован',
			description='Для Race усредняет непосредсвенно первичные оценки. Далее усредняет по составляющим с равными весами',
			is_actual=0,
		)
	models.Method.objects.create(
			id=9,
			name='Только по первичным',
			description='Для всех уровней - усредняет первичные оценки',
			is_actual=0,
		)


def make_method_specifications():

	models.Method_specification.objects.all().delete()

	############
	# Method 1 #
	############
	models.Method_specification.objects.create(
		method_id=1,
		level=1, # User
		by_param_spec=models.Method_specification.NO_CALCULATION,
		by_param_field='sum_int',
		by_param_use_correction=False,

		overall_dir='child',
		overall_spec=models.Method_specification.DIRECT_SUMM,
		overall_field='sum_int',
		overall_use_correction=False,
	)

	models.Method_specification.objects.create(
		method_id=1,
		level=2,  # Race

		by_param_spec=models.Method_specification.DIRECT_SUMM,
		by_param_field='sum_int',
		by_param_use_correction=False,

		overall_dir='child',
		overall_spec=models.Method_specification.DIRECT_SUMM,
		overall_field='sum_int',
		overall_use_correction=False,
	)

	for level in (3, 4, 5, 6):  # Event, Series, Organizer, Root
		models.Method_specification.objects.create(
			method_id=1,
			level=level,

			by_param_spec=models.Method_specification.REWEIGHTING,
			by_param_field='sum_float',
			by_param_use_correction=False,

			overall_dir='child',
			overall_spec=models.Method_specification.REWEIGHTING,
			overall_field='sum_float',
			overall_use_correction=False,
		)

	###################
	# Method 9 (fake) #
	###################
	models.Method_specification.objects.create(
		method_id=9,
		level=1, # User
		by_param_spec=models.Method_specification.NO_CALCULATION,
		by_param_field='sum_int',
		by_param_use_correction=False,

		overall_dir='child',
		overall_spec=models.Method_specification.DIRECT_SUMM,
		overall_field='sum_int',
		overall_use_correction=False,
	)

	models.Method_specification.objects.create(
		method_id=9,
		level=2,  # Race

		by_param_spec=models.Method_specification.DIRECT_SUMM,
		by_param_field='sum_int',
		by_param_use_correction=False,

		overall_dir='child',
		overall_spec=models.Method_specification.DIRECT_SUMM,
		overall_field='sum_int',
		overall_use_correction=False,
	)

	for level in (3, 4, 5, 6):  # Event, Series, Organizer, Root
		models.Method_specification.objects.create(
			method_id=9,
			level=level,

			by_param_spec=models.Method_specification.DIRECT_SUMM,
			by_param_field='sum_int',
			by_param_use_correction=False,

			overall_dir='child',
			overall_spec=models.Method_specification.DIRECT_SUMM,
			overall_field='sum_int',
			overall_use_correction=False,
		)


def delete_all_ratings():
	delete_aggregate_ratings(-1)
	sql_delete('starrating.Primary')
	sql_delete('starrating.Group_new')
	sql_delete('starrating.User_review')
	sql_delete('starrating.Group')


def delete_total_db_data():
	delete_all_ratings()
	delete_sentinel_root_data(-1)
	for model in models.Method_specification, models.Method, models.Parameter:
		model.objects.all().delete()


def db_init_from_scratch():
	delete_total_db_data()
	make_rating_parameters()
	make_methods()
	make_method_specifications()
	make_sentinel_root_data(-1)
	mk_fake_organizer()


def mark_all_groups_new():
	sql_str = """
	INSERT INTO {m:Group_new}
	(
	 SELECT DISTINCT {f:Primary.group_id} 
	 FROM {m:Primary} JOIN {m:Parameter} on {f:Primary.parameter_id} = {f:Parameter.id}
	 WHERE 
		{f:Primary.is_hidden} = 0
		and {f:Parameter.to_calculate} <> 0
		and {f:Primary.group_id} not in (SELECT G2.id from {m:Group_new} as G2)
	)
	"""

	sql_cmnd = Sql_command(sql_str, 'starrating').run()


def mk_fake_organizer():
	if Organizer.all_objects.filter(pk=FAKE_ORGANIZER_ID).exists():
		fake_organizer = Organizer.objects.fake_object
		if fake_organizer.name == FAKE_ORGANIZER_NAME:
			print('Fake organizer record already exists')
		elif fake_organizer.name == '':
			fake_organizer.name = FAKE_ORGANIZER_NAME
			fake_organizer.save()
			print((
				'Fake organizer record had empty name. Now the name was set to "{}"'.format(
					FAKE_ORGANIZER_NAME
				)
			))
		else:
			print((
				'ERROR: Fake organizer has incorrect name "{}". Must be "{}"'.format(
					fake_organizer.name, FAKE_ORGANIZER_NAME
				)
			))
			exit(10)
	else:
		fake_organizer = Organizer(
			pk=FAKE_ORGANIZER_ID, name=FAKE_ORGANIZER_NAME
		)
		fake_organizer.save()
		print('Fake organizer was created')

	Series.objects.filter(organizer=None).update(organizer_id=FAKE_ORGANIZER_ID)
