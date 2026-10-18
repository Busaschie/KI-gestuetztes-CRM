from django.contrib import admin
from django.db.models import Exists, OuterRef
from unfold.admin import ModelAdmin, TabularInline

from .models import Company, Employment, Person, PersonOrigin, client_contact_q


class EmploymentInline(TabularInline):
    model = Employment
    extra = 0
    autocomplete_fields = ["company"]


class PersonOriginInline(TabularInline):
    model = PersonOrigin
    extra = 0


class RoleFilter(admin.SimpleListFilter):
    title = "Rolle"
    parameter_name = "rolle"

    def lookups(self, request, model_admin):
        return [("kandidat", "Kandidat"), ("kunde", "Ansprechpartner Kunde"), ("sonstige", "Sonstige")]

    def queryset(self, request, queryset):
        if self.value() == "kandidat":
            return queryset.filter(candidate_profile__isnull=False)
        if self.value() == "kunde":
            return queryset.filter(pk__in=Person.objects.filter(client_contact_q()).values("pk"))
        if self.value() == "sonstige":
            return queryset.filter(candidate_profile__isnull=True).exclude(
                pk__in=Person.objects.filter(client_contact_q()).values("pk"))
        return queryset


@admin.register(Person)
class PersonAdmin(ModelAdmin):
    list_display = ["__str__", "role", "email", "city", "country", "last_contacted_at", "retain_until"]
    search_fields = ["first_name", "last_name", "email", "linkedin_url"]
    list_filter = [RoleFilter, "no_contact_care", "country"]
    inlines = [EmploymentInline, PersonOriginInline]

    def get_queryset(self, request):
        from apps.candidates.models import CandidateProfile

        client_ids = Person.objects.filter(client_contact_q()).values("pk")
        return super().get_queryset(request).annotate(
            _is_candidate=Exists(CandidateProfile.objects.filter(person=OuterRef("pk"))),
            _is_client_contact=Exists(Person.objects.filter(pk=OuterRef("pk"), pk__in=client_ids)),
        )

    @admin.display(description="Rolle")
    def role(self, obj):
        roles = [r for r, on in (("Kandidat", obj._is_candidate), ("Ansprechpartner Kunde", obj._is_client_contact)) if on]
        return ", ".join(roles) or "–"


@admin.register(Company)
class CompanyAdmin(ModelAdmin):
    list_display = ["name", "city", "country", "is_client", "has_contract_master_data"]
    list_filter = ["is_client", "country"]
    search_fields = ["name"]
    autocomplete_fields = ["signatory"]

    @admin.display(boolean=True, description="Vertragsdaten vollständig")
    def has_contract_master_data(self, obj):
        return obj.has_contract_master_data
