from django.shortcuts import get_object_or_404, render, redirect
from django.forms import modelformset_factory
from django.db.models import Q
from django.contrib import messages

from results import models, models_klb, results_util
from editor import forms, runner_stat
from . import views_common, views_klb, views_klb_stat, views_stat, views_user_actions

def get_first_name_position(raw_names): # Name Surname or Surname Name or ...?
	popular_names = set([
		'александр', 'алексей', 'даниил', 'дмитрий', 'евгений', 'иван', 'максим', 'михаил', 'никита', 'сергей',
		'александра', 'анастасия', 'анна', 'виктория', 'дарья', 'екатерина', 'елизавета', 'мария', 'софия', 'юлия',
		'елена', 'татьяна', 'ольга', 'наталья', 'ирина', 'светлана', 'людмила',
		'владимир', 'андрей', 'николай', 'степан', 'роман', 'iван'])
	first_name_positions = [0, 0, 0]
	name_lengths = [0, 0, 0]
	for name in raw_names[:50]:
		name_split = name.lower().split()
		if len(name_split) > 0:
			name_lengths[0] += len(name_split[0])
			if name_split[0] in popular_names:
				first_name_positions[0] += 1
			if len(name_split) > 1:
				name_lengths[1] += len(name_split[1])
				if name_split[1] in popular_names:
					first_name_positions[1] += 1
				if len(name_split) > 2:
					name_lengths[2] += len(name_split[2])
					if name_split[2] in popular_names:
						first_name_positions[2] += 1
	if sum(first_name_positions) == 0: # Most probably the protocol is in English. Then usually surnames are longer than first names
		return 1 if (name_lengths[0] > name_lengths[1]) else 0
	if first_name_positions[0] >= first_name_positions[1]:
		if first_name_positions[0] >= first_name_positions[2]:
			return 0
		else:
			return 2
	elif first_name_positions[1] >= first_name_positions[2]:
		return 1
	else:
		return 2

def split_name(name_raw, first_name_position): # Return triple: lname, fname, midname
	name_split = name_raw.split()
	if len(name_split) == 0: # Something strange
		return '', '', ''
	elif len(name_split) == 1: # Only one word - let it be last name
		return name_split[0], '', ''
	elif len(name_split) == 2:
		if first_name_position == 0: # Игорь Нетто
			return name_split[1], name_split[0], ''
		else: # Нетто Игорь
			return name_split[0], name_split[1], ''
	else: # len(name_split) > 2
		if first_name_position == 0: # Семён Семёнович Горбунков
			return " ".join(name_split[2:]), name_split[0], name_split[1]
		else: # Горбунков Семён Семёнович
			return name_split[0], name_split[1], " ".join(name_split[2:])

def fill_places(race):
	results = race.result_set.filter(result__gt=0, status=models.STATUS_FINISHED, source=models.RESULT_SOURCE_DEFAULT).select_related(
		'category_size').order_by('-result' if (race.distance.distance_type in models.TYPES_MINUTES) else 'result', 'place_raw')
	n_results = results.count()

	# How many people we already passed
	overall_place = 0
	gender_places = [0, 0, 0, 0]
	category_places = dict()

	# Place of last passed result
	overall_place_last = 0
	gender_places_last = [0, 0, 0, 0]
	category_places_last = dict()

	# Lasted passed result
	prev_overall_result = None
	prev_place_raw = None
	prev_gender_results = [None, None, None, None]
	prev_category_results = dict()
	for result in results:
		overall_place += 1
		if result.result == prev_overall_result and result.place_raw == prev_place_raw:
			result.place = overall_place_last
		else:
			result.place = overall_place
			overall_place_last = overall_place
			prev_overall_result = result.result

		if result.gender != results_util.GENDER_UNKNOWN:
			gender_places[result.gender] += 1
			if result.result == prev_gender_results[result.gender]:
				result.place_gender = gender_places_last[result.gender]
			else:
				result.place_gender = gender_places[result.gender]
				gender_places_last[result.gender] = gender_places[result.gender]
				prev_gender_results[result.gender] = result.result

		if result.category_size:
			category = result.category_size.name.lower()
			category_places[category] = category_places.get(category, 0) + 1
			if result.result == prev_category_results.get(category, None):
				result.place_category = category_places_last[category]
			else:
				result.place_category = category_places[category]
				category_places_last[category] = category_places[category]
				prev_category_results[category] = result.result
		result.save()
		prev_place_raw = result.place_raw

	race.category_size_set.all().update(size=0)
	for category, size in list(category_places.items()):
		category_size, created = models.Category_size.objects.get_or_create(race=race, name=category)
		if created:
			models.send_panic_email(
				'Results with category have no category_size link',
				'At race {} (id {}) there are results with category {} (size {}) but without a link to category size'.format(
					race, race.id, category, size)
			)
		category_size.size = size
		category_size.save()

	race.result_set.filter(Q(result=0) | Q(status__gt=models.STATUS_FINISHED), source=models.RESULT_SOURCE_DEFAULT).update(
		place=None, place_gender=None, place_category=None)
	for category_size in list(race.category_size_set.filter(size=0)):
		if not category_size.result_set.exists():
			category_size.delete()

	return n_results, len(category_places)

