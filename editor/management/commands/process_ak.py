from django.core.management.base import BaseCommand

from results import models
from editor import one_time_scripts, parse_weekly_events
from editor.scrape import athlinks, athlinks_series, baa, main, nyrr, parkrun, parkrun_series
from editor.views import views_mail

class Command(BaseCommand):
	help = 'Worked with AK55 base. Now does strange things'

	def add_arguments(self, parser):
		parser.add_argument('--int1', type=int, required=False)
		parser.add_argument('--int2', type=int, required=False)

	def handle(self, *args, **options):
		# one_time_scripts.create_regions_per_country()
		# nyrr.print_events()
		# platform_event_id = '19Q10K'
		# s = nyrr.NyrrScraper(url=f'https://results.nyrr.org/event/{platform_event_id}/finishers', platform_series_id=platform_event_id, platform_event_id=platform_event_id)
		# s.SaveEventDetailsInStandardForm()
		# print(len(s.standard_form_dict['races'][0]['results']))
		# s.Process()
		# one_time_scripts.FixNyrrRunnerIDs()
		# athlinks.FilterSeriesWithOriginalResults(options['int1'], options['int2'])
		# views_mail.test_email()
		# one_time_scripts.UnrecognizedDistances()
		# print(nyrr.NyrrScraper.AddEventsToQueue())
		# print(models.send_panic_email('For Alexey from robot', 'I hope you will know why Spartak'))
		# print(parse_weekly_events.update_weekly_events())
		# one_time_scripts.PrintRussianCities()
		# baa.scrape2(1)
		# baa.AddMarathons()
		# print(parkrun_series.ProcessSeries())

		# print(athlinks_series.ProcessSeriesSegment())
		# one_time_scripts.DeleteRedundandNyrrResults()

		# one_time_scripts.WTC2024()

		parkrun.test_regex()
