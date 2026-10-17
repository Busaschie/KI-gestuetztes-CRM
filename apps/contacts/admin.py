from django.contrib import admin
from unfold.admin import ModelAdmin, TabularInline

from .models import Company, Employment, Person, PersonOrigin


class EmploymentInline(TabularInline):
    model = Employment
    extra = 0
    autocomplete_fields = ["company"]


class PersonOriginInline(TabularInline):
    model = PersonOrigin
    extra = 0


@admin.register(Person)
class PersonAdmin(ModelAdmin):
    list_display = ["__str__", "email", "city", "country", "last_contacted_at", "retain_until"]
    search_fields = ["first_name", "last_name", "email", "linkedin_url"]
    list_filter = ["country"]
    inlines = [EmploymentInline, PersonOriginInline]


@admin.register(Company)
class CompanyAdmin(ModelAdmin):
    list_display = ["name", "city", "country", "is_client", "has_contract_master_data"]
    list_filter = ["is_client", "country"]
    search_fields = ["name"]
    autocomplete_fields = ["signatory"]

    @admin.display(boolean=True, description="Vertragsdaten vollständig")
    def has_contract_master_data(self, obj):
        return obj.has_contract_master_data
