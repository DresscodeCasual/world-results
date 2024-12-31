# -*- coding: utf-8 -*-


from django.contrib import admin

# Register your models here.

from . import models

admin.site.register(models.Parameter)
admin.site.register(models.Method)

admin.site.register(models.Primary)
admin.site.register(models.Group)

admin.site.register(models.Series_overall)
