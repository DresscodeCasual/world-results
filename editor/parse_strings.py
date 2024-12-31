import re
from typing import Optional, Tuple

from results import models, results_util

# 1. Often organizers round up distances to 21100 or 42200,
# 2. Athlinks has weird lengths, maybe after converting from miles.
def fix_weird_lengths(length: int) -> int:
	if length in (42165, 42195, 42200):
		return 42195 # Marathon
	if length in (21082, 21097, 21098, 21100):
		return 21098 # Half marathon
	return length

# Some Athlinks courses don't specify length at all.
WEIRD_ATHLINKS_COURSES = {
	1280710: 84300, # https://www.athlinks.com/event/1403/results/Event/754443/Course/1280710/Results - San Francisco 2018
	1654899: 84300, # https://www.athlinks.com/event/1403/results/Event/872627/Course/1654899/Results - San Francisco 2019
	1981792: 54200, # https://www.athlinks.com/event/1403/results/Event/949361/Course/1981792/Results - San Francisco 2020
	# 1934876: 1000, # https://www.athlinks.com/event/19924/results/Event/940328/Course/1934876/Results - New Haven Road Race 2020
	# 1682086: 1000, # https://www.athlinks.com/event/19924/results/Event/879106/Course/1682086/Results - New Haven Road Race 2019
}

# Tries to parse the length in meters from the raw length (if present; Athlinks has weird values sometimes) and the name of the distance.
# If it cannot make a decision, returns 0.
def parse_meters(length_raw: Optional[int]=None, name: str='', **kwargs) -> int:
	if length_raw:
		return fix_weird_lengths(length_raw)
	name = name.lower()
	for suffix in (' м', ' m', ' метров', ' meters'):
		if name.endswith(suffix):
			return results_util.int_safe(name[:-len(suffix)])
	if name.endswith(('0м',)):
		return results_util.int_safe(name[:-1])
	if name.startswith(('100k ')):
		return 100000
	if name.startswith(('марафон', 'marathon', 'run-marathon', 'run*marathon', 'run- marathon', 'run - marathon')):
		return 42195
	if name.endswith((' 26.2mi', 'full marathon')):
		return 42195
	if name == 'mar':
		return 42195
	if name.startswith(('полумарафон', 'half marathon', '13.1mi', '13.11mi')):
		return 21098
	if name.endswith(('полумарафон', 'half marathon', 'half wheelchair', ' 13.1mi')):
		return 21098
	if name in ('half', 'halb'): # Deutch
		return 21098
	if 'half-marathon' in name:
		return 21098
	if name.startswith(('20k')):
		return 20000
	if name == 'adventure race: 3.4mi run, 4.5mi run, 2.6mi run':
		return 16900 # https://www.athlinks.com/event/11527/results/Event/65339/Course/97606/Results
	if name.startswith(('10k')):
		return 10000
	if name.endswith(('/10k', '-10k', ' 10k', ' 10k run')):
		return 10000
	if name.startswith(('5k')):
		return 5000
	if name.endswith(('-5k', ' 5k', '*5k', 'run/5k', '-5 km')):
		return 5000
	if results_util.anyin(name, ('- 5k ', '//5k ')):
		return 5000
	if name.endswith((' -1 mile')):
		return 1609
	if results_util.anyin(name, (' 1-mile', '-1mi', '- 1mi')):
		return 1609
	if name.startswith(('1k')):
		return 1000
	if name.startswith(('.5mi')):
		return 805
	if name.endswith(('-1/2mi', ' -½ mile')):
		return 805
	res = re.search(r'^(\d+(\.\d+){0,1})( {0,1})mi', name) # '3 mi', '2.5 mi run'
	if res:
		return int(round(results_util.MILE_IN_METERS * float(res.group(1))))
	res = re.match(r'(\.\d+) mi', name) # '.5 mi run'
	if res:
		return int(round(results_util.MILE_IN_METERS * float(res.group(1))))
	res = re.match(r'(\d+(\.\d+){0,1})m', name) # '26M'
	if (kwargs.get('platform_id') == 'nyrr') and res:
		return int(round(results_util.MILE_IN_METERS * float(name[:-1])))
	res = re.search(r'-(\d+(\.\d+){0,1})mi$', name) # 'Run-5Mi'
	if res:
		return int(round(results_util.MILE_IN_METERS * float(res.group(1))))
	res = re.search(r'-(\d+(\.\d+){0,1})k$', name) # 'kids-1k'
	if res:
		return int(round(1000*float(res.group(1))))
	res = re.search(r' (\d+(\.\d+){0,1})k$', name) # 'kids - 1k'
	if res:
		return int(round(1000*float(res.group(1))))

	for suffix in ('km net time', 'км', 'km', 'km netto', 'km::start', 'k'):
		if name.endswith(suffix):
			return int(round(results_util.float_safe(name[:-len(suffix)].replace(',', '.')) * 1000))

	distance_with_same_name = models.Distance.objects.filter(distance_type=models.TYPE_METERS, name=name).first()
	if distance_with_same_name:
		return distance_with_same_name.length
	athlinks_course_id = kwargs.get('athlinks_course_id')
	if athlinks_course_id and (athlinks_course_id in WEIRD_ATHLINKS_COURSES):
		return WEIRD_ATHLINKS_COURSES[athlinks_course_id]
	return 0

# Tries to parse the length in minutes from the name of the distance.
# If it cannot make a decision, returns 0.
def parse_minutes(name: str) -> int:
	for suffix in ('мин', 'минут', 'minutes'):
		if name.endswith(suffix):
			return results_util.int_safe(name[:-len(suffix)])
	for suffix in ('час', 'часа', 'часов', 'hour', 'hours'):
		if name.endswith(suffix):
			return int(round(results_util.float_safe(name[:-len(suffix)].replace(',', '.')) * 60))
	return 0

# Returns distance (if parsed) or None otherwise.
def parse_distance(distance_raw: str, distance_type: Optional[int]=None) -> Optional[models.Distance]:
	if distance_raw == '':
		return None
	distance = None
	length = 0
	if distance_type in (None, models.TYPE_METERS):
		length = parse_meters(length_raw=length, name=distance_raw)
		if length and (distance_type is None):
			distance_type = models.TYPE_METERS
	if (length == 0) and (distance_type in (None, models.TYPE_MINUTES_RUN)):
		length = parse_minutes(distance_raw)
		if length and (distance_type is None):
			distance_type = models.TYPE_MINUTES_RUN
	if length == 0:
		length = results_util.int_safe(distance_raw)
	if length == 0:
		return None
	if distance_type == models.TYPE_METERS:
		if length in (21097, 21100):
			length = 21098
		elif length == 42200:
			length = 42195
	if not distance_type:
		distance_type = models.TYPE_METERS
	distance, _ = models.Distance.objects.get_or_create(length=length, distance_type=distance_type)
	return distance
