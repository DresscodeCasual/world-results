from django.shortcuts import get_object_or_404, render, redirect
from django.contrib.auth.decorators import login_required
from django.forms import formset_factory
from django.contrib import messages
from django.db.models import Q

import decimal
import math
from typing import Dict, List, Tuple

from results import models, models_klb
from results.views.views_common import user_edit_vars
from editor import forms, runner_stat
from . import views_klb
from .views_common import group_required
from .views_klb_stat import update_persons_score

COMPARED_BY_NOTHING = 0
COMPARED_BY_AGE = 1
COMPARED_BY_BIRTHYEAR = 2
COMPARED_BY_BIRTHDAY = 3

COMPARED_TYPES = (
	(COMPARED_BY_NOTHING, 'только&nbsp;имя'),
	(COMPARED_BY_AGE, 'примерный возраст'),
	(COMPARED_BY_BIRTHYEAR, 'год рождения'),
	(COMPARED_BY_BIRTHDAY, 'день рождения'),
)

MIN_RESULTS_TO_USE_PAGES = 501
RESULTS_PER_PAGE = 500

def get_pages_number(n_results):
	return int(math.ceil(n_results / RESULTS_PER_PAGE))

def check_distance_and_result(request, distance, person, result, year):
	if (distance.distance_type == models.TYPE_MINUTES_RUN) and (result.result < models_klb.get_min_distance_for_bonus(year)):
		messages.warning(request, 'Результат бегуна {} {}, {}, слишком мал для КЛБМатча. Пропускаем'.format(person.fname, person.lname, result))
		return False
	return True

def check_results_with_same_time(request, race, event, person, result, panic_on_error=False):
	if person.klb_result_set.filter(race=race).exists():
		error = f'У участника {result.fname} {result.lname} (id {person.id}) уже есть учтенный в Матче результат на этом старте. Не учитываем в Матче'
		messages.warning(request, error)
		if panic_on_error:
			models.send_panic_email(
				'Problem in check_results_with_same_time',
				'Problem occured when user {} (id {}) tried to add result {} to KLB person {}. Error: {}.'.format(
					request.user.get_full_name(), request.user.id, result.id, person.id, error)
			)
		return False
	if person.klb_result_set.filter(race__event=event, race__start_date=race.start_date, race__start_time=race.start_time).exists():
		error = 'У участника {} {} (id {}) уже есть учтенный в Матче результат в этом забеге с тем же временем старта. Не учитываем в Матче'.format(
			result.fname, result.lname, person.id)
		messages.warning(request, error)
		if panic_on_error:
			models.send_panic_email(
				'Problem in check_results_with_same_time',
				'Problem occured when user {} (id {}) tried to add result {} to KLB person {}. Error: {}.'.format(
					request.user.get_full_name(), request.user.id, result.id, person.id, error)
			)
		return False
	return True

def get_runner_ids_for_result(result):
	result_name_condition = Q(lname=result.lname, fname=result.fname) | Q(lname=result.fname, fname=result.lname)
	runners_for_result = models.Runner.objects.filter(result_name_condition)
	extra_names_for_result = models.Extra_name.objects.filter(result_name_condition)
	if result.midname:
		runners_for_result = runners_for_result.filter(midname__in=('', result.midname))
		extra_names_for_result = extra_names_for_result.filter(midname__in=('', result.midname))

	return set(runners_for_result.values_list('id', flat=True)) | set(extra_names_for_result.values_list('runner_id', flat=True))

