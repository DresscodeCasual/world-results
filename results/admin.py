from django.contrib import admin

from . import models

admin.site.register(models.Country)
admin.site.register(models.District)
admin.site.register(models.Region)
admin.site.register(models.City)

admin.site.register(models.Event)
admin.site.register(models.Race)
admin.site.register(models.Distance)

admin.site.register(models.Result)

admin.site.register(models.User_profile)
admin.site.register(models.Platform)
admin.site.register(models.Record_category_comment)
admin.site.register(models.Series_name)

@admin.register(models.Series)
class SeriesAdmin(admin.ModelAdmin):
	ordering = ['name']
	search_fields = ['name', 'id']

@admin.register(models.Document)
class DocumentAdmin(admin.ModelAdmin):
	ordering = ['url_source']
	search_fields = ['url_source', 'upload', 'id']

@admin.register(models.Runner)
class RunnerAdmin(admin.ModelAdmin):
	search_fields = ['id', 'lname', 'fname', 'midname', ]

@admin.register(models.Course_certificate)
class Course_certificateAdmin(admin.ModelAdmin):
	autocomplete_fields = ['series', 'created_by']

@admin.register(models.Result_not_for_age_group_record)
class Result_not_for_age_group_recordAdmin(admin.ModelAdmin):
	exclude = ('created_by', 'distance', 'result', 'country', 'gender', 'age_group', 'is_indoor', )

@admin.register(models.Record_result)
class Record_resultAdmin(admin.ModelAdmin):
	autocomplete_fields = ['protocol']
	fields = ('comment', 'session', 'protocol', 'is_world_record', 'is_europe_record', )
