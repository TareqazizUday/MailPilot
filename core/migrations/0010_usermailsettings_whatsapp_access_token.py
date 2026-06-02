from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0009_usermailsettings_telegram_bot_token"),
    ]

    operations = [
        migrations.AddField(
            model_name="usermailsettings",
            name="whatsapp_access_token_enc",
            field=models.TextField(blank=True, default=""),
        ),
    ]
