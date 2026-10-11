from django.urls import path

from . import views

app_name = "clients"
urlpatterns = [
    path("docuseal/webhook/", views.docuseal_webhook, name="docuseal_webhook"),
]
