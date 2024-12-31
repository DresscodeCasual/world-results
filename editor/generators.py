from django.template.loader import render_to_string
from django.db.models import Count, Q, Sum
from django.contrib.auth.models import Group
from django.utils import timezone
from django.conf import settings

from collections import Counter, OrderedDict
import datetime
import io
import os

from results import models, models_klb, results_util
from results.views import views_common

DAYS_IN_DEFAULT_CALENDAR = 31
LAST_PROTOCOLS_EVENT_NUMBER = 10

def is_good_symbol(s):
	return (ord(s) < 128) or ('а' <= s <= 'я') or ('А' <= s <= 'Я') or s in 'Ёё–—«»'

def try_write_to_cp1251_file(s, fname):
	s_cp1251 = ''.join([i if is_good_symbol(i) else '' for i in s])
	with io.open(os.path.join(settings.UPLOAD_FOR_PHP_PATH, fname), 'w', encoding="cp1251") as output_file:
		output_file.write(s_cp1251 + '\n')

def generate_html(source, context, target, dir='results/templates/generated/', to_old_probeg=False, debug=False):
	if debug:
		print('generate_html: Trying to render source {} to target {}'.format(source, target))
	res = render_to_string(source, context)
	if debug:
		print('generate_html: Done! Writing to file...')
	with io.open(os.path.join(settings.BASE_DIR, dir, target), 'w', encoding="utf8") as output_file:
		output_file.write(res)
	if debug:
		print('generate_html: Done!')
	if to_old_probeg:
		try_write_to_cp1251_file(res, to_old_probeg)

def get_weekly_series_by_region_id(region_id):
	return set(models.Series.objects.filter(is_weekly=True, city__region_id=region_id).values_list('id', flat=True))

def generate_default_calendar(year_ahead=False):
	context = {}
	today = datetime.date.today()
	events = []
	moscow_parkrun_ids = get_weekly_series_by_region_id(models.REGION_MOSCOW_ID)
	petersburg_parkrun_ids = get_weekly_series_by_region_id(models.REGION_SAINT_PETERSBURG_ID)
	other_parkrun_ids = set(models.Series.objects.filter(is_weekly=True).exclude(
		city__region_id__in=(models.REGION_MOSCOW_ID, models.REGION_SAINT_PETERSBURG_ID)).values_list('id', flat=True))
	parkrun_series_to_exclude = moscow_parkrun_ids | petersburg_parkrun_ids | other_parkrun_ids
	cur_day = today

	cis_countries = ('RU', 'BY', 'UA')
	cis_events = models.Event.objects.filter(invisible=False).exclude(series__id__in=parkrun_series_to_exclude)
	cis_events = cis_events.filter(
		Q(city__region__country_id__in=cis_countries)
		| (Q(city=None) & Q(series__city__region__country_id__in=cis_countries))
		| (Q(city=None) & Q(series__city=None) & Q(series__country_id__in=cis_countries))
	)
	for _ in range(366 if year_ahead else DAYS_IN_DEFAULT_CALENDAR):
		for event in views_common.add_related_to_events(cis_events.filter(start_date=cur_day)).order_by('name'):
			events.append({'events': [event], 'is_single_event': True})
		if cur_day.weekday() == 5: # So it's Saturday
			events_today = views_common.add_related_to_events(models.Event.objects.filter(start_date=cur_day)).order_by('name')
			moscow_parkruns = events_today.filter(series_id__in=moscow_parkrun_ids)
			if moscow_parkruns.exists():
				events.append({'events': moscow_parkruns})
			petersburg_parkruns = events_today.filter(series_id__in=petersburg_parkrun_ids)
			if petersburg_parkruns.exists():
				events.append({'events': petersburg_parkruns})
			other_parkruns = events_today.filter(series_id__in=other_parkrun_ids)
			if other_parkruns.exists():
				events.append({'events': other_parkruns, 'hide_cities': True})
		cur_day += datetime.timedelta(days=1)
	context['event_groups'] = events
	if year_ahead:
		context['list_title'] = 'Календарь забегов в России, Украине, Беларуси на ближайший год'
	else:
		context['list_title'] = 'Календарь забегов в России, Украине, Беларуси на ближайший месяц ({})'.format(
			results_util.dates2str(today, today + datetime.timedelta(days=DAYS_IN_DEFAULT_CALENDAR - 1)))
		context['show_link_to_full_calendar'] = True
	generate_html('generators/default_calendar.html', context, 'default_calendar{}.html'.format('_full' if year_ahead else ''))

