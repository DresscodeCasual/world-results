import json

from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.geos import Point

from results import links, models, results_util
from . import util

ALL_EVENTS_URL = 'https://images.parkrun.com/events.json'

def SeriesAndCountries():
	res, url = util.TryGetJson(results_util.session.get(ALL_EVENTS_URL))
	return res['events']['features'], res['countries']

def CountryDict(raw_dict: dict[str, any]) -> dict[int, dict[str, any]]:
	res = {}
	for key, val in raw_dict.items():
		if val['url'] is None:
			continue
		country_num = results_util.int_safe(key)
		if not country_num:
			raise Exception(f'CountryDict cannot recognize country number {key}')
		country_id = val['url'].split('.')[-1].upper()
		country = models.Country.objects.filter(pk=country_id).first()
		if not country:
			raise Exception(f'CountryDict cannot recognize country domain {country_id} (number {key})')
		res[country_num] = {
			'country': country,
			'site': 'https://' + val['url'],
		} 
	return res

PARKRUNS_WITH_COUNTRY_EXCEPTION = frozenset([
	'nobles', # City is in Isle of Man but the site is in .org.uk
	'cieszyn', # Close to the border of Poland and Czech Republic
	'pongola', # close to border
	'castleblayney',
])

def ProcessSeriesList() -> str:
	series_list, countries_dict_raw = SeriesAndCountries()
	countries_dict = CountryDict(countries_dict_raw)
	existing_series_platforms = models.Series_platform.objects.filter(platform_id='parkrun').select_related('series')
	series_by_code = {series_platform.value: series_platform.series for series_platform in existing_series_platforms}
	active_series_codes = set(existing_series_platforms.filter(series__create_weekly=True).values_list('value', flat=True))
	series_modified = []
	n_series_created = 0
	for series_dict in series_list:
		short_name = series_dict['properties']['eventname']
		if short_name in series_by_code:
			series = series_by_code[short_name]
			values_to_update = {
				'name': series_dict['properties']['EventLongName'],
				'start_place': series_dict['properties']['EventLocation'],
				'create_weekly': True,
			}
			was_modified = models.update_obj_if_needed_simple(series, new_vals=values_to_update, comment='When parsing all parkrun series')
			if was_modified:
				series_modified.append(short_name)
			active_series_codes.remove(short_name)
			continue

		coordinates = series_dict['geometry']['coordinates']
		location = Point(coordinates[0], coordinates[1], srid=4326)
		city = models.City.objects.annotate(distance=Distance('geo', location)).exclude(geo=None).order_by('distance').first()
		country_dict = countries_dict[series_dict['properties']['countrycode']]
		country = country_dict['country']
		if (city.region.country != country) and (short_name not in PARKRUNS_WITH_COUNTRY_EXCEPTION):
			# raise Exception(f'{series_dict["properties"]["EventLongName"]}: city {city.name}, distance {city.distance}, is in {city.region.country} '
			# 	+ f'but event country is {country}')
			print(f'{series_dict["properties"]["EventLongName"]}: city {city.name}, distance {city.distance}, is in {city.region.country} '
				+ f'but event country is {country}')
		# print(f'{series_dict["properties"]["EventLongName"]}: city {city.name}, distance {city.distance}')
		series = models.Series.objects.create(
			name=series_dict['properties']['EventLongName'],
			city=city,
			start_place=series_dict['properties']['EventLocation'],
			url_site=f'{country_dict["site"]}/{short_name}',
			is_weekly=True,
			create_weekly=True,
			contacts=f'{short_name}@parkrun.com',
			surface_type=results_util.SURFACE_ROAD,
			created_by=models.USER_ROBOT_CONNECTOR,
		)
		n_series_created += 1
		models.log_obj_create(models.USER_ROBOT_CONNECTOR, series, models.ACTION_CREATE, verified_by=models.USER_ROBOT_CONNECTOR)
		models.Series_platform.objects.create(platform_id='parkrun', series=series, value=short_name)
	res = f'{n_series_created} series created. {len(series_modified)} series modified.'
	if series_modified:
		res += f' First: {series_modified[:5]}'
	if active_series_codes:
		res += f'{len(active_series_codes)} existing series marked as inactive: {active_series_codes}'
		for series_code in active_series_codes:
			series = models.Series_platform.objects.get(platform_id='parkrun', series__create_weekly=True, value=series_code).series
			series.create_weekly = False
			series.save()
			models.log_obj_create(models.USER_ROBOT_CONNECTOR, series, models.ACTION_UPDATE, field_list=['create_weekly'], verified_by=models.USER_ROBOT_CONNECTOR)
	return res
