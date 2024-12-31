from django.shortcuts import get_object_or_404, render, redirect
from django.contrib import messages
from django.db import transaction

import logging

from results import models
from editor import forms
from .views_user_actions import log_form_change
from .views_common import group_required, changes_history, update_organizer

from tools.flock_mutex import Flock_mutex
from starrating.constants import LOCK_FILE_FOR_RATED_TREE_MODIFICATIONS
from starrating.aggr.rated_tree_modifications import change_parent
from starrating.exceptions import UpdatedRecordExistsError

@group_required('admins')
def organizer_details(request, organizer_id=None):
	if organizer_id:
		organizer = get_object_or_404(models.Organizer, pk=organizer_id)
		str_action = 'обновлён'
	else:
		organizer = models.Organizer(created_by=request.user)
		str_action = 'создан'

	if 'frmOrganizer_submit' in request.POST:
		form = forms.OrganizerForm(request.POST, instance=organizer, files=request.FILES)
		if form.is_valid():
			form.save()
			log_form_change(request.user, form, action=models.ACTION_UPDATE if organizer_id else models.ACTION_CREATE)
			messages.success(request, 'Организатор успешно {}. Проверьте, всё ли правильно.'.format(str_action))
			return redirect(organizer.get_editor_url())
		else:
			messages.warning(request, 'Организатор не {}. Пожалуйста, исправьте ошибки в форме.'.format(str_action))
	else:
		form = forms.OrganizerForm(instance=organizer)

	context = {}
	context['organizer'] = organizer
	context['form'] = form
	return render(request, 'editor/organizer_details.html', context)

@group_required('admins')
def organizer_changes_history(request, organizer_id):
	organizer = get_object_or_404(models.Organizer, pk=organizer_id)
	return changes_history(request, organizer, organizer.get_absolute_url())

@group_required('admins')
def organizer_delete(request, organizer_id):
	organizer = get_object_or_404(models.Organizer, pk=organizer_id)
	has_dependent_objects = organizer.has_dependent_objects()
	ok_to_delete = False
	if 'frmForOrganizer_submit' in request.POST:
		form = forms.ForOrganizerForm(request.POST, auto_id='frmForOrganizer_%s')
		if form.is_valid():
			if has_dependent_objects:
				organizer_for = form.cleaned_data['new_organizer']
				if organizer_for != organizer:
					ok_to_delete = True
				else:
					messages.warning(request, 'Нельзя заменить организатора на его самого.')
			else: # There are no dependent objects of the organizer, so we just delete it
				ok_to_delete = True
		else:
			messages.warning(request, 'Организатор не удалён. Пожалуйста, исправьте ошибки в форме.')
	else:
		form = None
		messages.warning(request, 'Вы не указали город для удаления.')
	if ok_to_delete:
		# NOT TESTED !
		if has_dependent_objects:
			organizer_for_id = organizer_for.id
		else:
			organizer_for_id = 0
			organizer_for = None
		log = logging.getLogger('structure_modification')
		log_prefix = 'organizer_delete: organizer {}->{}, by user {}.'.format(
			organizer_id, organizer_for_id, request.user.id
		)
		log_exc_info = False
		organizer_name_full = organizer.name_full()
		log.debug('{} before flock'.format(log_prefix))
		with Flock_mutex(LOCK_FILE_FOR_RATED_TREE_MODIFICATIONS):
			try:
				with transaction.atomic():
					if has_dependent_objects:
						update_organizer(request, organizer, organizer_for)
					models.log_obj_delete(request.user, organizer)
					organizer.delete()
				log.debug('{} trnsctn end'.format(log_prefix))
			except (UpdatedRecordExistsError, AssertionError) as e:
				error_msg = repr(e)
				if isinstance(e, AssertionError):
					log_exc_info = True
			except Exception as e:
				log.error('{} Unexpected error: {}'.format(log_prefix, repr(e)), exc_info=True)
				raise
			else:
				error_msg = None
		if error_msg is None:
			log.info('{} OK'.format(log_prefix))
			messages.success(request, 'Организатор «{}» успешно удалён.'.format(organizer_name_full))
		else:
			log.error('{} {}'.format(log_prefix, error_msg), exc_info=log_exc_info)
			messages.warning(
				request, 'Не удалось удалить организатора «{}» ({}).'.format(
					organizer_name_full, error_msg
				)
			)
		if has_dependent_objects and organizer_for:
			return redirect(organizer_for.get_editor_url())
		else:
			return redirect('results:organizers')
	return organizer_details(request, organizer_id=organizer_id)

