from django.core.management.base import BaseCommand

from starrating.aggr import checkers

class Command(BaseCommand):
	def handle(self, *args, **options):
		checkers.check_method_1(show_each=10)
