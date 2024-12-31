from django.core.management.base import BaseCommand

from editor.views import views_mail

class Command(BaseCommand):
	help = 'Fills places to all race results'

	def add_arguments(self, parser):
		parser.add_argument('message_id', type=int)

	def handle(self, *args, **options):
		views_mail.send_old_messages(id_from=options['message_id'])
		# message = models.Message_from_site.objects.get(pk=options['message_id'])
		# if message.is_sent:
		# 	print(f'Message with id {options["message_id"]} is already sent. Skipping')
		# else:
		# 	print(message.try_send())
