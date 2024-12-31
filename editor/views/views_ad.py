from django.shortcuts import get_object_or_404, render
from django.http import HttpResponse
from django.utils import timezone
from django.conf import settings

from collections import OrderedDict
import datetime
import pytz

from results import models
from .views_common import group_required

def reg_click(request, ad_id):
	ad = get_object_or_404(models.Ad, pk=ad_id)
	models.Ad_click.objects.create(
		ad=ad,
		referer=request.META.get('HTTP_REFERER', '')[:100],
		ip=request.META.get('REMOTE_ADDR', ''),
		is_admin=request.user.is_authenticated,
	)
	# TODO: Remove
	update_daily_clicks(ad)
	return HttpResponse('')

def update_daily_clicks(cur_ad=None):
	ads = [cur_ad] if cur_ad else models.Ad.objects.order_by('pk')
	settings_time_zone = pytz.timezone(settings.TIME_ZONE)
	for ad in ads:
		ad_click_set = ad.ad_click_set.filter(is_admin=False)
		today = datetime.datetime.combine(timezone.now().today(), datetime.time.min).astimezone(settings_time_zone)
		yesterday = today - datetime.timedelta(days=1)

		n_clicks_today = ad_click_set.filter(click_time__gte=today).count()
		n_clicks_yesterday = ad_click_set.filter(click_time__gte=yesterday).count() - n_clicks_today

		ad_clicks_today, _ = models.Ad_clicks_by_day.objects.get_or_create(ad=ad, date=today)
		ad_clicks_today.value = n_clicks_today
		ad_clicks_today.save()

		ad_clicks_yesterday, _ = models.Ad_clicks_by_day.objects.get_or_create(ad=ad, date=yesterday)
		ad_clicks_yesterday.value = n_clicks_yesterday
		ad_clicks_yesterday.save()
		# for day in [today, yesterday]:
		# 	by_day, _ = models.Ad_clicks_by_day.objects.get_or_create(ad=ad, date=day)
		# 	by_day.value = ad_click_set.filter(click_time__date=day).count()
		# 	by_day.save()
		overall, _ = models.Ad_clicks_by_day.objects.get_or_create(ad=ad, date=None)
		overall.value = ad_click_set.count()
		overall.save()

@group_required('admins')
def daily_clicks(request):
	today = datetime.date.today()
	start_date = max(today - datetime.timedelta(days=50), datetime.date(2020, 12, 10))
	n_days = (today - start_date).days + 1
	data = OrderedDict({ad: {'days': [0] * n_days} for ad in models.Ad.objects.order_by('pk')})
	for ad_click_by_day in models.Ad_clicks_by_day.objects.filter(date__gte=start_date).select_related('ad'):
		data[ad_click_by_day.ad]['days'][(today - ad_click_by_day.date).days] = ad_click_by_day.value
	for ad_click_by_day in models.Ad_clicks_by_day.objects.filter(date=None).select_related('ad'):
		data[ad_click_by_day.ad]['total'] = ad_click_by_day.value

	context = {}
	context['page_title'] = 'Клики по рекламным объявлениям по дням'
	context['ad_data'] = data
	context['dates'] = []
	for i in range(n_days):
		context['dates'].append(today - datetime.timedelta(days=i))
	context['last_clicks'] = models.Ad_click.objects.select_related('ad').order_by('-click_time')[:20]

	return render(request, 'editor/ad/daily_clicks.html', context)
