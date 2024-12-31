import re
import json
import pandas as pd
import requests
import tempfile
from typing import Iterable, List, Tuple
import xlrd

from django.contrib import messages

from results import models

RR_2023_RESULTS_DOMAIN = 'https://results.russiarunning.com'

DOMAINS_TO_LOAD_XLSX = (
	'https://russiarunning.com',
	'https://nomadsport.net',
	'https://market.tulamarathon.org',
	RR_2023_RESULTS_DOMAIN,
)

# Returns the domain and if we want to verify the SSL certificate (it fails for tulamarathon for unknown reason)
def get_domain(url: str) -> Tuple[str, bool]:
	for prefix in DOMAINS_TO_LOAD_XLSX:
		if url.startswith(prefix):
			return prefix, prefix != 'https://market.tulamarathon.org'
	return '', False

# Returns:
# * the domain ef determined,
# * whether we want to verify the SSL certificate (it fails for tulamarathon for unknown reason),
# * error, if any.
def validate_url(url: str) -> Tuple[str, bool, str]:
	domain, to_verify_SSL = get_domain(url)
	if not domain:
		return '', False, ''
	err = ''
	if url.count('/') < 6:
		err = f'Общий адрес {url} не подходит для скачивания результатов. Укажите адрес результатов любой конкретной дистанции'
	return domain, to_verify_SSL, err

def download_table(race_ids: Iterable[Tuple[str, str]], domain: str, to_verify_SSL: bool, path: str) -> List[Tuple[str, str]]:
	dists_with_errors = []
	with pd.ExcelWriter(path, engine='xlsxwriter') as writer:
		for i in race_ids:
			tableurl = (f'{domain}/Results/Services/DownloadProtocol?raceId={i[0]}'
						+ '&templateCode=RussiaRunning&fileExtension=xls&culture=ru')
			results = requests.get(tableurl, allow_redirects=True, verify=to_verify_SSL)
			try:
				with tempfile.NamedTemporaryFile() as temp_file:
					temp_file.write(results.content)
					df = pd.read_excel(temp_file.name)
					df.to_excel(writer, sheet_name=str(i[1])[:31], index=False, header=False)
			except xlrd.XLRDError as e:
				dists_with_errors.append((str(i[1]), str(e)))
	return dists_with_errors

# By Daniil Glukhovskiy https://www.facebook.com/daniil.glukhovskiy.3
# Returns <succeeded?>, <List of errors with distances>
def parse_rr_2020(url: str, domain: str, to_verify_SSL: bool, path: str) -> Tuple[bool, List[Tuple[str, str]]]:
	r = requests.get(url, allow_redirects=True, verify=to_verify_SSL)
	raceinfo = re.findall('var config = ({.+})', r.text)
	if not raceinfo:
		return False, [('все', f'В содержимом {url} не найден raceinfo')]
	json_raceinfo = raceinfo[0].replace('\\\\"', '').replace("\\", "00000")
	x = json.loads(json_raceinfo)
	event_code = x['eventCode']
	race_ids = [(i['Id'], i['Code']) for i in x['races']]
	return True, download_table(race_ids=race_ids, domain=domain, to_verify_SSL=to_verify_SSL, path=path)

# By Maxim Lixakov lixakov.maksim@yandex.ru
# Returns <succeeded?>, <List of errors with distances>
def parse_rr_2023(url: str, to_verify_SSL: bool, path: str) -> Tuple[bool, List[Tuple[str, str]]]:
	event_code = re.findall('event/(.+)/results', url)
	if not event_code:
		return False, [('все', f'В адресе {url} не найден код забега')]
	payload = {"eventCode": event_code[0], 'language': 'ru'}
	r = requests.post(RR_2023_RESULTS_DOMAIN + '/api/events/get', json=payload)
	race_ids = [(i['id'], i['code']) for i in r.json().get('races')]
	return True, download_table(race_ids=race_ids, domain='https://russiarunning.com', to_verify_SSL=to_verify_SSL, path=path)

# Returns <is RR url?>, <succeeded?>, <List of errors with distances>
def try_load_russiarunning_protocol(url: str, path: str) -> Tuple[bool, bool, List[Tuple[str, str]]]:
	domain, to_verify_SSL, err = validate_url(url)
	if not domain:
		return False, False, []
	if err:
		return True, False, [('все', err)]
	if domain == RR_2023_RESULTS_DOMAIN:
		succeeded, dists_with_errors = parse_rr_2023(url, to_verify_SSL, path)
	else:
		succeeded, dists_with_errors = parse_rr_2020(url, domain, to_verify_SSL, path)
	return True, succeeded, dists_with_errors

def log_warning(request, message):
	if request:
		messages.warning(request, message)
	else:
		print("Warning: " + message)
def log_success(request, message):
	if request:
		messages.success(request, message)
	else:
		print("Success: " + message)

# We try to save links to runners and users.
# Returns the number of deleted results with runner/user.
def delete_results_and_store_connections(request, user, race, results_for_deletion) -> int:
	n_results_for_deletion = results_for_deletion.count()
	if n_results_for_deletion == 0:
		return 0
	n_deleted_links = 0
	for result in results_for_deletion.select_related('result_on_strava', 'klb_result'):
		# If result has klb_result then it won't be lost.
		if (result.runner_id or result.user_id) and not hasattr(result, 'klb_result'):
			models.Lost_result.objects.create(
				user_id=result.user_id,
				runner_id=result.runner_id,
				race=race,
				result=result.result,
				status=result.status,
				lname=result.lname,
				fname=result.fname,
				midname=result.midname,
				strava_link=result.result_on_strava.link if hasattr(result, 'result_on_strava') else 0,
				loaded_by=user,
			)
			n_deleted_links += 1
	log_warning(request, f'Deleting {n_results_for_deletion} old results')
	res = results_for_deletion.delete()
	log_warning(request, f'Deleted {res[0]} results and splits')
	return n_deleted_links

def try_fix_lost_connection(result: models.Result) -> bool:
	lost_result = result.race.lost_result_set.filter(
		lname=result.lname, fname=result.fname, status=result.status, result=result.result).first()
	if lost_result:
		result.runner = lost_result.runner
		result.user = lost_result.user
		result.save()
		# We also fix the links to record results, if any.
		if lost_result.runner:
			models.Record_result.objects.filter(result=None, runner=lost_result.runner, race=result.race, value=result.result).update(result=result)
		lost_result.delete()
	return lost_result is not None
