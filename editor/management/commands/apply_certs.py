from django.core.management.base import BaseCommand
from editor.views import views_course

class Command(BaseCommand):
	help = 'Fix which certificate applies to which races'

	def handle(self, *args, **options):
		views_course.apply_certificates(debug=True)
