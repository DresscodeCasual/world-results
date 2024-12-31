import bs4
import io
from unittest import TestCase
import os

from editor.scrape import parkrun

def ResultsFile(name: str, extension: str = 'html') -> str:
		return os.path.join(os.path.dirname(__file__), f'parkrun_golden/{name}.{extension}')

class ParkrunTestCase(TestCase):
		def test_ParseName(self):
				self.assertEqual(('Vasya Moy', 'PUPKIN'), parkrun.ParseName('Vasya Moy PUPKIN'))
				self.assertEqual(('Vasya', 'MOY PUPKIN'), parkrun.ParseName('Vasya MOY PUPKIN'))
				self.assertEqual(('Vasya', 'PUPKIN'), parkrun.ParseName('Vasya PUPKIN'))
				self.assertEqual(('VASYA', 'PUPKIN'), parkrun.ParseName('VASYA PUPKIN'))
				self.assertEqual(('Vasya', 'Pupkin'), parkrun.ParseName('Vasya Pupkin'))

		def test_RaceResults(self):
			with io.open(ResultsFile('cieszyn-2024-11-23'), encoding="utf8") as file_in:
				results = parkrun.RaceResults('', file_in.read())
				self.assertEqual(len(results), 28)
				self.assertEqual(results[0], {
					'place_raw': 1,
					'name_raw': 'Artur WIĘCŁAW',
					'lname_raw': 'WIĘCŁAW',
					'fname_raw': 'Artur',
          'runner_id_on_platform': 3018936,
					'gender_raw': 'M',
					'category_raw': 'VM45-49',
					'club_raw': '4 Muszkieter',
					'result_raw': '21:38',
					'comment_raw': 'PB 19:30',
				})
				self.assertEqual(results[24], {
					'place_raw': 26,
					'name_raw': 'Veronika MRLINOVÁ',
					'lname_raw': 'MRLINOVÁ',
					'fname_raw': 'Veronika',
          'runner_id_on_platform': 9968555,
					'gender_raw': 'F',
					'category_raw': 'VW40-44',
          'club_raw': '',
					'result_raw': '31:01',
					'comment_raw': 'Debiutant',
				})
