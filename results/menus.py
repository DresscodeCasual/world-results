from django.conf import settings
from django.urls import reverse

from menu import Menu, MenuItem

def is_admin(request):
	return request.user.groups.filter(name='admins').exists()

def is_not_admin(request):
	return not request.user.groups.filter(name='admins').exists()

def is_only_editor(request):
	return request.user.groups.filter(name='editors').exists() and not request.user.groups.filter(name='admins').exists()

def is_authenticated(request):
	return request.user.is_authenticated

def is_not_authenticated(request):
	return not request.user.is_authenticated

Menu.add_item('user', MenuItem('Register / Login', reverse('auth:login'), check=is_not_authenticated))

Menu.add_item('main', MenuItem('News', settings.MAIN_PAGE))
Menu.add_item('main', MenuItem('My results', reverse('results:home'), check=is_authenticated))

# calendar_children = (
# 	MenuItem('общий', reverse('results:races')),
# 	MenuItem('в Москве и области', reverse('results:races', kwargs={'region_group': '46,47', 'date_region': 2})),
# 	MenuItem('в Петербурге и области', reverse('results:races', kwargs={'region_group': '64,41', 'date_region': 2})),
# 	MenuItem('триатлонов', reverse('results:events_triathlon')),
# 	MenuItem('для ветеранов', reverse('results:events_for_masters')),
# 	MenuItem('кроссов, трейлов, горного бега', reverse('results:future_trails')),
# 	MenuItem('паркранов и похожих забегов', reverse('results:parkruns_and_similar')),
# )

# Menu.add_item('main', MenuItem('Календари забегов', '#', children=calendar_children))
Menu.add_item('main', MenuItem('Runners Database', reverse('results:runners')))

admin_children = (
	MenuItem('Памятка администратору', reverse('editor:memo_admin')),
	MenuItem('Памятка редактору', reverse('editor:memo_editor')),
	MenuItem('Шаблоны для писем', reverse('editor:memo_templates')),
	MenuItem('Рекомендации по текстам', reverse('editor:memo_spelling')),
	MenuItem('Города', reverse('editor:cities'), separator=True),
	MenuItem('Добавить город', reverse('editor:city_create')),
	MenuItem('Страны и регионы', reverse('editor:regions')),
	MenuItem('Дистанции', reverse('editor:distances')),
	MenuItem('Добавить дистанцию', reverse('editor:distance_create')),
	MenuItem('Серии пробегов', reverse('editor:seria')),
	MenuItem('Добавить серию', reverse('editor:series_create')),
	MenuItem('Добавить новость', reverse('editor:news_create')),
	MenuItem('Действия для одобрения', reverse('editor:action_history'), separator=True),
	MenuItem('Неофициальные результаты', reverse('editor:klb_status')),
	MenuItem('Кто сколько чего сделал', reverse('editor:admin_work_stat')),
	MenuItem('Пользователи сайта', reverse('editor:users'), separator=True),
	# MenuItem('Страницы в соцсетях', reverse('editor:social_pages')),
	MenuItem('Имена бегунов', reverse('editor:runner_names')),
	MenuItem('Популярные имена в результатах', reverse('editor:popular_names_in_free_results')),
	MenuItem('Бегуны, результаты которых давно не искали', reverse('editor:runners_with_old_last_find_results_try')),
	MenuItem('Разные мелкие штуки', reverse('editor:util')),
	MenuItem('Администрирование Django', reverse('admin:index'), separator=True),
	MenuItem('Отправить письмо', '#', attr={'class': 'send_from_info_page'}),
)
Menu.add_item('user', MenuItem('Администратору',
							'#',
							# separator=True,
							check=is_admin,
							children=admin_children))

editor_children = (
	MenuItem('Memo', reverse('editor:memo_editor')),
	MenuItem('Recommendations on editing texts', reverse('editor:memo_spelling')),
	MenuItem('Cities', reverse('editor:cities'), separator=True),
	MenuItem('Add a city', reverse('editor:city_create')),
	MenuItem('Regions', reverse('editor:regions')),
	MenuItem('Distances', reverse('editor:distances')),
	MenuItem('Add a distance', reverse('editor:distance_create')),
)
Menu.add_item('user', MenuItem('For Editor',
							'#',
							# separator=True,
							check=is_only_editor,
							children=editor_children))

user_children = (
	MenuItem('My results', reverse('results:home')),
	MenuItem('Find my unattached results', reverse('results:find_results')),
	MenuItem('Fill Strava links to my results', reverse('results:my_strava_links')),
	MenuItem('Profile',  reverse('results:my_details'), separator=True),
	MenuItem('Change password', reverse('auth:password_change')),
	MenuItem('Log out',          reverse('auth:logout'), separator=True),
)

Menu.add_item('user', MenuItem(lambda request: request.user.get_full_name(),
							'#',
							check=is_authenticated,
							children=user_children))

other_children = (
	MenuItem('Add a new series to the calendar', reverse('results:add_new_event')),
	# MenuItem('Организаторы', reverse('results:organizers'), check=is_admin),
	# MenuItem('Клубы любителей бега', reverse('results:clubs'), separator=True),
	# MenuItem('Новые возможности для клубов', reverse('results:about_club_membership')),
	# MenuItem('Рейтинг забегов', reverse('results:rating'), separator=True),
	# MenuItem('Все результаты', reverse('results:results'), check=is_admin),
	# MenuItem('Все новости', reverse('results:all_news')),
	# MenuItem('Рекорды России в возрастных группах', reverse('results:age_group_records'), separator=True),
	# MenuItem('Рекорды Беларуси в возрастных группах', reverse('results:age_group_records', kwargs={'country_id': 'BY'}), check=is_admin),
	# MenuItem('Пробежавшие в максимуме регионов', reverse('results:best_by_regions_visited', kwargs={'country_id': 'RU'})),
	# MenuItem('Статистика по паркранам России', reverse('results:parkrun_stat')),
	# MenuItem('Архив документов', reverse('results:archive')),
	# MenuItem('Полезные ссылки', reverse('results:useful_links')),
	# MenuItem('Отчёты: Бег в России — 2019', reverse('results:russia_report', kwargs={'year': '2019'}), separator=True),
	# MenuItem('Бег в России — 2018', reverse('results:russia_report', kwargs={'year': '2018'})),
	# MenuItem('Бег в России — 2017', reverse('results:russia_report', kwargs={'year': '2017'})),
	# MenuItem('Бег в России — 2016', reverse('results:russia_report', kwargs={'year': '2016'})),
	# MenuItem('Бег в Беларуси — 2019', reverse('results:belarus_report', kwargs={'year': '2019'})),
	# MenuItem('Бег в Беларуси — 2018', reverse('results:belarus_report', kwargs={'year': '2018'})),
	# MenuItem('Сертификация трасс', reverse('results:measurement_about'), separator=True),
	# MenuItem('Разрядные нормативы в беге', reverse('sport_classes'), separator=True),
	# MenuItem('Стандарт протокола', reverse('protocol')),
	MenuItem('About Us', reverse('about'), separator=True),
	# MenuItem('Помогите нам с поиском протоколов', reverse('how_to_help')),
	MenuItem('Contact Us', '#', attr={'id': 'send_to_info_page'}),
	# MenuItem('Мы в соцсетях', reverse('social_links')),
)

Menu.add_item('main', MenuItem('More', '#', children=other_children))