@group_required('admins')
def klb_race_details(request, race_id, page=0):
	race = get_object_or_404(models.Race, pk=race_id)
	event = race.event
	year = event.start_date.year
	if not models.is_active_klb_year(year):
		messages.warning(request, f'Вы уже не можете изменять результаты забега {year} года. Тот матч давно в прошлом.')
		return redirect(race)
	user = request.user
	context = {}
	context['race'] = race
	context['event'] = event
	context['results_in_klb'] = 0
	context['results_to_add'] = 0
	context['results_errors'] = 0
	context['page_title'] = f'{race.name_with_event()}: результаты забега для КЛБМатча'
	if race.distance_real and (race.distance_real.length < race.distance.length):
		distance = race.distance_real
	else:
		distance = race.distance
	context['distance'] = distance

	official_results = race.result_set.filter(source=models.RESULT_SOURCE_DEFAULT, status=models.STATUS_FINISHED).select_related('runner').order_by(
		'lname', 'fname', 'pk')
	n_official_results = official_results.count()

	if models.Klb_result.objects.filter(race=race, result=None).exists():
		context['hasUnboundResults'] = 1
		return render(request, 'editor/klb/race_details.html', context)
	if n_official_results and race.get_unofficial_results().exists():
		context['hasOffAndUnoffResults'] = 1
		return render(request, 'editor/klb/race_details.html', context)
	results = []
	race_date = race.start_date if race.start_date else event.start_date
	klb_participant_ids = set(models.Klb_participant.objects.filter(
			Q(date_registered=None) | Q(date_registered__lte=race_date),
			Q(date_removed=None) | Q(date_removed__gte=race_date),
			was_deleted_from_team=False, year=models_klb.first_match_year(year),
		).values_list('klb_person__id', flat=True))
	has_results_to_work = False
	event_person_ids = set(models.Klb_result.objects.filter(
		race__event=event, race__start_date=race.start_date, race__start_time=race.start_time).values_list('klb_person_id', flat=True))

	if n_official_results >= MIN_RESULTS_TO_USE_PAGES:
		context['using_pages'] = True
		pages_number = get_pages_number(n_official_results)
		context['pages'] = list(range(pages_number))
		page = results_util.int_safe(page)
		context['page'] = page
		official_results = list(official_results[(page * RESULTS_PER_PAGE):((page + 1) * RESULTS_PER_PAGE)])
		context['n_results_on_cur_page'] = RESULTS_PER_PAGE if (n_official_results >= (page + 1) * RESULTS_PER_PAGE) \
			else n_official_results - page * RESULTS_PER_PAGE
		context['first_lname'] = official_results[0].lname
		context['last_lname'] = official_results[-1].lname
	else:
		context['using_pages'] = False

	for result in official_results:
		errors = []
		person = None
		candidates = []
		compared_type = COMPARED_BY_NOTHING
		has_checkboxes = False
		value_for_order = 0
		if hasattr(result, 'klb_result'):
			context['results_in_klb'] += 1
		elif (distance.distance_type == models.TYPE_MINUTES_RUN) and (result.result < models_klb.get_min_distance_for_bonus(year)):
			errors.append('Результат слишком мал для КЛБМатча.')
		else: # Let's try to find person in KLBmatch for this result
			value_for_order = 10

			persons = models.Klb_person.objects.filter(
					pk__in=klb_participant_ids,
					runner__id__in=get_runner_ids_for_result(result),
					# lname=result.lname,
					# fname=result.fname
				).select_related('city__region__country', 'runner__user__user_profile')
			if result.birthday:
				if result.birthday_known:
					persons = persons.filter(birthday=result.birthday)
					compared_type = COMPARED_BY_BIRTHDAY
				else:
					persons = persons.filter(birthday__year=result.birthday.year)
					compared_type = COMPARED_BY_BIRTHYEAR
			elif result.age:
				birthyear_around = year - result.age
				persons = persons.filter(birthday__year__range=(birthyear_around - 1, birthyear_around + 1))
				compared_type = COMPARED_BY_AGE
			if not persons.exists():
				continue
			value_for_order += compared_type
			for person in persons:
				has_results_to_work = True
				candidate_errors = []
				candidate_comments = []
				show_checkbox = True
				team = person.get_team(year)
				club = team.club if team else None
				correct_club_in_protocol = False
				if person.id in event_person_ids:
					candidate_errors.append('У этого участника КЛБМатча уже есть зачтенный результат в этом забеге с тем же временем старта')
					show_checkbox = False
				if club and result.club_name:
					club_name_found = False
					for club_name in [club.name, team.name] + list(club.club_name_set.values_list('name', flat=True)):
						if club_name.lower()[:6] in result.club_name.lower():
							club_name_found = True
							correct_club_in_protocol = True
							candidate_comments.append('Клуб указан в протоколе')
							value_for_order += 5
							break
					if not club_name_found:
						klb_participant = person.get_participant(year)
						user_set_correct_club, user_club, club_name_last_changed = klb_participant.did_user_set_correct_club(event.start_date)
						if user_set_correct_club:
							candidate_comments.append(f'Пользователь указал в профиле клуб {user_club}')
							club_name_found = True
						elif club_name_last_changed and (club_name_last_changed > event.start_date):
							candidate_comments.append(f'Пользователь указал в профиле клуб {user_club}, но только {club_name_last_changed}')
					if not club_name_found:
						candidate_errors.append('Клуб бегуна противоречит протоколу')
				runner = result.runner
				if runner:
					if runner.klb_person_id and (runner.klb_person_id != person.id):
						candidate_errors.append(f'В БД результатов указан другой бегун – с id {runner.klb_person_id}')
						show_checkbox = False
					elif (runner.klb_person_id is None) and hasattr(person, 'runner') and person.runner.klb_person_id:
						candidate_errors.append('К результату уже привязан другой бегун')
						show_checkbox = False
				if result.bib_given_to_unknown:
					candidate_errors.append('С этим номером бежал кто-то другой, не знаем, кто')
					show_checkbox = False
				if show_checkbox:
					has_checkboxes = True
				candidates.append({
					'person': person,
					'errors': candidate_errors,
					'comments': candidate_comments,
					'show_checkbox': show_checkbox,
					'team': team,
					'club': club,
				})
			if has_checkboxes:
				context['results_to_add'] += 1
		if hasattr(result, 'klb_result') or candidates or errors:
			results.append({
				'result': result,
				'candidates': candidates,
				'errors': errors,
				'value_for_order': value_for_order,
				'checked_by_default': (len(candidates) == 1) and (not candidates[0]['errors'])
					and ( (correct_club_in_protocol and team) or (compared_type >= COMPARED_BY_BIRTHYEAR) ),
				'compared_type': COMPARED_TYPES[compared_type][1],
				'has_checkboxes': has_checkboxes,
			})
		if errors:
			context['results_errors'] += 1
	if (not has_results_to_work) and (not race.was_checked_for_klb) and ( (not context['using_pages']) or (page == pages_number - 1) ):
		race.was_checked_for_klb = True
		race.save()
		models.log_obj_create(user, event, models.ACTION_RACE_UPDATE, field_list=['was_checked_for_klb'], child_object=race)
		context['just_checked'] = 1
	context['results'] = sorted(results, key=lambda x:-x['value_for_order'])
	context['results_total'] = n_official_results
	context['results_unbound'] = race.klb_result_set.filter(result=None)
	context['races'] = event.race_set.select_related('distance').order_by('distance__distance_type', '-distance__length')
	context['KLB_STATUS_OK'] = models.KLB_STATUS_OK
	return render(request, 'editor/klb/race_details.html', context)

