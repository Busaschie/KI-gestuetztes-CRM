from django.db import migrations, models


class Migration(migrations.Migration):
    # nach der Telegram-Migration aus dem parallelen Chat einsortiert (vorher Konflikt zweier 0004)
    dependencies = [("communications", "0004_inbound_channel_telegram")]

    operations = [
        migrations.AlterField("inbounditem", "error", models.TextField("Ergebnis / Fehler", blank=True)),
    ]
