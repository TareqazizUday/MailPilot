from __future__ import annotations

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from core.marketing import seed_default_pricing
from core.models import MarketingPricingPlan


@override_settings(SECURE_SSL_REDIRECT=False)
class PricingFeedTests(TestCase):
    def setUp(self) -> None:
        seed_default_pricing()
        self.client_api = APIClient()

    def test_public_feed_matches_admin_plans(self) -> None:
        res = self.client_api.get("/api/v1/pricing?currency=usd")
        self.assertEqual(res.status_code, 200)
        body = res.json()
        codes = [p["code"] for p in body["plans"]]
        expected = list(
            MarketingPricingPlan.objects.filter(is_published=True, show_on_homepage=True)
            .order_by("sort_order", "pk")
            .values_list("plan_code", flat=True)
        )
        self.assertEqual(codes, expected)
        self.assertFalse(body["account"]["authenticated"])
        pro = next(p for p in body["plans"] if p["code"] == "pro")
        self.assertEqual(pro["monthly"]["price"], "$20")
        self.assertEqual(pro["cta"]["action"], "signup")

    def test_gbp_conversion_matches_website(self) -> None:
        body = self.client_api.get("/api/v1/pricing?currency=gbp").json()
        pro = next(p for p in body["plans"] if p["code"] == "pro")
        self.assertEqual(body["currency_symbol"], "\u00a3")
        self.assertEqual(pro["monthly"]["price"], "\u00a316")
        self.assertEqual(pro["yearly"]["price"], "\u00a3160")
        self.assertEqual(pro["currencies"]["usd"]["monthly"]["price"], "$20")

    def test_admin_edit_shows_up_immediately(self) -> None:
        MarketingPricingPlan.objects.filter(plan_code="pro").update(price_display="$25", tier_label="Pro+")
        body = self.client_api.get("/api/v1/pricing?currency=usd").json()
        pro = next(p for p in body["plans"] if p["code"] == "pro")
        self.assertEqual(pro["tier_label"], "Pro+")
        self.assertEqual(pro["monthly"]["price"], "$25")

    def test_unpublished_plan_is_hidden(self) -> None:
        MarketingPricingPlan.objects.filter(plan_code="custom").update(is_published=False)
        body = self.client_api.get("/api/v1/pricing").json()
        self.assertNotIn("custom", [p["code"] for p in body["plans"]])

    def test_signed_in_user_gets_account_state(self) -> None:
        user = User.objects.create_user(username="buyer", password="pass12345")
        token = RefreshToken.for_user(user).access_token
        self.client_api.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        body = self.client_api.get("/api/v1/pricing").json()
        self.assertTrue(body["account"]["authenticated"])
        pro = next(p for p in body["plans"] if p["code"] == "pro")
        self.assertEqual(pro["cta"]["action"], "checkout_pro")

    def test_bad_token_still_returns_public_feed(self) -> None:
        self.client_api.credentials(HTTP_AUTHORIZATION="Bearer not-a-token")
        res = self.client_api.get("/api/v1/pricing")
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.json()["account"]["authenticated"])
