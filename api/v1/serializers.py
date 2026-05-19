from __future__ import annotations

from rest_framework import serializers


class OkSerializer(serializers.Serializer):
    ok = serializers.BooleanField()


class ErrorSerializer(serializers.Serializer):
    ok = serializers.BooleanField(default=False)
    error = serializers.CharField()


class SetupCredentialsRequestSerializer(serializers.Serializer):
    gmail_address = serializers.EmailField()
    client_secret = serializers.FileField()


class GmailConnectionStatusResponseSerializer(serializers.Serializer):
    ok = serializers.BooleanField()
    connected = serializers.BooleanField()
    gmail_connected = serializers.BooleanField()
    imap_connected = serializers.BooleanField()
    smtp_last_test_ok = serializers.BooleanField()
    send_transport = serializers.CharField(allow_blank=True)
    poll_ready = serializers.BooleanField()
    has_client_secret = serializers.BooleanField()
    has_token = serializers.BooleanField()
    has_gmail_address = serializers.BooleanField()
    gmail_address = serializers.CharField(allow_blank=True, allow_null=True)
    token_error = serializers.CharField(allow_blank=True, allow_null=True, required=False)


class GmailInboxResponseSerializer(serializers.Serializer):
    ok = serializers.BooleanField()
    source = serializers.ChoiceField(choices=["gmail", "imap"])
    threads = serializers.ListField(child=serializers.DictField(), required=False)


class GmailThreadDetailResponseSerializer(serializers.Serializer):
    ok = serializers.BooleanField()
    # Thread detail shape differs by backend; keep flexible but documented
    data = serializers.DictField(required=False)


class TriggerPollResponseSerializer(serializers.Serializer):
    ok = serializers.BooleanField()


class KBStatusResponseSerializer(serializers.Serializer):
    ok = serializers.BooleanField()
    configured = serializers.BooleanField()
    error = serializers.CharField(required=False, allow_blank=True)
    # VectorStore.stats() keys vary; allow extras
    stats = serializers.DictField(required=False)


class KBUploadJsonRequestSerializer(serializers.Serializer):
    json_file = serializers.FileField()


class KBUploadTextRequestSerializer(serializers.Serializer):
    text_file = serializers.FileField()


class KBUploadJsonResponseSerializer(serializers.Serializer):
    ok = serializers.BooleanField()
    documents = serializers.IntegerField(required=False)
    chunks = serializers.IntegerField(required=False)
    error = serializers.CharField(required=False, allow_blank=True)


class KBCrawlRequestSerializer(serializers.Serializer):
    start_url = serializers.URLField()


class KBCrawlResponseSerializer(serializers.Serializer):
    ok = serializers.BooleanField()
    started = serializers.BooleanField(required=False)
    error = serializers.CharField(required=False, allow_blank=True)


class PendingResponseSerializer(serializers.Serializer):
    ok = serializers.BooleanField()
    items = serializers.ListField(child=serializers.DictField(), required=False)


class AdminConfigGetResponseSerializer(serializers.Serializer):
    ok = serializers.BooleanField()
    effective = serializers.DictField(required=False)
    error = serializers.CharField(required=False, allow_blank=True)


class AdminConfigPostRequestSerializer(serializers.Serializer):
    # allow partial config payload; validated by legacy handler
    payload = serializers.DictField(required=False)


class AdminConfigPostResponseSerializer(serializers.Serializer):
    ok = serializers.BooleanField()
    updated = serializers.ListField(child=serializers.CharField(), required=False)
    error = serializers.CharField(required=False, allow_blank=True)


class SMTPTestResponseSerializer(serializers.Serializer):
    ok = serializers.BooleanField()
    error = serializers.CharField(required=False, allow_blank=True)


class SMTPStatusResponseSerializer(serializers.Serializer):
    ok = serializers.BooleanField()
    last_test_ok = serializers.BooleanField()
    last_test_at = serializers.CharField(allow_blank=True)
    last_test_error = serializers.CharField(allow_blank=True)


class OAuthAuthorizeUrlResponseSerializer(serializers.Serializer):
    ok = serializers.BooleanField()
    authorization_url = serializers.URLField(required=False)
    state = serializers.CharField(required=False, allow_blank=True)
    error = serializers.CharField(required=False, allow_blank=True)


class OAuthExchangeRequestSerializer(serializers.Serializer):
    code = serializers.CharField()
    state = serializers.CharField(required=False, allow_blank=True)


class OAuthExchangeResponseSerializer(serializers.Serializer):
    ok = serializers.BooleanField()
    error = serializers.CharField(required=False, allow_blank=True)

