from django.shortcuts import render

def parkrun_stat(request):
	context = {}
	context['page_title'] = 'Статистика по паркранам России'
	context['authenticated'] = request.user.is_authenticated
	return render(request, 'results/parkrun_stat.html', context)
