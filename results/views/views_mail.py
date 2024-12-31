from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404
from django.urls import reverse
from django.contrib.auth.models import User
from django.http import HttpResponse
import json

from results import models, forms, results_util
from .views_common import get_first_form_error
from editor import generators, parse_strings
from editor.views.views_user_actions import log_form_change
from editor.views.views_common import group_required
from editor.views.views_parkrun import create_future_events, PARKRUN_DISTANCE

def get_send_to_info_page(request):
	context = {}
	context['form'] = forms.MessageToInfoForm(request)
	return render(request, "results/modal_letter_to_info.html", context)

@group_required('admins')
def get_send_from_info_page(request, table_update_id=None, event_id=None,
		event_participants_id=None, event_wo_protocols_id=None, user_id=None, wrong_club=None):
	context = {}
	table_update = get_object_or_404(models.Table_update, pk=table_update_id) if table_update_id else None
	event = get_object_or_404(models.Event, pk=event_id) if event_id else None
	to_participants = False
	wo_protocols = False
	wrong_club = (wrong_club is not None)
	if event_participants_id:
		event = get_object_or_404(models.Event, pk=event_participants_id)
		to_participants = True
	elif event_wo_protocols_id:
		event = get_object_or_404(models.Event, pk=event_wo_protocols_id)
		wo_protocols = True
	user = get_object_or_404(User, pk=user_id) if user_id else None
	context['form'] = forms.MessageFromInfoForm(request=request, table_update=table_update, event=event, user=user,
		to_participants=to_participants, wo_protocols=wo_protocols, wrong_club=wrong_club)
	if table_update_id:
		context['table_update_id'] = table_update_id
	return render(request, "results/modal_letter_from_info.html", context)

@login_required
def get_add_event_page(request, series_id):
	context = {}
	context['series'] = get_object_or_404(models.Series, pk=series_id)
	context['frmEvent'] = forms.UnofficialEventForm(instance=models.Event(name=context['series'].name))
	return render(request, "results/modal_add_event.html", context)

@login_required
def get_add_series_page(request):
	context = {}
	context['frmSeries'] = forms.UnofficialSeriesForm
	return render(request, "results/modal_add_series.html", context)

@login_required
def get_add_review_page(request, event_id, photo=0):
	context = {}
	context['event'] = get_object_or_404(models.Event, pk=event_id)
	initial = {'event_id': int(event_id), 'author': request.user.get_full_name()}
	initial['doc_type'] = models.DOC_TYPE_PHOTOS if photo else models.DOC_TYPE_IMPRESSIONS
	context['form'] = forms.AddReviewForm(initial=initial)
	return render(request, "results/modal_add_review.html", context)

def create_distances_from_raw(user, event):
	for distance_raw in event.distances_raw.split(','):
		distance = parse_strings.parse_distance(distance_raw.strip(' ."«»'))
		if distance and not event.race_set.filter(distance=distance).exists():
			race = models.Race(
				event=event,
				created_by=user,
				distance=distance,
			)
			race.clean()
			race.save()
			models.log_obj_create(user, event, models.ACTION_RACE_CREATE, child_object=race)

