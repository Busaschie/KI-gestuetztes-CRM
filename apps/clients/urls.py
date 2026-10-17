from django.urls import path

from . import views

app_name = "clients"
urlpatterns = [
    path("documenso/webhook/", views.documenso_webhook, name="documenso_webhook"),
    path("contracts/<int:pk>/vorschau.pdf", views.contract_preview, name="contract_preview"),
]
