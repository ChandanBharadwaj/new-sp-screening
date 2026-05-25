"""First-boot data seed.

Downloads the actual publisher data for the subset of sources that expose a
stable direct URL, into the on-disk paths the ingesters already consume. Run
this before the app comes up (the Dockerfile entrypoint does so automatically);
re-running is idempotent — files newer than MAX_AGE_DAYS are kept.

We never synthesize data. Sources whose publishers only ship through navigation
pages, license-gated portals, or token URLs (Schedule B, WCO, BIS CCL,
EU consolidated FSF, EU dual-use Annex I, EU Russia annexes, ITAR/USML) are
*reported* with the publisher URL and destination path so the operator can drop
them manually and re-run; bootstrap never silently passes on those.

Run modes:
    python scripts/bootstrap_data.py                # download missing/stale; report manual gaps
    python scripts/bootstrap_data.py --best-effort  # never exit non-zero (Dockerfile uses this)
    python scripts/bootstrap_data.py --force        # re-download even if cache is fresh
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

try:
    import httpx
except ImportError:  # pragma: no cover — bootstrap must be self-contained at import time
    httpx = None  # type: ignore[assignment]

DATA_ROOT = Path("data")
MAX_AGE_DAYS_DEFAULT = 7
USER_AGENT = "screening-bootstrap/1.0 (+https://example.invalid)"


def _log(event: str, **fields: object) -> None:
    line = {"event": event, **fields}
    print(json.dumps(line, default=str), flush=True)


# ---------------------------------------------------------------------------
# Auto-downloadable sources
# ---------------------------------------------------------------------------


@dataclass
class DownloadJob:
    name: str
    url: str
    dest: Path
    # Some publishers gzip on the wire — we don't decode; the parser side handles it.
    min_size_bytes: int = 1024


# OFAC SDN: Treasury hosts stable CSVs at the legacy URL — sdn.csv, add.csv, alt.csv.
OFAC_BASE = "https://www.treasury.gov/ofac/downloads"

# UN Consolidated Sanctions: the same URL the existing UN ingester uses.
UN_XML_URL = "https://scsanctions.un.org/resources/xml/en/consolidated.xml"

# US HTS export endpoint. Must match HTS_URL_TEMPLATE in app/refdata/hts/ingest.py,
# and the destination must match the cache path that ingester checks
# (data/hts/htsdata_latest.json), or the seed is dead weight — the ingester would
# just re-download.
HTS_URL = "https://hts.usitc.gov/reststop/exportList?from=0100000000&to=9999999999&format=JSON&styles=false"

JOBS: list[DownloadJob] = [
    DownloadJob(
        name="HTS",
        url=HTS_URL,
        dest=DATA_ROOT / "hts" / "htsdata_latest.json",
        min_size_bytes=200_000,  # full HTS JSON is multi-megabyte
    ),
    DownloadJob(
        name="UN_CONSOLIDATED",
        url=UN_XML_URL,
        dest=DATA_ROOT / "sanctions" / "un_consolidated.xml",
    ),
    DownloadJob(
        name="OFAC_SDN",
        url=f"{OFAC_BASE}/sdn.csv",
        dest=DATA_ROOT / "sanctions" / "ofac" / "sdn.csv",
    ),
    DownloadJob(
        name="OFAC_SDN_ADD",
        url=f"{OFAC_BASE}/add.csv",
        dest=DATA_ROOT / "sanctions" / "ofac" / "add.csv",
        min_size_bytes=512,
    ),
    DownloadJob(
        name="OFAC_SDN_ALT",
        url=f"{OFAC_BASE}/alt.csv",
        dest=DATA_ROOT / "sanctions" / "ofac" / "alt.csv",
        min_size_bytes=512,
    ),
]


def _is_fresh(dest: Path, max_age_days: int) -> bool:
    if not dest.exists():
        return False
    if dest.stat().st_size <= 0:
        return False
    age_s = time.time() - dest.stat().st_mtime
    return age_s < max_age_days * 86400


def _atomic_write(dest: Path, body: bytes) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(dest.parent), prefix=".dl-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(body)
        os.replace(tmp_path, dest)
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


def _download_one(
    job: DownloadJob, *, force: bool, max_age_days: int, get_bytes: Callable[[str], bytes]
) -> dict[str, object]:
    if not force and _is_fresh(job.dest, max_age_days):
        return {"name": job.name, "status": "fresh", "path": str(job.dest)}
    try:
        body = get_bytes(job.url)
    except Exception as e:
        return {"name": job.name, "status": "error", "path": str(job.dest), "error": str(e)}
    if len(body) < job.min_size_bytes:
        return {
            "name": job.name,
            "status": "too_small",
            "path": str(job.dest),
            "bytes": len(body),
            "min_bytes": job.min_size_bytes,
        }
    _atomic_write(job.dest, body)
    return {
        "name": job.name,
        "status": "downloaded",
        "path": str(job.dest),
        "bytes": len(body),
    }


def _http_get(url: str) -> bytes:
    if httpx is None:
        raise RuntimeError("httpx is not installed in this environment")
    headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    with httpx.Client(timeout=120, headers=headers, follow_redirects=True) as c:
        r = c.get(url)
        r.raise_for_status()
        return r.content


# ---------------------------------------------------------------------------
# Manual-fetch sources — surface, never synthesize
# ---------------------------------------------------------------------------


@dataclass
class ManualSource:
    name: str
    publisher_url: str
    dest: Path
    why_manual: str


MANUAL_SOURCES: list[ManualSource] = [
    ManualSource(
        name="ScheduleB",
        publisher_url="https://www.census.gov/foreign-trade/schedules/b/",
        dest=DATA_ROOT / "schedule_b" / "schedule_b.csv",
        why_manual="Census publishes versioned ZIPs through a navigation page; direct CSV URL changes per release.",
    ),
    ManualSource(
        name="WCO",
        publisher_url="https://www.wcoomd.org/en/topics/nomenclature/instrument-and-tools/hs-nomenclature-2022-edition.aspx",
        dest=DATA_ROOT / "taxonomy" / "wco_hs_2022.xlsx",
        why_manual="License-gated XLSX behind WCO portal login.",
    ),
    ManualSource(
        name="BIS_CCL",
        publisher_url="https://www.bis.doc.gov/index.php/regulations/commerce-control-list-ccl",
        dest=DATA_ROOT / "sanctions" / "bis_ccl.csv",
        why_manual="CCL published as PDF supplements to the EAR; no structured CSV/XLSX feed.",
    ),
    ManualSource(
        name="EU_CONSOLIDATED",
        publisher_url="https://webgate.ec.europa.eu/europeaid/fsd/fsf/public/",
        dest=DATA_ROOT / "sanctions" / "eu_consolidated.xml",
        why_manual="EU FSF requires a per-requester token URL.",
    ),
    ManualSource(
        name="EU_DUAL_USE",
        publisher_url="https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX%3A02021R0821",
        dest=DATA_ROOT / "sanctions" / "eu_dual_use_annex_i.xlsx",
        why_manual="Published as a CELEX HTML legal page; structured XLSX is operator-extracted.",
    ),
    ManualSource(
        name="EU_RUSSIA",
        publisher_url="https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX%3A02014R0833",
        dest=DATA_ROOT / "sanctions" / "eu_russia_annex.xlsx",
        why_manual="Published as a CELEX HTML legal page; structured XLSX is operator-extracted.",
    ),
    ManualSource(
        name="ITAR_USML",
        publisher_url="https://www.ecfr.gov/current/title-22/chapter-I/subchapter-M/part-121",
        dest=DATA_ROOT / "sanctions" / "itar" / "usml.csv",
        why_manual="Published as text in 22 CFR §121; structured CSV is operator-curated.",
    ),
]


def _missing_manual_sources() -> list[ManualSource]:
    return [m for m in MANUAL_SOURCES if not m.dest.exists()]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--best-effort",
        action="store_true",
        help="Always exit 0; never block container startup on a publisher outage.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download even when the cached file is newer than --max-age-days.",
    )
    parser.add_argument(
        "--max-age-days",
        type=int,
        default=MAX_AGE_DAYS_DEFAULT,
        help="A cached file newer than this is considered fresh and is not re-fetched.",
    )
    args = parser.parse_args(argv)

    _log(
        "bootstrap.start",
        n_jobs=len(JOBS),
        force=args.force,
        max_age_days=args.max_age_days,
    )

    results: list[dict[str, object]] = []
    any_error = False
    for job in JOBS:
        r = _download_one(
            job,
            force=args.force,
            max_age_days=args.max_age_days,
            get_bytes=_http_get,
        )
        _log("bootstrap.job", **r)
        results.append(r)
        if r.get("status") in ("error", "too_small"):
            any_error = True

    missing = _missing_manual_sources()
    if missing:
        _log(
            "bootstrap.manual_sources_missing",
            n=len(missing),
            note="upload via Admin UI; bootstrap cannot auto-download these",
        )
        for m in missing:
            _log(
                "bootstrap.manual_source",
                name=m.name,
                publisher_url=m.publisher_url,
                dest=str(m.dest),
                why=m.why_manual,
            )

    auto_ok = sum(1 for r in results if r["status"] in ("downloaded", "fresh"))
    _log(
        "bootstrap.done",
        auto_ok=auto_ok,
        auto_total=len(results),
        manual_missing=len(missing),
        any_error=any_error,
    )

    if args.best_effort:
        return 0
    return 1 if any_error else 0


if __name__ == "__main__":
    sys.exit(main())
