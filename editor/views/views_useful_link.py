from django.shortcuts import get_object_or_404, render, redirect
from django.contrib import messages

from results import models, results_util
from editor import forms
from . import views_common

DEFAULT_GAP = 100

def get_new_label_priority(label_to_set_before_id):
	if label_to_set_before_id == 0:
		max_label = models.Useful_label.objects.order_by('-priority').first()
		if max_label:
			return max_label.priority + DEFAULT_GAP
		return 0

	label_to_set_before = get_object_or_404(models.Useful_label, pk=label_to_set_before_id)
	b = label_to_set_before.priority
	label_to_set_after = models.Useful_label.objects.filter(priority__lt=b).order_by('-priority').first()
	if label_to_set_after is None:
		return b - DEFAULT_GAP
	a = label_to_set_after.priority
	if (b - a) > 1:
		return (a + b) // 2
	for label in list(models.Useful_label.objects.filter(priority__ge=b)):
		label.priority += (2 * DEFAULT_GAP)
		label.save()
	return a + DEFAULT_GAP

@views_common.group_required('admins')
def add_link(request):
	if request.method == 'POST':
		form = forms.UsefulLinkForm(request.POST)
		if form.is_valid():
			link = form.save(commit=False)
			link.created_by = request.user
			link.save()
			form.save_m2m()
			messages.success(request, f'Ссылка {link.name} на страницу {link.url} успешно создана')
		else:
			messages.warning(request, f'Почему-то добавить ссылку {form.cleaned_data["name"]} на страницу {form.cleaned_data["url"]} не получилось :( {form.non_field_errors}')
			for field in form:
				if field.errors:
					messages.warning(request, f'{field.name}: {field.errors}')
	return redirect('results:useful_links')

@views_common.group_required('admins')
def add_label(request):
	if request.method == 'POST':
		form = forms.UsefulLabelForm(request.POST)
		if form.is_valid():
			label = form.save(commit=False)
			label.created_by = request.user
			if not models.Useful_label.objects.filter(name=label.name).exists():
				label.priority = get_new_label_priority(results_util.int_safe(form.cleaned_data['insert_before']))
				label.save()
				messages.success(request, f'Метка {label.name} успешно создана')
			else:
				messages.warning(request, f'Метка {label.name} уже есть. Ничего не делаем')
		else:
			messages.warning(request, f'Почему-то добавить метку {form.cleaned_data["name"]} не получилось :( {form.non_field_errors}')
			for field in form:
				if field.errors:
					messages.warning(request, f'{field.name}: {field.errors}')
	return redirect('results:useful_links')

@views_common.group_required('admins')
def link_details(request, link_id):
	link = get_object_or_404(models.Useful_link, pk=link_id)

	if request.method == 'POST':
		form = forms.UsefulLinkForm(request.POST, instance=link)
		if form.is_valid():
			link = form.save()
			messages.success(request, f'Ссылка «{link.name}» на страницу {link.url} успешно обновлена')
			return redirect('results:useful_links')
		else:
			messages.warning(request, f'Обновить ссылку {link.name} на страницу {link.url} не получилось')
	else:
		form = forms.UsefulLinkForm(instance=link)

	context = {}
	context['link'] = link
	context['frmLink'] = form
	return render(request, "editor/useful_link_details.html", context)

@views_common.group_required('admins')
def link_changes_history(request, link_id):
	link = get_object_or_404(models.Useful_link, pk=link_id)
	return views_common.changes_history(request, link, link.get_editor_url())
