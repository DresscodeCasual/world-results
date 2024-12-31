import bs4
from unittest import TestCase

from editor.scrape import baa

class BaaTestCase(TestCase):

	def test_ProcessPageHeader(self):
		# Boston Marathon 2019
		content = '<th>Year</th><th>Bib</th><th>Name</th><th>Age</th><th>M/F</th><th>City</th><th>State</th><th>Country</th><th> </th>'
		expected = {
			0: 'IGNORE',
			1: 'bib_raw',
			2: 'name_raw',
			3: 'age_raw',
			4: 'gender_raw',
			5: 'city_raw',
			6: 'region_raw',
			7: 'country_raw',
			8: 'race_type',
		}
		self.assertEqual(baa.ProcessPageHeader('', bs4.BeautifulSoup(content, 'html.parser')), expected)

		# BAA 10K 2011
		content = '<th>Bib</th><th>Name</th><th>Age</th><th>M/F</th><th>City</th><th>St</th><th>Ctry</th><th>Ctz</th><th>&nbsp;</th>'
		expected = {
			0: 'bib_raw',
			1: 'name_raw',
			2: 'age_raw',
			3: 'gender_raw',
			4: 'city_raw',
			5: 'region_raw',
			6: 'country_raw',
			7: 'IGNORE',
			8: 'race_type',
		}
		self.assertEqual(baa.ProcessPageHeader('', bs4.BeautifulSoup(content, 'html.parser')), expected)

	def test_ExtractResultDict(self):
		# Boston Marathon 2019
		row1 = '<tr class="tr_header"><td>2019  </td><td>W109  </td><td>Rocha, Aline  </td><td>28  </td><td>F  </td><td>São Caetano Do Sul  </td><td>&nbsp;  </td><td>BRA  </td><td>WHEELCHAIR  </td></tr>'
		row2 = '<tr><td colspan="9"><table class="table_infogrid" style="width:95%;"><tr><th rowspan="2" class="table_infogrid_title" style="background-color:#ddd; text-align:center;"> </th><th>Overall</th><th>Gender</th><th>Division</th><th>Official Time</th><th>Net Time</th></tr><tr><td>48       / 60      </td><td>14       / 16      </td><td>14       / 16      </td><td>1:59:29</td><td>1:59:29</td></tr></table></td></tr>'
		header_cols = {
			0: 'IGNORE',
			1: 'bib_raw',
			2: 'name_raw',
			3: 'age_raw',
			4: 'gender_raw',
			5: 'city_raw',
			6: 'region_raw',
			7: 'country_raw',
			8: 'race_type',
		}
		expected = {
			'bib_raw': 'W109',
			'name_raw': 'Rocha, Aline',
			'lname_raw': 'Rocha',
			'fname_raw': 'Aline',
			'age_raw': '28',
			'gender_raw': 'F',
			'city_raw': 'São Caetano Do Sul',
			'region_raw': '',
			'country_raw': 'BRA',
			'race_type': 'WHEELCHAIR',
			'place_raw': 48,
			'place_gender_raw': 14,
			'place_category_raw': 14,
			'result_raw': '1:59:29',
			'gun_time_raw': '1:59:29',
		}
		self.assertEqual(baa.ExtractResultDict(
			'',
			header_cols=header_cols,
			index=0,
			row1=bs4.BeautifulSoup(row1, 'html.parser').contents[0],
			row2=bs4.BeautifulSoup(row2, 'html.parser').contents[0],
		), expected)

		# BAA 10K 2011
		row1 = '<tr class="tr_header"><td>647  </td><td>Abraham, Steven  </td><td>25  </td><td>M  </td><td>Boston  </td><td>MA  </td><td>USA  </td><td>CAN  </td><td>&nbsp;  </td></tr>'
		row2 = '<tr><td colspan="9"><table class="table_infogrid" style="width:95%;"><tr><th rowspan="2" class="table_infogrid_title" style="background-color:#ddd; text-align:center;"> </th><th>5K Chkpt</th><th>Official Finish</th><th>Overall</th><th>Gender</th><th>Division</th></tr><tr><td>26:55</td><td>53:31</td><td>1283     / 3040    </td><td>836      / 1377    </td><td>181      / 276     </td></tr></table></td></tr>'
		header_cols = {
			0: 'bib_raw',
			1: 'name_raw',
			2: 'age_raw',
			3: 'gender_raw',
			4: 'city_raw',
			5: 'region_raw',
			6: 'country_raw',
			7: 'IGNORE',
			8: 'race_type',
		}
		expected = {
			'bib_raw': '647',
			'name_raw': 'Abraham, Steven',
			'lname_raw': 'Abraham',
			'fname_raw': 'Steven',
			'age_raw': '25',
			'gender_raw': 'M',
			'city_raw': 'Boston',
			'region_raw': 'MA',
			'country_raw': 'USA',
			'race_type': '',
			'place_raw': 1283,
			'place_gender_raw': 836,
			'place_category_raw': 181,
			'result_raw': '53:31',
			'splits': [{
				'distance': {
					'distance_type': 1,
					'length': 5000,
				},
				'value': ((26*60) + 55) * 100,
			}]
		}
		self.assertEqual(baa.ExtractResultDict(
			'',
			header_cols=header_cols,
			index=0,
			row1=bs4.BeautifulSoup(row1, 'html.parser').contents[0],
			row2=bs4.BeautifulSoup(row2, 'html.parser').contents[0],
		), expected)