@group_required('admins')
def add_series(request, organizer_id):
	organizer = get_object_or_404(models.Organizer, pk=organizer_id)
	if 'select_series' in request.POST:
		series_id = results_util.int_safe(request.POST['select_series'])
		series = get_object_or_404(models.Series, pk=series_id)
		if series.organizer_id != models.FAKE_ORGANIZER_ID:
			messages.warning(request, 'У серии {} (id {}) уже указан организатор {} (id {}).'.format(
					series.name, series_id, series.organizer.name, series.organizer.id))
		else:
			log = logging.getLogger('structure_modification')
			log_prefix = 'add_series {} to organizer {} by user {}.'.format(series.id, organizer_id, request.user.id)
			log.debug('{} before flock'.format(log_prefix))
			log_exc_info = False
			with Flock_mutex(LOCK_FILE_FOR_RATED_TREE_MODIFICATIONS):
				log.debug('{} trnsctn start'.format(log_prefix))
				try:
					with transaction.atomic():
						change_parent(series, organizer)   # to adapt the starrating data)
						series.organizer = organizer
						series.save()
						models.log_obj_create(request.user, series, models.ACTION_UPDATE, field_list=['organizer'])
					log.debug('{} trnsctn end'.format(log_prefix))
				except (UpdatedRecordExistsError, AssertionError) as e:
					error_msg = repr(e)
					if isinstance(e, AssertionError):
						log_exc_info = True
				else:
					error_msg = None
				if error_msg is None:
					log.info('{} OK'.format(log_prefix))
					messages.success(request, 'Серия «{}» (id {}) успешно добавлена этому организатору.'.format(series.name, series_id))
				else:
					log.error('{} {}'.format(log_prefix, error_msg), exc_info=log_exc_info)
					messages.warning(request, 'Не удалось добавить серию «{}» (id {}) этому организатору ({}).'.format(series.name, series_id, error_msg))
	return redirect(organizer)

@group_required('admins')
def remove_series(request, organizer_id, series_id):
	organizer = get_object_or_404(models.Organizer, pk=organizer_id)
	if 'btnRemoveSeries' in request.POST:
		series = get_object_or_404(models.Series, pk=series_id)
		if series.organizer != organizer:
			messages.warning(request, 'У серии {} (id {}) и так не указан организатор {} (id {}).'.format(
					series.name, series_id, series.organizer.name, series.organizer.id))
		else:
			log = logging.getLogger('structure_modification')
			log_prefix = 'remove_series {} from organizer {} by user {}.'.format(series.id, organizer_id, request.user.id)
			log.debug('{} before flock'.format(log_prefix))
			log_exc_info = False
			with Flock_mutex(LOCK_FILE_FOR_RATED_TREE_MODIFICATIONS):
				log.debug('{} trnsctn start'.format(log_prefix))
				try:
					with transaction.atomic():
						change_parent(series, models.Organizer.objects.fake_object)
						# ^ to adapt the starrating data) ^
						series.organizer_id = models.FAKE_ORGANIZER_ID
						series.save()
						models.log_obj_create(request.user, series, models.ACTION_UPDATE, field_list=['organizer'])
					log.debug('{} trnsctn end'.format(log_prefix))
				except (UpdatedRecordExistsError, AssertionError) as e:
					error_msg = repr(e)
					if isinstance(e, AssertionError):
						log_exc_info = True
				else:
					error_msg = None
				if error_msg is None:
					log.info('{} OK'.format(log_prefix))
					messages.success(request, 'Серия «{}» (id {}) успешно отвязана от этого организатора.'.format(series.name, series_id))
				else:
					log.error('{} {}'.format(log_prefix, error_msg), exc_info=log_exc_info)
					messages.warning(request, 'Не удалось отвязать серию «{}» (id {}) от этого организатора ({}).'.format(series.name, series_id, error_msg))
	return redirect(organizer)
