# Mage AI – Git-integration på Coolify

Den här guiden beskriver hur du versionshanterar Mage-pipelines i Coolify via GitHub.

## Arkitektur

```
┌─────────────────┐       git push/pull       ┌─────────────────┐
│  Lokal Cursor   │ ◄────────────────────────►│  GitHub         │
│  tur-mage-ai    │                            │  tur-mage-ai    │
└─────────────────┘                            │  (main branch)  │
                                                └────────┬────────┘
                                                         │
                                                         │ git pull
                                                         │ (public fetch /
                                                         │  PAT för push)
                                                         ▼
                                                ┌─────────────────┐
                                                │  Mage Coolify   │
                                                │  /home/src/     │
                                                │  (git repo)     │
                                                └─────────────────┘
```

Koden i `/home/src/` inuti `mage-k0oooc8ok4848880sk0g0kkc`-containern är ett
riktigt git-repo kopplat till `origin/main` på GitHub. Gitignored paths
(`mage_data/`, `mage_project/state/`, `mage_project/data_lake/`,
`mage_project/metadata.yaml`) rörs aldrig av git-operationer.

## Två arbetssätt

### A. Utveckling lokalt (primärt, rekommenderat)

1. Redigera pipelines i din Cursor-miljö (`mage_project/...`)
2. Testa lokalt med `docker compose up`
3. Commit + push till GitHub:
   ```bash
   git add mage_project/
   git commit -m "feat: new pipeline step"
   git push origin main
   ```
4. Synka till Coolify + restart:
   ```bash
   ./scripts/sync_from_github.sh --restart
   ```

### B. Redigering i Mage UI (direkt i produktion)

För att commit:a och pusha ändringar som du gjort i Mage UI:n behöver du
en GitHub Personal Access Token.

#### 1. Skapa en Fine-grained Personal Access Token

1. Gå till <https://github.com/settings/personal-access-tokens/new>
2. **Token name:** `mage-coolify`
3. **Expiration:** 1 år (eller "No expiration" om du vill)
4. **Repository access:** Only select repositories → `tur-mage-ai`
5. **Permissions → Repository permissions:**
   - **Contents:** Read and write
   - **Metadata:** Read-only (läggs automatiskt)
6. Klicka **Generate token**, kopiera direkt (visas bara en gång)

#### 2. Konfigurera Mage UI

Gå till <https://mage.theunnamedroads.com/settings/workspace/git>

Fyll i:
| Fält | Värde |
|---|---|
| **Repository URL** | `https://github.com/emilingemarkarlsson/tur-mage-ai.git` |
| **Branch** | `main` |
| **Username** | `emilingemarkarlsson` |
| **Email** | din GitHub-email |
| **Authentication type** | HTTPS |
| **Access token** | (klistra in PAT från steg 1) |

Spara. Mage testar anslutningen automatiskt.

#### 3. Alternativ: via Coolify env vars (persistent även vid container-recreate)

I Coolify Mage-service → Environment Variables, lägg till:

```
GIT_REPO_LINK=https://github.com/emilingemarkarlsson/tur-mage-ai.git
GIT_BRANCH=main
GIT_USERNAME=emilingemarkarlsson
GIT_EMAIL=din@email.com
GIT_ACCESS_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxx
GIT_SYNC_ON_PIPELINE_RUN=0
GIT_SYNC_ON_START=0
```

OBS: markera `GIT_ACCESS_TOKEN` som secret i Coolify-UI:n. Starta om
containern för att env vars ska tas upp.

## Flöden

### Pull senaste från GitHub till Coolify

```bash
./scripts/sync_from_github.sh --restart
```

eller direkt:

```bash
ssh tha 'docker exec mage-k0oooc8ok4848880sk0g0kkc \
  git -C /home/src pull origin main'
```

### Commit från Mage UI

1. Gör ändring i UI (t.ex. redigera en transformer)
2. Gå till Git-ikonen (övre högra hörnet) eller Settings → Git
3. Se "Files changed" – välj filer
4. Skriv commit message → "Commit"
5. "Push" till origin/main
6. Lokalt: `git pull origin main` för att synka ner

### Commit från CLI inuti containern

```bash
ssh tha
docker exec -it mage-k0oooc8ok4848880sk0g0kkc bash
cd /home/src
git add mage_project/pipelines/your_pipeline/
git commit -m "fix: edge case in transformer"
git push origin main   # kräver att GIT_ACCESS_TOKEN är satt
```

## Säkerhetsnät

### Uncommitted ändringar skyddas vid pull

`sync_from_github.sh` kör automatiskt `git stash` på oommitted ändringar
innan `git reset --hard`. Dvs. om någon redigerat filer i containern direkt
(utan Mage UI) försvinner de inte:

```bash
ssh tha 'docker exec mage-k0oooc8ok4848880sk0g0kkc \
  git -C /home/src stash list'
# stash@{0}: On main: auto-stash before pull 2026-04-19T12:34:56

ssh tha 'docker exec mage-k0oooc8ok4848880sk0g0kkc \
  git -C /home/src stash show -p stash@{0}'   # visa vad som stashat
```

### State-filer (inkrementell load) är gitignored

Filerna i `mage_project/state/` (t.ex. `last_games_date.txt`) ligger i
`.gitignore` och påverkas INTE av git-operationer. De är unika per miljö
(lokal vs produktion).

### Rollback till tidigare version

```bash
ssh tha 'docker exec mage-k0oooc8ok4848880sk0g0kkc bash -c \
  "cd /home/src && git reset --hard HEAD~1 && docker restart"'
```

Eller rebase till en specifik commit:
```bash
ssh tha 'docker exec mage-k0oooc8ok4848880sk0g0kkc \
  git -C /home/src reset --hard <commit-sha>'
```

## Rekommenderat flöde framåt

1. **Redigera primärt lokalt** i Cursor (bättre diff-verktyg, AI-hjälp)
2. **Testa lokalt** med `docker compose up`
3. **Commita + pusha till main**
4. **Kör `./scripts/sync_from_github.sh --restart`**
5. **Verifiera i Coolify-UI:n** att ingen pipeline fallerar efter deploy

Använd Mage UI för snabba fixar direkt i produktion (t.ex. justera en
query), men commit:a dem snabbt så du inte tappar synk med GitHub.

## Relaterade filer

- `scripts/sync_from_github.sh` – pull + restart
- `scripts/deploy_to_coolify.sh` – fallback (rsync, använd för oommitted changes)
- `documentation/COOLIFY_MIGRATION.md` – övergripande Coolify-setup