def generate_default_calendars():
	generate_default_calendar()
	generate_default_calendar(year_ahead=True)

def generate_last_loaded_protocols():
	last_updates = models.Table_update.objects.filter(action_type=models.ACTION_RESULTS_LOAD).select_related('user').order_by(
		'-added_time')[:LAST_PROTOCOLS_EVENT_NUMBER * 6]
	used_race_ids = set()
	last_events = OrderedDict()
	editors = {}
	dates = {}
	for update in last_updates:
		race_id = update.child_id
		if race_id not in used_race_ids:
			used_race_ids.add(race_id)
			race = models.Race.objects.filter(pk=race_id).select_related('event__city__region__country', 'event__series__city__region__country',
				'event__series__country', ).first()
			if race:
				event = race.event
				user_name = update.user.get_full_name()
				if event in last_events:
					last_events[event] += ', <nobr>{}</nobr>'.format(race.distance)
					editors[event].add(user_name)
				else:
					if len(last_events) == LAST_PROTOCOLS_EVENT_NUMBER:
						break
					last_events[event] = '<nobr>{}</nobr>'.format(race.distance)
					editors[event] = set([user_name])
					dates[event] = update.added_time
	res = OrderedDict()
	for event, distances in list(last_events.items()):
		res[event] = {'distances': distances, 'editors': ', '.join(editors[event]), 'date': dates[event]}
	generate_html('generators/last_loaded_protocols.html', {'last_events': res}, 'last_loaded_protocols.html',
		to_old_probeg='dj_media/blocks/5_block_protokol.php')

def generate_last_added_reviews():
	last_reviews = models.Document.objects.filter(
		document_type__in=(models.DOC_TYPE_PHOTOS, models.DOC_TYPE_IMPRESSIONS), series=None).select_related(
		'created_by__user_profile', 'event__series__city__region__country', 'event__city__region__country').order_by(
		'-date_posted')[:LAST_PROTOCOLS_EVENT_NUMBER]
	res = []
	for review in last_reviews:
		user = review.created_by
		show_link_to_author = (review.author == user.get_full_name()) and hasattr(user, 'user_profile') and user.user_profile.is_public
		doc_type = 'отчёт' if (review.document_type == models.DOC_TYPE_IMPRESSIONS) else 'фотоальбом'
		res.append((review, doc_type, show_link_to_author))
	generate_html('generators/last_added_reviews.html', {'last_reviews': res}, 'last_added_reviews.html')

def generate_events_in_seria_by_year(debug=False): # For Nadya
	with io.open(os.path.join(settings.BASE_DIR, 'results/templates/generated/events_in_seria_by_year.html'), 'w', encoding="utf8") as output_file:
		context_header = {}
		context_header['page_title'] = "Все забеги {}-{} годов в России по сериям".format(
			models.NADYA_CALENDAR_YEAR_START, models.NADYA_CALENDAR_YEAR_END)
		context_header['last_update'] = datetime.datetime.now()
		output_file.write(render_to_string('generators/events_in_seria_by_year_header.html', context_header))

		series_ids = set(models.Event.objects.filter(series__city__region__country_id='RU', start_date__year__gte=2010).exclude(
			pk__in=models.Series.get_russian_parkrun_ids()).values_list('series_id', flat=True).distinct())
		all_series = models.Series.objects.filter(pk__in=series_ids).select_related('city')
		context = {}
		context['years'] = list(range(models.NADYA_CALENDAR_YEAR_START, models.NADYA_CALENDAR_YEAR_END + 1))
		for region in models.Region.objects.filter(country_id='RU', active=True).order_by('name'):
			context['region'] = region
			context['seria'] = OrderedDict()
			for series in all_series.filter(city__region=region).order_by('city__name', 'name'):
				events = []
				for year in range(models.NADYA_CALENDAR_YEAR_START, models.NADYA_CALENDAR_YEAR_END + 1):
					events.append(series.event_set.filter(start_date__year=year).select_related('series__city__region__country',
						'city__region__country', 'series__country').order_by('start_date'))
				context['seria'][series] = events
			if debug:
				print('{}: {} series are processed'.format(region.name_full, all_series.filter(city__region=region).count()))
			output_file.write(render_to_string('generators/event_in_seria_by_year_spaces.html', context))
		output_file.write(render_to_string('generators/events_in_seria_by_year_footer.html', {}))

