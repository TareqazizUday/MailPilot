from __future__ import annotations

from django import template

register = template.Library()


@register.inclusion_tag("components/footer.html")
def marketing_footer():
    from core.marketing import get_footer_settings

    page = get_footer_settings()
    return {
        "footer": page,
        "footer_product_links": page.links.filter(column="product", is_published=True),
        "footer_account_links": page.links.filter(column="account", is_published=True),
        "footer_trust": page.trust_badges.filter(is_published=True),
        "footer_offices": page.offices.filter(is_published=True),
        "star_slots": (1, 2, 3, 4, 5),
    }
