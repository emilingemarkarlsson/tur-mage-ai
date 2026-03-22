# Mage i Docker → MotherDuck – steg för steg (minnes- och disksnål)

Denna guide beskriver hur du kör full data-laddning (2010–2026) i Mage AI i Docker och får allt in i MotherDuck utan att fylla Mac-disken eller få minneskrasch i containern.

---

## Översikt

| Steg | Vad som händer |
|------|----------------|
| 1 | Mage läser matchdata från S3 (Hetzner) – endast läser, ingen lokal kopiering |
| 2 | Transform extraherar games, game_players, game_events, game_stories |
| 3 | Export skriver Silver (Parquet) till `mage_project/data_lake/silver/` |
| 4 | Refresh bygger Gold (DuckDB) från Silver |
| 5 | MotherDuck-sync kopierar Gold till molnet (CREATE OR REPLACE) |

**Disk:** Silver + Gold ligger under `mage_project/data_lake/` (= din Mac via volym). Räkna med ~15–25 GB för full 2010–2026.

**Minnes:** Loadern batchar automatiskt (30 datum åt gången). Du kan minska till 15–20 för säkerhet.

---

## Före du börjar

### 1. Säkerställ att du har plats

```bash
df -h .   # Kolla ledigt utrymme i projektmappen
# Rekommenderat: minst 25 GB ledigt
```

### 2. Konfigurera `.env`

```bash
# S3-källa (Hetzner)
S3_SOURCE=hetzner
HETZNER_BUCKET=nhlhockey-data
# ... HETZNER_* credentials

# Data lake – lokalt (enklast)
DATA_LAKE_SINK=local
DATA_LAKE_PATH=/home/src/mage_project/data_lake

# Startdatum för matcher
GAMES_START_DATE=2010-01-01

# Minnesbesparande (valfritt men rekommenderat)
GAMES_BATCH_SIZE=15

# MotherDuck – synk sker automatiskt efter varje refresh
MOTHERDUCK_TOKEN=din-token
MOTHERDUCK_DATABASE_NAME=nhl
```

### 3. (Rekommenderat) Minnesgräns i Docker

Lägg till i `docker-compose.yml` under `mage` för att undvika att containern tar hela Mac-minnet:

```yaml
services:
  mage:
    # ... befintlig config ...
    deploy:
      resources:
        limits:
          memory: 4G
```

Alternativt (äldre Compose-format):

```yaml
  mage:
    mem_limit: 4g
```

---

## Steg-för-steg: Full laddning år för år

### Steg 1: Starta Mage

```bash
cd /sökväg/till/tur-mage-ai
docker compose up -d
```

Öppna: **http://localhost:6789**

### Steg 2: Rensa games-state

```bash
./scripts/reset_full_games_load.sh
```

(Requires att Docker kör. Om containern heter annat: `docker exec -i DIN_CONTAINER rm -f /home/src/mage_project/state/last_games_date.txt`)

### Steg 3: Kontrollera omfattning

```bash
python scripts/scope_games_pipeline.py
```

Visar antal datum/filer som kommer att laddas. Om `games_year.txt` finns visas omfattning för det året.

### Steg 4: Sätt första året

Skapa eller redigera `mage_project/state/games_year.txt`:

```
2010
```

### Steg 5: Kör dimensions och seasonal_stats (en gång)

I Mage UI:

1. Kör **dimensions_pipeline** (loader → transform → export → refresh)
2. Kör **seasonal_stats_pipeline**
3. Vänta tills båda är klara

### Steg 6: Kör games_pipeline (år 2010)

1. Kör **games_pipeline**
2. Loadern loggar t.ex. *"År 2010: kör automatiskt i X batchar …"*
3. Vänta tills alla batchar är klara (kan ta 10–30 min per år beroende på nätverk)
4. Efter varje batch: export → refresh → **MotherDuck-sync körs automatiskt**

### Steg 7: Nästa år

1. Redigera `mage_project/state/games_year.txt` → `2011`
2. Kör **games_pipeline** igen (bara games, inte dimensions/seasonal_stats)
3. Upprepa för 2012 … 2026

### Steg 8: Kontrollera MotherDuck

Efter varje refresh synkas tabellerna till MotherDuck. Du kan verifiera med:

```bash
python scripts/validate_motherduck.py
```

eller i MotherDuck UI: `SELECT count(*) FROM games;` osv.

---

## Minnes- och diskoptimering

| Problem | Åtgärd |
|--------|--------|
| Mage-containern går OOM (Out of Memory) | Sätt `mem_limit: 4g` i docker-compose + `GAMES_BATCH_SIZE=15` i .env |
| Fortfarande OOM | Minska till `GAMES_BATCH_SIZE=10` |
| Mac-disken fylls | Ta bort gamla år manuellt: `rm -rf mage_project/data_lake/silver/games/game_date=2010*` (eller liknande). **Obs:** Du måste köra rebuild eller ladda om för att få tillbaka data. Bättre: ha minst 25 GB ledigt från början. |
| Vill inte fylla disk med Silver | Använd `DATA_LAKE_SINK=s3` + S3_DATA_LAKE_BUCKET/PREFIX. Silver laddas upp till S3; Gold byggs lokalt, synkas till MotherDuck, laddas upp och tas bort lokalt. **Silver ligger kvar lokalt** (refresh behöver den) – disk används ändå. |

---

## Flöde till MotherDuck

```
S3 (by_date)  →  Load  →  Transform  →  Export (Silver Parquet)  →  Refresh (Gold DuckDB)
                                                                           ↓
                                                              _sync_to_motherduck()
                                                                           ↓
                                                                    MotherDuck
```

Synken sker **inom Mage-containern** efter varje `refresh_duckdb_views`. Ingen manuell export behövs.

---

## Snabbreferens

| Uppgift | Kommando / åtgärd |
|---------|-------------------|
| Reset state | `./scripts/reset_full_games_load.sh` |
| Sätt år | Skriv `2010` i `mage_project/state/games_year.txt` |
| Kolla omfattning | `python scripts/scope_games_pipeline.py` |
| Minnesgräns Docker | `mem_limit: 4g` i docker-compose |
| Mindre batchar | `GAMES_BATCH_SIZE=15` i .env |
| Validera MotherDuck | `python scripts/validate_motherduck.py` |

---

## Felsökning

**"Inga datum kvar för år X"**  
- State har redan senaste datum för året. Om du laddar om samma år: skapa `mage_project/state/games_force_refresh.txt` med innehållet `2010` (eller aktuellt år), kör igen.

**Container kraschar / OOM**  
- Minska `GAMES_BATCH_SIZE` till 10–15.  
- Lägg till `mem_limit: 4g` så att containern inte tar allt RAM.

**MotherDuck-synk fungerar inte**  
- Kontrollera `MOTHERDUCK_TOKEN` i .env.  
- Skapa databasen `nhl` i MotherDuck UI om den inte finns.

**Disk full**  
- Silver + Gold växer år för år. Ta bort äldre Silver-partitioner om du inte behöver dem (kräver omkörning för att återställa).
