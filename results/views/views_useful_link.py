from django.shortcuts import render, redirect
from django.contrib import messages

from results import models
from results.forms import UsefulLinkSuggestForm
from editor.forms import UsefulLinkForm, UsefulLabelForm
from .views_common import user_edit_vars
from . import views_mail

def useful_links(request, frmSuggestLink=None):
	context = user_edit_vars(request.user)
	context['page_title'] = 'Полезные ссылки'
	context['links_by_label'] = models.Useful_label.objects.prefetch_related('useful_link_set')
	all_labeled_links = set(models.Link_label.objects.values_list('link_id', flat=True))
	context['links_wo_label'] = models.Useful_link.objects.exclude(pk__in=all_labeled_links).order_by('name')
	if context['is_admin']:
		context['frmNewLink'] = UsefulLinkForm()
		context['frmNewLabel'] = UsefulLabelForm()
	else:
		if frmSuggestLink is None:
			frmSuggestLink = UsefulLinkSuggestForm(user=request.user)
		context['frmSuggestLink'] = frmSuggestLink

	return render(request, 'results/useful_links.html', context)

def suggest_link(request):
	if request.method == 'POST':
		form = UsefulLinkSuggestForm(request.POST, user=request.user)
		if form.is_valid():
			link = form.save(commit=False)
			views_mail.send_suggest_useful_link_mail(request.user, form.cleaned_data)
			messages.success(request, f'Предложение добавить ссылку «{link.name}» на страницу {link.url} успешно отправлено. Спасибо!')
			return redirect('results:useful_links')
		else:
			link = form.instance
			messages.warning(request,
				f'Отправить предложение добавить ссылку «{link.name}» на страницу {link.url} не получилось. Пожалуйста, исправьте ошибки ниже')
	else:
		form = UsefulLinkSuggestForm(user=request.user)
	return useful_links(request, frmSuggestLink=form)
