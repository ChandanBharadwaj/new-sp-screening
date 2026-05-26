"""Derive ScreeningRule rows from sanctioned_commodity + country_rule data.

The country-program/OFAC/EU/BIS/ITAR/UN ingesters populate `sanctioned_commodity`
and `country_rule`; this module turns those rows into `screening_rule` rows so
the cross-encoder semantic path (`app/pipeline/rules.py::score`) can match
cargo text against curated commodity language with origin/destination scoping
and the conditions DSL.

Idempotency: upsert via the partial unique index `uq_screening_rule_materialized`
(migration 0006), keyed on `(created_by, name)`. Re-running for the same source
updates existing rows in place; rows whose source records have disappeared are
soft-deactivated.

Gating: `sanctions_rule_config.enabled` per source. Disabled sources are a
cheap no-op so the materializer can be wired unconditionally after every
sanctions ingest in `app/workers/refdata_jobs.py`.
"""
from __future__ import annotations

import asyncio
import hashlib
import re
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    CountryRule,
    SanctionedCommodity,
    SanctionedCommodityAlias,
    SanctionsRuleConfig,
    ScreeningRule,
)
from app.refdata.common import lazy_embedder
from app.telemetry import log

VALID_STRATEGIES = ("description_only", "with_aliases", "split_lists")
DEFAULT_THRESHOLD = 0.55
MAX_PHRASES = 10  # mirrors app/schemas/rule.py::PhraseGroup.phrases max_length
MAX_NAME_LEN = 200  # mirrors RuleIn.name max_length
SPLIT_RE = re.compile(r"\s*(?:,|;| and )\s*", re.IGNORECASE)


def _scope_token(origin: str | None, destination: str | None) -> str:
    return f"{origin or '*'}->{destination or '*'}"


def _build_phrases(
    description: str, aliases: list[str], strategy: str
) -> list[str]:
    """Return the deduped phrase list for the given strategy, capped at MAX_PHRASES.

    The first element is always the (cleaned) description — used as the legacy
    `phrase` field and as the embedding seed in `materialize_for_source`.
    """
    desc = (description or "").strip()
    if not desc:
        return []
    out: list[str] = [desc]
    seen: set[str] = {desc.lower()}

    def _add(p: str) -> None:
        p = (p or "").strip()
        if not p or len(p) < 3:
            return
        key = p.lower()
        if key in seen:
            return
        seen.add(key)
        out.append(p)

    if strategy in ("split_lists",):
        for part in SPLIT_RE.split(desc):
            _add(part)
    if strategy in ("with_aliases", "split_lists"):
        for a in aliases or []:
            _add(a)
    return out[:MAX_PHRASES]


def _stable_record_token(commodity: dict[str, Any]) -> str:
    """Stable per-commodity identity used in the materialized rule's name.

    Prefers `source_record_id` (set by every well-behaved ingester). Falls back to
    a short hash of `description` so the name is still deterministic across runs.
    """
    rid = commodity.get("source_record_id")
    if rid:
        return str(rid)
    desc = (commodity.get("description") or "").strip()
    return "h" + hashlib.sha1(desc.encode("utf-8")).hexdigest()[:10]


def build_rule_fields(
    commodity: dict[str, Any],
    aliases: list[str],
    country_rule: dict[str, Any],
    cfg: dict[str, Any],
) -> dict[str, Any] | None:
    """Pure deriver. Returns the dict of fields a ScreeningRule row needs, or None.

    Inputs:
      commodity: subset of a sanctioned_commodity row (`id`, `source`,
        `source_record_id`, `description`).
      aliases:   alias strings already loaded for that commodity.
      country_rule: subset of a country_rule row (`origin_iso`, `destination_iso`,
        `restriction_type`, `conditions`).
      cfg:       `{enabled, default_threshold, phrase_strategy}` for the source.

    Returns None when the row has no usable phrase (empty description).
    """
    strategy = cfg.get("phrase_strategy") or "split_lists"
    if strategy not in VALID_STRATEGIES:
        strategy = "split_lists"

    phrases = _build_phrases(commodity.get("description") or "", aliases, strategy)
    if not phrases:
        return None

    primary = phrases[0]
    phrase_group: dict[str, Any] | None = None
    if len(phrases) > 1:
        phrase_group = {"mode": "any_of", "phrases": phrases}

    source = commodity["source"]
    token = _stable_record_token(commodity)
    scope = _scope_token(
        country_rule.get("origin_iso"), country_rule.get("destination_iso")
    )
    raw_name = f"{source}:{token}::{scope}"
    name = raw_name[:MAX_NAME_LEN]

    threshold = float(cfg.get("default_threshold") or DEFAULT_THRESHOLD)

    return {
        "name": name,
        "phrase": primary,
        "phrase_group": phrase_group,
        "threshold": threshold,
        "conditions": country_rule.get("conditions"),
        "origin_iso": country_rule.get("origin_iso"),
        "destination_iso": country_rule.get("destination_iso"),
        "active": True,
        "created_by": f"sanctions_source:{source}",
    }