def get_timing_type(n_results, n_whole_seconds, n_whole_tenths):
	if n_results == 0:
		return models.TIMING_UNKNOWN
	n_with_hundredths = n_results - n_whole_seconds - n_whole_tenths
	if 2 * n_with_hundredths >= n_results: # So most results have non-zero hundredths
		return models.TIMING_ELECTRONIC
	if 5 * n_with_hundredths >= n_results: # Too many hundredths for manual fixes (at least 20% of all results)
		return models.TIMING_STRANGE

	n_with_tenths = n_results - n_whole_seconds - n_with_hundredths # Results with tenths without hundredths
	if 2 * n_with_tenths >= n_results: # So most results have non-zero tenths
		return models.TIMING_HAND
	if 5 * n_with_tenths >= n_results: # Too many tenths for manual fixes
		return models.TIMING_STRANGE
	return models.TIMING_UNKNOWN

def fill_timing_type(race):
	if race.distance.distance_type in models.TYPES_MINUTES:
		return
	n_results = 0
	n_whole_seconds = 0
	n_whole_tenths = 0
	for value in race.result_set.filter(source=models.RESULT_SOURCE_DEFAULT, status=models.STATUS_FINISHED).values_list(
			'result', flat=True):
		n_results += 1
		if (value % 100) == 0:
			n_whole_seconds += 1
		elif (value % 10) == 0:
			n_whole_tenths += 1
	race.timing = get_timing_type(n_results, n_whole_seconds, n_whole_tenths)
	race.save()

# Distances to create
@views_common.group_required('editors', 'admins')
def race_fill_places(request, race_id):
	race = get_object_or_404(models.Race, pk=race_id)
	context, has_rights, target = views_common.check_rights(request, event=race.event)
	if not has_rights:
		return target
	n_results, n_categories = fill_places(race)
	messages.success(request, 'Места для забега «{}» на {} успешно проставлены. Всего {} результатов, {} категорий.'.format(
		race.event, race.distance, n_results, n_categories))
	return redirect(race)

def clean_race_participants_numbers(race):
	race.n_participants = None
	race.n_participants_male = None
	race.n_participants_female = None
	race.n_participants_nonbinary = None
	race.n_participants_finished = None
	race.n_participants_finished_male = None
	race.n_participants_finished_female = None
	race.n_participants_finished_nonbinary = None

# Different actions with results
def fill_race_headers(race):
	results = race.get_official_results()
	if results.exists():
		participants = results.exclude(status=results_util.STATUS_DNS)
		race.n_participants = participants.count()
		race.n_participants_male = participants.filter(gender=results_util.GENDER_MALE).count()
		race.n_participants_female = participants.filter(gender=results_util.GENDER_FEMALE).count()
		race.n_participants_nonbinary = participants.filter(gender=results_util.GENDER_NONBINARY).count()
		finishers = results.filter(status=results_util.STATUS_FINISHED)
		race.n_participants_finished = finishers.count()
		race.n_participants_finished_male = finishers.filter(gender=results_util.GENDER_MALE).count()
		race.n_participants_finished_female = finishers.filter(gender=results_util.GENDER_FEMALE).count()
		race.n_participants_finished_nonbinary = finishers.filter(gender=results_util.GENDER_NONBINARY).count()
	else:
		clean_race_participants_numbers(race)
	race.fill_winners_info()
	views_stat.update_course_records(race.event.series)

