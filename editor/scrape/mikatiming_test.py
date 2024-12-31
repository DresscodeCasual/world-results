import bs4
import io
import json
import os
import pprint
from unittest import TestCase

from results import models
from editor.scrape import mikatiming

def ResultsFile(name: str, extension: str = 'html') -> str:
    return os.path.join(os.path.dirname(__file__), f'mikatiming_golden/{name}.{extension}')

class MikatimingTestCase(TestCase):
    def compare_result_page(self, content, expected):
      actual = mikatiming.MikaTimingScraper(attempt=models.Download_attempt()).ParseResultsPage(bs4.BeautifulSoup(content, 'html.parser'))
      # print(f'\n\nActual:\n{sorted(actual[0].items())}')
      # print(f'\n\nExpected:\n{sorted(expected[0].items())}')
      self.assertEqual(actual, expected, msg = pprint.pformat((actual, expected)))

    def test_parse_result_page(self):
      expected1 = [
        {
          'lname_raw': 'Heikura',
          'fname_raw': 'Kari',
          'name_raw': 'Heikura, Kari (FIN)',
          'country_raw': 'FIN',
          'bib_raw': '21442',
          'category_raw': 'M35',
          'club_raw': 'Polvijärven urheilijat',
          'gun_time_raw': '02:23:40',
          'result_raw': '02:23:30',
          'id_on_platform': 'HCH3C0OH73EB8',
          'place_gender_raw': 89,
          'place_category_raw': 19,
          'status_raw': 'FINISHED',
        },
        {
          'lname_raw': 'Elmore',
          'fname_raw': 'Malindi',
          'name_raw': 'Elmore, Malindi',
          'bib_raw': 'F17',
          'category_raw': 'W40',
          'club_raw': '',
          'gun_time_raw': '02:23:30',
          'result_raw': '02:23:30',
          'id_on_platform': 'HCH3C0OH7F7B0',
          'place_gender_raw': 13,
          'place_category_raw': 1,
          'status_raw': 'FINISHED',
        },
        {
          'lname_raw': 'Allen',
          'fname_raw': 'Jonathan',
          'name_raw': 'Allen, Jonathan (USA)',
          'country_raw': 'USA',
          'bib_raw': '12373',
          'category_raw': 'MH',
          'club_raw': 'Columbus Track Club',
          'gun_time_raw': '02:23:58',
          'result_raw': '02:23:30',
          'id_on_platform': 'HCH3C0OH72A9A',
          'place_gender_raw': 90,
          'place_category_raw': 34,
          'status_raw': 'FINISHED',
        },
        {
          'lname_raw': 'Asrih',
          'fname_raw': 'Karim',
          'name_raw': 'Asrih, Karim (BEL)',
          'country_raw': 'BEL',
          'bib_raw': '12821',
          'category_raw': 'M30',
          'club_raw': '',
          'gun_time_raw': '02:23:41',
          'result_raw': '02:23:31',
          'id_on_platform': 'HCH3C0OH76EDF',
          'place_gender_raw': 91,
          'place_category_raw': 31,
          'status_raw': 'FINISHED',
        },
      ]
      with io.open(ResultsFile('2023-berlin-page-2'), encoding="utf8") as file_in:
        self.compare_result_page(file_in.read(), expected1)

      expected2 = [
        {
          'lname_raw': 'Kiptum',
          'fname_raw': 'Kelvin',
          'name_raw': 'Kiptum, Kelvin (KEN)',
          'country_raw': 'KEN',
          'bib_raw': '2',
          'category_raw': '20-24',
          'result_raw': '02:00:35',
          'id_on_platform': '9TGG963828AFFB',
          'place_raw': 1,
          'place_gender_raw': 1,
          'status_raw': 'FINISHED',
        },
        {
          'lname_raw': 'Kipruto',
          'fname_raw': 'Benson',
          'name_raw': 'Kipruto, Benson',
          'bib_raw': '1',
          'category_raw': '30-34',
          'result_raw': '02:04:02',
          'id_on_platform': '9TGG963828AFE5',
          'place_raw': 2,
          'place_gender_raw': 2,
          'status_raw': 'FINISHED',
        },
        {
          'lname_raw': 'Abdi',
          'fname_raw': 'Bashir',
          'name_raw': 'Abdi, Bashir (BEL)',
          'country_raw': 'BEL',
          'bib_raw': '3',
          'category_raw': '30-34',
          'result_raw': '02:04:32',
          'id_on_platform': '9TGG963828B00D',
          'place_raw': 3,
          'place_gender_raw': 3,
          'status_raw': 'FINISHED',
        },
        {
          'lname_raw': 'Korir',
          'fname_raw': 'John',
          'name_raw': 'Korir, John (KEN)',
          'country_raw': 'KEN',
          'bib_raw': '7',
          'category_raw': '25-29',
          'result_raw': '02:05:09',
          'id_on_platform': '9TGG963828AFE7',
          'place_raw': 4,
          'place_gender_raw': 4,
          'status_raw': 'FINISHED',
        },
      ]
      with io.open(ResultsFile('2023-chicago-page-1'), encoding="utf8") as file_in:
        self.compare_result_page(file_in.read(), expected2)

    def test_EventAndRaceNames(self):
      with io.open(ResultsFile('2023-berlin-title'), encoding="utf8") as file_in:
        self.assertEqual(('BMW BERLIN MARATHON', 'BML'), mikatiming.EventAndRaceNames(url='', title_page_soup=bs4.BeautifulSoup(file_in.read(), 'html.parser')))

      with io.open(ResultsFile('2023-chicago-title'), encoding="utf8") as file_in:
        self.assertEqual(('', 'MAR'), mikatiming.EventAndRaceNames(url='', title_page_soup=bs4.BeautifulSoup(file_in.read(), 'html.parser')))

    def test_NameCountryDict(self):
      self.assertEqual({'lname_raw': 'Orellana', 'fname_raw': 'Ricardo', 'country_raw': 'ECU'}, mikatiming.NameCountryDict('Orellana, Ricardo (ECU)'))
      self.assertEqual({'lname_raw': 'Orellana', 'fname_raw': 'Ricardo'}, mikatiming.NameCountryDict('Orellana, Ricardo'))
      self.assertEqual({'lname_raw': 'Pluta', 'fname_raw': '', 'country_raw': 'GER'}, mikatiming.NameCountryDict('Pluta (GER)'))
      self.assertEqual({'lname_raw': 'WU', 'fname_raw': 'Xiao Fang(Fion)', 'country_raw': 'CHN'}, mikatiming.NameCountryDict('WU, Xiao Fang(Fion) (CHN)'))

    def test_ElemOnDetailedPage(self):
      self.assertEqual('Male', mikatiming.ElemOnDetailedPage('',
        bs4.BeautifulSoup('<tr class=" f-sex"><th class="desc">Gender</th><td class="f-sex last">Male</td></tr>', 'html.parser'),
        'Gender'))
      self.assertEqual('Male', mikatiming.ElemOnDetailedPage('',
        bs4.BeautifulSoup('<tr class=" f-sex"><th class="desc">Gender</th>\n<td class="f-sex last">Male</td>\n</tr>', 'html.parser'),
        'Gender'))
      self.assertEqual(None, mikatiming.ElemOnDetailedPage('',
        bs4.BeautifulSoup('<tr class=" f-sex"><th class="desc">Gender</th><td class="f-sex last">Male</td></tr>', 'html.parser'),
        'City'))
      self.assertEqual('Nairobi', mikatiming.ElemOnDetailedPage('',
        bs4.BeautifulSoup('<tr class="list-highlight f-__city_state"><th class="desc">City, State</th><td class="f-__city_state last">Nairobi</td></tr>', 'html.parser'),
        'City, State'))
      self.assertEqual('1', mikatiming.ElemOnDetailedPage('',
        bs4.BeautifulSoup('<tr class="list-highlight f-place_age"><th class="desc">Place Age Group</th><td class="f-place_age last">1</td></tr>', 'html.parser'),
        'Place Age Group'))

    def test_ParseSplit(self):
      self.assertEqual(
        {'distance': {
            'distance_type': models.TYPE_METERS,
            'length': 5000,
          },
          'value': (60*14+26) * 100,
        },
        mikatiming.ParseSplit('', bs4.BeautifulSoup("""
<tr class=" f-time_05">
<th class="desc">05K</th>
<td class="time_day">07:44:28AM</td>
<td class="time">00:14:26</td>
<td class="diff">14:26</td>
<td class="min_km right opt colgroup-splits colgroup-splits-metric">02:54</td>
<td class="kmh colgroup-splits colgroup-splits-metric">20.80</td>
<td class="min_mile right opt colgroup-splits colgroup-splits-imperial">04:39</td>
<td class="miles_h right opt colgroup-splits colgroup-splits-imperial last">12.93</td>
</tr>
          """, 'html.parser'))
      )

    def test_EventCodesByYearFromJson(self):
      with io.open(ResultsFile('chicago-history', 'json'), encoding="utf8") as file_in:
        self.assertEqual(mikatiming.EventCodesByYearFromJson(json.load(file_in)),
          [
            (2023, 'MAR_9TGG963812D'),
            (2022, 'MAR_9TGG9638119'),
            (2021, 'MAR_9TGG9638F1'),
            (2019, 'MAR_999999107FA31100000000C9'),
            (2018, 'MAR_999999107FA30900000000B5'),
            (2017, 'MAR_999999107FA30900000000A1'),
            (2016, 'MAR_999999107FA309000000008D'),
            (2015, 'MAR_999999107FA3090000000079'),
            (2014, 'MAR_999999107FA3090000000065'),
            (2013, 'MAR_9999990E9A92360000000079'),
            (2012, 'MAR_9999990E9A9236000000003D'),
          ]
        )
