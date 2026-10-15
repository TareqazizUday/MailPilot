from __future__ import annotations

from rest_framework import serializers


class OkSerializer(serializers.Serializer):
    ok = serializers.BooleanField()


class ErrorSerializer(serializers.Serializer):
    ok = serializers.BooleanField(default=False)
    error = serializers.CharField()


class SetupCredentialsRequestSerializer(serializers.Serializer):
    gmail_address = serializers.EmailField()
    client_secret = serializers.FileField(help_text="Google OAuth client JSON (.json)")


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
    account_id = serializers.IntegerField(
        required=False, help_text="Save the token on this Gmail mailbox instead of the user-level token."
    )


class OAuthExchangeResponseSerializer(serializers.Serializer):
    ok = serializers.BooleanField()
    account_id = serializers.IntegerField(required=False)
    error = serializers.CharField(required=False, allow_blank=True)


class MailAccountSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    slot = serializers.IntegerField()
    transport = serializers.ChoiceField(choices=["gmail_api", "smtp"])
    label = serializers.CharField(allow_blank=True)
    is_enabled = serializers.BooleanField()
    email = serializers.CharField(allow_blank=True)
    gmail_connected = serializers.BooleanField()
    gmail_inbox_ready = serializers.BooleanField()
    oauth_email_mismatch = serializers.BooleanField()
    profile_email = serializers.CharField(allow_blank=True)
    imap_ready = serializers.BooleanField()
    inbox_ready = serializers.BooleanField()
    has_client_secret = serializers.BooleanField()
    has_token = serializers.BooleanField()
    has_smtp_password = serializers.BooleanField()
    smtp_last_test_ok = serializers.BooleanField()
    config = serializers.DictField()
    kb_chunk_count = serializers.IntegerField(required=False)


class MailAccountResponseSerializer(serializers.Serializer):
    ok = serializers.BooleanField()
    account = MailAccountSerializer()


class UserProfileSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    username = serializers.CharField()
    email = serializers.CharField(allow_blank=True)
    first_name = serializers.CharField(allow_blank=True)
    last_name = serializers.CharField(allow_blank=True)
    display_name = serializers.CharField(allow_blank=True)
    phone = serializers.CharField(allow_blank=True)
    company = serializers.CharField(allow_blank=True)
    timezone = serializers.CharField()
    notes = serializers.CharField(allow_blank=True)
    avatar_url = serializers.URLField(allow_null=True)


class UserProfileResponseSerializer(serializers.Serializer):
    ok = serializers.BooleanField()
    user = UserProfileSerializer()


class AvatarUploadRequestSerializer(serializers.Serializer):
    avatar = serializers.ImageField(help_text="PNG, JPG, WEBP or GIF, max 2 MB")


class ProfileUpdateRequestSerializer(serializers.Serializer):
    first_name = serializers.CharField(required=False, allow_blank=True, max_length=150)
    last_name = serializers.CharField(required=False, allow_blank=True, max_length=150)
    email = serializers.EmailField(required=False, allow_blank=True)
    display_name = serializers.CharField(required=False, allow_blank=True, max_length=120)
    phone = serializers.CharField(required=False, allow_blank=True, max_length=32)
    company = serializers.CharField(required=False, allow_blank=True, max_length=160)
    timezone = serializers.CharField(required=False, allow_blank=True, max_length=64)
    notes = serializers.CharField(required=False, allow_blank=True, max_length=2000)


class SignupRequestSerializer(serializers.Serializer):
    first_name = serializers.CharField(max_length=150)
    last_name = serializers.CharField(required=False, allow_blank=True, max_length=150)
    email = serializers.EmailField()
    password = serializers.CharField(min_length=8)
    password2 = serializers.CharField()
    terms = serializers.BooleanField(help_text="Must be true")
    username = serializers.CharField(required=False, allow_blank=True, help_text="Derived from email when omitted")


class SignupResponseSerializer(UserProfileResponseSerializer):
    access = serializers.CharField()
    refresh = serializers.CharField()


class ChangePasswordRequestSerializer(serializers.Serializer):
    current_password = serializers.CharField()
    new_password = serializers.CharField(min_length=8)


class PasswordResetRequestSerializer(serializers.Serializer):
    identifier = serializers.CharField(help_text="Email or username")


class PasswordResetRequestResponseSerializer(serializers.Serializer):
    ok = serializers.BooleanField()
    email = serializers.CharField(allow_blank=True, help_text="Empty when no account matches")
    email_hint = serializers.CharField(allow_blank=True)


class PasswordResetVerifyRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()
    otp = serializers.CharField(help_text="6-digit code from the email")


class PasswordResetVerifyResponseSerializer(serializers.Serializer):
    ok = serializers.BooleanField()
    reset_token = serializers.CharField()


class PasswordResetConfirmRequestSerializer(serializers.Serializer):
    reset_token = serializers.CharField()
    password = serializers.CharField(min_length=8)
    password2 = serializers.CharField()


class SocialProviderSerializer(serializers.Serializer):
    id = serializers.ChoiceField(choices=["google", "github"])
    label = serializers.CharField()
    configured = serializers.BooleanField(help_text="False until the provider keys are set on the server")


class SocialProvidersResponseSerializer(serializers.Serializer):
    ok = serializers.BooleanField()
    providers = SocialProviderSerializer(many=True)


class SocialAuthorizeUrlResponseSerializer(serializers.Serializer):
    ok = serializers.BooleanField()
    authorization_url = serializers.URLField()
    state = serializers.CharField()


class SocialExchangeRequestSerializer(serializers.Serializer):
    code = serializers.CharField(help_text="One-time `code` from the `return_to` deep link (valid 2 minutes)")


class SocialTokenRequestSerializer(serializers.Serializer):
    provider = serializers.ChoiceField(choices=["firebase", "google"])
    id_token = serializers.CharField(help_text="Firebase ID token (provider=firebase) or Google Sign-In ID token")
    access_token = serializers.CharField(
        required=False, help_text="GitHub OAuth access token from the same Firebase sign-in (GitHub only)"
    )


class SocialLoginResponseSerializer(SignupResponseSerializer):
    created = serializers.BooleanField(help_text="True when this sign-in created the account")


class KBClearResponseSerializer(serializers.Serializer):
    ok = serializers.BooleanField()
    deleted_documents = serializers.IntegerField(required=False)
    deleted_chunks = serializers.IntegerField(required=False)
    deleted_crawl_file = serializers.BooleanField(required=False)
    error = serializers.CharField(required=False, allow_blank=True)

