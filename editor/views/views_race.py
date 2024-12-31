from django.shortcuts import get_object_or_404, render, redirect
from django.contrib.auth.decorators import login_required
from django.forms import modelformset_factory
from django.contrib import messages

from results import models
from editor import forms, runner_stat
from . import views_common, views_result, views_user_actions

def getResultFormSet(race, data=None):
	ResultFormSet = modelformset_factory(models.Result, form=forms.ResultForm, can_delete=True, extra=0)
	res = ResultFormSet(
		data=data,
		queryset=models.Result.objects.filter(race=race).order_by('status', 'place', 'lname', 'fname', 'midname', 'id').select_related('category_size')
	)
	for form in res.forms:
		form.fields['DELETE'].widget.attrs.update({'class': 'chkbox'})
	return res

@views_common.group_required('admins')
def race_details(request, race_id=None, race=None, frmResults=None):
	if not race:
		race = get_object_or_404(models.Race, pk=race_id)
	context = {}

	if not frmResults:
		frmResults = getResultFormSet(race)
	context['frmResults'] = frmResults

	context['race'] = race
	context['event'] = race.event
	context['page_title'] = '{}: редактирование результатов'.format(race)

	return render(request, "editor/race_details.html", context)

@views_common.group_required('admins')
def race_update(request, race_id):
	race = get_object_or_404(models.Race, pk=race_id)
	context = {}

	if 'frmResults_submit' in request.POST:
		formset = getResultFormSet(race, data=request.POST)
		if formset.is_valid():
			formset.save()
			views_user_actions.log_document_formset(request.user, race.event, formset)
			for result, changed_data in formset.changed_objects:
				views_result.update_result_connections(request.user, result, changed_data)
			messages.success(request, ('Результаты забега «{}» успешно обновлены: {} результатов добавлено, {} обновлено, '
				+ '{} удалено. Проверьте, всё ли правильно.').format(
				race, len(formset.new_objects), len(formset.changed_objects), len(formset.deleted_objects)))
			race.was_checked_for_klb = False
			race.save()
			if race.load_status == models.RESULTS_LOADED:
				views_result.fill_race_headers(race)
			return redirect(race.get_results_editor_url())
		else:
			messages.warning(request, "Результаты забега «{}» не обновлены. Пожалуйста, исправьте ошибки в форме.".format(race))
	else:
		formset = None
	return race_details(request, race_id=race_id, race=race, frmResults=formset)

@views_common.group_required('admins')
def race_update_stat(request, race_id):
	race = get_object_or_404(models.Race, pk=race_id)
	n_runners = runner_stat.update_race_runners_stat(race)
	messages.success(request, 'Обновлена статистика у участников забега: {} человек'.format(n_runners))
	return redirect(race)

@login_required
def race_add_unoff_result(request, race_id):
	race = get_object_or_404(models.Race, pk=race_id)
	event = race.event
	user = request.user
	if 'frmAddResult_submit' in request.POST:
		runner = models.Runner.objects.filter(pk=request.POST.get('select_runner')).first()
		if runner:
			has_rights_for_this_runner = models.is_admin(user) or (runner.id in models.get_runner_ids_for_user(user))

			if has_rights_for_this_runner:
				result_in_this_race = runner.result_set.filter(race=race).first()
				if result_in_this_race is None:
					result_str = request.POST.get('result_str', '')
					result_centiseconds = race.parse_result(result_str)
					if result_centiseconds > 0:
						result = models.Result(
							runner=runner,
							user=runner.user,
							race=race,
							time_raw=result_str,
							result=result_centiseconds,
							status=models.STATUS_FINISHED,
							source=models.RESULT_SOURCE_USER,
							loaded_by=user,
						)
						result.save()
						models.log_obj_create(user, event, models.ACTION_UNOFF_RESULT_CREATE, child_object=result)
						runner_stat.update_runners_and_users_stat([runner])
						if ((result_centiseconds % 10) > 0) and (race.timing == models.TIMING_UNKNOWN):
							race.timing = models.TIMING_ELECTRONIC
							race.save()
							models.log_obj_create(user, event, models.ACTION_RACE_UPDATE, child_object=race, field_list=['timing'],
								comment='При добавлении неофициального результата с сотыми')
						messages.success(request, 'Результат {} бегуну {} успешно добавлен'.format(result, runner.name()))
					else:
						if race.distance.distance_type in models.TYPES_MINUTES:
							messages.warning(request, 'Пожалуйста, введите в качестве результата число метров')
						else:
							messages.warning(request, 'Пожалуйста, введите результат в формате ЧЧ:ММ:СС или ЧЧ:ММ:СС,хх')
				else:
					messages.warning(request, 'У этого бегуна уже есть результат {} на этой дистанции'.format(result_in_this_race))
			else:
				messages.warning(request, 'У Вас нет прав добавлять результат бегуну {} {} (id {})'.format(runner.fname, runner.lname, runner.id))
		else:
			messages.warning(request, 'Выбранный бегун не найден')
	return redirect(race)

