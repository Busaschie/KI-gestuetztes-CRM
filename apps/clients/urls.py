from django.urls import path

from . import views

app_name = "clients"
urlpatterns = [
    path("docuseal/webhook/", views.docuseal_webhook, name="docuseal_webhook"),
    path("contracts/<int:pk>/vorschau.pdf", views.contract_preview, name="contract_preview"),
]
