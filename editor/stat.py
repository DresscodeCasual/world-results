import datetime
from typing import Optional

from results import models

def set_stat_value(name, value, today: Optional[datetime.date] = None) -> str: # Saving this way for last_update to update
	if today is None:
		today = datetime.date.today()
	stat, _ = models.Statistics.objects.get_or_create(name=name, date_added=today)
	stat.value = value
	stat.save()
	return f'{name}={value}'
	# print("{}: {} = {}".format(datetime.datetime.now(), name, value))

def get_stat_value(name):
	stat = models.Statistics.objects.filter(name=name).order_by('-date_added').first()
	return stat.value if stat else None

def update_events_count() -> str:
	today = datetime.date.today()
	good_events = models.Event.objects.filter(invisible=False, cancelled=False)
	return '\n'.join([
		set_stat_value(
			'n_events_in_past',
			good_events.filter(start_date__lte=today).count(),
			today),
		set_stat_value(
			'n_events_in_future',
			good_events.filter(start_date__gte=today).count(),
			today),
		set_stat_value(
			'n_events_this_week',
			good_events.filter(start_date__gte=today, start_date__lte=today + datetime.timedelta(days=7)).count(),
			today),
	])

def update_results_count() -> str:
	today = datetime.date.today()
	return '\n'.join([
			set_stat_value('n_results', models.Result.objects.count(), today),
			set_stat_value('n_results_with_runner', models.Result.objects.exclude(runner=None).count(), today),
			set_stat_value('n_results_with_user', models.Result.objects.exclude(user=None).count(), today),
	])
