#!/usr/bin/env python3
"""
Analyserar Bronze (S3) och Silver (Parquet) på ett strukturerat sätt så du kan
uppdatera pipelinen och få ut all data till Silver/Gold.

Skapar:
  - documentation/DATA_STRUCTURE_REPORT.md  (läsbar rapport)
  - documentation/DATA_STRUCTURE_REPORT.json (maskinläsbar för vidare analys)

Kör från projektroten (eller i Mage-containern med cd /home/src):
  python scripts/analyze_data_structure.py
  python scripts/analyze_data_structure.py --no-s3          # bara Silver
  python scripts/analyze_data_structure.py --s3-quick     # S3: max 500 nycklar per prefix (snabbare)
"""
import json
import os
import sys
from datetime import datetime, timezone

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_mage = os.path.join(_root, "mage_project")
sys.path.insert(0, _mage)
os.chdir(_mage)
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_root, ".env"))
except Exception:
    pass

# Prefixes som pipelinen använder eller som finns i S3 (för inventering)
S3_PREFIXES = [
    ("nhl-data/basic/teams/", "dimensions", "teams, roster"),
    ("nhl-data/basic/players/", "dimensions", "players"),
    ("nhl-data/basic/schedule/", "dimensions", "schedule"),
    ("nhl-data/basic/standings/", "seasonal_stats", "standings"),
    ("nhl-data/helpers/", "dimensions", "game_ids"),
    ("nhl-data/misc/", "dimensions", "countries, glossary, draft"),
    ("nhl-data/stats/skaters/", "seasonal_stats", "skater_stats"),
    ("nhl-data/stats/goalies/", "seasonal_stats", "goalie_stats"),
    ("nhl-data/stats/teams/", "seasonal_stats", "team_stats"),
    ("nhl-data/edge/skaters/", "seasonal_stats", "edge_skaters"),
    ("nhl-data/edge/goalies/", "seasonal_stats", "edge_goalies"),
    ("nhl-data/edge/teams/", "seasonal_stats", "edge_teams"),
    ("nhl-data-reorganized/games/by_date/", "games", "games, game_players"),
    ("nhl-data-reorganized/games/by_team/", "—", "samma som by_date, laddas ej"),
    ("nhl-data-reorganized/games/by_player/", "—", "samma som by_date, laddas ej"),
]

# Max antal nycklar att lista per prefix (för --s3-quick). Full inventering paginerar.
S3_QUICK_MAX_KEYS = 500


def _json_structure(obj, depth: int, max_depth: int = 3):
    """Returnerar en strukturerad beskrivning av JSON (nycklar och typer)."""
    if depth > max_depth:
        if isinstance(obj, list):
            return f"[array, len={len(obj)}]"
        if isinstance(obj, dict):
            return f"{{dict, {len(obj)} keys}}"
        return type(obj).__name__
    if obj is None:
        return "null"
    if isinstance(obj, bool):
        return "bool"
    if isinstance(obj, (int, float)):
        return "number"
    if isinstance(obj, str):
        return "string"
    if isinstance(obj, list):
        if not obj:
            return "[]"
        first = obj[0]
        if isinstance(first, dict):
            keys = list(first.keys())[:8]
            return f"[array of {{ {', '.join(keys)}... }}]"
        return f"[array of {type(first).__name__}]"
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            out[k] = _json_structure(v, depth + 1, max_depth)
        return out
    return type(obj).__name__


def s3_inventory(client, bucket: str, quick: bool) -> dict:
    """Listar prefix, antal filer och en exempelnyckel per prefix."""
    from utils.s3_utils import list_keys

    inventory = {}
    for prefix, pipeline, silver in S3_PREFIXES:
        count = 0
        sample_key = None
        max_keys = S3_QUICK_MAX_KEYS if quick else None
        try:
            for key in list_keys(client, bucket, prefix):
                if not key.endswith(".json"):
                    continue
                if "games_summary" in key:
                    continue
                if sample_key is None:
                    sample_key = key
                count += 1
                if quick and count >= S3_QUICK_MAX_KEYS:
                    break
            if quick and count >= S3_QUICK_MAX_KEYS:
                count_str = f"{count}+"
            else:
                count_str = str(count)
        except Exception as e:
            count_str = f"error: {e}"
            sample_key = None
        inventory[prefix] = {
            "pipeline": pipeline,
            "silver_tables": silver,
            "file_count": count_str,
            "sample_key": sample_key,
        }
    return inventory