@views_common.group_required('admins')
def race_delete_off_results(request, race_id):
	race = get_object_or_404(models.Race, pk=race_id)
	results = race.get_official_results()
	if results.exists():
		results.delete()
		views_result.fill_race_headers(race)
		race.load_status = models.RESULTS_NOT_LOADED
		race.loaded_from = ''
		race.was_checked_for_klb = False
		race.save()
		models.log_obj_create(request.user, race.event, models.ACTION_RACE_UPDATE, child_object=race, field_list=['loaded', 'loaded_from', 'was_checked_for_klb'],
			comment='При удалении всех официальных результатов')
		messages.success(request, 'Все официальные результаты на забеге {} успешно удалены'.format(race.name_with_event()))
	else:
		messages.warning(request, 'Официальных результатов на забеге {} не нашлось. Ничего не делаем'.format(race.name_with_event()))
	return redirect(race)

@views_common.group_required('admins')
def not_count_results_present_in_both_races_for_stat(request):
	if not (('race_id' in request.POST) and ('other_race_id' in request.POST)):
		return redirect('editor:util')
	try:
		race_id = int(request.POST.get('race_id'))
	except:
		messages.warning(request, f'Вы указали в качестве ID первой дистанции {request.POST.get("race_id")}. Это значение не подходит.')
		return redirect('editor:util')
	race = get_object_or_404(models.Race, pk=race_id)
	try:
		other_race_id = int(request.POST.get('other_race_id'))
	except:
		messages.warning(request, f'Вы указали в качестве ID второй дистанции {request.POST.get("other_race_id")}. Это значение не подходит.')
		return redirect('editor:util')
	other_race = get_object_or_404(models.Race, pk=other_race_id)

	if race.event_id != other_race.event_id:
		messages.warning(request, f'Два указанных старта — {race} и {other_race} — относятся к разным забегам (с id {race.event_id} и {other_race.event_id}). Не ошибка ли это?')
		return redirect(race)
	other_race_runner_ids = set(other_race.result_set.filter(status=models.STATUS_FINISHED, do_not_count_in_stat=False).exclude(runner=None).values_list('runner_id', flat=True))
	race_results_with_those_runners = race.result_set.filter(status=models.STATUS_FINISHED, runner_id__in=other_race_runner_ids).select_related('runner')
	n_results = race_results_with_those_runners.count()
	if n_results == 0:
		messages.warning(request, f'Мы не нашли бегунов, у которых есть успешные результаты сразу на стартах {race} и {other_race}.')
		return redirect(race)
	n_already_good = n_fixed = 0
	runners_to_update_stat = []
	for result in list(race_results_with_those_runners):
		if result.do_not_count_in_stat:
			n_already_good += 1
			continue
		result.do_not_count_in_stat = True
		result.save()
		models.log_obj_create(request.user, race.event, models.ACTION_RESULT_UPDATE, field_list=['do_not_count_in_stat'], child_object=result,
			comment=f'При массовой пометке результатов, которые также есть в старте {other_race.id}, как не учитывающиеся в статистике бегуна')
		runners_to_update_stat.append(result.runner)
		n_fixed += 1
	if runners_to_update_stat:
		runner_stat.update_runners_and_users_stat(runners_to_update_stat)
	messages.success(request, f'Мы поставили галочку «Не учитывать в личной статистике» у {n_fixed} результатов старта {race}, привязанных к бегунам, имеющим результат и на старте {other_race}.')
	if n_already_good:
		messages.success(request, f'У ещё {n_already_good} результатов с этим свойством такая галочка уже стояла.')
	return redirect(race)
