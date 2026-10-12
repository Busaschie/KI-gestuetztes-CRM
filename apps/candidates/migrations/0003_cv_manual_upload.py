import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("candidates", "0002_profile_details")]

    operations = [
        migrations.AlterField("cvdocument", "original_filename",
                              models.CharField("Originaler Dateiname", max_length=255, blank=True)),
        migrations.AlterField("cvdocument", "received_at",
                              models.DateTimeField("Eingegangen", default=django.utils.timezone.now)),
        migrations.AlterField(
            "cvdocument", "origin",
            models.CharField("Quelle", max_length=20, default="manual", choices=[
                ("linkedin", "LinkedIn"), ("personal", "Persönlich"), ("application", "Bewerbung"),
                ("referral", "Empfehlung"), ("email", "E-Mail"), ("placement", "Frühere Vermittlung"),
                ("job_board", "Jobbörse"), ("voice", "Sprachnachricht"), ("import", "Import (CV-Ordner/CRM)"),
                ("manual", "Manuell")]),
        ),
    ]
