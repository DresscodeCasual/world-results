from django.urls import path, register_converter

from tools import url_param_converters
from . import parse_weekly_events
from .views import views_ad
from .views import views_age_group_record
from .views import views_ajax
from .views import views_city
from .views import views_club
from .views import views_course
from .views import views_db_structure
from .views import views_distance
from .views import views_document
from .views import views_event
from .views import views_klb
from .views import views_klb_person
from .views import views_klb_race
from .views import views_klb_report
from .views import views_klb_team
from .views import views_mail
from .views import views_name
from .views import views_news
from .views import views_organizer
from .views import views_parkrun
from .views import views_protocol
from .views import views_protocol_queue
from .views import views_race
from .views import views_region
from .views import views_result
from .views import views_runner
from .views import views_series
from .views import views_site
from .views import views_social
from .views import views_useful_link
from .views import views_user
from .views import views_util

app_name = 'editor'

register_converter(url_param_converters.CountryConverter, 'country')
register_converter(url_param_converters.FourDigitYearConverter, 'year')
register_converter(url_param_converters.CountryOfThreeConverter, 'country_of_3')
register_converter(url_param_converters.CyrillicWordConverter, 'cyrillic_word')
register_converter(url_param_converters.ModelNameConverter, 'model_name')
register_converter(url_param_converters.GenderConverter, 'gender')

