# New groups processing

from django.core.management.base import BaseCommand

from starrating.aggr import localtools

class Command(BaseCommand):
	def handle(self, *args, **options):
		localtools.create_all_zero_records_for_new_groups()
