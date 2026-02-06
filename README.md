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

Pipelines i repo:t skriver Parquet‑filer till `DATA_LAKE_PATH` (default `mage_project/data_lake`).
DuckDB‑filen skapas lokalt i `mage_project/data_lake/gold/nhl.duckdb` under körning.
När `DATA_LAKE_SINK=s3`: Parquet och `nhl.duckdb` laddas upp till S3 (t.ex. `nhl-analytics/silver/...` och `nhl-analytics/gold/nhl.duckdb`). **Den lokala DuckDB‑filen tas bort efter uppladdning** så att S3 är enda kopian och disken inte fylls. Streamlit‑viewern kan läsa direkt från S3 (read‑only) – kryssa i "Använd S3 (Hetzner) från .env" eller ange sökväg `s3://bucket/prefix/gold/nhl.duckdb`.

## Full laddning i Mage (alla pipelines → Streamlit)

För att köra **full laddning av all data** enligt planen och sedan använda Streamlit:

### 1. Konfiguration

- I `.env`: sätt `GAMES_START_DATE=2010-01-01` (eller tidigaste datum du har data för). För endast senaste säsong kan du använda t.ex. `2025-01-01`.
- Sätt `DATA_LAKE_SINK=s3` och `S3_DATA_LAKE_BUCKET` / `S3_DATA_LAKE_PREFIX` om Silver ska skrivas till Hetzner.

### 2. Rensa incremental state (vid full omkörning av games)

Om du vill att **games_pipeline** ska läsa **alla** datum från källan (inte bara nya sedan förra körningen):

```bash
./scripts/reset_full_games_load.sh
```

Alternativt (om container heter annat):

```bash
docker exec -it tur-mage-ai-mage-1 rm -f /home/src/mage_project/state/last_games_date.txt
```

### 3. Starta Mage och kör pipelines i ordning

1. `docker compose up -d`
2. Öppna Mage: **http://localhost:6789**
3. Kör i Mage UI (i denna ordning):
   - **dimensions_pipeline** (teams, players, countries, roster, schedule, game_ids, glossary, draft)
   - **seasonal_stats_pipeline**
   - **games_pipeline** (kan ta lång tid vid full backfill – många JSON-filer från S3)
   - **refresh_duckdb_views** (uppdaterar `gold/nhl.duckdb` från alla Silver-Parquet)

Efter det ligger Silver i `mage_project/data_lake/silver/` (och i S3 om `DATA_LAKE_SINK=s3`) och Gold i `mage_project/data_lake/gold/nhl.duckdb`.

### 4. Starta Streamlit och koppla till DuckDB

Viewern kan antingen läsa en **lokal** DuckDB‑fil (t.ex. `mage_project/data_lake/gold/nhl.duckdb`) eller **direkt från S3** (ingen lokal kopia). När du kör med `DATA_LAKE_SINK=s3` finns databasen bara i S3 – använd då i viewern kryssrutan "Använd S3 (Hetzner) från .env" eller sökväg `s3://bucket/prefix/gold/nhl.duckdb`.

**I containern (samma volym som Mage):**

```bash
docker exec -it tur-mage-ai-mage-1 streamlit run /home/src/streamlit_viewer.py --server.address 0.0.0.0 --server.port 8501
```

Öppna **http://localhost:8501**. Välj tabell/vy i sidofältet och bläddra i data.

**Lokalt (om du har Python + duckdb + streamlit):**

```bash
cd /sökväg/till/tur-mage-ai
streamlit run streamlit_viewer.py
```

Sökvägen till DuckDB i sidofältet ska vara `mage_project/data_lake/gold/nhl.duckdb` (relativt projektroten).

## S3‑källa (Hetzner eller MinIO)

Du kan välja källa med `S3_SOURCE`:
- `S3_SOURCE=hetzner` använder `HETZNER_*`
- `S3_SOURCE=minio` använder `MINIO_*`

Se `.env.example` för alla variabler.

**Validera Silver och Gold:** Kör `python scripts/validate_silver_gold.py` (från projektroten eller i containern). Det visar vilka datamängder som har Parquet-filer och (om DuckDB finns lokalt) radantal per vy. Nya kolumner i Silver (t.ex. `conference_abbr`, `start_time_utc`, edge `category`/`value_*`) hamnar automatiskt i Gold-vyerna eftersom vyer bygger på `SELECT *` från Parquet.

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

- **[KEY_EXTRACTION_ANALYSIS.md](documentation/KEY_EXTRACTION_ANALYSIS.md)** – vilka nycklar som finns i källorna vs vad pipelinen plockar ut, och åtgärder för att få med så mycket som möjligt.
- **[TREND_ANALYSIS.md](documentation/TREND_ANALYSIS.md)** – vilken statistik som finns tillgänglig för trendanalyser (lag och spelare per match).
- **[DATA_SOURCES_S3.md](documentation/DATA_SOURCES_S3.md)** – S3-mappar som pipelinen läser och vilka pipelines som använder dem.
- **[JSON_KEY_INVENTORY.md](documentation/JSON_KEY_INVENTORY.md)** – genererad inventering av alla JSON-nyckelvägar per källtyp (från `scripts/inventory_json_keys_from_s3.py`).

## Schemaläggning (cron / n8n)

För **återkommande uppdateringar** kan du trigga Mage-pipelines externt:

- **Cron:** Anropa Mage API (om du exponerar det) eller kör t.ex. `docker exec … mage run dimensions_pipeline` (beroende på hur Mage är konfigurerat). Kör först dimensions och seasonal_stats, sedan games (ev. med inkrementellt datum), slutligen refresh_duckdb_views.
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
