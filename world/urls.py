from django.urls import include, path
from django.contrib import admin
from django.views.generic import RedirectView, TemplateView
from results.views import views_site
from django.conf import settings

urlpatterns = [
    path(r'about/', views_site.about, name='about'),
    path(r'protocol/', views_site.protocol, name='protocol'),
    # path(r'social_links/', views_site.social_links, name='social_links'),
    path(r'results_binding/', views_site.results_binding, name='results_binding'),
    path(r'how_to_help/', views_site.how_to_help, name='how_to_help'),
    path(r'login_problems/', views_site.login_problems, name='login_problems'),
    path(r'facebook_policy/', views_site.facebook_policy, name='facebook_policy'),

    path(r'ads\.txt/', TemplateView.as_view(template_name='misc/ads.txt', content_type='text/plain')),
    # TODO path(r'favicon.png', RedirectView.as_view(url='https://probeg.org/dj_static/images/man-square2.png'), name='favicon'),

    path(r'', include('results.urls')),
    path(r'admin/', admin.site.urls),
    path(r'editor/', include('editor.urls', namespace='editor')),
    path(r'', include('social_django.urls', namespace='social')),
    path(r'', include('world_auth.urls', namespace='world_auth')),
    path(r'tinymce/', include('tinymce.urls')),
    path('select2/', include('django_select2.urls')),
    path(r'', include('starrating.urls', namespace='starrating')),
]

# if settings.DEBUG:
#     import debug_toolbar
#     urlpatterns = [
#         path(r'__debug__/', include(debug_toolbar.urls)),
#     ] + urlpatterns