def most_popular_clubs(year=2018, to_exclude_parkrun=True):
	results = models.Result.objects.filter(race__event__start_date__year=year, source=models.RESULT_SOURCE_DEFAULT)
	if to_exclude_parkrun:
		results = results.exclude(race__event__series_id__in=models.Series.get_russian_parkrun_ids())
	c = Counter(s.lower().replace('"', '').replace('\n', ' ').replace('   ', ' ').replace('  ', ' ').replace('“', '').replace('”', '').replace(
			'«', ' ').replace('»', '').replace('клб ', '').replace('клуб любителей бега ', '').replace('клуб ', '').strip()
		for s in results.values_list('club_name', flat=True))

	# with io.open('club_names_2018.txt', 'w', encoding="utf8") as output_file:
	# 	for k, v in sorted(c.items()):
	# 		# output_file.write(u'{}\t{}\n'.format(k, v))
	# 		output_file.write(u'{}\n'.format(k))
	# return

	with io.open('club_names_2018_win.txt', 'w', encoding="cp1251") as output_file:
		for k, v in sorted(c.items()):
			try:
				s_cp1251 = ''.join([i if is_good_symbol(i) else '' for i in k])
				output_file.write(s_cp1251 + '\n')
			except Exception as e:
				pass
	return

	bad_club_names = ['', 'независимый', 'лично', 'noclub', '-', 'rus', 'нет клуба/no club', 'санкт-петербург', '(kyiv)', 'нет', '(dnipro)']
	for bad_name in bad_club_names:
		if bad_name in c:
			del c[bad_name]

	other_names = [
		('wake&amp;run', 'wake&run'),
		('клб "вита"', 'вита'),
		('ilr', 'i love running'),
		('мк "бим"', 'бим'),
		('ао "фпк"', 'фпк'),
		# (u'', u''),
		# (u'', u''),
		# (u'', u''),
		# (u'', u''),
	]

	for bad, good in other_names:
		if bad in c:
			c[good] += c[bad]
			del c[bad]

	for club, count in c.most_common(200):
		print(club, '%t', count)
	print('Total', len(c))

