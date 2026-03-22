#!/usr/bin/env python3
"""
Analyserar NHL-data i MotherDuck och genererar en dokumentationsfil.

Kräver: MOTHERDUCK_TOKEN i .env eller miljö.

  python scripts/analyze_motherduck_data.py

Output:
  - Skriver till documentation/MOTHERDUCK_DATA_COVERAGE.md
  - Innehåller: tabeller, radantal, kolumner, datumspann, säsonger,
    null-statistik, datakvalitet, exempelrader
"""
import os
import sys
from datetime import datetime

try:
    import duckdb
except ImportError:
    print("Kräver: pip install duckdb>=1.4.4")
    sys.exit(1)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))
except Exception:
    pass

MD_DB = os.getenv("MOTHERDUCK_DATABASE_NAME", "nhl").strip() or "nhl"
OUTPUT_PATH = os.path.join(ROOT, "documentation", "MOTHERDUCK_DATA_COVERAGE.md")


def safe_exec(conn, sql: str, default=None):
    """Kör SQL, returnera resultat eller default vid fel."""
    try:
        return conn.execute(sql).fetchall()
    except Exception as e:
        return default if default is not None else []


def safe_exec_df(conn, sql: str):
    """Kör SQL, returnera DataFrame eller None."""
    try:
        return conn.execute(sql).fetchdf()
    except Exception:
        return None


def get_tables(conn) -> list[str]:
    """Lista alla tabeller/vyer i main."""
    rows = safe_exec(
        conn,
        """
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'main' AND table_type IN ('BASE TABLE', 'VIEW')
        ORDER BY table_name
        """,
        [],
    )
    return [r[0] for r in rows] if rows else []


def get_columns(conn, table: str) -> list[tuple[str, str]]:
    """Lista kolumner och typer för en tabell."""
    rows = safe_exec(
        conn,
        f"""
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = 'main' AND table_name = '{table}'
        ORDER BY ordinal_position
        """,
        [],
    )
    return [(r[0], r[1]) for r in rows] if rows else []


def get_row_count(conn, table: str) -> int | None:
    try:
        (n,) = conn.execute(f'SELECT COUNT(*) FROM main."{table}"').fetchone()
        return int(n)
    except Exception:
        return None


def analyze_table(conn, table: str, lines: list[str]) -> None:
    """Lägg till analys för en tabell."""
    count = get_row_count(conn, table)
    cols = get_columns(conn, table)

    lines.append(f"### `{table}`")
    lines.append("")
    lines.append(f"| Attribut | Värde |")
    lines.append("|----------|-------|")
    lines.append(f"| Rader | {count if count is not None else 'N/A'} |")
    lines.append(f"| Kolumner | {len(cols)} |")
    lines.append("")

    if cols:
        lines.append("**Kolumner:**")
        lines.append("")
        lines.append("| Kolumn | Typ |")
        lines.append("|--------|-----|")
        for cname, ctype in cols[:30]:  # Max 30 för att hålla doc läsbar
            lines.append(f"| {cname} | {ctype} |")
        if len(cols) > 30:
            lines.append(f"| … (+{len(cols) - 30} till) | |")
        lines.append("")

    # Tabell-specifik analys
    if table == "games":
        _analyze_games(conn, lines)
    elif table == "game_players":
        _analyze_game_players(conn, lines)
    elif table == "player_game_stats":
        _analyze_player_game_stats(conn, lines)
    elif table == "team_game_stats":
        _analyze_team_game_stats(conn, lines)

    lines.append("---")
    lines.append("")


