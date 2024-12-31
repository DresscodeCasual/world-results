from django.db.models import Count, Q
from django.contrib import messages
from django.shortcuts import render, redirect

from editor import forms
from editor.views import views_common
from results import models

@views_common.group_required('admins', 'editors')
def regions(request):
	if 'btnAddCountryConversionItem' in request.POST:
		form = forms.CountryConversionForm(request.POST)
		if form.is_valid():
			c = form.save()
			messages.success(request, f'Альтернативное название «{c.country_raw}» для страны {c.country.name} успешно добавлено')
		else:
			messages.warning(request, f'Альтернативное название не добавлено: {form.non_field_errors()[0]}')
		return redirect('editor:regions')

	context = {}
	context['list_title'] = 'Страны и регионы'
	context['regions'] = models.Region.objects.select_related('country').prefetch_related('country__country_conversion_set').filter(Q(is_active=1) | Q(country__has_regions=0)).annotate(
		num_cities=Count('city', distinct=True)).order_by('country__value', 'country__name', 'name')
	context['form'] = forms.CountryConversionForm()
	return render(request, 'editor/regions.html', context)
