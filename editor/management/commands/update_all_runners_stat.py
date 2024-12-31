from django.core.management.base import BaseCommand

from editor import runner_stat

class Command(BaseCommand):
	help = 'Updates statistics for all runner for current year'

	def add_arguments(self, parser):
		parser.add_argument('-f', '--from', type=int, default=0, help='First runner_id to work with')

	def handle(self, *args, **options):
		runner_stat.update_runners_stat(id_from=options['from'], debug=1)
