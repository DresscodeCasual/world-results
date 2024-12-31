from django.core.management.base import BaseCommand

import datetime

from results import models
from editor.views import views_result

class Command(BaseCommand):
	help = 'Sends individual Message_from_site by id'

	def add_arguments(self, parser):
		parser.add_argument('race_id', type=int)

	def handle(self, *args, **options):
		start = datetime.datetime.now()
		race = models.Race.objects.get(pk=options['race_id'])
		print(views_result.fill_places(race=race))
		start2 = datetime.datetime.now()
		print(start2 - start)
		views_result.fill_race_headers(race=race)
		print(datetime.datetime.now() - start2)
