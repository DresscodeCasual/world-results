from django.conf import settings
from django.shortcuts import get_object_or_404, render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib import messages
from django.http import Http404
from django.urls import reverse

import datetime
from typing import Optional

from results import models, models_klb, forms, results_util
from . import views_common
from editor import runner_stat
from editor.views import views_result, views_user_actions
from starrating.utils.show_rating import annotate_user_results_with_sr_data

@login_required
def home(request):
	user = request.user
	profile = models.User_profile.objects.filter(user=user).first()
	if (profile is None) or (user.email == '') or (not profile.email_is_verified):
		return my_details(request)
	return user_details(request, user_id=request.user.id)

def user_details_full(request, user_id):
	return user_details(request, user_id, show_full_page=True)

def user_details(request, user_id, series_id=None, club_id=None, show_full_page=False):
	user = get_object_or_404(User, pk=user_id)
	context = views_common.user_edit_vars(request.user)
	if (not user.is_active) and not context['is_admin']:
		raise Http404()
	profile, profile_just_created = models.User_profile.objects.get_or_create(user=user)
	frmClubsEditor = forms.ClubsEditorForm(user=user)

	if club_id:
		if context['is_admin']:
			club = get_object_or_404(models.Club, pk=club_id)
			club_editor = user.club_editor_set.filter(club=club).first()
			if club_editor:
				club_editor.delete()
				messages.success(request, f'У пользователя {user.get_full_name()} отобраны права редактора на клуб «{club.name}».')
				return redirect(profile)
			else:
				messages.warning(request, f'У пользователя {user.get_full_name()} уже не было прав редактора на клуб «{club.name}».')
		else:
			messages.warning(request, 'У Вас нет прав на это действие.')
	elif 'frmClubsEditor_submit' in request.POST:
		if context['is_admin']:
			frmClubsEditor = forms.ClubsEditorForm(request.POST, user=user)
			if frmClubsEditor.is_valid():
				club = frmClubsEditor.cleaned_data['club']
				if user.club_editor_set.filter(club=club).exists():
					messages.warning(request, f'У пользователя {user.get_full_name()} уже есть права редактора на клуб «{club.name}».')
				else:
					models.Club_editor.objects.create(club=club, user=user, added_by=request.user)
					messages.success(request, f'Пользователю {user.get_full_name()} добавлены права редактора на клуб «{club.name}».')
					return redirect(profile)
			else:
				messages.warning(request, 'Права не добавлены. Пожалуйста, исправьте ошибки в форме.')
		else:
			messages.warning(request, 'У Вас нет прав на это действие.')

	context['user'] = user
	context['profile'] = profile
	if hasattr(user, 'runner'):
		context['runner'] = runner = user.runner
		context.update(views_common.get_lists_for_club_membership(request.user, user.runner, context['is_admin']))
		context.update(views_common.get_dict_for_klb_participations_block(user.runner, context['is_admin']))

		if (runner.last_find_results_try is None) or (runner.last_find_results_try < datetime.date.today() - datetime.timedelta(days=7)):
			context['n_possible_results'] = len(runner.get_possible_results())
		else:
			context['n_possible_results'] = runner.n_possible_results

	context.update(views_common.get_filtered_results_dict(
			request=request,
			user=user,
			has_many_distances=profile.has_many_distances,
			is_in_klb='klb_person' in context,
			series_id=series_id,
			show_full_page=show_full_page,
		))

	context['user_is_admin'] = models.is_admin(user)
	context['is_user_homepage'] = request.user.is_authenticated and (user == request.user)
	context['page_title'] = user.get_full_name()
	context['series_to_edit'] = user.series_to_edit_set.order_by('name')
	context['frmClubsEditor'] = frmClubsEditor
	context['calendar'] = user.calendar_set.filter(event__start_date__gte=datetime.date.today()).select_related(
		'event', 'race__distance').order_by('event__start_date')
	context['cur_stat_year'] = results_util.CUR_YEAR_FOR_RUNNER_STATS
	context['cur_year'] = datetime.date.today().year
	context['SITE_URL'] = results_util.SITE_URL

	if context['is_admin'] or context['is_user_homepage']:
		context['unclaimed_results'] = user.unclaimed_result_set.select_related('result__race__event', 'result__race__distance').order_by(
			'-result__race__event__start_date')

	# Adding info on how the user have rated the race
	context['results'] = annotate_user_results_with_sr_data(context['results'], context['to_show_rating'])

	return render(request, 'results/user_details.html', context)

