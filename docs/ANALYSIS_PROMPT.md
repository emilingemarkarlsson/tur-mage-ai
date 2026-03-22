# Analys-prompt: NHL-datapipeline och trendstruktur

Använd denna prompt för att få en fullständig analys av projektets uppsättning, datainhämtning och strukturering för trendanalyser.

---

## Prompt

```
Analysera NHL-datapipelinen enligt nedan. Projektet består av två delar:

**1. Källprojektet (tur-nhl-api)**  
Sökväg: /Users/emilkarlsson/Documents/dev/tur-nhl-api

- Här hämtas data från NHL:s API (via nhl-api-py) och laddas upp till S3 (Hetzner/MinIO)
- Data exporteras och organiseras i nhl-data/ (teams, players, standings, stats, edge) och nhl-data-reorganized/games/
- Dokumentation: docs/HETZNER_S3_DATA_STRUCTURE_FOR_MAGE.md, docs/WHAT_DATA_IN_GAMES.md, docs/DATA_OVERVIEW.md

**2. Transformationsprojektet (tur-mage-ai)**  
Sökväg: /Users/emilkarlsson/Documents/dev/tur-mage-ai

- Mage AI i Docker med tre pipelines: dimensions_pipeline, seasonal_stats_pipeline, games_pipeline
- Läser från S3 (samma bucket som tur-nhl-api skriver till), transformerar till Silver (Parquet) och Gold (DuckDB)
- Dokumentation: README.md, documentation/GOLD_SCHEMA.md, documentation/DATA_SOURCES_S3.md, documentation/TREND_ANALYSIS.md, documentation/GAME_AND_PLAYER_DATA_COVERAGE.md

---

## Uppgifter

### A. Verifiera projektuppsättning

1. Gå igenom hur tur-mage-ai är uppsatt: Docker Compose, Mage, MinIO/Hetzner S3, io_config.yaml, .env
2. Säkerställ att konfigurationen är korrekt enligt dokumentationen (README, docs/)
3. Kontrollera att tur-nhl-api och tur-mage-ai använder samma S3-bucket/prefix och att dataflödet är konsekvent

### B. Analysera datainhämtningen (tur-nhl-api → S3)

1. Vilken data hämtas från NHL API och hur laddas den upp?
2. Vilka S3-sökvägar används? (jämför med documentation/DATA_SOURCES_S3.md)
3. Finns det data i S3 som inte laddas av Mage-pipelines? Om ja, vilken?

### C. Verifiera att pipelinen får med all data

1. Gå igenom dimensions_pipeline, seasonal_stats_pipeline och games_pipeline
2. Kontrollera att alla relevanta S3-prefix läses (nhl-data/, nhl-data-reorganized/)
3. Jämför käll-JSON med Silver-extraktion: documentation/GAME_AND_PLAYER_DATA_COVERAGE.md, documentation/KEY_EXTRACTION_ANALYSIS.md
4. Kör (eller hänvisa till) scripts som validerar täckning:
   - `scripts/list_s3_bucket.py` – vad finns i S3
   - `scripts/compare_bronze_silver_volume.py` – antal matcher i S3 vs Silver
   - `scripts/analyze_data_structure.py` – S3-inventering, JSON-struktur, Silver-schema
   - `scripts/inventory_json_keys_from_s3.py` – alla JSON-nycklar per filtyp

### D. Struktur för trendkurvor (datum per spelare, lag, match)

1. Kontrollera att datan är strukturerad utifrån datum per spelare, lag och match så att trendkurvor kan beräknas
2. Verifiera vilka Gold-vyer som används:
   - **Spelare över tid:** `player_game_stats` (game_date, player_id) – en rad per spelare per match
   - **Lag över tid:** `team_game_stats` (game_date, team_abbr) – en rad per lag per match
   - **Match-nivå:** `games` (game_date, game_id)
3. Säkerställ att alla nödvändiga fält för trender finns: game_date, player_id, team_abbr, goals, assists, points, sog, hits, m.m.
4. Utvärdera om organisationer (t.ex. conference, division) kan användas för trendanalyser – finns motsvarande fält i Gold?
5. Dokumentera eventuella luckor eller förbättringar för att underlätta trendkurvor för spelare, lag och organisationer

---

## Önskat resultat

1. **Sammanfattning** – Är projektet korrekt uppsatt och följer dokumentationen?
2. **Data coverage** – Får pipelinen med sig all relevant data från S3? Vilka eventuella luckor finns?
3. **Trendstruktur** – Är datan tillräckligt strukturerad (datum per spelare/lag/match) för trendkurvor? Vad finns redan, vad saknas?
4. **Rekommendationer** – Konkreta åtgärder för att säkerställa full datatäckning och bättre stöd för trendanalyser.
```

---

## Kortversion (för snabb användning)

```
Analysera NHL-datapipelinen:
1) Verifiera att tur-mage-ai (Mage i Docker) är korrekt uppsatt och att tur-nhl-api (API → S3) matar rätt data.
2) Säkerställ att alla tre pipelines (dimensions, seasonal_stats, games) får med sig all data från S3 – jämför med documentation/DATA_SOURCES_S3.md och GAME_AND_PLAYER_DATA_COVERAGE.md.
3) Kontrollera att Gold-strukturen (player_game_stats, team_game_stats, games) stödjer trendkurvor knutet till tid för spelare, lag och organisationer. Dokumentera luckor och ge rekommendationer.
```
