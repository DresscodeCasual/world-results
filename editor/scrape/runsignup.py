from django.conf import settings

from results import models, results_util
from . import util

from bs4 import BeautifulSoup, Tag
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
import io
import json
from typing import List, Optional, Set, Tuple
import requests
import time
import re

RESULTSET_RE = re.compile(r'(https?://runsignup\.com)?(?P<url>/Race/Results/(Simple/)?(?P<series>[0-9]+)/?#?\??(resultSetId(=|-)(?P<resultset>[0-9]+).*)?)')

@dataclass
class RunsignupRace:
    """Class for keeping race information from Runsignup"""
    url: str
    name: str
    date: datetime
    place: str
    zip: str
    tags: list[str]
    resultsets: Set[Tuple[int,str]]

def parse_html(html: str) -> Tuple[List[RunsignupRace], Optional[str]]:
    """
    Returns list of races and next page (if there is one)
    """
    soup = BeautifulSoup(html, 'html.parser')
    races = [y for el in soup.find('tbody').children if isinstance(el, Tag) and (y := parse_row(el)) is not None]
    next = get_next_page(soup)
    return races, next

def get_next_page(soup: Tag) -> Optional[str]:
    next_page_a = soup.find('a', class_='rsuPagination__arrowRight')
    return next_page_a['href'] if next_page_a else None

def parse_row(row: Tag) -> Optional[RunsignupRace]:
    """
    Parses a single row from HTML table of races.
    Returns: triple of url, event name and list of tag values
    """
    try:
        tds = list(row.find_all('td'))

        links = list(tds[0].find_all('a'))
        url = links[1]['href']
        name = links[1].contents[0]

        date_str = str(tds[1].contents[0]).strip()
        date = datetime.strptime(date_str, '%a %m/%d/%y')

        place_span = tds[2].span
        place = place_span.span.contents[0]
        zipcode = place_span.div.contents[0]

        tag_spans = tds[0].find_all('span', class_='rsuVitamin')
        tags = list(map(lambda el: el.contents[0], tag_spans))
        return RunsignupRace(url, name, date, place, zipcode, tags, set())
    except Exception:
        return None

def get_series_id(html: str) -> Set[Tuple[int,Optional[int],str]]:
    """
    Returns list of series id, resultset id and URL from race page.

    There are several variants of URL format. However, both link variants seem
    to point to the same page. Links to the result sets are also the same.

    If series id is not found, returns empty list.
    """
    soup = BeautifulSoup(html, 'html.parser')
    res = set()
    a_resultset = soup.find_all('a', string=re.compile('.*Results'))
    for a in a_resultset:
        href = a.get('href')
        if href is None:
            print(f'href is None! "{a}"')
            continue
        m = re.match(RESULTSET_RE, href)
        if m:
            series_id = int(m.group('series'))
            if m.group('resultset'):
                resultset_id = int(m.group('resultset'))
            else:
                resultset_id = None
            url = m.group('url')
            res.add((series_id, resultset_id, url))
    return res

def get_resultset_ids(html: str) -> Set[Tuple[int,str]]:
    """
    Returns list of ids of result sets from results page.
    """
    soup = BeautifulSoup(html, 'html.parser')
    links = soup.find_all('a', href=RESULTSET_RE)
    if links:
        res = set()
        for link in links:
            m = re.match(RESULTSET_RE, link.get('href'))
            if m and m.group('resultset'):
                res.add((int(m.group('resultset')),m.group('url')))
        return res
    else:
        return set()

