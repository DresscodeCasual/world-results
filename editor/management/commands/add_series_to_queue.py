from django.core.management.base import BaseCommand

from results import models
from editor.scrape import athlinks, mikatiming, nyrr, runsignup

class Command(BaseCommand):
	help = 'Process one more item from the protocol queue'
	def add_arguments(self, parser):
		parser.add_argument('--url', type=str, required=False)
		parser.add_argument('--platform', type=str, required=True)
		parser.add_argument('--platform_series_id', type=str, required=False)
		parser.add_argument('--distance', type=str, required=False) # For mikatiming
		parser.add_argument('--extra_data', type=str, required=False) # For mikatiming
		parser.add_argument('--series_id', type=int, required=False)
		parser.add_argument('--event_id', type=int, required=False)
		parser.add_argument('--limit', type=int, required=False)
		parser.add_argument('--page', type=int, required=False)
		parser.add_argument('--check_already_loaded_series', action='store_true')
		# parser.add_argument('--end_prev_attempts', action='store_true')

	def handle(self, *args, **options):
		if options['platform'] == 'athlinks':
			if not options['platform_series_id']:
				raise Exception('For athlinks, you have to provide --platform_series_id.')
			print(athlinks.AthlinksScraper.AddSeriesEventsToQueue(platform_series_id=options['platform_series_id'], series_id=options.get('series_id'), debug=1))
		elif options['platform'] == 'nyrr':
			print(nyrr.NyrrScraper.AddEventsToQueue(for_all_years=True, limit=options['limit'], debug=1))
		elif options['platform'] == 'runsignup':
			print(runsignup.RunsignupScraper.AddEventsToQueue(limit=options['limit'],
				page=options['page'],
				check_already_loaded_series=options['check_already_loaded_series'],
				debug=1))
		elif options['platform'] == 'mikatiming':
			if not options['url']:
				raise Exception('For mikatiming, you have to provide --url.')
			if options['distance']: # So we're adding a page with many events
				if not options['series_id']:
					raise Exception('For mikatiming with distance, you have to provide --series_id.')
				return mikatiming.AddEventsToQueue(series_id=options['series_id'], series_url=options['url'], distance_name=options['distance'])
			if not options['event_id']:
				raise Exception('For mikatiming, you have to provide --event_id.')
			models.Scraped_event.objects.create(
				url_site=options['url'],
				url_results=options['url'],
				event_id=options['event_id'],
				extra_data=options.get('extra_data', ''),
				platform_id='mikatiming',
			)
		else: # e.g. trackshackresults
			platform = models.Platform.objects.get(pk=options['platform'])
			if not options['event_id']:
				raise Exception('You have to provide --event_id.')
			models.Scraped_event.objects.create(
				url_site=options['url'],
				url_results=options['url'],
				event_id=options['event_id'],
				platform=platform,
			)
		# else:
		# 	raise Exception(f'Unknown platform {options["platform"]}')
