from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login
from django.contrib.auth.models import User
from django.db.models import Q
from django.shortcuts import render, redirect

from results import models
from results.views.views_user import home
from editor import runner_stat, stat
from . import forms

def register_view(request, context={}):
	if request.user.is_authenticated:
		return home(request)

	if request.method != 'POST':
		return login_view(request)

	form = forms.RegisterForm(request.POST)
	context['registerForm'] = form
	if not form.is_valid():
		return login_view(request, context)

	lname = form.cleaned_data['lname'].strip()
	fname = form.cleaned_data['fname'].strip()
	midname = form.cleaned_data.get('midname', '').strip()
	email = form.cleaned_data['email'].strip()
	password = form.cleaned_data['password']
	password_confirm = form.cleaned_data['password_confirm']

	if lname == "":
		context['msgErrorRegister'] = "Вы не указали фамилию. Попробуйте ещё раз."
		return login_view(request, context)

	if fname == "":
		context['msgErrorRegister'] = "Вы не указали имя. Попробуйте ещё раз."
		return login_view(request, context)

	if password != password_confirm:
		context['msgErrorRegister'] = "Введённые пароли не совпадают. Попробуйте ещё раз."
		return login_view(request, context)

	if User.objects.filter(username=email).exists():
		context['msgErrorRegister'] = "Пользователь с таким адресом электронной почты уже зарегистрирован."
		return login_view(request, context)

	user = User.objects.create_user(email, email, password)
	user.first_name = fname
	user.last_name = lname
	user.save()
	
	user = authenticate(username=email, password=password)
	login(request, user)

	user_profile = models.User_profile.objects.create(
		user=user,
		midname=midname.title(),
		gender=models.Runner_name.gender_from_name(fname),
		birthday=form.cleaned_data['birthday'],
	)

	runners = models.Runner.objects.filter(user=None, lname=lname, fname=fname, birthday=form.cleaned_data['birthday'], birthday_known=True)
	if midname:
		runners = runners.filter(Q(midname='') | Q(midname=midname))
	existing_runner = runners.first()
	if existing_runner:
		existing_runner.user = user
		existing_runner.save()
		models.log_obj_create(user, existing_runner, models.ACTION_UPDATE, field_list=['user'], comment='При регистрации с данными уже существующего бегуна')
		existing_runner.result_set.update(user=user)
		runner_stat.update_runner_stat(user=user, update_club_members=False)
		messages.success(request, 'Мы привязали Вам похожие на Ваши результаты. Если это ошибка, пожалуйста, напишите нам на info@probeg.org.')
	else:
		user_profile.create_runner(user, comment='При регистрации пользователя')
	return redirect("results:my_details")

def login_view(request, context={}, test_mode=False):
	context['skip_adsense'] = True

	next_page = request.GET.get('next')
	if next_page:
		messages.warning(request, f'Для просмотра страницы {settings.MAIN_PAGE}{next_page} Вам нужно зарегистрироваться у нас на сайте или авторизоваться через любую соцсеть.')
		context['next_page_suffix'] = f'?next={next_page}'

	if 'registerForm' not in context:
		context['registerForm'] = forms.RegisterForm()

	context['n_events_in_past'] = stat.get_stat_value('n_events_in_past')
	context['n_events_in_future'] = stat.get_stat_value('n_events_in_future')
	context['n_events_this_month_RU_UA_BY'] = stat.get_stat_value('n_events_this_month_RU_UA_BY')
	context['n_results'] = stat.get_stat_value('n_results')
	context['n_results_with_runner'] = stat.get_stat_value('n_results_with_runner')
	if 'email' not in request.POST:
		context['loginForm'] = forms.LoginForm()
		context['get_params'] = str(request.GET)
		return render(request, 'auth/login.html', context=context)

	form = forms.LoginForm(request.POST) if ('btnLogin' in request.POST) else forms.LoginForm()
	context['loginForm'] = form
	if ('btnLogin' not in request.POST) or not form.is_valid():
		return render(request, 'auth/login.html', context=context)

	email = form.cleaned_data['email']
	password = form.cleaned_data['password']
	user = authenticate(username=email, password=password)

	if user is not None:
		if user.is_active:
			login(request, user)
			return redirect(next_page if next_page else "results:home")
		else:
			context['msgError'] = "Этот пользователь неактивен. Пожалуйста, обратитесь к администраторам, если нужно это исправить."
			return render(request, 'auth/login.html', context=context)
	elif 'btnLogin' in request.POST:
		context['msgError'] = "Такой пользователь не зарегистрирован, либо же Вы ошиблись в логине или пароле."
	return render(request, 'auth/login.html', context=context)
