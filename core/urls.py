from __future__ import annotations

from django.urls import path

from core import auth_views, views

urlpatterns = [
    path("robots.txt", views.robots_txt, name="robots_txt"),
    path("sitemap.xml", views.sitemap_xml, name="sitemap_xml"),
    path("terms", views.terms_page, name="terms"),
    path("privacy", views.privacy_page, name="privacy"),
    path("features", views.features_page, name="features"),
    path("how-it-works", views.how_it_works_page, name="how_it_works"),
    path("reviews", views.reviews_page, name="reviews"),
    path("pricing", views.pricing_page, name="pricing"),
    path("pricing/custom", views.custom_plan_builder_page, name="custom_plan_builder"),
    path("", views.landing_page, name="home"),
    path("contact", views.landing_contact, name="landing_contact"),
    path("login", auth_views.login_view, name="login"),
    path("signup", auth_views.signup_view, name="signup"),
    path("logout", auth_views.logout_view, name="logout"),
    path("password-reset", auth_views.password_reset_request_view, name="password_reset"),
    path("password-reset/done", auth_views.password_reset_done_view, name="password_reset_done"),
    path("password-reset/verify", auth_views.password_reset_verify_view, name="password_reset_verify"),
    path("password-reset/set-password", auth_views.password_reset_set_view, name="password_reset_set"),
    path("password-reset/complete", auth_views.password_reset_complete_view, name="password_reset_complete"),
    path("favicon.ico", views.favicon),
    path("healthz", views.healthz),
    path("billing/checkout/pro", views.billing_checkout_pro, name="billing_checkout_pro"),
    path("billing/checkout/custom/<int:quote_id>", views.billing_checkout_custom, name="billing_checkout_custom"),
    path("billing/demo/checkout", views.billing_demo_checkout, name="billing_demo_checkout"),
    path("billing/demo/complete", views.billing_demo_complete, name="billing_demo_complete"),
    path("billing/custom", views.billing_custom_request, name="billing_custom_request"),
    path("billing/portal", views.billing_portal, name="billing_portal"),
    path("billing/webhook/stripe", views.billing_stripe_webhook, name="billing_stripe_webhook"),
    path("setup", views.setup_page, name="setup"),
    path("dashboard", views.dashboard_page, name="dashboard"),
    path("profile", views.profile_page, name="profile"),
    path("settings", views.settings_page, name="settings"),
]
