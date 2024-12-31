from django.db.models import Count, Sum
from django.shortcuts import redirect
from django.contrib import messages

import datetime
import decimal
from typing import Optional, Tuple
import xlsxwriter

from results import models, results_util

def get_participants_question_answers_dicts(event, registrants):
	questions = list(event.reg_question_set.order_by('number', 'title').annotate(Count('reg_question_choice')))
	n_questions = len(questions)
	if n_questions == 0:
		return 0, None, None, None, None, None

	question_first_answers = [0] * (n_questions + 1)
	question_numbers = {}
	for i, question in enumerate(questions):
		question_first_answers[i + 1] = question_first_answers[i] + question.reg_question_choice__count
		question_numbers[question.id] = i
	# So, if there are 3 questions with 2, 10, 100 answers, question_first_answers will be [0, 2, 12, 112],
	# and if question IDs are 51, 52, 53, question_numbers will be {51: 0, 52: 1, 53: 2}.

	choice_names = [''] * question_first_answers[-1]
	for choice in models.Reg_question_choice.objects.filter(reg_question__event=event):
		question_number = question_numbers[choice.reg_question_id]
		choice_overall_number = question_first_answers[question_number] + (choice.number - 1)
		choice_names[choice_overall_number] = choice.name

	n_answers_total = question_first_answers[n_questions]
	answer_yes_sums = [0] * n_answers_total
	answers_dict = {registrant.id: [False] * n_answers_total for registrant in registrants}

	for answer in models.Reg_answer.objects.filter(registrant__race__event=event).select_related('reg_question_choice'):
		question_number = question_numbers[answer.reg_question_choice.reg_question_id]
		choice_overall_number = question_first_answers[question_number] + (answer.reg_question_choice.number - 1)
		answers_dict[answer.registrant_id][choice_overall_number] = True
		answer_yes_sums[choice_overall_number] += 1

	return questions, question_first_answers, question_numbers, choice_names, answers_dict, answer_yes_sums

BIRTHDAY_FORMAT_FULL = 0
BIRTHDAY_FORMAT_YEAR = 1
BIRTHDAY_FORMAT_AGE = 2
BIRTHDAY_FORMATS = (
	(BIRTHDAY_FORMAT_FULL, 'Дата рождения'),
	(BIRTHDAY_FORMAT_YEAR, 'Год рождения'),
	(BIRTHDAY_FORMAT_AGE, 'Возраст на день забега'),
)

def get_birthday_in_format(event, birthday, birthday_format):
	if birthday_format == BIRTHDAY_FORMAT_FULL:
		return birthday.strftime('%d.%m.%Y')
	if birthday_format == BIRTHDAY_FORMAT_YEAR:
		return birthday.year
	if birthday_format == BIRTHDAY_FORMAT_AGE:
		return event.get_age_on_event_date(birthday)
	return ''