def reset_race_headers(race):
	clean_race_participants_numbers(race)
	views_stat.update_course_records(race.event.series)

@views_common.group_required('editors', 'admins')
def update_race_headers(request, race_id):
	race = get_object_or_404(models.Race, pk=race_id)
	context, has_rights, target = views_common.check_rights(request, event=race.event)
	if not has_rights:
		return target
	fill_race_headers(race)
	messages.success(request, 'Информация о победителях успешно обновлена')
	return redirect(race)

# Different actions with results
@views_common.group_required('admins')
def race_swap_names(request, race_id, swap_type):
	race = get_object_or_404(models.Race, pk=race_id)
	results = race.result_set.all()
	n_touched = 0
	swap_type = results_util.int_safe(swap_type)
	for result in results:
		if swap_type == 1:
			tmp = result.fname
			result.fname = result.lname
			result.lname = tmp
			result.save()
			n_touched += 1
		elif swap_type == 2:
			tmp = result.fname
			result.fname = result.midname
			result.midname = tmp
			result.save()
			n_touched += 1
	if swap_type in [1,2]:
		messages.success(request, 'Успешно обновлено имён: {}.'.format(n_touched))
	else:
		messages.warning(request, 'Неправильный тип перестановки имён:{}.'.format(swap_type))
	if n_touched:
		race.fill_winners_info()
	return redirect(race)

N_EXTRA_SPLITS = 5
def getSplitFormSet(result, data=None):
	SplitFormSet = modelformset_factory(models.Split, form=forms.SplitForm, formset=forms.SplitFormSet, can_delete=True, extra=N_EXTRA_SPLITS)
	distance = result.race.distance
	return SplitFormSet(
		data=data,
		queryset=result.split_set.order_by('distance__length'),
		initial=[{'result':result}] * N_EXTRA_SPLITS,
		form_kwargs={
			'distance': distance,
		},
	)

@views_common.group_required('admins')
def result_details(request, result_id=None, result=None, frmResult=None, create_new=False, frmSplits=None):
	if not result: # False if we are creating new result
		result = get_object_or_404(models.Result, pk=result_id)
	if result and not frmResult:
		frmResult = forms.ResultForm(instance=result)
	race = result.race
	event = race.event
	context = {}
	context['result'] = result
	context['race'] = race
	context['event'] = event
	context['year'] = event.start_date.year
	context['form'] = frmResult
	context['create_new'] = create_new
	context['type_minutes'] = (race.distance.distance_type in models.TYPES_MINUTES)
	context['page_title'] = 'Создание нового результата' if create_new else f'Результат {result}'
	if not create_new:
		if frmSplits is None:
			frmSplits = getSplitFormSet(result)
		context['frmSplits'] = frmSplits
		if not result.runner:
			context['possible_runners'] = views_stat.get_runners_for_result(result)[:3]
	return render(request, "editor/result_details.html", context)

def update_result_connections(user, new_result, changed_data, result=models.Result()):
	""" If needed, recalc klb_result. If needed, update user's and runner's statistic. If possible, use old result fields """
	users_to_update = set()
	runners_to_update = set()
	if 'result' in changed_data:
		for user in [result.user, new_result.user]:
			if user:
				users_to_update.add(user)
		for runner in [result.runner, new_result.runner]:
			if runner:
				runners_to_update.add(runner)
	else:
		if 'user' in changed_data:
			for user in [result.user, new_result.user]:
				if user:
					users_to_update.add(user)
		if 'runner' in changed_data:
			for runner in [result.runner, new_result.runner]:
				if runner:
					runners_to_update.add(runner)
	for user in users_to_update:
		runner_stat.update_runner_stat(user=user)
	for runner in runners_to_update:
		runner_stat.update_runner_stat(runner=runner)
	if ('user' in changed_data) and new_result.user:
		new_result.add_for_mail()
	return klb_result_changed

