from django.shortcuts import get_object_or_404, render, redirect
from collections import OrderedDict
from django.contrib import messages
from django.db.models import Count

from results import models
from editor import forms
from results.views.views_common import user_edit_vars
from .views_user_actions import log_form_change
from .views_common import group_required, update_distance, changes_history

# E.g. (4.300, км) -> (1, 4300), (2.5, ч) -> (2, 150)
def pair2type_length(value, unit):
	if unit == "км":
		return models.TYPE_METERS, int(round(value * 1000))
	if unit in ['м', 'метров']:
		return models.TYPE_METERS, int(round(value))
	if unit in ['мили', 'миля', 'миль']:
		return models.TYPE_METERS, int(round(value * models.MILE_IN_METERS))
	if unit == "суток":
		return models.TYPE_MINUTES_RUN, int(round(value * 24 * 60))
	if unit in ['час', 'часа', 'часов', 'ч']:
		return models.TYPE_MINUTES_RUN, int(round(value * 60))
	if unit in ['минут', 'мин']:
		return models.TYPE_MINUTES_RUN, int(round(value))
	if unit in ["ступенек", "ступеньки"]:
		return models.TYPE_STEPS, int(round(value))
	if unit == "этажей":
		return models.TYPE_FLOORS, int(round(value))
	return models.TYPE_TRASH, int(round(value))

def cut_prefix(s, prefix):
	prefix_len = len(prefix)
	if s[:prefix_len] == prefix:
		s = s[prefix_len:]
	return s
def cut_suffix(s, suffix):
	suffix_len = len(suffix)
	if s[-suffix_len:] == suffix:
		s = s[:-suffix_len]
	return s

prefixes_to_cut = ["(Шоссе) ", "(Кросс-кантри) "]
suffixes_to_cut = [" (женщины)", " (мужчины)", " (дети)", " (до 12 лет)", " (до 8 лет)", " (гандикап)",
			" (несоревновательная)", " (несоревновательный)", " (критериум)", " (д)", " (ю)"]

# Returns 2 params, distance and to_break.
# distance - stripped distance without suffixes and prefixes.
# if to_break, we just pass this distance and do not work with it
def process_distance(distance):
	res = distance.strip()
	to_break = False
	for suffix in suffixes_to_cut:
		res = cut_suffix(res, suffix)
	for prefix in prefixes_to_cut:
		res = cut_prefix(res, prefix)
	if "+" in res:
		to_break = True
	if "x" in res:
		to_break = True
	if res == "":
		to_break = True
	if res == "1 верста (1076 м)":
		res = "1076 м"
	elif res == "1/3 версты (359 м)":
		res = "359 м"
	elif res == "1/2 версты (538 м)":
		res = "538 м"
	elif res == "2/3 версты (717 м)":
		res = "717 м"
	elif res == "10 верст (10.670 км)":
		res = "10670 м"
	elif res == "12.2 версты (13 км)":
		res = "13000 м"
	elif res == "5 верст (5.330 км)":
		res = "5330 м"
	elif res == "40 верст (42.672 км)":
		res = "42672 м"
	elif res == "2 версты (1.870 км)":
		res = "1870 м"
	elif res == "2 версты (2152 м)":
		res = "2152 м"
	elif res == "5 верст (5.335 км)":
		res = "5335 м"
	elif res == "10 верст (10.668 км)":
		res = "10668 м"
	elif res == "20 верст (21.336 км)":
		res = "21336 м"
	elif res == "5 верст (5.334 км)":
		res = "5334 м"
	return res, to_break

# Print all distances from database
@group_required('admins', 'editors')
def distances(request):
	context = user_edit_vars(request.user)
	context['mylist'] = models.Distance.objects.annotate(
		num_races=Count('race', distinct=True)).order_by('distance_type', 'length')

	return render(request, "editor/distances.html", context)

