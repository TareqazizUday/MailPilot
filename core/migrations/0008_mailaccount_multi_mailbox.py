# Generated manually for multi-mailbox support

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def migrate_legacy_accounts(apps, schema_editor):
    User = apps.get_model("auth", "User")
    UserMailSettings = apps.get_model("core", "UserMailSettings")
    MailAccount = apps.get_model("core", "MailAccount")

    for ms in UserMailSettings.objects.all():
        if MailAccount.objects.filter(user_id=ms.user_id).exists():
            continue
        sj = dict(ms.settings_json or {})
        st = str(sj.get("SEND_TRANSPORT") or "gmail_api").strip()
        if st not in ("gmail_api", "smtp"):
            st = "gmail_api"
        mode = "smtp" if st == "smtp" else "gmail"
        if not ms.active_transport_mode:
            ms.active_transport_mode = mode
            ms.save(update_fields=["active_transport_mode"])

        if st == "gmail_api":
            ga = str(sj.get("GMAIL_ADDRESS") or "").strip()
            if ga or ms.google_oauth_token_enc or ms.client_secret_json_enc:
                acc = MailAccount.objects.create(
                    user_id=ms.user_id,
                    slot=1,
                    transport="gmail_api",
                    label=ga or "Gmail 1",
                    is_enabled=True,
                    config_json={"GMAIL_ADDRESS": ga} if ga else {},
                    oauth_token_enc=ms.google_oauth_token_enc or "",
                    client_secret_enc=ms.client_secret_json_enc or "",
                )
                ms.default_account_id = acc.id
                ms.save(update_fields=["default_account_id"])
        else:
            cfg = {
                k: sj[k]
                for k in sj
                if k.startswith(("SMTP_", "IMAP_"))
                or k in ("SMTP_LAST_TEST_OK", "SMTP_LAST_TEST_AT", "SMTP_LAST_TEST_ERROR")
            }
            if cfg or ms.smtp_password_enc:
                acc = MailAccount.objects.create(
                    user_id=ms.user_id,
                    slot=1,
                    transport="smtp",
                    label=str(cfg.get("SMTP_USERNAME") or cfg.get("SMTP_FROM_EMAIL") or "SMTP 1"),
                    is_enabled=True,
                    config_json=cfg,
                    smtp_password_enc=ms.smtp_password_enc or "",
                    imap_password_enc=ms.imap_password_enc or "",
                )
                ms.default_account_id = acc.id
                ms.save(update_fields=["default_account_id"])


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0007_contactsubmission"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="usermailsettings",
            name="active_transport_mode",
            field=models.CharField(default="gmail", max_length=8),
        ),
        migrations.AddField(
            model_name="usermailsettings",
            name="default_account_id",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.CreateModel(
            name="MailAccount",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("slot", models.PositiveSmallIntegerField()),
                ("transport", models.CharField(max_length=16)),
                ("label", models.CharField(blank=True, default="", max_length=80)),
                ("is_enabled", models.BooleanField(default=True)),
                ("config_json", models.JSONField(blank=True, default=dict)),
                ("oauth_token_enc", models.TextField(blank=True, default="")),
                ("client_secret_enc", models.TextField(blank=True, default="")),
                ("smtp_password_enc", models.TextField(blank=True, default="")),
                ("imap_password_enc", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="mail_accounts",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "core_mailaccount",
                "ordering": ["slot", "id"],
            },
        ),
        migrations.AddConstraint(
            model_name="mailaccount",
            constraint=models.UniqueConstraint(
                fields=("user", "slot", "transport"), name="uq_mailaccount_user_slot_transport"
            ),
        ),
        migrations.RunPython(migrate_legacy_accounts, migrations.RunPython.noop),
    ]
