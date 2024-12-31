from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
        def handle(self, *args, **options):

                sql_commands = [
                        "SHOW VARIABLES LIKE '%timeout'",
                        "SHOW global VARIABLES LIKE '%timeout'",
                        "SHOW session VARIABLES LIKE '%timeout'",
                ]

                with connection.cursor() as cursor:
                        for command in sql_commands:
                                cursor.execute(command)
                                row = cursor.fetchall()
                                for line in row:
                                        print(line)
                                print('=====')
