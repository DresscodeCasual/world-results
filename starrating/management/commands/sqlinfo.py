from django.core.management.base import BaseCommand
from django.db import connection

def print_query_result(query):
	with connection.cursor() as cursor:
		cursor.execute(query)
		for row in cursor.fetchall():
			print(row)

def main():
	print_query_result('show variables;')
#	print_query_result('show status;')


class Command(BaseCommand):
	def handle(self, *args, **options):
		main()
