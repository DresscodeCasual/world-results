from django.db.models import Q

from results import models, results_util

from collections import Counter, defaultdict
from typing import Optional

N_TO_STORE = 100
def fill_regions_visited(country: models.Country, distance: Optional[models.Distance]):
	country.regions_visited_set.filter(distance=distance).delete()
	results = models.Result.objects.filter(
		Q(race__event__city__region__country=country) | Q(race__event__city=None, race__event__series__city__region__country=country),
		status=models.STATUS_FINISHED,
	).exclude(runner=None)
	if distance:
		results = results.filter(race__distance=distance)
	runners = defaultdict(set)
	runners_total_finishes = Counter()
	for runner_id, event_region, series_region in results.values_list('runner_id', 'race__event__city__region_id', 'race__event__series__city__region_id'):
		region_id = event_region if event_region else series_region
		runners[runner_id].add(region_id)
		runners_total_finishes[runner_id] += 1
	runners_count = sorted([(len(regions), runner_id) for runner_id, regions in runners.items()], reverse=True)
	min_len_to_store = runners_count[N_TO_STORE][0]

	objs = []
	last_place = last_value = index = 0
	for value, runner_id in runners_count[:5 * N_TO_STORE]:
		if value < min_len_to_store:
			break
		index += 1
		place = last_place if (value == last_value) else index
		objs.append(models.Regions_visited(
			country=country,
			distance=distance,
			runner_id=runner_id,
			place=place,
			n_finishes=runners_total_finishes[runner_id],
			value=value,
		))
		last_place = place
		last_value = value
	models.Regions_visited.objects.bulk_create(objs)

def generate_all():
	country = models.Country.objects.get(pk='RU')
	marathon = models.Distance.objects.get(pk=results_util.DIST_MARATHON_ID)
	fill_regions_visited(country, marathon)
	fill_regions_visited(country, distance=None)
	country = models.Country.objects.get(pk='BY')
	fill_regions_visited(country, marathon)
	fill_regions_visited(country, distance=None)

def regions_for_runner(runner: models.Runner, country: models.Country, distance: Optional[models.Distance]):
	regions = Counter()
	results = runner.result_set.filter(
		Q(race__event__city__region__country=country) | Q(race__event__city=None, race__event__series__city__region__country=country),
		status=models.STATUS_FINISHED,
	)
	if distance:
		results = results.filter(race__distance=distance)
	for result in results.select_related('race__event__city__region', 'race__event__series__city__region'):
		region = result.race.event.city.region if result.race.event.city else result.race.event.series.city.region
		regions[region] += 1
	i = 0
	for region, value in regions.most_common(100):
		i += 1
		print(f'{i}. {value} - {region}')
