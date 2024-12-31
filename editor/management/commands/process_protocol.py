from django.core.management.base import BaseCommand

from editor.views import views_protocol

BOOLEAN_PARAMS = ('try_load', 'try_get_gender_from_group', 'all_are_male', 'all_are_female')
class Command(BaseCommand):
	help = 'Loads results from XLS/XLSX protocol'

	def add_arguments(self, parser):
		parser.add_argument('--race', type=int, required=True)
		parser.add_argument('--sheet', type=int, default=0)
		parser.add_argument('--delete_old_results', action='store_true')
		for param in BOOLEAN_PARAMS:
			parser.add_argument('--' + param, action='store_true')

	def handle(self, *args, **options):
		# print 'Trying to call process_protocol with race_id', options['race'], ', sheet index', options['sheet'], ', try to load? ', options['try_load']
		# if options['delete_old_results']:
		# 	print 'Trying to delete old results!!'
		settings = {}
		if options['delete_old_results']:
			settings['save_old_results'] = views_protocol.OLD_RESULTS_DELETE_ALL
		for param in BOOLEAN_PARAMS:
			settings[param] = True if options[param] else False
		if settings['all_are_male'] and settings['all_are_female']:
			print('You cannot specify --all_are_male and --all_are_female at the same time.')
			return
		views_protocol.process_protocol(
			race_id=options['race'],
			sheet_index=options['sheet'],
			settings=settings
		)