def s3_sample_structures(client, bucket: str, inventory: dict) -> dict:
    """Läser en sample-fil per prefix och returnerar JSON-struktur."""
    from utils.s3_utils import read_json

    structures = {}
    for prefix, info in inventory.items():
        key = info.get("sample_key")
        if not key:
            continue
        try:
            data = read_json(client, bucket, key)
            structures[prefix] = {
                "sample_key": key,
                "top_level_keys": list(data.keys()) if isinstance(data, dict) else [],
                "structure": _json_structure(data, 0, max_depth=3),
            }
        except Exception as e:
            structures[prefix] = {"sample_key": key, "error": str(e)}
    return structures


def silver_schema(data_lake_path: str) -> dict:
    """Läser Silver Parquet-mappar och returnerar tabellnamn, kolumner, typer, antal rader."""
    silver_path = os.path.join(data_lake_path, "silver")
    if not os.path.isdir(silver_path):
        return {}

    try:
        import duckdb
    except ImportError:
        return {"_error": "duckdb not installed"}

    conn = duckdb.connect(":memory:")
    result = {}
    for name in sorted(os.listdir(silver_path)):
        dir_path = os.path.join(silver_path, name)
        if not os.path.isdir(dir_path):
            continue
        glob = os.path.join(dir_path, "**", "*.parquet")
        if not os.path.exists(dir_path):
            continue
        try:
            row = conn.execute(f"SELECT COUNT(*) FROM parquet_scan('{glob}')").fetchone()
            count = row[0] if row else 0
        except Exception:
            count = None
        try:
            df = conn.execute(f"SELECT * FROM parquet_scan('{glob}') LIMIT 0").fetchdf()
            columns = [{"name": c, "type": str(df.dtypes[c])} for c in df.columns]
        except Exception:
            columns = []
        result[name] = {"row_count": count, "columns": columns}
    return result


def build_mapping(inventory: dict, silver: dict) -> list:
    """Bygger mapping: S3-prefix → pipeline → Silver-tabell(ar)."""
    rows = []
    for prefix, info in inventory.items():
        pipeline = info.get("pipeline", "—")
        silver_tables = info.get("silver_tables", "")
        file_count = info.get("file_count", "?")
        silver_exists = []
        for table in silver_tables.replace(",", " ").split():
            if table in silver and silver[table].get("row_count") is not None:
                silver_exists.append(f"{table}({silver[table]['row_count']} rader)")
        rows.append({
            "s3_prefix": prefix,
            "pipeline": pipeline,
            "silver_tables": silver_tables,
            "s3_file_count": file_count,
            "silver_status": ", ".join(silver_exists) if silver_exists else "—",
        })
    return rows


