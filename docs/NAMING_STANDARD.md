# Namnstandard och struktur – multi-liga data platform

Beslutad 2026-05-01. Gäller från och med NHL-rename (planerat efter backfill).

## Principer

- **Källa, inte liga** — prefixet speglar *varifrån* datan hämtas, inte en specifik liga.
  `swe` täcker hela swehockey.com (SHL, HockeyAllsvenskan, HockeyEttan, juniorer m.m.).
- **Ett Mage-projekt** — alla pipelines i `mage_project/`, organiserade med Mage-tags.
- **En MotherDuck-databas per källa** — isolerade databaser, inga cross-source-joins i Gold.
- **Konsekvent lager-struktur** — Bronze → Silver → Gold gäller oavsett källa.

---

## Pipeline-namnstandard

Format: `{källa}_{typ}_pipeline`

| Källa | Typ | Pipeline-namn | Status |
|---|---|---|---|
| `nhl` | `dimensions` | `nhl_dimensions_pipeline` | 🔄 Rename planerad |
| `nhl` | `stats` | `nhl_stats_pipeline` | 🔄 Rename planerad |
| `nhl` | `games` | `nhl_games_pipeline` | 🔄 Rename planerad |
| `nhl` | `analytics` | `nhl_analytics_pipeline` | 🔄 Rename planerad |
| `swe` | `games` | `swe_games_pipeline` | ✅ Klar |
| `swe` | `pdf` | `swe_pdf_pipeline` | ✅ Klar |

### Framtida källkoder

| Kod | Källa | Ligor |
|---|---|---|
| `nhl` | NHL officiellt API | NHL |
| `swe` | swehockey.com | SHL, HockeyAllsvenskan, HockeyEttan, juniorer m.m. |
| `ahl` | AHL API | AHL |
| `khl` | KHL data | KHL |
| `iihf` | IIHF | VM, OS, World Juniors |
| `liiga` | Liiga (Finland) | Liiga |
| `del` | DEL (Tyskland) | DEL |

### Typer

| Typ | Beskrivning |
|---|---|
| `dimensions` | Lag, spelare, roster, spelschema, draft |
| `stats` | Säsongsstatistik, standings, aggregat |
| `games` | Match-för-match: händelser, spelare, resultat |
| `pdf` | PDF-rapporter (officiella matchrapporter) |
| `analytics` | Anomaly detection, LLM insights |

---

## Data lake-struktur

### Silver (lokalt + S3)

```
data_lake/silver/
  nhl/                    ← efter rename
    games/
    standings/
    skater_stats/
    goalie_stats/
    team_stats/
    game_players/
    game_events/
    game_stories/
    players/
    teams/
    roster/
    ...
  swe/
    games/
    pdf_reports/
    ...
  ahl/                    ← framtida
  khl/                    ← framtida
```

Nuläge (före rename): `data_lake/silver/games/` etc. (implicit NHL, ingen ligamapp).

### Gold (DuckDB)

Lokal fil: `data_lake/gold/nhl.duckdb` — en fil per källa efter rename.

```
data_lake/gold/
  nhl.duckdb
  swe.duckdb              ← framtida (nu synkas swe direkt till MotherDuck)
```

---

## MotherDuck

En databas per källa. Namnges med källkoden.

| Databas | Källa | Status |
|---|---|---|
| `nhl` | NHL | ✅ Aktiv |
| `swe` | swehockey.com | ✅ Aktiv |
| `ahl` | AHL | Framtida |
| `khl` | KHL | Framtida |

---

## Mage AI – taggar

Pipelines taggas i Mage UI för visuell gruppering:

- `nhl` — alla NHL-pipelines
- `swe` — alla swehockey-pipelines
- `analytics` — insights/ML-pipelines
- `daily` / `weekly` — körfrekvens

---

## Körschema (efter rename)

| Pipeline | Källa | Tid (UTC) | Frekvens | Kör via |
|---|---|---|---|---|
| `nhl_dimensions_pipeline` | NHL API | 07:00 | Måndag | Mage AI |
| `nhl_games_pipeline` | NHL API | 07:00 | Dagligen | Mage AI |
| `nhl_stats_pipeline` | NHL API | 07:15 | Dagligen | Mage AI |
| `nhl_analytics_pipeline` | MotherDuck | 07:00 | Dagligen | GitHub Actions |
| `swe_games_pipeline` | swehockey.com | TBD | TBD | Mage AI |
| `swe_pdf_pipeline` | swehockey.com | TBD | TBD | Mage AI |

---

## Rename-plan (att genomföra efter backfill)

1. Byt namn på pipeline-mappar: `mage_project/pipelines/games_pipeline/` → `nhl_games_pipeline/`
2. Uppdatera `metadata.yaml` i varje pipeline (namn + uuid)
3. Uppdatera Postgres pipeline_schedule-tabellen med nya `pipeline_uuid`
4. Flytta Silver-mappar på servern: `silver/games/` → `silver/nhl/games/`
5. Uppdatera alla `parquet_scan`-sökvägar i `refresh_duckdb_views.py`
6. Deploya och verifiera ett testkörnig
