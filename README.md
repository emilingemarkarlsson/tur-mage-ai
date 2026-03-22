# Mage AI i Docker (med MinIO)

Detta repo är en "by the book"-setup för Mage OSS i Docker Compose med:
- ihållande volymer
- enkel uppgradering via version i `.env`
- MinIO/S3-konfiguration via extern endpoint
- `io_config.yaml` färdig för MinIO

## Snabbstart

1. Kopiera exempel-ENV:
   ```bash
   cp .env.example .env
   ```
2. Starta:
   ```bash
   docker compose up -d --build
   ```
3. Öppna Mage: `http://localhost:6789`

Standard-inlogg (Mage OSS): `admin` / `admin`. Byt lösenord direkt efter första inloggningen.  
Om du använder den här repots uppsatta default-owner, logga in med: `admin@example.com` / `admin`.  
Källa: Mage Quickstart-dokumentationen.  

## Verifiera att projektet sparas lokalt

När du skapar pipelines/blocks i Mage skrivs de som filer i `mage_project/` lokalt.
Ett snabbt sätt att verifiera:

1. Skapa en ny pipeline i UI
2. Kontrollera att en ny mapp/fil dyker upp under `mage_project/`

Om du raderar containern men behåller mappen `mage_project/` så ligger allt kvar.

## Data Lake (Parquet + DuckDB)

Pipelines skriver Parquet till `DATA_LAKE_PATH` (default `mage_project/data_lake`) och Gold DuckDB byggs i `mage_project/data_lake/gold/nhl.duckdb`.

- **`DATA_LAKE_SINK=local`** (rekommenderat för att undvika S3-flaskhals): Silver och Gold skrivs **bara lokalt**. Källan (t.ex. games) läses fortfarande från S3; Parquet och DuckDB byggs lokalt. Enklare att migrera projektet senare. Se **`docs/DATA_LAKE_APPROACH.md`**.
- **`DATA_LAKE_SINK=s3`**: Parquet och `nhl.duckdb` laddas upp till S3. Lokal DuckDB tas bort efter uppladdning. Streamlit kan läsa från S3 (read‑only) om `DUCKDB_VIEWER_PATH` pekar på `s3://...`.

## Full laddning i Mage (alla pipelines → Streamlit)

**Efter att du ändrat transformers eller loaders** (t.ex. nya kolumner för teams, schedule, games, edge-leaders) ska du köra **alla pipelines i ordning** så att Silver (och sedan Gold) fylls med den uppdaterade datan. Befintlig Silver skrivs över av varje pipeline-körning.

För att köra **full laddning av all data** enligt planen och sedan använda Streamlit:

### 1. Konfiguration

- I `.env`: sätt `GAMES_START_DATE=2010-01-01` (eller tidigaste datum du har data för). För endast senaste säsong kan du använda t.ex. `2025-01-01`.
- Sätt `DATA_LAKE_SINK=s3` och `S3_DATA_LAKE_BUCKET` / `S3_DATA_LAKE_PREFIX` om Silver ska skrivas till Hetzner.

### 2. Rensa incremental state (vid full omkörning av games)

**games_pipeline** hämtar matchdata från Hetzner S3: `nhl-data-reorganized/games/by_date/` (rätt källa enligt dokumentationen, från 2010 om `GAMES_START_DATE=2010-01-01`). Det är **en stor körning** – många tusen JSON-filer.

Om du redan kört pipelinen tidigare sparar den senaste datum i state. Då hämtar nästa körning **bara nya datum** (inkrementellt). För att köra **full laddning från 2010** måste du först rensa state:

```bash
./scripts/reset_full_games_load.sh
```

Alternativt (om container heter annat):

```bash
docker exec -it tur-mage-ai-mage-1 rm -f /home/src/mage_project/state/last_games_date.txt
```

**Kolla omfattning innan körning:** `python scripts/scope_games_pipeline.py` (eller i Docker med samma sökväg). Det visar antal datum och matchfiler som pipelinen kommer att läsa.

**Varför laddas inte 2010–2026?** Källan är `nhl-data-reorganized/games/by_date/` (första datum 2010-10-01, senaste 2026). Loadern filtrerar på: (1) **GAMES_START_DATE** – endast datum ≥ detta; (2) **state-fil** `last_games_date.txt` – om den finns laddas bara datum *efter* senaste körning (inkrementell). Om du tidigare kört pipelinen sparades t.ex. 2025-01-01 i state, då laddas 2010–2024 inte. **Lösning:** sätt `GAMES_START_DATE=2010-01-01` i `.env`, kör `./scripts/reset_full_games_load.sh`, kör sedan **games_pipeline** i Mage. I Mage-run loggen syns nu raderna `[games loader] GAMES_START_DATE=... | last_games_date (state)=...` och vilket datumspann som laddas.

