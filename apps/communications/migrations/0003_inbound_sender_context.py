from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("communications", "0002_inbound_attachment")]

    operations = [
        migrations.AddField("inbounditem", "sender", models.CharField("Absender", max_length=255, blank=True)),
        migrations.AddField(
            "inbounditem", "context",
            models.CharField("Kontext", max_length=255, blank=True, help_text="z. B. Betreff der E-Mail mit dem Anhang"),
        ),
        migrations.AlterField("inbounditem", "subject", models.CharField("Betreff / Dateiname", max_length=255, blank=True)),
    ]
