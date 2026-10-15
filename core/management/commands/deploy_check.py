from __future__ import annotations

from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.deploy_check import deploy_checks


class Command(BaseCommand):
    help = "Check that this server is ready for production (env, HTTPS, DB, static files, billing)."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--production",
            action="store_true",
            help="Strict checks even when MAILPILOT_ENV is not production.",
        )
        parser.add_argument("--skip-billing", action="store_true", help="Leave out Stripe/PayPal checks.")

    def handle(self, *args: Any, **opts: Any) -> None:
        production = bool(opts["production"]) or settings.IS_PRODUCTION
        self.stdout.write(f"Deploy check - {'production' if production else 'local (relaxed)'}\n")

        failed = warned = 0
        for row in deploy_checks(production=production, billing=not opts["skip_billing"]):
            if row["ok"]:
                mark = self.style.SUCCESS("OK  ")
            elif row["severity"] == "warn":
                mark = self.style.WARNING("WARN")
                warned += 1
            else:
                mark = self.style.ERROR("FAIL")
                failed += 1
            detail = f" - {row['detail']}" if row.get("detail") else ""
            self.stdout.write(f"  [{mark}] {row['label']}{detail}")

        self.stdout.write("")
        if failed:
            raise CommandError(f"{failed} check(s) failed, {warned} warning(s). Fix the FAIL lines before going live.")
        self.stdout.write(self.style.SUCCESS(f"Ready. {warned} warning(s)."))