@views_common.group_required('admins')
def result_connect_to_runner(request, result_id, runner_id):
	result = get_object_or_404(models.Result, pk=result_id)
	race = result.race
	if result.runner:
		messages.warning(request, 'Этот результат уже и так привязан к бегуну. Ничего не делаем')
		return redirect(result.get_editor_url())

	runner = get_object_or_404(models.Runner, pk=runner_id)
	existing_result = runner.result_set.filter(race=race).first()
	if existing_result:
		messages.warning(request, f'К этому бегуну уже привязан результат {existing_result} (id {existing_result.id}) на этом же старте.'
			+ ' Ничего не делаем')
		return redirect(result.get_editor_url())

	result.runner = runner
	changed_fields = ['runner']
	if runner.user:
		result.user = runner.user
		changed_fields.append('user')
	result.save()
	models.log_obj_create(request.user, race.event, models.ACTION_RESULT_UPDATE, field_list=changed_fields, child_object=result,
		comment='При привязке на странице правки результата')

	runner_stat.update_runner_stat(runner=runner)
	if runner.user:
		runner_stat.update_runner_stat(user=runner.user, update_club_members=False)
		result.add_for_mail()
	if result.place_gender == 1:
		fill_race_headers(race)

	if request.POST.get('chkAddName'):
		if result.lname and result.fname:
			extra_name, created = models.Extra_name.objects.get_or_create(runner=runner, lname=result.lname, fname=result.fname, midname=result.midname,
				defaults={'comment': 'При привязке со страницы результата', 'added_by': request.user})
			if created:
				messages.success(request, f'Дополнительное имя {result.lname} {result.fname} {result.midname} бегуну добавлено')
			else:
				messages.warning(request, f'Дополнительное имя {result.lname} {result.fname} {result.midname} у бегуна уже есть')
		else:
			messages.warning(request, 'Не получилось добавить это имя бегуну — для этого у результата должны быть указаны и имя, и фамилия')
	messages.success(request, f'Результат успешно привязан к бегуну {runner.name()}')
	return redirect(result.get_editor_url())

@views_common.group_required('admins')
def result_update(request, result_id):
	if ('btnСonnectToRunner' in request.POST) and ('runner' in request.POST):
		return result_connect_to_runner(request, result_id, request.POST['runner'])

	if 'btnDisconnect' in request.POST:
		return result_disconnect(request, result_id)

	result = get_object_or_404(models.Result, pk=result_id)
	race = result.race
	if ('frmResult_submit' in request.POST) or ('frmResult_submit_gotorace' in request.POST):
		form = forms.ResultForm(request.POST, instance=result)
		if form.is_valid():
			new_result = form.save()
			views_user_actions.log_form_change(request.user, form, models.ACTION_RESULT_UPDATE, obj=new_result.race.event, child_id=new_result.id)

			klb_result_changed = update_result_connections(request.user, new_result, form.changed_data, result)
			if klb_result_changed:
				messages.success(request, 'Очки за результат в КЛБМатче пересчитаны')

			messages.success(request, 'Результат «{}» успешно обновлён. Изменены следующие поля: {}'.format(
				result, ", ".join(form.changed_data)))

			if ('runner' in form.changed_data) and new_result.runner and new_result.runner.user:
				new_result.user = new_result.runner.user
				new_result.save()

			if race.load_status == models.RESULTS_LOADED:
				if ('result' in form.changed_data) or ('status' in form.changed_data):
					fill_places(race)
					fill_race_headers(race)
				if 'runner' in form.changed_data:
					race.fill_winners_info()
			if 'frmResult_submit' in request.POST:
				return redirect(result.get_editor_url())
			else:
				return redirect(race)
		else:
			messages.warning(request, "Результат не обновлён. Пожалуйста, исправьте ошибки в форме.")
	else:
		form = None
	return result_details(request, result_id=result_id, result=result, frmResult=form)

@views_common.group_required('admins')
def result_add_to_klb(request, result_id):
	result = get_object_or_404(models.Result, pk=result_id)
	year = result.race.event.start_date.year
	if ('select_participant_for_klb' in request.POST) and (result.get_klb_status() == models.KLB_STATUS_OK):
		participant_id = results_util.int_safe(request.POST['select_participant_for_klb'])
		participant = get_object_or_404(models.Klb_participant, pk=participant_id, year=models_klb.first_match_year(year))
		person = participant.klb_person
		if result.race.klb_result_set.filter(klb_person=person).exists():
			messages.warning(request, f'У участника КЛБМатчей с id {person.id} уже есть результат в матче на этом старте')
		else:
			only_bonus_score = 'only_bonus_score' in request.POST
			klb_result = views_klb.create_klb_result(result, person, request.user, only_bonus_score=only_bonus_score, comment='Со страницы правки результата')
			if klb_result:
				views_klb_stat.update_persons_score(year=year, persons_to_update=[person])
				if participant.team:
					touched_persons_by_team = {participant.team: [(person, 0, klb_result.total_score())]}
					views_klb.log_teams_score_changes(result.race, touched_persons_by_team,
						f'Добавление результата участника {person.get_name()}' + (' (только бонусы)' if only_bonus_score else ''), request.user) # pytype: disable=wrong-arg-types
				messages.success(request, f'Результат успешно засчитан в КЛБМатч. Очки участника {person.get_name()} (id {person.id}) обновлены')
			else:
				messages.warning(request, f'Результат не засчитан в КЛБМатч — скорее всего, у этого участника уже есть очки в матч на этой дистанции. На info@ ушло письмо с подробностями')
	return redirect(result.get_editor_url())

