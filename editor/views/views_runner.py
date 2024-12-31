from django.shortcuts import get_object_or_404, render, redirect
from django.contrib import messages

import datetime
from typing import Optional

from results import models, models_klb, results_util
from results.forms import UserNameForm
from editor import forms, runner_stat
from . import views_common, views_user_actions

@views_common.group_required('admins')
def runner_details(request,
		runner_id: Optional[int]=None,
		runner: Optional[models.Runner]=None,
		frmRunner: Optional[any]=None,
		frmName: Optional[any]=None,
		frmLink: Optional[any]=None,
		frmPlatform: Optional[any]=None):
	if runner is None: # False if we are creating new runner
		runner = get_object_or_404(models.Runner, pk=runner_id)
	if frmRunner is None:
		initial = {}
		if runner.city:
			initial['city'] = runner.city
			initial['region'] = runner.city.region.id
		frmRunner = forms.RunnerForm(instance=runner, initial=initial)
	context = {}
	context['runner'] = runner
	context['form'] = frmRunner
	context['frmName'] = frmName or UserNameForm()
	context['frmLink'] = frmLink or forms.RunnerLinkForm()
	context['frmPlatform'] = frmPlatform or forms.RunnerPlatformForm()

	if runner.id:
		context['page_title'] = f'{runner.name()} (id {runner.id})'
		context['names'] = runner.extra_name_set.order_by('lname', 'fname', 'midname')
		context['runner_links'] = runner.runner_link_set.order_by('description')
		context['runner_platforms'] = runner.runner_platform_set.select_related('platform').order_by('platform_id')
		context['has_nyrr_id'] = context['runner_platforms'].filter(platform_id='nyrr').exists()
	else:
		context['page_title'] = 'Создание нового бегуна'
	return render(request, "editor/runner_details.html", context)

@views_common.group_required('admins')
def runner_update(request, runner_id):
	runner = get_object_or_404(models.Runner, pk=runner_id)
	if 'frmRunner_submit' in request.POST:
		frmRunner = forms.RunnerForm(request.POST, instance=runner)
		if frmRunner.is_valid():
			runner = frmRunner.save()
			views_user_actions.log_form_change(request.user, frmRunner, action=models.ACTION_UPDATE, exclude=['country', 'region'])
			messages.success(request, 'Бегун «{}» успешно обновлён. Изменены поля: {}'.format(
				runner.name(), ", ".join(frmRunner.changed_data)))
			klb_person = runner.klb_person
			if klb_person:
				fields_for_klb_person = []
				if ('birthday' in frmRunner.changed_data) and runner.birthday_known:
					fields_for_klb_person.append('birthday')
				for field in ['lname', 'fname', 'midname', 'gender', 'city_id']:
					if field in frmRunner.changed_data:
						fields_for_klb_person.append(field)
				if fields_for_klb_person:
					for field in fields_for_klb_person:
						setattr(klb_person, field, getattr(runner, field))
					klb_person.clean()
					klb_person.save()
					if ('birthday' in fields_for_klb_person) or ('gender' in fields_for_klb_person):
						participant = klb_person.klb_participant_set.filter(year=models_klb.CUR_KLB_YEAR).first()
						if participant:
							participant.fill_age_group()
					models.log_obj_create(request.user, klb_person, models.ACTION_UPDATE, field_list=fields_for_klb_person, comment='При правке бегуна')
					messages.success(request, 'У участника КЛБМатчей изменены поля: {}'.format(", ".join(fields_for_klb_person)))
			return redirect(runner)
		else:
			messages.warning(request, "Бегун не обновлён. Пожалуйста, исправьте ошибки в форме.")
	else:
		frmRunner = None
	return runner_details(request, runner_id=runner_id, runner=runner, frmRunner=frmRunner)

# Needs to be called only if runner.has_dependent_objects() == True
def delete_runner_for_another(request, creator, runner, has_dependent_objects, new_runner):
	if has_dependent_objects:
		views_common.update_runner(request, creator, runner, new_runner)
		runner_stat.update_runners_and_users_stat([new_runner])
	models.log_obj_delete(creator, runner)
	if request:
		messages.success(request, 'Бегун {} (id {}) успешно удалён.'.format(runner.name(), runner.id))
	runner.delete()

