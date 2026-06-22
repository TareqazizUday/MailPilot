from django.db import migrations, models
import django.db.models.deletion


def link_sections_to_page(apps, schema_editor):
    Settings = apps.get_model("core", "LegalTermsSettings")
    Section = apps.get_model("core", "LegalTermsSection")
    page, _ = Settings.objects.get_or_create(singleton_key=1)
    Section.objects.filter(page__isnull=True).update(page_id=page.pk)
    Section.objects.filter(page_id__isnull=True).update(page_id=page.pk)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0022_legal_terms"),
    ]

    operations = [
        migrations.AddField(
            model_name="legaltermssection",
            name="page",
            field=models.ForeignKey(
                default=1,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="sections",
                to="core.legaltermssettings",
            ),
            preserve_default=False,
        ),
        migrations.RunPython(link_sections_to_page, migrations.RunPython.noop),
    ]
