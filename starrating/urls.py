from django.urls import path, register_converter

from . import views
from tools import url_param_converters 

app_name = 'starrating'

register_converter(url_param_converters.LevelConverter, 'level')

urlpatterns = [
	path(r'race/<int:race_id>/add_marks/', views.add_marks, name='add_marks'),
	path(r'race/<int:race_id>/add_marks/user/<int:user_id>/', views.add_marks, name='add_marks_for_user'),

	path(
		r'race/<int:race_id>/test_add_marks/user/<int:user_id>/',
		views.add_marks,
		dict(test_mode=True),
		name='test_add_marks_for_user',
	),

	path(
		r'race/<int:race_id>/add_marks2/user/<int:user_id>/',
		views.add_marks,
		dict(to_move_to_next_race=True),
		name='add_marks2_for_user',
	),

	path(
		r'race/<int:race_id>/abstain/user/<int:user_id>/',
		views.abstain, name='abstain',
	),
	path(
		r'user/<int:user_id>/postpone_rating/',
		views.postpone_adding_marks, name='postpone_adding_marks',
	),
	path(
		r'user/<int:user_id>/bulk_stop/',
		views.stop_adding_marks, name='stop_adding_marks',
	),

	path(r'race/<int:race_id>/my_marks/', views.my_marks, name='my_marks'),

	path(r'race/<int:race_id>/rating/user/<int:user_id>/', views.my_marks, name='my_marks_for_user'),
	path(r'editor/all_marks/', views.editor_rating_details, name='editor_rating_details'),
	path(r'editor/<level:level>/<int:id_>/rating/', views.editor_rating_details, name='editor_rating_details'),
	path(r'starrating/save_marks/', views.save_marks, name='save_marks'),
	path(r'starrating/parameters/', views.parameters, name='parameters'),
	path(r'starrating/methods/', views.methods, name='methods'),
	path(r'<level:level>/<int:id_>/rating/', views.rating_details, name='rating_details'),

	path(r'group/<int:group_id>/delete/', views.group_delete, name='group_delete'),
]
