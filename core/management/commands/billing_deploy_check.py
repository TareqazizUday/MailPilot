from __future__ import annotations

from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand
from dotenv import load_dotenv

from core.billing_deploy import billing_deploy_checks


class Command(BaseCommand):
    help = "Check production billing / deploy readiness (Stripe + PayPal from .env)."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--production",
            action="store_true",
            help="Run strict production checks (ignore local DEBUG=true).",
        )

    def handle(self, *args: Any, **opts: Any) -> None:
        load_dotenv(settings.BASE_DIR / ".env", override=True)

        production = bool(opts.get("production")) or not settings.DEBUG
        mode = "production" if production else "local (relaxed)"
        self.stdout.write(f"Billing deploy check — {mode}\n")

        failed = 0
        warned = 0
        for row in billing_deploy_checks(production=production):
            if row["ok"]:
                mark = self.style.SUCCESS("OK")
            elif row["severity"] == "warn":
                mark = self.style.WARNING("WARN")
                warned += 1
            else:
                mark = self.style.ERROR("FAIL")
                failed += 1
            detail = f" — {row['detail']}" if row.get("detail") else ""
            self.stdout.write(f"  [{mark}] {row['label']}{detail}")

        self.stdout.write("")
        if failed:
            self.stdout.write(self.style.ERROR(f"{failed} blocking issue(s). Fix before go-live."))
            raise SystemExit(1)
        if warned:
            self.stdout.write(self.style.WARNING(f"{warned} warning(s). Recommended to fix."))
        else:
            self.stdout.write(self.style.SUCCESS("All checks passed."))
