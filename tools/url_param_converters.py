class DefaultConverter:
	def to_python(self, value):
		return value
	def to_url(self, value):
		return value

class IntegerConverter:
	regex = r'\-{0,1}[0-9]+'
	def to_python(self, value):
		return int(value)
	def to_url(self, value):
		return str(value)

class FourDigitYearConverter(IntegerConverter):
	regex = '[1-2][0-9]{3}'

class CountryConverter(DefaultConverter):
	regex = '[A-Za-z]{2,3}'
	def to_url(self, value):
		return value.upper()

class CountryOfThreeConverter(CountryConverter):
	regex = 'RU|ru|UA|ua|BY|by'

class CyrillicWordConverter(DefaultConverter):
	regex = '[A-Za-zА-Яа-я]+'

class GenderConverter(DefaultConverter):
	regex = 'male|female'

class ModelNameConverter(DefaultConverter):
	regex = r'[a-zA-Z0-9_]+\.[a-zA-Z0-9_]+'

class LevelConverter(DefaultConverter):
	regex = 'race|event|series|organizer|root'

class SeriesTabConverter(DefaultConverter):
	regex = 'all_events|races_by_event|races_by_distance|reviews|strikes|default'
