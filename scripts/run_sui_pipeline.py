"""
Standalone runner för sui_to_motherduck pipeline.

Kör bara om det finns ny data. Ny-data-kontroll sker på två sätt:
  - Lokalt / Hetzner cron: jämför Minio LastModified mot state/sui_last_run.txt
  - GitHub Actions (--max-age-hours N): kör bara om CSV är yngre än N timmar

Användning:
  python3 scripts/run_sui_pipeline.py                   # state-filbaserad kontroll
  python3 scripts/run_sui_pipeline.py --force           # kör alltid
  python3 scripts/run_sui_pipeline.py --max-age-hours 25  # CI-mode: körs bara om CSV < 25h gammal
"""
from __future__ import annotations

import argparse
import os
import sys
import types
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Mage-mock (måste ligga före imports från mage_project)
# ---------------------------------------------------------------------------
_mage = types.ModuleType("mage_ai")
_mage.settings = types.ModuleType("mage_ai.settings")
_mage.settings.repo = types.ModuleType("mage_ai.settings.repo")
_mage.settings.repo.get_repo_path = lambda: str(
    Path(__file__).resolve().parent.parent / "mage_project"
)
_mage.data_preparation = types.ModuleType("mage_ai.data_preparation")
_mage.data_preparation.decorators = types.ModuleType("mage_ai.data_preparation.decorators")
_mage.data_preparation.decorators.data_loader = lambda f: f
_mage.data_preparation.decorators.data_exporter = lambda f: f
sys.modules.update({
    "mage_ai": _mage,
    "mage_ai.settings": _mage.settings,
    "mage_ai.settings.repo": _mage.settings.repo,
    "mage_ai.data_preparation": _mage.data_preparation,
    "mage_ai.data_preparation.decorators": _mage.data_preparation.decorators,
})

# ---------------------------------------------------------------------------
# Paths & env
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "mage_project"))


def _load_env():
    env = REPO_ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())


_load_env()

# ---------------------------------------------------------------------------
# State (lokal fil – används inte i CI-mode)
# ---------------------------------------------------------------------------
STATE_FILE = REPO_ROOT / "mage_project/state/sui_last_run.txt"
BUCKET = "sui-scrape"
PREFIX = "parsed/"
CSV_FILES = ["games", "player_stats", "goalie_stats", "team_stats", "goals", "penalties"]


def _minio_client():
    import boto3
    endpoint = os.environ.get("MINIO_ENDPOINT", "").strip()
    if endpoint and not endpoint.startswith("http"):
        endpoint = f"https://{endpoint}"
    return boto3.client(
        "s3",
        endpoint_url=endpoint or None,
        aws_access_key_id=os.environ.get("MINIO_ACCESS_KEY", ""),
        aws_secret_access_key=os.environ.get("MINIO_SECRET_KEY", ""),
        region_name="us-east-1",
    )


def _latest_minio_ts(client) -> datetime | None:
    """Return the most recent LastModified timestamp across all CSVs."""
    latest = None
    for name in CSV_FILES:
        try:
            resp = client.head_object(Bucket=BUCKET, Key=f"{PREFIX}{name}.csv")
            ts = resp["LastModified"]
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if latest is None or ts > latest:
                latest = ts
        except Exception as e:
            print(f"[sui runner] WARNING: head_object {name}.csv: {e}")
    return latest


def _read_last_run() -> datetime | None:
    if STATE_FILE.exists():
        val = STATE_FILE.read_text().strip()
        try:
            return datetime.fromisoformat(val)
        except ValueError:
            pass
    return None


def _write_last_run(ts: datetime):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(ts.isoformat())


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def run(force: bool = False, max_age_hours: int | None = None):
    import time
    t0 = time.time()

    client = _minio_client()

    latest_ts = _latest_minio_ts(client)
    if latest_ts is None:
        print("[sui runner] Inga CSVer hittades i Minio – avslutar")
        return

    # ── Ny-data-kontroll ─────────────────────────────────────────────────────
    if force:
        print("[sui runner] --force satt – kör oavsett timestamp")

    elif max_age_hours is not None:
        # CI-mode: kör bara om CSVen är uppdaterad de senaste N timmarna
        age = datetime.now(timezone.utc) - latest_ts
        if age > timedelta(hours=max_age_hours):
            print(
                f"[sui runner] CSV {latest_ts.strftime('%Y-%m-%d %H:%M UTC')} är "
                f"{age.total_seconds()/3600:.1f}h gammal (gräns {max_age_hours}h) – hoppar över"
            )
            return
        print(
            f"[sui runner] CSV uppdaterad {latest_ts.strftime('%Y-%m-%d %H:%M UTC')} "
            f"({age.total_seconds()/3600:.1f}h sedan) – kör pipeline"
        )

    else:
        # Lokal mode: jämför mot state-fil
        last_run = _read_last_run()
        if last_run is not None and latest_ts <= last_run:
            print(
                f"[sui runner] Ingen ny data (CSV: {latest_ts.strftime('%Y-%m-%d %H:%M UTC')}, "
                f"senaste körning: {last_run.strftime('%Y-%m-%d %H:%M UTC')}) – hoppar över"
            )
            return
        print(
            f"[sui runner] Ny data: CSV={latest_ts.strftime('%Y-%m-%d %H:%M UTC')}"
            + (f", förra körning={last_run.strftime('%Y-%m-%d %H:%M UTC')}" if last_run else ", första körning")
        )

    # ── Kör pipeline ─────────────────────────────────────────────────────────
    from data_loaders.load_csvs_from_minio import load_csvs_from_minio
    from data_exporters.upsert_sui_to_motherduck import upsert_sui_to_motherduck

    print("\n[sui runner] STEG 1/2 – Laddar CSVer från Minio")
    data = load_csvs_from_minio()

    if not data:
        print("[sui runner] Inga DataFrames laddades – avslutar utan att uppdatera state")
        return

    print("\n[sui runner] STEG 2/2 – Upsertar till MotherDuck (sui.*)")
    upsert_sui_to_motherduck(data)

    # Uppdatera state-filen (no-op i CI där mappen inte persists)
    try:
        _write_last_run(latest_ts)
    except Exception:
        pass

    elapsed = round(time.time() - t0, 1)
    print(f"\n[sui runner] Klar på {elapsed}s. CSV-timestamp: {latest_ts.isoformat()}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SUI hockey pipeline runner")
    parser.add_argument("--force", action="store_true",
                        help="Kör även om ingen ny data finns")
    parser.add_argument("--max-age-hours", type=int, default=None, metavar="N",
                        help="CI-mode: kör bara om CSV är yngre än N timmar (ignorerar state-fil)")
    args = parser.parse_args()
    run(force=args.force, max_age_hours=args.max_age_hours)
