from django.core.management.base import BaseCommand

from starrating.utils import db_init, fake_rating
from starrating.models import Method
from starrating.constants import CURRENT_METHOD

class Command(BaseCommand):
	def handle(self, *args, **options):
		db_init.db_init_from_scratch()

		db_init.delete_all_ratings()
		fake_rating.generate_sample_primary_ratings(90.0)

		m = Method.objects.get(pk=CURRENT_METHOD)
		m.is_actual = True
		m.save()

		db_init.mark_all_groups_new()
