"""django-q im Unfold-Design: die Admins von django-q neu registrieren (nur Darstellung)."""
from django.contrib import admin
from django_q import admin as q_admin
from django_q.models import Failure, OrmQ, Schedule, Success
from unfold.admin import ModelAdmin

for model, base in [(Schedule, q_admin.ScheduleAdmin), (Success, q_admin.TaskAdmin),
                    (Failure, q_admin.FailAdmin), (OrmQ, q_admin.QueueAdmin)]:
    if admin.site.is_registered(model):
        admin.site.unregister(model)
        admin.site.register(model, type(base.__name__, (base, ModelAdmin), {}))