@login_required
def planned_events(request, user_id: Optional[int]=None):
	context = views_common.user_edit_vars(request.user)
	if user_id and context['is_admin']:
		user = get_object_or_404(User, pk=user_id)
		gender = user.user_profile.gender
		context['page_title'] = f'Все забеги, которые {user.get_full_name()} добавлял{"а" if gender == results_util.GENDER_FEMALE else ""} в календарь'
	else:
		user = request.user
		context['page_title'] = 'Все забеги, которые Вы добавляли в календарь'
	
	results = user.result_set.select_related('race')
	race_dict = {}
	event_dict = {}
	# We don't want exceptions if there are several results on one event or race, so we just leave one result per race/event.
	for result in results:
		race_dict[result.race_id] = result
		event_dict[result.race.event_id] = result

	calendar = user.calendar_set.select_related('event', 'race__distance').order_by('event__start_date')
	context['calendar_and_results'] = []
	for item in calendar:
		result = None
		if item.race:
			result = race_dict.get(item.race_id)
		if not result:
			result = event_dict.get(item.event_id)
		context['calendar_and_results'].append((item, result))
	return render(request, 'results/user_planned_events.html', context)

def is_result_good_for_klb(result, participant_set):
	if participant_set and (result.get_klb_status() == models.KLB_STATUS_OK) and not hasattr(result, 'klb_result'):
		race = result.race
		race_date = race.start_date if race.start_date else race.event.start_date
		participant = participant_set.filter(year=models_klb.first_match_year(race_date.year)).first()
		if participant and ( (participant.date_registered is None) or (participant.date_registered <= race_date) ) \
				and ( (participant.date_removed is None) or (participant.date_removed >= race_date) ):
			return True, participant
	return False, None

def try_claim_results(request, runner, is_admin):
	results_claimed = 0
	results_for_klbmatch = 0
	results_errors = 0
	results_unclaimed = 0

	user = runner.user
	person = None
	participant_set = None
	if runner.klb_person:
		person = runner.klb_person
		active_klb_years = [models_klb.CUR_KLB_YEAR]
		if models_klb.NEXT_KLB_YEAR_AVAILABLE_FOR_ALL or is_admin:
			active_klb_years.append(models_klb.NEXT_KLB_YEAR)
		participant_set = person.klb_participant_set.filter(was_deleted_from_team=False, year__in=active_klb_years)

	for key, val in list(request.POST.items()):
		if key.startswith("claim_"):
			result_id = results_util.int_safe(key[len("claim_"):])
			result = models.Result.objects.filter(id=result_id, user=None).first()
			if result is None:
				continue

			is_for_klb, participant = is_result_good_for_klb(result, participant_set)
			year = None
			if is_for_klb:
				year = result.race.event.start_date.year
				if not models.is_active_klb_year(year, is_admin):
					is_for_klb = False
			res, msgError = result.claim_for_runner(request.user, runner, comment='Со страницы "Поискать результаты"',
				# is_for_klb=is_for_klb,
				allow_merging_runners=True)
			if res:
				results_claimed += 1
				if is_for_klb:
					results_for_klbmatch += 1
				if (result.source == models.RESULT_SOURCE_DEFAULT) and (result.place_gender == 1):
					views_result.fill_race_headers(result.race)
			else:
				results_errors += 1
				if msgError:
					messages.warning(request, msgError)
		elif key.startswith("unclaim_forever_"):
			result_id = results_util.int_safe(key[len("unclaim_forever_"):])
			result = models.Result.objects.filter(id=result_id, user__isnull=True).first()
			if result:
				if not user.unclaimed_result_set.filter(result=result).exists():
					models.Unclaimed_result.objects.create(user=user, runner=runner, result=result, added_by=request.user)
					results_unclaimed += 1
	return results_claimed, results_for_klbmatch, results_unclaimed, results_errors

