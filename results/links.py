
def AthlinksEventURL(platform_series_id: str, platform_event_id: int) -> str:
	return f'https://www.athlinks.com/event/{platform_series_id}/results/Event/{platform_event_id}/Results'

def NyrrEventURL(platform_event_id: str) -> str:
	return f'https://results.nyrr.org/event/{platform_event_id}/finishers'

def MikatimingEventURL(platform_series_id: str, platform_event_id: str) -> str:
	return f'https://{platform_series_id}/{platform_event_id}'

def TrackShackResultsEventURL(platform_event_id: str) -> str:
	return f'https://www.trackshackresults.com/{platform_event_id}'
