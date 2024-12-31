from django import forms
from django.contrib.auth.forms import PasswordChangeForm, SetPasswordForm

class LoginForm(forms.Form):
	email = forms.CharField(
		label='Адрес электронной почты',
		max_length=100,
		widget=forms.TextInput(attrs={'class':'form-control'}))
	password = forms.CharField(
		label='Пароль',
		widget=forms.PasswordInput(attrs={'class':'form-control'}))

class RegisterForm(forms.Form):
	lname = forms.CharField(
		label='Фамилия',
		max_length=100,
		required=True,
		widget=forms.TextInput(attrs={'class':'form-control'}))
	fname = forms.CharField(
		label='Имя',
		max_length=100,
		required=True,
		widget=forms.TextInput(attrs={'class':'form-control'}))
	midname = forms.CharField(
		label='Отчество (необязательно)',
		max_length=100,
		required=False,
		widget=forms.TextInput(attrs={'class':'form-control'})) 
	birthday = forms.DateField(
		label='Дата рождения',
		required=True,
		widget=forms.TextInput(attrs={'class':'form-control', 'type':'date'}))
	email = forms.EmailField(
		label='Адрес электронной почты',
		max_length=100,
		widget=forms.EmailInput(attrs={'class':'form-control'}))
	password = forms.CharField(
		label='Пароль (не меньше 6 символов)',
		min_length=6,
		widget=forms.PasswordInput(attrs={'class':'form-control'}))
	password_confirm = forms.CharField(
		label='Повторите пароль',
		min_length=6,
		widget=forms.PasswordInput(attrs={'class':'form-control'}))

class MyPasswordChangeForm(PasswordChangeForm):
	def __init__(self, *args, **kwargs):
		super(MyPasswordChangeForm, self).__init__(*args, **kwargs)
		for field in self.fields:
			self.fields[field].widget.attrs.update({'class': 'form-control'})

class MySetPasswordForm(SetPasswordForm):
	def __init__(self, *args, **kwargs):
		super(MySetPasswordForm, self).__init__(*args, **kwargs)
		for field in self.fields:
			self.fields[field].widget.attrs.update({'class': 'form-control'})