@group_required('admins')
def klb_race_process(request, race_id=None):
	race = get_object_or_404(models.Race, pk=race_id)
	event = race.event
	year = event.start_date.year
	match_year = models_klb.first_match_year(year)
	user = request.user
	distance, was_real_distance_used = race.get_distance_and_flag_for_klb()
	page = None
	target = redirect(race.get_klb_editor_url(page=page))
	if models.Klb_result.objects.filter(race=race, result=None).exists():
		messages.warning(request, 'На этой дистанции есть результаты, проведённые в КЛБМатч, но не привязанные к загруженным результатам.')
		return target
	if request.method != 'POST':
		return target
	
	results_added = 0
	results_deleted = 0
	results_errors = 0
	touched_persons = set()
	touched_persons_by_team : Dict[models.Klb_team, List[Tuple[models.Klb_person, decimal.Decimal, decimal.Decimal]]] = {}
	page = results_util.int_safe(request.POST.get('page', 0))
	pages_number = get_pages_number(race.result_set.filter(source=models.RESULT_SOURCE_DEFAULT, status=models.STATUS_FINISHED).count())
	only_bonus_score = 'only_bonus_score' in request.POST
	for key, val in list(request.POST.items()):
		if key.startswith("person_for_"):
			person_id = results_util.int_safe(val)
			if person_id == 0:
				continue
			result_id = results_util.int_safe(key[len("person_for_"):])
			result = models.Result.objects.filter(race=race, id=result_id, klb_result=None).first()
			if result is None:
				messages.warning(request, 'Результат с id {} не найден. Пропускаем'.format(result_id))
				continue
			if hasattr(result, 'klb_result'):
				messages.warning(request, 'Результат с id {} уже учтён в КЛБМатче. Пропускаем'.format(result_id))
				continue
			person = models.Klb_person.objects.filter(pk=person_id).first()
			if not person:
				messages.warning(request, '{} {}: участник КЛБМатчей с id {} не найден. Пропускаем'.format(
					result.fname, result.lname, person_id))
				continue
			if not check_results_with_same_time(request, race, event, person, result):
				continue
			# We can have two runners: from result and from person
			if result.runner:
				runner = result.runner
				if hasattr(person, 'runner'):
					if runner != person.runner:
						messages.warning(request, ('{} {}: у результата и участника Матча два разных бегуна, {} и {}. '
							+ 'Сначала объедините их').format(result.fname, result.lname, result.runner, person.runner))
						continue
					# If runner == person.runner, we just do nothing
				elif runner.klb_person_id and (runner.klb_person_id != person.id):
					messages.warning(request, ('{} {}: В БД результатов указан другой бегун – с id {}. Пропускаем').format(
						result.fname, result.lname, runner.klb_person_id))
					continue
				# So result has its runner, person doesn't have, and either runner.klb_person_id = person.id or runner.klb_person_id=None
				if runner.klb_person_id is None:
					runner.klb_person = person
					runner.save()
			# Great! That's time to create KLBResult
			person.refresh_from_db()
			if not check_results_with_same_time(request, race, event, person, result, panic_on_error=True):
				continue
			klb_result = views_klb.create_klb_result(result, person, user, distance, was_real_distance_used, only_bonus_score=only_bonus_score,
				comment='Со страницы обработки официальных результатов')
			if klb_result is None:
				results_errors += 1
				continue
			table_update = models.Table_update.objects.filter(
					model_name=event.__class__.__name__,
					row_id=event.id,
					child_id=result.id,
					action_type=models.ACTION_RESULT_UPDATE,
					is_verified=False,
				).first()
			if table_update:
				table_update.verify(request.user, comment='одобрено при обработке старта целиком')
			touched_persons.add(person)
			team = person.get_team(match_year)
			if team:
				if team not in touched_persons_by_team:
					touched_persons_by_team[team] = []
				touched_persons_by_team[team].append((person, 0, klb_result.total_score()))
			results_added += 1
		elif key.startswith("to_delete_"):
			result_id = results_util.int_safe(key[len("to_delete_"):])
			result = models.Result.objects.filter(race=race, id=result_id, klb_result__isnull=False).first()
			if not result:
				messages.warning(request, 'Результат с id {} не найден. Пропускаем'.format(result_id))
				continue
			klb_result = result.klb_result
			touched_persons.add(klb_result.klb_person)
			team = klb_result.get_team()
			if team:
				if team not in touched_persons_by_team:
					touched_persons_by_team[team] = []
				touched_persons_by_team[team].append((klb_result.klb_person, klb_result.total_score(), 0))
			models.log_obj_delete(user, event, child_object=klb_result, action_type=models.ACTION_KLB_RESULT_DELETE)
			klb_result.delete()
			if 'to_unclaim_{}'.format(result_id) in request.POST:
				result.unclaim_from_runner(user)
			results_deleted += 1
	if results_added:
		messages.success(request, 'В КЛБМатч добавлено результатов: {}'.format(results_added))
		race.fill_winners_info()
	if results_deleted:
		messages.success(request, 'Из КЛБМатча удалено результатов: {}'.format(results_deleted))
	if results_errors:
		messages.warning(request, 'Не получилось создать результатов, поскольку у этих людей уже есть результаты на этом старте: {}'.format(results_errors))
	if touched_persons:
		update_persons_score(year=year, persons_to_update=touched_persons, update_runners=True)
		messages.success(request, 'Затронуто участников Матча: {}. Их результаты пересчитаны.'.format(len(touched_persons)))
	if touched_persons_by_team:
		messages.success(request, 'Затронуты команды: {}'.format(', '.join(team.name for team in touched_persons_by_team.keys())))
		views_klb.log_teams_score_changes(race, touched_persons_by_team, 'Обработка всей дистанции в КЛБМатч', user)

	if (not race.was_checked_for_klb) and (page == pages_number - 1):
		race.was_checked_for_klb = True
		race.save()
		models.log_obj_create(user, event, models.ACTION_RACE_UPDATE, field_list=['was_checked_for_klb'], child_object=race)
	return redirect(race.get_klb_editor_url(page=page))