def registration_report_response(event, all_data, birthday_format=BIRTHDAY_FORMAT_FULL, include_not_paid=True):
	now = datetime.datetime.now()
	fname = results_util.XLSX_FILES_DIR + '/probeg_reg_event_{}_report_{}.xlsx'.format(event.id, now.strftime('%Y%m%d_%H%M%S'))
	workbook = xlsxwriter.Workbook(fname)
	worksheet = workbook.add_worksheet()
	bold = workbook.add_format({'bold': True})
	number_format = workbook.add_format({'num_format': '0.00'})

	registration = event.registration
	registrants = registration.get_registrant_set()
	if not include_not_paid:
		registrants = registrants.filter(is_paid=True)

	row = 0
	col = 0
	worksheet.write(row, col, '{} {}'.format(event.name, event.date(with_nobr=False)), bold); row += 1

	if all_data:
		title = 'Все зарегистрированные'
		if not include_not_paid:
			title += ' и оплатившие участие'
	else:
		title = 'Стартовый протокол'
		if not include_not_paid:
			title += ' (только оплатившие участие)'
	worksheet.write(row, col, title); row += 2

	has_multiple_distances = event.race_set.count() > 1
	has_age_groups = models.Reg_age_group.objects.filter(race__event=event).exists()
	has_promocodes = models.Promocode.objects.filter(race__event=event).exists() or event.promocode_set.exists()

	questions, question_first_answers, question_numbers, choice_names, answers_dict, answer_yes_sums = \
		get_participants_question_answers_dicts(event, registrants)

	worksheet.write(row, col, '№', bold); col += 1
	if not all_data:
		worksheet.write(row, col, 'Стартовый номер', bold); col += 1
	if has_multiple_distances:
		worksheet.write(row, col, 'Дистанция', bold); col += 1
	worksheet.write(row, col, 'ID бегуна на ПроБЕГе', bold); col += 1
	worksheet.write(row, col, 'Имя', bold); col += 1
	if has_age_groups:
		worksheet.write(row, col, 'Возрастная группа', bold); col += 1
	worksheet.write(row, col, 'Пол', bold); col += 1
	worksheet.write(row, col, 'Город', bold); col += 1
	worksheet.write(row, col, 'Клуб', bold); col += 1
	if all_data:
		worksheet.write(row, col, 'Дата рождения', bold); col += 1
		worksheet.write(row, col, 'Возраст', bold); col += 1
		if registration.is_phone_number_needed:
			worksheet.write(row, col, 'Телефон', bold); col += 1
		if registration.is_email_needed:
			worksheet.write(row, col, 'E-mail', bold); col += 1
		if registration.is_address_needed:
			worksheet.write(row, col, 'Почтовый адрес', bold); col += 1
		worksheet.write(row, col, 'Экстренный контакт', bold); col += 1
		if questions:
			first_question_col = col
			for i, question in enumerate(questions):
				worksheet.write(row, col, question.name, bold); col += (question_first_answers[i + 1] - question_first_answers[i])
		worksheet.write(row, col, 'Время регистрации', bold); col += 1
		worksheet.write(row, col, 'Пользователь, заявивший человека', bold); col += 1
		worksheet.write(row, col, 'Его страница', bold); col += 1
	else:
		worksheet.write(row, col, BIRTHDAY_FORMATS[birthday_format][1], bold); col += 1
	if include_not_paid:
		worksheet.write(row, col, 'Участие оплачено?', bold); col += 1
	if all_data:
		if has_promocodes:
			worksheet.write(row, col, 'Промокод', bold); col += 1
		worksheet.write(row, col, 'Заплаченная сумма', bold); col += 1
	else:
		worksheet.write(row, col, 'Результат', bold); col += 1

	if all_data and questions: # Row with the names of question answers
		row += 1
		col = first_question_col
		for choice_name in choice_names:
			worksheet.write(row, col, choice_name, bold); col += 1

	# Iterate over the data and write it row by row.
	for i, registrant in enumerate(registrants.filter(is_cancelled=False)):
		row += 1
		col = 0
		worksheet.write(row, col, i + 1); col += 1
		if not all_data:
			col += 1
		if has_multiple_distances:
			worksheet.write(row, col, registrant.race.get_precise_name()); col += 1
		worksheet.write(row, col,
			registrant.user.runner.id if (registrant.registers_himself and hasattr(registrant.user, 'runner')) else ''); col += 1
		worksheet.write(row, col, registrant.get_full_name()); col += 1
		if has_age_groups:
			worksheet.write(row, col, registrant.age_group.name if registrant.age_group else ''); col += 1
		worksheet.write(row, col, registrant.get_gender_display()[0]); col += 1
		worksheet.write(row, col, registrant.city.nameWithCountry(with_nbsp=False) if registrant.city else ''); col += 1
		worksheet.write(row, col, registrant.club_name); col += 1
		if all_data:
			worksheet.write(row, col, registrant.birthday.strftime('%d.%m.%Y')); col += 1
			worksheet.write(row, col, event.get_age_on_event_date(registrant.birthday)); col += 1
			if registration.is_phone_number_needed:
				worksheet.write(row, col, registrant.phone_number); col += 1
			if registration.is_email_needed:
				worksheet.write(row, col, registrant.email); col += 1
			if registration.is_address_needed:
				worksheet.write(row, col, f'{registrant.zipcode} {registrant.address}'); col += 1
			worksheet.write(row, col, f'{registrant.emergency_phone_number} {registrant.emergency_name}'); col += 1
			if questions:
				for answer in answers_dict[registrant.id]:
					worksheet.write(row, col, answer); col += 1
			worksheet.write(row, col, registrant.created_time.strftime('%d.%m.%Y %H:%M:%S')); col += 1

			user_name = ''
			user_page = ''
			user = registrant.user
			if user:
				user_name = user.get_full_name()
				if hasattr(user, 'user_profile'):
					user_page = results_util.SITE_URL + user.user_profile.get_absolute_url()
			worksheet.write(row, col, user_name); col += 1
			worksheet.write(row, col, user_page); col += 1
		else:
			worksheet.write(row, col, get_birthday_in_format(event, registrant.birthday, birthday_format)); col += 1
		if include_not_paid:
			worksheet.write(row, col, 'да' if registrant.is_paid else 'нет'); col += 1
		if all_data:
			if has_promocodes:
				worksheet.write(row, col, registrant.promocode.name if registrant.promocode else ''); col += 1
			worksheet.write(row, col, int(registrant.price) if registrant.is_paid else ''); col += 1

	if all_data and questions: # Row with the numbers of positive answers on questions
		row += 1
		col = first_question_col
		for n_yes in answer_yes_sums:
			worksheet.write(row, col, n_yes, bold); col += 1

	cancelled_registrants = registrants.filter(is_cancelled=True)
	if all_data and cancelled_registrants:
		row += 2
		worksheet.write(row, 0, 'Отказавшиеся от участия (им вернули стартовый взнос)', bold)
		row += 1
		col = 0
		worksheet.write(row, col, '№', bold); col += 1
		if has_multiple_distances:
			worksheet.write(row, col, 'Дистанция', bold); col += 1
		worksheet.write(row, col, 'Имя', bold); col += 1
		for i, registrant in enumerate(cancelled_registrants):
			row += 1
			col = 0
			worksheet.write(row, col, i + 1); col += 1
			if has_multiple_distances:
				worksheet.write(row, col, registrant.race.get_precise_name()); col += 1
			worksheet.write(row, col, registrant.get_full_name()); col += 1

	row += 2
	worksheet.write(row, 0, 'Время создания файла:')
	worksheet.write(row, 3, now.strftime('%d.%m.%Y %H:%M:%S'))

	row += 1
	worksheet.write(row, 0, 'Страница забега:')
	worksheet.write(row, 3, '{}{}'.format(results_util.SITE_URL, event.get_absolute_url()))

	workbook.close()
	return results_util.get_file_response(fname)

