from ..constants import CURRENT_METHOD, TIMEDELTA_TO_RATE_A_RACE, TIMEDELTA_FOR_USER_TO_RATE
from ..models import Parameter, User_overall, User_review, Group
from tools.dj_other import queryset_to_dict
from starrating.aggr.aggr_utils import get_sumfield_name, get_dependent_model

from django.db.models import OuterRef, Subquery, Case, When, Value, BooleanField
import datetime


def get_overall_object(rated, method_id):
	if not hasattr(rated, 'sr_overall'):
		return None
	overall_list = rated.sr_overall.filter(method_id=method_id)
	assert len(overall_list) <= 1
	if len(overall_list) == 0:
		return None
	else:
		return overall_list[0]


def get_sr_overall_data(rated, to_show_rating, method_id=CURRENT_METHOD):
	'Here rated may be an instance of one of models: Race, Event, Serier, Organizer'

	if not to_show_rating:
		return None

	overall_obj = get_overall_object(rated, method_id)
	if overall_obj is None:
		return None
	else:
		if overall_obj.weight == 0:
			return None
		sum_val = getattr(overall_obj, get_sumfield_name(overall_obj))
		weight = overall_obj.weight
		avg = float(sum_val) / weight
		user_count = overall_obj.user_count
	return {
			'sum_val': sum_val,
			'weight': weight,
			'avg': avg,
			'user_count' : user_count,
			'id' : rated.id,
			'level': type(rated).__name__.lower(),
		}


def get_sr_by_param_data(
		rated,
		to_show_rating,
		show_parameters_without_rating=True,
		method_id=CURRENT_METHOD
):
	if rated is None:
		from results.models import Event
		rated = Event.objects.get(pk=20831)

	if not to_show_rating:
		return None

	par_list = list(Parameter.objects.filter(to_show=True).order_by('order').values())

	# Accessing and preprocerssing by_param data
	overall_obj = get_overall_object(rated, method_id)
	if overall_obj is None:
		return None
	by_param_dict = queryset_to_dict(
		overall_obj.by_param.filter(parameter__to_show=True),
		'parameter_id'
	)
	sumfield_name = get_sumfield_name(
		get_dependent_model(type(overall_obj)),
		overall_obj.method_id
	)

	for par in par_list:
		try:
			data_for_this_par = by_param_dict[par['id']]
		except KeyError:
			pass
		else:
			par['weight'] = weight = data_for_this_par.weight
			par['sum_val'] = sum_val = getattr(data_for_this_par, sumfield_name)
			if data_for_this_par.user_count != 0:  # Check for not to show zero data to non-admins
				par['user_count'] = data_for_this_par.user_count
				try:
					par['avg'] = float(sum_val) / weight
				except ZeroDivisionError:
					par['avg'] = 0

	if not show_parameters_without_rating:
		par_list = [par for par in par_list if 'user_count' in par]

	return par_list


def annotate_user_results_with_sr_data(results, to_show_rating):
	if not to_show_rating:
		return results

	# Adding info on how the user have rated the race and
	today = datetime.date.today()
	date_limit_for_race = today - TIMEDELTA_TO_RATE_A_RACE
	date_limit_for_user = today - TIMEDELTA_FOR_USER_TO_RATE
	annotated_results = results.annotate(
		sum_value=Subquery(User_overall.objects.filter(
					rated__user_id=OuterRef('user_id'),
					rated__race_id=OuterRef('race_id'),
					method_id=CURRENT_METHOD
				).values_list('sum_int')
			),
		weight=Subquery(User_overall.objects.filter(
					rated__user_id=OuterRef('user_id'),
					rated__race_id=OuterRef('race_id'),
					method_id=CURRENT_METHOD
				).values_list('weight')
			),
		is_race_new=Case(
				When(
						race__event__start_date__gte=date_limit_for_race,
						then=Value(True)
					),
				default=Value(False),
				output_field=BooleanField()
			),
		is_user_new=Case(
				When(
						user__date_joined__gte=date_limit_for_user,
						then=Value(True)
					),
				default=Value(False),
				output_field=BooleanField()
			),
		sr_group_is_empty=Subquery(Group.objects.filter(
					user_id=OuterRef('user_id'),
					race_id=OuterRef('race_id'),
				).values_list('is_empty')
			),
		sr_user_review_id=Subquery(User_review.objects.filter(
					group__user_id=OuterRef('user_id'),
					group__race_id=OuterRef('race_id'),
				).values_list('pk')
			),
		)
	return annotated_results
