# GitOps-flöde för Mage på Coolify

Det slutgiltiga målet: **push till GitHub → Docker-image byggs automatiskt
→ Coolify pull:ar och deployar**. Koden körs från imagen, inga manuella
`docker cp` eller `rsync`.

## Arkitektur

```
┌─────────────┐      git push       ┌─────────────────┐
│  Din dev-   │ ──────────────────► │  GitHub         │
│  maskin     │                     │  tur-mage-ai    │
└─────────────┘                     │   (main)        │
                                    └────────┬────────┘
                                             │
                          GitHub Actions ────┤
                          docker-build.yml   │
                                             ▼
                                    ┌─────────────────┐
                                    │  GHCR           │
                                    │  ghcr.io/       │
                                    │  emilingemar... │
                                    │  /tur-mage-ai   │
                                    │  :latest        │
                                    └────────┬────────┘
                                             │
                   docker pull + restart ────┤
                   (via script eller         │
                    Coolify webhook)         │
                                             ▼
                                    ┌─────────────────┐
                                    │ Coolify Mage    │
                                    │ (kör GHCR-image)│
                                    └─────────────────┘
```

## Tre flöden att välja mellan

### Flöde 1 – Pseudo-GitOps via `git pull` (enklast, används idag)

**Hur:** Containerns `/home/src` är ett git-repo. Vid deploy: `git fetch + reset --hard`.

```bash
git push origin main
./scripts/sync_from_github.sh --restart
```

| Pro | Con |
|---|---|
| Enkelt, ingen image-build | Dependencies i `requirements.txt` måste installeras om vid varje container-recreate |
| Instant sync | `pip install` tar ~2 min per recreate |
| Ingen extra infra | Manuellt steg efter push |

**Se:** [MAGE_GIT_INTEGRATION.md](MAGE_GIT_INTEGRATION.md)

### Flöde 2 – GHCR-image byggs av GitHub Actions (rekommenderat)

**Hur:** GitHub Actions bygger image + pushar till GHCR. Sedan pull:as den till Coolify.

```bash
git push origin main
# GitHub Actions bygger automatiskt (~5-8 min, se Actions-tab)
./scripts/deploy_image_to_coolify.sh --tag latest
```

| Pro | Con |
|---|---|
| Dependencies bakade i imagen (ingen pip install vid restart) | 5-8 min build-tid i GitHub Actions |
| Versionerad (kan rulla tillbaka till `sha-xxx`) | Kräver att GHCR är satt upp (gratis för publika repos) |
| Mage-UI-ändringar persisterar (om volume kvar) | Manuellt `deploy_image_to_coolify.sh`-steg |

**Aktivera:**
1. Workflow `.github/workflows/docker-build.yml` finns redan i repot
2. Första gången: gå till GitHub → Actions → "Build and push Mage image" → Run workflow
3. Efter första build:en kommer den köras automatiskt vid push

**Redeploy efter build:**
- Helt automatiskt via Coolify webhook (se avsnitt längre ner)
- Eller kör `./scripts/deploy_image_to_coolify.sh`

### Flöde 3 – Full Coolify Application (mest "GitOps", kräver konvertering)

**Hur:** Konvertera Coolify Service → Application. Coolify själv bygger från GitHub.

```bash
git push origin main
# Coolify auto-deployar inom 30-60s (om webhook är aktiv)
```

| Pro | Con |
|---|---|
| Helt automatiskt, inga manuella steg | Kräver Application-konvertering (ca 20-30 min setup) |
| Coolify bygger imagen, inte GitHub | Förlora docker-compose multi-service (Postgres blir separat resource) |
| Webhook-driven | Risk att tappa volym-data vid fel konvertering |

**Steg för Application-konvertering** (att göra när du har tid):

1. **Backup databas** (redundant eftersom vi redan har daglig backup, men bättre säker):
   ```bash
   ssh tha 'bash /usr/local/bin/backup_mage_postgres.sh'
   ```

2. **Skapa nytt Coolify Application** (låt den gamla Service:en köra!):
   - Coolify UI → Projects → theunnamedroads → + New Resource → Application
   - Source: GitHub, repo: `emilingemarkarlsson/tur-mage-ai`
   - Branch: main
   - Build Pack: Docker Compose
   - Docker Compose Location: `./docker-compose.coolify.yml`
   - Domain: `mage-v2.theunnamedroads.com` (TEMPORÄR! För testning)

3. **Uppdatera `docker-compose.coolify.yml`** att använda `build:` istället för `image:`:
   ```yaml
   services:
     mage:
       build:
         context: .
         dockerfile: Dockerfile
   ```

4. **Kopiera alla env vars** från gamla Service:en till nya Application:en
   (Coolify API eller UI).

5. **Testa den nya applikationen** på `mage-v2.theunnamedroads.com`.

6. **När allt fungerar**: byt domän, radera gamla Service:en.

**Risker:**
- Postgres-volymen kopplas inte automatiskt över till nya Applikationen
- Därför: använd `pg_dump` från gamla, `pg_restore` in i nya
- Alternativt: kör båda parallellt tills gamla är tom på körningar

## Rekommendation

**För tillfället: Flöde 1** (`sync_from_github.sh`) räcker och är rent.

**Nästa steg: Flöde 2** (GHCR-image) – aktivera workflow och få snabbare restarts.
Gör det när du känner för 5 minuters setup.

**Framtida: Flöde 3** – bara om du vill ha riktig GitOps och är beredd att
göra en timmes konvertering.

## Coolify webhook för auto-deploy (gäller Flöde 2 & 3)

För att Coolify ska auto-deploya vid ny image, sätt upp en webhook:

```bash
# Generera webhook URL i Coolify UI: Project → Service → Webhooks → "Generate"
# Exempel-URL: https://coolify.example.com/api/v1/deploy?uuid=k0oooc8ok4848880sk0g0kkc&force=false

# Lägg till i .github/workflows/docker-build.yml efter push-steget:
- name: Trigger Coolify redeploy
  if: success()
  run: |
    curl -sf -X GET "${{ secrets.COOLIFY_WEBHOOK_URL }}" || echo "(webhook failed, non-fatal)"
```

Lägg till secrets i GitHub → Settings → Secrets → `COOLIFY_WEBHOOK_URL`.

## Sammanfattning: vad görs var?

| Uppgift | Var det hanteras |
|---|---|
| Edit pipeline-kod | Cursor (lokalt) eller Mage UI i produktion |
| Commit/Push | `git push origin main` |
| Image-build | GitHub Actions (när workflow aktiveras) |
| Deploy till Coolify | `./scripts/sync_from_github.sh` eller `deploy_image_to_coolify.sh` |
| Schedules | Mage UI (`/triggers`) |
| Notifikationer | `metadata.yaml` + Slack webhook |
| Backup | `/usr/local/bin/backup_mage_postgres.sh` (cron 04:00 UTC) |
| Monitorering | Coolify UI + Slack |