@login_required
def add_unofficial_event(request, series_id):
	series = get_object_or_404(models.Series, pk=series_id)
	context = {}
	message_text = ''
	res = {}
	res['success'] = 0
	if request.method == 'POST':
		user = request.user
		form = forms.UnofficialEventForm(request.POST, instance=models.Event(series=series, name=series.name, created_by=user))
		if form.is_valid():
			event = form.save()
			event.clean()
			event.save()
			log_form_change(user, form, action=models.ACTION_CREATE)
			res['success'] = 1
			create_distances_from_raw(user, event)
			message_from_site = models.Message_from_site.objects.create(
				message_type=models.MESSAGE_TYPE_USER_ACTION_TO_ADMINS,
				title='Создан новый забег: {} ({})'.format(event.name, event.date(with_nobr=False)),
				attachment=request.FILES.get('attachment', None),
			)
			body = ('Только что пользователь {} ({}{}, {}) создал новый забег.\n\n'
				+ 'Название: {}\nСтраница забега: {}{}\n'
				+ 'Серия: {} ({}{})\nДата проведения: {}\nСайт забега: {}\n'
				+ 'Дистанции: {}\nКомментарий (виден только администраторам): «{}»\n\n').format(
				user.get_full_name(), results_util.SITE_URL, user.user_profile.get_absolute_url(), user.email,
				event.name, results_util.SITE_URL, event.get_absolute_url(), event.series.name, results_util.SITE_URL, event.series.get_absolute_url(),
				event.date(with_nobr=False), event.url_site, event.distances_raw, event.comment_private,
				)
			if event.race_set.exists():
				body += 'Были распознаны и автоматически добавлены следующие дистанции: {}. \n\n'.format(
					', '.join(race.distance.name for race in event.race_set.order_by('distance__distance_type', '-distance__length')))
			if message_from_site.attachment:
				body += 'Также пользователь приложил файл {}/{} размером {} байт. \n\n'.format(
					results_util.SITE_URL, message_from_site.attachment.name, message_from_site.attachment.size)
			body += 'Теперь нужно:\n1. На странице {}{} одобрить добавленный пробег;\n'.format(
				results_util.SITE_URL, reverse('editor:action_history'))
			if message_from_site.attachment:
				body +=  ('2. На странице редактирования забега {}{} '
					+ 'добавить недостающие дистанции и приложить документы.\n\n').format(results_util.SITE_URL, event.get_editor_url())
			else:
				body +=  ('2. На странице редактирования забега {}{} '
					+ 'добавить недостающие дистанции.\n\n').format(results_util.SITE_URL, event.get_editor_url())
			body += 'Удачных стартов!\nВаш робот'
			message_from_site.body = body
			message_from_site.save()
			send_res = message_from_site.try_send(attach_file=False)
			if not send_res['success']:
				models.send_panic_email(
					'Message to info about adding new event could not be sent',
					'There was a problem with sending message id {} about user {} creating event {}. Error: {}'.format(
						message_from_site.id, user.id, event.id, send_res['error']),
					to_all=True
				)
		else:
			res['error'] = get_first_form_error(form)
	else:
		res['error'] = 'Запрос не получен.'
	return HttpResponse(json.dumps(res), content_type='application/json')

@login_required
def add_unofficial_series(request):
	context = {}
	message_text = ''
	res = {}
	res['success'] = 0
	if request.method == 'POST':
		user = request.user
		user_is_editor = user.groups.filter(name="editors").exists()
		form = forms.UnofficialSeriesForm(request.POST, instance=models.Event(series=models.Series(), created_by=user))
		if form.is_valid():
			event = form.save()
			event.city = None
			event.surface_type = models.SURFACE_DEFAULT
			event.source = 'Через форму «Добавить серию» на сайте'
			event.clean()
			event.save()

			series = event.series
			log_form_change(user, form, action=models.ACTION_CREATE)
			res['success'] = 1
			create_distances_from_raw(user, event)

			if series.is_russian_parkrun() and user_is_editor and event.race_set.count() == 1 and event.race_set.all()[0] == PARKRUN_DISTANCE:
				n_created_parkruns = create_future_events(series, models.USER_ROBOT_CONNECTOR)

			res['link'] = results_util.SITE_URL + series.get_absolute_url()
			message_from_site = models.Message_from_site.objects.create(
				message_type=models.MESSAGE_TYPE_USER_ACTION_TO_ADMINS,
				title=f'Созданы серия и забег в ней: {event.name} ({event.date(with_nobr=False)})',
				attachment=request.FILES.get('attachment', None),
			)
			body = ('Только что пользователь {} ({}{}) создал серию и забег в ней.\n\n'
				+ 'Название: {}\nГород: {}\nСтраница серии: {}{}\n'
				+ 'Дата проведения: {}\nСайт забега: {}\n'
				+ 'Дистанции: {}\nКомментарий (виден только администраторам): «{}»\n\n').format(
				user.get_full_name(), results_util.SITE_URL, user.user_profile.get_absolute_url(), 
				event.name, event.strCityCountry(with_nbsp=False), results_util.SITE_URL, series.get_absolute_url(),
				event.date(with_nobr=False), event.url_site, event.distances_raw, event.comment_private,
				)
			if event.race_set.exists():
				body += 'Были распознаны и автоматически добавлены следующие дистанции: {}.\n\n'.format(
					', '.join(race.distance.name for race in event.race_set.order_by('distance__distance_type', '-distance__length')))
			if message_from_site.attachment:
				body += 'Также пользователь приложил файл {}/{} размером {} байт.\n\n'.format(
					results_util.SITE_URL, message_from_site.attachment.name, message_from_site.attachment.size)
			if form.cleaned_data.get('i_am_organizer'):
				body += 'Пользователь указал, что является организатором забега. Ему выданы права на редактирование забега.\n\n'.format()
			body += 'Теперь нужно:\n1. На странице {}{} одобрить добавленные пробег и серию;\n'.format(
				results_util.SITE_URL, reverse('editor:action_history'))
			if message_from_site.attachment:
				body += '2. На странице редактирования забега {}{} добавить недостающие дистанции и приложить документы.\n\n'.format(
					results_util.SITE_URL, event.get_editor_url())
			else:
				body += '2. На странице редактирования забега {}{} добавить недостающие дистанции.\n\n'.format(results_util.SITE_URL, event.get_editor_url())
			body += 'Удачных стартов!\nВаш робот'
			message_from_site.body = body
			message_from_site.save()
			send_res = message_from_site.try_send(attach_file=False)
			if not send_res['success']:
				models.send_panic_email(
					'Message to info about adding new series could not be sent',
					'There was a problem with sending message id {} about user {} creating series {}. Error: {}'.format(
						message_from_site.id, user.id, series.id, send_res['error']),
					to_all=True
				)
		else:
			res['error'] = get_first_form_error(form)
	else:
		res['error'] = 'Запрос не получен.'
	return HttpResponse(json.dumps(res), content_type='application/json')