@login_required
def find_results(request, user_id=None, runner_id=None):
	context: dict[str, any] = views_common.user_edit_vars(request.user)
	user = None
	runner = None
	profile = None

	if context['is_admin'] and user_id:
		user = get_object_or_404(User, pk=user_id)
		context['user_id'] = user_id
		person_name = 'Пользователю {}'.format(user.get_full_name())
		profile = user.user_profile
	elif context['is_admin'] and runner_id:
		runner = get_object_or_404(models.Runner, pk=runner_id)
		context['runner_id'] = runner_id
		person_name = 'Бегуну {}'.format(runner.name())
		if runner.user:
			profile = runner.user.user_profile
	else:
		user = request.user
		person_name = 'Вам'
		profile = user.user_profile

	if runner is None:
		if not hasattr(user, 'runner'):
			messages.warning(request, 'У пользователя {} (id {}) нет бегуна. За таких нельзя искать результаты.'.format(
				user.get_full_name(), user.id))  # pytype: disable=attribute-error
			profile, profile_just_created = models.User_profile.objects.get_or_create(user=user)
			return redirect(profile)
		runner = user.runner
	context['user'] = user
	context['runner'] = runner

	if 'frmResults_claim' in request.POST:
		results_claimed, results_for_klbmatch, results_unclaimed, results_errors = try_claim_results(request, runner, context['is_admin'])
		if results_claimed > 0:
			runner.refresh_from_db()
			runner_stat.update_runner_stat(runner=runner)
			if runner.user:
				runner_stat.update_runner_stat(user=runner.user, update_club_members=False)
			messages.success(request, '{} добавлен{} {} результат{}'.format(person_name, results_util.ending(results_claimed, 17),
				results_claimed, results_util.ending(results_claimed, 1)))
		if results_for_klbmatch > 0:
			messages.success(request, f'В том числе отправлено на модерацию в КЛБМатч: {results_for_klbmatch}')
		if results_unclaimed > 0:
			messages.success(request, f'Больше не будем показывать Вам результатов Ваших тёзок: {results_unclaimed}')
		if results_errors > 0:
			messages.warning(request, f'Возникли ошибки c {results_errors} результатами. Редакторы уже знают о проблеме.')
		if results_claimed + results_unclaimed > 0:
			runner.get_possible_results()

		if user_id:
			return redirect('results:user_details', user_id=user_id)
		if runner_id:
			return redirect(runner)
		return redirect('results:home')
	else:
		runner.last_find_results_try = datetime.date.today()
		runner.save()

	context['names'] = runner.extra_name_set.all()
	context['results'] = runner.get_possible_results()
	if runner.klb_person:
		person = runner.klb_person
		if person.klb_participant_set.filter(year__in=(models_klb.CUR_KLB_YEAR, models_klb.NEXT_KLB_YEAR)).exists():
			participant_set = person.klb_participant_set
			context['result_for_klb_ids'] = set()
			for result in context['results']:
				if (result.get_klb_status() == models.KLB_STATUS_OK) and (not hasattr(result, 'klb_result')) \
						and participant_set.filter(year=result.race.event.start_date.year).exists():
					event_date = result.race.event.start_date
					participant = participant_set.filter(year=event_date.year).first()
					if ( (participant.date_registered is None) or (participant.date_registered <= event_date) ) \
							and ( (participant.date_removed is None) or (participant.date_removed >= event_date) ):
						context['result_for_klb_ids'].add(result.id)
						if participant.team_id:
							context['needs_klb_confirmation'] = True
	context['page_title'] = 'Поиск своих результатов'

	return render(request, 'results/find_results.html', context=context)

@login_required
def send_confirmation_letter(request, user_id=0):
	return my_details(request, user_id=user_id, resend_message=True)