def registration_payments_report_response(event=None, date_from=None, date_to=None):
	now = datetime.datetime.now()
	str_event_id = f'_event_{event.id}' if event else ''
	fname = f'{results_util.XLSX_FILES_DIR}/probeg_reg_payments_report{str_event_id}_{now.strftime("%Y%m%d_%H%M%S")}.xlsx'
	workbook = xlsxwriter.Workbook(fname, {'remove_timezone': True})
	worksheet = workbook.add_worksheet()

	centered = workbook.add_format()
	bold = workbook.add_format({'bold': True})
	bold_wrapped = workbook.add_format({'bold': True})
	number_format = workbook.add_format({'num_format': '0.00'})
	datetime_format = workbook.add_format({'num_format': 'dd.mm.yyyy hh:mm:ss'})
	centered.set_align('center')
	bold.set_align('center')
	bold_wrapped.set_align('center')
	bold_wrapped.set_align('vjustify')
	number_format.set_align('center')
	datetime_format.set_align('center')

	registrants = models.Registrant.objects.filter(is_paid=True, price__gt=0).select_related(
		'payment__response', 'race__event').order_by('payment__response__added_time', 'lname', 'fname')
	title = 'Все оплаченные регистрации'
	if event:
		registrants = registrants.filter(race__event=event)
		title += f' на забег {event.name} ({event.date(with_nobr=False)}, id {event.id})'
	if date_from:
		registrants = registrants.filter(payment__response__added_time__gte=date_from)
		title += f' с {date_from}'
	if date_to:
		registrants = registrants.filter(payment__response__added_time__lte=date_to + datetime.timedelta(days=1))
		title += f' по {date_to}'

	row = 0
	col = 0
	worksheet.write(row, col, title, bold); row += 2

	worksheet.set_column(col, col, 6);  worksheet.write(row, col, '№', bold_wrapped); col += 1
	worksheet.set_column(col, col, 12); worksheet.write(row, col, 'ID платежа у Монеты', bold_wrapped); col += 1
	worksheet.set_column(col, col, 20); worksheet.write(row, col, 'Время оплаты', bold_wrapped); col += 1
	worksheet.set_column(col, col, 10); worksheet.write(row, col, 'Поступило', bold_wrapped); col += 1
	worksheet.set_column(col, col, 10); worksheet.write(row, col, 'Получено', bold_wrapped); col += 1
	worksheet.set_column(col, col, 10); worksheet.write(row, col, 'Комиссия Монеты', bold_wrapped); col += 1
	if not event:
		worksheet.set_column(col, col, 10); worksheet.write(row, col, 'Забег', bold_wrapped); col += 1
		worksheet.set_column(col, col, 10); worksheet.write(row, col, 'Дата забега', bold_wrapped); col += 1
		worksheet.set_column(col, col, 10); worksheet.write(row, col, 'ID забега', bold_wrapped); col += 1
	worksheet.set_column(col, col, 14); worksheet.write(row, col, 'Дистанция', bold_wrapped); col += 1
	worksheet.set_column(col, col, 18); worksheet.write(row, col, 'ID платежа у нас', bold_wrapped); col += 1
	worksheet.set_column(col, col, 24); worksheet.write(row, col, 'Участник', bold_wrapped); col += 1
	worksheet.set_column(col, col, 8);  worksheet.write(row, col, 'ID зарегистировавшегося', bold); col += 1

	amount_total = 0
	withdraw_amount_total = 0

	# Iterate over the data and write it row by row.
	for i, registrant in enumerate(registrants):
		row += 1
		col = 0
		payment = registrant.payment
		response = payment.response
		worksheet.write(row, col, i + 1, centered); col += 1
		worksheet.write(row, col, response.moneta_operation_id if response else '', centered); col += 1
		worksheet.write(row, col, response.added_time if response else '', datetime_format); col += 1

		amount_total += registrant.price
		withdraw_amount_total += registrant.get_withdraw_amount()
		col_price = col
		worksheet.write(row, col, registrant.price, number_format); col += 1
		worksheet.write(row, col, registrant.get_withdraw_amount(), number_format); col += 1
		worksheet.write(row, col, payment.get_fee_percent() + ' %', centered); col += 1
		if not event:
			worksheet.write(row, col, registrant.race.event.name, centered); col += 1
			worksheet.write(row, col, registrant.race.event.date(with_nobr=False), centered); col += 1
			worksheet.write(row, col, registrant.race.event.id, centered); col += 1
		worksheet.write(row, col, registrant.race.get_precise_name(), centered); col += 1
		worksheet.write(row, col, payment.transaction_id, centered); col += 1
		worksheet.write(row, col, registrant.get_full_name()); col += 1
		worksheet.write(row, col, registrant.id, centered); col += 1

	if amount_total:
		row += 1
		worksheet.write(row, col_price - 1, 'Всего:', bold)
		worksheet.write(row, col_price, amount_total, number_format)
		worksheet.write(row, col_price + 1, withdraw_amount_total, number_format)

	if event:
		row += 1
		worksheet.write(row, 0, 'Страница забега:')
		worksheet.write(row, 3, results_util.SITE_URL + event.get_absolute_url())

	worksheet.set_column(0, 0, 6)
	worksheet.set_column(1, 1, 12)
	worksheet.set_column(2, 2, 20)
	worksheet.set_column(3, 3, 10)
	worksheet.set_column(4, 4, 10)
	worksheet.set_column(5, 5, 10)
	worksheet.set_column(6, 6, 14)
	worksheet.set_column(7, 7, 18)
	worksheet.set_column(8, 8, 24)
	worksheet.set_column(9, 9, 8)

	workbook.close()
	return results_util.get_file_response(fname)