def _analyze_games(conn, lines: list[str]) -> None:
    df = safe_exec_df(
        conn,
        """
        SELECT
            MIN(game_date) AS forsta_match,
            MAX(game_date) AS senaste_match,
            COUNT(DISTINCT game_id) AS unika_matcher,
            COUNT(*) AS total_rader,
            COUNT(DISTINCT season) AS antal_sasonger
        FROM main.games
        """,
    )
    if df is not None and not df.empty:
        r = df.iloc[0]
        lines.append("**Datums- och säsongsstatistik (games):**")
        lines.append("")
        lines.append("| Mätvärde | Värde |")
        lines.append("|----------|-------|")
        lines.append(f"| Första match | {r['forsta_match']} |")
        lines.append(f"| Senaste match | {r['senaste_match']} |")
        lines.append(f"| Unika matcher (game_id) | {r['unika_matcher']} |")
        lines.append(f"| Totala rader | {r['total_rader']} |")
        dupes = r["total_rader"] - r["unika_matcher"] if r["total_rader"] and r["unika_matcher"] else 0
        lines.append(f"| Dubletter (rader - unika) | {dupes} |")
        lines.append(f"| Antal säsonger | {r['antal_sasonger']} |")
        lines.append("")

    df2 = safe_exec_df(conn, "SELECT season, COUNT(*) AS matcher FROM main.games GROUP BY season ORDER BY season")
    if df2 is not None and not df2.empty:
        lines.append("**Matcher per säsong:**")
        lines.append("")
        lines.append("| Säsong | Matcher |")
        lines.append("|--------|---------|")
        for _, row in df2.iterrows():
            lines.append(f"| {row['season']} | {row['matcher']} |")
        lines.append("")

    # Null-check viktiga kolumner
    df3 = safe_exec_df(
        conn,
        """
        SELECT
            COUNT(*) AS total,
            COUNT(game_id) AS n_game_id,
            COUNT(game_date) AS n_game_date,
            COUNT(home_team_abbr) AS n_home_team,
            COUNT(away_team_abbr) AS n_away_team,
            COUNT(home_score) AS n_home_score,
            COUNT(away_score) AS n_away_score
        FROM main.games
        """,
    )
    if df3 is not None and not df3.empty:
        r = df3.iloc[0]
        total = int(r["total"] or 0)
        lines.append("**Null-täckning (viktiga kolumner):**")
        lines.append("")
        for col, key in [
            ("game_id", "n_game_id"),
            ("game_date", "n_game_date"),
            ("home_team_abbr", "n_home_team"),
            ("away_team_abbr", "n_away_team"),
            ("home_score", "n_home_score"),
            ("away_score", "n_away_score"),
        ]:
            v = int(r.get(key, 0) or 0)
            pct = (100 * v / total) if total else 0
            lines.append(f"- {col}: {v}/{total} ({pct:.1f}%)")
        lines.append("")

    # Exempel: senaste 3 matcher
    df4 = safe_exec_df(
        conn,
        """
        SELECT game_id, game_date, home_team_abbr, away_team_abbr, home_score, away_score, status
        FROM main.games ORDER BY game_date DESC LIMIT 3
        """,
    )
    if df4 is not None and not df4.empty:
        lines.append("**Exempel – senaste 3 matcher:**")
        lines.append("")
        lines.append("| " + " | ".join(df4.columns) + " |")
        lines.append("|" + "|".join(["---"] * len(df4.columns)) + "|")
        for _, row in df4.iterrows():
            cells = ["" if v is None or (isinstance(v, float) and str(v) == "nan") else str(v) for v in row]
            lines.append("| " + " | ".join(cells) + " |")
        lines.append("")


def _analyze_game_players(conn, lines: list[str]) -> None:
    total = get_row_count(conn, "game_players")
    df = safe_exec_df(
        conn,
        """
        SELECT COUNT(*) AS unika_par
        FROM (SELECT game_id, player_id FROM main.game_players GROUP BY game_id, player_id)
        """,
    )
    if df is not None and not df.empty and total is not None:
        unika = int(df.iloc[0]["unika_par"])
        lines.append("**Unika (game_id, player_id):**")
        lines.append("")
        lines.append(f"- Total rader: {total}")
        lines.append(f"- Unika par: {unika} {'(inga dubletter)' if unika == total else f'(VARNING: {total - unika} dubletter)'}")
        lines.append("")

    # Kolumntäckning för skater vs målvakt
    df2 = safe_exec_df(
        conn,
        """
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN position = 'G' THEN 1 ELSE 0 END) AS goalies,
            SUM(CASE WHEN position != 'G' OR position IS NULL THEN 1 ELSE 0 END) AS skaters,
            COUNT(goals) AS har_goals,
            COUNT(assists) AS har_assists,
            COUNT(toi_seconds) AS har_toi,
            COUNT(save_pct) AS har_save_pct
        FROM main.game_players
        """,
    )
    if df2 is not None and not df2.empty:
        r = df2.iloc[0]
        lines.append("**Spelarstatistik-täckning:**")
        lines.append("")
        lines.append(f"- Målvakter (position=G): {r['goalies']}")
        lines.append(f"- Skridskoåkare: {r['skaters']}")
        lines.append(f"- Har goals: {r['har_goals']}")
        lines.append(f"- Har assists: {r['har_assists']}")
        lines.append(f"- Har toi_seconds: {r['har_toi']}")
        lines.append(f"- Har save_pct (målvakter): {r['har_save_pct']}")
        lines.append("")