@login_required
def my_details(request, user_id=0, just_registered=False, resend_message=False, frmName=forms.UserNameForm()):
	context = views_common.user_edit_vars(request.user)
	user_id = results_util.int_safe(user_id)
	if context['is_admin'] and user_id:
		user = get_object_or_404(User, pk=user_id)
	else:
		if not request.user.is_active:
			messages.warning(request, 'Этот пользователь отключён. Пожалуйста, попробуйте зайти ещё раз. Если Вы считаете, что эта ошибка, напишите нам на info@probeg.org.')
			return redirect('auth:logout')
		user = request.user
	context['user'] = user
	context['user_id'] = user.id
	message_prefix = ''
	to_redirect = False

	profile, profile_just_created = models.User_profile.objects.get_or_create(user=user, defaults={'gender': models.Runner_name.gender_from_name(user.first_name)})
	context['url_for_update'] = reverse('results:my_details')
	url_to_redirect = reverse('results:my_details')
	if context['is_admin'] and (user != request.user):
		context['url_for_update'] = profile.get_our_editor_url()
		url_to_redirect = profile.get_our_editor_url()
	if (not profile.agrees_with_policy) and (user == request.user):
		url_to_redirect = profile.get_find_results_url()
	if profile_just_created:
		models.log_obj_create(request.user, profile, models.ACTION_CREATE, comment='При регистрации на сайте', verified_by=request.user)
		message_prefix = 'Для завершения регистрации осталось заполнить эту форму и подтвердить свой электронный адрес. '
		if not hasattr(request.user, 'runner'):
			profile.create_runner(request.user, comment='При регистрации пользователя')
			user.refresh_from_db()
		if user.email:
			resend_message = True
	if user.is_active and not hasattr(user, 'runner'):
		profile.create_runner(user, comment='На странице my_details')
		models.send_panic_email(
			'Active user had no runner',
			f'User {user} (id {user.id}) had no runner. We have just created one.'
		)
		# We reload the user so that she gets her runner
		user = User.objects.get(pk=user.id)

	if 'frmProfile_submit' in request.POST:
		form = forms.UserProfileForm(request.POST, request.FILES, instance=profile, user=user, city=profile.city)
		if form.is_valid():
			user.first_name = form.cleaned_data['fname'].strip()
			user.last_name = form.cleaned_data['lname'].strip()
			user.email = form.cleaned_data['email'].strip()
			if 'email' in form.changed_data:
				form.instance.email_is_verified = False
				if user.email:
					resend_message = True
				if profile.has_password():
					user.username = user.email
			profile = form.save()
			verified_by = request.user
			if ('lname' in form.changed_data) or ('fname' in form.changed_data) or ('midname' in form.changed_data):
				# In this case admins should check this action.
				verified_by = None
			views_user_actions.log_form_change(request.user, form, action=models.ACTION_UPDATE, exclude=['country', 'region'], verified_by=verified_by)
			user.save()
			if 'avatar' in form.changed_data:
				if not profile.make_thumbnail():
					messages.warning(request, 'Не получилось уменьшить фото для аватара.')

			changed_fields_for_runner = []
			if hasattr(user, 'runner'):
				runner = user.runner
				for field in ['midname', 'gender', 'city_id', 'club_name', 'birthday']:
					if field in form.changed_data:
						setattr(runner, field, getattr(profile, field))
						changed_fields_for_runner.append(field)
				for field in ['lname', 'fname']:
					if field in form.changed_data:
						setattr(runner, field, form.cleaned_data[field].strip())
						changed_fields_for_runner.append(field)
				if ('birthday' in form.changed_data) and not runner.birthday_known:
					runner.birthday = profile.birthday
					runner.birthday_known = (profile.birthday is not None)
					changed_fields_for_runner += ['birthday', 'birthday_known']
				if changed_fields_for_runner:
					runner.save()
					models.log_obj_create(request.user, runner, models.ACTION_UPDATE, field_list=changed_fields_for_runner,
						comment='При правке пользователя', verified_by=request.user)

			messages.success(request, 'Данные сохранены.')
			to_redirect = True
		else:
			messages.warning(request, 'Данные не сохранены. Пожалуйста, исправьте ошибки в форме.')
	else:
		form = forms.UserProfileForm(instance=profile, user=user, city=profile.city)

	if not profile.email_is_verified:
		if resend_message:
			if profile.email_verification_code == '':
				profile.email_verification_code = results_util.generate_verification_code()
				profile.save()
			if models.is_email_correct(user.email):
				res = send_letter_with_code(user, profile)
				if res['success']:
					messages.success(request, message_prefix
						+ 'Письмо для подтверждения электронного адреса отправлено на адрес {}.'.format(user.email))
				else:
					messages.warning(request, (message_prefix
						+ f'К сожалению, письмо на адрес {user.email} отправить не удалось. Мы уже разбираемся'
						+ f' в причинах. Вы можете написать нам на <a href="mailto:{settings.EMAIL_INFO_USER}">{settings.EMAIL_INFO_USER}</a>,'
						+ ' чтобы ускорить решение проблемы.'))
			else:
				messages.warning(request, message_prefix
					+ 'Пожалуйста, укажите корректный электронный адрес. Мы пришлём на него письмо для подтверждения.')
		elif user.email == '':
			messages.warning(request, message_prefix
				+ 'Пожалуйста, укажите Ваш электронный адрес. Мы пришлём на него письмо для подтверждения.')
		else:
			send_link = reverse('results:send_confirmation_letter') if (user_id == 0) else reverse('results:send_confirmation_letter', kwargs={'user_id': user_id})
			messages.warning(request, ('Вы ещё не подтвердили свой электронный адрес. Перейдите по ссылке из присланного Вам '
					+ 'письма, или <a href="{}">закажите ещё одно письмо</a> на адрес {}, или измените свой адрес.').format(
				send_link, user.email))

	if to_redirect:
		return redirect(url_to_redirect)

	context['frmProfile'] = form
	context['profile'] = profile

	name_for_title = (user.first_name + " " + user.last_name) if user.last_name else 'Следующий шаг:'
	context['page_title'] = name_for_title + ': личные данные'

	if (not profile_just_created) and (not user_id):
		context['showNames'] = True
		context['names'] = user.runner.extra_name_set.order_by('lname', 'fname', 'midname')
		context['frmName'] = frmName

	return render(request, "results/my_details.html", context)

