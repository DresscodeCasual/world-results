from django.contrib import messages
from django.shortcuts import redirect

from results import models
from editor.views import views_common

def apply_certificate_to_races(certificate, debug=False) -> int:
	n_deleted = certificate.race_set.all().update(certificate=None)
	n_found = models.Race.objects.filter(event__series=certificate.series, event__start_date__gte=certificate.date_measured,
		event__start_date__lte=certificate.date_expires, distance=certificate.distance).update(certificate=certificate)
	if debug:
		print(f'Updated certificate {certificate}: deleted from {n_deleted} races, applied to {n_found} races')
	return n_found

def apply_certificates(debug=False) -> int:
	n_found = 0
	for certificate in models.Course_certificate.objects.exclude(date_measured=None).exclude(date_expires=None).order_by('id'):
		# if debug:
		# 	print(f'Working with {certificate}, {certificate.distance}')
		n_found += apply_certificate_to_races(certificate, debug=debug)
	return n_found

@views_common.group_required('admins')
def view_apply_certificates(request):
	n_found = apply_certificates()
	messages.success(request, f'Сертификаты успешно проставлены у {n_found} стартов.')
	return redirect('results:measurement_about')
