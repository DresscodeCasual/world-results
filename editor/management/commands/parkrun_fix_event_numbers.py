from django.core.management.base import BaseCommand

from editor.views.views_parkrun import fix_parkrun_numbers

class Command(BaseCommand):
	help = 'Loads all not loaded Russian parkrun results'

	def add_arguments(self, parser):
		parser.add_argument('-f', '--from', type=int, help='From what correct event should we start')

	def handle(self, *args, **options):
		event_id = options['from']
		series, n_fixed_parkruns = fix_parkrun_numbers(correct_event_id=event_id)
		print('{}: numbers fixed: {}'.format(series.name, n_fixed_parkruns))
