from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("candidates/", include("apps.candidates.urls")),
    path("clients/", include("apps.clients.urls")),
    path("jobs/", include("apps.jobs.urls")),
    path("pipeline/", include("apps.pipeline.urls")),
]