def getKlbResultFormSet(extra, data=None, **kwargs):
	KlbResultFormSet = formset_factory(forms.KlbResultForm, extra=extra)
	return KlbResultFormSet(data=data, form_kwargs=kwargs)

N_PERSONS_DEFAULT = 3
@login_required
def klb_race_add_results(request, race_id):
	race = get_object_or_404(models.Race, pk=race_id)
	event = race.event
	year = event.start_date.year
	match_year = models_klb.first_match_year(year)
	user = request.user
	context = user_edit_vars(user, series=event.series)
	race_is_for_klb = race.get_klb_status() == models.KLB_STATUS_OK
	context['race'] = race
	context['event'] = event
	if race_is_for_klb:
		context['page_title'] = f'{race}: ввод результатов для КЛБМатча'
	else:
		context['page_title'] = f'{race}: ввод отдельных результатов'
	context['race_is_ok_for_klb'] = race_is_for_klb
	context['KLB_STATUS_OK'] = models.KLB_STATUS_OK
	context['user_is_female'] = user.user_profile.is_female()

	club_id = results_util.int_safe(request.POST.get('club', 0))
	if context['is_admin']: # Only admins can add results to individual participants here
		club = models.Club.objects.filter(pk=club_id).first()
	else:
		club = get_object_or_404(models.Club, pk=club_id)

	if (not context['is_admin']) and (club not in user.user_profile.get_club_set_to_add_results()):
		messages.warning(request, 'У Вас нет прав на это действие')
		return redirect(race)

	runners_for_user = user.user_profile.get_runners_to_add_results(race, race_is_for_klb=race_is_for_klb, club=club, for_given_club_only=True)

	n_persons = results_util.int_safe(request.POST.get('n_persons', N_PERSONS_DEFAULT))
	formset_kwargs = {
		'race': race,
		'extra': n_persons,
		'is_admin': context['is_admin'],
		'race_is_for_klb': race_is_for_klb,
		'runner_choices': [('', '(пропускаем)')] + [(runner.id, data['text']) for runner, data in list(runners_for_user.items())],
		'disabled_choices': set(runner.id for runner, data in list(runners_for_user.items()) if data['is_already_in_race']),
	}
	if 'formset_submit' in request.POST:
		formset = getKlbResultFormSet(data=request.POST, **formset_kwargs)
		if formset.is_valid():
			n_results_created = 0
			n_klb_results_created = 0
			touched_persons = set()
			touched_runners = set()
			touched_persons_by_team : Dict[models.Klb_team, List[Tuple[models.Klb_person, decimal.Decimal, decimal.Decimal]]] = {}
			loaded_from = request.POST.get('source', '')
			distance, was_real_distance_used = race.get_distance_and_flag_for_klb()

			for form in formset:
				runner = form.cleaned_data.get('runner')
				if runner:
					if runner not in runners_for_user:
						messages.warning(request, 'Участник забегов {} (id {}) не относится к выбранному клубу. Пропускаем'.format(
							runner.name(), runner.id))
						continue
					result = models.Result.objects.create(
						race=race,
						runner=runner,
						user=runner.user,
						loaded_by=user,
						lname=runner.lname,
						fname=runner.fname,
						source=models.RESULT_SOURCE_USER,
						result=form.cleaned_data['result'],
					)
					touched_runners.add(runner)
					n_results_created += 1
					# And now try to create result for KLBMatch if needed
					will_be_counted_for_klb = False
					only_bonus_score = False
					if race_is_for_klb and runners_for_user[runner]['is_in_klb'] and form.cleaned_data.get('is_for_klb', False):
						person = runner.klb_person
						if person and check_distance_and_result(request, distance, person, result, year) \
								and check_results_with_same_time(request, race, event, person, result):
							if context['is_admin']:
								klb_result = views_klb.create_klb_result(result, person, user, distance, was_real_distance_used,
									only_bonus_score=form.cleaned_data.get('only_bonus_score', False),
									comment='Со страницы добавления отдельных результатов')
								if klb_result:
									touched_persons.add(person)
									team = person.get_team(match_year)
									if team:
										if team not in touched_persons_by_team:
											touched_persons_by_team[team] = []
										touched_persons_by_team[team].append((person, 0, klb_result.total_score()))
							else:
								will_be_counted_for_klb = True
							n_klb_results_created += 1
					models.log_obj_create(user, event, models.ACTION_UNOFF_RESULT_CREATE, child_object=result, is_for_klb=will_be_counted_for_klb)
			if n_results_created:
				if race.load_status == models.RESULTS_NOT_LOADED:
					race.load_status = models.RESULTS_SOME_UNOFFICIAL
					race.save()
				for runner in touched_runners:
					runner_stat.update_runner_stat(runner=runner)
					if runner.user:
						runner_stat.update_runner_stat(user=runner.user, update_club_members=False)
				messages.success(request, 'Добавлено результатов: {}. Статистика этих бегунов обновлена'.format(n_results_created))
			if n_klb_results_created:
				messages.success(request, 'В том числе результатов в КЛБМатч: {}.{}'.format(n_klb_results_created,
					'' if context['is_admin'] else ' Очки за них будут добавлены после добавления модератором'))
			if touched_persons:
				update_persons_score(year=year, persons_to_update=touched_persons, update_runners=True)
				messages.success(request, 'Затронуто участников Матча: {}. Их результаты пересчитаны.'.format(len(touched_persons)))
			if touched_persons_by_team:
				messages.success(request, 'Затронуты команды: {}'.format(', '.join(team.name for team in touched_persons_by_team.keys())))
			views_klb.log_teams_score_changes(race, touched_persons_by_team, 'Добавление вручную результатов на данной дистанции в КЛБМатч', user)
			return redirect(race)
		else:
			messages.warning(request, "Результаты не добавлены. Пожалуйста, исправьте ошибки в форме.")
	else:
		# So we just arrived here or have errors in POST request
		formset = getKlbResultFormSet(**formset_kwargs)
	context['club'] = club
	context['n_persons'] = n_persons
	context['formset'] = formset
	context['hasOfficialResults'] = race.get_official_results().exists()
	context['type_minutes'] = (race.distance.distance_type == models.TYPE_MINUTES_RUN)
	return render(request, 'editor/klb/race_add_results.html', context)