@views_common.group_required('admins')
def runner_delete(request, runner_id):
	runner = get_object_or_404(models.Runner, pk=runner_id)
	has_dependent_objects = runner.has_dependent_objects()
	ok_to_delete = False
	form = None
	new_runner = None
	if 'frmForRunner_submit' in request.POST:
		if has_dependent_objects:
			new_runner_id = results_util.int_safe(request.POST.get('select_runner'))
			if new_runner_id:
				if new_runner_id != runner.id:
					new_runner = models.Runner.objects.filter(pk=new_runner_id).first()
					if new_runner:
						is_merged, msgError = new_runner.merge(runner, request.user, allow_merge_nyrr=('allow_merge_nyrr' in request.POST))
						if is_merged:
							ok_to_delete = True
						else:
							messages.warning(request, f'Не удалось объединить бегунов. Ошибка: {msgError}')
					else:
						messages.warning(request, 'Бегун, на которого нужно заменить текущего, не найден.')
				else:
					messages.warning(request, 'Нельзя заменить бегуна на него же.')
			else:
				messages.warning(request, 'Бегун, на которого нужно заменить текущего, не указан.')
		else: # There are no results for runner, so we just delete him
			ok_to_delete = True
	else:
		messages.warning(request, "Вы не указали бегуна для удаления.")

	if ok_to_delete:
		delete_runner_for_another(request, request.user, runner, has_dependent_objects, new_runner)
		return redirect(new_runner if has_dependent_objects else 'results:runners') 

	return runner_details(request, runner_id=runner_id, runner=runner)

@views_common.group_required('admins', 'editors')
def runner_create(request, lname='', fname=''):
	runner = models.Runner(created_by=request.user, lname=lname, fname=fname)
	if 'frmRunner_submit' in request.POST:
		form = forms.RunnerForm(request.POST, instance=runner)
		if form.is_valid():
			form.save()
			views_user_actions.log_form_change(request.user, form, action=models.ACTION_CREATE)
			messages.success(request, 'Бегун «{}» успешно создан. Проверьте, всё ли правильно.'.format(runner))
			return redirect(runner.get_absolute_url())
		else:
			messages.warning(request, "Бегун не создан. Пожалуйста, исправьте ошибки в форме.")
	else:
		form = None
	return runner_details(request, runner=runner, frmRunner=form)

@views_common.group_required('admins')
def runner_changes_history(request, runner_id):
	runner = get_object_or_404(models.Runner, pk=runner_id)
	return views_common.changes_history(request, runner, runner.get_absolute_url())

@views_common.group_required('admins')
def runner_update_stat(request, runner_id):
	runner = get_object_or_404(models.Runner, pk=runner_id)
	runner_stat.update_runners_and_users_stat([runner])
	messages.success(request, 'Статистика успешно обновлена')
	return redirect('results:runner_details', runner_id=runner.id)

@views_common.group_required('admins')
def runner_name_add(request, runner_id):
	runner = get_object_or_404(models.Runner, pk=runner_id)
	if 'frmName_submit' not in request.POST:
		return redirect(runner.get_editor_url())
	extra_name = models.Extra_name(runner=runner, added_by=request.user)
	frmName = UserNameForm(request.POST, instance=extra_name)
	if not frmName.is_valid():
		messages.warning(request, 'Данные для нового имени указаны с ошибкой. Пожалуйста, исправьте ошибки в форме.')
		return runner_details(request, runner_id=runner_id, runner=runner, frmName=frmName)
	extra_name = frmName.save()
	views_user_actions.log_form_change(request.user, frmName, action=models.ACTION_EXTRA_NAME_CREATE, obj=runner, child_id=extra_name.id)
	messages.success(request, 'Новое имя успешно добавлено.')
	return redirect(runner)

@views_common.group_required('admins')
def runner_name_delete(request, runner_id, name_id):
	runner = get_object_or_404(models.Runner, pk=runner_id)
	name = models.Extra_name.objects.filter(pk=name_id, runner=runner).first()
	if name is None:
		messages.warning(request, f'Имя с id {name_id} для удаления не найдено. Ничего не удалено.')
		return redirect(runner)
	models.log_obj_delete(request.user, runner, child_object=name, action_type=models.ACTION_EXTRA_NAME_DELETE)
	name.delete()
	messages.success(request, 'Имя успешно удалено.')
	return redirect(runner)

@views_common.group_required('admins')
def runner_link_add(request, runner_id):
	runner = get_object_or_404(models.Runner, pk=runner_id)
	if 'frmLink_submit' not in request.POST:
		return redirect(runner.get_editor_url())
	runner_link = models.Runner_link(runner=runner, added_by=request.user)
	frmLink = forms.RunnerLinkForm(request.POST, instance=runner_link)
	if not frmLink.is_valid():
		messages.warning(request, 'Форма для добавления страницы о бегуне заполнена с ошибкой. Пожалуйста, исправьте ошибки в форме.')
		return runner_details(request, runner_id=runner_id, runner=runner, frmLink=frmLink)
	runner_link = frmLink.save()
	views_user_actions.log_form_change(request.user, frmLink, action=models.ACTION_RUNNER_LINK_CREATE, obj=runner, child_id=runner_link.id)
	messages.success(request, 'Ссылка на страницу о бегуне успешно добавлена.')
	return redirect(runner)

