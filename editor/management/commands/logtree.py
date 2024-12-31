from django.core.management.base import BaseCommand

from .format import printout

class Command(BaseCommand):
        def handle(self, *args, **options):
                printout()