def generate_parkrun_stat_table():
	context = {}
	context['strange'] = []
	context['parkruns_data'] = []
	context['today'] = datetime.date.today().strftime("%d.%m.%Y")
	parkrun_series_ids = set()
	for series in models.Series.get_russian_parkruns().order_by('name'):
		data = {}
		data['series'] = series
		data['name'] = series.name[len('parkrun '):]
		races = models.Race.objects.filter(event__series=series, loaded=models.RESULTS_LOADED)
		data['n_events'] = races.count()
		if data['n_events'] == 0:
			context['parkruns_data'].append(data)
			continue

		data['sum_participants'] = races.aggregate(Sum('n_participants'))['n_participants__sum']
		data['avg_n_participants'] = data['sum_participants'] / data['n_events']
		data['avg_n_participants_for_sort'] = results_util.int_safe(data['avg_n_participants'] * 100)
		results = models.Result.objects.filter(race__event__series=series, source=models.RESULT_SOURCE_DEFAULT)
		if results.count() != data['sum_participants']:
			context['strange'].append('В серии {} (id {}) сумма чисел участников — {}, а результатов в базе данных — {}'.format(
				series.name, series.id, data['sum_participants'], results.count()))

		parkrun_ids = Counter(results.values_list('parkrun_id', flat=True))
		data['n_different_participants'] = len(parkrun_ids)
		data['most_participations'] = parkrun_ids.most_common(1)[0][1]
		data['most_frequent_participants'] = [(models.Runner.objects.filter(parkrun_id=parkrun_id).first(), n)
			for parkrun_id, n in parkrun_ids.most_common(3)]
		data['women_percent'] = int(round((100 * results.filter(gender=results_util.GENDER_FEMALE).count()) / data['sum_participants']))

		for key, gender in (('male', results_util.GENDER_MALE), ('female', results_util.GENDER_FEMALE)):
			results_by_gender = results.filter(gender=gender).order_by('result')
			n_results_by_gender = results_by_gender.count()
			best_result = results_by_gender.first()
			if best_result:
				data[key + '_record'] = models.centisecs2time(best_result.result)
				data[key + '_recordsman'] = best_result.runner
				data[key + '_mean'] = models.centisecs2time(sum(results_by_gender.values_list('result', flat=True)) // n_results_by_gender,
					round_hundredths=True)
				data[key + '_median'] = results_by_gender[(n_results_by_gender - 1) // 2]

		context['parkruns_data'].append(data)
		parkrun_series_ids.add(series.id)

	context['not_parkruns'] = models.Series.objects.filter(is_weekly=True).exclude(pk__in=parkrun_series_ids).annotate(Count('event')).order_by('city__name', 'name')
	generate_html('generators/parkrun_table.html', context, 'parkrun_table.html')

def get_best_participants_dict(participants, year):
	participants_cur_year = participants.filter(year=year)
	participants_male = participants_cur_year.filter(klb_person__gender=results_util.GENDER_MALE)
	participants_female = participants_cur_year.filter(klb_person__gender=results_util.GENDER_FEMALE)
	data = {}
	data['n_participants'] = participants_cur_year.count()
	data['n_participants_male'] = participants_male.count()
	data['n_participants_female'] = participants_female.count()
	data['best_male'] = participants_male.order_by('place').first()
	data['best_female'] = participants_female.order_by('place').first()
	data['n_participants_prev_year'] = participants.filter(year=year - 1).count()
	return data

def generate_klb_winners_by_regions(year):
	context = {}
	context['year'] = year
	context['page_title'] = f'КЛБМатч-{models_klb.year_string(year)}: Итоги по регионам и странам'
	context['n_results_for_bonus_score'] = models_klb.get_n_results_for_bonus_score(year)
	context['main_countries'] = OrderedDict()
	COUNTRIES_WITH_REGIONS = ('RU', 'UA', 'BY')
	all_participants = models.Klb_participant.objects.filter(n_starts__gt=0).select_related('klb_person__runner__user__user_profile')
	for country_id in COUNTRIES_WITH_REGIONS:
		country_data = OrderedDict()
		country = models.Country.objects.get(pk=country_id)
		for region in country.region_set.filter(active=True).order_by('name'):
			country_data[region] = get_best_participants_dict(all_participants.filter(klb_person__city__region_id=region.id), year)

		total = get_best_participants_dict(all_participants.filter(klb_person__city__region__country_id=country_id), year)
		context['main_countries'][country] = {'regions': country_data, 'total': total}

	context['other_countries'] = OrderedDict()
	other_countries_ids = set(all_participants.filter(year=year).exclude(
		klb_person__city__region__country_id__in=COUNTRIES_WITH_REGIONS).values_list('klb_person__city__region__country_id', flat=True))
	for country in models.Country.objects.filter(pk__in=other_countries_ids).order_by('name'):
		context['other_countries'][country] = get_best_participants_dict(all_participants.filter(
			klb_person__city__region__country_id=country.id), year)

	context['districts'] = OrderedDict()
	context['clubs_by_districts'] = OrderedDict()
	for district in models.District.objects.filter(country_id='RU').order_by('name'):
		context['districts'][district] = get_best_participants_dict(all_participants.filter(klb_person__city__region__district_id=district.id), year)
		context['clubs_by_districts'][district] = models.Klb_team.objects.filter(
			year=year, club__city__region__district_id=district.id).select_related('club__city__region').order_by('place')
	generate_html('generators/klb_winners_by_region.html', context, f'{year}.html', dir='results/templates/klb/winners_by_region')

def generate_admin_work_stat():
	context = {}
	context['page_title'] = 'Кто сколько чего сделал в этом и прошлом году'
	today = datetime.date.today()
	cur_year = today.year
	context['today'] = today
	context['months'] = []
	years = [cur_year, cur_year - 1] if (today.month <= 6) else [cur_year]
	for year in years:
		last_month = today.month if (cur_year == year) else 12
		users = Group.objects.get(name="admins").user_set.exclude(pk__in=(230, 3384)).order_by('last_name')
		month_names = ['', 'Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь', 'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь']
		for month in range(last_month, 0, -1):
			month_data = {}
			month_data['month'] = '{} {}'.format(month_names[month], year)
			date_start = datetime.datetime(year, month, 1, tzinfo=timezone.utc)
			date_end = datetime.datetime(year, month + 1, 1, tzinfo=timezone.utc) if (month < 12) else datetime.datetime(year + 1, 1, 1, tzinfo=timezone.utc)
			month_updates = models.Table_update.objects.filter(added_time__range=(date_start, date_end))
			month_data['users'] = []
			for user in users:
				user_updates = month_updates.filter(user=user)
				d = {}
				d['user'] = user
				d['series_created'] = user_updates.filter(model_name='Series', action_type=models.ACTION_CREATE).count()
				d['series_updated'] = user_updates.filter(model_name='Series', action_type=models.ACTION_UPDATE).count()
				d['events_created'] = user_updates.filter(model_name='Event', action_type=models.ACTION_CREATE).count()
				d['events_updated'] = user_updates.filter(model_name='Event', action_type=models.ACTION_UPDATE).count()
				d['races_created'] = user_updates.filter(model_name='Event', action_type=models.ACTION_RACE_CREATE).count()
				d['races_updated'] = user_updates.filter(model_name='Event', action_type=models.ACTION_RACE_UPDATE).count()
				d['runners_created'] = user_updates.filter(model_name='Runner', action_type=models.ACTION_CREATE).count()
				d['runners_updated'] = user_updates.filter(model_name='Runner', action_type=models.ACTION_UPDATE).count()
				d['documents_created'] = user_updates.filter(model_name='Event', action_type=models.ACTION_DOCUMENT_CREATE).count()
				d['documents_updated'] = user_updates.filter(model_name='Event', action_type=models.ACTION_DOCUMENT_UPDATE).count()
				d['news_created'] = user_updates.filter(model_name='Event', action_type=models.ACTION_NEWS_CREATE).count() \
					+ user_updates.filter(model_name='News', action_type=models.ACTION_CREATE).count()
				d['news_updated'] = user_updates.filter(model_name='Event', action_type=models.ACTION_NEWS_UPDATE).count() \
					+ user_updates.filter(model_name='News', action_type=models.ACTION_UPDATE).count()
				d['off_results_created'] = user_updates.filter(model_name='Event', action_type=models.ACTION_RESULTS_LOAD).count()
				d['off_results_uploaded'] = models.Result.objects.filter(added_time__range=(date_start, date_end), source=models.RESULT_SOURCE_DEFAULT,
					loaded_by=user).count()
				d['off_results_updated'] = user_updates.filter(model_name='Event', action_type=models.ACTION_RESULT_UPDATE).count()
				d['unoff_results_created'] = user_updates.filter(model_name='Event', action_type=models.ACTION_UNOFF_RESULT_CREATE).count()
				d['klb_participants_created'] = user_updates.filter(model_name='Klb_person', action_type=models.ACTION_KLB_PARTICIPANT_CREATE).count()
				d['klb_participants_updated'] = user_updates.filter(model_name='Klb_person', action_type=models.ACTION_KLB_PARTICIPANT_UPDATE).count()
				d['social_posts_created'] = user_updates.filter(action_type=models.ACTION_SOCIAL_POST).count()
				d['off_results_approved'] = month_updates.filter(action_type=models.ACTION_RESULT_UPDATE, verified_by=user).count()
				d['unoff_results_approved'] = month_updates.filter(action_type=models.ACTION_UNOFF_RESULT_CREATE, verified_by=user).count()
				d['klb_results_created'] = user_updates.filter(action_type=models.ACTION_KLB_RESULT_CREATE).count()
				d['created_total'] = user_updates.count()
				d['verified_total'] = month_updates.filter(verified_by=user).count()

				month_data['users'].append(d)

			context['months'].append(month_data)

	month_data = {}
	month_data['month'] = 'За всегда (с 2016 года)'
	month_updates = models.Table_update.objects
	month_data['users'] = []
	for user in users:
		user_updates = month_updates.filter(user=user)
		d = {}
		d['user'] = user
		d['series_created'] = user_updates.filter(model_name='Series', action_type=models.ACTION_CREATE).count()
		d['series_updated'] = user_updates.filter(model_name='Series', action_type=models.ACTION_UPDATE).count()
		d['events_created'] = user_updates.filter(model_name='Event', action_type=models.ACTION_CREATE).count()
		d['events_updated'] = user_updates.filter(model_name='Event', action_type=models.ACTION_UPDATE).count()
		d['races_created'] = user_updates.filter(model_name='Event', action_type=models.ACTION_RACE_CREATE).count()
		d['races_updated'] = user_updates.filter(model_name='Event', action_type=models.ACTION_RACE_UPDATE).count()
		d['runners_created'] = user_updates.filter(model_name='Runner', action_type=models.ACTION_CREATE).count()
		d['runners_updated'] = user_updates.filter(model_name='Runner', action_type=models.ACTION_UPDATE).count()
		d['documents_created'] = user_updates.filter(model_name='Event', action_type=models.ACTION_DOCUMENT_CREATE).count()
		d['documents_updated'] = user_updates.filter(model_name='Event', action_type=models.ACTION_DOCUMENT_UPDATE).count()
		d['news_created'] = user_updates.filter(model_name='Event', action_type=models.ACTION_NEWS_CREATE).count() \
			+ user_updates.filter(model_name='News', action_type=models.ACTION_CREATE).count()
		d['news_updated'] = user_updates.filter(model_name='Event', action_type=models.ACTION_NEWS_UPDATE).count() \
			+ user_updates.filter(model_name='News', action_type=models.ACTION_UPDATE).count()
		d['off_results_created'] = user_updates.filter(model_name='Event', action_type=models.ACTION_RESULTS_LOAD).count()
		d['off_results_uploaded'] = models.Result.objects.filter(source=models.RESULT_SOURCE_DEFAULT, loaded_by=user).count()
		d['off_results_updated'] = user_updates.filter(model_name='Event', action_type=models.ACTION_RESULT_UPDATE).count()
		d['unoff_results_created'] = user_updates.filter(model_name='Event', action_type=models.ACTION_UNOFF_RESULT_CREATE).count()
		d['klb_participants_created'] = user_updates.filter(model_name='Klb_person', action_type=models.ACTION_KLB_PARTICIPANT_CREATE).count()
		d['klb_participants_updated'] = user_updates.filter(model_name='Klb_person', action_type=models.ACTION_KLB_PARTICIPANT_UPDATE).count()
		d['social_posts_created'] = user_updates.filter(action_type=models.ACTION_SOCIAL_POST).count()
		d['off_results_approved'] = month_updates.filter(action_type=models.ACTION_RESULT_UPDATE, verified_by=user).count()
		d['unoff_results_approved'] = month_updates.filter(action_type=models.ACTION_UNOFF_RESULT_CREATE, verified_by=user).count()
		d['klb_results_created'] = user_updates.filter(action_type=models.ACTION_KLB_RESULT_CREATE).count()
		d['created_total'] = user_updates.count()
		d['verified_total'] = month_updates.filter(verified_by=user).count()

		month_data['users'].append(d)

	context['months'].append(month_data)
	generate_html('generators/admin_work_stat.html', context, 'admin_work_stat.html')
