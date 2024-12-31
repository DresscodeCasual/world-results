from django.shortcuts import get_object_or_404, render, redirect
from collections import OrderedDict
from django.contrib import messages
from django.db.models import Count

from typing import Tuple

from results import models
from editor import forms
from results.views.views_common import user_edit_vars
from .views_user_actions import log_form_change
from .views_common import group_required, update_city, changes_history

@group_required('admins', 'editors')
def cities(request, country_id=None, region_id=None, detailed=False):
	context = user_edit_vars(request.user)
	list_title = "Cities"
	conditions = []
	country = region = None
	initial = {}
	cities = models.City.objects.select_related('region__country')
	form = None
	if country_id:
		country = get_object_or_404(models.Country, pk=country_id)
		initial['country'] = country
	elif region_id:
		region = get_object_or_404(models.Region, pk=region_id)
		if region.is_active:
			initial['region'] = region
		else:
			initial['country'] = region.country
	elif 'frmSearchCity_submit' in request.GET:
		form = forms.CitySearchForm(request.GET)
		if form.is_valid():
			country = form.cleaned_data['country']
			region = form.cleaned_data['region']
			detailed = form.cleaned_data['detailed']

	if country:
		cities = cities.filter(region__country=country)
		conditions.append(' in country ' + country.name)

	if region:
		cities = cities.filter(region=region)
		conditions.append(' in region ' + region.name)

	if detailed:
		cities = cities.annotate(
			n_series=Count('series_city_set', distinct=True) + Count('series_city_finish_set', distinct=True),
			n_events=Count('event_city_set', distinct=True) + Count('event_city_finish_set', distinct=True),
			n_clubs=Count('club', distinct=True),
			n_klb_persons=Count('klb_person', distinct=True),
			n_users=Count('user_profile', distinct=True),
			n_results=Count('result', distinct=True),
			n_runners=Count('runner', distinct=True),
			)

	if form is None:
		form = forms.CitySearchForm(initial=initial)
	context['frmSearchCity'] = form
	context['detailed'] = detailed
	context['country'] = country
	if region:
		context['region'] = region
	elif country and not country.has_regions:
		context['region'] = country.region_set.first()
	context['list_title'] = list_title + ", ".join(conditions)
	context['page_title'] = context['list_title']

	if (not detailed) or (country and not country.has_regions) or region:
		context['cities'] = cities.order_by('name')
	else:
		context['msgInsteadCities'] = "Укажите регион или страну для отображения подробного списка городов. "\
			+ "Для России, Беларуси, Украины необходимо указать регион (страну можно не указывать)."

	return render(request, "editor/cities.html", context)

@group_required('admins', 'editors')
def city_details(request, city_id=None, city=None,
		frmCity=None, frmForCity=forms.ForCityForm(auto_id='frmForCity_%s'), create_new=False):
	if city_id and not city: # False if we are creating new city
		city = get_object_or_404(models.City, pk=city_id)

	if city and not frmCity:
		initial = {'region': city.region.id}
		frmCity = forms.CityForm(instance=city, initial=initial)

	context = user_edit_vars(request.user)
	context['city'] = city
	context['frmCity'] = frmCity
	context['frmForCity'] = frmForCity
	context['frmSearchCity'] = forms.CitySearchForm()
	context['create_new'] = create_new
	context['form_title'] = 'Создание нового города' if create_new else city.nameWithCountry()
	context['page_title'] = context['form_title']

	if not create_new:
		counts = OrderedDict()
		counts[models.Series._meta.db_table] = city.series_city_set.count() + city.series_city_finish_set.count()
		counts[models.Event._meta.db_table] = city.event_city_set.count() + city.event_city_finish_set.count()
		counts[models.Club._meta.db_table] = city.club_set.count()
		counts[models.Klb_person._meta.db_table] = city.klb_person_set.count()
		counts[models.Klb_participant._meta.db_table] = city.klb_participant_set.count()
		counts[models.User_profile._meta.db_table] = city.user_profile_set.count()
		counts[models.Runner._meta.db_table] = city.runner_set.count()
		counts[models.City_conversion._meta.db_table] = city.city_conversion_set.count()
		context['counts'] = counts
	return render(request, "editor/city_details.html", context)

