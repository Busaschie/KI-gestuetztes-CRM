import pytest
from django.contrib.auth import get_user_model

from apps.candidates.display import fmt_date, render_profile
from apps.candidates.models import CandidateProfile
from apps.contacts.models import Person


def make_profile(**data):
    person = Person.objects.create(first_name="Anna", last_name="Hötter")
    return CandidateProfile.objects.create(person=person, **data)


def test_fmt_date():
    assert fmt_date("2019-03") == "03/2019"
    assert fmt_date("2019") == "2019"
    assert fmt_date(None) == ""


@pytest.mark.django_db
def test_render_profile_readable_and_escaped():
    profile = make_profile(
        positions=[{"title": "Leiterin Vertrieb", "company": "Muster AG", "start": "2019-03", "end": None,
                    "is_current": True, "tasks": ["Führung von 8 Mitarbeitern"]}],
        education=[{"title": "M.Sc. Informatik", "institution": "TU Graz", "start": "2010", "end": "2012",
                    "kind": "studium"}],
        languages=[{"name": "Englisch", "level": "C1"}],
        skills=["Vertrieb", "<script>x</script>"],
    )
    html = render_profile(profile)
    assert "03/2019 – heute" in html
    assert "Muster AG" in html and "TU Graz" in html
    assert "Führung von 8 Mitarbeitern" in html
    assert "Englisch" in html and "C1" in html
    assert "<script>x</script>" not in html  # Inhalte aus dem CV werden escaped


@pytest.mark.django_db
def test_render_profile_tolerates_bad_data():
    profile = make_profile(positions=["nur Text"], education=[], languages=None or [])
    html = render_profile(profile)
    assert "nur Text" in html


@pytest.mark.django_db
def test_admin_change_page(client):
    user = get_user_model().objects.create_superuser("admin", "a@example.com", "pw")
    client.force_login(user)
    profile = make_profile(skills=["Python"])
    resp = client.get(f"/admin/candidates/candidateprofile/{profile.pk}/change/")
    assert resp.status_code == 200
    assert "Profil aus dem Lebenslauf" in resp.content.decode()