@views_common.group_required('admins')
def result_delete_from_klb(request, result_id):
	result = get_object_or_404(models.Result, pk=result_id)
	if ('frmKlbResult_submit' in request.POST) and hasattr(result, 'klb_result') and \
			(result.race.get_klb_status() in (models.KLB_STATUS_OK, models.KLB_STATUS_ONLY_ONE_PARTICIPANT)):
		person_id = results_util.int_safe(request.POST.get('select_person_for_klb', 0))
		klb_result = result.klb_result
		person = klb_result.klb_person
		team = klb_result.klb_participant.team
		score = klb_result.total_score()
		models.log_obj_delete(request.user, result.race.event, child_object=klb_result, action_type=models.ACTION_KLB_RESULT_DELETE)
		klb_result.delete()
		to_update_runner = False
		if 'to_unclaim' in request.POST:
			result.unclaim_from_runner(request.user)
			to_update_runner = True
		views_klb_stat.update_persons_score(year=result.race.event.start_date.year, persons_to_update=[person], update_runners=to_update_runner)
		if team:
			touched_persons_by_team = {team: [(person, score, 0)]}
			views_klb.log_teams_score_changes(result.race, touched_persons_by_team,
				f'Удаление результата участника {person.fname} {person.lname} из КЛБМатча', request.user) # pytype: disable=wrong-arg-types
		messages.success(request, 'Результат успешно удалён из КЛБМатча. Очки участника {} {} (id {}) обновлены'.format(
			person.fname, person.lname, person.id))
		return redirect(result.get_editor_url())
	return result_details(request, result_id=result_id, result=result)

@views_common.group_required('admins')
def result_mark_as_error(request, result_id):
	result = get_object_or_404(models.Result, pk=result_id)
	if not ('frmKlbErrorResult_submit' in request.POST):
		return redirect(result.get_editor_url())
	if not hasattr(result, 'klb_result'):
		messages.warning(request, 'Этот результат и так не учтён в КЛБМатчах')
		return redirect(result.get_editor_url())
	klb_result = result.klb_result
	event = result.race.event 
	year = event.start_date.year
	if models.is_active_klb_year(year):
		messages.warning(request, 'Этот результат относится к продолжающемуся КЛБМатчу. Просто удалите его и, если нужно, отвяжите от бегуна')
		return redirect(result.get_editor_url())
	klb_result.result = None
	klb_result.is_error = True
	klb_result.save()

	touched_fields = []
	runner = result.runner
	if runner:
		touched_fields.append('runner')
		result.runner = None
	user = result.user
	if user:
		touched_fields.append('user')
		result.user = None
	result.save()
	if runner:
		runner_stat.update_runner_stat(runner=runner)
	if user:
		runner_stat.update_runner_stat(user=user, update_club_members=False)
	models.log_obj_create(request.user, event, models.ACTION_RESULT_UPDATE, field_list=touched_fields, child_object=result,
		comment='При помечании КЛБ-результата как ошибочного')
	messages.success(request, 'КЛБ-результат помечен как ошибочный и отвязан от бегуна')
	return redirect(result.get_editor_url())

