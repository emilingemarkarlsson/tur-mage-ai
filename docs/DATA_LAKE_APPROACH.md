# Data Lake: läsa från S3, bygga Silver + Gold lokalt

## Approach

- **Källa (read-only):** S3 (t.ex. Hetzner) – `nhl-data-reorganized/games/by_date/` m.m. Pipelines **läser** härifrån.
- **Silver (Parquet):** skrivs **lokalt** i `mage_project/data_lake/silver/` (och eventuellt till S3 om du vill).
- **Gold (DuckDB):** byggs **lokalt** i `mage_project/data_lake/gold/nhl.duckdb` från lokal Silver. Ingen S3-flaskhals vid refresh.
- **Senare:** migrera hela det lokala projektet (kod + `data_lake/`) till ny miljö eller t.ex. MotherDuck.

## Konfiguration

I `.env`:

```bash
# Läs från S3 (Hetzner) – oförändrat
S3_SOURCE=hetzner
HETZNER_BUCKET=nhlhockey-data
# ... HETZNER_* credentials

# Skriv Silver och Gold ENDAST lokalt (minskar S3-flaskhals, enklare migrering)
DATA_LAKE_SINK=local
```

Med `DATA_LAKE_SINK=local`:

- **export_games_parquet** (och andra exporters) skriver bara till `DATA_LAKE_PATH` (lokalt i containern = monterad volym på din maskin).
- **refresh_duckdb_views** bygger Gold från lokala Parquet-filer och **laddar inte upp** något till S3.
- Streamlit och validering använder den lokala filen: sätt t.ex.  
  `DUCKDB_VIEWER_PATH=/absolut/sökväg/till/tur-mage-ai/mage_project/data_lake/gold/nhl.duckdb`  
  eller låt default (samma sökväg) gälla.

## Flöde

1. **Mage (Docker):** games_pipeline läser från S3 → transform → skriver Silver lokalt → refresh bygger Gold lokalt. Allt ligger under `mage_project/data_lake/` (volym = din disk).
2. **Streamlit / validate:** kör lokalt mot `mage_project/data_lake/gold/nhl.duckdb`.
3. **Migrering:** kopiera `mage_project/` (inkl. `data_lake/`) till nytt repo eller export Gold till MotherDuck/annan destination.

## Om du vill skriva Silver till S3 ändå

Sätt `DATA_LAKE_SINK=s3` och fyll i `S3_DATA_LAKE_BUCKET` / `S3_DATA_LAKE_PREFIX`. Då skrivs Silver (och vid refresh Gold) till S3. För att bara bygga Gold lokalt från befintlig S3-Silver kan du använda:

```bash
BUILD_GOLD_LOCAL_ONLY=1 python scripts/rebuild_gold_from_s3.py
```

Se `scripts/rebuild_gold_from_s3.py` och `docs/GAMES_LOADING.md`.
