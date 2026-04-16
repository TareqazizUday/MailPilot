from __future__ import annotations

import smtplib
from email.message import EmailMessage

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
        raise NotImplementedError("SMTP send is not implemented in the shim.")

