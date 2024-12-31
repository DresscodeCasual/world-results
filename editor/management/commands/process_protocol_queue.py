from django.core.management.base import BaseCommand

from results import models
from editor.scrape import main

class Command(BaseCommand):
	help = 'Process one more item from the protocol queue'
	def add_arguments(self, parser):
		parser.add_argument('--url', type=str, required=False)
		parser.add_argument('--extra_data', type=str, required=False)
		parser.add_argument('--platform_event_id', type=str, required=False)
		# parser.add_argument('--end_prev_attempts', action='store_true')

	def handle(self, *args, **options):
		if options['url']:
			kwargs = {
				'url_site': options['url'],
				'extra_data': options.get('extra_data') or '',
			}
			if options['platform_event_id']:
				kwargs['platform_event_id'] = options['platform_event_id']
			row = models.Scraped_event.objects.get(**kwargs)
			print(main.process_queue_element(row))
		else:
			print(main.process_queue())