def reg_payments_accounting_report_response(event=None, date_from=None, date_to=None):
	now = datetime.datetime.now()
	str_event_id = f'_event_{event.id}' if event else ''
	fname = f'{results_util.XLSX_FILES_DIR}/probeg_reg_payments_acc_report{str_event_id}_{now.strftime("%Y%m%d_%H%M%S")}.xlsx'
	workbook = xlsxwriter.Workbook(fname, {'remove_timezone': True})
	worksheet = workbook.add_worksheet()
	organizers = {}

	centered = workbook.add_format()
	bold = workbook.add_format({'bold': True})
	bold_wrapped = workbook.add_format({'bold': True})
	number_format = workbook.add_format({'num_format': '0.00'})
	datetime_format = workbook.add_format({'num_format': 'dd.mm.yyyy hh:mm:ss'})
	centered.set_align('center')
	bold.set_align('center')
	bold_wrapped.set_align('center')
	bold_wrapped.set_align('vjustify')
	number_format.set_align('center')
	datetime_format.set_align('center')

	registrants = models.Registrant.objects.filter(is_paid=True, price__gt=0).select_related(
		'payment__response', 'race__event__series', 'race__event__registration').order_by('-payment__response__added_time', 'lname', 'fname')
	title = 'Платежи за регистрации для проводок по бухгалтерскому учету'
	if event:
		registrants = registrants.filter(race__event=event)
		title += f' на забег {event.name} ({event.date(with_nobr=False)}, id {event.id})'
	if date_from:
		registrants = registrants.filter(payment__response__added_time__gte=date_from)
		title += f' с {date_from}'
	if date_to:
		registrants = registrants.filter(payment__response__added_time__lte=date_to + datetime.timedelta(days=1))
		title += f' по {date_to}'

	row = 0
	col = 0
	worksheet.write(row, col, title, bold); row += 2

	worksheet.set_column(col, col, 12); worksheet.write(row, col, 'ID платежа у Монеты', bold_wrapped); col += 1
	worksheet.set_column(col, col, 20); worksheet.write(row, col, 'Время оплаты', bold_wrapped); col += 1
	worksheet.set_column(col, col, 10); worksheet.write(row, col, 'Поступило', bold_wrapped); col += 1
	worksheet.set_column(col, col, 10); worksheet.write(row, col, 'Удержано Монетой', bold_wrapped); col += 1
	worksheet.set_column(col, col, 10); worksheet.write(row, col, 'ID забега', bold_wrapped); col += 1
	worksheet.set_column(col, col, 14); worksheet.write(row, col, 'Номер договора', bold_wrapped); col += 1
	worksheet.set_column(col, col, 18); worksheet.write(row, col, 'Организатор', bold_wrapped); col += 1
	worksheet.set_column(col, col, 10); worksheet.write(row, col, 'Отметка о проводке', bold_wrapped); col += 1
	worksheet.set_column(col, col, 18); worksheet.write(row, col, 'ID платежа у нас', bold_wrapped); col += 1
	worksheet.set_column(col, col, 24); worksheet.write(row, col, 'Участник', bold_wrapped); col += 1
	worksheet.set_column(col, col, 10); worksheet.write(row, col, 'Забег', bold_wrapped); col += 1
	worksheet.set_column(col, col, 10); worksheet.write(row, col, 'Дата забега', bold_wrapped); col += 1

	amount_total = 0
	withdraw_amount_total = 0

	# Iterate over the data and write it row by row.
	for i, registrant in enumerate(registrants):
		row += 1
		col = 0
		payment = registrant.payment
		response = payment.response
		series = registrant.race.event.series
		if series.id not in organizers:
			organizers[series.id] = ', '.join(series.series_editor_set.values_list('user__last_name', flat=True).order_by('user__last_name'))
		worksheet.write(row, col, response.moneta_operation_id if response else '', centered); col += 1
		worksheet.write(row, col, response.added_time if response else '', datetime_format); col += 1
		worksheet.write(row, col, registrant.price, number_format); col += 1
		worksheet.write(row, col, registrant.get_fee(), number_format); col += 1
		worksheet.write(row, col, registrant.race.event.id, centered); col += 1
		worksheet.write(row, col, registrant.race.event.registration.contract_number, centered); col += 1
		worksheet.write(row, col, organizers[series.id], centered); col += 1
		worksheet.write(row, col, '', centered); col += 1
		worksheet.write(row, col, payment.transaction_id, centered); col += 1
		worksheet.write(row, col, registrant.get_full_name()); col += 1
		worksheet.write(row, col, registrant.race.event.name, centered); col += 1
		worksheet.write(row, col, registrant.race.event.date(with_nobr=False), centered); col += 1
	workbook.close()
	return results_util.get_file_response(fname)

