# Gold layer: DuckDB schema and naming standards

This document is the single source of truth for the Gold layer (DuckDB). All table and view names are **English**, **snake_case**. Use it for analytics, Streamlit, and SQL.

---

## Audit summary (what was corrected)

- **View names:** Swedish names replaced with English: `spelarstatistik_per_match` → **`player_game_stats`**, `lagstatistik_per_match` → **`team_game_stats`**.
- **Naming standard:** All Gold objects use **snake_case** and English; column names in Silver/Gold are snake_case (except legacy `players.firstName`/`lastName`; `player_game_stats` exposes `player_first_name`, `player_last_name`).
- **Deduplication:** Applied in transformers for games, game_players, edge_*, schedule, game_ids, roster, standings, skater_stats, goalie_stats, team_stats so Gold does not contain duplicate keys.
- **Schema consistency:** `game_players` Parquet uses a fixed column list (including `gaa`) so all files share the same schema and DuckDB can read them without mismatch.
- **Single reference:** This file lists every Gold view, its grain, key columns, and when to use it.

---

## Naming standards

| Rule | Example |
|------|--------|
| Tables/views | `snake_case`, English | `game_players`, `player_game_stats` |
| Columns | `snake_case` | `game_id`, `player_id`, `team_abbr`, `goals_for` |
| IDs | `*_id` or `*_abbr` | `game_id`, `player_id`, `team_abbr` |
| Dates | `*_date` | `game_date`, `schedule_date` |
| Flags | `is_*` | `is_home` |

**Note:** The `players` dimension may still expose `firstName` / `lastName` (from source). The view `player_game_stats` exposes `player_first_name`, `player_last_name` (snake_case).

---

## Gold objects (views over Silver Parquet)

### Dimension / reference (from dimensions_pipeline)

| View | Grain | Key columns | Description |
|------|--------|-------------|-------------|
| `teams` | One per team | `id`, `abbrev` | Teams, conference, division |
| `players` | One per player | `id` | Players; names, position, birth, etc. |
| `countries` | One per country | `code` | Country lookup |
| `roster` | One per (season, team, player) | `season`, `team_id`, `player_id` | Roster links |
| `schedule` | One per scheduled game | `gamePk`, `schedule_date` | Schedule; game dates and IDs |
| `game_ids` | One per (season, game) | `season`, `game_id` | Game IDs per season (helpers) |
| `glossary` | One per term | — | Glossary |
| `draft` | One per draft item | — | Draft years/rounds |

### Seasonal / aggregated (from seasonal_stats_pipeline)

| View | Grain | Key columns | Description |
|------|--------|-------------|-------------|
| `standings` | One per team per season | `season`, `teamId` | Standings |
| `skater_stats` | One per skater per season | `season`, `playerId` | Skater season stats |
| `goalie_stats` | One per goalie per season | `season`, `playerId` | Goalie season stats |
| `team_stats` | One per team per season | `season`, `teamId` | Team season stats |
| `edge_skaters` | One per (season, category, player) | `season`, `category`, `player_id` | EDGE skater leaders |
| `edge_goalies` | One per (season, category, player) | `season`, `category`, `player_id` | EDGE goalie leaders |
| `edge_teams` | One per (season, category, team) | `season`, `category`, `team_id` | EDGE team leaders |

### Game-level (from games_pipeline)

| View | Grain | Key columns | Description |
|------|--------|-------------|-------------|
| `games` | One per game | `game_id` | One row per game; home/away team id & abbr, scores, SOG, hits, venue, game_state, ot_periods, period_number/type, etc. |
| `game_players` | One per player per game | `game_id`, `player_id` | Raw player stats per game (skaters + goalies; goalies include shots_against by situation). Join to `players` for names. |
| **`player_game_stats`** | One per player per game | `game_id`, `player_id` | Same as `game_players` with `player_first_name`, `player_last_name`. **Use for player-by-game trends.** |
| **`team_game_stats`** | One per team per game | `game_id`, `team_abbr` | Unpivot of `games`: one row per team per game with `goals_for`, `goals_against`, `sog`, `is_home`, etc. **Use for team-by-game trends.** |

---

## Quick reference: get the data you want

| Want | Use view(s) | Filter / join |
|------|-------------|----------------|
| Player stats per game (with names) | `player_game_stats` | `WHERE player_id = ?` or `player_last_name = 'X'`; order by `game_date` |
| Team stats per game (one row per team per game) | `team_game_stats` | `WHERE team_abbr = 'TOR'`; order by `game_date` |
| Raw player stats per game | `game_players` | Join to `players` on `players.id = game_players.player_id` for names |
| Game-level (one row per game) | `games` | `game_date`, `home_team_abbr`, `away_team_abbr` |

---

## Deduplication and data quality

- **games:** Deduplicated by `game_id` in the transformer.
- **game_players:** Deduplicated by `(game_id, player_id)`.
- **Edge tables:** Deduplicated by `(season, category, player_id)` or `(season, category, team_id)`.
- **schedule:** Deduplicated by `(schedule_date, gamePk)`.
- **game_ids:** Deduplicated by `(season, game_id)`.
- **roster:** Deduplicated by `(season, team_id, player_id)`.
- **standings / skater_stats / goalie_stats / team_stats:** Deduplicated by their natural keys where columns exist.

---

## File and path

- **Local:** `mage_project/data_lake/gold/nhl.duckdb`
- **S3:** `s3://<bucket>/<prefix>/gold/nhl.duckdb` (when `DATA_LAKE_SINK=s3`)

Views are created by the **refresh_duckdb_views** block at the end of each pipeline (dimensions, seasonal_stats, games). Run all three pipelines so Gold contains all views.

### MotherDuck-synk

Om `MOTHERDUCK_TOKEN` är satt i `.env` synkas Gold automatiskt till MotherDuck efter varje `refresh_duckdb_views`. Lokala vyer (som refererar Parquet) materialiseras till tabeller i molnet. Skapa databasen `nhl` i MotherDuck UI först om den inte finns.
