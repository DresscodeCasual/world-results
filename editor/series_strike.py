from results import models

from collections import Counter
import datetime
from typing import Any, Dict, List, Optional, Tuple

# Returns the ordered list of dates of events in given series with given distance,
# and checks that it happens not more than once a year.
# It is OK to have several races of same distance on one event (e.g. semifinals and finals, or handicapped race).
# But if there are two events with same start date, we raise an exception.
def race_dates_and_check_annuality(series: models.Series, distance: models.Distance) -> Tuple[List[datetime.date], bool]:
	is_annual_event = True
	events_by_date = {}
	events_by_year = {}
	for race in models.Race.objects.filter(event__series=series, distance=distance, event__cancelled=False, event__invisible=False).select_related('event'):
		date = race.event.start_date
		if date not in events_by_date:
			events_by_date[date] = race.event
		elif race.event != events_by_date[date]:
			raise Exception(f'В серии с id {series.id} есть сразу два забега, прошедшие {date}, с одной и той же дистанцией {distance}')
		if date.year not in events_by_year:
			events_by_year[date.year] = race.event
		elif race.event != events_by_year[date.year]:
			is_annual_event = False
	return sorted(events_by_date.keys()), is_annual_event

class Runner_strike:
	max_strike_length = 0
	max_strike_start = None
	max_strike_end = None
	first = None
	last = None
	first_in_row = None
	last_in_row = None
	def __init__(self, n_events):
		self.results: List[Any] = [None] * n_events
	def calc_strikes(self):
		cur_strike_length = 0
		cur_strike_start = None
		cur_strike_end = None
		for i, result in enumerate(self.results):
			if result is None:
				cur_strike_length = 0
				cur_strike_start = None
				continue

			if self.first is None:
				self.first = result.race
			self.last = result.race

			cur_strike_length += 1
			if cur_strike_start is None:
				cur_strike_start = i
			if cur_strike_length > self.max_strike_length:
				self.max_strike_length = cur_strike_length
				self.max_strike_start = cur_strike_start
				self.max_strike_end = i
		self.first_in_row = self.results[self.max_strike_start].race # pytype: disable=attribute-error
		self.last_in_row = self.results[self.max_strike_end].race    # pytype: disable=attribute-error
	def maybe_strike_obj(self, series, distance, runner, is_annual_event) -> Optional[models.Strike]: # To store in DB
		participations = [result for result in self.results if result is not None]
		if len(participations) < models.MIN_FINISHES_FOR_STRIKE:
			return None
		if len(participations) * 100 < len(self.results) * models.MIN_FINISHES_FOR_STRIKE_PERCENT:
			return None
		result_values = [result.result for result in participations if result.status == models.STATUS_FINISHED]
		self.calc_strikes()

		best_result = average_result = None
		if result_values:
			best_result = max(result_values) if (distance.distance_type in models.TYPES_MINUTES) else min(result_values)
			average_result = sum(result_values) / len(result_values)

		return models.Strike(
				series=series,
				distance=distance,
				runner=runner,
				total_participations=len(participations),
				total_participations_in_row=self.max_strike_length,
				is_annual_event=is_annual_event,
				best_result=best_result,
				average_result=average_result,
				first=self.first,
				last=self.last,
				first_in_row=self.first_in_row,
				last_in_row=self.last_in_row,
			)

# We want to save just MAX_STRIKES_FOR_SERIES strikes with largest total_participations, and also all strikes with the same value.
def filter_largest_strikes(strike_objs: List[models.Strike]) -> List[models.Strike]:
	if len(strike_objs) <= models.MAX_STRIKES_FOR_SERIES:
		return strike_objs
	strikes_sorted = sorted(strike_objs, key=lambda x: -x.total_participations)
	min_participations = strikes_sorted[models.MAX_STRIKES_FOR_SERIES - 1].total_participations
	return [strike_obj for strike_obj in strike_objs if strike_obj.total_participations >= min_participations]