def payments_report_response(start_date=None, end_date=None):
	now = datetime.datetime.now()
	fname = results_util.XLSX_FILES_DIR + '/probeg_payment_report_{}.xlsx'.format(now.strftime('%Y%m%d_%H%M%S'))
	workbook = xlsxwriter.Workbook(fname)
	worksheet = workbook.add_worksheet()
	bold = workbook.add_format({'bold': True})
	number_format = workbook.add_format({'num_format': '0.00'})

	payments = models.Payment_moneta.objects.select_related('response', 'user__user_profile').order_by('-added_time')

	title = 'Все платежи на ПроБЕГе'
	if start_date:
		title += ' с {}'.format(start_date.strftime('%Y-%m-%d'))
		payments = payments.filter(added_time__gte=start_date)
	if end_date:
		title += ' по {}'.format(end_date.strftime('%Y-%m-%d'))
		payments = payments.filter(added_time__lt=end_date + datetime.timedelta(days=1))
	worksheet.write(0, 0, title)
	# worksheet.write(1, 0, unicode(payments.query))

	row = 2

	worksheet.write(row, 0, '№', bold)
	worksheet.write(row, 1, 'ID', bold)
	worksheet.write(row, 2, 'Время создания', bold)
	worksheet.write(row, 3, 'Время оплаты', bold)
	worksheet.write(row, 4, 'Имя отправителя', bold)
	worksheet.write(row, 5, 'Страница пользователя', bold)
	worksheet.write(row, 6, 'Описание', bold)
	worksheet.write(row, 7, 'Поступило', bold)
	worksheet.write(row, 8, 'Получено', bold)
	worksheet.write(row, 9, 'Комиссия, %', bold)
	worksheet.write(row, 10, 'Оплачен?', bold)

	worksheet.set_column(0, 1, 3.29)
	worksheet.set_column(2, 3, 17.29)
	worksheet.set_column(4, 5, 31.86)
	worksheet.set_column(6, 6, 40)
	worksheet.set_column(7, 8, 10)
	worksheet.set_column(9, 9, 11.57)
	worksheet.set_column(10, 10, 9.29)

	# Iterate over the data and write it out row by row.
	for i, payment in enumerate(payments):
		row += 1
		worksheet.write(row, 0, i + 1)
		worksheet.write(row, 1, payment.id)
		worksheet.write(row, 2, payment.added_time.strftime('%d.%m.%Y %H:%M:%S'))
		if payment.response:
			worksheet.write(row, 3, payment.response.added_time.strftime('%d.%m.%Y %H:%M:%S'))
		worksheet.write(row, 4, payment.sender)
		if payment.user and hasattr(payment.user, 'user_profile'):
			worksheet.write(row, 5, results_util.SITE_URL + payment.user.user_profile.get_absolute_url())
		worksheet.write(row, 6, payment.description)
		worksheet.write(row, 7, payment.amount, number_format)
		worksheet.write(row, 8, payment.withdraw_amount, number_format)
		worksheet.write(row, 9, payment.get_fee_percent().replace('.', ','), number_format)
		worksheet.write(row, 10, 'да' if payment.is_paid else 'нет')

	row += 2
	good_payments = payments.filter(is_paid=True).aggregate(Sum('withdraw_amount'), Sum('amount'))

	worksheet.write(row, 5, 'Всего по оплаченным платежам:', bold)
	worksheet.write(row, 7, good_payments['amount__sum'], bold)
	worksheet.write(row, 8, good_payments['withdraw_amount__sum'], bold)

	workbook.close()
	return results_util.get_file_response(fname)

