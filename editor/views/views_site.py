from django.shortcuts import render, redirect
from django.contrib.auth.models import User
from django.contrib import messages
from django.conf import settings

from results import models, models_klb, results_util
from . import views_common

@views_common.group_required('editors', 'admins')
def memo_editor(request):
	context = {}
	context['page_title'] = 'Памятка редактору'
	return render(request, "editor/memo/memo_editor.html", context)

@views_common.group_required('admins')
def memo_admin(request):
	context = {}
	context['page_title'] = 'Памятка администратору'
	context['doc_types'] = models.DOCUMENT_TYPES
	return render(request, "editor/memo/memo_admin.html", context)

@views_common.group_required('admins')
def memo_templates(request):
	context = {}
	context['page_title'] = 'Шаблоны для писем'
	context['year'] = models_klb.CUR_KLB_YEAR
	context['SITE_URL'] = results_util.SITE_URL
	context['regulations_link'] = models_klb.get_regulations_link(models_klb.NEXT_KLB_YEAR if models_klb.NEXT_KLB_YEAR else models_klb.CUR_KLB_YEAR)
	return render(request, "editor/memo/memo_templates.html", context)

@views_common.group_required('editors', 'admins')
def memo_spelling(request):
	context = {}
	context['page_title'] = 'Рекомендации по текстам'
	return render(request, "editor/memo/memo_spelling.html", context)

@views_common.group_required('admins')
def memo_server(request):
	context = {}
	context['page_title'] = 'Сервер нашего сайта'
	return render(request, "editor/memo/memo_server.html", context)

@views_common.group_required('admins')
def memo_salary(request):
	context = {}
	context['page_title'] = 'Оплата работы на сайте'
	context['template_name'] = 'editor/memo/memo_salary.html'
	return render(request, "results/base_template.html", context)

@views_common.group_required('admins')
def memo_python(request):
	context = {}
	context['page_title'] = 'Инструкции по редактированию файлов Django по разным поводам'
	context['template_name'] = 'editor/memo/memo_python.html'
	return render(request, "results/base_template.html", context)

@views_common.group_required('admins')
def admin_work_stat(request):
	context = {}
	context['page_title'] = 'Кто сколько чего сделал в этом и прошлом году'
	context['template_name'] = 'generated/admin_work_stat.html'
	return render(request, "results/base_template.html", context)

@views_common.group_required('admins')
def search_by_id(request, id=None):
	context = {}
	phone_number = None
	id_is_number = False
	if id is None:
		id = request.GET.get("id_for_search", '').strip()
	if id == '':
		return redirect("results:races")
	elif models.is_phone_number_correct(id):
		phone_number = ''.join(c for c in id if c.isdigit())[-7:]
		id = None
	elif results_util.int_safe(id) > 0:
		id = results_util.int_safe(id)
		id_is_number = True
	elif models.Event.objects.filter(id_on_platform=id).exists():
		pass
	else:
		maybe_name = id.split()
		if len(maybe_name) == 2:
			if models.Runner.objects.filter(fname__istartswith=maybe_name[0], lname__istartswith=maybe_name[1]).exists():
				return redirect('results:runners', lname=maybe_name[1], fname=maybe_name[0])
		elif len(maybe_name) == 1:
			if models.Runner.objects.filter(lname=maybe_name[0]).exists():
				return redirect('results:runners', lname=maybe_name[0])
		return redirect("results:races", race_name=id)
	if id:
		context['page_title'] = f'Объекты с id={id}'
		context['id'] = id

		if id_is_number:
			context['series'] = models.Series.objects.filter(pk=id).first()
			context['event'] = models.Event.objects.filter(pk=id).first()
			context['race'] = models.Race.objects.filter(pk=id).select_related('distance', 'event').first()
			context['news'] = models.News.objects.filter(pk=id).select_related('event').first()
			context['city'] = models.City.objects.filter(pk=id).first()
			context['document'] = models.Document.objects.filter(pk=id).select_related('series', 'event').first()
			context['distance'] = models.Distance.objects.filter(pk=id).first()
			context['club'] = models.Club.objects.filter(pk=id).first()
			context['klb_person'] = models.Klb_person.objects.filter(pk=id).first()
			context['klb_team'] = models.Klb_team.objects.filter(pk=id).first()
			context['user'] = User.objects.filter(pk=id).select_related('user_profile').first()
			context['user_profile'] = models.User_profile.objects.filter(pk=id).select_related('user').first()
			context['runner'] = models.Runner.objects.filter(pk=id).first()
			context['table_update'] = models.Table_update.objects.filter(pk=id).first()
			context['result'] = models.Result.objects.filter(pk=id).select_related('race').first()
			context['klb_participant'] = models.Klb_participant.objects.filter(pk=id).select_related('klb_person', 'team').first()
			context['klb_result'] = models.Klb_result.objects.filter(pk=id).select_related('result__race', 'klb_participant__klb_person').first()
			context['club_member'] = models.Club_member.objects.filter(pk=id).select_related('runner', 'club').first()
			context['message'] = models.Message_from_site.objects.filter(pk=id).first()
			context['runners_by_platform_id'] = models.Runner_platform.objects.filter(value=id).select_related('runner')

		context['series_by_platform_id'] = models.Series_platform.objects.filter(value=id).select_related('series')
		context['events_by_platform_id'] = models.Event.objects.filter(id_on_platform=id)
		context['races_by_platform_id'] = models.Race.objects.filter(id_on_platform=id).select_related('event')
	elif phone_number:
		context['page_title'] = f'Участники КЛБМатчей с телефонами, содержащими {phone_number}'
		context['phone_number'] = phone_number
		context['participants_with_phone_number'] = models.Klb_participant.objects.filter(phone_number_clean__contains=phone_number).select_related(
			'team', 'klb_person').order_by('year', 'klb_person__lname', 'klb_person__fname')
	return render(request, "editor/search_by_id.html", context)

@views_common.group_required('admins')
def restart(request):
	messages.success(request, 'Django перезапущен')
	results_util.restart_django()
	return redirect(settings.MAIN_PAGE)
