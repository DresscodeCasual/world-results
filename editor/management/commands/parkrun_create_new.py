from django.core.management.base import BaseCommand

from editor.views.views_parkrun import create_future_events_once

class Command(BaseCommand):
	help = 'Creates Russian parkrun events for the next month'

	def handle(self, *args, **options):
		create_future_events_once(debug=True)
