from django.shortcuts import get_object_or_404, render, redirect
from django.contrib import messages

import datetime

from results import models
from editor import forms
from . import views_common, views_social, views_user_actions

@views_common.group_required('admins')
def news_details(request, news_id=None, news=None, cloned_news_id=None, frmNews=None, create_new=False):
	if not news: # False if we are creating new news
		news = get_object_or_404(models.News, pk=news_id)

	if news and not frmNews:
		frmNews = forms.NewsForm(instance=news, is_admin=True)

	context = {}
	context['news'] = news
	context['frmNews'] = frmNews
	context['create_new'] = create_new
	context['cloned_news_id'] = cloned_news_id

	if cloned_news_id:
		context['page_title'] = 'Клонирование новости'
	elif create_new:
		context['page_title'] = 'Создание новой новости'
	else:
		context['page_title'] = 'Новость «{}» (id {})'.format(news, news.id)
	return render(request, "editor/news_details.html", context)

@views_common.group_required('admins')
def news_changes_history(request, news_id):
	news = get_object_or_404(models.News, pk=news_id)
	return views_common.changes_history(request, news, news.get_absolute_url())

@views_common.group_required('admins')
def news_update(request, news_id):
	news = get_object_or_404(models.News, pk=news_id)
	if (request.method == 'POST') and request.POST.get('frmNews_submit', False):
		form = forms.NewsForm(request.POST, request.FILES, instance=news, is_admin=True)
		if form.is_valid():
			form.instance.clean_image_align()
			news = form.save()
			views_user_actions.log_form_change(request.user, form, action=models.ACTION_UPDATE, exclude=['country', 'region'])
			messages.success(request, 'Новость «{}» успешно обновлена. Проверьте, всё ли правильно.'.format(news))
			if ('image' in form.changed_data) and not news.make_thumbnail():
				messages.warning(request, "Не получилось уменьшить фото для новости с id {}.".format(news.id))
			return redirect(news.get_editor_url())
		else:
			messages.warning(request, "Новость не обновлена. Пожалуйста, исправьте ошибки в форме.")
	else:
		form = forms.NewsForm(instance=news, is_admin=True)
	return news_details(request, news_id=news_id, news=news, frmNews=form)

@views_common.group_required('admins')
def news_create(request, country_id=None, region_id=None, city_id=None, news_id=None):
	if news_id: # Clone news with this id
		news = get_object_or_404(models.News, pk=news_id)
		news.id = None
		news.date_posted = datetime.datetime.now()
	else:
		news = models.News()
	news.created_by = request.user
	if (request.method == 'POST') and request.POST.get('frmNews_submit', False):
		form = forms.NewsForm(request.POST, request.FILES, instance=news, is_admin=True)
		if form.is_valid():
			form.instance.clean_image_align()
			news = form.save()
			views_user_actions.log_form_change(request.user, form, action=models.ACTION_CREATE, exclude=['country', 'region'])
			if news.image:
				if not news.make_thumbnail():
					messages.warning(request, "Не получилось уменьшить фото для новости с id {}.".format(news.id))
			messages.success(request, 'Новость «{}» успешно создана. Проверьте, всё ли правильно.'.format(news))
			return redirect(news.get_editor_url())
		else:
			messages.warning(request, "Новость не создана. Пожалуйста, исправьте ошибки в форме.")
	else:
		initial = {}
		# if country_id:
		# 	initial['country'] = get_object_or_404(Country, pk=country_id)
		# if region_id:
		# 	initial['region'] = get_object_or_404(Region, pk=region_id)
		# 	initial['country'] = initial['region'].country
		# if city_id:
		# 	city = get_object_or_404(City, pk=city_id)
		# 	news.city = city
		# 	initial['city'] = city
		# 	if city.region.active:
		# 		initial['region'] = city.region
		# 	else:
		# 		initial['country'] = city.region.country
		form = forms.NewsForm(instance=news, initial=initial, is_admin=True)

	return news_details(request, news=news, frmNews=form, create_new=True, cloned_news_id=news_id)

@views_common.group_required('admins')
def news_delete(request, news_id):
	news = get_object_or_404(models.News, pk=news_id)
	ok_to_delete = False

	if (request.method == 'POST') and request.POST.get('frmDeleteNews_submit', False):
		models.log_obj_delete(request.user, news)
		news.delete()
		messages.success(request, 'Новость «{}» успешно удалена.'.format(news))
		return redirect('results:all_news')
	return news_details(request, news_id=news_id, news=news)

@views_common.group_required('editors', 'admins')
def news_post(request, news_id=None):
	news = get_object_or_404(models.News, pk=news_id)
	context, has_rights, target = views_common.check_rights(request, event=news.event)
	if not has_rights:
		return target
	news_posted = 0
	if request.method == 'POST':
		tweet = request.POST['twitter_text']
		for page in models.Social_page.objects.all():
			if 'page_' + str(page.id) in request.POST:
				result, post = views_social.post_news(request, page, news, tweet)
				if result:
					news_posted += 1
				else:
					messages.warning(request, 'Ошибка с публикацией в группу {}. Текст ошибки: {}'.format(page.url, post))
		if news_posted:
			messages.success(request, 'Опубликовано новостей: {}'.format(news_posted))
	if news.event:
		return redirect("results:event_details", event_id=news.event.id)
	else:
		return redirect("results:news_details", news_id=news.id)