class RunsignupScraper(util.Scraper):
    PLATFORM_ID = 'runsignup'

    @classmethod
    def AddEventsToQueue(cls,
                         limit: Optional[int] = None,
                         page: Optional[int] = None,
                         check_already_loaded_series: Optional[bool] = False,
                         debug: int = 0) -> Tuple[bool, str]:
        """
        Parameters:
        - limit: stop requesting new pages when we get at least <limit> races
          (e.g. if limit==300, parses two pages because 1*250 < 300 and 2*250 >= 300)
        - page: start from the specified page
        - check_already_loaded_series: re-check series that were already loaded
        - debug: print debugging info

        Returns:
        * success?
        * message about the results
        """
        total_items = None
        n_added = already_in_queue = 0
        all_items = []
        BASE_URL = 'https://runsignup.com'
        ITEMS_PER_PAGE = 250

        page_str = f'&page={page}' if page is not None else ''
        cur_page: Optional[str] = f'/Races?num={ITEMS_PER_PAGE}{page_str}'
        while cur_page is not None:
            res = requests.get(BASE_URL + cur_page, headers=results_util.HEADERS)

            if res.status_code != 200:
                return False, f'Could not load {cur_page}: {res}'

            items, next_page = parse_html(res.text)

            print(f'\nTotal items on {cur_page}: {len(items)}. Added: {n_added}, already were in queue: {already_in_queue}\n')

            if len(items) == 0:
                if debug:
                    print(f'No items found in:\n{res.text}')
                break

            for i, item in enumerate(items):
                # Skip events from external domains: usually campaigns,
                # e.g. https://www.ticketsignup.io/TicketEvent/2024FallLineTrailblazerCampaign
                if item.url[0] != '/':
                    if debug:
                        print(f'Skipping {item.url} from external domain')
                    continue
                # Skip events from far future, unless for_all_years is set
                if item.date > datetime.now() + timedelta(days=365):
                    if debug:
                        print(f'Skipping {item.url} because it is on {item.date}')
                    continue
                # Skip virtual events
                if 'Virtual Event' in item.tags:
                    if debug:
                        print(f'Skipping {item.url} because it is virtual: {item.tags}')
                    continue

                # Skip events we already parsed
                # TODO: next year events are created without changing URL, we have to re-parse them
                race_url = BASE_URL + item.url
                if not check_already_loaded_series and models.Scraped_event.objects.filter(url_site=race_url).exists():
                    already_in_queue += 1
                    if debug:
                        print(f'{race_url} is already in the queue')
                    continue

                race_page = requests.get(race_url, headers=results_util.HEADERS)
                if race_page.status_code != 200:
                    if debug:
                        print(f'Error {race_page.status_code} when trying to get {race_url}')
                    # TODO: retry if error is not fatal
                    continue

                series_info = get_series_id(race_page.text)

                if len(series_info) == 0:
                    if debug:
                        print(f'No results link on {race_url}, skipping')
                    continue

                for series_id, resultset_id, url in series_info:
                    # no resultset ids on race page, we have to parse results page
                    if resultset_id is None:
                        results_url = BASE_URL + url
                        results_page = requests.get(results_url, headers=results_util.HEADERS)
                        if results_page.status_code != 200:
                            if debug:
                                print(f'Error {results_page.status_code} when trying to get {results_url}')
                            # TODO: retry if error is not fatal
                            continue
                        resultsets = get_resultset_ids(results_page.text)
                    else:
                        resultsets = {(resultset_id, url)}

                    # now we have resultset_ids, one way or another
                    item.resultsets = resultsets

                    for resultset_id, url in resultsets:
                        url_results = (BASE_URL + url) if (url[0] == '/') else url
                        if models.Scraped_event.objects.filter(url_results=url_results).exists():
                            already_in_queue += 1
                            if debug:
                                print(f'Results for {url_results} is already in the queue')
                            continue
                        models.Scraped_event.objects.create(
                            url_site=race_url,
                            url_results=url_results,
                            platform_id=cls.PLATFORM_ID,
                            platform_series_id=series_id,
                            platform_event_id=resultset_id)

                all_items.append(asdict(item))
                n_added += 1
                if debug:
                    print(f'{item.url} was added')

                if limit and n_added >= limit:
                    return True, f'{n_added} protocols were added to the queue! Stopped at {cur_page}'
            cur_page = next_page
            time.sleep(1)
        if limit is None:
            with io.open(settings.INTERNAL_FILES_ROOT + 'misc/runsignup/all_events.json', "w", encoding="utf8") as file_out:
                json.dump(
                    all_items,
                    file_out,
                    ensure_ascii=False,
                    sort_keys=True,
                    indent=1,
                    default=str
                )
        return True, f'All {n_added} protocols were added to the queue, {already_in_queue} were added before. Stopped at {cur_page}'
