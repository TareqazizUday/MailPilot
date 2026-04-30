from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage
from email.utils import make_msgid

from email_automation.settings import Settings


class SMTPClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    def test_connection(self) -> None:
        host = (self.settings.SMTP_HOST or "").strip()
        port = int(self.settings.SMTP_PORT or 0)
        if not host or not port:
            raise RuntimeError("SMTP not configured (missing SMTP_HOST/SMTP_PORT).")

        username = (self.settings.SMTP_USERNAME or "").strip()
        password = self.settings.SMTP_PASSWORD.get_secret_value() if self.settings.SMTP_PASSWORD else ""

        if self.settings.SMTP_USE_SSL:
            server: smtplib.SMTP = smtplib.SMTP_SSL(host, port, timeout=10)
        else:
            server = smtplib.SMTP(host, port, timeout=10)
        try:
            server.ehlo()
            if self.settings.SMTP_USE_TLS and not self.settings.SMTP_USE_SSL:
                server.starttls()
                server.ehlo()
            if username and password:
                server.login(username, password)
        finally:
            try:
                server.quit()
            except Exception:
                pass

    def send_test_email(self, to_email: str) -> None:
        msg = EmailMessage()
        msg["Subject"] = "MailPilot SMTP test"
        msg["From"] = self.settings.outbound_from_email() or "no-reply@example.com"
        msg["To"] = to_email
        msg.set_content("SMTP configuration looks OK.")
        self.send_message(msg)

    def send_message(self, msg: EmailMessage) -> None:
        host = (self.settings.SMTP_HOST or "").strip()
        port = int(self.settings.SMTP_PORT or 0)
        if not host or not port:
            raise RuntimeError("SMTP not configured (missing SMTP_HOST/SMTP_PORT).")

        username = (self.settings.SMTP_USERNAME or "").strip()
        password = self.settings.SMTP_PASSWORD.get_secret_value() if self.settings.SMTP_PASSWORD else ""

        ctx = ssl.create_default_context()
        if not bool(getattr(self.settings, "SMTP_VERIFY_TLS", True)):
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE

        if self.settings.SMTP_USE_SSL:
            server: smtplib.SMTP = smtplib.SMTP_SSL(host, port, timeout=20, context=ctx)
        else:
            server = smtplib.SMTP(host, port, timeout=20)
        try:
            server.ehlo()
            if self.settings.SMTP_USE_TLS and not self.settings.SMTP_USE_SSL:
                # Allow overriding the TLS servername for SNI/hostname verification.
                # Useful when connecting to smtp.<domain> but the certificate is issued for <domain>.
                tls_name = (getattr(self.settings, "SMTP_TLS_SERVERNAME", "") or "").strip()
                if tls_name and bool(getattr(self.settings, "SMTP_VERIFY_TLS", True)):
                    try:
                        server._host = tls_name  # smtplib uses this for server_hostname in starttls()
                    except Exception:
                        pass
                server.starttls(context=ctx)
                server.ehlo()
            if username and password:
                server.login(username, password)
            server.send_message(msg)
        finally:
            try:
                server.quit()
            except Exception:
                pass

    def send_text_email(
        self,
        *,
        to_email: str,
        subject: str,
        body_text: str,
        in_reply_to: str | None = None,
        references: str | None = None,
    ) -> None:
        msg = EmailMessage()
        msg["Subject"] = subject or "(No subject)"
        msg["From"] = self.settings.outbound_from_email() or "no-reply@example.com"
        msg["To"] = to_email
        msg["Message-ID"] = make_msgid(domain=None)
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
        if references:
            msg["References"] = references
        msg.set_content(body_text or "")
        self.send_message(msg)