@login_required
def my_strava_links(request, user_id=None):
	context: dict[str, any] = views_common.user_edit_vars(request.user)
	user_id = results_util.int_safe(user_id)
	if context['is_admin'] and user_id:
		user = get_object_or_404(User, pk=user_id)
		context['page_title'] = f'Ссылки на забеги в Strava и Garmin у пользователя {user.get_full_name()}'
	else:
		user = request.user
		context['page_title'] = 'Ссылки на ваши забеги в Strava и Garmin'
	context['user'] = user
	context['user_id'] = user.id
	results_data = {}

	if 'btnStravaLinks' in request.POST:
		results = user.result_set.select_related('result_on_strava')
		for result in results:
			data = {}
			strava_link = request.POST.get(f'strava_for_{result.id}', '')
			result_on_strava = result.result_on_strava if hasattr(result, 'result_on_strava') else None
			if strava_link:
				data['link'] = strava_link
				tracker_number, tracker, is_private_activity = results_util.maybe_strava_activity_number(strava_link)
				if tracker_number:
					if result_on_strava and (result_on_strava.link != tracker_number):
						result_on_strava.link = tracker_number
						result_on_strava.tracker = tracker
						result_on_strava.save()
						models.log_obj_create(user, result_on_strava, models.ACTION_UPDATE, field_list=['link'],
							comment='При обновлении всех ссылок сразу', verified_by=request.user)
						data['is_saved'] = True
					elif result_on_strava is None:
						result_on_strava = models.Result_on_strava.objects.create(
							result=result,
							link=tracker_number,
							tracker=tracker,
							added_by=request.user,
						)
						models.log_obj_create(user, result_on_strava, models.ACTION_CREATE, comment='При обновлении всех ссылок сразу', verified_by=request.user)
						data['is_saved'] = True
					data['link'] = str(result_on_strava)
				else:
					data['error'] = True
					if is_private_activity:
						messages.warning(request,
							f'Похоже, ссылка {strava_link} ведёт на тренировку, доступную только зарегистрированным пользователям Стравы.')
						messages.warning(request,
							'Мы не смогли её обработать. Если вы всё равно хотите её добавить, откройте тренировку в браузере и скопируйте оттуда —')
						messages.warning(request, 'ссылка должна иметь вид https://strava.com/activities/...')
					else:
						user_url = user.user_profile.get_absolute_url() if hasattr(user, 'user_profile') else ''
						models.send_panic_email('Incorrect Strava link', '{} {}{} tried to add Strava link {} to race {}{}'.format(
							user.get_full_name(), results_util.SITE_URL, user_url, strava_link, results_util.SITE_URL, result.race.get_absolute_url()))
			else:
				if result_on_strava:
					models.log_obj_create(user, result_on_strava, models.ACTION_DELETE, comment='При обновлении всех ссылок сразу', verified_by=request.user)
					result_on_strava.delete()
					data['is_removed'] = True
			results_data[result] = data
		messages.success(request, 'Введённые данные обработаны')

	context['results'] = []
	for result in views_common.add_race_dependent_attrs(user.result_set).order_by('-race__event__start_date'):
		if result in results_data: # So we've just worked with it, nothing else is needed in dict
			context['results'].append((result, results_data[result]))
		elif hasattr(result, 'result_on_strava'):
			context['results'].append((result, {'link': str(result.result_on_strava)}))
		else:
			context['results'].append((result, {}))

	return render(request, "results/user_strava_links.html", context)

