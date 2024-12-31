from django.db.models import Count, Sum
from django.db.models.query import Prefetch
from django.shortcuts import get_object_or_404, render

from collections import OrderedDict, Counter
import datetime
from typing import Any

from results import models
from results.views import views_common, views_race
from starrating.utils import show_rating

def get_prefetch_race_set():
	return Prefetch('race_set',
				queryset=views_race.add_races_annotations(models.Race.objects).select_related(
					'winner_male__user__user_profile', 'winner_male__runner',
					'winner_female__user__user_profile', 'winner_female__runner',
					'winner_nonbinary__user__user_profile', 'winner_nonbinary__runner',
					'distance_real')
			)

def series_details(request, series_id, tab=None):
	series = get_object_or_404(models.Series, pk=series_id)
	user = request.user
	context: dict[str, Any] = views_common.user_edit_vars(user, series=series)
	context['series'] = series

	# Otherwise there's no need to show cities of events
	context['city_needed'] = (series.city is None) or series.event_set.exclude(city=None).exclude(city=series.city).exists()

	events = series.event_set
	if not (context['is_admin'] or context['is_editor']):
		events = events.filter(invisible=False)

	today = datetime.date.today()
	events_in_past = events.filter(start_date__lte=today, cancelled=False, invisible=False)
	context['n_events_in_past'] = events_in_past.count()
	context['events_exist'] = events.exists()
	context['platforms'] = series.series_platform_set.order_by('platform_id', 'value').select_related('platform')

	if tab == 'all_events':
		context['active_tab'] = "all_events"
		events = events.prefetch_related(
			get_prefetch_race_set(),
			Prefetch('document_set',
				queryset=models.Document.objects.exclude(document_type__in=models.DOC_TYPES_NOT_FOR_RIGHT_COLUMN).order_by(
					'document_type', 'comment')
			)
		)
		if not (context['is_admin'] or context['is_editor']):
			events = events.filter(invisible=False)

		events = events.order_by('-start_date', '-start_time')

		if len(events) > 20:   # Temporary hack. Todo.
			events_list = [(event, None) for event in events]
		else:
			events_list = [(event, show_rating.get_sr_overall_data(event, context['to_show_rating'])) for event in events]

		context['events_list'] = events_list

	elif tab == 'races_by_event':
		context['active_tab'] = "races_by_event"
		events = events.annotate(
			n_participants_finished=Sum('race__n_participants_finished'),
			n_participants_finished_male=Sum('race__n_participants_finished_male'),
			n_participants_finished_female=Sum('race__n_participants_finished_female'),
			n_races=Count('race'),
		).prefetch_related(get_prefetch_race_set())
		if not (context['is_admin'] or context['is_editor']):
			events = events.filter(invisible=False)
		context['events'] = events.order_by('-start_date', '-start_time')
	elif tab == 'races_by_distance':
		context['active_tab'] = "races_by_distance"
		events_in_past_ids = set(events.filter(start_date__lte=today, cancelled=False, invisible=False).values_list('id', flat=True))
		context['races'] = [{'distance': str(race.distance), 'race': race}
			for race in models.Race.objects.filter(event_id__in=events_in_past_ids).select_related(
				'winner_male__user__user_profile', 'winner_male__runner',
				'winner_female__user__user_profile', 'winner_female__runner',
				'winner_nonbinary__user__user_profile', 'winner_nonbinary__runner',
				'event__city__region__country', 'event__series__city__region__country', 'distance', 'distance_real').order_by(
				'distance__distance_type', '-distance__length', '-event__start_date')
		]
	elif tab == 'reviews' and series.has_news_reviews_photos():
		context['active_tab'] = "reviews"
		links_dict = {}
		for doc_type, doc_type_name in ((models.DOC_TYPE_IMPRESSIONS, 'reviews'), (models.DOC_TYPE_PHOTOS, 'photos')):
			for doc in models.Document.objects.filter(event__series_id=series.id, document_type=doc_type).select_related('event'):
				if doc.event not in links_dict:
					links_dict[doc.event] = {'reviews': [], 'photos': [], 'news': []}
				links_dict[doc.event][doc_type_name].append(doc)
		for news in models.News.objects.filter(event__series_id=series.id).select_related('event').order_by('-date_posted'):
			if news.event not in links_dict:
				links_dict[news.event] = {'reviews': [], 'photos': [], 'news': []}
			links_dict[news.event]['news'].append(news)
		context['events_links'] = sorted(list(links_dict.items()), key=lambda x:x[0].start_date, reverse=True)
	elif tab == 'strikes':
		context['active_tab'] = 'strikes'
		strikes = series.strike_set.select_related('distance', 'runner__user__user_profile', 'first__event', 'last__event', 'first_in_row__event', 'last_in_row__event').order_by(
			'distance__distance_type', '-distance__length', '-total_participations', '-total_participations_in_row', 'runner__lname', 'runner__fname')
		context['distance_strikes'] = OrderedDict()
		for strike in strikes:
			if strike.distance not in context['distance_strikes']:
				context['distance_strikes'][strike.distance] = {'strikes': []}
			context['distance_strikes'][strike.distance]['strikes'].append(strike)
			# context['distance_strikes'].get(strike.distance, {'strikes': []})['strikes'].append(strike)
		for series_dist_data in series.series_distance_data_set.select_related('distance', 'first', 'last'):
			if series_dist_data.distance in context['distance_strikes']:
				context['distance_strikes'][series_dist_data.distance]['dist_data'] = series_dist_data

		context['MIN_FINISHES_FOR_STRIKE'] = models.MIN_FINISHES_FOR_STRIKE
		context['MIN_FINISHES_FOR_STRIKE_PERCENT'] = models.MIN_FINISHES_FOR_STRIKE_PERCENT
		context['MAX_STRIKES_FOR_SERIES'] = models.MAX_STRIKES_FOR_SERIES
	else:
		context['active_tab'] = 'default'

		future_events = events.filter(start_date__gt=today, cancelled=False, invisible=False)
		context['event_next'] = future_events.order_by('start_date').first()
		if context['event_next']:
			context['n_future_events'] = future_events.count() - 1 # Excluding event_next
			context['event_next_race_set'] = views_race.event_races_for_context(context['event_next'])
			if user.is_authenticated:
				context['calendar'] = user.calendar_set.filter(event=context['event_next']).first()
				context['user_is_authenticated'] = True

		event_prev = events_in_past.order_by('-start_date').first()
		if event_prev:
			context['event_prev'] = event_prev
			context['event_prev_race_set'] = views_race.event_races_for_context(event_prev).select_related('winner_male', 'winner_female')
			context['user_has_no_results_on_event_prev'] = user.is_authenticated \
				and not user.result_set.filter(race__event=event_prev).exists()

			sums = event_prev.race_set.aggregate(Sum('n_participants_finished'), Sum('n_participants_finished_male'), Sum('n_participants_finished_female'))
			context['event_prev_n_finishers'] = sums['n_participants_finished__sum'] if sums['n_participants_finished__sum'] else 0
			context['event_prev_n_finishers_male'] = sums['n_participants_finished_male__sum'] if sums['n_participants_finished_male__sum'] else 0
			context['event_prev_n_finishers_female'] = sums['n_participants_finished_female__sum'] if sums['n_participants_finished_female__sum'] else 0
			context['event_prev_has_results'] = context['event_prev_n_finishers'] > 0
			context['event_prev_has_partially_loaded_races'] = event_prev.race_set.filter(load_status=models.RESULTS_SOME_OFFICIAL).exists()

		if context['n_events_in_past'] > 1:
			context['event_first'] = events_in_past.order_by('start_date').first()
			races_by_distance = {}
			event_sizes_by_distance = {}
			events_size = {}
			male_records = {}
			female_records = {}
			nonbinary_records = {}
			for race in models.Race.objects.filter(event_id__in=events_in_past.values_list('id', flat=True)).select_related(
					'event', 'distance', 'distance_real',
					'winner_male__user__user_profile', 'winner_male__runner',
					'winner_female__user__user_profile', 'winner_female__runner',
					'winner_nonbinary__user__user_profile', 'winner_nonbinary__runner',
					):
				distance = race.distance

				if distance not in races_by_distance:
					races_by_distance[distance] = []
				races_by_distance[distance].append(race)

				if race.is_course_record_male:
					male_records[distance] = race
				if race.is_course_record_female:
					female_records[distance] = race
				if race.is_course_record_nonbinary:
					nonbinary_records[distance] = race

				if race.n_participants_finished:
					events_size[race.event] = events_size.get(race.event, 0) + race.n_participants_finished
					if distance not in event_sizes_by_distance:
						event_sizes_by_distance[distance] = Counter()
					event_sizes_by_distance[distance][race.event] += race.n_participants_finished

			context['n_prev_events_with_results'] = len(events_size)
			context['prev_distances'] = []
			for distance, races in sorted(list(races_by_distance.items()), key=lambda x: (x[0].distance_type, -x[0].length)):
				data = {}
				data['distance'] = distance
				data['n_starts'] = len(set(race.event_id for race in races))
				dates = sorted([(race.event.start_date, race) for race in races], key=lambda x: x[0])
				data['first_race'] = dates[0]
				data['last_race'] = dates[-1]
				if distance in event_sizes_by_distance:
					data['n_starts_with_results'] = len(event_sizes_by_distance[distance])
					data['max_event'], data['max_size'] = event_sizes_by_distance[distance].most_common(1)[0]
					data['mean_size'] = sum(event_sizes_by_distance[distance].values()) / data['n_starts_with_results']
				else:
					data['n_starts_with_results'] = 0
				data['race_with_male_record'] = male_records.get(distance)
				data['race_with_female_record'] = female_records.get(distance)
				data['race_with_nonbinary_record'] = nonbinary_records.get(distance)
				context['prev_distances'].append(data)

			if events_size:
				context['max_event_size'] = max(events_size.values())
				context['mean_event_size'] = sum(events_size.values()) / len(events_size)
				for event, size in list(events_size.items()):
					if size == context['max_event_size']:
						context['max_event'] = event
						break

	context['page_title'] = f'{series.name}: All Events in The Series'

	context['sr_series'] = show_rating.get_sr_overall_data(series, context['to_show_rating'])

	context['tabs'] = [('default', 'Overview')]
	if context['n_events_in_past'] > 0:
		context['tabs'].append(('races_by_distance', 'Results by distance'))
		context['tabs'].append(('races_by_event', 'Results by event'))
	if series.has_news_reviews_photos():
		context['tabs'].append(('reviews', 'News, reviews, photos'))
	if series.event_set.exists():
		context['tabs'].append(('all_events', 'All events in the series'))
	if series.strike_set.exists():
		context['tabs'].append(('strikes', 'Strikes'))

	return render(request, f'series/{context["active_tab"]}.html', context)
