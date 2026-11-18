from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0054_social_app_handoff"),
    ]

    operations = [
        migrations.AlterField(
            model_name="usermailsettings",
            name="active_transport_mode",
            field=models.CharField(default="gmail", max_length=16),
        ),
    ]