def main():
    no_s3 = "--no-s3" in sys.argv
    s3_quick = "--s3-quick" in sys.argv
    out_dir = os.path.join(_root, "documentation")
    os.makedirs(out_dir, exist_ok=True)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "s3_inventory": {},
        "s3_sample_structures": {},
        "silver_schema": {},
        "mapping": [],
    }

    # --- S3 ---
    if not no_s3:
        try:
            from utils.s3_utils import get_s3_bucket, get_s3_client
        except ImportError:
            report["s3_inventory"] = {"_error": "utils.s3_utils not found (run from project root or Mage container)"}
        else:
            client = get_s3_client()
            bucket = get_s3_bucket()
            if not bucket:
                report["s3_inventory"] = {"_error": "S3 bucket not configured"}
            else:
                report["s3_inventory"] = s3_inventory(client, bucket, quick=s3_quick)
                report["s3_sample_structures"] = s3_sample_structures(client, bucket, report["s3_inventory"])
    else:
        report["s3_inventory"] = {"_skipped": "run without --no-s3 to include S3"}
        report["s3_sample_structures"] = {}

    # --- Silver ---
    data_lake = os.environ.get("DATA_LAKE_PATH", os.path.join(_root, "mage_project", "data_lake"))
    report["silver_schema"] = silver_schema(data_lake)
    report["data_lake_path"] = data_lake

    # --- Mapping ---
    if isinstance(report["s3_inventory"], dict) and "_error" not in report["s3_inventory"] and "_skipped" not in report["s3_inventory"]:
        report["mapping"] = build_mapping(report["s3_inventory"], report["silver_schema"])
    else:
        report["mapping"] = []

    # --- JSON (spara strukturer men begränsa storlek för structure)
    def _truncate_structure(s, max_len=12000):
        j = json.dumps(s, indent=2, default=str)
        return j[:max_len] + "\n... (truncated)" if len(j) > max_len else j

    json_export = {
        "generated_at": report["generated_at"],
        "s3_inventory": report["s3_inventory"],
        "s3_sample_structures": {
            k: {**v, "structure": _truncate_structure(v.get("structure", "")) if isinstance(v.get("structure"), (dict, list)) else v.get("structure")}
            for k, v in report["s3_sample_structures"].items()
        },
        "silver_schema": report["silver_schema"],
        "mapping": report["mapping"],
    }
    json_path = os.path.join(out_dir, "DATA_STRUCTURE_REPORT.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(json_export, f, indent=2, ensure_ascii=False, default=str)
    print(f"Skrev: {json_path}")

    # --- Markdown ---
    md_lines = [
        "# Data Structure Report",
        "",
        f"Genererad: {report['generated_at']}",
        "",
        "Använd denna rapport för att se alla källor (Bronze/S3), Silver-tabeller och struktur, så att du kan uppdatera pipelinen och få ut all data till Silver/Gold.",
        "",
        "---",
        "",
        "## 1. S3 (Bronze) – inventering",
        "",
    ]
    if no_s3:
        md_lines.append("*S3 hoppades över (--no-s3).*")
    elif isinstance(report["s3_inventory"], dict) and ("_error" in report["s3_inventory"] or "_skipped" in report["s3_inventory"]):
        md_lines.append(f"*{report['s3_inventory'].get('_error', report['s3_inventory'].get('_skipped', ''))}*")
    else:
        md_lines.append("| S3-prefix | Pipeline | Silver-tabell(ar) | Antal filer | Sample-nyckel |")
        md_lines.append("|-----------|----------|-------------------|-------------|---------------|")
        for prefix, info in report["s3_inventory"].items():
            if prefix.startswith("_"):
                continue
            sample = (info.get("sample_key") or "")[:60] + ("..." if len((info.get("sample_key") or "")) > 60 else "")
            md_lines.append(f"| `{prefix}` | {info.get('pipeline', '')} | {info.get('silver_tables', '')} | {info.get('file_count', '')} | `{sample}` |")
    md_lines.extend(["", "---", "", "## 2. S3 (Bronze) – struktur per källtyp (sample)", ""])
    for prefix, data in report["s3_sample_structures"].items():
        if prefix.startswith("_"):
            continue
        md_lines.append(f"### `{prefix}`")
        if data.get("error"):
            md_lines.append(f"*Fel: {data['error']}*")
        else:
            md_lines.append(f"- **Sample:** `{data.get('sample_key', '')}`")
            md_lines.append(f"- **Top-level nycklar:** `{', '.join(data.get('top_level_keys', []))}`")
            md_lines.append("")
            md_lines.append("```json")
            md_lines.append(json.dumps(data.get("structure", {}), indent=2, ensure_ascii=False, default=str)[:8000])
            if len(json.dumps(data.get("structure", {}))) > 8000:
                md_lines.append("... (truncated)")
            md_lines.append("```")
        md_lines.append("")
    md_lines.extend(["---", "", "## 3. Silver – tabeller och kolumner", ""])
    if not report["silver_schema"]:
        md_lines.append("*Inga Silver-tabeller hittades (kör pipelines först).*")
    else:
        for table, info in sorted(report["silver_schema"].items()):
            if table.startswith("_"):
                continue
            md_lines.append(f"### {table}")
            md_lines.append(f"- **Rader:** {info.get('row_count', '—')}")
            md_lines.append("- **Kolumner:**")
            for col in info.get("columns", []):
                md_lines.append(f"  - `{col.get('name', '')}` ({col.get('type', '')})")
            md_lines.append("")
    md_lines.extend(["---", "", "## 4. Mapping: Källa → Pipeline → Silver", ""])
    md_lines.append("| S3-prefix | Pipeline | Silver-tabeller | S3 filer | Silver-status |")
    md_lines.append("|-----------|----------|-----------------|----------|---------------|")
    for row in report["mapping"]:
        md_lines.append(f"| `{row['s3_prefix']}` | {row['pipeline']} | {row['silver_tables']} | {row['s3_file_count']} | {row['silver_status']} |")
    md_lines.extend([
        "",
        "---",
        "",
        "## 5. Nästa steg för att få ut all data",
        "",
        "1. **Jämför** S3-struktur (avsnitt 2) med Silver-kolumnerna (avsnitt 3). Fält som finns i Bronze men saknas i Silver kan läggas till i respektive transformer/export.",
        "2. **Kontrollera** att alla prefix som ska användas står i avsnitt 1 och att rätt pipeline läser dem (se [DATA_SOURCES_S3.md](DATA_SOURCES_S3.md)).",
        "3. **Kör** pipelinen efter ändringar och kör sedan `refresh_duckdb_views` så att Gold uppdateras.",
        "",
    ])
    md_path = os.path.join(out_dir, "DATA_STRUCTURE_REPORT.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines))
    print(f"Skrev: {md_path}")
    print("Klar. Öppna documentation/DATA_STRUCTURE_REPORT.md för att analysera strukturen.")


if __name__ == "__main__":
    main()
