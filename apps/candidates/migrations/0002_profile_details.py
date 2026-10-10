from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("candidates", "0001_initial")]

    operations = [
        migrations.RenameField("candidateprofile", "qualifications", "skills"),
        migrations.AlterField(
            "candidateprofile", "skills", models.JSONField("Kompetenzen", default=list, blank=True)
        ),
        migrations.AddField("candidateprofile", "education", models.JSONField("Aus- und Weiterbildung", default=list, blank=True)),
        migrations.AddField("candidateprofile", "certifications", models.JSONField("Zertifikate", default=list, blank=True)),
        migrations.AddField(
            "candidateprofile", "other_experience",
            models.JSONField("Sonstiges (z. B. Wehrdienst, Ehrenamt)", default=list, blank=True),
        ),
        migrations.AddField("candidateprofile", "strengths", models.JSONField("Persönliche Stärken", default=list, blank=True)),
        migrations.AddField("candidateprofile", "interests", models.JSONField("Interessen und Leistungen", default=list, blank=True)),
    ]
