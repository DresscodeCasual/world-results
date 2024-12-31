from django.core.mail import send_mail
from django.shortcuts import render, get_object_or_404
from django.template.loader import render_to_string
from django.contrib.auth.models import User
from django.http import HttpResponse
from django.contrib import messages
import smtplib
import time

from results import models, models_klb
from . import views_common

def test_email():
	send_mail(
		"Test email from Django",
		"Here is the message.\n\nAlexey",
		"info@worldresults.org",
		["alexey.chernov@gmail.com"],
		fail_silently=False,
	)

def test_email2():
	server = smtplib.SMTP('smtp-relay.gmail.com', port=587)
	server.starttls()
	server.set_debuglevel(1)
	server.login(user='info@worldresults.org', password='')
	server.sendmail(from_addr='info@worldresults.org', to_addrs=["alexey.chernov@gmail.com"], msg='Here is the message.\n\nAlexey')

@views_common.group_required('admins')
def message_details(request, message_id=None):
	context = {}
	message = get_object_or_404(models.Message_from_site, pk=message_id)
	if message.body_html:
		res = message.body_html
	else:
		res = '<html><body><pre>' + message.body + '</pre></body></html>'
	return HttpResponse(res)

def get_context_for_klb_person(person):
	context = {}
	year = models_klb.CUR_KLB_YEAR
	participant = person.klb_participant_set.filter(year=year).first()
	if participant:
		team = participant.team
		context['participant'] = participant
		context['teams_number'] = models.Klb_team.get_teams_number(year)
		if team:
			context['team'] = team
			if team.place_medium_teams:
				context['medium_teams_number'] = models.Klb_team.get_medium_teams_number(year)
			elif team.place_small_teams:
				context['small_teams_number'] = models.Klb_team.get_small_teams_number(year)
	return context

def get_context_for_user_letter(user=None, runner=None, added_to_team_data=None, added_to_club_data=None):
	context = {}
	context['url_start'] = results_util.SITE_URL
	if user: # Slightly different behavior for users and runners. And we try to fill runner for user and vice versa
		if hasattr(user, 'runner'):
			runner = user.runner
		context['user_name'] = user.first_name
		if hasattr(user, 'user_profile'):
			context['user_city'] = user.user_profile.city
	elif runner:
		user = runner.user
		context['user_name'] = runner.fname
		context['user_city'] = runner.city
	else:
		return context

	if user:
		context['user'] = user
		context['claimed_results'] = user.result_for_mail_set.filter(is_sent=False).select_related('result__race__event').order_by(
			'result__race__event__start_date')
	if runner:
		context['n_unclaimed_results'] = len(runner.get_possible_results())
		if runner.klb_person:
			context.update(get_context_for_klb_person(runner.klb_person))
	context['added_to_team_data'] = added_to_team_data
	context['added_to_club_data'] = added_to_club_data
	return context

# Should be called only if user.user_profile is not None and profile.email_is_verified=True
def send_user_results_letter(user, sender, context, connection=None):
	profile = user.user_profile
	table_update = models.Table_update.objects.create(model_name=profile.__class__.__name__,
		row_id=profile.id, action_type=models.ACTION_RESULT_MESSAGE_SEND, user=sender)
	message_from_site = models.Message_from_site.objects.create(
		message_type=models.MESSAGE_TYPE_RESULTS_FOUND,
		target_email=user.email,
		# target_email='alexey.chernov@gmail.com',
		table_update=table_update,
		title='ПроБЕГ: Ваши новые результаты',
		body=render_to_string('letters/letter_results.txt', context),
		body_html=render_to_string('letters/letter_results.html', context),
		created_by=sender,
	)
	return message_from_site.try_send(connection=connection)

# Should be called only if user is None or user.user_profile is not None and profile.email_is_verified=True
def send_newsletter(user, sender, filename, title, target='', create_table_update=True, context={}, runner=None, cc=''):
	if target == '':
		target = user.email
	if not models.is_email_correct(target):
		models.send_panic_email(
			'Target email is invalid',
			'editor.views_mail: send_newsletter with user {}, runner {}: Email {} provided is bad.'.format(
				user, runner, target)
		)

	if user and create_table_update:
		profile = user.user_profile
		table_update = models.Table_update.objects.create(model_name=profile.__class__.__name__,
			row_id=profile.id, action_type=models.ACTION_NEWSLETTER_SEND, user=sender)
	else:
		table_update = None
	context['page_title'] = title
	context.update(get_context_for_user_letter(user=user, runner=runner))
	message_from_site = models.Message_from_site.objects.create(
		message_type=models.MESSAGE_TYPE_NEWSLETTER,
		target_email=target,
		# target_email='alexey.chernov@gmail.com',
		cc=cc,
		table_update=table_update,
		title=title,
		body=render_to_string('letters/' + filename + '.txt', context),
		body_html=render_to_string('letters/' + filename + '.html', context),
		created_by=sender,
	)
	return message_from_site.try_send()