def send_message(request):
	context = {}
	result = {}
	result['success'] = 0
	if request.method == 'POST':
		form = forms.MessageToInfoForm(request, request.POST, request.FILES)
		if form.is_valid():
			message_from_site = form.save()
			result = message_from_site.try_send()
		else:
			result['error'] = get_first_form_error(form)
	else:
		result['error'] = 'Запрос не получен.'
	return HttpResponse(json.dumps(result), content_type='application/json')

@group_required('admins')
def send_message_admin(request):
	context = {}
	result = {}
	result['success'] = 0
	if request.method == 'POST':
		form = forms.MessageFromInfoForm(request.POST, request.FILES, request=request)
		if form.is_valid():
			message_from_site = form.save()
			result = message_from_site.try_send()
			result['targets'] = message_from_site.target_email
		else:
			result['error'] = get_first_form_error(form)
	else:
		result['error'] = 'Запрос не получен.'
	return HttpResponse(json.dumps(result), content_type='application/json')

@login_required
def add_review(request):
	context = {}
	message_text = ''
	res = {}
	res['success'] = 0
	if request.method == 'POST':
		user = request.user
		form = forms.AddReviewForm(request.POST, request.FILES)
		if form.is_valid():
			event = get_object_or_404(models.Event, pk=form.cleaned_data['event_id'])
			attachment = request.FILES.get('attachment', None)
			doc_type = results_util.int_safe(form.cleaned_data['doc_type'])
			author_runner_id = None
			if str(form.cleaned_data['author']).startswith(user.get_full_name()) and hasattr(user, 'runner'):
				author_runner_id = user.runner.id
			doc = models.Document.objects.create(
				event=event,
				document_type=doc_type,
				loaded_type=models.LOAD_TYPE_LOADED if attachment else models.LOAD_TYPE_NOT_LOADED,
				upload=attachment,
				url_source=form.cleaned_data['url'],
				author=form.cleaned_data['author'],
				author_runner_id=author_runner_id,
				created_by=user
			)
			models.log_obj_create(user, event, models.ACTION_DOCUMENT_CREATE, child_object=doc, verified_by=models.USER_ROBOT_CONNECTOR)
			doc.process_review_or_photo()
			generators.generate_last_added_reviews()
			res['success'] = 1
			res['link'] = results_util.SITE_URL + event.get_absolute_url()
			doc_link = f'{results_util.SITE_URL}/{doc.upload.name}' if attachment else doc.url_source
			if not models.is_admin(user):
				message_from_site = models.Message_from_site.objects.create(
					message_type=models.MESSAGE_TYPE_USER_ACTION_TO_ADMINS,
					title=f'{event.name} ({event.date(with_nobr=False)}) — добавлен {doc.get_report_or_photo_doc_type()}',
					attachment=attachment,
				)
				message_from_site.body = (f'{user.get_full_name()} ({results_util.SITE_URL}{user.user_profile.get_absolute_url()}) добавил на сайт {doc.get_report_or_photo_doc_type()} '
					+ f'к забегу:\n{doc_link}\n\n')
				if doc.author:
					message_from_site.body += f'Автор документа: {doc.author}.\n\n'
				message_from_site.body += f'Все документы забега: {results_util.SITE_URL}{event.get_absolute_url()}\n\nВаш робот'
				message_from_site.save()
				send_res = message_from_site.try_send(attach_file=False)
				if not send_res['success']:
					models.send_panic_email(
						'Message to info about adding new review could not be sent',
						'There was a problem with sending message id {} about user {} creating document {} for event {}. Error: {}'.format(
							message_from_site.id, user.id, doc.id, event.id, send_res['error']),
						to_all=True
					)
		else:
			res['error'] = get_first_form_error(form)
	else:
		res['error'] = 'Запрос не получен.'
	return HttpResponse(json.dumps(res), content_type='application/json')

