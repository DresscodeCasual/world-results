from django.core.management.base import BaseCommand

from editor import cities

class Command(BaseCommand):
	help = 'Process the Excel file with US cities'
	def add_arguments(self, parser):
		parser.add_argument('--path', type=str, required=True)

	def handle(self, *args, **options):
		if 'uscities' in options['path']:
			cities.parse_simplemaps_us(options['path'])
			return
		if 'worldcities' in options['path']:
			cities.parse_simplemaps_world(options['path'])
			return
		print('Strange file name!')		