def send_newsletters(filename, title, test_mode, pk_from=None):
	sender = models.USER_ADMIN
	target = ''
	users = User.objects.none()
	if test_mode:
		print('I am in test mode.')
		users = User.objects.filter(pk=1)
		# users = User.objects.filter(pk=9) # Куров
		target = 'alexey.chernov@gmail.com'
		# target = 'info@probeg.org'
		# target = 'angladkov@mail.ru'
	else:
		# users = User.objects.exclude(email='').select_related('user_profile').filter(
		# 	is_active=True, user_profile__email_is_verified=True, user_profile__ok_to_send_news=True).order_by('pk')
		if pk_from:
			users = users.filter(pk__gte=pk_from)
	n_messages_sent = 0
	user_errors = []
	for user in users:
	# for user in users[1:]: # To everybody else
	# for user in users[:1]: # Only to alexey.chernov@gmail.com
		res = send_newsletter(user, sender, filename, title=title, target=target)
		if res['success']:
			n_messages_sent += 1
			if (n_messages_sent % 50) == 0:
				print(n_messages_sent, user.id)
		else:
			user_errors.append((user.id, res['error']))
		time.sleep(6)
	print('Messages sent:', n_messages_sent)
	if user_errors:
		print(f'Errors (total {len(user_errors)}):')
		print(user_errors)

def send_to_klb_participants(filename, title): #=u'ПроБЕГ: Новости за январь-2017'):
	sender = models.USER_ADMIN
	klb_participants = models.Klb_participant.objects.filter(year=2018).exclude(email='').select_related(
		'klb_person__runner__user__user_profile').order_by('pk')
	# klb_participants = klb_participants.filter(klb_person__runner__user_id=9)
	print('Number of participants:', klb_participants.count())
	used_emails = set()
	n_messages_sent = 0
	user_errors = []
	for participant in klb_participants:
		if participant.email in used_emails:
			continue
		used_emails.add(participant.email)

		user = None
		if participant.klb_person.runner.user and hasattr(participant.klb_person.runner.user, 'user_profile'):
			user = participant.klb_person.runner.user

		res = send_newsletter(user, sender, filename, title=title, target=participant.email, create_table_update=(user is not None))
		# res = send_newsletter(user, sender, filename, title=title, target='info@probeg.org', create_table_update=(user is not None))
		if res['success']:
			n_messages_sent += 1
			if (n_messages_sent % 50) == 0:
				print(n_messages_sent)
		else:
			user_errors.append((participant.id, res['error']))
	print('Messages sent:', n_messages_sent)
	if user_errors:
		print('Errors (total {}):'.format(len(user_errors)))
		print(user_errors)

FORMAT_HTML = 0
FORMAT_TXT = 1
@views_common.group_required('admins')
def show_newsletter(request, user_id, filename, format_type=FORMAT_HTML):
	user = get_object_or_404(User, pk=user_id)
	sender = models.USER_ADMIN
	template = 'letters/' + filename + ('.txt' if format_type == FORMAT_TXT else '.html')
	context = get_context_for_user_letter(user=user)
	context['start_tags'] = '<html><body><pre>'
	context['finish_tags'] = '</pre></body></html>'
	target = request.GET.get('target')
	if target:
		title = 'ПроБЕГ: Новости за январь-2017'
		result = send_newsletter(user, sender, filename, title=title, target=target, context=context)
		if result['success']:
			messages.success(request, 'Отправлено писем: {}'.format(result['success']))
		else:
			messages.warning(request, 'Ошибка при отправке письма: {}'.format(result['error']))
	return render(request, template, context)

@views_common.group_required('admins')
def show_newsletter_txt(request, user_id, filename):
	return show_newsletter(request, user_id, filename, format_type=FORMAT_TXT)

def send_old_messages(id_from): # When some messages weren't sent due to some bug on the server
	n_sent = 0
	n_errors = 0
	for message in list(models.Message_from_site.objects.filter(is_sent=False, pk__gte=id_from).order_by('pk')):
		res = message.try_send()
		print(('{} {} {}'.format(message.id, message.target_email, res['success'])))
		time.sleep(3)
		if res['success']:
			n_sent += 1
		else:
			n_errors += 1
	print(f'Done! Messages sent: {n_sent}, errors: {n_errors}')

@views_common.group_required('admins')
def emails_for_newsletter(request): # Emails of all users that are OK to receive newsletters.
	emails = set(User.objects.filter(is_active=True, user_profile__ok_to_send_news=True).values_list('email', flat=True))
	return HttpResponse('<html><body>' + '<br/>'.join(sorted(emails)) + '</body></html>')
