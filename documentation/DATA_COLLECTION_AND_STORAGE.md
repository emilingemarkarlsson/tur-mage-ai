# Hur datan samlas in och sparas

Denna guide beskriver **varifrån** datan kommer, **hur** den samlas in, **var** den sparas (inkl. S3) och **hur du kan använda den** för att bygga dashboards och transformationer.

---

## 1. Översikt: från källa till lagring

```
NHL API (statsapi.web.nhl.com / nhl-api-py)
        ↓
Scraper (Python: export + organize)
        ↓
Lokala mappar: nhl-data/ + nhl-data-reorganized/
        ↓
Uppladdning till Hetzner S3 (hel1.your-objectstorage.com)
        ↓
Bucket: nhlhockey-data
        ├── nhl-data/           ← grunddata + statistik
        └── nhl-data-reorganized/  ← matchdata (per datum, lag, spelare)
```

- **Källa:** NHL:s officiella API (via biblioteket [nhl-api-py](https://github.com/coreyjs/nhl-api-py)).
- **Samling:** Scrapern kör script som hämtar data (catch-up, grunddata, statistik) och organiserar matcher.
- **Format:** Allt sparas som **JSON** (inga CSV i denna pipeline).
- **Lagring:** Samma katalogstruktur skrivs lokalt och sedan upp till S3; lokala filer tas bort efter lyckad uppladdning (konfigurerbart).

---

## 2. Var datan sparas (S3)

| S3-prefix | Innehåll |
|-----------|----------|
| **nhl-data/** | Grunddata, ställningar, schema, statistik (skater/goalie/team), EDGE-statistik, hjälp- och misc-filer. |
| **nhl-data-reorganized/** | Matchdata (boxscore) organiserad per datum, per lag och per spelare. |

**Bucket:** `nhlhockey-data`  
**Endpoint:** `hel1.your-objectstorage.com` (S3-kompatibel).

För att **läsa datan** behöver du S3-klient (t.ex. AWS SDK/boto3, eller Hetzners webbgränssnitt) med samma credentials som används vid uppladdning (access key + secret key). Du kan lista objekt under `nhl-data/` och `nhl-data-reorganized/` och ladda ner de JSON-filer du behöver.

---

## 3. Struktur och innehåll

### 3.1 nhl-data/ (grunddata och statistik)

Alla sökvägar nedan är **relativa under prefixet `nhl-data/`** i S3 (och motsvarar lokala mappar under `nhl-data/`).

| Sökväg | Beskrivning | Användning för dashboards |
|--------|-------------|----------------------------|
| **basic/teams/all_teams.json** | Alla NHL-lag (id, namn, abbreviation, arena, division, conference). | Dimensionstabell lag; koppla abbreviation till namn. |
| **basic/teams/rosters/{season}/all_rosters.json** | Trupper per lag för en säsong (t.ex. `20252026`). | Koppla spelare till lag per säsong. |
| **basic/standings/** | Ställningar. Filer t.ex. `league_standings_{season}.json`, `season_standing_manifest.json`. | Tabeller/grafer för poäng, vinster, målskillnad. |
| **basic/schedule/daily_{YYYY-MM-DD}.json** | Dagens matchschema. | Vilka matcher som spelats/planeras. |
| **basic/schedule/weekly.json** | Veckans schema. | Samma. |
| **basic/players/all_players.json** | Spelarlista. | Dimensionstabell spelare. |
| **basic/players/players_by_team.json** | Spelare grupperade per lag. | Koppling spelare–lag. |
| **stats/skaters/summary_{season}.json** | Skater-statistik för säsong. | Poäng, mål, assist, TOI, etc. |
| **stats/goalies/summary_{season}.json** | Målvaktsstatistik för säsong. | SVS%, GAA, shutouts. |
| **stats/teams/summary_{season}.json** | Lagstatistik för säsong. | Aggregerad lagstatistik. |
| **edge/skaters/landing_{season}.json** | NHL EDGE-skaterstatistik. | Avancerade mått (skott, hastighet, etc.). |
| **edge/goalies/landing_{season}.json** | NHL EDGE-målvaktsstatistik. | Avancerade målvaktsmått. |
| **edge/teams/landing_{season}.json** | NHL EDGE-lagstatistik. | Avancerade lagmått. |
| **helpers/game_ids_{season}.json** | Alla match-ID:n för säsongen. | Lista matcher att koppla mot by_date. |
| **misc/countries.json** | Länder (t.ex. för nationalitet). | Dimension. |
| **misc/glossary.json** | Ordlista för statistiktermer. | Förklaringar i UI. |
| **misc/draft_year_and_rounds.json** | Draft-info. | Kontext. |

- **Säsong:** Format `20252026` = säsong 2025–2026. Beräknas automatiskt i scrapern.
- **Format:** En JSON-fil per objekt/lista; ofta `{"teams": [...]}` eller `{"games": [...]}` etc. Öppna en fil för att se exakt nyckelstruktur.

---

### 3.2 nhl-data-reorganized/ (matchdata)

Alla sökvägar är **relativa under prefixet `nhl-data-reorganized/`** i S3.

| Sökväg | Beskrivning | Användning för dashboards |
|--------|-------------|----------------------------|
| **games/by_date/{YYYY-MM-DD}/{gameId}.json** | En fil per match. Innehåller boxscore (resultat, perioder, lag, spelarstatistik per match). | Matchresultat, spelarstatistik per match, mål/assists. |
| **games/by_date/{YYYY-MM-DD}/games_summary.json** | Sammanfattning för alla matcher den dagen. | Snabb översikt per datum. |
| **games/by_team/{TEAM_ABBR}/{YYYY-MM-DD}/{gameId}.json** | Samma boxscore-filer, men kopierade per lag (TEAM_ABBR = t.ex. TOR, BOS). | Alla matcher för ett lag. |
| **games/by_player/{playerId}/{YYYY-MM-DD}/{gameId}.json** | Samma boxscore-filer, kopierade per spelare (playerId = NHL person ID). | Alla matcher en spelare deltog i. |

- **gameId:** NHL:s match-ID (t.ex. `2025020644`).
- **Boxscore:** Innehåller bl.a. resultat, perioder, mål, straffar, och per spelare: mål, assist, plus/minus, skott, TOI, målvaktsstatistik etc. Se [WHAT_DATA_IN_GAMES.md](WHAT_DATA_IN_GAMES.md) för fält.
- **Organisering:** Samma JSON sparas flera gånger (en gång under by_date, en gång per lag i matchen under by_team, en gång per spelare under by_player) så att du enkelt kan hämta “alla matcher för X” utan att scanna alla datum.

---

## 4. Hur datan samlas in (flöde)

1. **Trigger:** Manuellt (webbknapp), n8n (`POST /update/async`) eller schemalagt (cron).
2. **Catch-up (matchdata):** Script hämtar matcher från senaste sparade datum till idag via NHL Schedule/Game API och sparar boxscore per datum i `nhl-data-reorganized/games/by_date/`.
3. **Organisering:** Samma matchfiler kopieras till `by_team/{ABBR}/...` och `by_player/{playerId}/...`.
4. **Grunddata:** Lag, trupper, ställningar, schema, spelarlistor exporteras till `nhl-data/basic/`.
5. **Statistik:** Skater-, goalie- och team-statistik samt EDGE-landing exporteras till `nhl-data/stats/` och `nhl-data/edge/`.
6. **Uppladdning:** Alla filer under `nhl-data/` och `nhl-data-reorganized/` laddas upp till S3 (samma sökvägar under bucket), varefter lokala filer kan tas bort.

State för “senaste exportdatum” sparas i `logs/last_export_date.txt` så nästa körning vet från vilket datum catch-up ska börja.

---

## 5. Format och typiska nycklar (JSON)

- **Encoding:** UTF-8.
- **Struktur:** Filer är “vanliga” JSON-objekt/listor (inga radseparerade JSON-rader).

Exempel på vad du kan förvänta dig (varierar något mellan endpoints):

- **Lag:** `id`, `name`, `abbreviation` / `abbr`, `division`, `conference`, arena-info.
- **Spelare:** `id`, `firstName`, `lastName`, `primaryPosition`, `sweaterNumber`, nationalitet.
- **Match (boxscore):** `boxscore.gameData.teams`, `boxscore.playerByGameStats` (eller `liveData.boxscore.teams`), resultat, perioder, mål, straffar.
- **Ställningar:** Division/Conference, lag, GP, W, L, OT, PTS, GF, GA.
- **Statistikfiler:** Ofta listor eller objekt med spelar-/lag-ID och statistikfält (goals, assists, points, TOI, saves, etc.).

För exakt struktur: ladda ner en representativ fil från S3 och inspektera nycklarna (t.ex. en `by_date/.../games_summary.json` och en `by_date/.../{gameId}.json`).

---

## 6. Anslutning och användning för dashboards

### 6.1 Läsa från S3

- **S3-kompatibel klient** (boto3, AWS CLI, eller Hetzner Console): använd samma bucket och endpoint som scrapern, med access key och secret key.
- **Lista filer:** ListObjects under prefix `nhl-data/` respektive `nhl-data-reorganized/` för att hitta till exempel senaste `by_date`-datum eller tillgängliga säsonger.
- **Ladda ner:** GetObject på vald nyckel (t.ex. `nhl-data/basic/teams/all_teams.json`) och parsa JSON i din pipeline.

### 6.2 Rekommenderad ordning för att bygga datamodell

1. **Dimensioner:** Läs `nhl-data/basic/teams/all_teams.json` och `basic/players/all_players.json` (eller motsvarande) för lag och spelare.
2. **Ställningar och schema:** Använd `basic/standings/*` och `basic/schedule/*` för tabeller och vilka matcher som finns.
3. **Aggregerad statistik:** Använd `stats/skaters/`, `stats/goalies/`, `stats/teams/` för säsongsstatistik.
4. **Matchnivå:** Använd `nhl-data-reorganized/games/by_date/{date}/{gameId}.json` för resultat och spelarstatistik per match; använd `by_team` eller `by_player` om du vill filtrera på lag/spelare utan att själv aggregera per datum.

### 6.3 Transformation och dashboards

- **ETL:** Hämta JSON från S3 → parsa → normalisera till dina tabeller (t.ex. lag, spelare, matcher, spelarstatistik_per_match, ställningar). Säsongs- och EDGE-filer kan matas in som separata tabeller eller vyer.
- **Joins:** Koppla matchfiler till lag via team abbreviation; koppla spelarstatistik till spelare via player ID; koppla till ställningar via datum/säsong och lag.
- **Dashboards:** Bygg rapporter på de transformerade tabellerna (poäng, mål, trend per lag/spelare, EDGE-mått etc.). Cache eller materialisera S3-data med jämna mellanrum om scrapern uppdaterar dagligen.

---

## 7. Snabbreferens: viktiga sökvägar i S3

```
nhlhockey-data/
├── nhl-data/
│   ├── basic/teams/all_teams.json
│   ├── basic/teams/rosters/{season}/all_rosters.json
│   ├── basic/standings/
│   ├── basic/schedule/
│   ├── basic/players/
│   ├── stats/skaters/summary_{season}.json
│   ├── stats/goalies/summary_{season}.json
│   ├── stats/teams/summary_{season}.json
│   ├── edge/skaters/landing_{season}.json
│   ├── edge/goalies/landing_{season}.json
│   ├── edge/teams/landing_{season}.json
│   ├── helpers/
│   └── misc/
└── nhl-data-reorganized/
    └── games/
        ├── by_date/{YYYY-MM-DD}/{gameId}.json
        ├── by_team/{ABBR}/{YYYY-MM-DD}/{gameId}.json
        └── by_player/{playerId}/{YYYY-MM-DD}/{gameId}.json
```

För mer detaljer om vad som finns i **matchfiler** (boxscore), se [WHAT_DATA_IN_GAMES.md](WHAT_DATA_IN_GAMES.md). För **tillgängliga API-endpoints och datatyper**, se [DATA_OVERVIEW.md](DATA_OVERVIEW.md).

**Nästa steg:** För exakt hur du hämtar datan från S3, bygger tabeller i en databas med Mage AI och kopplar Streamlit samt n8n, se [DATA_INGESTION_MAGE_DB.md](DATA_INGESTION_MAGE_DB.md).
