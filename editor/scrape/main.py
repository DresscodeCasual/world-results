import datetime
import traceback

from django.db.models import Q
from django.utils import timezone

from results import models
from . import athlinks, baa, mikatiming, nyrr, trackshackresults, util

def Scraper(row: models.Scraped_event, attempt: models.Download_attempt) -> util.Scraper:
	kwargs = {
		'url': row.url_site,
		'attempt': attempt,
		'protocol': row.protocol,
		'event': row.protocol.event if row.protocol else row.event,
		'platform_series_id': row.platform_series_id,
		'platform_event_id': row.platform_event_id,
	}
	if row.platform_id == 'athlinks':
		return athlinks.AthlinksScraper(**kwargs)
	if row.platform_id == 'baa':
		return baa.BaaScraper(**kwargs)
	if row.platform_id == 'mikatiming':
		return mikatiming.MikaTimingScraper(attempt_timeout=datetime.timedelta(hours=2), **kwargs)
	if row.platform_id == 'nyrr':
		return nyrr.NyrrScraper(**kwargs)
	if row.platform_id == 'trackshackresults':
		return trackshackresults.TrackShackResultsScraper(**kwargs)
	raise util.NonRetryableError(f'There is no scraper yet for platform {row.platform_id}')

def process_queue_element(row: models.Scraped_event) -> str:
	new_attempt = models.Download_attempt.objects.create(scraped_event=row)
	try:
		row.result = models.DOWNLOAD_IN_PROGRESS
		row.save()
		scraper = None
		try:
			scraper = Scraper(row, new_attempt)
			new_attempt.error = scraper.Process()
			res = f'Loaded in {timezone.now() - new_attempt.start_time}'
			new_attempt.result = models.DOWNLOAD_SUCCESS
			row.result = new_attempt.result
			row.save()
			row.refresh_from_db()
			if row.protocol and not row.protocol.is_processed:
				row.protocol.is_processed = True
				row.protocol.save()
				models.log_obj_create(models.USER_ROBOT_CONNECTOR, row.protocol.event, models.ACTION_DOCUMENT_UPDATE, child_object=row.protocol, field_list=['is_processed'],
					verified_by=models.USER_ROBOT_CONNECTOR)
		except util.WaitAndRetryError as e: # We want to wait a bit and then retry.
			new_attempt.result = models.DOWNLOAD_ERROR
			new_attempt.error = str(e)[:1000]
			res = f'not loaded: {e}'
			row.result = models.DOWNLOAD_NOT_STARTED
			row.dont_retry_before = timezone.now() + util.PAUSE_BEFORE_RETRY
			models.send_panic_email(
				subject='WaitAndRetryError raised',
				body=f'For url {row.url_site}: "{e}". Next attempt at {row.dont_retry_before}, attempt No. {new_attempt.id}')
		except util.RetryableError as e: # In this case we want to retry ASAP.
			new_attempt.result = models.DOWNLOAD_ERROR
			new_attempt.error = str(e)[:1000]
			res = f'not loaded: {e}'
			row.result = models.DOWNLOAD_NOT_STARTED
		except Exception as e: # Otherwise, we don't retry.
			new_attempt.result = models.DOWNLOAD_ERROR
			# new_attempt.error = str(e)[:1000]
			err_text = str(e) # traceback.format_exc() # if (scraper.ath_event_id == 615881) else str(e)
			new_attempt.error = err_text[:1000]
			res = f'not loaded: {traceback.format_exc()}'
			row.result = models.DOWNLOAD_ERROR

		if (row.protocol is None) and scraper and scraper.protocol:
			row.protocol = scraper.protocol
		if (row.event is None) and scraper and scraper.event:
			row.event = scraper.event

		row.last_attempt_finished = timezone.now()
		row.save()
		new_attempt.finish_time = timezone.now()
		new_attempt.save()
		return f'{datetime.datetime.now()} Attempt {new_attempt.id}: Protocol {row.url_site} for event {row.protocol.event_id if row.protocol else None} {res}'
	except Exception as e:
		return f'{datetime.datetime.now()} Failed attempt {new_attempt.id}: {e}'

def mark_long_running_as_failed_by_platform(attempts, timeout):
	n_marked = 0
	old_attempts = attempts.filter(start_time__lt=timezone.now() - (timeout + datetime.timedelta(minutes=120)))
	elem_ids = set(old_attempts.values_list('scraped_event_id', flat=True))
	for elem_id in elem_ids:
		elem = models.Scraped_event.objects.get(pk=elem_id)
		if (elem.download_attempt_set.filter(finish_time=None).count() > 
				old_attempts.filter(scraped_event=elem).count()):
			raise RuntimeError(f'Protocol {elem.url_site} has both old and new attempts')
		if elem.result == models.DOWNLOAD_IN_PROGRESS:
			elem.result = models.DOWNLOAD_NOT_STARTED
			elem.save()
		n_marked += old_attempts.filter(scraped_event=elem).update(finish_time=timezone.now(),
			result=models.DOWNLOAD_ERROR, error='Killed as running too late')
	if n_marked:
		print(f'Marked {n_marked} attempts as failed because running too long')

def mark_long_running_as_failed():
	attempts = models.Download_attempt.objects.filter(finish_time=None)
	mark_long_running_as_failed_by_platform(attempts.exclude(scraped_event__platform_id='mikatiming'), timeout=util.ATTEMPT_TIMEOUT)
	mark_long_running_as_failed_by_platform(attempts.filter(scraped_event__platform_id='mikatiming'), timeout=util.datetime.timedelta(hours=2))

def process_queue() -> str:
	mark_long_running_as_failed()
	for platform_id in util.ACTIVE_PLATFORM_IDS:
		n_ongoing = models.Scraped_event.objects.filter(platform_id=platform_id, result=models.DOWNLOAD_IN_PROGRESS).select_related('protocol').count()
		if n_ongoing:
			print(f'{n_ongoing} protocols on platform {platform_id} are in progress')
			continue

		row = util.EventQueue(platform_id).first()
		if not row:
			print(f'{datetime.datetime.now()} All protocols on platform {platform_id} are loaded or have errors, nothing to do')
			continue
		if (not row.url_site) and (not row.protocol):
			print(f'Scraped_event {row.id} has neither URL nor document')
			continue
		if not row.url_site:
			row.url_site = row.protocol.url_source
			row.save()
		last_attempt = row.download_attempt_set.order_by('-start_time').first()
		if last_attempt and (last_attempt.result == models.DOWNLOAD_IN_PROGRESS):
			print(f'{datetime.datetime.now()} Protocol {row.url_site} for event {row.protocol.event_id if row.protocol else None} '
				+ f'is still processed for {timezone.now() - last_attempt.start_time}')
			continue
		return process_queue_element(row)
	return 'We do not launch any new processings now.'
