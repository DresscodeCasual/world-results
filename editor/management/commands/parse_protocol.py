from django.core.management.base import BaseCommand

from editor import parse_athlinks

BOOLEAN_PARAMS = ('try_load', 'try_get_gender_from_group', 'all_are_male', 'all_are_female')
class Command(BaseCommand):
	help = 'Loads results from XLS/XLSX protocol'

	def add_arguments(self, parser):
		parser.add_argument('--url', type=str, required=True)
		parser.add_argument('--races_to_reload', nargs="+", type=int)
		# parser.add_argument('--sheet', type=int, default=0)
		parser.add_argument('--rewrite_protocol', action='store_true')
		# for param in BOOLEAN_PARAMS:
		# 	parser.add_argument('--' + param, action='store_true')

	def handle(self, *args, **options):
		athEvent = parse_athlinks.AthEvent(url=options['url'], races_to_reload=options['races_to_reload'] if options['races_to_reload'] else [], rewrite_protocol=options['rewrite_protocol'])
		# print(f'races_to_reload: {options["races_to_reload"]}')
		print(athEvent.try_load_event())
