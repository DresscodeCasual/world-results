from django.shortcuts import render, redirect
from django.contrib import messages
from django.urls import reverse

import datetime
from typing import Any

from . import views_common
from editor import stat
from results import models, models_klb, results_util

def about(request):
	context = {}
	context['page_title'] = 'О сайте'
	context['site_age'] = results_util.CUR_YEAR - 2024
	context['n_events_thousands'] = models.Event.objects.filter(cancelled=False, invisible=False).count() // 1000
	return render(request, "static/about.html", context)

def contacts(request):
	context = {}
	context['page_title'] = 'Контактная информация'
	return render(request, "static/contacts.html", context)

def protocol(request):
	context = {}
	context['page_title'] = 'Стандарт протокола'
	return render(request, "static/protocol.html", context)

def social_links(request):
	context = {}
	context['page_title'] = 'ПроБЕГ в социальных сетях'
	return render(request, "static/social_links.html", context)

def how_to_help(request):
	context = {}
	context['page_title'] = 'Как вы можете помочь сайту «ПроБЕГ»'
	return render(request, "static/how_to_help.html", context)

def add_new_event(request):
	context = {}
	context['page_title'] = 'Как добавить новый забег в календарь на сайте «ПроБЕГ»?'
	context['user_is_authenticated'] = request.user.is_authenticated
	return render(request, "results/add_new_event.html", context)

def measurement_about(request):
	context = {}
	context['page_title'] = 'Сертификация трасс'
	context['certificates'] = models.Course_certificate.objects.select_related('series__city__region__country', 'distance').order_by(
		'-date_expires', 'series__name')
	return render(request, "measurement/about.html", context)

def login_problems(request):
	context = {}
	context['page_title'] = 'Частые проблемы при авторизации на нашем сайте'
	return render(request, "static/login_problems.html", context)

def archive(request):
	context = {}
	context['page_title'] = 'Архивные документы'
	return render(request, "static/archive.html", context)

def facebook_policy(request):
	context = {}
	context['page_title'] = 'Политика использования данных, полученных от социальной сети Facebook'
	return render(request, "static/facebook_policy.html", context)

def results_binding(request):
	context = {}
	context['page_title'] = 'О привязке результатов'
	context['n_results'] = stat.get_stat_value('n_results')
	context['n_results_with_user'] = stat.get_stat_value('n_results_with_user')
	return render(request, "results/results_binding.html", context)

def search_by_text(request):
	query = request.GET.get('query', '').strip()
	if query == '':
		messages.warning(request, 'Вы не указали никакую строку для поиска. Можно ввести любую часть названия забега или имя и фамилию бегуна')
		return redirect("results:races")
	if len(query) < 3:
		messages.warning(request, 'Вы указали слишком короткую строку для поиска. Введите хотя бы три символа')
		return redirect("results:races")
	maybe_name = query.split()
	if len(maybe_name) == 2:
		if models.Runner.objects.filter(fname__istartswith=maybe_name[0], lname__istartswith=maybe_name[1]).exists():
			return redirect('results:runners', fname=maybe_name[0], lname=maybe_name[1])
		if models.Runner.objects.filter(fname__istartswith=maybe_name[1], lname__istartswith=maybe_name[0]).exists():
			return redirect('results:runners', fname=maybe_name[1], lname=maybe_name[0])
	elif len(maybe_name) == 1:
		if models.Runner.objects.filter(lname=maybe_name[0]).exists():
			return redirect('results:runners', lname=maybe_name[0])
	return redirect('results:races', race_name=query)

N_FIRST_TEAMS = 3
N_FIRST_PERSONS = 10
N_FIRST_NEWS = 29
def main_page(request):
	context: dict[str, Any] = views_common.user_edit_vars(request.user)
	context['is_main_page'] = True
	context['page_title'] = 'World Results: your and others\' running results from all over the world'
	context['all_news'] = models.News.objects.select_related(
		'event__city__region__country', 'event__series__city__region__country', 'event__series__city_finish__region__country').filter(
		is_for_social=False).order_by('-date_posted')[:N_FIRST_NEWS]
	context['is_authenticated'] = request.user.is_authenticated

	if not context['is_authenticated']:
		context['n_events_in_past'] = stat.get_stat_value('n_events_in_past')
		context['n_results'] = stat.get_stat_value('n_results')
		context['n_results_with_runner'] = stat.get_stat_value('n_results_with_runner')
	if context['is_admin']:
		n_messages_not_sent = models.Message_from_site.objects.filter(is_sent=False, date_posted__date__gte=datetime.date.today() - datetime.timedelta(days=7)).count()
		if n_messages_not_sent > 1:
			messages.warning(request, f'За неделю не получилось отправить {n_messages_not_sent} писем!')
	return render(request, 'results/main_page.html', context=context)
