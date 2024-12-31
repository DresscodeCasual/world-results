from django.core.management.base import BaseCommand

from starrating.utils import db_init, fake_rating
from starrating.models import Method
from starrating.constants import CURRENT_METHOD

class Command(BaseCommand):
	def handle(self, *args, **options):
		db_init.db_init_from_scratch()

		db_init.delete_all_ratings()
		fake_rating.generate_random_primary_ratings(10.0, 30.0)
		fake_rating.generate_sample_reviews()

		m = Method.objects.get(pk=CURRENT_METHOD)
		m.is_actual = True
		m.save()

		db_init.mark_all_groups_new()
