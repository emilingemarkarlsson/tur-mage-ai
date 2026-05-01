"""
Scrape Swedish hockey games from stats.swehockey.se → Hetzner S3.

Modes (via runtime variable `swe_scrape_mode`):
  daily       – Scrapar gårdagens + dagens matcher (standard vid schemalagd körning)
  backfill    – Scrapar ett datumintervall: swe_date_from → swe_date_to
  yesterday   – Enbart gårdagen (CI-fallback)

Runtime variables:
  swe_scrape_mode   (str)  – "daily" | "backfill" | "yesterday" (default: "daily")
  swe_date_from     (str)  – YYYY-MM-DD, krävs vid mode=backfill
  swe_date_to       (str)  – YYYY-MM-DD, krävs vid mode=backfill

Env vars (sätts i Coolify/docker-compose):
  SWE_ENDPOINT      – Hetzner S3 endpoint (hel1.your-objectstorage.com)
  SWE_ACCESS_KEY    – S3 access key för swehockey-data bucket
  SWE_SECRET_KEY    – S3 secret key
  SWE_BUCKET        – Bucket-namn (default: swehockey-data)
"""

import os
import sys
import importlib
from pathlib import Path
from datetime import date, timedelta

if "data_loader" not in globals():
    from mage_ai.data_preparation.decorators import data_loader

# ---------------------------------------------------------------------------
# Lägg till swe_scraper i Python-path
# ---------------------------------------------------------------------------
_utils_dir = Path(__file__).resolve().parent.parent / "utils"
if str(_utils_dir) not in sys.path:
    sys.path.insert(0, str(_utils_dir))

# Installera minio om det saknas (undviker att behöva bygga om Docker-imagen)
try:
    import minio  # noqa: F401
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "minio>=7.2.0", "-q"])
    import minio  # noqa: F401


def _get_runtime_var(kwargs: dict, key: str) -> str | None:
    """Hämtar runtime-variabel från Mage kwargs."""
    val = (
        kwargs.get(key)
        or kwargs.get("context", {}).get(key)
        or kwargs.get("variables", {}).get(key)
    )
    return str(val).strip() if val else None


def _build_storage():
    """Bygger storage-objekt med SWE_* env vars (faller tillbaka på MINIO_*)."""
    # Importera lazily efter att minio är installerat
    from swe_scraper.storage import HybridStorage
    try:
        from minio import Minio
    except ImportError:
        raise RuntimeError("minio-paketet saknas")

    endpoint = (
        os.getenv("SWE_ENDPOINT")
        or os.getenv("MINIO_ENDPOINT")
    )
    access_key = (
        os.getenv("SWE_ACCESS_KEY")
        or os.getenv("MINIO_ACCESS_KEY")
    )
    secret_key = (
        os.getenv("SWE_SECRET_KEY")
        or os.getenv("MINIO_SECRET_KEY")
    )
    bucket = (
        os.getenv("SWE_BUCKET")
        or os.getenv("MINIO_BUCKET_NAME")
        or "swehockey-data"
    )
    secure = os.getenv("SWE_SECURE", "true").lower() == "true"

    if not endpoint or not access_key or not secret_key:
        print("[swe_scrape] VARNING: SWE_*/MINIO_* credentials saknas – kör utan S3-lagring")
        return None, bucket

    # Rensa bort https:// prefix om det finns
    endpoint_clean = endpoint.replace("https://", "").replace("http://", "")

    minio_client = Minio(
        endpoint_clean,
        access_key=access_key,
        secret_key=secret_key,
        secure=secure,
    )

    # Sätt bucket-namn på klienten (HybridStorage-kompatibelt)
    minio_client._bucket_name = bucket

    from swe_scraper.storage import MinIOStorage
    minio_storage = MinIOStorage(client=minio_client, bucket_name=bucket)

    data_dir = Path(os.getenv("DATA_LAKE_PATH", "/home/src/mage_project/data_lake")).parent / "swe_scraped"
    data_dir.mkdir(parents=True, exist_ok=True)

    storage = HybridStorage(minio_storage=minio_storage, local_dir=data_dir)
    return storage, bucket


@data_loader
def scrape_swe_games(*args, **kwargs):
    """
    Returnerar dict med scrape-resultat:
      {
        "mode": str,
        "dates_attempted": int,
        "games_found": int,
        "games_scraped": int,
        "errors": list[str],
        "date_from": str,
        "date_to": str,
      }
    """
    from swe_scraper.orchestrator import ScrapingOrchestrator

    mode = _get_runtime_var(kwargs, "swe_scrape_mode") or "daily"
    date_from = _get_runtime_var(kwargs, "swe_date_from")
    date_to = _get_runtime_var(kwargs, "swe_date_to")

    storage, bucket = _build_storage()

    data_dir = Path(os.getenv("DATA_LAKE_PATH", "/home/src/mage_project/data_lake")).parent / "swe_scraped"
    orchestrator = ScrapingOrchestrator(data_dir=data_dir, storage=storage)

    print(f"[swe_scrape] Mode: {mode} | Bucket: {bucket}")

    if mode == "backfill":
        if not date_from or not date_to:
            raise ValueError("swe_date_from och swe_date_to krävs vid mode=backfill")
        print(f"[swe_scrape] Backfill: {date_from} → {date_to}")
        result = orchestrator.scrape_date_range(
            start_date=date_from,
            end_date=date_to,
            fetch_details=True,
            resume=True,
        )
        dates_attempted = len(result.get("results", [result]))
        games_found = result.get("total_games_found", result.get("games_found", 0))
        games_scraped = result.get("total_games_scraped", result.get("games_scraped", 0))
        errors = result.get("errors", [])
        actual_from = date_from
        actual_to = date_to

    elif mode == "yesterday":
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        print(f"[swe_scrape] Scrapar gårdagen: {yesterday}")
        result = orchestrator.scrape_date(date_str=yesterday, fetch_details=True)
        dates_attempted = 1
        games_found = result.get("games_found", 0)
        games_scraped = result.get("games_scraped", 0)
        errors = result.get("errors", [])
        actual_from = actual_to = yesterday

    else:  # daily (default)
        today = date.today().isoformat()
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        print(f"[swe_scrape] Daglig körning: {yesterday} + {today}")
        dates_attempted = 0
        games_found = 0
        games_scraped = 0
        errors = []
        for d in [yesterday, today]:
            r = orchestrator.scrape_date(date_str=d, fetch_details=True)
            dates_attempted += 1
            games_found += r.get("games_found", 0)
            games_scraped += r.get("games_scraped", 0)
            errors.extend(r.get("errors", []))
        actual_from = yesterday
        actual_to = today

    summary = {
        "mode": mode,
        "dates_attempted": dates_attempted,
        "games_found": games_found,
        "games_scraped": games_scraped,
        "errors": errors[:10],  # Begränsa till 10 för logg-läsbarhet
        "date_from": actual_from,
        "date_to": actual_to,
    }

    print(f"[swe_scrape] Klar: {games_scraped} spel scrapat ({dates_attempted} datum)")
    if errors:
        print(f"[swe_scrape] {len(errors)} fel: {errors[:3]}")

    return summary
