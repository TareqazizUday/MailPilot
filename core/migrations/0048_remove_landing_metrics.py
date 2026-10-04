# Generated manually for removing landing metrics strip

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0047_rename_landing_grounding_verbose"),
    ]

    operations = [
        migrations.RemoveField(model_name="marketinglandingpage", name="metrics_kicker"),
        migrations.RemoveField(model_name="marketinglandingpage", name="metrics_title"),
        migrations.RemoveField(model_name="marketinglandingpage", name="metrics_sub"),
        migrations.RemoveField(model_name="marketinglandingpage", name="stat1_value"),
        migrations.RemoveField(model_name="marketinglandingpage", name="stat1_prefix"),
        migrations.RemoveField(model_name="marketinglandingpage", name="stat1_suffix"),
        migrations.RemoveField(model_name="marketinglandingpage", name="stat1_label"),
        migrations.RemoveField(model_name="marketinglandingpage", name="stat2_value"),
        migrations.RemoveField(model_name="marketinglandingpage", name="stat2_prefix"),
        migrations.RemoveField(model_name="marketinglandingpage", name="stat2_suffix"),
        migrations.RemoveField(model_name="marketinglandingpage", name="stat2_label"),
        migrations.RemoveField(model_name="marketinglandingpage", name="stat3_value"),
        migrations.RemoveField(model_name="marketinglandingpage", name="stat3_prefix"),
        migrations.RemoveField(model_name="marketinglandingpage", name="stat3_suffix"),
        migrations.RemoveField(model_name="marketinglandingpage", name="stat3_label"),
        migrations.RemoveField(model_name="marketinglandingpage", name="stat4_value"),
        migrations.RemoveField(model_name="marketinglandingpage", name="stat4_prefix"),
        migrations.RemoveField(model_name="marketinglandingpage", name="stat4_suffix"),
        migrations.RemoveField(model_name="marketinglandingpage", name="stat4_label"),
    ]