@group_required('admins', 'editors')
def city_changes_history(request, city_id):
	city = get_object_or_404(models.City, pk=city_id)
	return changes_history(request, city, city.get_editor_url())

@group_required('admins')
def city_update(request, city_id):
	city = get_object_or_404(models.City, pk=city_id)
	if 'frmCity_submit' in request.POST:
		form = forms.CityForm(request.POST, instance=city)
		if form.is_valid():
			form.save()
			log_form_change(request.user, form, action=models.ACTION_UPDATE)
			messages.success(request, 'Город «{}» успешно обновлён. Проверьте, всё ли правильно.'.format(city))
			update_city(request, city)
			return redirect(city.get_editor_url())
		else:
			messages.warning(request, "Город не обновлён. Пожалуйста, исправьте ошибки в форме.")
	else:
		form = forms.CityForm(instance=city)

	return city_details(request, city_id=city_id, city=city, frmCity=form)

@group_required('admins', 'editors')
def city_create(request, region_id=None):
	city = models.City(created_by=request.user)
	if 'frmCity_submit' in request.POST:
		form = forms.CityForm(request.POST, instance=city)
		if form.is_valid():
			city = form.save()
			log_form_change(request.user, form, action=models.ACTION_CREATE)
			messages.success(request, 'Город «{}» успешно создан. Проверьте, всё ли правильно.'.format(city.name_full()))
			return redirect(city.get_editor_url())
		else:
			messages.warning(request, "Город не создан. Пожалуйста, исправьте ошибки в форме.")
	else:
		initial = {}
		if region_id:
			initial['region'] = get_object_or_404(models.Region, pk=region_id).id
		form = forms.CityForm(initial=initial)
	return city_details(request, city=city, frmCity=form, create_new=True)

# Returns <OK to delete?, warning message if not OK>
def ok_to_delete_city(city: models.City, new_city: models.City) -> Tuple[bool, str]:
	if new_city == city:
		return False, 'Нельзя заменить забег на себя же.'
	for event in city.event_city_set.all():
		if new_city.event_city_set.filter(series=event.series, start_date=event.start_date, start_time=event.start_time).exists():
			return False, f'В серии {event.series.name} (id {event.series.id}) уже есть забег в городе {new_city}, который пройдет {event.start_date}. Сначала удалите один из этих забегов.'
	return True, ''

@group_required('admins')
def city_delete(request, city_id):
	city = get_object_or_404(models.City, pk=city_id)
	has_dependent_objects = city.has_dependent_objects()
	ok_to_delete = False
	if 'frmForCity_submit' not in request.POST:
		form = None
		messages.warning(request, "Вы не указали город для удаления.")
	else:
		form = forms.ForCityForm(request.POST, auto_id='frmForCity_%s', city_required=has_dependent_objects)
		if not form.is_valid():
			messages.warning(request, "Город не удалён. Пожалуйста, исправьте ошибки в форме.")
		elif not has_dependent_objects:
			# There are no dependent objects of the city, so we just delete it
			ok_to_delete = True
		else:
			city_for = form.cleaned_data['city']
			ok_to_delete, warning = ok_to_delete_city(city, city_for)
			if not ok_to_delete:
				messages.warning(request, warning)
	if ok_to_delete:
		if has_dependent_objects:
			update_city(request, city, city_for)
		models.log_obj_delete(request.user, city)
		city.delete()
		messages.success(request, 'Город «{}» успешно удалён.'.format(city.name_full()))
		if has_dependent_objects:
			return redirect(city_for.get_editor_url())
		else:
			return redirect('editor:city_create')
	return city_details(request, city_id=city_id, city=city, frmForCity=form)