@group_required('admins', 'editors')
def distance_details(request, distance_id=None, distance=None,
		frmDistance=None, frmForDistance=forms.ForDistanceForm(auto_id='frmForDistance_%s'), create_new=False):
	if distance_id and not distance: # False if we are creating new distance
		distance = get_object_or_404(models.Distance, pk=distance_id)

	if distance and not frmDistance:
		frmDistance = forms.DistanceForm(instance=distance)

	context = user_edit_vars(request.user)
	context['distance'] = distance
	context['frmDistance'] = frmDistance
	context['frmForDistance'] = frmForDistance
	context['create_new'] = create_new
	context['form_title'] = 'Создание новой дистанции' if create_new else 'Дистанция {} (id {})'.format(distance, distance.id)

	if not create_new:
		counts = OrderedDict()
		counts[models.Race._meta.db_table] = distance.race_set.count()
		counts['Фактические дистанции'] = distance.distance_real_set.count()
		counts[models.Split._meta.db_table] = distance.split_set.count()
		context['counts'] = counts

	return render(request, "editor/distance_details.html", context)

@group_required('admins')
def distance_changes_history(request, distance_id):
	distance = get_object_or_404(models.Distance, pk=distance_id)
	return changes_history(request, distance, distance.get_editor_url())

@group_required('admins')
def distance_update(request, distance_id):
	distance = get_object_or_404(models.Distance, pk=distance_id)
	ok_to_save = True
	if (request.method == 'POST') and request.POST.get('frmDistance_submit', False):
		form = forms.DistanceForm(request.POST, instance=distance)
		if form.is_valid():
			form.save()
			log_form_change(request.user, form, action=models.ACTION_UPDATE)
			messages.success(request, 'Дистанция «{}» успешно обновлена. Проверьте, всё ли правильно.'.format(distance))
			update_distance(request, distance)
			return redirect(distance.get_editor_url())
		else:
			messages.warning(request, "Дистанция не обновлена. Пожалуйста, исправьте ошибки в форме.")
	else:
		form = forms.DistanceForm(instance=distance)
	return distance_details(request, distance_id=distance_id, distance=distance, frmDistance=form)

@group_required('admins', 'editors')
def distance_create(request):
	distance = models.Distance()
	if (request.method == 'POST') and request.POST.get('frmDistance_submit', False):
		form = forms.DistanceForm(request.POST, instance=distance)
		if form.is_valid():
			form.instance.created_by = request.user
			distance = form.save()
			log_form_change(request.user, form, action=models.ACTION_CREATE)
			if (distance.name == '') and distance.distance_type:
				distance.name = distance.nameFromType()
				distance.save()
			messages.success(request, 'Дистанция «{}» успешно создана. Проверьте, всё ли правильно.'.format(distance))
			return redirect(distance.get_editor_url())
		else:
			messages.warning(request, "Дистанция не создана. Пожалуйста, исправьте ошибки в форме.")
	else:
		form = forms.DistanceForm(instance=distance)
	return distance_details(request, distance=distance, frmDistance=form, create_new=True)

@group_required('admins')
def distance_delete(request, distance_id):
	distance = get_object_or_404(models.Distance, pk=distance_id)
	has_dependent_objects = distance.has_dependent_objects()
	ok_to_delete = False
	if 'frmForDistance_submit' in request.POST:
		form = forms.ForDistanceForm(request.POST, auto_id='frmForDistance_%s')
		if form.is_valid():
			if has_dependent_objects:
				new_distance = form.cleaned_data['new_distance']
				if new_distance != distance:
						ok_to_delete = True
				else:
					messages.warning(request, 'Нельзя заменить дистанцию на неё же.')
			else: # There are no dependent races or splits, so we can delete it
				ok_to_delete = True
		else:
			messages.warning(request, "Дистанция не создана. Пожалуйста, исправьте ошибки в форме.")
	else:
		form = forms.ForDistanceForm(auto_id='frmForDistance_%s')
		messages.warning(request, "Вы не указали город для удаления.")

	if ok_to_delete:
		if has_dependent_objects:
			update_distance(request, distance, new_distance)
		models.log_obj_delete(request.user, distance)
		distance.delete()
		messages.success(request, 'Дистанция «{}» успешно удалена.'.format(distance))
		if has_dependent_objects:
			return redirect(new_distance.get_editor_url())
		else:
			return redirect('editor:distances')

	return distance_details(request, distance_id=distance_id, distance=distance, frmForDistance=form)
