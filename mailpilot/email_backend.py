from __future__ import annotations

import ssl

from django.core.mail.backends.smtp import EmailBackend as DjangoSMTPEmailBackend
from django.utils.functional import cached_property


class NoHostnameCheckEmailBackend(DjangoSMTPEmailBackend):
    """
    SMTP backend that disables TLS hostname verification only.

    Keeps certificate chain verification, but doesn't require the certificate
    hostname to match the SMTP host (useful when a provider presents a cert for
    a different name, e.g. the domain).
    """

    @cached_property
    def ssl_context(self):
        ctx = super().ssl_context
        ctx.check_hostname = False
        return ctx


class InsecureTLSEmailBackend(DjangoSMTPEmailBackend):
    """
    SMTP backend that can disable TLS certificate verification.

    Use ONLY for development or when your SMTP server has a mismatched/self-signed
    certificate and you accept the risk.
    """

    @cached_property
    def ssl_context(self):
        ctx = super().ssl_context
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx

