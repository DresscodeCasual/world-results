from django.core.management.base import BaseCommand
import unittest

from editor import tests
from editor.scrape import runsignup_test, util_test

class Command(BaseCommand):
	help = 'Runs probeg tests'

	def handle(self, *args, **options):
		suite = unittest.TestLoader().loadTestsFromTestCase(tests.StaticTest)
		unittest.TextTestRunner(verbosity=2).run(suite)

		suite = unittest.TestLoader().loadTestsFromTestCase(tests.HTMLTest)
		unittest.TextTestRunner(verbosity=2).run(suite)

		# suite = unittest.TestLoader().loadTestsFromTestCase(tests.KLBScoreTest)
		# unittest.TextTestRunner(verbosity=2).run(suite)

		suite = unittest.TestLoader().loadTestsFromTestCase(tests.TrackerURLTest)
		unittest.TextTestRunner(verbosity=2).run(suite)

		suite = unittest.TestLoader().loadTestsFromTestCase(tests.EddingtonTest)
		unittest.TextTestRunner(verbosity=2).run(suite)

		# suite = unittest.TestLoader().loadTestsFromTestCase(runsignup_test.RunsignupTestCase)
		# unittest.TextTestRunner(verbosity=2).run(suite)

		suite = unittest.TestLoader().loadTestsFromTestCase(util_test.UtilTestCase)
		unittest.TextTestRunner(verbosity=2).run(suite)
