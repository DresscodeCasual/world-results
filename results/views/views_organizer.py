# -*- coding: utf-8 -*-
from django.shortcuts import get_object_or_404, render
from django.db.models.query import Prefetch
from django.db.models import Count

import datetime
from typing import Any

from results import models
from .views_common import user_edit_vars

from starrating.utils.show_rating import get_sr_overall_data

def organizer_details(request, organizer_id):
	organizer = get_object_or_404(models.Organizer, pk=organizer_id)
	context: dict[str, Any] = user_edit_vars(request.user)
	context['page_title'] = 'Организатор забегов: {}'.format(organizer.name)
	context['organizer'] = organizer
	context['series_list'] = []
	today = datetime.date.today()

	context['sr_organizer'] = get_sr_overall_data(organizer, context['is_admin'])

	for series in organizer.series_set.annotate(Count('event')).order_by('-event__count'):
		events = series.event_set.filter(invisible=False, cancelled=False).order_by('-start_date', '-start_time')
		item = {}
		item['series'] = series
		item['n_events'] = events.count()
		item['event_next'] = events.filter(start_date__gt=today).last()
		item['event_prev'] = events.filter(start_date__lte=today).first()
		context['series_list'].append(item)
	return render(request, 'results/organizer_details.html', context)

def organizers(request):
	context = user_edit_vars(request.user)
	context['page_title'] = 'Организаторы забегов'
	context['organizers'] = models.Organizer.objects.select_related('user').prefetch_related(
			Prefetch('series_set', queryset=models.Series.objects.select_related('city__region__country', 'city_finish__region__country').annotate(
				n_events=Count('event')).order_by('name'))
		).annotate(n_series=Count('series')).order_by('name')
	# context['organizers'] = []
	# for organizer in organizers.order_by('name'):
	# 	context['organizers'].append((
	# 		organizer, 
	# 		organizer.series_set.select_related('city_finish__region__country', 'city__region__country').annotate(
	# 			n_events=Count('event')).order_by('name')
	# 	))
	return render(request, 'results/organizers.html', context)
