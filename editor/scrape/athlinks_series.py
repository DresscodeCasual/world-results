import requests
import time

from django.utils import timezone

from results import models, results_util
from editor import stat
from editor.scrape import athlinks, util

N_SERIES_TO_PROCESS = 2000

def HasOriginalResults(series_metadata: dict[str, any]) -> bool:
	if series_metadata['result']['currentRace'] is None:
		return False
		# raise Exception('currentRace is null')
	return series_metadata['result']['currentRace']['timer'] is not None

# Creates/updates the record in Athlinks_series if needed.
def ProcessSeriesMetadata(platform_series_id: int, series_metadata: dict):
	defaults = {
		'name': series_metadata['result']['name'],
		'has_original_results': HasOriginalResults(series_metadata),
		'is_deleted': False,
		'last_check': timezone.now(),
	}
	series, just_created = models.Athlinks_series.objects.get_or_create(pk=platform_series_id, defaults=defaults)
	if not just_created:
		models.update_obj_if_needed(series, defaults)

# When some series was previously present at Athlinks, but not any more.
def MarkSeriesAsDeleted(platform_series_id: int):
	series = models.Athlinks_series.objects.get(pk=platform_series_id, is_deleted=False)
	models.update_obj_if_needed(series, {'is_deleted': True})

# We want to scrape all of these.
def ProcessSeriesWithOriginalResults(id_from: int, id_to: int) -> tuple[int, int, int, int, list[int], str]:
	errors = []
	n_added = n_already_present = n_series_to_load = n_series_not_to_load = 0
	disappeared_series = []
	existing_series = set(models.Athlinks_series.objects.filter(id__range=(id_from, id_to), is_deleted=False).values_list('id', flat=True))
	for platform_series_id in range(id_from, id_to + 1):
		time.sleep(1)
		url = athlinks.SeriesMetadataURL(platform_series_id)
		series_metadata, url = util.TryGetJson(requests.get(url, headers=results_util.HEADERS))
		if not series_metadata.get('success'):
			if series_metadata.get('ErrorMessage', '').endswith('not found'):
				if platform_series_id in existing_series:
					disappeared_series.append(platform_series_id)
					MarkSeriesAsDeleted(platform_series_id=platform_series_id)
			else:
				errors.append(f'ERROR: {url}: {series_metadata}')
			continue
		try:
			if HasOriginalResults(series_metadata):
				n_series_to_load += 1
				just_added, just_already_present, err = athlinks.AthlinksScraper.AddSeriesEventsToQueue(platform_series_id=platform_series_id, debug=1)
				n_added += just_added
				n_already_present += just_already_present
				if err:
					errors.append(f'ERROR: {url}: {err}')
			else:
				n_series_not_to_load += 1
		except Exception as e:
			errors.append(f'ERROR: {url}: {e}')
	return n_added, n_already_present, n_series_to_load, n_series_not_to_load, disappeared_series, '\n'.join(errors)
	# print(f'Found {n_series_to_load} series to process, {n_series_not_to_load} series to ignore. '
	# 	+ f'Added {n_added} events to queue; {n_already_present} events were already there.')
	# if errors:
	# 	print(f'{len(errors)} errors:')
	# 	print('\n'.join(errors))
	# else:
	# 	print('No errors!')

def ProcessSeriesSegment() -> str:
	last_checked = stat.get_stat_value('last_athlinks_series_processed') or 0
	last_to_check = last_checked + N_SERIES_TO_PROCESS
	n_added, n_already_present, n_series_to_load, n_series_not_to_load, disappeared_series, errors = ProcessSeriesWithOriginalResults(
		last_checked + 1, last_to_check)

	# Smallest series ID at Athlinks now is 1015
	new_last_checked = last_to_check if (n_series_to_load + n_series_to_load > 0) else 1000
	stat.set_stat_value('last_athlinks_series_processed', new_last_checked)
	res = f'We checked Athlinks series with IDs {last_checked + 1}..{last_to_check}.'
	res += f'\nFound {n_series_to_load} series to process, {n_series_not_to_load} series to ignore. '
	res += f'\nAdded {n_added} events to queue; {n_already_present} events were already there.'
	if disappeared_series:
		res += f'\n{len(disappeared_series)} series disappeared. First: {disappeared_series[:5]}'
	if errors:
		res += f'\n{len(errors)} errors:\n' + errors
	return res
