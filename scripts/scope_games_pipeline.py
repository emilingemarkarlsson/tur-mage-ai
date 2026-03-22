#!/usr/bin/env python3
"""
Visar exakt vilken data games_pipeline kommer att hämta från Hetzner S3.
Använder samma prefix och GAMES_START_DATE som load_games_incremental.
Kör från projektroten: python scripts/scope_games_pipeline.py
I Docker: docker exec tur-mage-ai-mage-1 bash -c "cd /home/src && python scripts/scope_games_pipeline.py"
"""
import os
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"), override=True)
except Exception:
    pass

# Samma som i load_games_incremental
PREFIX = "nhl-data-reorganized/games/by_date/"
# State i container; lokalt kan samma fil finnas under repo
STATE_PATH_CONTAINER = "/home/src/mage_project/state/last_games_date.txt"
STATE_PATH_LOCAL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mage_project", "state", "last_games_date.txt")


def main():
    sys.path.insert(0, os.path.join(ROOT, "mage_project"))
    from utils.s3_utils import get_s3_bucket, get_s3_client, list_keys

    client = get_s3_client()
    bucket = get_s3_bucket()
    if not bucket:
        print("ERROR: S3 bucket not configured (HETZNER_BUCKET or S3_BUCKET)")
        sys.exit(1)

    start_date = os.getenv("GAMES_START_DATE", "").strip()
    if not start_date:
        start_date = "2010-01-01"
        print("GAMES_START_DATE inte satt – antar 2010-01-01\n")

    games_year = (os.getenv("GAMES_YEAR") or "").strip()
    # games_year.txt har företräde (samma som i loadern)
    for state_dir in (
        os.path.join(ROOT, "mage_project", "state"),
        os.path.join(ROOT, "state"),
    ):
        txt_path = os.path.join(state_dir, "games_year.txt")
        if os.path.isfile(txt_path):
            try:
                import re
                with open(txt_path, "r", encoding="utf-8-sig") as f:
                    raw = (f.read() or "").strip()
                m = re.search(r"(19|20)\d{2}", raw)
                if m:
                    games_year = m.group(0)
                    print(f"games_year.txt hittad: {games_year} (används istället för .env)\n")
            except Exception:
                pass
            break
    print(f"Bucket: {bucket}")
    print(f"Prefix:  {PREFIX}")
    print(f"GAMES_START_DATE: {start_date}" + (f"  GAMES_YEAR: {games_year}" if games_year else ""))

    # Räkna filer per datum (endast .json, exkl. games_summary.json)
    date_counts = defaultdict(int)
    total_files = 0
    for key in list_keys(client, bucket, PREFIX):
        if not key.startswith(PREFIX) or not key.endswith(".json") or key.endswith("games_summary.json"):
            continue
        rest = key[len(PREFIX):].strip("/")
        parts = rest.split("/", 1)
        if not parts or len(parts[0]) != 10:
            continue
        d = parts[0]
        if d < start_date:
            continue
        date_counts[d] += 1
        total_files += 1

    dates_sorted = sorted(date_counts.keys())
    if not dates_sorted:
        print("\nInga matchfiler hittades efter filtrering. Kontrollera att det finns data under by_date/ och att GAMES_START_DATE matchar.")
        sys.exit(1)

    first_date = dates_sorted[0]
    last_date = dates_sorted[-1]
    num_dates = len(dates_sorted)

    if games_year:
        dates_in_year = [d for d in dates_sorted if len(d) >= 4 and d[:4] == games_year]
        files_in_year = sum(date_counts[d] for d in dates_in_year)
        print(f"\n--- Omfattning (GAMES_YEAR={games_year}) ---")
        print(f"  Datum i året: {len(dates_in_year)}, filer: {files_in_year}")
        if dates_in_year:
            print(f"  Från {dates_in_year[0]} till {dates_in_year[-1]}")
    print(f"\n--- Omfattning (efter GAMES_START_DATE) ---")
    print(f"  Datum från:  {first_date}")
    print(f"  Datum till: {last_date}")
    print(f"  Antal datum med minst en match: {num_dates}")
    print(f"  Totalt antal matchfiler (.json, exkl. games_summary): {total_files}")

    # Kolla incremental state (container-path eller lokal mage_project/state)
    last_run_date = None
    for state_path in (STATE_PATH_CONTAINER, STATE_PATH_LOCAL):
        if os.path.isfile(state_path):
            with open(state_path, "r", encoding="utf-8") as f:
                last_run_date = f.read().strip() or None
            break
    if last_run_date:
        dates_after_state = [d for d in dates_sorted if d > last_run_date]
        files_after_state = sum(date_counts[d] for d in dates_after_state)
        print(f"\n  *** STATE-FIL FINNS: last_games_date = {last_run_date} ***")
        if not dates_after_state:
            print(f"  Nästa körning i Mage skulle hämta 0 nya datum (state är redan senaste).")
            print(f"  Om Silver/Gold saknar 2010–2024 har en tidigare körning bara laddat del av spannet; state sparades ändå till senaste datum.")
        else:
            print(f"  Vid nästa körning hämtas ENDAST datum > {last_run_date}: {len(dates_after_state)} datum, ca {files_after_state} filer.")
        print("\n  För FULL laddning 2010–2026: rensa state och kör games_pipeline igen:")
        print("    ./scripts/reset_full_games_load.sh")
        print("  eller: docker exec -i tur-mage-ai-mage-1 rm -f /home/src/mage_project/state/last_games_date.txt")
    else:
        print("\n  Ingen state-fil – nästa körning av games_pipeline blir FULL (alla datum ovan).")
        print("  Säkerställ GAMES_START_DATE=2010-01-01 (eller 2010-10-01) i .env.")

    # Kort statistik per år
    by_year = defaultdict(int)
    for d in dates_sorted:
        by_year[d[:4]] += date_counts[d]
    print("\n  Filer per år (urval):")
    for year in sorted(by_year.keys())[:5]:
        print(f"    {year}: {by_year[year]} filer")
    if len(by_year) > 5:
        print(f"    ... och {len(by_year) - 5} år till")
    print("\nKlar. games_pipeline använder denna källa (by_date); för full laddning, nollställ state innan körning.")


if __name__ == "__main__":
    main()
