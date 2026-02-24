# Sista genomgång – kör pipelines i Mage UI

Använd denna checklista innan du triggar pipelines.

---

## 1. Miljö (.env)

| Variabel | Krävs | Din .env | Kommentar |
|---------|--------|----------|-----------|
| `DATA_LAKE_PATH` | Ja | `/home/src/mage_project/data_lake` | OK |
| `GAMES_START_DATE` | Ja (games) | `2010-01-01` | För full 2010–2026 |
| `DATA_LAKE_SINK` | Ja | `s3` | Silver/Gold skrivs till S3 |
| `S3_DATA_LAKE_PREFIX` | Ja (vid s3) | `nhl-analytics` | OK |
| `S3_DATA_LAKE_BUCKET` | Ja (vid s3) | `nhlhockey-data` | OK |
| `S3_SOURCE` | Ja | `hetzner` | OK |
| `HETZNER_BUCKET` | Ja | `nhlhockey-data` | Samma som källa |
| `HETZNER_ENDPOINT` | Ja | Satt | OK |
| `HETZNER_ACCESS_KEY` / `HETZNER_SECRET_KEY` | Ja | Satta | OK |
| `DUCKDB_VIEWER_PATH` | Rekommenderat | `s3://.../gold/nhl.duckdb` | För Streamlit |
| `REFRESH_USE_S3_FALLBACK_FOR_GAMES` | Valfritt | `1` | Gold kan inkludera games från S3 om dimensions/seasonal körs utan games |
| `GAMES_YEAR` / `games_year` | Valfritt | (tom) | År-för-år: sätt i **Mage UI → Variables** som `games_year` = `2010`, kör pipeline, ändra till `2011` osv. Eller sätt i .env. Se `docs/GAMES_LOADING.md`. |

---

## 2. Före körning – games (full eller år för år)

**Alternativ A – år för år (rekommenderat vid stor datamängd)**  
Se **`docs/GAMES_LOADING.md`**: använd `./scripts/run_games_year.sh 2010` … `2026` och kör games_pipeline en gång per år. Inga dubbletter.

**Alternativ B – full laddning i en körning**

Om du vill ha **all** matchdata 2010–2026 i en körning:

1. **Rensa state** (annars laddas bara datum efter senaste körning):
   ```bash
   ./scripts/reset_full_games_load.sh
   ```
   Eller lokalt: `rm -f mage_project/state/last_games_date.txt`

2. **Kolla omfattning** (valfritt):
   ```bash
   python scripts/scope_games_pipeline.py
   ```
   Du ska se datum från 2010-10-01 till 2026-xx-xx och antingen "Ingen state-fil" eller att du just rensat state.

---

## 3. Pipeline-struktur (oförändrad)

Varje pipeline har fyra steg i kedja: **loader → transformer → export parquet → refresh duckdb views**.

| Pipeline | Steg 1 | Steg 2 | Steg 3 | Steg 4 |
|----------|--------|--------|--------|--------|
| **dimensions_pipeline** | load_dimensions | transform_dimensions | export_dimensions_parquet | refresh_duckdb_views |
| **seasonal_stats_pipeline** | load_seasonal_stats | transform_seasonal_stats | export_seasonal_stats_parquet | refresh_duckdb_views |
| **games_pipeline** | load_games_incremental | transform_games | export_games_parquet | refresh_duckdb_views |

Block-filer finns under `mage_project/data_loaders/`, `mage_project/transformers/`, `mage_project/data_exporters/` och matchar uuid i pipeline-metadata.

---

## 4. Körande i Mage UI

1. Starta: `docker compose up -d`
2. Öppna: **http://localhost:6789**
3. Kör i **denna ordning**:
   - **dimensions_pipeline** (snabb)
   - **seasonal_stats_pipeline** (snabb)
   - **games_pipeline** (lång vid full laddning – många tusen matcher)

Vid games_pipeline ska du i block-loggen för **load games incremental** se något i stil med:
- `[games loader] GAMES_START_DATE=2010-01-01 | last_games_date (state)=(ingen)`
- `[games loader] Laddar N datum: från 2010-10-01 till 2026-01-03`

Om du istället ser `last_games_date (state)=2026-01-03` och 0 datum har state inte rensats – kör reset-skriptet och kör games_pipeline igen.

---

## 5. Efter körning

- **Validera Gold:**  
  `python scripts/validate_duckdb_viewer.py`  
  Du ska få 19 tabeller/vyer inkl. games, game_players, player_game_stats, team_game_stats, utan varning om saknade.

- **Streamlit:** Starta viewern och välj t.ex. games eller player_game_stats; kontrollera datumspann (första/sista match).

---

## 6. Kort sammanfattning

- **.env:** Hetzner-uppgifter, DATA_LAKE_*, GAMES_START_DATE=2010-01-01.
- **State:** För full games-laddning, rensa med `./scripts/reset_full_games_load.sh` innan games_pipeline.
- **Ordning:** dimensions → seasonal_stats → games.
- **Logg:** I Mage-run för load games incremental syns vilket datumspann som laddas.
