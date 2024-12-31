import datetime
from unittest import TestCase

from editor.scrape import util

class UtilTestCase(TestCase):
	def test_runner_shard(self):
		self.assertEqual('AK', util.runner_shard('spartak'))
		self.assertEqual('99', util.runner_shard('id1299'))
		self.assertEqual('K', util.runner_shard('k'))
		self.assertEqual('__', util.runner_shard('фф'))
		self.assertEqual('_', util.runner_shard('Ъ'))
		self.assertEqual('__', util.runner_shard('&&'))
		with self.assertRaises(RuntimeError):
			util.runner_shard('')
		with self.assertRaises(RuntimeError):
			util.runner_shard('   ')

	def test_MaxBirthday(self):
		self.assertEqual(datetime.date(2005, 1, 1), util.MaxBirthday(today=datetime.date(2020, 1, 1), age_today=15))
		self.assertEqual(datetime.date(2005, 2, 28), util.MaxBirthday(today=datetime.date(2020, 2, 29), age_today=15))
		self.assertEqual(datetime.date(2004, 2, 29), util.MaxBirthday(today=datetime.date(2020, 2, 29), age_today=16))
		self.assertEqual(datetime.date(2005, 3, 1), util.MaxBirthday(today=datetime.date(2020, 3, 1), age_today=15))

	def test_MinBirthday(self):
		self.assertEqual(datetime.date(2004, 1, 2), util.MinBirthday(today=datetime.date(2020, 1, 1), age_today=15))
		self.assertEqual(datetime.date(2004, 3, 1), util.MinBirthday(today=datetime.date(2020, 2, 29), age_today=15))
		self.assertEqual(datetime.date(2003, 3, 1), util.MinBirthday(today=datetime.date(2020, 2, 29), age_today=16))
		self.assertEqual(datetime.date(2004, 3, 2), util.MinBirthday(today=datetime.date(2020, 3, 1), age_today=15))
