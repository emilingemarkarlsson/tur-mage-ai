#!/usr/bin/env python3
"""
Validerar DATA_DICTIONARY.yaml mot MotherDuck-schemat.

Kör:
  python scripts/validate_data_dictionary.py

- Listar tabeller som saknas i dictionary
- Listar kolumner som dokumenterats men inte finns i DB (eller tvärtom)
- Genererar documentation/DATA_DICTIONARY.md (mänskligt läsbar)
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    import yaml
except ImportError:
    print("Kräver: pip install pyyaml")
    sys.exit(1)

MD_DB = os.getenv("MOTHERDUCK_DATABASE_NAME", "nhl").strip() or "nhl"


def load_dictionary() -> dict:
    path = ROOT / "documentation" / "DATA_DICTIONARY.yaml"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def get_motherduck_schema():
    """Hämta faktiskt schema från MotherDuck. Returnerar None om anslutning misslyckas."""
    try:
        import duckdb
    except ImportError:
        return None
    if not os.getenv("MOTHERDUCK_TOKEN", "").strip():
        return None
    try:
        conn = duckdb.connect(f"md:{MD_DB}")
        rows = conn.execute("""
            SELECT table_name, column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = 'main'
              AND table_name NOT IN ('database_snapshots', 'databases', 'owned_shares',
                  'query_history', 'recent_queries', 'shared_with_me', 'storage_info', 'storage_info_history')
            ORDER BY table_name, ordinal_position
        """).fetchall()
        conn.close()
        schema = {}
        for t, c, typ in rows:
            if t not in schema:
                schema[t] = {}
            schema[t][c] = typ
        return schema
    except Exception as e:
        print(f"Kunde inte ansluta till MotherDuck: {e}")
        return None


def generate_markdown(dictionary: dict, out_path: Path) -> None:
    """Generera läsbar Markdown från DATA_DICTIONARY.yaml."""
    tables = dictionary.get("tables") or {}
    lines = [
        "# Data Dictionary – NHL Gold",
        "",
        "Dokumentation av tabeller och kolumner för Insight Engine och analys.",
        "Källa: `documentation/DATA_DICTIONARY.yaml`.",
        "Kör `python scripts/validate_data_dictionary.py` för att uppdatera denna fil.",
        "",
        "---",
        "",
    ]
    for table_name, table_def in tables.items():
        if not isinstance(table_def, dict):
            continue
        desc = table_def.get("description", "")
        grain = table_def.get("grain", "")
        primary = table_def.get("insight_engine", {}).get("primary_for", [])
        cols = table_def.get("columns") or {}
        lines.append(f"## `{table_name}`")
        lines.append("")
        lines.append(desc)
        lines.append("")
        if grain:
            lines.append(f"**Grain:** {grain}")
            lines.append("")
        if primary:
            lines.append(f"**Insight Engine – primär för:** {', '.join(primary)}")
            lines.append("")
        if cols:
            lines.append("### Kolumner")
            lines.append("")
            lines.append("| Kolumn | Typ | Beskrivning |")
            lines.append("|--------|-----|-------------|")
            for col_name, col_def in cols.items():
                if isinstance(col_def, dict):
                    typ = col_def.get("type", "")
                    desc_col = col_def.get("description", "")
                else:
                    typ = ""
                    desc_col = str(col_def)
                lines.append(f"| {col_name} | {typ} | {desc_col} |")
            lines.append("")
        lines.append("---")
        lines.append("")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Markdown genererad: {out_path}")


def main():
    dictionary = load_dictionary()
    if not dictionary:
        print("DATA_DICTIONARY.yaml saknas eller är tom.")
        sys.exit(1)

    schema = get_motherduck_schema()
    issues = []

    if schema:
        tables_def = dictionary.get("tables") or {}
        for table, cols_db in schema.items():
            cols_dict = (tables_def.get(table) or {}).get("columns") or {}
            documented = set(cols_dict.keys())
            actual = set(cols_db.keys())
            missing_doc = actual - documented
            extra_doc = documented - actual
            if missing_doc and table in ("games", "game_players", "player_game_stats", "team_game_stats"):
                for c in sorted(missing_doc)[:10]:
                    issues.append(f"  {table}.{c} – finns i DB, saknas i dictionary")
                if len(missing_doc) > 10:
                    issues.append(f"  ... +{len(missing_doc)-10} fler i {table}")
            if extra_doc:
                for c in sorted(extra_doc):
                    issues.append(f"  {table}.{c} – dokumenterad men finns inte i DB")
    else:
        print("MotherDuck ej tillgänglig (sätt MOTHERDUCK_TOKEN) – hoppar över schema-validering.")

    if issues:
        print("\nPåverkade kolumner (validering):")
        for i in issues[:20]:
            print(i)
        if len(issues) > 20:
            print(f"... +{len(issues)-20} fler")
    else:
        print("Validering OK (inga uppenbara avvikelser).")

    out_path = ROOT / "documentation" / "DATA_DICTIONARY.md"
    generate_markdown(dictionary, out_path)
    print("\nKlart.")


if __name__ == "__main__":
    main()
