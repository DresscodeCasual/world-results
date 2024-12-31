from django.core.management.base import BaseCommand

from starrating.utils import db_init

class Command(BaseCommand):
	def handle(self, *args, **options):
		db_init.mark_all_groups_new()
