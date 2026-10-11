from django.contrib import admin
from django.urls import include, path

from apps.core.views import protected_media

urlpatterns = [
    path("admin/", admin.site.urls),
    path("candidates/", include("apps.candidates.urls")),
    path("clients/", include("apps.clients.urls")),
    path("jobs/", include("apps.jobs.urls")),
    path("pipeline/", include("apps.pipeline.urls")),
    path("media/<path:path>", protected_media, name="protected_media"),
]
