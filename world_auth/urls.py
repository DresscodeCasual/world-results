from django.contrib.auth import views as auth_views
from django.urls import path

from . import views, forms

app_name = 'auth'

urlpatterns = [
	path(r'login/', views.login_view, name='login'),
	path(r'logout/', auth_views.LogoutView.as_view(), name='logout'),
	path(r'register/', views.register_view, name='register'),
	path(r'password_change/', auth_views.PasswordChangeView.as_view(
			template_name='world_auth/password_change_form.html',
			success_url='/password_change/done/',
			form_class=forms.MyPasswordChangeForm,
		),
		name="password_change"),
	path(r'password_change/done/',
		auth_views.PasswordChangeDoneView.as_view(template_name='world_auth/password_change_done.html'),
		name='password_change_done'),
	path(r'password_reset/', auth_views.PasswordResetView.as_view(
			template_name='world_auth/password_reset_form.html',
			email_template_name='world_auth/password_reset_email.html',
			subject_template_name='world_auth/password_reset_subject.html',
			success_url='/password_reset/done',
		),
		name='password_reset'),
	path(r'password_reset/done/', auth_views.PasswordResetDoneView.as_view(
			template_name='world_auth/password_reset_done.html',
		),
		name='password_reset_done'),
	path(r'reset/<uidb64>/<token>/',
		auth_views.PasswordResetConfirmView.as_view(
			template_name='world_auth/password_reset_confirm.html',
			success_url='/reset/done/',
			form_class=forms.MySetPasswordForm,
			post_reset_login=True,
			post_reset_login_backend='django.contrib.auth.backends.ModelBackend',
		),
		name='password_reset_confirm'),
	path(r'reset/done/', auth_views.PasswordResetCompleteView.as_view(
			template_name='world_auth/password_reset_complete.html',
		),
		name='password_reset_complete'),
]
