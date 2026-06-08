from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0008_mailaccount_multi_mailbox"),
    ]

    operations = [
        migrations.AddField(
            model_name="usermailsettings",
            name="telegram_bot_token_enc",
            field=models.TextField(blank=True, default=""),
        ),
    ]