def _analyze_player_game_stats(conn, lines: list[str]) -> None:
    df = safe_exec_df(
        conn,
        """
        SELECT
            COUNT(DISTINCT player_id) AS unika_spelare,
            COUNT(DISTINCT game_id) AS unika_matcher,
            MIN(game_date) AS forsta,
            MAX(game_date) AS senaste
        FROM main.player_game_stats
        """,
    )
    if df is not None and not df.empty:
        r = df.iloc[0]
        lines.append("**Täckning (player_game_stats):**")
        lines.append("")
        lines.append(f"- Unika spelare: {r['unika_spelare']}")
        lines.append(f"- Unika matcher: {r['unika_matcher']}")
        lines.append(f"- Datumspann: {r['forsta']} till {r['senaste']}")
        lines.append("")


def _analyze_team_game_stats(conn, lines: list[str]) -> None:
    df = safe_exec_df(
        conn,
        """
        SELECT
            COUNT(DISTINCT team_abbr) AS unika_lag,
            COUNT(DISTINCT game_id) AS unika_matcher,
            MIN(game_date) AS forsta,
            MAX(game_date) AS senaste
        FROM main.team_game_stats
        """,
    )
    if df is not None and not df.empty:
        r = df.iloc[0]
        lines.append("**Täckning (team_game_stats):**")
        lines.append("")
        lines.append(f"- Unika lag: {r['unika_lag']}")
        lines.append(f"- Unika matcher: {r['unika_matcher']}")
        lines.append(f"- Datumspann: {r['forsta']} till {r['senaste']}")
        lines.append("")


def main():
    if not os.getenv("MOTHERDUCK_TOKEN", "").strip():
        print("Sätt MOTHERDUCK_TOKEN i .env eller miljö.")
        sys.exit(1)

    print(f"Ansluter till MotherDuck ({MD_DB})...")
    conn = duckdb.connect(f"md:{MD_DB}")

    tables = get_tables(conn)
    print(f"Hittade {len(tables)} tabeller: {', '.join(tables)}")

    lines = [
        "# MotherDuck NHL – datatäckning",
        "",
        f"*Genererat: {datetime.now().strftime('%Y-%m-%d %H:%M')}*",
        "",
        "Denna rapport beskriver vilken data som finns i MotherDuck NHL-databasen.",
        "Kör `python scripts/analyze_motherduck_data.py` för att uppdatera.",
        "",
        "---",
        "",
        "## Sammanfattning",
        "",
    ]

    # Snabbsammanfattning
    games_count = get_row_count(conn, "games") if "games" in tables else None
    gp_count = get_row_count(conn, "game_players") if "game_players" in tables else None
    lines.append("| Tabell | Rader |")
    lines.append("|--------|-------|")
    for t in tables:
        c = get_row_count(conn, t)
        lines.append(f"| {t} | {c if c is not None else 'N/A'} |")
    lines.append("")

    if games_count is not None:
        df = safe_exec_df(conn, "SELECT MIN(game_date) AS lo, MAX(game_date) AS hi FROM main.games")
        if df is not None and not df.empty:
            lo, hi = df.iloc[0]["lo"], df.iloc[0]["hi"]
            lines.append(f"**Matcher:** {games_count} st, datumspann {lo} till {hi}")
            lines.append("")
    if gp_count is not None:
        lines.append(f"**Game players (spelare × matcher):** {gp_count} rader")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## Detaljer per tabell")
    lines.append("")

    for table in tables:
        try:
            analyze_table(conn, table, lines)
        except Exception as e:
            lines.append(f"### `{table}`")
            lines.append("")
            lines.append(f"*Analysfel: {e}*")
            lines.append("")
            lines.append("---")
            lines.append("")

    conn.close()

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"\nDokumentation skriven till: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
