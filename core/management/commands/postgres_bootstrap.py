from __future__ import annotations

import os
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from dotenv import load_dotenv

import psycopg
from psycopg import sql


class Command(BaseCommand):
    help = (
        "One-time: connect as PostgreSQL superuser, ensure app role + database exist, "
        "and set the app user password to match DJANGO_DB_PASSWORD."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--admin-user",
            default=None,
            help="Superuser name (default: env POSTGRES_BOOTSTRAP_USER or 'postgres').",
        )
        parser.add_argument(
            "--admin-password",
            default=None,
            help="Superuser password (default: env POSTGRES_BOOTSTRAP_PASSWORD).",
        )

    def handle(self, *args: Any, **opts: Any) -> None:
        # Re-load .env so vars win over empty placeholders in the process environment.
        load_dotenv(settings.BASE_DIR / ".env", override=True)

        app_db = (os.environ.get("DJANGO_DB_NAME") or "mailpilot").strip()
        app_user = (os.environ.get("DJANGO_DB_USER") or "mailpilot_user").strip()
        app_password = os.environ.get("DJANGO_DB_PASSWORD") or ""
        host = (os.environ.get("DJANGO_DB_HOST") or "127.0.0.1").strip() or "127.0.0.1"
        port = (os.environ.get("DJANGO_DB_PORT") or "5432").strip() or "5432"

        if not app_db or not app_user:
            raise CommandError("DJANGO_DB_NAME and DJANGO_DB_USER must be set in .env")

        admin_user = (opts.get("admin_user") or os.environ.get("POSTGRES_BOOTSTRAP_USER") or "postgres").strip()
        admin_password = (opts.get("admin_password") or os.environ.get("POSTGRES_BOOTSTRAP_PASSWORD") or "").strip()
        if not admin_password:
            raise CommandError(
                "Set POSTGRES_BOOTSTRAP_PASSWORD in .env to the PostgreSQL superuser password "
                "(the one you chose when installing PostgreSQL), or pass --admin-password."
            )

        conninfo = (
            f"host={host} port={port} dbname=postgres "
            f"user={admin_user} password={admin_password} connect_timeout=10"
        )

        self.stdout.write(
            f"Bootstrapping role={app_user!r} database={app_db!r} on {host}:{port} (as admin {admin_user!r})…"
        )

        try:
            with psycopg.connect(conninfo, autocommit=True) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (app_user,))
                    if cur.fetchone() is None:
                        cur.execute(
                            sql.SQL("CREATE USER {} WITH PASSWORD {}").format(
                                sql.Identifier(app_user),
                                sql.Literal(app_password),
                            )
                        )
                        self.stdout.write(self.style.SUCCESS(f"Created role {app_user!r}."))
                    else:
                        cur.execute(
                            sql.SQL("ALTER USER {} WITH PASSWORD {}").format(
                                sql.Identifier(app_user),
                                sql.Literal(app_password),
                            )
                        )
                        self.stdout.write(self.style.SUCCESS(f"Updated password for role {app_user!r}."))

                    cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (app_db,))
                    if cur.fetchone() is None:
                        cur.execute(
                            sql.SQL("CREATE DATABASE {} OWNER {}").format(
                                sql.Identifier(app_db),
                                sql.Identifier(app_user),
                            )
                        )
                        self.stdout.write(self.style.SUCCESS(f"Created database {app_db!r} (owner {app_user!r})."))
                    else:
                        self.stdout.write(f"Database {app_db!r} already exists (left unchanged).")
        except Exception as e:
            raise CommandError(f"Bootstrap failed: {e}") from e

        self.stdout.write(self.style.SUCCESS("Done. Next: python manage.py migrate"))