# Given a queryset with costs, choose the most appropriate for given age and gender
def choose_price_for_age_gender(race_costs, age, gender):
	senior_cost = race_costs.filter(gender=gender, age_min__lte=age).first()
	if senior_cost:
		return senior_cost
	child_cost = race_costs.filter(age_max__gte=age).first()
	if child_cost:
		return child_cost
	return race_costs.filter(age_min=None, age_max=None).first()

def get_raceday_price(event, registrant):
	age = event.get_age_on_event_date(registrant.birthday)
	all_costs = registrant.race.race_cost_set
	raceday_cost = choose_price_for_age_gender(all_costs.filter(is_for_race_day=True), age, registrant.gender)
	if raceday_cost:
		return raceday_cost.cost
	finish_date_cost = choose_price_for_age_gender(all_costs.filter(finish_date=None, is_for_race_day=False), age, registrant.gender)
	if finish_date_cost:
		return finish_date_cost.cost
	models.send_panic_email(
		'Race day price not found',
		'There are no race day prices on event {} (id {}) for registrant {} (id {}).'.format(
			event, event.id, registrant.get_full_name(), registrant.id),
		to_all=True
	)
	return 0

def send_reg_complete_mail(user, registration, registrant):
	race = registrant.race
	event = race.event
	url_cart = results_util.SITE_URL + reverse("results:reg_cart")
	url_open_regs = results_util.SITE_URL + reverse("results:open_registrations")

	title = f'ПроБЕГ: успешная регистрация на забег «{event.name}» {event.date(with_nobr=False)} ({race.get_precise_name()})'
	body = f' {user.first_name}, добрый день!'

	if registrant.registers_himself:
		str_action = 'зарегистрировались'
	else:
		str_action = f'зарегистрировали участника {registrant.fname} {registrant.lname}'
	body += f'\n\nВы успешно {str_action} на забег «{event.name}», '
	body += f'который пройдёт {results_util.date2str(race.get_start_date(), with_nbsp=False)} года, на дистанцию {race.get_precise_name()}.'

	if registrant.promocode:
		body += f'\nВы использовали промокод {registrant.promocode.name}.'
	if registrant.price == 0:
		body += '\nУчастие в забеге бесплатное, достаточно прийти на старт.'
	elif registration.can_pay_on_event_day:
		raceday_price = get_raceday_price(event, registrant)
		if registrant.race_cost.cost == raceday_price:
			body += (f'\nВы можете оплатить участие заранее на странице {url_cart}'
				+ ' или в день забега перед стартом.'
				+ f' Стоимость в любом случае составит {registrant.price} ₽.')
		else:
			body += (f'\nВы можете оплатить участие заранее на странице {url_cart} ({registrant.price} ₽)'
				+ f' или в день забега перед стартом ({raceday_price} ₽).')
	else:
		reg_finish_datetime = f'{results_util.date2str(registration.finish_date, with_nbsp=False)}, {registration.finish_date.strftime("%H:%M")}'
		body += ('\nОсталось оплатить участие. Это можно сделать до закрытия регистрации'
			+ f' ({reg_finish_datetime} по московскому времени) на странице {url_cart} .')

	if registrant.price > 0:
		body += '\n\nВы также можете за раз оплатить несколько регистраций сразу. '
	else:
		body += '\n\n'

	body += (f'На странице {results_util.SITE_URL}{event.get_reg_url()} можно зарегистрировать другого человека на этот же забег;'
		+ f' на {url_open_regs} — посмотреть на все забеги, на которые у нас открыта регистрация.')

	body += (f'\n\nКонтакты организаторов и ссылка на положение забега есть на странице {results_util.SITE_URL}{event.get_absolute_url()} .'
		+ ' По любым вопросам, связанным с забегом, лучше пишите напрямую организаторам.'
		+ ' В случае каких-либо важных изменений мы сразу напишем Вам на этот же адрес.')

	body += u'\n\nУдачи на забеге!\n\n---\nРобот сайта «ПроБЕГ»'

	message = models.Message_from_site.objects.create(
		message_type=models.MESSAGE_TYPE_REG_COMPLETE,
		title=title,
		body=body,
		target_email=user.email,
	)
	send_res = message.try_send()
	if not send_res['success']:
		models.send_panic_email(
			'Message to user about completed registration could not be sent',
			f'There was a problem with sending message id {message.id} about user {user.id} registering for event {event.id}'
			+ f' (registrant id {registrant.id}). Error: {send_res["error"]}'
			# to_all=True
		)
	return send_res['success']

