# -*- coding: utf-8 -*-
from django.core.management.base import BaseCommand
import datetime

from results import results_util
from editor import generators

class Command(BaseCommand):
	help = 'Updates the full list of Russian series with all events in last three years'

	def handle(self, *args, **options):
		print(datetime.datetime.now())
		generators.generate_events_in_seria_by_year()
		results_util.restart_django()
		print(datetime.datetime.now())
		print('Finished!')