@views_common.group_required('admins')
def result_delete(request, result_id):
	result = get_object_or_404(models.Result, pk=result_id)
	race = result.race
	models.log_obj_delete(request.user, race.event, child_object=result)
	res_str = str(result)
	if hasattr(result, 'klb_result'):
		year = race.event.start_date.year
		if models.is_active_klb_year(year):
			person = result.klb_result.klb_person
			team = result.klb_result.klb_participant.team
			result.klb_result.delete()
			views_klb_stat.update_persons_score(year=year, persons_to_update=[person], update_runners=True)
			if team:
				prev_score = team.score
				team.refresh_from_db()
				models.Klb_team_score_change.objects.create(
					team=team,
					race=result.race,
					clean_sum=team.score - team.bonus_score,
					bonus_sum=team.bonus_score,
					delta=team.score - prev_score,
					n_persons_touched=1,
					comment='Удаление результата участника {} {} насовсем'.format(person.fname, person.lname),
					added_by=request.user,
				)
			messages.warning(request, 'Результат из КЛБМатча успешно удалён')
	runner = result.runner
	result.delete()
	if runner:
		runner_stat.update_runner_stat(runner=runner)
		if runner.user:
			runner_stat.update_runner_stat(user=runner.user, update_club_members=False)
	fill_places(race)
	fill_race_headers(race)
	messages.success(request, "Результат {} на забеге «{}» успешно удалён. Места проставлены заново, числа участников обновлены".format(
		res_str, race))
	return redirect(race)

def result_disconnect(request, result_id):
	result = get_object_or_404(models.Result, pk=result_id)
	if hasattr(result, 'klb_result'):
		messages.warning(request, 'Этот результат посчитан в КЛБМатч. Его нельзя отвязать от человека')
		return redirect(result.get_editor_url())
	runner = result.runner
	user = result.user
	changed_fields = []
	if runner:
		result.runner = None
		changed_fields.append('runner')
	if user:
		result.user = None
		changed_fields.append('user')
	if not changed_fields:
		messages.warning(request, 'Этот результат и так не привязан ни к какому человеку. Ничего не делаем')
		return redirect(result.get_editor_url())
	result.save()
	models.log_obj_create(request.user, result.race.event, models.ACTION_UPDATE, field_list=changed_fields, child_object=result,
		comment='При отвязке результата от человека')
	msgs = []
	if runner:
		runner_stat.update_runner_stat(runner=runner)
		msgs.append('от бегуна {}'.format(runner.get_name_and_id()))
	if user:
		runner_stat.update_runner_stat(user=user, update_club_members=False)
		msgs.append('от пользователя {} (id {})'.format(user.get_full_name(), user.id))
	messages.success(request, 'Результат успешно отвязан {}'.format(' и '.join(msgs)))
	return redirect(result.get_editor_url())

@views_common.group_required('admins')
def result_splits_update(request, result_id):
	result = get_object_or_404(models.Result, pk=result_id)
	if 'frmSplits_submit' in request.POST:
		formset = getSplitFormSet(result, data=request.POST)
		if formset.is_valid():
			formset.save()
			views_user_actions.log_document_formset(request.user, result.race.event, formset)
			messages.success(request, ('Сплиты результата «{}» успешно обновлены: {} сплитов добавлено, {} обновлено, '
				+ '{} удалено. Проверьте, всё ли правильно.').format(
				result, len(formset.new_objects), len(formset.changed_objects), len(formset.deleted_objects)))
			return redirect('editor:result_details', result_id=result.id)
		else:
			messages.warning(request, "Сплиты результата «{}» не обновлены. Пожалуйста, исправьте ошибки в форме.".format(result))
	else:
		formset = None
	return result_details(request, result_id=result_id, result=result, frmSplits=formset)

def make_names_title():
	fields = ['lname', 'fname', 'midname']
	to_change = {}
	for field in fields:
		to_change[field] = 0
	for thousand in range(1544):
		for result in models.Result.objects.filter(pk__range=(thousand * 1000 + 1, thousand * 1000 + 1000)):
			for field in fields:
				value = getattr(result, field)
				if value.title() != value:
					setattr(result, field, value.title())
					result.save()
					to_change[field] += 1
	for field in fields:
		print(field, to_change[field])
	print('Done!')

def clean_hundredths(race_id): # Sometimes, due to weird Excel files, we want to remove any fractions of seconds
	race = models.Race.objects.get(pk=race_id)
	n_results_changed = 0
	for result in race.result_set.all():
		new_value = (result.result // 100) * 100
		if new_value != result.result:
			result.result = new_value
			result.save()
			n_results_changed += 1
	print('Done! Results changed:', n_results_changed)
