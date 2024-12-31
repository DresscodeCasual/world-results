from django.views.generic.base import RedirectView
from django.urls import path, register_converter

from tools import url_param_converters
from .views import views_age_group_record, views_club, views_mail
from .views import views_news, views_organizer, views_parkrun
from .views import views_race, views_result, views_runner, views_series, views_site, views_useful_link, views_user

app_name = 'results'

register_converter(url_param_converters.CountryConverter, 'country')
register_converter(url_param_converters.FourDigitYearConverter, 'year')
register_converter(url_param_converters.IntegerConverter, 'integer')
register_converter(url_param_converters.CountryOfThreeConverter, 'country_of_3')
register_converter(url_param_converters.GenderConverter, 'gender')
register_converter(url_param_converters.SeriesTabConverter, 'series_tab')

urlpatterns = [
	path(r'', views_site.main_page, name='main_page'),
	path(r'home/', views_user.home, name='home'),
	path(r'series/<int:series_id>/', views_series.series_details, name='series_details'),
	path(r'series/<int:series_id>/<series_tab:tab>/', views_series.series_details, name='series_details'),

	path(r'event/<int:event_id>/', views_race.event_details, name='event_details'),
	path(r'event/<int:event_id>/age_group_records/', views_race.event_age_group_records, name='event_age_group_records'),
	path(r'race/<int:race_id>/', views_race.race_details, name='race_details'),
	path(r'race/<int:race_id>/tab_editor/', views_race.race_details, {'tab_editor': 1}, name='race_details_tab_editor'),
	path(r'race/<int:race_id>/tab_unofficial/', views_race.race_details, {'tab_unofficial': 1}, name='race_details_tab_unofficial'),
	path(r'race/<int:race_id>/add_to_club/', views_race.race_details, {'tab_add_to_club': 1}, name='race_details_tab_add_to_club'),

	path(r'logo/event/<int:event_id>/', views_race.get_logo_page, name='get_logo_page'),
	path(r'logo/series/<int:series_id>/', views_race.get_logo_page, name='get_logo_page'),
	path(r'logo/organizer/<int:organizer_id>/', views_race.get_logo_page, name='get_logo_page'),

	path(r'add_event_to_calendar/<int:event_id>/', views_race.add_event_to_calendar, name='add_event_to_calendar'),
	path(r'remove_event_from_calendar/<int:event_id>/', views_race.remove_event_from_calendar, name='remove_event_from_calendar'),

	path(r'results/disconnected/', views_result.results, {'disconnected': True}, name='results_disconnected'),
	path(r'results/disconnected/<str:lname>/', views_result.results, {'disconnected': True}, name='results_disconnected'),
	path(r'results/disconnected/<str:lname>/<str:fname>/', views_result.results, {'disconnected': True}, name='results_disconnected'),
	path(r'results/disconnected//<str:fname>/', views_result.results, {'disconnected': True}, name='results_disconnected'),
	path(r'results/', views_result.results, name='results'),
	path(r'results/<str:lname>/', views_result.results, name='results'),
	path(r'results/<str:lname>/<str:fname>/', views_result.results, name='results'),
	path(r'results//<str:fname>/', views_result.results, name='results'),

	path(r'races/', views_race.races, name='races'),
	path(r'races/year_ahead/', views_race.races_default, {'full': True}, name='races_year_ahead'),
	path(r'races/view/<int:view>/', views_race.races, name='races'), # Not used currently. Useful for testing.
	path(r'races/country/<country:country_id>/', views_race.races, name='races'),
	path(r'races/region/<int:region_id>/', views_race.races, name='races'),
	path(r'races/region/<int:region_id>/date_region/<int:date_region>/', views_race.races, name='races'),
	path(r'races/region_group/<str:region_group>/', views_race.races, name='races'),
	path(r'races/region_group/<str:region_group>/date_region/<int:date_region>/', views_race.races, name='races'),
	path(r'races/city/<int:city_id>/', views_race.races, name='races'),
	path(r'races/distance/<int:distance_id>/', views_race.races, name='races'),
	path(r'races/name/<path:race_name>/', views_race.races, name='races'),
	path(r'calendar/trails/', views_race.future_trails, name='future_trails'),
	path(r'calendar/parkruns/', views_race.parkruns_and_similar, name='parkruns_and_similar'),
	path(r'calendar/masters/', views_race.events_for_masters, name='events_for_masters'),
	path(r'calendar/triathlon/', views_race.events_triathlon, name='events_triathlon'),

	path(r'races/date_region/<int:date_region>/', views_race.races, name='races'),
	path(r'races/country/<country:country_id>/date_region/<int:date_region>/', views_race.races, name='races'),
	path(r'races/region/<int:region_id>/date_region/<int:date_region>/', views_race.races, name='races'),
	path(r'races/city/<int:city_id>/date_region/<int:date_region>/', views_race.races, name='races'),
	
	path(r'details/', views_user.my_details, name='my_details'),
	path(r'details/just_registered/', views_user.my_details, {'just_registered': True}, name='my_details_just_registered'),
	path(r'details/user/<int:user_id>/', views_user.my_details, name='my_details'),
	path(r'details/resend/', views_user.send_confirmation_letter, name='send_confirmation_letter'),
	path(r'details/resend/user/<int:user_id>/', views_user.send_confirmation_letter, name='send_confirmation_letter'),
	path(r'verify_email/<str:code>/', views_user.verify_email, name='verify_email'),

	path(r'user/<int:user_id>/', views_user.user_details, name='user_details'),
	path(r'user/<int:user_id>/full/', views_user.user_details_full, name='user_details_full'),
	path(r'user/<int:user_id>/delete_club/<int:club_id>/', views_user.user_details, name='user_delete_club'),
	path(r'user/<int:user_id>/series/<int:series_id>/', views_user.user_details, name='user_details'),
	path(r'get_avatar/user/<int:user_id>/', views_user.get_avatar_page, name='get_avatar_page'),

	path(r'planned_events/', views_user.planned_events, name='planned_events'),
	path(r'user/<int:user_id>/planned_events/', views_user.planned_events, name='planned_events'),

	path(r'details/add_name/', views_user.my_name_add, name='name_add'),
	path(r'details/delete_name/<int:name_id>/', views_user.my_name_delete, name='name_delete'),

	path(r'strava_links/', views_user.my_strava_links, name='my_strava_links'),
	path(r'strava_links/user/<int:user_id>/', views_user.my_strava_links, name='my_strava_links'),

	path(r'news/', views_news.all_news, name='all_news'),
	path(r'news/country/<country:country_id>/', views_news.all_news, name='all_news'),
	path(r'news/region/<int:region_id>/', views_news.all_news, name='all_news'),
	path(r'news/city/<int:city_id>/', views_news.all_news, name='all_news'),
	path(r'news/<int:news_id>/', views_news.news_details, name='news_details'),
	path(r'blog/', views_news.blog, name='blog'),

	path(r'find_results/', views_user.find_results, name='find_results'),
	path(r'find_results/user/<int:user_id>/', views_user.find_results, name='find_results'),
	path(r'find_results/runner/<int:runner_id>/', views_user.find_results, name='find_results'),
	path(r'claim_result/<int:result_id>/', views_result.claim_result, name='claim_result'),
	path(r'unclaim_result/<int:result_id>/', views_result.unclaim_result, name='unclaim_result'),
	path(r'unclaim_results/', views_result.unclaim_results, name='unclaim_results'),
	path(r'race/<int:race_id>/unclaim_result/<int:result_id>/', views_result.unclaim_result, name='unclaim_result'),

	path(r'send_message/', views_mail.send_message, name='send_message'),
	path(r'send_message_admin/', views_mail.send_message_admin, name='send_message_admin'),
	path(r'get_send_to_info_page/', views_mail.get_send_to_info_page, name='get_send_to_info_page'),
	path(r'get_send_from_info_page/', views_mail.get_send_from_info_page, name='get_send_from_info_page'),
	path(r'get_send_from_info_page/ticket/<int:table_update_id>/', views_mail.get_send_from_info_page, name='get_send_from_info_page'),
	path(r'get_send_from_info_page/ticket/<int:table_update_id>/wrong_club/', views_mail.get_send_from_info_page, {'wrong_club': True},
		name='get_send_from_info_page_wrong_club'),
	path(r'get_send_from_info_page/event/<int:event_id>/', views_mail.get_send_from_info_page, name='get_send_from_info_page'),
	path(r'get_send_from_info_page/event_participants/<int:event_participants_id>/', views_mail.get_send_from_info_page,
		name='get_send_from_info_page'),
	path(r'get_send_from_info_page/event_wo_protocols/<int:event_wo_protocols_id>/', views_mail.get_send_from_info_page,
		name='get_send_from_info_page'),
	path(r'get_send_from_info_page/user/<int:user_id>/', views_mail.get_send_from_info_page, name='get_send_from_info_page'),

	path(r'get_add_result_page/event/<int:event_id>/', views_result.get_add_result_page, name='get_add_result_page'),
	path(r'add_unofficial_result/event/<int:event_id>/', views_result.add_unofficial_result, name='add_unofficial_result'),
	path(r'delete_unofficial_result/<int:result_id>/', views_result.delete_unofficial_result, name='delete_unofficial_result'),

	path(r'get_add_event_page/series/<int:series_id>/', views_mail.get_add_event_page, name='get_add_event_page'),
	path(r'get_add_series_page/', views_mail.get_add_series_page, name='get_add_series_page'),
	path(r'add_unofficial_event/series/<int:series_id>/', views_mail.add_unofficial_event, name='add_unofficial_event'),
	path(r'add_unofficial_series/', views_mail.add_unofficial_series, name='add_unofficial_series'),

	path(r'get_add_review_page/event/<int:event_id>/', views_mail.get_add_review_page, name='get_add_review_page'),
	path(r'get_add_review_page/event/<int:event_id>/photo/', views_mail.get_add_review_page, {'photo': True}, name='get_add_photo_page'),
	path(r'add_review/', views_mail.add_review, name='add_review'),

	path(r'runner/<int:runner_id>/', views_runner.runner_details, name='runner_details'),
	path(r'runner/<int:runner_id>/full/', views_runner.runner_details, {'show_full_page': True}, name='runner_details_full'),
	path(r'runner/<int:runner_id>/series/<int:series_id>/', views_runner.runner_details, name='runner_details'),
	path(r'runners/fname/<str:fname>/', views_runner.runners, name='runners'),
	path(r'runners/name/', views_runner.runners, name='runners'),
	path(r'runners/', views_runner.runners, name='runners'),
	path(r'runners/name/<str:lname>/', views_runner.runners, name='runners'),
	path(r'runners/name/<str:lname>/<str:fname>/', views_runner.runners, name='runners'),

	path(r'result/<int:result_id>/', views_result.result_details, name='result_details'),

	path(r'clubs/', views_club.clubs, name='clubs'),
	path(r'clubs/about/', views_club.about_club_membership, name='about_club_membership'),
	path(r'clubs/<int:view>/', views_club.clubs, name='clubs'),
	path(r'club/<int:club_id>/', views_club.club_details, name='club_details'),
	path(r'club/<int:club_id>/planned_starts/', views_club.planned_starts, name='planned_starts'),
	path(r'club/<int:club_id>/records/', views_club.club_records, name='club_records'),
	path(r'club/<int:club_id>/records/<year:year>/', views_club.club_records, name='club_records'),
	path(r'club/<int:club_id>/members/', views_club.club_members, name='club_members'),
	path(r'club/<int:club_id>/members/all/', views_club.club_members_all, name='club_members_all'),
	path(r'club/<int:club_id>/members/order/<str:ordering>/', views_club.club_members, name='club_members'),
	path(r'club/<int:club_id>/members/all/order/<str:ordering>/', views_club.club_members_all, name='club_members_all'),

	path(r'protocols_wanted/', views_race.protocols_wanted, name='protocols_wanted'),
	path(r'protocols_wanted/no_protocol/', views_race.protocols_wanted, {'events_type_code': 'no_protocol'}, name='protocols_wanted_no_protocol'),
	path(r'protocols_wanted/protocol_in_complicated_format/', views_race.protocols_wanted, {'events_type_code': 'protocol_in_complicated_format'},
	 	name='protocols_wanted_complicated_format'),
	path(r'protocols_wanted/<str:events_type_code>/<str:year>/<int:region_id>/', views_race.protocols_wanted, name='protocols_wanted'),

	path(r'rating/', views_race.rating, name='rating'),
	path(r'rating/<str:country_id>/<str:distance_code>/<int:year>/<str:rating_type_code>/', views_race.rating, name='rating'),
	path(r'rating/<str:country_id>/<str:distance_code>/<int:year>/<str:rating_type_code>/<int:page>/', views_race.rating, name='rating'),

	path(r'add_new_event/', views_site.add_new_event, name='add_new_event'),
	path(r'how_to_add_event/', RedirectView.as_view(pattern_name='results:add_new_event', permanent=True), name='how_to_add_event'),

	path(r'organizers/', views_organizer.organizers, name='organizers'),
	path(r'organizer/<int:organizer_id>/', views_organizer.organizer_details, name='organizer_details'),

	path(r'links/', views_useful_link.useful_links, name='useful_links'),
	path(r'links/suggest/', views_useful_link.suggest_link, name='suggest_useful_link'),

	# path(r'age_group_records/', views_age_group_record.age_group_records, name='age_group_records'),
	# path(r'age_group_records/<country_of_3:country_id>/', views_age_group_record.age_group_records, name='age_group_records'),
	# path(r'age_group_records/<country_of_3:country_id>/<gender:gender_code>/<int:age>'
	# 		+ r'/<str:distance_code>/<str:surface_code>/',
	# 	views_age_group_record.age_group_details, name='age_group_record_details'),

	# path(r'age_group_records/<country_of_3:country_id>/<str:distance_code>/<str:surface_code>/',
	# 	views_age_group_record.records_for_distance, name='age_group_records_for_distance'),

	# path(r'age_group_records/marathon/<gender:gender_code>/',
	# 	views_age_group_record.records_for_marathon, name='age_group_records_for_marathon'),

	# path(r'age_group_records/by_month/<country_of_3:country_id>/', views_age_group_record.age_group_records_by_month, name='age_group_records_by_month_initial'),
	# path(r'age_group_records/by_month/<country_of_3:country_id>/<int:year>/<int:month>/', views_age_group_record.age_group_records_by_month, name='age_group_records_by_month'),

	# path(r'age_group_records/commission_protocols/<int:session_id>/', views_age_group_record.commission_protocol, name='commission_protocol'),

	# path(r'ultra_records/', views_age_group_record.ultra_records, name='ultra_records'),
	# path(r'ultra_records/<country_of_3:country_id>/', views_age_group_record.ultra_records, name='ultra_records'),
	# path(r'ultra_records/<country_of_3:country_id>/<gender:gender_code>/<str:distance_code>/',
	# 	views_age_group_record.ultra_record_details, name='ultra_record_details'),

	# path(r'best_by_regions_visited/<country_of_3:country_id>/', views_runner.best_by_regions_visited, name='best_by_regions_visited'),
	# path(r'runner/<int:runner_id>/regions/<country_of_3:country_id>/distance/<str:distance_code>/', views_runner.regions_for_runner, name='regions_for_runner'),

	# path(r'archive/', views_site.archive, name='archive'),

	path(r'search/', views_site.search_by_text, name='search_by_text'),
]