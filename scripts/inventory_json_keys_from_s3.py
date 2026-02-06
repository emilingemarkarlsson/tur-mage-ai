#!/usr/bin/env python3
"""
Läser sample-filer från S3 från olika år/säsonger och skriver ut alla nyckelvägar.
Mer statistik har tillkommit senaste åren – därför analyseras både äldre och nyare filer
så att vi får unionen av alla fält och kan plocka ut all data i pipelinen.

Kör (från projektroten, med .env för S3):
  python scripts/inventory_json_keys_from_s3.py
  python scripts/inventory_json_keys_from_s3.py --out documentation/JSON_KEY_INVENTORY.md
"""
import os
import re
import sys
from collections import defaultdict

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_mage = os.path.join(_root, "mage_project")
sys.path.insert(0, _mage)
os.chdir(_mage)
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_root, ".env"))
except Exception:
    pass

# Prefix → beskrivning
S3_SAMPLES = [
    ("nhl-data/basic/teams/all_teams.json", "teams", None),
    ("nhl-data/basic/players/all_players.json", "players", None),
    ("nhl-data/basic/standings/", "standings", "season"),   # league_standings_{season}.json
    ("nhl-data/basic/schedule/", "schedule", "any"),
    ("nhl-data/helpers/", "helpers", "season"),            # game_ids_{season}.json
    ("nhl-data/misc/countries.json", "countries", None),
    ("nhl-data/misc/glossary.json", "glossary", None),
    ("nhl-data/misc/draft_year_and_rounds.json", "draft", None),
    ("nhl-data/basic/teams/rosters/", "rosters", "season"), # {season}/all_rosters.json
    ("nhl-data/stats/skaters/", "skater_stats", "season"),   # summary_{season}.json
    ("nhl-data/stats/goalies/", "goalie_stats", "season"),
    ("nhl-data/stats/teams/", "team_stats", "season"),
    ("nhl-data/edge/skaters/", "edge_skaters", "season"),   # landing_{season}.json
    ("nhl-data/edge/goalies/", "edge_goalies", "season"),
    ("nhl-data/edge/teams/", "edge_teams", "season"),
    ("nhl-data-reorganized/games/by_date/", "games", "date"), # {date}/{gameId}.json
]


def _all_key_paths(obj, prefix: str = "") -> list:
    """Returnerar alla nyckelvägar i ett JSON-objekt."""
    out = []
    if obj is None:
        return [f"{prefix}=null"]
    if isinstance(obj, bool):
        return [f"{prefix}=bool"]
    if isinstance(obj, (int, float)):
        return [f"{prefix}=number"]
    if isinstance(obj, str):
        return [f"{prefix}=string"]
    if isinstance(obj, list):
        if not obj:
            return [f"{prefix}=[]"]
        out.append(f"{prefix}=[array len={len(obj)}]")
        out.extend(_all_key_paths(obj[0], f"{prefix}[]"))
        return out
    if isinstance(obj, dict):
        for k, v in obj.items():
            key_path = f"{prefix}.{k}" if prefix else k
            out.append(key_path)
            out.extend(_all_key_paths(v, key_path))
        return out
    return [f"{prefix}=other"]


def _extract_season_from_key(key: str, prefix: str) -> str | None:
    """Hämtar säsong från filnamn, t.ex. summary_20242025.json -> 20242025."""
    rest = key[len(prefix):].lstrip("/")
    # summary_20242025.json, league_standings_20242025.json, landing_20242025.json, game_ids_20242025.json
    m = re.search(r"(\d{8})\.json$", rest)
    if m:
        return m.group(1)
    # rosters/20242025/all_rosters.json
    m = re.search(r"^(\d{8})/", rest)
    if m:
        return m.group(1)
    return None


def _extract_date_from_key(key: str, prefix: str) -> str | None:
    """Hämtar datum från key, t.ex. by_date/2024-01-15/2024012345.json -> 2024-01-15."""
    rest = key[len(prefix):].lstrip("/")
    # 2024-01-15/2024012345.json
    m = re.match(r"^(\d{4}-\d{2}-\d{2})/", rest)
    if m:
        return m.group(1)
    return None