# Returns the number of created strikes
def calc_strikes_for_distance(series: models.Series, distance: models.Distance, to_delete_old: bool=True) -> int:
	if to_delete_old:
		series.strike_set.filter(distance=distance).delete()
		series.series_distance_data_set.filter(distance=distance).delete()
	if series.id in (
			1664, # Wings For Life
			2057, # Бегущие сердца
			2273, # Стадионный марафон, Эстония
			3545, # Забег.рф
			3615, # Legal Run
			3735, # Достигая цели
			4006, # Witunia Weekend Maraton
			4792, # Iver Swim, плавание во многих городах
			5962, # первенство Приволжского федерального округа
			7365, # Зеленый марафон
			8328, # Легкоатлетический забег «На старт»
			):
		return 0
	event_dates, is_annual_event = race_dates_and_check_annuality(series, distance)
	if len(event_dates) < models.MIN_FINISHES_FOR_STRIKE:
		return 0
	event_dates_inv = {event_dates[i]: i for i in range(len(event_dates))}

	# Fill runner_strikes
	runner_strikes = {}
	events_with_results = set() # To determine first, last, count of events with at least one result.
	for result in models.Result.objects.filter(race__event__series=series, race__distance=distance, status__in=(models.STATUS_FINISHED, models.STATUS_COMPLETED)).exclude(
			runner=None).exclude(race__event__cancelled=True).exclude(race__event__invisible=True).select_related('runner', 'race__event').order_by('race__event__start_date'):
		events_with_results.add(result.race.event)
		if result.runner not in runner_strikes:
			runner_strikes[result.runner] = Runner_strike(len(event_dates))
		if result.race.event.start_date not in event_dates_inv:
			print('Here is the bug', result.id, result.race.id, result.race.event.start_date, event_dates_inv)
		runner_strikes[result.runner].results[event_dates_inv[result.race.event.start_date]] = result
	strike_objs = []
	for runner, runner_strike in runner_strikes.items():
		maybe_strike = runner_strike.maybe_strike_obj(series, distance, runner, is_annual_event)
		if maybe_strike:
			strike_objs.append(maybe_strike)

	largest_strikes = filter_largest_strikes(strike_objs)
	for strike_obj in largest_strikes:
		strike_obj.save()
	if largest_strikes:
		events_with_results_sorted = sorted(events_with_results, key=lambda event:event.start_date)
		models.Series_distance_data.objects.create(
			series=series,
			distance=distance,
			n_events=len(events_with_results_sorted),
			first=events_with_results_sorted[0],
			last=events_with_results_sorted[-1],
		)
	return len(largest_strikes)

def calc_strikes(series: models.Series) -> Dict[models.Distance, int]:
	series.strike_set.all().delete()
	series.series_distance_data_set.all().delete()
	res = {}
	distance_ids = Counter(models.Race.objects.filter(event__series=series).exclude(load_status=models.RESULTS_NOT_LOADED).values_list('distance_id', flat=True))
	for distance_id, count in distance_ids.items():
		if count >= models.MIN_FINISHES_FOR_STRIKE:
			distance = models.Distance.objects.get(pk=distance_id)
			res[distance] = calc_strikes_for_distance(series, distance, to_delete_old=False)
	return res

def calc_strikes_from_queue() -> str:
	n_pairs = n_strikes_found = 0
	for strike_queue in list(models.Strike_queue.objects.select_related('series', 'distance')):
		n_strikes_found += calc_strikes_for_distance(strike_queue.series, strike_queue.distance)
		n_pairs += 1
		strike_queue.delete()
	return f'обработано пар (серия, дистанция): {n_pairs}, найдено страйков: {n_strikes_found}'

def update_all_series(from_id=0):
	for series in models.Series.objects.filter(pk__gte=from_id).order_by('pk'):
		if (series.id % 1000) == 0:
			print(series.id)
		try:
			calc_strikes(series)
		except Exception as e:
			print(series.id, e)