def send_reg_payment_received_mail(payment):
	registrants = payment.registrant_set.select_related('race__event')
	n_registrants = registrants.count()
	url_cart = results_util.SITE_URL + reverse("results:reg_cart")
	url_open_regs = results_util.SITE_URL + reverse("results:open_registrations")
	registers_only_himself = all(registrant.registers_himself for registrant in registrants)

	str_registrations = 'регистрации' if (n_registrants == 1) else 'регистраций'
	events = set(registrant.race.event for registrant in registrants)
	if len(events) == 1:
		race = registrants[0].race
		event = race.event
		str_events = f'забег {event.name} {event.date(with_nobr=False)}'
	elif len(events) <= 5:
		delimiter = ', ' if (len(events) == 2) else ' и '
		str_events = 'забеги ' + delimiter.join(f'{event.name} {event.date(with_nobr=False)}' for event in events)
	else:
		str_events = 'забеги'
	title = f'ПроБЕГ: успешная оплата {str_registrations} на {str_events}'

	body = f' {payment.user.first_name}, добрый день!'
	if registers_only_himself:
		str_action = 'оплатили своё участие'
	else:
		str_action = f'оплатили участие'
	if n_registrants == 1:
		if not registers_only_himself:
			str_action += f' бегуна {registrants[0].get_full_name()}'
		body += f'\n\nВы успешно {str_action} в забеге {event.name}, '
		body += f'который пройдёт {results_util.date2str(race.get_start_date(), with_nbsp=False)} года, на дистанцию {race.get_precise_name()}.'
	else:
		body += f'\n\nВы успешно {str_action} в следующих забегах:'
		for i, registrant in enumerate(registrants.order_by('race__event__start_date', '-race__distance__length', 'lname', 'fname')):
			race = registrant.race
			event = race.event
			body += f'\n{i + 1}. {event.name}, {results_util.date2str(race.get_start_date(), with_nbsp=False)}, дистанция {race.get_precise_name()}'
			if not registers_only_himself:
				body += f', {registrant.get_full_name()}'
		
	body += f'\n\nВсе забеги, на которые вы регистрировались через наш сайт: {url_cart}'
	if models.Event.get_events_with_open_reg().exists():
		body += f'\n\nЗабеги, на которые у нас сейчас открыта регистрация: {url_open_regs}'

	body += u'\n\nУдачи на забеге!\n\n---\nРобот сайта «ПроБЕГ»'

	message = models.Message_from_site.objects.create(
		message_type=models.MESSAGE_TYPE_REG_PAID,
		title=title,
		body=body,
		target_email=payment.user.email,
	)
	send_res = message.try_send()
	if not send_res['success']:
		models.send_panic_email(
			'Message to user about registration payment could not be sent',
			f'There was a problem with sending message id {message.id} about user {payment.user.id} completing payment {payment.id}.'
			+ f' Error: {send_res["error"]}'
			# to_all=True
		)
	return send_res['success']

def send_suggest_useful_link_mail(user, cleaned_data):
	title = f'Письмо на ПроБЕГ. Предложение ссылки на {cleaned_data["url"]}'
	body = f'Добрый день!\n\nПосетитель сайта'
	user_email = cleaned_data.get('email')
	if user_email:
		body += f' с адресом {user_email}'
	else:
		body += f', не указавший свой емейл,'
	body += f' предложил добавить ссылку на страницу {cleaned_data["url"]} и назвать её «{cleaned_data["name"]}».'
	comment = cleaned_data.get('comment', '')
	if comment:
		body += f'\n\nКомментарий к ссылке: «{comment}».'

	cc = ''
	if user_email and cleaned_data.get('to_send_copy'):
		body += f'\n\nКопия этого письма отправлена пользователю.'
		cc = user_email
	body += f'\n\nДобавить ссылку можно на странице {results_util.SITE_URL}{reverse("results:useful_links")}.\n\nХорошего дня!\nВаш робот'
	message = models.Message_from_site.objects.create(
		message_type=models.MESSAGE_TYPE_TO_INFO,
		title=title,
		body=body,
	)
	send_res = message.try_send()
	return send_res['success']
