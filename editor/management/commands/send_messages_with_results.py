# -*- coding: utf-8 -*-
from django.core.management.base import BaseCommand

from editor.views.views_user import send_messages_with_results

class Command(BaseCommand):
	help = "Sends newsletter to all users who didn't ask to stop"

	def handle(self, *args, **options):
		# print 'Filename:', options['filename']
		# print options['title']
		# print u'Title: "{}"'.format(options['title'].decode().encode('utf-8'))
		send_messages_with_results()
