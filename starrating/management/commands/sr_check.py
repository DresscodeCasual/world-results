from django.core.management.base import BaseCommand

import logging
from starrating.aggr import checkers

class Command(BaseCommand):
	def handle(self, *args, **options):
		lst = checkers.check_relationship_structure_of_aggregate_models(logger=logging.getLogger('sr_dbchecks'), fast=True)
		for item in lst:
			print(item)
		print("=== End of structure check")
		checkers.check_method_9(100)
