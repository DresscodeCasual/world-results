from results import models

def get_action_type(classname, action):
	if classname == "Social_page":
		if action == "CREATE":
			return models.ACTION_CREATE
		elif action == "UPDATE":
			return models.ACTION_UPDATE
		elif action == "DELETE":
			return models.ACTION_DELETE
	if classname == "Document":
		if action == "CREATE":
			return models.ACTION_DOCUMENT_CREATE
		elif action == "UPDATE":
			return models.ACTION_DOCUMENT_UPDATE
		elif action == "DELETE":
			return models.ACTION_DOCUMENT_DELETE
	if classname == "News":
		if action == "CREATE":
			return models.ACTION_NEWS_CREATE
		elif action == "UPDATE":
			return models.ACTION_NEWS_UPDATE
		elif action == "DELETE":
			return models.ACTION_NEWS_DELETE
	if classname == "Race":
		if action == "CREATE":
			return models.ACTION_RACE_CREATE
		elif action == "UPDATE":
			return models.ACTION_RACE_UPDATE
		elif action == "DELETE":
			return models.ACTION_RACE_DELETE
	if classname == "Result":
		if action == "CREATE":
			return models.ACTION_RESULT_CREATE
		elif action == "UPDATE":
			return models.ACTION_RESULT_UPDATE
		elif action == "DELETE":
			return models.ACTION_RESULT_DELETE
	if classname == "Split":
		if action == "CREATE":
			return models.ACTION_SPLIT_CREATE
		elif action == "UPDATE":
			return models.ACTION_SPLIT_UPDATE
		elif action == "DELETE":
			return models.ACTION_SPLIT_DELETE
	if classname == "Klb_result":
		if action == "CREATE":
			return models.ACTION_KLB_RESULT_CREATE
		elif action == "UPDATE":
			return models.ACTION_KLB_RESULT_UPDATE
		elif action == "DELETE":
			return models.ACTION_KLB_RESULT_DELETE
	models.send_panic_email(
		'Unknown action in log_document_change',
		f'Не получается восстановить тип действия по типу объекта {classname} и действию {action}.',
	)
	return models.ACTION_UNKNOWN

def log_form_change(user, form, action, exclude=[], obj=None, child_id=None, verified_by=None): # For Series, events, etc
	if obj is None: # obj is not None only if we change result: then obj=event
		obj = form.instance
	if form.has_changed():
		table_update = models.Table_update.objects.create(
			model_name=obj.__class__.__name__,
			child_id=child_id,
			row_id=obj.id,
			action_type=action,
			user=user,
			verified_by=verified_by,
			is_verified=(verified_by is not None) or user.groups.filter(name="admins").exists()
		)
		for field in form.changed_data:
			if field not in exclude:
				field_name = field
				# A hack: all descendants of ModelFormWithCity have city_id field which is always contained in form.cleaned_data.
				# We want to include it only if city was really changed.
				if (field == 'city_id') and ('city' in form.cleaned_data):
					field_name = 'city'
				models.Field_update.objects.create(table_update=table_update, field_name=field_name,
					new_value=str(form.cleaned_data[field_name])[:models.MAX_VALUE_LENGTH])

def log_document_change(user, obj, child_obj, field_list, action, exclude=[]): # For documents, news, races, social pages, splits
	action_type = get_action_type(child_obj.__class__.__name__, action)
	if obj:
		table_update = models.Table_update.objects.create(model_name=obj.__class__.__name__,
			row_id=obj.id, child_id=(child_obj.id if child_obj.id else None),
			action_type=action_type, user=user, is_verified=user.groups.filter(name="admins").exists())
	else: # For social pages
		table_update = models.Table_update.objects.create(model_name=child_obj.__class__.__name__,
			row_id=(child_obj.id if child_obj.id else 0),
			action_type=action_type, user=user, is_verified=user.groups.filter(name="admins").exists())
	if action != "DELETE":
		for field in field_list:
			if (field not in exclude) and hasattr(child_obj, field):
				new_value = getattr(child_obj, field)
				if (action != "CREATE") or new_value: # If creating object, do not log fields with empty values
					models.Field_update.objects.create(table_update=table_update, field_name=field,
						new_value=str(new_value)[:models.MAX_VALUE_LENGTH])

def log_document_formset(user, obj, formset, exclude=[]): # For documents, news, races, social pages, results
	for instance in formset.new_objects:
		log_document_change(user, obj, instance, [x.name for x in instance._meta.fields], "CREATE", exclude)
	for instance, field_list in formset.changed_objects:
		log_document_change(user, obj, instance, field_list, "UPDATE", exclude)
	for instance in formset.deleted_objects:
		log_document_change(user, obj, instance, [], "DELETE", exclude)

def log_change_event_series(user, event): # When we change the series of an event
	table_update = models.Table_update.objects.create(model_name=event.__class__.__name__, row_id=event.id, action_type=models.ACTION_UPDATE,
		user=user, is_verified=user.groups.filter(name="admins").exists())
	models.Field_update.objects.create(table_update=table_update, field_name='series_id',
		new_value=str(event.series.id)[:models.MAX_VALUE_LENGTH])