# Round up to 2 digits after comma
def dec(x):
	return decimal.Decimal(x).quantize(decimal.Decimal('.01'))

def get_total_fee(amount_total: decimal.Decimal) -> Tuple[decimal.Decimal, str]:
	if amount_total <= 10000:
		return dec(amount_total * 95 / 1000), '9,5% от {}'.format(amount_total)
	if amount_total <= 20000:
		return dec(amount_total * 8 / 100), '8% от {}'.format(amount_total)
	return dec(amount_total * 75 / 1000), '7,5% от {}'.format(amount_total)

# Same but percent of our&Moneta fee is fixed
def reg_get_money_xls_report(request, event: models.Event, time_from: Optional[datetime.datetime],
		time_to: Optional[datetime.datetime]):
	registration = event.registration
	now = datetime.datetime.now()
	fname = results_util.XLSX_FILES_DIR + '/probeg_reg_event_{}_money_report_{}.xlsx'.format(event.id, now.strftime('%Y%m%d_%H%M%S'))
	today = datetime.date.today()
	workbook = xlsxwriter.Workbook(fname)
	worksheet = workbook.add_worksheet()
	bold = workbook.add_format({'bold': True})
	center = workbook.add_format({'align': 'center'})
	bold_center = workbook.add_format({'bold': True, 'align': 'center'})
	bold_wrapped = workbook.add_format({'bold': True, 'align': 'vjustify'})
	bold_large = workbook.add_format({'bold': True, 'font_size': 13})
	bold_large_center = workbook.add_format({'bold': True, 'font_size': 13, 'align': 'center'})
	yellow = workbook.add_format({'num_format': '0.00', 'font_size': 13, 'bold': True, 'bg_color': 'yellow', 'align': 'center'})
	number_format = workbook.add_format({'num_format': '0.00'})
	number_format_center = workbook.add_format({'num_format': '0.00', 'align': 'center'})
	number_format_bold_large_center = workbook.add_format({'num_format': '0.00', 'bold': True, 'font_size': 13, 'align': 'center'})

	registrants = models.Registrant.objects.filter(race__event=event, is_paid=True, is_cancelled=False).exclude(payment=None).select_related(
		'payment__response', 'race').order_by('payment__response__added_time')

	interval_desc = ''
	if time_from:
		registrants = registrants.filter(payment__response__added_time__gte=time_from)
		interval_desc += f' с {time_from}'
	if time_to:
		registrants = registrants.filter(payment__response__added_time__lte=time_to)
		interval_desc += f' до {time_to}'
	if not registrants.exists():
		messages.warning(request, f'В указанный интервал{interval_desc} ни одного человека не оплачивало регистрацию')
		return redirect(event.registration.get_info_url())

	worksheet.write(0, 3, 'Отчёт о выводе средств от', bold)
	worksheet.write(0, 5, today.strftime('%d.%m.%Y'), bold)
	worksheet.write(1, 2, 'Дата старта', bold)
	worksheet.write(2, 2, event.date())
	worksheet.write(1, 3, 'Забег', bold)
	worksheet.write(2, 3, event.name)
	worksheet.write(1, 7, 'ID старта', bold_center)
	worksheet.write(2, 7, event.id, center)

	worksheet.write(1, 8, 'Договор:', bold)
	worksheet.write(1, 9, 'Номер', bold)
	if registration.contract_number:
		worksheet.write(2, 9, registration.contract_number)
	worksheet.write(1, 10, 'Дата', bold)
	if registration.contract_date:
		worksheet.write(2, 10, registration.contract_date.strftime('%d.%m.%Y'))

	if interval_desc:
		worksheet.write(0, 7, 'по платежам, поступившим ' + interval_desc, bold)

	row = 4

	worksheet.write(row, 0, '№', bold_wrapped)
	worksheet.write(row, 1, 'ID платежа на Монете', bold_wrapped)
	worksheet.write(row, 2, 'ID платежа на ПроБЕГе', bold_wrapped)
	worksheet.write(row, 3, 'Время', bold_wrapped)
	worksheet.write(row, 4, 'Дистанция', bold_wrapped)
	worksheet.write(row, 5, 'Заплачено участником (₽)', bold_wrapped)
	worksheet.write(row, 6, 'Способ оплаты', bold_wrapped)
	worksheet.write(row, 7, 'Комиссия сборщика платежей (₽)', bold_wrapped)
	worksheet.write(row, 8, 'Комиссия (%)', bold_wrapped)
	worksheet.write(row, 9, 'Получено (₽)', bold_wrapped)
	worksheet.write(row, 10, 'Участник', bold_wrapped)

	worksheet.set_column(0, 0, 2.57)
	worksheet.set_column(1, 1, 11.00)
	worksheet.set_column(2, 2, 17.14)
	worksheet.set_column(3, 3, 18.14)
	worksheet.set_column(4, 4, 13.00)
	worksheet.set_column(5, 5, 15.00)
	worksheet.set_column(6, 6, 17.71)
	worksheet.set_column(7, 7, 11.71)
	worksheet.set_column(8, 8, 9.71)
	worksheet.set_column(9, 9, 9.14)
	worksheet.set_column(10, 10, 28.43)

	amount_total = 0
	withdraw_amount_total = 0

	for i, registrant in enumerate(registrants):
		row += 1
		worksheet.write(row, 0, i + 1)
		worksheet.write(row, 4, registrant.race.get_precise_name())
		worksheet.write(row, 10, registrant.get_full_name())
		payment = registrant.payment
		response = payment.response
		if response is None:
			continue
		amount_total += registrant.price
		payment_fee = payment.amount - payment.withdraw_amount

		# Part of fee that corresponds to given participant, as there can be several registrants paid by that payment
		registrant_fee = dec(registrant.get_fee())
		registrant_withdraw_amount = registrant.price - registrant_fee
		withdraw_amount_total += registrant_withdraw_amount

		worksheet.write(row, 1, response.moneta_operation_id)
		worksheet.write(row, 2, payment.transaction_id)
		worksheet.write(row, 3, response.added_time.strftime('%d.%m.%Y %H:%M:%S'))
		worksheet.write(row, 5, registrant.price, center)
		worksheet.write(row, 6, response.get_payment_method())
		worksheet.write(row, 7, registrant_fee, number_format_center)
		worksheet.write(row, 8, '{} %'.format(payment.get_fee_percent()), center)
		worksheet.write(row, 9, registrant_withdraw_amount, number_format_center)

	row += 1
	worksheet.write(row, 1, 'Итого:', bold_large)
	worksheet.write(row, 5, amount_total, bold_large_center)
	worksheet.write(row, 7, amount_total - withdraw_amount_total, number_format_bold_large_center)
	if amount_total > 0:
		worksheet.write(row, 8, '{:.2f} %'.format(100 * (amount_total - withdraw_amount_total) / amount_total), bold_large_center)
	worksheet.write(row, 9, withdraw_amount_total, number_format_bold_large_center)
	row += 2
	worksheet.write(row, 5, 'Сумма', bold_center)
	worksheet.write(row, 6, 'Как она рассчитана', bold)
	row += 1
	fee_total, fee_desc = get_total_fee(amount_total)
	worksheet.write(row, 1, 'Общая комиссия Агента и сборщика платежей:', bold)
	worksheet.write(row, 5, fee_total, number_format_center)
	worksheet.write(row, 6, fee_desc.replace('.', ','))
	row += 1
	worksheet.write(row, 1, '(9,5% при общей сумме платежей до 10.000 ₽, 8% при сумме от 10.001 до 20.000 ₽, 7,5% иначе)')
	row += 1
	for_org = dec(amount_total - fee_total)
	worksheet.write(row, 1, 'К перечислению Принципалу на счёт:', bold)
	worksheet.write(row, 5, for_org, yellow)
	worksheet.write(row, 6, f'{amount_total} - {fee_total}'.replace('.', ','))
	row += 3
	worksheet.write(row, 1, 'Справочная информация. Налоги и комиссии', bold)
	row += 1
	worksheet.write(row, 1, 'Комиссия сборщика платежей')
	worksheet.write(row, 5, amount_total - withdraw_amount_total, number_format_center)
	worksheet.write(row, 6, 'Сумма чисел в столбце H')
	row += 1
	taxable_income = withdraw_amount_total - for_org
	worksheet.write(row, 1, 'К перечислению на р/с налогоблагаемого дохода (полученное от сборщика платежей минус перечисленное Принципалу)')
	worksheet.write(row, 5, taxable_income, yellow)
	worksheet.write(row, 6, f'{amount_total} - {amount_total - withdraw_amount_total} - {for_org}'.replace('.', ','))
	row += 1
	income_tax = dec(taxable_income * 7 / 100)
	worksheet.write(row, 1, 'Налог НДС с выручки (7%)')
	worksheet.write(row, 5, income_tax, number_format_center)
	worksheet.write(row, 6, f'{taxable_income} * 7 / 100'.replace('.', ','))
	row += 1
	tax_plus_fees = 29 + 79 + dec(for_org / 100)
	worksheet.write(row, 1, 'Комиссия банку за перевод (29 ₽ + 79 ₽ + 1% от суммы, которая дойдёт Принципалу)')
	worksheet.write(row, 5, tax_plus_fees, number_format_center)
	worksheet.write(row, 6, f'29 + 79 + {for_org} / 100'.replace('.', ','))
	row += 1
	final_income = taxable_income - income_tax - tax_plus_fees
	worksheet.write(row, 1, 'Выручка Агента', bold)
	worksheet.write(row, 5, final_income, yellow)
	worksheet.write(row, 6, f'{taxable_income} - {income_tax} - {tax_plus_fees}'.replace('.', ','))
	row += 1
	final_income_percent = dec(100 * final_income / amount_total)
	worksheet.write(row, 1, 'Выручка Агента как процент от заплаченных взносов в %')
	worksheet.write(row, 5, '{:.2f} %'.format(final_income_percent), center)
	worksheet.write(row, 6, f'100 * {final_income} / {amount_total}'.replace('.', ','))

	workbook.close()
	return results_util.get_file_response(fname)
