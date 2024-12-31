from django.core.management.base import BaseCommand
from editor.views import views_age_group_record

class Command(BaseCommand):
	help = 'fill_record_protocols'

	def handle(self, *args, **options):
		views_age_group_record.fill_record_protocols()