urlpatterns = [
	path(r'cities/', views_city.cities, name='cities'),
	path(r'cities/country/<country:country_id>/', views_city.cities, name='cities'),
	path(r'cities/region/<int:region_id>/', views_city.cities, name='cities'),

	path(r'city/<int:city_id>/', views_city.city_details, name='city_details'),
	path(r'city/<int:city_id>/update/', views_city.city_update, name='city_update'),
	path(r'city/<int:city_id>/delete/', views_city.city_delete, name='city_delete'),
	path(r'city/create/', views_city.city_create, name='city_create'),
	path(r'city/create/region/<int:region_id>/', views_city.city_create, name='city_create'),
	path(r'city/<int:city_id>/history/', views_city.city_changes_history, name='city_changes_history'),

	path(r'cities/list/', views_ajax.cities_list, name='cities_list'),
	path(r'cities/list_by_name/', views_ajax.cities_list_by_name, name='cities_list_by_name'),
	path(r'klb/participants/list/race/<int:race_id>/', views_ajax.participants_list, name='participants_list'),
	path(r'klb/unpaid_participants/list/', views_ajax.unpaid_participants_list, name='unpaid_participants_list'),
	path(r'race/<int:race_id>/results/list/', views_ajax.race_result_list, name='race_result_list'),
	path(r'runners/list/', views_ajax.runners_list, name='runners_list'),
	path(r'runners/list/with_birthday/', views_ajax.runners_with_birthday_list, name='runners_with_birthday_list'),
	path(r'runners/list/runner/<int:runner_id>/', views_ajax.runners_list, name='runners_list'),
	path(r'runners/list/race/<int:race_id>/', views_ajax.runners_list, name='runners_list'),
	path(r'organizers/list/', views_ajax.organizers_list, name='organizers_list'),
	path(r'organizers/list/organizer/<int:organizer_id>/', views_ajax.organizers_list, name='organizers_list'),
	path(r'series/list/', views_ajax.series_list, name='series_list'),
	path(r'series/list/organizer/<int:organizer_id>/', views_ajax.series_list, name='series_list'),
	path(r'persons/list/', views_ajax.persons_list, name='persons_list'),
	path(r'persons/list/person/<int:person_id>/', views_ajax.persons_list, name='persons_list'),

	path(r'series/', views_series.seria, name='seria'),
	path(r'series/country/<country:country_id>/', views_series.seria, name='seria'),
	path(r'series/region/<int:region_id>/', views_series.seria, name='seria'),
	path(r'series/city/<int:city_id>/', views_series.seria, name='seria'),
	path(r'series/name/<cyrillic_word:series_name>/', views_series.seria, name='seria'),
	path(r'events_wo_protocol/<year:year>/', views_series.events_wo_protocol, name='events_wo_protocol'),
	path(r'events_wo_protocol_for_klb/<year:year>/', views_series.events_wo_protocol_for_klb, name='events_wo_protocol_for_klb'),
	path(r'events_not_in_next_year/<year:year>/', views_series.events_not_in_next_year, name='events_not_in_next_year'),
	path(r'events_wo_statistics/<year:year>/', views_series.events_wo_statistics, name='events_wo_statistics'),
	path(r'all_events_by_year/regions/<int:regions>/', views_series.all_events_by_year, name='all_events_by_year'),
	path(r'events_in_seria_by_year/', views_series.events_in_seria_by_year, name='events_in_seria_by_year'),
	path(r'gen_nadya_calendar/', views_series.gen_nadya_calendar, name='gen_nadya_calendar'),
	path(r'events_with_xls_protocol/', views_series.events_with_xls_protocol, name='events_with_xls_protocol'),
	path(r'events_in_klb/', views_series.events_in_klb, name='events_in_klb'),
	path(r'series_wo_new_event/', views_series.series_wo_new_event, name='series_wo_new_event'),

	path(r'series/<int:series_id>/', views_series.series_details, name='series_details'),
	path(r'series/<int:series_id>/update/', views_series.series_update, name='series_update'),
	path(r'series/<int:series_id>/delete/', views_series.series_delete, name='series_delete'),
	path(r'series/<int:series_id>/update_documents/', views_series.series_documents_update, name='series_documents_update'),
	path(r'series/<int:series_id>/update_strikes/', views_series.update_strikes, name='series_update_strikes'),

	path(r'series/create/', views_series.series_create, name='series_create'),
	path(r'series/create/series/<int:series_id>/', views_series.series_create, name='series_create'),
	path(r'series/create/country/<country:country_id>/', views_series.series_create, name='series_create'),
	path(r'series/create/region/<int:region_id>/', views_series.series_create, name='series_create'),
	path(r'series/create/city/<int:city_id>/', views_series.series_create, name='series_create'),
	path(r'series/<int:series_id>/history/', views_series.series_changes_history, name='series_changes_history'),

	path(r'event/<int:event_id>/', views_event.event_details, name='event_details'),
	path(r'event/<int:event_id>/news/<int:news_id>/', views_event.event_details, name='event_details'),
	path(r'event/<int:event_id>/update/', views_event.event_update, name='event_update'),
	path(r'event/<int:event_id>/update_distances/', views_event.event_distances_update, name='event_distances_update'),
	path(r'event/<int:event_id>/update_documents/', views_event.event_documents_update, name='event_documents_update'),
	path(r'event/<int:event_id>/update_news/', views_event.event_news_update, name='event_news_update'),
	path(r'event/<int:event_id>/delete/', views_event.event_delete, name='event_delete'),
	path(r'event/<int:event_id>/change_series/', views_event.event_change_series, name='event_change_series'),
	path(r'event/<int:event_id>/copy/', views_event.event_create, name='event_create'),
	path(r'series/<int:series_id>/event/create/', views_event.event_create, name='event_create'),
	path(r'event/<int:event_id>/history/', views_event.event_changes_history, name='event_changes_history'),
	path(r'event/<int:event_id>/make_news/', views_event.event_details_make_news, name='event_details_make_news'),
	path(r'event/<int:event_id>/remove_races_with_no_results/', views_event.remove_races_with_no_results, name='remove_races_with_no_results'),

	path(r'refresh_default_calendar/', views_event.refresh_default_calendar, name='refresh_default_calendar'),
	path(r'restart/', views_site.restart, name='restart'),

	path(r'race/<int:race_id>/', views_race.race_details, name='race_details'),
	path(r'race/<int:race_id>/update/', views_race.race_update, name='race_update'),
	path(r'race/<int:race_id>/fill_places/', views_result.race_fill_places, name='race_fill_places'),
	path(r'race/<int:race_id>/swap/<int:swap_type>/', views_result.race_swap_names, name='race_swap_names'),
	path(r'race/<int:race_id>/update_headers/', views_result.update_race_headers, name='update_race_headers'),
	path(r'race/<int:race_id>/update_stat/', views_race.race_update_stat, name='race_update_stat'),
	path(r'race/<int:race_id>/reload_weekly_race/', parse_weekly_events.reload_race_results, name='reload_weekly_race'),
	path(r'race/<int:race_id>/delete_skipped_parkrun/', views_parkrun.delete_skipped_parkrun, name='delete_skipped_parkrun'),
	path(r'race/<int:race_id>/add_unoff_result/', views_race.race_add_unoff_result, name='race_add_unoff_result'),
	path(r'race/<int:race_id>/delete_off_results/', views_race.race_delete_off_results, name='race_delete_off_results'),

	path(r'regions/', views_region.regions, name='regions'),

	path(r'distances/', views_distance.distances, name='distances'),
	path(r'distance/<int:distance_id>/', views_distance.distance_details, name='distance_details'),
	path(r'distance/<int:distance_id>/update/', views_distance.distance_update, name='distance_update'),
	path(r'distance/<int:distance_id>/delete/', views_distance.distance_delete, name='distance_delete'),
	path(r'distance/<int:distance_id>/history/', views_distance.distance_changes_history, name='distance_changes_history'),

	path(r'distance/create/', views_distance.distance_create, name='distance_create'),

	path(r'documents/add/', views_document.add_docs, name='add_docs'),
	path(r'documents/add_to_old_fields/', views_document.add_docs_to_old_fields, name='add_docs_to_old_fields'),

	path(r'result/<int:result_id>/', views_result.result_details, name='result_details'),
	path(r'result/<int:result_id>/update/', views_result.result_update, name='result_update'),
	path(r'result/<int:result_id>/delete/', views_result.result_delete, name='result_delete'),
	path(r'result/<int:result_id>/update_splits/', views_result.result_splits_update, name='result_splits_update'),
	path(r'result/<int:result_id>/klb_add/', views_result.result_add_to_klb, name='result_klb_add'),
	path(r'result/<int:result_id>/klb_delete/', views_result.result_delete_from_klb, name='result_klb_delete'),
	path(r'result/<int:result_id>/mark_as_error/', views_result.result_mark_as_error, name='result_mark_as_error'),
	path(r'result/<int:result_id>/connect_to_runner/<int:runner_id>/', views_result.result_connect_to_runner, name='result_connect_to_runner'),

	path(r'runner/<int:runner_id>/', views_runner.runner_details, name='runner_details'),
	path(r'runner/<int:runner_id>/update/', views_runner.runner_update, name='runner_update'),
	path(r'runner/<int:runner_id>/delete/', views_runner.runner_delete, name='runner_delete'),
	path(r'runner/<int:runner_id>/history/', views_runner.runner_changes_history, name='runner_changes_history'),
	path(r'runner/<int:runner_id>/update_stat/', views_runner.runner_update_stat, name='runner_update_stat'),
	path(r'runner/create/', views_runner.runner_create, name='runner_create'),
	path(r'runner/create/<str:lname>/<str:fname>/', views_runner.runner_create, name='runner_create'),
	path(r'runner/<int:runner_id>/unclaim_unclaimed_by_user/', views_runner.unclaim_unclaimed_by_user, name='unclaim_unclaimed_by_user'),

	path(r'news/create/', views_news.news_create, name='news_create'),
	path(r'news/create/country/<country:country_id>/', views_news.news_create, name='news_create'),
	path(r'news/create/region/<int:region_id>/', views_news.news_create, name='news_create'),
	path(r'news/create/city/<int:city_id>/', views_news.news_create, name='news_create'),

	path(r'news/<int:news_id>/update/', views_news.news_update, name='news_update'),
	path(r'news/<int:news_id>/delete/', views_news.news_delete, name='news_delete'),
	path(r'news/<int:news_id>/history/', views_news.news_changes_history, name='news_changes_history'),
	path(r'news/<int:news_id>/', views_news.news_details, name='news_details'),
	path(r'news/<int:news_id>/post/', views_news.news_post, name='news_post'),
	
	path(r'users/', views_user.users, name='users'),
	path(r'user/<int:user_id>/history/', views_user.user_changes_history, name='user_changes_history'),
	path(r'user/<int:user_id>/update_stat/', views_user.user_update_stat, name='user_update_stat'),
	path(r'user/<int:user_id>/add_series_editor/', views_user.add_series_editor, name='user_add_series_editor'),
	path(r'user/<int:user_id>/remove_series_editor/', views_user.remove_series_editor, name='user_remove_series_editor'),
	path(r'user/<int:user_id>/merge/', views_user.merge_users, name='user_merge'),

	path(r'memo_admin/', views_site.memo_admin, name='memo_admin'),
	path(r'memo_editor/', views_site.memo_editor, name='memo_editor'),
	path(r'memo_python/', views_site.memo_python, name='memo_python'),
	path(r'memo_salary/', views_site.memo_salary, name='memo_salary'),
	path(r'memo_server/', views_site.memo_server, name='memo_server'),
	path(r'memo_spelling/', views_site.memo_spelling, name='memo_spelling'),
	path(r'memo_templates/', views_site.memo_templates, name='memo_templates'),
	path(r'db_structure/', views_db_structure.db_structure, name='db_structure'),
	path(r'db_structure/<model_name:model_name>/', views_db_structure.db_structure, name='db_structure'),

	path(r'search_by_id/', views_site.search_by_id, name='search_by_id'),
	path(r'search_by_id/id/<int:id>/', views_site.search_by_id, name='search_by_id'),

	path(r'action_history/', views_user.action_history, name='action_history'),
	path(r'action/<int:table_update_id>/', views_user.action_details, name='action_details'),

	path(r'event/<int:event_id>/protocol/', views_protocol.protocol_details, name='protocol_details'),
	path(r'event/<int:event_id>/protocol/<int:protocol_id>/', views_protocol.protocol_details, name='protocol_details'),
	path(r'event/<int:event_id>/protocol/<int:protocol_id>/sheet/<int:sheet_id>/', views_protocol.protocol_details,
		name='protocol_details'),
	path(r'event/<int:event_id>/protocol/sheet/<int:sheet_id>/', views_protocol.protocol_details, name='protocol_details'),
	path(r'race/<int:race_id>/protocol/<int:protocol_id>/', views_protocol.protocol_details, name='protocol_details'),
	path(r'protocol/<int:protocol_id>/mark_processed/', views_protocol.protocol_mark_processed, name='protocol_mark_processed'),
	path(r'loaded_protocols_by_month/', views_series.loaded_protocols_by_month, name='loaded_protocols_by_month'),

	path(r'events_for_result_import/', views_protocol.events_for_result_import, name='events_for_result_import'),

	path(r'social_pages/', views_social.social_pages, name='social_pages'),
	path(r'social_page/<int:page_id>/history/', views_social.social_page_history, name='social_page_history'),

	path(r'klb_status/', views_klb.klb_status, name='klb_status'),
	path(r'klb_status/year/<year:year>/', views_klb.klb_status, name='klb_status'),
	path(r'klb_status/connect_klb_results/', views_klb.connect_klb_results, name='connect_klb_results'),
	path(r'klb_status/connect_unoff_results/', views_klb.connect_unoff_results, name='connect_unoff_results'),

	path(r'klb/race/<int:race_id>/', views_klb_race.klb_race_details, name='klb_race_details'),
	path(r'klb/race/<int:race_id>/page/<int:page>/', views_klb_race.klb_race_details, name='klb_race_details'),
	path(r'klb/race/<int:race_id>/process/', views_klb_race.klb_race_process, name='klb_race_process'),
	path(r'klb/race/<int:race_id>/add_results/', views_klb_race.klb_race_add_results, name='klb_race_add_results'),

	path(r'klb/person/<int:person_id>/', views_klb_person.klb_person_details, name='klb_person_details'),
	path(r'klb/person/<int:person_id>/participant_update/year/<year:year>/', views_klb_person.klb_person_participant_update,
		name='klb_person_participant_update'),
	path(r'klb/person/<int:person_id>/refresh/', views_klb_person.klb_person_refresh_stat, name='klb_person_refresh_stat'),
	path(r'klb/person/create/runner/<int:runner_id>/', views_klb_person.klb_person_create, name='klb_person_create'),
	path(r'klb/person/<int:person_id>/update/', views_klb_person.klb_person_update, name='klb_person_update'),
	path(r'klb/person/<int:person_id>/delete/', views_klb_person.klb_person_delete, name='klb_person_delete'),
	path(r'klb/person/<int:person_id>/history/', views_klb_person.klb_person_changes_history, name='klb_person_changes_history'),

	path(r'klb/team/<int:team_id>/history/', views_klb_team.klb_team_changes_history, name='klb_team_changes_history'),
	path(r'klb/team/<int:team_id>/delete/', views_klb_team.klb_team_delete, name='klb_team_delete'),
	path(r'klb/team/<int:team_id>/change_name/', views_klb_team.klb_team_change_name, name='klb_team_change_name'),
	path(r'klb/team/<int:team_id>/details/', views_klb_team.klb_team_contact_info, name='klb_team_contact_info'),
	path(r'klb/team/<int:team_id>/details/order/<int:ordering>/', views_klb_team.klb_team_contact_info, name='klb_team_contact_info'),
	path(r'klb/team/<int:team_id>/add_old_participants/',
		views_klb_team.klb_team_add_old_participants, name='klb_team_add_old_participants'),
	path(r'klb/team/<int:team_id>/add_new_participant/',
		views_klb_team.klb_team_add_new_participant, name='klb_team_add_new_participant'),
	path(r'klb/team/<int:team_id>/delete_participants/',
		views_klb_team.klb_team_delete_participants, name='klb_team_delete_participants'),
	path(r'klb/team/<int:team_id>/move_participants/',
		views_klb_team.klb_team_move_participants, name='klb_team_move_participants'),

	path(r'klb/team/<int:team_id>/did_not_run/', views_klb_team.did_not_run, name='klb_team_did_not_run'),
	path(r'klb/team/<int:team_id>/did_not_run/with_marked/<int:with_marked>/', views_klb_team.did_not_run, name='klb_team_did_not_run'),

	path(r'klb/participant/<int:participant_id>/contact_info/', views_klb_person.klb_participant_for_captain_details,
		name='klb_participant_for_captain_details'),

	path(r'klb/update_match/<year:year>/', views_klb.klb_update_match, name='klb_update_match'),

	path(r'klb/make_report/<year:year>/type/<str:role>/', views_klb_report.make_report, name='klb_make_report'),

	path(r'klb/team_leaders_emails/', views_klb.klb_team_leaders_emails, name='klb_team_leaders_emails'),
	path(r'klb/team_leaders_emails/year/<year:year>/', views_klb.klb_team_leaders_emails, name='klb_team_leaders_emails'),
	path(r'klb/did_not_pay/', views_klb.klb_who_did_not_pay, name='klb_who_did_not_pay'),
	path(r'klb/did_not_pay/year/<year:year>/', views_klb.klb_who_did_not_pay, name='klb_who_did_not_pay'),
	path(r'klb/repeating_contact_data/', views_klb.klb_repeating_contact_data, name='klb_repeating_contact_data'),
	path(r'klb/repeating_contact_data/year/<year:year>/', views_klb.klb_repeating_contact_data, name='klb_repeating_contact_data'),

	path(r'letter/<int:user_id>/', views_user.user_mail, name='user_mail'),
	path(r'letter_txt/<int:user_id>/', views_user.user_mail_txt, name='user_mail_txt'),
	path(r'newsletter/<int:user_id>/<str:filename>/', views_mail.show_newsletter, name='show_newsletter'),
	path(r'newsletter_txt/<int:user_id>/<str:filename>/', views_mail.show_newsletter_txt, name='show_newsletter_txt'),
	path(r'emails_for_newsletter/', views_mail.emails_for_newsletter, name='emails_for_newsletter'),

	path(r'message/<int:message_id>/', views_mail.message_details, name='message_details'),

	path(r'club/create/', views_club.club_create, name='club_create'),
	path(r'club/<int:club_id>/', views_club.club_details, name='club_details'),
	path(r'club/<int:club_id>/delete/', views_club.club_delete, name='club_delete'),
	path(r'club/<int:club_id>/history/', views_club.club_changes_history, name='club_changes_history'),
	path(r'club/<int:club_id>/update_records/', views_club.update_records, name='club_update_records'),
	path(r'club/<int:club_id>/add_klb_team/<int:year>/', views_club.add_team, name='add_klb_team'),
	path(r'club/<int:club_id>/add_cur_year_team/', views_club.add_cur_year_team, name='add_cur_year_team'),
	path(r'club/<int:club_id>/add_next_year_team/', views_club.add_next_year_team, name='add_next_year_team'),
	path(r'club/<int:club_id>/name/<int:club_name_id>/delete/', views_club.club_name_delete, name='club_name_delete'),

	path(r'club/<int:club_id>/add_new_member/', views_club.add_club_member, name='club_add_new_member'),
	path(r'club/<int:club_id>/add_runner/<int:runner_id>/', views_club.add_runner, name='club_add_runner'),
	path(r'club/<int:club_id>/member/<int:member_id>/edit/', views_club.member_details, name='club_member_details'),
	path(r'club/<int:club_id>/member/<int:member_id>/edit/return/<str:return_page>/', views_club.member_details,
		name='club_member_details'),
	path(r'club/<int:club_id>/member/<int:member_id>/delete/', views_club.delete_member, name='club_delete_member'),

	path(r'runner_names/', views_name.runner_names, name='runner_names'),
	path(r'runner_name/<int:runner_name_id>/delete/', views_name.runner_name_delete, name='runner_name_delete'),
	path(r'popular_names_in_free_results/', views_name.popular_names_in_free_results, name='popular_names_in_free_results'),
	path(r'runners_with_old_last_find_results_try/', views_runner.runners_with_old_last_find_results_try,
		name='runners_with_old_last_find_results_try'),

	path(r'runner/<int:runner_id>/add_name/', views_runner.runner_name_add, name='runner_name_add'),
	path(r'runner/<int:runner_id>/delete_name/<int:name_id>/', views_runner.runner_name_delete, name='runner_name_delete'),

	path(r'runner/<int:runner_id>/add_link/', views_runner.runner_link_add, name='runner_link_add'),
	path(r'runner/<int:runner_id>/delete_link/<int:link_id>/', views_runner.runner_link_delete, name='runner_link_delete'),

	path(r'runner/<int:runner_id>/add_platform/', views_runner.runner_platform_add, name='runner_platform_add'),
	path(r'runner/<int:runner_id>/delete_platform/<int:runner_platform_id>/', views_runner.runner_platform_delete, name='runner_platform_delete'),
	path(r'series/<int:series_id>/add_platform/', views_series.series_platform_add, name='series_platform_add'),
	path(r'series/<int:series_id>/delete_platform/<int:series_platform_id>/', views_series.series_platform_delete, name='series_platform_delete'),

	path(r'admin_work_stat/', views_site.admin_work_stat, name='admin_work_stat'),

	path(r'organizer/<int:organizer_id>/', views_organizer.organizer_details, name='organizer_details'),
	path(r'organizer/<int:organizer_id>/history/', views_organizer.organizer_changes_history, name='organizer_changes_history'),
	path(r'organizer/<int:organizer_id>/add_series/', views_organizer.add_series, name='organizer_add_series'),
	path(r'organizer/<int:organizer_id>/remove_series/<int:series_id>/', views_organizer.remove_series, name='organizer_remove_series'),
	path(r'organizer/create/', views_organizer.organizer_details, name='organizer_create'),

	path(r'util/', views_util.util, name='util'),
	path(r'replace_in_event_names/', views_util.replace_in_event_names, name='replace_in_event_names'),
	path(r'scrape_athlinks_protocol/', views_util.scrape_athlinks_protocol, name='scrape_athlinks_protocol'),
	path(r'not_count_results_present_in_both_races_for_stat/', views_race.not_count_results_present_in_both_races_for_stat,
		name='not_count_results_present_in_both_races_for_stat'),

	path(r'age_group_records/', views_age_group_record.age_group_records_edit, name='age_group_records_edit'),
	path(r'age_group_records/<country_of_3:country_id>/<gender:gender_code>/<str:distance_code>/<str:surface_code>/',
		views_age_group_record.age_group_records_edit, name='age_group_records_edit'),
	path(r'age_group_records/<country_of_3:country_id>/<gender:gender_code>/absolute/',
		views_age_group_record.age_group_records_edit, name='country_records_edit'),

	path(r'age_group_record/add/', views_age_group_record.age_group_record_details, name='age_group_record_add'),
	path(r'age_group_record/add/<country_of_3:country_id>/<gender:gender_code>/<int:age>/<str:distance_code>/<str:surface_code>/',
		views_age_group_record.age_group_record_details, name='age_group_record_add'),
	path(r'age_group_record/<int:record_result_id>/', views_age_group_record.age_group_record_details, name='age_group_record_details'),
	path(r'age_group_record/<int:record_result_id>/delete/', views_age_group_record.age_group_record_delete, name='age_group_record_delete'),
	path(r'age_group_record/<int:record_result_id>/add_to_cur_session/', views_age_group_record.add_to_cur_session, name='age_group_add_to_cur_session'),
	path(r'age_group_record/<int:bad_record_id>/mark_good/', views_age_group_record.record_mark_good, name='record_mark_good'),

	path(r'better_age_group_results/<country_of_3:country_id>/indoor/<int:is_indoor>/', views_age_group_record.better_age_group_results,
		name='better_age_group_results'),
	path(r'better_age_group_results/<country_of_3:country_id>/', views_age_group_record.better_age_group_results,
		name='better_age_group_results'),

	path(r'add_possible_age_group_records/', views_age_group_record.add_possible_age_group_records, name='add_possible_age_group_records'),
	path(r'update_age_group_records'
		+ '/<country_of_3:country_id>/<gender:gender_code>/<int:age>/<str:distance_code>/<str:surface_code>/',
		views_age_group_record.update_age_group_records, name='update_age_group_records'),
	path(r'generate_better_age_group_results'
		+ '/<country_of_3:country_id>/<gender:gender_code>/<int:age>/<str:distance_code>/<str:surface_code>/',
		views_age_group_record.generate_better_age_group_results_for_tuple, name='generate_better_age_group_results_for_tuple'),
	path(r'delete_other_saved_results'
		+ '/<country_of_3:country_id>/<gender:gender_code>/<int:age>/<str:distance_code>/<str:surface_code>/',
		views_age_group_record.delete_other_saved_results, name='delete_other_saved_results'),
	path(r'add_comment'
		+ '/<country_of_3:country_id>/<gender:gender_code>/<int:age>/<str:distance_code>/<str:surface_code>/',
		views_age_group_record.add_comment, name='age_group_add_comment'),
	path(r'age_group_records/mark_cur_session_complete/', views_age_group_record.mark_cur_session_complete, name='mark_cur_session_complete'),

	path(r'links/add_label/', views_useful_link.add_label, name='add_useful_link_label'),
	path(r'links/add_link/', views_useful_link.add_link, name='add_useful_link'),
	path(r'link/<int:link_id>/', views_useful_link.link_details, name='useful_link_details'),
	path(r'link/<int:link_id>/history/', views_useful_link.link_changes_history, name='useful_link_changes_history'),

	path(r'reg_click/<int:ad_id>/', views_ad.reg_click, name='ad_reg_click'),
	path(r'daily_clicks/', views_ad.daily_clicks, name='ad_daily_clicks'),

	path(r'apply_course_certificates/', views_course.view_apply_certificates, name='apply_certificates'),

	path(r'protocol_queue/', views_protocol_queue.queue, name='protocol_queue'),
	path(r'add_protocol_to_queue/', views_protocol_queue.add_to_queue, name='add_protocol_to_queue'),
	path(r'add_protocol_to_queue/<int:protocol_id>/', views_protocol_queue.add_to_queue, name='add_protocol_to_queue'),
	path(r'add_series_to_queue/', views_protocol_queue.add_series_to_queue, name='add_series_to_queue'),
	path(r'mark_item_not_failed/<int:row_id>/', views_protocol_queue.mark_item_not_failed, name='mark_item_not_failed'),
	path(r'mark_item_stopped/<int:row_id>/', views_protocol_queue.mark_item_stopped, name='mark_item_stopped'),
]
