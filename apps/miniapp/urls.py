from django.urls import path

from . import views

app_name = "miniapp"
urlpatterns = [
    path("", views.shell, name="shell"),
    path("heute/", views.today, name="today"),
    path("wv/<int:pk>/<str:action>/", views.followup_action, name="followup_action"),
    path("stopp/<str:kind>/<int:pk>/", views.stop_action, name="stop_action"),
    path("vertraege/", views.contracts, name="contracts"),
    path("vertrag/<int:pk>/<str:action>/", views.contract_action, name="contract_action"),
    path("auftraege/", views.mandates, name="mandates"),
    path("auftrag/<int:pk>/", views.mandate_detail, name="mandate"),
    path("kandidat/<int:pk>/<str:action>/", views.submission_action, name="submission_action"),
]
