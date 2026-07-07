"""Admin usage economics: plan tokens, mailbox pipeline, and estimated variable cost."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from django.contrib.auth.models import User
from django.db.models import Sum

from core.models import MarketingPricingSettings, ProcessedMeta, UsageCounter, UserProfile, UserSubscription


@dataclass(frozen=True)
class ProfitAssumptions:
    api_cost_per_send_usd: Decimal
    token_cost_per_1k_usd: Decimal
    llm_cost_per_analyze_usd: Decimal


def get_profit_assumptions() -> ProfitAssumptions:
    cfg, _ = MarketingPricingSettings.objects.get_or_create(singleton_key=1)
    return ProfitAssumptions(
        api_cost_per_send_usd=Decimal(str(cfg.profit_api_cost_per_send_usd or 0)),
        token_cost_per_1k_usd=Decimal(str(cfg.profit_token_cost_per_1k_usd or 0)),
        llm_cost_per_analyze_usd=Decimal(str(cfg.profit_llm_cost_per_analyze_usd or 0)),
    )


def period_date_range(period_key: str) -> tuple[date, date]:
    year, month = map(int, period_key.split("-"))
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1)
    else:
        end = date(year, month + 1, 1)
    return start, end


def user_id_from_tenant(tenant_id: str) -> int | None:
    if not tenant_id:
        return None
    try:
        return int(str(tenant_id).split(":")[0])
    except (TypeError, ValueError):
        return None


def _parse_processed_date(raw: Any) -> date | None:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.date()
    except (TypeError, ValueError):
        return None


def aggregate_pipeline_by_user(
    period_key: str,
    *,
    user_ids: set[int] | None = None,
) -> dict[int, dict[str, int]]:
    """Mailbox → LLM → draft/send pipeline counts from ProcessedMeta."""
    start, end = period_date_range(period_key)
    stats: dict[int, dict[str, int]] = {}
    allowed = user_ids

    for row in ProcessedMeta.objects.only("tenant_id", "meta_json").iterator(chunk_size=500):
        uid = user_id_from_tenant(row.tenant_id)
        if uid is None:
            continue
        if allowed is not None and uid not in allowed:
            continue
        meta = row.meta_json if isinstance(row.meta_json, dict) else {}
        processed_on = _parse_processed_date(meta.get("processed_at"))
        if processed_on is None or processed_on < start or processed_on >= end:
            continue

        action = str(meta.get("action") or "").lower()
        reason = str(meta.get("reason") or "").lower()
        bucket = stats.setdefault(
            uid,
            {
                "mailbox_handled": 0,
                "sent": 0,
                "draft": 0,
                "ignored": 0,
                "prefilter_skipped": 0,
                "llm_calls": 0,
            },
        )

        if action == "sent":
            bucket["mailbox_handled"] += 1
            bucket["sent"] += 1
            bucket["llm_calls"] += 1
        elif action == "draft":
            bucket["mailbox_handled"] += 1
            bucket["draft"] += 1
            bucket["llm_calls"] += 1
        elif action == "ignored":
            bucket["mailbox_handled"] += 1
            if reason == "keyword_prefilter":
                bucket["prefilter_skipped"] += 1
            else:
                bucket["ignored"] += 1
                bucket["llm_calls"] += 1

    return stats


def estimate_variable_cost_usd(
    *,
    assumptions: ProfitAssumptions,
    plan_tokens: int,
    auto_sends: int,
    llm_calls: int,
) -> dict[str, Decimal]:
    """Estimate variable cost: auto-send pipeline + extra LLM reads + token overhead."""
    non_send_llm = max(0, int(llm_calls) - int(auto_sends))
    send_cost = Decimal(auto_sends) * assumptions.api_cost_per_send_usd
    llm_cost = Decimal(non_send_llm) * assumptions.llm_cost_per_analyze_usd
    token_cost = (Decimal(plan_tokens) / Decimal(1000)) * assumptions.token_cost_per_1k_usd
    total = send_cost + llm_cost + token_cost
    return {
        "send_cost": send_cost,
        "llm_cost": llm_cost,
        "token_cost": token_cost,
        "total": total,
    }


def _quantize_usd(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.01")))


def build_usage_economics(period_key: str, *, user_label_fn) -> dict[str, Any]:
    """Per-user usage + cost rows and period totals for the admin dashboard."""
    assumptions = get_profit_assumptions()
    pipeline = aggregate_pipeline_by_user(period_key)

    counters = {
        row.user_id: row
        for row in UsageCounter.objects.filter(period_key=period_key).select_related("user")
    }
    user_ids = set(counters) | set(pipeline)
    if not user_ids:
        return {
            "period": period_key,
            "assumptions": {
                "api_cost_per_send_usd": _quantize_usd(assumptions.api_cost_per_send_usd),
                "llm_cost_per_analyze_usd": _quantize_usd(assumptions.llm_cost_per_analyze_usd),
                "token_cost_per_1k_usd": _quantize_usd(assumptions.token_cost_per_1k_usd),
            },
            "totals": {
                "plan_tokens": 0,
                "auto_sends": 0,
                "mailbox_handled": 0,
                "llm_calls": 0,
                "drafts": 0,
                "ignored": 0,
                "prefilter_skipped": 0,
                "cost_usd": 0.0,
                "send_cost_usd": 0.0,
                "llm_cost_usd": 0.0,
                "token_cost_usd": 0.0,
            },
            "users": [],
            "cost_chart": {"labels": [], "series": []},
            "pipeline_chart": {"labels": ["Auto-sent", "Draft", "Ignored", "Prefilter skip"], "series": [0, 0, 0, 0]},
        }

    profiles = {p.user_id: p for p in UserProfile.objects.filter(user_id__in=user_ids)}
    subs = {s.user_id: s for s in UserSubscription.objects.filter(user_id__in=user_ids)}
    users = {u.id: u for u in User.objects.filter(id__in=user_ids)}

    rows: list[dict[str, Any]] = []
    totals = {
        "plan_tokens": 0,
        "auto_sends": 0,
        "mailbox_handled": 0,
        "llm_calls": 0,
        "drafts": 0,
        "ignored": 0,
        "prefilter_skipped": 0,
        "cost_usd": Decimal(0),
        "send_cost_usd": Decimal(0),
        "llm_cost_usd": Decimal(0),
        "token_cost_usd": Decimal(0),
    }

    for uid in user_ids:
        counter = counters.get(uid)
        pipe = pipeline.get(
            uid,
            {
                "mailbox_handled": 0,
                "sent": 0,
                "draft": 0,
                "ignored": 0,
                "prefilter_skipped": 0,
                "llm_calls": 0,
            },
        )
        plan_tokens = int(counter.tokens_used) if counter else 0
        auto_sends = int(counter.auto_sent_count) if counter else 0
        llm_calls = int(pipe["llm_calls"])

        costs = estimate_variable_cost_usd(
            assumptions=assumptions,
            plan_tokens=plan_tokens,
            auto_sends=auto_sends,
            llm_calls=llm_calls,
        )

        user = users.get(uid)
        if not user:
            continue
        sub = subs.get(uid)
        profile = profiles.get(uid)
        limit = int(sub.monthly_token_limit) if sub and sub.monthly_token_limit else None
        used = plan_tokens
        pct = min(100, round((used / max(1, limit)) * 100)) if limit else None

        row = {
            "user_id": uid,
            "name": user_label_fn(user, profile),
            "email": user.email or user.username,
            "plan": sub.get_plan_code_display() if sub else "—",
            "plan_tokens": plan_tokens,
            "token_limit": limit,
            "token_pct": pct,
            "auto_sends": auto_sends,
            "mailbox_handled": int(pipe["mailbox_handled"]),
            "llm_calls": llm_calls,
            "drafts": int(pipe["draft"]),
            "ignored": int(pipe["ignored"]),
            "prefilter_skipped": int(pipe["prefilter_skipped"]),
            "cost_usd": _quantize_usd(costs["total"]),
            "send_cost_usd": _quantize_usd(costs["send_cost"]),
            "llm_cost_usd": _quantize_usd(costs["llm_cost"]),
            "token_cost_usd": _quantize_usd(costs["token_cost"]),
        }
        rows.append(row)

        totals["plan_tokens"] += plan_tokens
        totals["auto_sends"] += auto_sends
        totals["mailbox_handled"] += row["mailbox_handled"]
        totals["llm_calls"] += llm_calls
        totals["drafts"] += row["drafts"]
        totals["ignored"] += row["ignored"]
        totals["prefilter_skipped"] += row["prefilter_skipped"]
        totals["cost_usd"] += costs["total"]
        totals["send_cost_usd"] += costs["send_cost"]
        totals["llm_cost_usd"] += costs["llm_cost"]
        totals["token_cost_usd"] += costs["token_cost"]

    rows.sort(key=lambda r: (-r["cost_usd"], -r["plan_tokens"], r["name"].lower()))

    cost_chart_rows = rows[:12]
    pipeline_series = [
        totals["auto_sends"],
        totals["drafts"],
        totals["ignored"],
        totals["prefilter_skipped"],
    ]

    return {
        "period": period_key,
        "assumptions": {
            "api_cost_per_send_usd": _quantize_usd(assumptions.api_cost_per_send_usd),
            "llm_cost_per_analyze_usd": _quantize_usd(assumptions.llm_cost_per_analyze_usd),
            "token_cost_per_1k_usd": _quantize_usd(assumptions.token_cost_per_1k_usd),
        },
        "totals": {
            "plan_tokens": totals["plan_tokens"],
            "auto_sends": totals["auto_sends"],
            "mailbox_handled": totals["mailbox_handled"],
            "llm_calls": totals["llm_calls"],
            "drafts": totals["drafts"],
            "ignored": totals["ignored"],
            "prefilter_skipped": totals["prefilter_skipped"],
            "cost_usd": _quantize_usd(totals["cost_usd"]),
            "send_cost_usd": _quantize_usd(totals["send_cost_usd"]),
            "llm_cost_usd": _quantize_usd(totals["llm_cost_usd"]),
            "token_cost_usd": _quantize_usd(totals["token_cost_usd"]),
        },
        "users": rows,
        "cost_chart": {
            "labels": [r["name"] for r in cost_chart_rows],
            "series": [r["cost_usd"] for r in cost_chart_rows],
        },
        "pipeline_chart": {
            "labels": ["Auto-sent", "Draft", "Ignored", "Prefilter skip"],
            "series": pipeline_series,
        },
    }


def period_token_totals(period_key: str) -> dict[str, int]:
    agg = UsageCounter.objects.filter(period_key=period_key).aggregate(
        tokens=Sum("tokens_used"),
        sends=Sum("auto_sent_count"),
    )
    return {
        "plan_tokens": int(agg.get("tokens") or 0),
        "auto_sends": int(agg.get("sends") or 0),
    }


_EMPTY_PIPELINE = {
    "mailbox_handled": 0,
    "sent": 0,
    "draft": 0,
    "ignored": 0,
    "prefilter_skipped": 0,
    "llm_calls": 0,
}


def usage_map_for_user_ids(user_ids: list[int], period_key: str) -> dict[int, dict[str, Any]]:
    """Compact per-user usage + cost for admin changelists (current billing period)."""
    if not user_ids:
        return {}

    assumptions = get_profit_assumptions()
    uid_set = set(user_ids)
    pipeline = aggregate_pipeline_by_user(period_key, user_ids=uid_set)
    counters = {
        row.user_id: row
        for row in UsageCounter.objects.filter(period_key=period_key, user_id__in=user_ids)
    }
    subs = {
        s.user_id: s
        for s in UserSubscription.objects.filter(user_id__in=user_ids).only(
            "user_id", "monthly_token_limit", "plan_code"
        )
    }

    out: dict[int, dict[str, Any]] = {}
    for uid in user_ids:
        counter = counters.get(uid)
        pipe = pipeline.get(uid, _EMPTY_PIPELINE)
        plan_tokens = int(counter.tokens_used) if counter else 0
        auto_sends = int(counter.auto_sent_count) if counter else 0
        llm_calls = int(pipe["llm_calls"])
        costs = estimate_variable_cost_usd(
            assumptions=assumptions,
            plan_tokens=plan_tokens,
            auto_sends=auto_sends,
            llm_calls=llm_calls,
        )
        sub = subs.get(uid)
        limit = int(sub.monthly_token_limit) if sub and sub.monthly_token_limit else None
        pct = min(100, round((plan_tokens / max(1, limit)) * 100)) if limit else None
        out[uid] = {
            "plan_tokens": plan_tokens,
            "token_limit": limit,
            "token_pct": pct,
            "auto_sends": auto_sends,
            "mailbox_handled": int(pipe["mailbox_handled"]),
            "llm_calls": llm_calls,
            "drafts": int(pipe["draft"]),
            "ignored": int(pipe["ignored"]),
            "cost_usd": _quantize_usd(costs["total"]),
        }
    return out