**Ladda år för år (undvik 24h-körning):** I **Mage UI → Variables** skapa `games_year` = `2010`, rensa state, kör games_pipeline; när klar ändra till `2011`, kör igen, osv. Inga dubbletter. Se **`docs/GAMES_LOADING.md`**. Alternativt: sätt `GAMES_YEAR` i `.env` och använd `./scripts/run_games_year.sh`.

### 3. Starta Mage och kör pipelines i ordning (Mage UI)

1. `docker compose up -d`
2. Öppna Mage: **http://localhost:6789**
3. Kör i Mage UI (i denna ordning):
   - **dimensions_pipeline** (teams, players, countries, roster, schedule, game_ids, glossary, draft)
   - **seasonal_stats_pipeline**
   - **games_pipeline** (kan ta lång tid vid full backfill – många JSON-filer från S3)

   Varje pipeline har fyra steg: **loader → transformer → export parquet → refresh duckdb views**. Refresh bygger Gold från all Silver (lokalt + vid S3-fallback games/game_players om aktiverat). När du kört alla tre är Gold fylld – du behöver inte köra något extra.

   **Tekniskt:** S3-sökvägar använder `DATA_LAKE_PATH` från miljö. Games-export rensar partition-mappen (lokal + S3) innan skriv så att omkörning inte ger dubletter. Refresh försöker först full schema för `team_game_stats`; vid äldre Silver används minimal vy automatiskt.

**Data försvinner inte:** Refresh bygger Gold från **all** Silver som finns lokalt. När du kört games_pipeline en gång ligger `silver/games` och `silver/game_players` kvar. Nästa gång du kör dimensions eller seasonal använder refresh fortfarande den lokala Silver-mappen, så games/game_players finns kvar i Gold. Först när du kör **games_pipeline** igen uppdateras matchdatan. Dagliga körningar (dimensions → seasonal → games) blir snabba eftersom vi inte läser games från S3 vid varje refresh; S3-fallback är av som standard (`REFRESH_USE_S3_FALLBACK_FOR_GAMES` är inte satt).

Efter det ligger Silver i `mage_project/data_lake/silver/` (och i S3 om `DATA_LAKE_SINK=s3`) och Gold i `mage_project/data_lake/gold/nhl.duckdb`.

### 4. Starta Streamlit och koppla till DuckDB

Viewern läser **lokal** fil eller **S3** automatiskt utifrån `.env`: vid `DATA_LAKE_SINK=s3` används `DUCKDB_VIEWER_PATH` (t.ex. `s3://bucket/prefix/gold/nhl.duckdb`). Sätt i `.env`:

```bash
DUCKDB_VIEWER_PATH=s3://nhlhockey-data/nhl-analytics/gold/nhl.duckdb
```

**Validera anslutning först (lokalt):**

```bash
cd /sökväg/till/tur-mage-ai
python scripts/validate_duckdb_viewer.py
```

Det listar tabeller och visar om `games` / `game_players` finns. Om de saknas: kör **games_pipeline** i Mage till slut (Loader → Transform → Export → refresh_duckdb_views) och kör valideringen igen.

**Starta Streamlit (rekommenderat från projektrot):**

```bash
cd /sökväg/till/tur-mage-ai
./scripts/run_streamlit_viewer.sh
```

eller:

```bash
streamlit run streamlit_viewer.py
```

Öppna **http://localhost:8501**. I sidofältet: om rätt sökväg inte visas, klicka **"Återställ sökväg till standard"** så sätts S3/lokal från `.env`.

## S3‑källa (Hetzner eller MinIO)

Du kan välja källa med `S3_SOURCE`:
- `S3_SOURCE=hetzner` använder `HETZNER_*`
- `S3_SOURCE=minio` använder `MINIO_*`

Se `.env.example` för alla variabler.

**Validera Silver och Gold:** Kör `python scripts/validate_silver_gold.py`

**Analysera och dokumentera MotherDuck-data:** Kör `python scripts/analyze_motherduck_data.py` (kräver `MOTHERDUCK_TOKEN`). Genererar `documentation/MOTHERDUCK_DATA_COVERAGE.md` med tabeller, radantal, datumspann, säsonger och kolumntäckning. (från projektroten eller i containern). Det visar vilka datamängder som har Parquet-filer och (om DuckDB finns lokalt) radantal per vy. Nya kolumner i Silver (t.ex. `conference_abbr`, `start_time_utc`, edge `category`/`value_*`) hamnar automatiskt i Gold-vyerna eftersom vyer bygger på `SELECT *` från Parquet.

