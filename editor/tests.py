import decimal
from unittest import TestCase
from typing import Optional

from results import models, results_util
from editor import parse_strings, runner_stat
from editor.views import views_common, views_klb_stat, views_protocol

# After adding a new test, also add it to commands/run_tests.py!

class StaticTest(TestCase):
	def setUp(self):
		self.dist_marathon = models.Distance.objects.get(pk=results_util.DIST_MARATHON_ID)
		self.dist_10km = models.Distance.objects.get(pk=results_util.DIST_10KM_ID)
		self.dist_3km = models.Distance.objects.get(pk=results_util.DIST_3KM_ID)
		self.dist_1500m = models.Distance.objects.get(pk=results_util.DIST_1500M_ID)
		self.dist_400m = models.Distance.objects.get(pk=results_util.DIST_400M_ID)
		self.dist_100m = models.Distance.objects.get(pk=results_util.DIST_100M_ID)
		self.dist_60m = models.Distance.objects.get(pk=results_util.DIST_60M_ID)
		self.dist_1hour = models.Distance.objects.get(pk=results_util.DIST_1HOUR_ID)
		self.dist_racewalking_5km = models.Distance.objects.get(pk=results_util.DIST_RACEWALKING_5KM_ID)

	def _check_string2centiseconds(self, s, distance, tup_expected, should_fail=False):
		res, tup = views_protocol.parse_string_to_time(s, distance)
		if should_fail:
			self.assertFalse(res)
		else:
			self.assertTrue(res)
			self.assertTrue(0 <= tup[1] <= 59)
			self.assertTrue(0 <= tup[2] <= 59)
			if len(tup) > 3:
				self.assertTrue((tup[3] % 10000) == 0)
				self.assertTrue(0 <= (tup[3] // 10000) <= 99)
			self.assertEqual(views_protocol.tuple2centiseconds(tup, distance.length), models.tuple2centiseconds(*tup_expected))

	def _check_number2centiseconds(self, x, distance, tup_expected, should_fail=False):
		res, tup = views_protocol.parse_number_to_time(x, distance.length)
		if should_fail:
			self.assertFalse(res)
		else:
			self.assertTrue(res)
			self.assertEqual(tup, models.tuple2centiseconds(*tup_expected))

	def _check_string2meters(self, s, distance, expected, should_fail=False):
		res, got = views_protocol.parse_string_to_meters(s, distance)
		if should_fail:
			self.assertFalse(res)
		else:
			self.assertTrue(res)
			self.assertEqual(got, expected)

	def _check_string2distance(self, distance: str, distance_type: Optional[int],
			length_wanted: int, dist_type_wanted: int, should_return_none: bool=False):
		distance_got = parse_strings.parse_distance(distance, distance_type=distance_type)
		if should_return_none:
			self.assertIsNone(distance_got)
		else:
			self.assertIsNotNone(distance_got)
			self.assertEqual(distance_got.length, length_wanted)
			self.assertEqual(distance_got.distance_type, dist_type_wanted)

	def test_parse_string2time(self):
		self._check_string2centiseconds('54,49', self.dist_marathon, (0, 54, 49))
		self._check_string2centiseconds('54,49', self.dist_400m, (0, 0, 54, 49))
		self._check_string2centiseconds('65,27', self.dist_400m, (0, 1, 5, 27))
		self._check_string2centiseconds('54,49', self.dist_100m, (0, 0, 54, 49))
		self._check_string2centiseconds('6:23:45', self.dist_marathon, (6, 23, 45))
		self._check_string2centiseconds('6:23.45', self.dist_marathon, (6, 23, 45))
		self._check_string2centiseconds('6:23,45', self.dist_marathon, (6, 23, 45))
		self._check_string2centiseconds('6ч23м45с', self.dist_marathon, (6, 23, 45))
		self._check_string2centiseconds('6.23.45', self.dist_marathon, (6, 23, 45))
		self._check_string2centiseconds('6:23:45.67', self.dist_marathon, (6, 23, 45, 67))
		self._check_string2centiseconds('6:23:45:67', self.dist_marathon, (6, 23, 45, 67))
		self._check_string2centiseconds('10,428', self.dist_100m, (0, 0, 10, 43))
		self._check_string2centiseconds('01:23', self.dist_400m, (0, 1, 23))
		self._check_string2centiseconds('03:12', self.dist_400m, (0, 3, 12))
		self._check_string2centiseconds('24:36,49', self.dist_racewalking_5km, (0, 24, 36, 49))
		self._check_string2centiseconds('0:10.16', self.dist_3km, (0, 10, 16))
		self._check_string2centiseconds('8:03.14', self.dist_3km, (0, 8, 3, 14))
		self._check_string2centiseconds('9.0', self.dist_60m, (0, 0, 9))
		self._check_string2centiseconds('9,0', self.dist_60m, (0, 0, 9))
		self._check_string2centiseconds('9.1', self.dist_60m, (0, 0, 9, 10))
		self._check_string2centiseconds('63,55', self.dist_400m, (0, 1, 3, 55))
		self._check_string2centiseconds('38,54,2', self.dist_10km, (0, 38, 54, 20))
		self._check_string2centiseconds('38,54,17', self.dist_10km, (0, 38, 54, 17))
		# self._check_string2centiseconds(u'', self.dist_marathon, (, , ))
		# self._check_string2centiseconds(u'', self.dist_marathon, (, , ))

	def test_parse_number2time(self):
		self._check_number2centiseconds(6.51, self.dist_1500m, (0, 6, 51))
		self._check_number2centiseconds(6.81, self.dist_1500m, (), should_fail=True)
		self._check_number2centiseconds(6.51, self.dist_100m, (0, 0, 6, 51))
		self._check_number2centiseconds(6.81, self.dist_100m, (0, 0, 6, 81))
		self._check_number2centiseconds(10.363, self.dist_100m, (0, 0, 10, 37))
		self._check_number2centiseconds(10.363, self.dist_marathon, (), should_fail=True)

	def test_parse_string2meters(self):
		self._check_string2distance('5000 м', None, 5000, models.TYPE_METERS)
		self._check_string2distance('10000 м', None, 10000, models.TYPE_METERS)
		self._check_string2distance('marathon', None, 42195, models.TYPE_METERS)
		self._check_string2distance('hAlF mArAtHoN', None, 21098, models.TYPE_METERS)
		self._check_string2distance('First Half Marathon', None, 21098, models.TYPE_METERS)
		self._check_string2distance('7km', None, 7000, models.TYPE_METERS)
		self._check_string2distance('12 km netto', None, 12000, models.TYPE_METERS)
		self._check_string2distance('.5mi run', None, 805, models.TYPE_METERS)
		self._check_string2distance('Run-1/2Mi', None, 805, models.TYPE_METERS)
		self._check_string2distance('Run-20K', None, 20000, models.TYPE_METERS)
		self._check_string2distance('Run 20K', None, 20000, models.TYPE_METERS)
		self._check_string2distance('Kids-1K', None, 1000, models.TYPE_METERS)
		self._check_string2distance('17.5 Mi Run', None, 28164, models.TYPE_METERS) # 1609.344*17.5
		self._check_string2distance('54.4 Mile Ultra Marathon', None, 87548, models.TYPE_METERS) # 1609.344*54.4
		self._check_string2distance('21097', models.TYPE_METERS, 21098, models.TYPE_METERS)

	def test_parse_meters(self):
		self.assertEqual(805, parse_strings.parse_meters(length_raw=0, name='0.5Mi Kids Run'))
		self.assertEqual(10000, parse_strings.parse_meters(length_raw=0, name='10K Run'))
		self.assertEqual(1000, parse_strings.parse_meters(length_raw=0, name='1000 meters'))
		self.assertEqual(8047, parse_strings.parse_meters(length_raw=0, name='Run-5Mi'))

class HTMLTest(TestCase):
	def test_replace_relative_links(self):
		origin1 = """
<body>
<img src="/relative/url/img.jpg" />
<img class="text-center" src="/relative/url/img.jpg"/>
<form action="/">
<a href='/relative/url/'>Note the Single Quote</a>
<img src="//site.com/protocol-relative-img.jpg" />
</body>
"""
		result1 = """
<body>
<img src="https://example.com/relative/url/img.jpg" />
<img class="text-center" src="https://example.com/relative/url/img.jpg"/>
<form action="https://example.com/">
<a href="https://example.com/relative/url/">Note the Single Quote</a>
<img src="//site.com/protocol-relative-img.jpg" />
</body>
"""
		self.maxDiff = None
		self.assertEqual(result1, views_common.fix_relative_links(bytes(origin1, 'utf-8'), 'https://example.com').decode('utf-8'))

	def test_extract_filename(self):
		self.assertEqual('', views_common.get_maybe_filename('https://example.com'))
		self.assertEqual('file.doc', views_common.get_maybe_filename('https://example.com/file.doc'))
		self.assertEqual('file.doc', views_common.get_maybe_filename('https://example.com/path/file.doc'))
		self.assertEqual('file.doc', views_common.get_maybe_filename('https://example.com/path/file.doc?key=val'))
		self.assertEqual('a.jpg', views_common.get_maybe_filename('https://www.instagram.com/a.jpg?hl=en&taken-by=nike'))

class KLBScoreTest(TestCase):
	def test_score_2022(self):
		self.assertEqual(decimal.Decimal('8.997'), views_klb_stat.get_sport_score(2022, 1992, 2, 42195, (135 * 60 + 29) * 100))

		self.assertEqual(
			((135 * 60 + 29) * 100, decimal.Decimal('8.997'), decimal.Decimal('0.211')),
			views_klb_stat.get_klb_score(2022, 1992, 2, 42195, (135 * 60 + 29) * 100),
		)

		self.assertEqual(decimal.Decimal('0.105'), views_klb_stat.length2bonus(20900, 2022))

class TrackerURLTest(TestCase):
	def test_1(self):
		self.assertEqual((7827045671, 1, False), results_util.maybe_strava_activity_number('https://www.strava.com/activities/7827045671'))
		self.assertEqual((12345, 1, False), results_util.maybe_strava_activity_number('strava.com/activities/12345'))
		self.assertEqual((9627927899, 2, False), results_util.maybe_strava_activity_number('https://connect.garmin.com/modern/activity/9627927899'))


class EddingtonTest(TestCase):
	def test_1(self):
		self.assertEqual( (3, 2), runner_stat.eddington([1000 * x for x in [1,2,3,4,5]]))
		self.assertEqual( (0, 1), runner_stat.eddington([1,2,3,4,5]))
		self.assertEqual( (1, 2), runner_stat.eddington([1,2,1001,4,5]))
		self.assertEqual( (41, 1), runner_stat.eddington([42195] * 41 + [41999]))
		self.assertEqual( (41, 1), runner_stat.eddington([42195] * 41 + [41999] * 1000))
		self.assertEqual( (42, 43), runner_stat.eddington([42195] * 1000))