@login_required
def my_name_add(request):
	user = request.user
	runner = user.runner
	extra_name = models.Extra_name(runner=runner, added_by=request.user)
	if 'frmName_submit' in request.POST:
		form = forms.UserNameForm(request.POST, instance=extra_name)
		if form.is_valid():
			form.save()
			views_user_actions.log_form_change(user, form, action=models.ACTION_CREATE)
			messages.success(request, 'Новое имя успешно добавлено')
			return redirect('results:my_details')
		else:
			messages.warning(request, 'Данные для нового имени указаны с ошибкой. Пожалуйста, исправьте ошибки в форме.')
	else:
		form = forms.UserNameForm()
	return my_details(request, frmName=form)

@login_required
def my_name_delete(request, name_id):
	name = models.Extra_name.objects.filter(pk=name_id, runner=request.user.runner).first()
	if name:
		models.log_obj_create(request.user, name, models.ACTION_DELETE, comment='Удалено пользователем со своей страницы')
		name.delete()
		messages.success(request, 'Имя успешно удалено.')
		return redirect('results:my_details')
	else:
		messages.warning(request, 'Имя для удаления не найдено. Ничего не удалено.')
		return my_details(request)

@login_required
def verify_email(request, code):
	user = request.user
	profile = user.user_profile
	if profile is None:
		messages.warning(request, 'Что-то пошло не так. Пожалуйста, пройдите по ссылке из письма ещё раз, или напишите нам.')
		return redirect('results:my_details')
	if profile.email_is_verified:
		messages.success(request, 'Ваш почтовый адрес уже был подтверждён раньше, всё в порядке!')
		return redirect('results:my_details')
	if code == profile.email_verification_code:
		profile.email_is_verified = True
		profile.email_verification_code = ''
		profile.save()
		messages.success(request, 'Ваш почтовый адрес {} успешно подтверждён. Теперь Вам доступны все возможности сайта!'.format(
			user.email))
		return redirect('results:my_details')
	else:
		messages.warning(request, ('Вы указали неверный код авторизации. Попробуйте ещё раз перейти по ссылке, '
					+ 'или <a href="{}">закажите ещё одно письмо</a> на адрес {}, или измените почтовый адрес.').format(
			reverse('results:send_confirmation_letter'), user.email))
		return redirect('results:my_details')

def send_letter_with_code(user, profile):
	link = reverse('results:verify_email', kwargs={'code': profile.email_verification_code})
	message_from_site = models.Message_from_site.objects.create(
		message_type=models.MESSAGE_TYPE_CONFIRM_EMAIL,
		title='World Results: Confirm your email',
		body=(f'Hello,\n\nSomeone – maybe you – entered your email address {user.email} at {results_util.SITE_URL}. '
			+ '\nIf it was you, please click the link below to confirm that.'
			+ f'Otherwise, please ignore this letter.\n\nConfirmation link: {results_util.SITE_URL}{link}'
			+ '\n\n---\nRegards,\nThe "World Results" team'),
		target_email=user.email,
		created_by=user,
		)
	return message_from_site.try_send()

def get_avatar_page(request, user_id):
	user = get_object_or_404(User, pk=user_id)
	context = {}
	context['image_url'] = user.user_profile.get_avatar_url()
	return render(request, "results/modal_image.html", context)

def unsubscribe(request, user_id, unsubscribe_code, email_type):
	# TODO
	name = models.Extra_name.objects.filter(pk=user_id, runner=request.user.runner).first()
	if name:
		models.log_obj_create(request.user, name, models.ACTION_DELETE, comment='Удалено пользователем со своей страницы')
		name.delete()
		messages.success(request, 'Имя успешно удалено.')
		return redirect('results:my_details')
	else:
		messages.warning(request, 'Имя для удаления не найдено. Ничего не удалено.')
		return my_details(request)
