from django.core.management.base import BaseCommand

from starrating.utils.fake_rating import leave_one_rating

class Command(BaseCommand):
	def handle(self, *args, **options):
		leave_one_rating(empty=True)