def _get_sample_keys_multi_year(client, bucket: str, prefix: str, mode: str) -> list[str]:
    """
    Returnerar flera sample-nycklar så att vi får både äldre och nyare data.
    mode: None = en fil (exakt prefix), "season" = plocka från tidig och sen säsong, "date" = tidigt och sent datum, "any" = första och sista fil.
    """
    from utils.s3_utils import list_keys

    if mode is None or prefix.endswith(".json"):
        return [prefix] if prefix.endswith(".json") else []

    keys = [
        k for k in list_keys(client, bucket, prefix)
        if k.endswith(".json") and "games_summary" not in k
    ]
    if not keys:
        return []

    if mode == "season":
        by_season = defaultdict(list)
        for k in keys:
            s = _extract_season_from_key(k, prefix)
            if s:
                by_season[s].append(k)
        if not by_season:
            return [keys[0]]
        seasons_sorted = sorted(by_season.keys())
        out = []
        if seasons_sorted:
            out.append(by_season[seasons_sorted[0]][0])
        if len(seasons_sorted) > 1 and by_season[seasons_sorted[-1]][0] not in out:
            out.append(by_season[seasons_sorted[-1]][0])
        return out if out else [keys[0]]

    if mode == "date":
        by_date = defaultdict(list)
        for k in keys:
            d = _extract_date_from_key(k, prefix)
            if d:
                by_date[d].append(k)
        if not by_date:
            return [keys[0]]
        dates_sorted = sorted(by_date.keys())
        out = []
        if dates_sorted:
            out.append(by_date[dates_sorted[0]][0])
        if len(dates_sorted) > 1 and by_date[dates_sorted[-1]][0] not in out:
            out.append(by_date[dates_sorted[-1]][0])
        return out if out else [keys[0]]

    # any: första och sista i listan (ofta sorterad)
    if len(keys) >= 2:
        return [keys[0], keys[-1]]
    return [keys[0]]


def main():
    out_path = os.path.join(_root, "documentation", "JSON_KEY_INVENTORY.md")
    if "--out" in sys.argv:
        i = sys.argv.index("--out")
        if i + 1 < len(sys.argv):
            out_path = sys.argv[i + 1]

    try:
        from utils.s3_utils import get_s3_bucket, get_s3_client, read_json
    except ImportError:
        print("Kräver utils.s3_utils (kör från projektrot eller Mage-containern)")
        sys.exit(1)

    client = get_s3_client()
    bucket = get_s3_bucket()
    if not bucket:
        print("S3 bucket inte konfigurerad. Avslutar.")
        sys.exit(1)

    lines = [
        "# JSON-nyckelinventering (sample från flera år)",
        "",
        "Genererat av `scripts/inventory_json_keys_from_s3.py`. För varje källtyp har **flera filer från olika år/säsonger** analyserats,",
        "eftersom mer statistik tillkommit senaste åren. Listan visar **unionen** av alla nyckelvägar så att pipelinen kan plocka ut all data.",
        "",
        "---",
        "",
    ]

    for prefix, label, mode in S3_SAMPLES:
        lines.append(f"## {label}")
        lines.append(f"**Prefix:** `{prefix}`")

        sample_keys = _get_sample_keys_multi_year(client, bucket, prefix, mode)
        if not sample_keys:
            lines.append("*Ingen .json hittad.*")
            lines.append("")
            continue

        all_paths = set()
        samples_used = []
        for key in sample_keys:
            samples_used.append(key)
            try:
                data = read_json(client, bucket, key)
                paths = _all_key_paths(data)
                for p in paths:
                    if "=number" in p or "=string" in p or "=bool" in p or "=null" in p:
                        continue
                    all_paths.add(p)
            except Exception as e:
                lines.append(f"*Fel vid läsning av {key}: {e}*")

        if len(sample_keys) > 1:
            lines.append("**Analyserade filer (olika år/säsonger):**")
            for k in sample_keys:
                lines.append(f"- `{k}`")
        else:
            lines.append(f"**Sample:** `{sample_keys[0]}`")

        paths_sorted = sorted(all_paths)
        lines.append("**Nyckelvägar (union från alla samples):**")
        for p in paths_sorted[:250]:
            lines.append(f"- `{p}`")
        if len(paths_sorted) > 250:
            lines.append(f"- ... och {len(paths_sorted) - 250} fler (totalt {len(paths_sorted)} vägar)")
        lines.append("")

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"Skrev: {out_path}")
    print("Filer från olika år har analyserats; jämför nyckelvägarna med transform_*.py och export_*.py.")


if __name__ == "__main__":
    main()
