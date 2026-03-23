"""
Generate LLM narratives for top anomalies and persist to MotherDuck agent_insights table.

- Calls LiteLLM (gemini-flash by default) for the top N insights (LITELLM_MAX_INSIGHTS).
- Skips insights already stored in MotherDuck (idempotent via insight_id).
- Creates agent_insights table on first run.
"""
import json
import os
import sys
from datetime import datetime

import duckdb
from mage_ai.settings.repo import get_repo_path

repo_path = get_repo_path()
if repo_path not in sys.path:
    sys.path.append(repo_path)

if "data_exporter" not in globals():
    from mage_ai.data_preparation.decorators import data_exporter

SYSTEM_PROMPT = """You are an expert NHL hockey analyst. You receive statistical data about a player or team
and write a concise, insightful summary for a hockey analytics platform.

Rules:
- Write in English, clear and professional
- 1 short headline (max 10 words, no period)
- 2-3 sentences of body text that explain the trend, its significance, and a forward-looking angle
- Use specific numbers from the data provided
- Do NOT use phrases like "based on the data" or "according to statistics"
- Output format: JSON with keys "headline" and "body" only, no markdown

Example output:
{"headline": "McDavid Scorching: 2.4 pts/game Over Last 5", "body": "Connor McDavid is producing at a historic pace over his last five games, averaging 2.4 points per game – nearly double his 20-game baseline of 1.3. With a z-score of +2.7, this stretch ranks among the top 1% of 5-game runs in our 16-season dataset. Expect regression, but McDavid's underlying shot metrics remain elite."}"""


def _md_conn_rw() -> duckdb.DuckDBPyConnection:
    token = os.getenv("MOTHERDUCK_TOKEN", "").strip()
    if not token:
        raise RuntimeError("MOTHERDUCK_TOKEN not set")
    db = os.getenv("MOTHERDUCK_DATABASE_NAME", "nhl").strip() or "nhl"
    conn = duckdb.connect(f"md:{db}?motherduck_token={token}")
    return conn


def _ensure_insights_table(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agent_insights (
            insight_id    VARCHAR PRIMARY KEY,
            generated_at  TIMESTAMP,
            insight_type  VARCHAR,
            entity_type   VARCHAR,
            entity_id     VARCHAR,
            entity_name   VARCHAR,
            team_abbr     VARCHAR,
            severity      DOUBLE,
            zscore        DOUBLE,
            season        VARCHAR,
            game_date     DATE,
            headline      VARCHAR,
            body          TEXT,
            prompt_context TEXT
        )
    """)


def _already_stored(conn: duckdb.DuckDBPyConnection, item: dict) -> bool:
    # Idempotent on both insight_id AND (entity_id, game_date) to prevent duplicates
    # when insight_type changes between runs (e.g. cold_spell → hot_streak)
    rows = conn.execute(
        """SELECT 1 FROM agent_insights
           WHERE insight_id = ?
              OR (entity_id = ? AND game_date = ? AND entity_type = ?)
           LIMIT 1""",
        [item["insight_id"], item["entity_id"], item["game_date"], item["entity_type"]]
    ).fetchall()
    return len(rows) > 0


def _call_litellm(prompt_context: str) -> tuple[str, str]:
    """Returns (headline, body). Falls back to plain text if JSON parse fails."""
    try:
        from openai import OpenAI
    except ImportError:
        return ("LLM unavailable", "openai package not installed in this environment.")

    base_url = os.getenv("LITELLM_BASE_URL", "").strip().rstrip("/")
    api_key = os.getenv("LITELLM_API_KEY", "").strip()
    model = os.getenv("LITELLM_DEFAULT_MODEL", "gemini-flash").strip()

    if not base_url or not api_key:
        return ("LLM not configured", "Set LITELLM_BASE_URL and LITELLM_API_KEY in .env.")

    client = OpenAI(base_url=f"{base_url}/v1", api_key=api_key)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt_context},
        ],
        max_tokens=300,
        temperature=0.4,
    )
    raw = response.choices[0].message.content or ""

    try:
        parsed = json.loads(raw)
        return parsed.get("headline", ""), parsed.get("body", raw)
    except json.JSONDecodeError:
        # LLM returned plain text – use first line as headline
        lines = raw.strip().splitlines()
        return lines[0][:120] if lines else "", raw


@data_exporter
def export_data(insights: list, *args, **kwargs) -> None:
    if not insights:
        print("[generate_insights] No insights to process.")
        return

    max_insights = int(os.getenv("LITELLM_MAX_INSIGHTS", "5"))
    top = insights[:max_insights]

    conn = _md_conn_rw()
    _ensure_insights_table(conn)

    stored, skipped, failed = 0, 0, 0
    for item in top:
        iid = item["insight_id"]
        if _already_stored(conn, item):
            print(f"[generate_insights] skip (exists): {item['entity_name']} / {item['insight_type']}")
            skipped += 1
            continue

        try:
            headline, body = _call_litellm(item["prompt_context"])
            conn.execute("""
                INSERT INTO agent_insights VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                iid,
                datetime.utcnow(),
                item["insight_type"],
                item["entity_type"],
                item["entity_id"],
                item["entity_name"],
                item["team_abbr"],
                item["severity"],
                item["zscore"],
                item["season"],
                item["game_date"],
                headline,
                body,
                item["prompt_context"],
            ])
            stored += 1
            print(f"[generate_insights] stored: {item['entity_name']} | {headline[:60]}")
        except Exception as e:
            failed += 1
            print(f"[generate_insights] failed for {item['entity_name']}: {e}")

    conn.close()
    print(f"[generate_insights] Done – stored: {stored}, skipped: {skipped}, failed: {failed}")
