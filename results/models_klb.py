# TODO: Delete this file.
import datetime
from calendar import monthrange

from typing import Optional, Tuple

CUR_KLB_YEAR = 2024
NEXT_KLB_YEAR = 0
NEXT_KLB_YEAR_AVAILABLE_FOR_ALL = False

MAX_CLEAN_SCORE = 16

MIN_TEAM_SIZE = 3

def get_min_distance_for_score(year: int) -> int:
	if year >= 2018:
		return 9500
	return 10000 # true only for year >= 2015

def get_max_distance_for_score(year: int) -> int:
	if year >= 2022:
		return 350000
	if year >= 2018:
		return 300000
	return 250000 # true only for year >= 2015

def get_min_distance_for_bonus(year: int) -> int:
	if year >= 2018:
		return 9500
	return 9800 # true only for year >= 2015

def get_small_team_limit(year: int) -> int:
	if year >= 2017:
		return 18
	if year >= 2015:
		return 15
	return 12

def get_medium_team_limit(_: int) -> int:
	return 40

def get_team_limit(year: int) -> int:
	if year >= 2020:
		return 90
	if year >= 2017:
		return 100
	if year == 2016:
		return 110
	if year == 2015:
		return 120
	return 150

def get_n_runners_for_team_clean_score(year: int) -> int:
	if year >= 2016:
		return 15
	return 12

def get_n_results_for_clean_score(year: int) -> int:
	if year >= 2019:
		return 4
	return 3

def get_n_results_for_bonus_score(year: int) -> int:
	if year >= 2017:
		return 18
	return 20

def get_bonus_score_denominator(year: int) -> int:
	if year >= 2019:
		return 200000
	return 100000

def get_max_bonus_for_one_race(year: int) -> int:
	if year >= 2019:
		return 6
	return 20

def get_max_bonus_per_year(year: int) -> int:
	if year >= 2019:
		return 20
	return 100

def get_participation_price(year: int) -> int:
	if year >= 2023:
		return 200
	if year >= 2019:
		return 120
	return 100

def get_regulations_link(year: int) -> str:
	if year >= 2010:
		return f'/static2/klb/docs/Pl_KLBMatch_{year % 1000}.pdf'
	return ''

def get_regulations_changes_link(year: int) -> str:
	if 2020 >= year >= 2018:
		return f'/static2/klb/docs/Pl_KLBMatch_{year % 1000}_izm.pdf'
	if year == 2017:
		return f'/static2/klb/docs/Pl_KLBMatch_{year % 1000}_new.pdf'
	return ''

def get_old_match_link(year: int) -> str:
	if 2011 <= year <= 2016:
		return f'/klb/{year}/results.php'
	return ''

# You may also need to fix results/templates/klb/team_details.html.
def get_last_month_to_pay_for_teams(year: int) -> int:
	if year == 2020:
		return 12
	if year <= 2022:
		return 5
	if year == 2023:
		return 3
	return 4

def get_last_month_to_move_between_teams(year: int) -> int:
	if year == 2020:
		return 12
	return 5

def get_last_day_to_pay(year: int) -> datetime.date:
	month = get_last_month_to_pay_for_teams(year)
	return datetime.date(year, month, monthrange(year, month)[1])

def get_last_day_to_move_between_teams(year: int) -> datetime.date:
	month = get_last_month_to_move_between_teams(year)
	return datetime.date(year, month, monthrange(year, month)[1])

# Returns last day to pay for a participant who registered for match-{match_year} on {reg_date}
def get_last_day_to_pay_for_participant(match_year: int, reg_date: Optional[datetime.date]) -> datetime.date:
	match_last_day_to_pay = get_last_day_to_pay(match_year)
	if (reg_date is None) or match_last_day_to_pay >= reg_date:
		return match_last_day_to_pay
	return datetime.date(reg_date.year, reg_date.month, monthrange(reg_date.year, reg_date.month)[1])

def first_match_year(year: int) -> int:
	if year == 2021: # Because of match 2020/21
		return 2020
	return year

def match_year_range(year: int) -> Tuple[int, int]: # For SQL queries
	if year == 2020:
		return (2020, 2021)
	return (year, year)

def last_match_year(year: int) -> int:
	return match_year_range(first_match_year(year))[1]

def year_string(year) -> str:
	if year == 2020:
		return '2020/21'
	return str(year)

def get_age_coefficient_year(year: int) -> int:
	if year <= 2017:
		return 2017
	if year <= 2021:
		return 2018
	return 2022

def has_diplomas(year: int) -> bool:
	return 2015 <= year <= 2023

def has_team_diplomas(year: int) -> bool:
	return 2017 <= year <= 2023

def participant_first_day(year: int, today: datetime.date) -> datetime.date:
	if year != 2024:
		return today
	# In 2024 we allow everyone to register until 2024-03-31 with all January results counted.
	if today.year == year and today.month <= 3:
		return datetime.date(year, 1, 1)
	return today

MEDAL_PAYMENT_YEAR = 0
MEDAL_PRICE = 340
PLATE_PRICE = 0