@views_common.group_required('admins')
def runner_link_delete(request, runner_id, link_id):
	runner = get_object_or_404(models.Runner, pk=runner_id)
	runner_link = models.Runner_link.objects.filter(pk=link_id, runner=runner).first()
	if runner_link is None:
		messages.warning(request, f'Страница о бегуне с id {link_id} для удаления не найдена. Ничего не удалено.')
		return redirect(runner)
	models.log_obj_delete(request.user, runner, child_object=runner_link, action_type=models.ACTION_RUNNER_LINK_DELETE)
	link = runner_link.link
	runner_link.delete()
	messages.success(request, f'Ссылка на страницу о бегуне {link} успешно удалена.')
	return redirect(runner)

@views_common.group_required('admins')
def runner_platform_add(request, runner_id):
	runner = get_object_or_404(models.Runner, pk=runner_id)
	if 'frmPlatform_submit' not in request.POST:
		return redirect(runner.get_editor_url())
	runner_platform = models.Runner_platform(runner=runner)
	frmPlatform = forms.RunnerPlatformForm(request.POST, instance=runner_platform)
	if not frmPlatform.is_valid():
		messages.warning(request, 'Форма для добавления ID бегуна на платформе заполнена с ошибкой. Пожалуйста, исправьте ошибки в форме.')
		return runner_details(request, runner_id=runner_id, runner=runner, frmPlatform=frmPlatform)
	runner_platform = frmPlatform.save()
	views_user_actions.log_form_change(request.user, frmPlatform, action=models.ACTION_RUNNER_PLATFORM_CREATE, obj=runner, child_id=runner_platform.id)
	messages.success(request, f'Данные о бегуне на платформе {runner_platform.platform_id} успешно добавлены.')
	return redirect(runner)

@views_common.group_required('admins')
def runner_platform_delete(request, runner_id, runner_platform_id):
	runner = get_object_or_404(models.Runner, pk=runner_id)
	runner_platform = models.Runner_platform.objects.filter(pk=runner_platform_id, runner=runner).first()
	if runner_platform is None:
		messages.warning(request, f'Запись о платформе с id {runner_platform_id} для удаления не найдена. Ничего не удалено.')
		return redirect(runner)
	models.log_obj_delete(request.user, runner, child_object=runner_platform, action_type=models.ACTION_RUNNER_PLATFORM_DELETE)
	platform = runner_platform.platform
	value = runner_platform.value
	runner_platform.delete()
	messages.success(request, f'Запись об ID {value} на платформе {platform} успешно удалена.')
	return redirect(runner)

@views_common.group_required('admins')
def runners_with_old_last_find_results_try(request):
	context = {}
	context['runners'] = []
	context['page_title'] = 'Бегуны, у которых никто давно не искал похожие результаты'
	n_runners_with_zero_results = 0
	today = datetime.date.today()

	runners = models.Runner.objects.filter(last_find_results_try=None).order_by('lname', 'fname', 'midname')
	if not runners.exists():
		runners = models.Runner.objects.order_by('last_find_results_try', 'lname', 'fname', 'midname')

	for runner in list(runners[:100]):
		n_possible_results = len(runner.get_possible_results())
		if n_possible_results > 0:
			context['runners'].append((runner, n_possible_results))
			if len(context['runners']) == 20:
				break
		else:
			runner.last_find_results_try = today
			runner.n_possible_results = n_possible_results
			runner.save()
			n_runners_with_zero_results += 1

	if n_runners_with_zero_results:
		messages.success(request, f'Только что мы пометили как проверенные {n_runners_with_zero_results} бегунов с нулём похожих результатов')
	return render(request, "editor/runners_with_old_last_find_results_try.html", context)

@views_common.group_required('admins')
def unclaim_unclaimed_by_user(request, runner_id):
	runner = get_object_or_404(models.Runner, pk=runner_id)
	user = runner.user
	if not user:
		messages.warning(request, f'У бегуна с id {runner_id} нет пользователя. Ничего не делаем.')
		return redirect(runner)
	results = runner.result_set.filter(user=None)
	results_count = results.count()
	if results_count == 0:
		messages.warning(request, f'У бегуна с id {runner_id} все результаты привязаны и к пользователю. Ничего не делаем.')
		return redirect(runner)
	for result in list(results.select_related('race__event')):
		result.runner = None
		result.save()
		models.log_obj_create(request.user, result.race.event, models.ACTION_RESULT_UPDATE, field_list=['runner'], child_object=result,
			comment=f'При отвязке всех результатов от бегуна {runner.name()} (id {runner.id}) без пользователя')
	runner_stat.update_runners_and_users_stat([runner])
	messages.success(request, f'{results_count} результатов, не привязанные к пользователю, успешно отвязаны от бегуна.')
	return redirect(runner)
