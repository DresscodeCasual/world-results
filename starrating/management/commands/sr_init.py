from django.core.management.base import BaseCommand

from starrating.utils import db_init
from starrating.models import Method
from starrating.constants import CURRENT_METHOD

class Command(BaseCommand):
	def handle(self, *args, **options):
		db_init.db_init_from_scratch()

		db_init.delete_all_ratings()

		m = Method.objects.get(pk=CURRENT_METHOD)
		m.is_actual = True
		m.save()
