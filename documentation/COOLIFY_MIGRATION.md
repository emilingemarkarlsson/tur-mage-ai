# Coolify Migration – Runbook

Detta dokument beskriver hur `tur-mage-ai` migrerades från lokal Docker till Coolify-hostat Mage på `mage.theunnamedroads.com`, och hur du gör nya code-deploys framöver.

## Nuvarande tillstånd (efter migrering 2026-04-19)

| Komponent | Värde |
|---|---|
| Coolify server | `tha` (46.62.206.47) |
| Coolify projekt | `theunnamedroads platform` (UUID `d48sskwogoswsw00wkwww0wg`) |
| Coolify service | `mage-tur` (UUID `k0oooc8ok4848880sk0g0kkc`) – **Service**, docker-compose raw |
| Mage container | `mage-k0oooc8ok4848880sk0g0kkc` |
| Postgres container | `postgres-k0oooc8ok4848880sk0g0kkc` |
| Domän | `https://mage.theunnamedroads.com` (Traefik + Let's Encrypt auto) |
| Project UUID | `596d7a5303b545248d4f59e24cb785f2` (samma som lokalt) |
| `DATA_LAKE_SINK` | `s3` (skriver till Hetzner `s3://nhlhockey-data/nhl-analytics/`) |

### Volymer (namngivna, persisterar mellan redeploys)

- `k0oooc8ok4848880sk0g0kkc_mage-code` → `/home/src` – innehåller `mage_project/`, `scripts/`
- `k0oooc8ok4848880sk0g0kkc_mage-data-lake` → `/home/src/mage_project/data_lake` – lokal Silver/Gold-cache
- `k0oooc8ok4848880sk0g0kkc_postgres-data` → Postgres metadata-DB

## Arkitektur-skillnader mot lokal setup

| Aspekt | Lokalt (`docker-compose.yml`) | Coolify (`docker-compose.coolify.yml`) |
|---|---|---|
| Kod-mount | Bind mount `.:/home/src` – direkta ändringar syns | Namngiven volym `mage_code:/home/src` – kod måste deployas |
| Build | Dockerfile + `pip install -r requirements.txt` | Raw `mageai/mageai:latest` (inga extra deps installerade i imagen) |
| `DATA_LAKE_SINK` | `s3` | `s3` (satt nu) |
| Routing | `localhost:6789` | Traefik + Let's Encrypt via Coolify-labels |
| Schedules | Inga (manuellt triggade) | Inga (manuellt triggade) |

**Det viktigaste att komma ihåg:** Coolify-varianten har en **tom volym** för `/home/src` vid första start. All kod måste kopieras in.

## Hur migreringen gick till (engångsåtgärd)

### Förberedelse

`~/.coolify-token` innehåller Coolify API-token. Används som Bearer-auth mot `http://localhost:8000/api/v1` **från servern** (porten är inte exponerad publikt).

### Steg 1 – Paketera kod

```bash
cd /Users/emilkarlsson/Documents/dev/tur-mage-ai

tar czf /tmp/mage_migration.tar.gz \
  --exclude='mage_project/data_lake' \
  --exclude='mage_project/.ssh_tunnel' \
  --exclude='__pycache__' --exclude='.DS_Store' --exclude='*.pyc' \
  mage_project/

tar czf /tmp/mage_scripts.tar.gz \
  --exclude='__pycache__' --exclude='.DS_Store' --exclude='*.pyc' \
  scripts/
```

### Steg 2 – Ladda upp till server

```bash
scp /tmp/mage_migration.tar.gz tha:/tmp/
scp /tmp/mage_scripts.tar.gz tha:/tmp/
```

### Steg 3 – In i containern

```bash
MAGE=mage-k0oooc8ok4848880sk0g0kkc

# Backup gammal tom struktur (kan raderas senare)
ssh tha "docker exec $MAGE sh -c 'mv /home/src/mage_project /home/src/mage_project.bak-\$(date +%s) 2>/dev/null || true'"

# Kopiera och extrahera kod
ssh tha "docker cp /tmp/mage_migration.tar.gz $MAGE:/tmp/"
ssh tha "docker exec $MAGE sh -c 'cd /home/src && tar xzf /tmp/mage_migration.tar.gz && rm /tmp/mage_migration.tar.gz'"

# Kopiera scripts
ssh tha "docker cp /tmp/mage_scripts.tar.gz $MAGE:/tmp/"
ssh tha "docker exec $MAGE sh -c 'cd /home/src && tar xzf /tmp/mage_scripts.tar.gz && rm /tmp/mage_scripts.tar.gz'"

# Städa macOS-metadata och fixa ägarskap
ssh tha "docker exec $MAGE sh -c 'find /home/src/mage_project -name \"._*\" -delete; find /home/src/scripts -name \"._*\" -delete; chown -R root:root /home/src/mage_project /home/src/scripts'"
```

### Steg 4 – Installera saknade Python-beroenden

`mageai/mageai:latest` har `boto3`, `polars`, `openai` men saknar:
- `duckdb>=1.4.4` (imagen har 1.0.0)
- `motherduck`
- `pyyaml`, `python-dotenv`

```bash
ssh tha "docker exec $MAGE pip install --quiet 'duckdb>=1.4.4' motherduck pyyaml python-dotenv"
```

> **Varning:** Dessa paket försvinner om containern recreate:as av Coolify (vid ny deploy med annan image). Se "Hur man gör det persistent" nedan.

### Steg 5 – Uppdatera Coolify env-variabler

Via Coolify API (`http://localhost:8000/api/v1/services/$SVC/envs`):

- **PATCH** `DATA_LAKE_SINK=s3` (var `local`)
- **POST** `AWS_ACCESS_KEY_ID` = värdet av `MINIO_ACCESS_KEY`
- **POST** `AWS_SECRET_ACCESS_KEY` = värdet av `MINIO_SECRET_KEY`
- **POST** `AWS_REGION=us-east-1`
- **POST** `PROJECT_NAME=mage_project`
- **POST** `ENV=production`
- **POST** `MAGE_VERSION=latest`

Exempel:
```bash
TOKEN=$(cat ~/.coolify-token)
SVC=k0oooc8ok4848880sk0g0kkc

ssh tha "curl -s -X PATCH \
  -H 'Authorization: Bearer $TOKEN' \
  -H 'Content-Type: application/json' \
  -d '{\"key\":\"DATA_LAKE_SINK\",\"value\":\"s3\"}' \
  http://localhost:8000/api/v1/services/$SVC/envs"

ssh tha "curl -s -X POST \
  -H 'Authorization: Bearer $TOKEN' \
  -H 'Content-Type: application/json' \
  -d '{\"key\":\"AWS_REGION\",\"value\":\"us-east-1\"}' \
  http://localhost:8000/api/v1/services/$SVC/envs"
```

### Steg 6 – Starta om och verifiera

```bash
ssh tha "docker restart $MAGE"
curl -s -o /dev/null -w "%{http_code}\n" https://mage.theunnamedroads.com/
# Ska svara 200
```

---

## Hur du gör code-deploys framöver

**`/home/src/` inuti Mage-containern är ett git-repo kopplat till GitHub.**
Se [MAGE_GIT_INTEGRATION.md](MAGE_GIT_INTEGRATION.md) för PAT-setup och Mage UI:ns
Git-integration.

### Alternativ A – Git pull (rekommenderat)

Förutsätter att ändringarna är pushade till GitHub:

```bash
cd /Users/emilkarlsson/Documents/dev/tur-mage-ai
git push origin main
./scripts/sync_from_github.sh --restart
```

Scriptet kör `git fetch + reset --hard` i containern och restart:ar om `--restart`.
Oommitted ändringar i containern (t.ex. från Mage UI) stashas automatiskt
innan reset för att inte försvinna.

### Alternativ B – Direkt rsync (för oommitted lokala ändringar)

När du vill testa något i Coolify innan du commit:ar:

```bash
cd /Users/emilkarlsson/Documents/dev/tur-mage-ai
./scripts/deploy_to_coolify.sh --restart
```

Använder tar + docker cp (kringgår git helt).

### Alternativ B – GitOps via Dockerfile-bake (rekommenderad långsiktig lösning)

Detta kräver att servicen görs om från "Service" till "Application" i Coolify UI. Fördelar: push till GitHub → auto-deploy.

1. Uppdatera `Dockerfile` så den kopierar in `mage_project/` och `scripts/`:
   ```dockerfile
   ARG MAGE_VERSION=latest
   FROM mageai/mageai:${MAGE_VERSION}

   ARG PROJECT_NAME=mage_project
   ARG USER_CODE_PATH=/home/src/${PROJECT_NAME}

   COPY requirements.txt ${USER_CODE_PATH}/requirements.txt
   RUN pip3 install -r ${USER_CODE_PATH}/requirements.txt

   COPY mage_project/ ${USER_CODE_PATH}/
   COPY scripts/ /home/src/scripts/
   ```

2. I Coolify UI: ta bort `mage-tur`-servicen och skapa ny **Application** med:
   - Source: GitHub (`emilingemarkarlsson/tur-mage-ai`, branch `main`)
   - Build Pack: Docker Compose
   - Docker Compose Location: `/docker-compose.coolify.yml`
   - Volumes: återanvänd `k0oooc8ok4848880sk0g0kkc_postgres-data` och `k0oooc8ok4848880sk0g0kkc_mage-data-lake` om du vill behålla metadata + data_lake

3. Lägg till `build:`-block i `docker-compose.coolify.yml`:
   ```yaml
   services:
     mage:
       build:
         context: .
         dockerfile: Dockerfile
         args:
           MAGE_VERSION: ${MAGE_VERSION:-latest}
           PROJECT_NAME: ${PROJECT_NAME:-mage_project}
       # ta bort image: rad eller behåll som fallback
   ```

4. **Ta bort** `mage_code:/home/src`-volymen (koden bakas in) – behåll `mage_data_lake:/home/src/mage_project/data_lake` (data persisterar) och ev. lägg till `mage_state:/home/src/mage_project/state` så state-filer överlever deploys.

Detta är den "riktiga" lösningen men kräver att du river och bygger om servicen. Nuvarande (Alternativ A) fungerar tills du har tid.

---

## Hur du uppdaterar env-variabler framöver

Via Coolify UI → `theunnamedroads platform` → `mage-tur` → Environment Variables.

Eller via API (kräver token från `~/.coolify-token`):

```bash
TOKEN=$(cat ~/.coolify-token)
SVC=k0oooc8ok4848880sk0g0kkc

# Uppdatera befintlig
ssh tha "curl -s -X PATCH -H 'Authorization: Bearer $TOKEN' -H 'Content-Type: application/json' \
  -d '{\"key\":\"GAMES_START_DATE\",\"value\":\"2025-01-01\"}' \
  http://localhost:8000/api/v1/services/$SVC/envs"

# Skapa ny
ssh tha "curl -s -X POST -H 'Authorization: Bearer $TOKEN' -H 'Content-Type: application/json' \
  -d '{\"key\":\"NEW_VAR\",\"value\":\"something\"}' \
  http://localhost:8000/api/v1/services/$SVC/envs"

# Lista alla
ssh tha "curl -s -H 'Authorization: Bearer $TOKEN' http://localhost:8000/api/v1/services/$SVC/envs" | python3 -m json.tool
```

Env-ändringar kräver redeploy eller `docker restart`.

---

## Backfill / full reload i Coolify

State-filerna finns nu i `/home/src/mage_project/state/` i containern (kopierade från lokalt):
- `last_games_date.txt` = `2026-03-21`
- `last_swe_date_*.txt` = per år
- `swe_pdf_processed.txt` = lista på processade PDF-IDs

För att tvinga full backfill:

```bash
# NHL games från 2010
ssh tha "docker exec $MAGE rm -f /home/src/mage_project/state/last_games_date.txt"

# Specifikt år
ssh tha "docker exec $MAGE sh -c 'echo 2010 > /home/src/mage_project/state/games_year.txt'"
```

---

## Troubleshooting

### "Pipelines visas inte i UI"
- Verifiera att filerna finns: `ssh tha "docker exec $MAGE ls /home/src/mage_project/pipelines/"`
- Restart container: `ssh tha "docker restart $MAGE"`
- Kolla logs: `ssh tha "docker logs --tail 100 $MAGE"`

### "ImportError / ModuleNotFoundError"
- Python-deps är installerade per container-runtime (inte i imagen). Om containern recreates försvinner de. Kör om:
  ```bash
  ssh tha "docker exec $MAGE pip install --quiet 'duckdb>=1.4.4' motherduck pyyaml python-dotenv"
  ```

### "S3 / Hetzner / MinIO credentials funkar inte"
- `io_config.yaml` läser `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` (nu satt till MinIO-värdena).
- Hetzner-specifika loaders läser `HETZNER_*` direkt.
- MinIO-specifika exporters läser `MINIO_*` direkt.
- Verifiera env inne i container: `ssh tha "docker exec $MAGE env | grep -E 'AWS|HETZNER|MINIO'"`

### "Backfill startar från 2010 oavsett vad jag gör"
- State-filerna försvann. Kopiera in dem från lokalt igen (se Steg 3 ovan, men bara `mage_project/state/`).

### "Mage-postgres förlorar data vid redeploy"
- Volymen `k0oooc8ok4848880sk0g0kkc_postgres-data` är namngiven och persisterar. Kontrollera: `ssh tha "docker volume ls | grep k0oooc"`.

---

## Referens: env-variabler som är satta i Coolify

```
DATA_LAKE_PATH                      = /home/src/mage_project/data_lake
DATA_LAKE_SINK                      = s3
GAMES_BATCH_SIZE                    = 10
GAMES_START_DATE                    = 2010-01-01
HETZNER_ACCESS_KEY                  = D63PPYVS6MRR4JTBDOB3
HETZNER_BUCKET                      = nhlhockey-data
HETZNER_ENDPOINT                    = hel1.your-objectstorage.com
HETZNER_REGION                      = eu-central
HETZNER_SECRET_KEY                  = (secret)
LITELLM_API_KEY                     = (secret)
LITELLM_BASE_URL                    = http://litellm-kkswc8gokk84c0o8oo84w44w.46.62.206.47.sslip.io
LITELLM_DEFAULT_MODEL               = gemini-flash
LITELLM_MAX_INSIGHTS                = 5
MINIO_ACCESS_KEY                    = pT500GOPQaHL8QFQ
MINIO_BUCKET                        = nhl-gold
MINIO_ENDPOINT                      = https://minio-api.thehockeyanalytics.com
MINIO_GOLD_BUCKET                   = nhl-gold
MINIO_REGION                        = us-east-1
MINIO_SECRET_KEY                    = (secret)
MOTHERDUCK_DATABASE_NAME            = nhl
MOTHERDUCK_TOKEN                    = (secret)
POSTGRES_DB                         = mage
POSTGRES_PASSWORD                   = (secret)
POSTGRES_USER                       = mage
REFRESH_USE_S3_FALLBACK_FOR_GAMES   = 0
S3_DATA_LAKE_BUCKET                 = nhlhockey-data
S3_DATA_LAKE_PREFIX                 = nhl-analytics
S3_SOURCE                           = hetzner
AWS_ACCESS_KEY_ID                   = pT500GOPQaHL8QFQ    (= MINIO_ACCESS_KEY, io_config.yaml)
AWS_SECRET_ACCESS_KEY               = (secret)            (= MINIO_SECRET_KEY, io_config.yaml)
AWS_REGION                          = us-east-1
PROJECT_NAME                        = mage_project
ENV                                 = production
MAGE_VERSION                        = latest
```

---

## Nästa steg (TODO)

- [x] Skapa `scripts/deploy_to_coolify.sh` för snabb code-sync
- [x] Git-integration på plats – se [MAGE_GIT_INTEGRATION.md](MAGE_GIT_INTEGRATION.md)
- [x] `scripts/sync_from_github.sh` – git pull-baserad deploy
- [x] Uppdatera `tur-coolify-setup/SERVICES.md` med `mage-tur` som aktiv service
- [x] Postgres-backup cron (`pg_dump` → MinIO dagligen) – `/usr/local/bin/backup_mage_postgres.sh`
- [x] Slack-notifieringar vid pipeline-fel – se [MAGE_NOTIFICATIONS.md](MAGE_NOTIFICATIONS.md)
- [x] Dockerfile uppdaterad – bakar in kod + deps (förberedelse för GHCR)
- [x] Dokumenterat schedule-rekommendationer – se [MAGE_SCHEDULES.md](MAGE_SCHEDULES.md)
- [x] GitHub Actions-workflow för att bygga + pusha image till GHCR (`.github/workflows/docker-build.yml`)
- [x] `scripts/deploy_image_to_coolify.sh` för att pull:a ny GHCR-image
- [x] GitOps-flöde dokumenterat – se [GITOPS_FLOW.md](GITOPS_FLOW.md)
- [ ] **Manuella steg kvar (kräver att du klickar i UI):**
  - [ ] Skapa GitHub PAT och klistra in i Mage UI (se MAGE_GIT_INTEGRATION.md)
  - [ ] Konfigurera schedules/triggers i Mage UI (se MAGE_SCHEDULES.md)
  - [ ] Trigga första GHCR-build:en via Actions-tab → "Run workflow"
- [ ] **Framtida förbättringar:**
  - [ ] Lägg till Coolify webhook-secret i GitHub för auto-deploy efter image-build
  - [ ] Överväg konvertera Coolify Service → Application för ren GitOps (se GITOPS_FLOW.md)
  - [ ] Migrera `pg_dump` från lokal Postgres om du vill ta med run history / variables