**Kontrollera att all data i Hetzner kommer med:** Kör `python scripts/list_s3_bucket.py` (i containern: `docker exec tur-mage-ai-mage-1 bash -c "cd /home/src && python scripts/list_s3_bucket.py"`) och jämför med [documentation/DATA_SOURCES_S3.md](documentation/DATA_SOURCES_S3.md) – där står vilka S3-mappar pipelinen läser och vilka som (ännu) inte laddas. **Bronze (~100 GB) vs Silver:** S3 innehåller samma matchfiler många gånger (by_date, by_team, by_player); pipelinen läser bara by_date och sparar utplockade fält i Parquet, så Silver blir mycket mindre i GB men med samma täckning. Kör `python scripts/compare_bronze_silver_volume.py` för att se antal matcher i S3 vs Silver och förklaring till storleken.

**Analysera alla filer och strukturer (för att få ut all data till Silver/Gold):** Kör `python scripts/analyze_data_structure.py`. Det skapar `documentation/DATA_STRUCTURE_REPORT.md` och `.json` med S3-inventering, JSON-struktur per källtyp, Silver-schema och mapping. Använd rapporten för att uppdatera pipelinen. Flaggor: `--no-s3` (bara Silver), `--s3-quick` (snabb S3-scan, max 500 filer per mapp).

## Metadata‑DB (Postgres)

Repo:t är konfigurerat att använda Postgres som metadata‑databas (stabilare än sqlite för dagliga körningar).
Detta styrs via `MAGE_DATABASE_CONNECTION_URL` i `.env`.

## MinIO (externt)

Ange din externa MinIO‑endpoint i `.env` som `MINIO_ENDPOINT` och dina nycklar som `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`.
Mage kopplar då mot din befintliga MinIO.

## S3/MinIO-konfiguration (io_config.yaml)

`mage_project/io_config.yaml` använder variabler från `.env`:
- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`
- `AWS_REGION`
- `MINIO_ENDPOINT`

Mage stödjer MinIO genom att ange `AWS_ENDPOINT` i `io_config.yaml`.  
Källa: Mage S3-integrationsdokumentation (MinIO support).

## Uppgradera Mage

1. Uppdatera `MAGE_VERSION` i `.env`
2. Kör:
   ```bash
   docker compose pull
   docker compose up -d --build
   ```

## Dokumentation

- **[GOLD_SCHEMA.md](documentation/GOLD_SCHEMA.md)** – **Gold (DuckDB): alla tabeller/vyer, engelska namn, snake_case, nycklar och användning.** Start här för analytics och Streamlit.
- **[GAME_AND_PLAYER_DATA_COVERAGE.md](documentation/GAME_AND_PLAYER_DATA_COVERAGE.md)** – **Säkerställer all data per game och per player per game:** källa vs extraktion, vilka fält som finns i `games` och `game_players`.
- **[TREND_ANALYSIS.md](documentation/TREND_ANALYSIS.md)** – trendanalyser per match (lag och spelare); vilka vyer som används.
- **[KEY_EXTRACTION_ANALYSIS.md](documentation/KEY_EXTRACTION_ANALYSIS.md)** – vilka nycklar som finns i källorna vs vad pipelinen plockar ut.
- **[DATA_SOURCES_S3.md](documentation/DATA_SOURCES_S3.md)** – S3-mappar som pipelinen läser och vilka pipelines som använder dem.
- **[JSON_KEY_INVENTORY.md](documentation/JSON_KEY_INVENTORY.md)** – genererad inventering av alla JSON-nyckelvägar per källtyp (från `scripts/inventory_json_keys_from_s3.py`).

## Schemaläggning (cron / n8n)

För **återkommande uppdateringar** kan du trigga Mage-pipelines externt:

- **Cron:** Anropa Mage API (om du exponerar det) eller kör t.ex. `docker exec … mage run dimensions_pipeline` (beroende på hur Mage är konfigurerat). Kör dimensions, sedan seasonal_stats, sedan games – Gold (DuckDB) uppdateras automatiskt i sista steget av varje pipeline.
- **n8n (eller annan orchestrator):** Sätt upp flöde som kör pipelines i rätt ordning efter att ny data dykt upp i S3. Se [DATA_INGESTION_MAGE_DB.md](documentation/DATA_INGESTION_MAGE_DB.md) för strategier (full refresh vs upsert och hur man kan använda Mage som API).

## Git (valfritt men rekommenderat)

```bash
git init
git add .
git commit -m "Init Mage + MinIO docker setup"
```

## Referenser

- Mage Quickstart (Docker/Compose): https://docs.mage.ai/getting-started/setup
- Compose template: https://github.com/mage-ai/compose-quickstart
- S3/MinIO-konfiguration: https://docs.mage.ai/integrations/databases/S3
