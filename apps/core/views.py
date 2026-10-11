from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.views.static import serve


@staff_member_required
def protected_media(request, path):
    """Hochgeladene Dateien (CVs, Verträge) nur für angemeldete Mitarbeiter – nie öffentlich.
    Für den Betrieb später über den Webserver (X-Accel-Redirect) beschleunigen."""
    return serve(request, path, document_root=settings.MEDIA_ROOT)
