# Mage Pipeline Schedules – Rekommendationer

Detta dokument föreslår schemaläggning för samtliga 7 pipelines. Schedules
sätts upp i Mage UI:n och sparas i Postgres-metadata-DB:n (som backas upp
dagligen till S3).

## Snabbreferens

| Pipeline | Syfte | Körtid (~) | Föreslaget schema | Kommentar |
|---|---|---|---|---|
| `dimensions_pipeline` | Team/player-dimensions från NHL | 1-2 min | Daily 02:00 UTC | Liten, körs innan games |
| `games_pipeline` | NHL-matcher (incremental) | 10-30 min | Daily 03:00 UTC | `last_games_date.txt` styr backfill |
| `seasonal_stats_pipeline` | Aggregat per säsong | 2-5 min | Daily 04:00 UTC | Körs efter games |
| `analytics_pipeline` | Silver→Gold | 5-10 min | Daily 05:00 UTC | Körs sist |
| `swe_games_pipeline` | SHL/HockeyAllsvenskan JSON | 5-10 min | Daily 06:00 UTC | Flera `last_swe_date_YYYY.txt` |
| `swe_pdf_pipeline` | SHL PDF-extraktion | 10-20 min | Daily 07:00 UTC | Tung, körs efter swe_games |
| `base_pipeline` | Smoke-test / health check | < 1 min | Inga schedules | Testas manuellt vid behov |

**Backup körs 04:00 UTC** (host cron), så matcherna med analytics-tiden
blir seriellt utspridda.

## Hur du sätter upp schedules

Per pipeline:

1. Logga in på <https://mage.theunnamedroads.com/>
2. Öppna pipeline i vänstermenyn (t.ex. `dimensions_pipeline`)
3. Klicka på **Triggers** i sidopanelen (klockikon)
4. **+ Create** → välj typ:
   - **Schedule** (cron-baserad) för automatisk körning
   - **API trigger** om du vill trigga utifrån
5. Fyll i:
   - **Name:** `daily_02_utc` (fritt valt)
   - **Frequency:** `daily`
   - **Start time:** `02:00`
   - **Settings → Timeout in seconds:** 3600 (1h, lämpligt för små pipelines; öka för games_pipeline till 7200)
   - **Settings → Skip if previous running:** ✓ (förhindrar dubbla körningar)
6. **Save** → **Enable trigger**

## Dependency-setup (pipeline-A triggar pipeline-B när A slutar)

Mage stödjer även "Event-based" triggers. Så du kan göra:

| Trigger-typ | Användning |
|---|---|
| **Schedule** | Startar pipeline enligt cron |
| **Event** → *Pipeline run status change* | Trigga pipeline-B när pipeline-A slutat framgångsrikt |
| **API** | Trigga från externa scripts |

**Rekommenderat dependency-flöde** (efter att dimensions har körts dagligen):

```
dimensions_pipeline (02:00)
    ↓ on_success
games_pipeline
    ↓ on_success
seasonal_stats_pipeline
    ↓ on_success
analytics_pipeline
```

Detta säkerställer att analytics alltid har färsk data.

## Cron-uttryck (alternativ syntax)

Om du föredrar cron över "daily" i UI:n:

| Cron | Beskrivning |
|---|---|
| `0 2 * * *` | Varje dag 02:00 UTC |
| `0 */6 * * *` | Var 6:e timme |
| `0 2 * * 1-5` | Måndag-fredag 02:00 UTC |
| `0 2 1 * *` | Första i varje månad 02:00 UTC |

## Monitorering

Efter första veckan – kolla att schedules faktiskt har kört:

```bash
ssh tha 'docker exec postgres-k0oooc8ok4848880sk0g0kkc psql -U mage -d mage -c "
SELECT
    ps.name,
    ps.pipeline_uuid,
    pr.status,
    pr.execution_date,
    pr.created_at
FROM pipeline_run pr
JOIN pipeline_schedule ps ON pr.pipeline_schedule_id = ps.id
ORDER BY pr.created_at DESC
LIMIT 20;"'
```

Eller i Mage UI:n under **Pipeline runs** i vänstermenyn.

## Viktigt: State-filer och incremental loads

De befintliga `state/`-filerna ligger nu i Mage-containern (se
[COOLIFY_MIGRATION.md](COOLIFY_MIGRATION.md)):

```
/home/src/mage_project/state/
├── last_games_date.txt        # → games_pipeline startar här
├── last_swe_date_YYYY.txt     # → swe_games_pipeline per säsong
├── swe_pdf_processed.txt      # → swe_pdf_pipeline (filer att hoppa över)
└── games_year.txt             # → backfill-kontroll
```

När pipelines kör via schedule uppdaterar de själva dessa filer. Om du
behöver tvinga backfill, rensa berörd fil innan nästa schedulerad körning.

Dessa filer ÄR persistenta (i `mage_code`-volymen) – de försvinner inte
vid restart/redeploy.

## Varningsignaler

- **Pipeline hängar sig:** kolla `pipeline_run`-tabellen för runs utan
  `completed_at`. Kan behöva manual cancel i UI.
- **Backup-botarna kraschar:** kolla `/var/log/mage-backup.log` på host.
- **Disk fylls upp:** kolla `df -h` på servern. `mage_data_lake`-volymen
  kan växa snabbt om `DATA_LAKE_SINK=local`.
