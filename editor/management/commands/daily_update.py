from django.core.management.base import BaseCommand
from django.utils import timezone
import datetime

from results import models, results_util
from editor import generators, monitoring, parse_weekly_events, regions_visited, runner_stat, series_strike, stat
from editor.scrape import athlinks_series, nyrr, parkrun_series
from editor.views import views_stat, views_klb_stat, views_user, views_age_group_record, views_klb_report

def try_call_function(desc, func, **kwargs):
	function_call = models.Function_call.objects.create(
		name=func.__name__,
		args=', '.join('{}={}'.format(k, v) for k, v in list(kwargs.items())),
		description=desc,
		start_time=timezone.now(),
	)
	try:
		res = func(**kwargs)
		function_call.running_time = timezone.now() - function_call.start_time
		if res:
			function_call.result = str(res)[:1000]
		function_call.save()
	except Exception as e:
		function_call.error = repr(e)[:100]
		function_call.save()

class Command(BaseCommand):
	help = 'Updates values in Statistics table and places in KLBMatch, connects results with birthdat to runners, creates new runners,' \
		+ ' sends results with recently attached results'

	def add_arguments(self, parser):
		parser.add_argument('--only_make_connections', action='store_true')

	def handle(self, *args, **options):
		# try_call_function('Обновление календаря забегов на ближайшие месяц и год', generators.generate_default_calendars)
		try_call_function('Обновление числа забегов в прошлом и будущем', stat.update_events_count)
		try_call_function('Обновление числа результатов в базе', stat.update_results_count)

		today = datetime.date.today()
		if today.weekday() in (0, 3):
			try_call_function('Просмотр части серий на Athlinks', athlinks_series.ProcessSeriesSegment)
		if today.weekday() == 1:
			try_call_function('Поиск новых серий на NYRR', nyrr.NyrrScraper.AddEventsToQueue)
			try_call_function('Загрузка результатов еженедельных забегов по вторникам', parse_weekly_events.update_weekly_events)
		if today.weekday() == 2:
			try_call_function('Поиск новых серий паркранов', parkrun_series.ProcessSeriesList)

		if (today.month == 2) and (today.day == 1):
			try_call_function(f'Обновление статистики всех бегунов для перехода на текущий {results_util.CUR_YEAR_FOR_RUNNER_STATS} год',
				runner_stat.update_runners_stat, reset_cur_year_stat=True)

		# if models.Strike_queue.objects.exists():
		# 	try_call_function('Обновление страйков у серий, где были привязаны к людям результаты', series_strike.calc_strikes_from_queue)

		# try_call_function('Присоединение результатов, создание бегунов, письмо от Робота Присоединителя', views_stat.make_connections)

		# try_call_function('Отправка писем пользователям о присоединенных результатах и включении в команды',
		# 	views_user.send_messages_with_results)

		monitoring.send_function_calls_letter()