async def get_config(db: AsyncSession, source: str) -> dict[str, Any] | None:
    row = (
        await db.execute(
            select(SanctionsRuleConfig).where(SanctionsRuleConfig.source == source)
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    return {
        "source": row.source,
        "enabled": bool(row.enabled),
        "default_threshold": float(row.default_threshold),
        "phrase_strategy": row.phrase_strategy,
    }


async def _fetch_source_data(
    db: AsyncSession, source: str
) -> tuple[list[dict[str, Any]], dict[int, list[str]], dict[int, list[dict[str, Any]]]]:
    """Load every (sanctioned_commodity, aliases, country_rules) tuple for source."""
    commodity_rows = (
        await db.execute(
            select(
                SanctionedCommodity.id,
                SanctionedCommodity.source,
                SanctionedCommodity.source_record_id,
                SanctionedCommodity.description,
            ).where(
                SanctionedCommodity.source == source,
                SanctionedCommodity.sys_to.is_(None),
            )
        )
    ).all()
    commodities = [
        {
            "id": r.id,
            "source": r.source,
            "source_record_id": r.source_record_id,
            "description": r.description,
        }
        for r in commodity_rows
    ]
    if not commodities:
        return [], {}, {}

    ids = [c["id"] for c in commodities]

    alias_rows = (
        await db.execute(
            select(
                SanctionedCommodityAlias.sanctioned_commodity_id,
                SanctionedCommodityAlias.alias,
            ).where(SanctionedCommodityAlias.sanctioned_commodity_id.in_(ids))
        )
    ).all()
    aliases_by_cid: dict[int, list[str]] = {}
    for cid, alias in alias_rows:
        aliases_by_cid.setdefault(cid, []).append(alias)

    cr_rows = (
        await db.execute(
            select(
                CountryRule.sanctioned_commodity_id,
                CountryRule.origin_iso,
                CountryRule.destination_iso,
                CountryRule.restriction_type,
                CountryRule.conditions,
                CountryRule.active,
            ).where(CountryRule.sanctioned_commodity_id.in_(ids))
        )
    ).all()
    crs_by_cid: dict[int, list[dict[str, Any]]] = {}
    for r in cr_rows:
        if not r.active:
            continue
        crs_by_cid.setdefault(r.sanctioned_commodity_id, []).append(
            {
                "origin_iso": r.origin_iso,
                "destination_iso": r.destination_iso,
                "restriction_type": r.restriction_type,
                "conditions": r.conditions,
            }
        )
    # Commodities with no country_rule still produce one global-scope rule
    # (origin=None, destination=None) so the cross-encoder can fire on
    # source records that ship without a country_rule companion (e.g. OFAC SDN
    # entries published as party-only, BIS CCL entries without HS crosswalk).
    for c in commodities:
        crs_by_cid.setdefault(c["id"], [{"origin_iso": None, "destination_iso": None, "restriction_type": None, "conditions": None}])

    return commodities, aliases_by_cid, crs_by_cid


async def materialize_for_source(
    db: AsyncSession, source: str
) -> dict[str, int]:
    """UPSERT one ScreeningRule per (sanctioned_commodity × country_rule) for source.

    No-op (returns zero counters) when `sanctions_rule_config.enabled` is false
    or the config row is missing. Orphaned previously-materialized rows for this
    source (no longer derivable from current data) are soft-deactivated.
    """
    cfg = await get_config(db, source)
    if cfg is None or not cfg["enabled"]:
        log.info("materialize_rules.skip", source=source, reason="disabled")
        return {"created": 0, "updated": 0, "deactivated": 0, "kept": 0}

    commodities, aliases_by_cid, crs_by_cid = await _fetch_source_data(db, source)
    if not commodities:
        log.info("materialize_rules.no_commodities", source=source)
        return {"created": 0, "updated": 0, "deactivated": 0, "kept": 0}

    # Build every rule field row + collect the unique phrase set for batched embedding.
    rule_dicts: list[dict[str, Any]] = []
    for c in commodities:
        aliases = aliases_by_cid.get(c["id"], [])
        for cr in crs_by_cid[c["id"]]:
            fields = build_rule_fields(c, aliases, cr, cfg)
            if fields is not None:
                rule_dicts.append(fields)

    if not rule_dicts:
        log.info("materialize_rules.empty_after_build", source=source)
        return {"created": 0, "updated": 0, "deactivated": 0, "kept": 0}

    # Embed primary phrases in a single batched encode (off-thread).
    embedder = lazy_embedder()
    primary_phrases = [r["phrase"] for r in rule_dicts]
    vectors = await asyncio.to_thread(embedder.encode_batch, primary_phrases)

    created_by = f"sanctions_source:{source}"

    # Snapshot of what's currently materialized for this source so we can count
    # creates vs updates and identify orphans to soft-deactivate.
    prior_rows = (
        await db.execute(
            select(ScreeningRule.name, ScreeningRule.active).where(
                ScreeningRule.created_by == created_by
            )
        )
    ).all()
    prior_names: set[str] = {n for n, _ in prior_rows}
    prior_active: set[str] = {n for n, active in prior_rows if active}

    seen_names: set[str] = set()
    n_applied = 0

    # UPSERT loop. The partial unique index `uq_screening_rule_materialized`
    # is `(created_by, name) WHERE created_by LIKE 'sanctions_source:%'`.
    for fields, vec in zip(rule_dicts, vectors, strict=True):
        seen_names.add(fields["name"])
        embedding = vec.tolist() if vec is not None else None
        stmt = insert(ScreeningRule).values(
            name=fields["name"],
            phrase=fields["phrase"],
            phrase_group=fields["phrase_group"],
            threshold=fields["threshold"],
            conditions=fields["conditions"],
            origin_iso=fields["origin_iso"],
            destination_iso=fields["destination_iso"],
            active=True,
            version=1,
            created_by=created_by,
            embedding=embedding,
        )
        upsert = stmt.on_conflict_do_update(
            index_elements=["created_by", "name"],
            index_where=ScreeningRule.created_by.like("sanctions_source:%"),
            set_={
                "phrase": stmt.excluded.phrase,
                "phrase_group": stmt.excluded.phrase_group,
                "threshold": stmt.excluded.threshold,
                "conditions": stmt.excluded.conditions,
                "origin_iso": stmt.excluded.origin_iso,
                "destination_iso": stmt.excluded.destination_iso,
                "active": True,
                "embedding": stmt.excluded.embedding,
            },
        )
        await db.execute(upsert)
        n_applied += 1

    n_created = len(seen_names - prior_names)
    n_updated = len(seen_names & prior_names)

    # Soft-deactivate orphans: previously-materialized rows whose name was not
    # produced by this run. Skipped when prior_active is empty (first run).
    orphan_names = prior_active - seen_names
    n_deactivated = 0
    if orphan_names:
        deactivate_stmt = (
            update(ScreeningRule)
            .where(
                ScreeningRule.created_by == created_by,
                ScreeningRule.active.is_(True),
                ScreeningRule.name.in_(list(orphan_names)),
            )
            .values(active=False)
        )
        deact_result = await db.execute(deactivate_stmt)
        n_deactivated = int(deact_result.rowcount or 0)

    await db.commit()

    log.info(
        "materialize_rules.done",
        source=source,
        created=n_created,
        updated=n_updated,
        deactivated=n_deactivated,
        applied=n_applied,
        strategy=cfg["phrase_strategy"],
    )
    return {
        "created": int(n_created),
        "updated": int(n_updated),
        "deactivated": int(n_deactivated),
        "applied": int(n_applied),
    }


async def maybe_materialize_after_ingest(db: AsyncSession, source: str) -> dict[str, int] | None:
    """Convenience for the refdata worker: no-op if the source has no config row
    or `enabled=False`. Returns the counts dict on success, None when skipped.
    """
    cfg = await get_config(db, source)
    if cfg is None or not cfg["enabled"]:
        return None
    return await materialize_for_source(db, source)
