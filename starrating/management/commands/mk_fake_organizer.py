from django.core.management.base import BaseCommand

# When deploing into production sever this script must be run
# before migrations for results application.
# (Because fake organizer is needed for migrations of Series model
# to satisfy a foreign key constraint)

from starrating.utils import db_init

class Command(BaseCommand):
	def handle(self, *args, **options):
		db_init.mk_fake_organizer()
