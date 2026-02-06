# Hetzner S3 – full datastruktur för Mage AI (Silver Parquet + Gold DuckDB)

Denna dokumentation beskriver **hela datastrukturen** i Hetzner-bucketen så att du kan bygga **silver-nivå (Parquet)** och **guld-nivå (DuckDB)** i Mage AI. All data som projektet sparar i S3 är medräknad; fokus ligger på att du ska kunna **analysera per match och trender över tid**, inte bara agregerad data.

---

## 1. Översikt

| Lager   | Källa        | Innehåll i S3 |
|--------|---------------|----------------|
| **Bron** | NHL API + scraper | JSON i bucket `nhlhockey-data` under `nhl-data/` och `nhl-data-reorganized/` |
| **Silver** | Mage (du bygger) | Parquet-filer per entitet: teams, players, games, game_players, standings, stats, etc. |
| **Guld** | Mage (du bygger) | DuckDB-databas med tabeller + vyer för trendanalys per match |

**Viktigt:** För matcher finns samma boxscore-JSON sparad på tre ställen (`by_date`, `by_team`, `by_player`). I Mage ska du **endast läsa från `by_date`** så att varje match bara räknas en gång.

---

## 2. Full S3-nyckelstruktur (all data)

Bucket: **`nhlhockey-data`**  
Endpoint: **`hel1.your-objectstorage.com`**

```
nhlhockey-data/
├── nhl-data/
│   ├── basic/
│   │   ├── teams/
│   │   │   ├── all_teams.json
│   │   │   ├── all_teams.csv
│   │   │   ├── franchises.json
│   │   │   └── rosters/
│   │   │       └── {season}/
│   │   │           ├── all_rosters.json
│   │   │           └── roster_{franchise_id}.json
│   │   ├── standings/
│   │   │   ├── league_standings_{season}.json
│   │   │   └── season_standing_manifest.json
│   │   ├── schedule/
│   │   │   ├── daily_{YYYY-MM-DD}.json
│   │   │   ├── weekly.json
│   │   │   └── calendar_{YYYY-MM-DD}.json
│   │   └── players/
│   │       ├── all_players.json
│   │       └── players_by_team.json
│   ├── stats/
│   │   ├── skaters/
│   │   │   └── summary_{season}.json
│   │   ├── goalies/
│   │   │   └── summary_{season}.json
│   │   └── teams/
│   │       └── summary_{season}.json
│   ├── edge/
│   │   ├── skaters/
│   │   │   └── landing_{season}.json
│   │   ├── goalies/
│   │   │   └── landing_{season}.json
│   │   └── teams/
│   │       └── landing_{season}.json
│   ├── helpers/
│   │   ├── game_ids_{season}.json
│   │   ├── all_players_{season}.json
│   │   └── all_players_summary_statistics_{season}.json
│   └── misc/
│       ├── countries.json
│       ├── glossary.json
│       └── draft_year_and_rounds.json
│
└── nhl-data-reorganized/
    └── games/
        ├── by_date/
        │   └── {YYYY-MM-DD}/
        │       ├── games_summary.json
        │       └── {gameId}.json          ← en fil per match (använd ENDAST denna för matcher)
        ├── by_team/
        │   └── {ABBR}/
        │       └── {YYYY-MM-DD}/
        │           └── {gameId}.json      ← samma innehåll som by_date, dubblett
        └── by_player/
            └── {playerId}/
                └── {YYYY-MM-DD}/
                    └── {gameId}.json      ← samma innehåll som by_date, dubblett
```

**Platshållare:**
- `{season}` = säsong, t.ex. `20242025` eller `20252026`
- `{YYYY-MM-DD}` = datum
- `{gameId}` = NHL match-ID (t.ex. `2025020644`)
- `{ABBR}` = lagförkortning (t.ex. `TOR`, `BOS`)
- `{playerId}` = NHL person-ID (t.ex. `8471214`)
- `{franchise_id}` = franchise-ID från API

---

## 3. Hur du listar tillgänglig data i S3

Innan du bygger silver/gold behöver du veta vilka säsonger och datum som finns.

| Vad du vill hitta | S3-prefix att lista |
|-------------------|----------------------|
| Alla datum med matchdata | `nhl-data-reorganized/games/by_date/` → varje “mapp” är ett datum (YYYY-MM-DD) |
| Alla matchfiler för ett datum | `nhl-data-reorganized/games/by_date/2025-01-15/` → filer som slutar med `.json` och där filnamn är numeriskt (gameId); exkludera `games_summary.json` |
| Tillgängliga säsonger (rosters, standings, stats) | Lista t.ex. `nhl-data/basic/teams/rosters/`, `nhl-data/stats/skaters/` → mappnamn eller filnamn innehåller `{season}` |
| Tillgängliga ställningsfiler | `nhl-data/basic/standings/` |
| Tillgängliga EDGE-filer | `nhl-data/edge/skaters/`, `nhl-data/edge/goalies/`, `nhl-data/edge/teams/` |

Exempel (Python/boto3):

```python
paginator = client.get_paginator("list_objects_v2")

# Alla datum med matcher
for page in paginator.paginate(Bucket=bucket, Prefix="nhl-data-reorganized/games/by_date/", Delimiter="/"):
    for prefix in page.get("CommonPrefixes", []):
        # prefix["Prefix"] == "nhl-data-reorganized/games/by_date/2025-01-15/"
        date = prefix["Prefix"].rstrip("/").split("/")[-1]
```

---

## 4. JSON-struktur per filtyp (för Silver Parquet-design)

Här beskrivs **exakt vilka nycklar** du kan förvänta dig i varje filtyp. Använd detta för att mappa till kolumner i silver Parquet och sedan till DuckDB.

### 4.1 Dimensioner och grunddata

#### `nhl-data/basic/teams/all_teams.json`

- **Root:** objekt med nyckel `"teams"` (lista) eller direkt lista.
- **Varje lag:** dict med bland annat:
  - `id` / `franchise_id`, `name`, `common_name`, `abbr` / `abbreviation`
  - `division`, `conference`, arena-relaterade fält (om API returnerar det)

**Silver:** en Parquet-tabell `teams` (en rad per lag).

#### `nhl-data/basic/players/all_players.json`

- **Root:** lista av spelare (eller objekt som innehåller en lista).
- **Varje spelare:** dict med t.ex. `id`, `firstName`, `lastName`, `primaryPosition`, `sweaterNumber`, `birthDate`, `nationality` / `countryCode`, `teamAbbr`, etc.

**Silver:** en Parquet-tabell `players` (en rad per spelare).

#### `nhl-data/basic/teams/rosters/{season}/all_rosters.json`

- **Root:** dict med franchise_id som nyckel; värde = roster-objekt/lista.
- **Roster:** lista av spelare med `playerId`, `teamId`/team-info, eventuellt position.

**Silver:** Parquet-tabell `roster` med kolumner t.ex. `season`, `team_id`/`franchise_id`, `player_id`.

#### `nhl-data/basic/standings/league_standings_{season}.json`

- **Root:** API-typisk ställningsstruktur (conference/division → lag).
- **Varje lag:** t.ex. `teamAbbr`, `teamName`, `gp`, `w`, `l`, `ot`, `pts`, `gf`, `ga`, `conference`, `division`.

**Silver:** Parquet-tabell `standings` med kolumner t.ex. `season`, `team_abbr`, `team_name`, `gp`, `w`, `l`, `ot`, `pts`, `gf`, `ga`, `conference`, `division`.

#### `nhl-data/basic/schedule/daily_{YYYY-MM-DD}.json` och `weekly.json`

- Ofta `dates` (lista) eller `games` (lista) med matchreferenser inkl. `gamePk` / `gameId`, `teams`, datum, etc.
- Använd för att veta vilka matcher som finns; den faktiska matchdatan hämtar du från `by_date/{date}/{gameId}.json`.

**Silver:** valfritt – du kan istället härleda “alla spelade matcher” från `by_date`-listning.

#### `nhl-data/misc/countries.json`, `glossary.json`, `draft_year_and_rounds.json`

- Olika strukturer; använd vid behov som dimensioner/referenstabeller.

---

### 4.2 Matchdata (per match) – kärnan för trendanalys

**S3-nyckel:** `nhl-data-reorganized/games/by_date/{YYYY-MM-DD}/{gameId}.json`  
**Viktigt:** Använd **endast** denna sökväg för att undvika dubbletter.

#### Root-nivå i filen

| Nyckel       | Typ   | Beskrivning |
|-------------|--------|-------------|
| `gameId`    | string | Match-ID (t.ex. `"2025020644"`) |
| `date`      | string | Datum (YYYY-MM-DD) |
| `boxscore`  | objekt | All match- och spelarstatistik (se nedan) |
| `playByPlay`| objekt | Valbart; händelser i matchen |
| `gameStory` | objekt | Valbart; sammanfattning |

#### `boxscore` – inre struktur

API-strukturen kan variera något; här är den vanligaste formen.

**gameData (metadata):**

- `boxscore.gameData.teams` – objekt med `home` och `away`, varje med t.ex. `id`, `name`, `abbreviation`/`abbr`.
- `boxscore.gameData.status` – t.ex. `abstractGameState` (Final, Live, …).

**liveData (resultat, perioder):**

- `boxscore.liveData.linescore` – resultat:
  - `teams.home.goals`, `teams.away.goals`
  - `periods` (lista) – periodresultat
  - Övertid/shootout om tillgängligt

**Spelarstatistik per match (trender):**

- `boxscore.playerByGameStats` – objekt med:
  - `awayTeam` och `homeTeam`
  - Varje lag: dict med listor:
    - `forwards` – lista av spelarobjekt
    - `defense` – lista av spelarobjekt
    - `goalies` – lista av spelarobjekt

**Varje spelarobjekt** (under forwards/defense/goalies) innehåller typiskt:

- `playerId`, `name` / `firstName`, `lastName`, `position`, `jerseyNumber`
- **Skridsko:** `goals`, `assists`, `points`, `plusMinus`, `shots`, `blockedShots`, `hits`, `faceoffWins`, `faceoffLosses`, `pim`, `toi` (time on ice, ofta sträng t.ex. "15:30")
- **Målvakt:** `saves`, `shotsAgainst`, `savePct`, `goalsAgainst`, `gaa`, `shutouts`

**Lagstatistik per match:**

- `boxscore.teamGameStats` – om det finns: skott, faceoffs, powerplay, penalty kill, hits, blocked shots per lag.

**Silver (rekommendation):**

1. **games** – en rad per match:  
   `game_id`, `game_date`, `season`, `home_team_abbr`, `away_team_abbr`, `home_score`, `away_score`, `status`, eventuellt perioder.
2. **game_players** – en rad per spelare per match:  
   `game_id`, `player_id`, `team_abbr`, `position`, `goals`, `assists`, `points`, `plus_minus`, `shots`, `pim`, `toi_seconds`, och för målvakt: `saves`, `shots_against`, `save_pct`, etc.  
   Detta är **underlaget för alla trendanalyser per match**.

**TOI:** Om `toi` kommer som sträng (t.ex. `"15:30"`), konvertera till sekunder i silver (t.ex. 15*60+30 = 930) så att DuckDB kan aggregera och filtrera enkelt.

---

#### `nhl-data-reorganized/games/by_date/{YYYY-MM-DD}/games_summary.json`

- **Root:** `date` (str), `games` (lista).
- **Varje element i `games`:** `gameId`, `date`, `status`, `homeTeam`, `awayTeam`, `homeScore`, `awayScore`.
- Använd för snabb översikt “vilka matcher spelades denna dag” och för att bygga en liten `schedule`/`games_overview` om du vill, men den fulla matchdatan finns i `{gameId}.json`.

---

### 4.3 Säsongsstatistik (aggregerad)

#### `nhl-data/stats/skaters/summary_{season}.json`

- Lista (eller objekt med lista) av spelare med säsongsstatistik: t.ex. `playerId`, `teamAbbr`, `games`, `goals`, `assists`, `points`, `plusMinus`, `pim`, `toi`, etc.

**Silver:** Parquet `skater_stats` med kolumner t.ex. `season`, `player_id`, `team_abbr`, `games`, `goals`, `assists`, `points`, …

#### `nhl-data/stats/goalies/summary_{season}.json`

- Motsvarande för målvakter: `games`, `wins`, `saves`, `shotsAgainst`, `savePct`, `gaa`, `shutouts`, etc.

**Silver:** Parquet `goalie_stats`.

#### `nhl-data/stats/teams/summary_{season}.json`

- Lagstatistik per säsong.

**Silver:** Parquet `team_stats`.

#### `nhl-data/edge/skaters/landing_{season}.json` (och goalies/teams)

- NHL EDGE-mått (avancerade mått). Struktur följer API; använd för silver som separata Parquet-tabeller om du behöver EDGE i analysen.

---

### 4.4 Helpers

- `nhl-data/helpers/game_ids_{season}.json` – lista av match-ID för säsongen.
- `nhl-data/helpers/all_players_{season}.json`, `all_players_summary_statistics_{season}.json` – kompletterande spelardata.

Du kan använda dessa för att validera eller komplettera silver-tabeller; de behöver inte nödvändigtvis bli egna silver-tabeller om du redan har `games` och `game_players` från boxscore.

---

## 5. Rekommenderad Silver-nivå (Parquet) i Mage

Bygg **en Parquet-fil (eller partitionerad mapp) per logisk entitet**. All data ska dras ut från S3 enligt listan nedan.

| Silver-tabell (Parquet) | S3-källa | Kommentar |
|-------------------------|----------|-----------|
| `teams` | `nhl-data/basic/teams/all_teams.json` | En rad per lag |
| `players` | `nhl-data/basic/players/all_players.json` | En rad per spelare |
| `roster` | `nhl-data/basic/teams/rosters/{season}/all_rosters.json` | Alla säsonger → flata rader (season, team_id, player_id) |
| `standings` | `nhl-data/basic/standings/league_standings_{season}.json` | Alla tillgängliga säsonger |
| `games` | `nhl-data-reorganized/games/by_date/{date}/{gameId}.json` | Extrahera från boxscore (gameData + liveData.linescore); en rad per match |
| `game_players` | Samma `{gameId}.json` | Extrahera från boxscore.playerByGameStats (alla forwards/defense/goalies); en rad per spelare per match – **huvudkälla för trendanalys** |
| `games_summary` (valfritt) | `by_date/{date}/games_summary.json` | Snabb översikt per datum |
| `skater_stats` | `nhl-data/stats/skaters/summary_{season}.json` | Aggregerad säsong |
| `goalie_stats` | `nhl-data/stats/goalies/summary_{season}.json` | Aggregerad säsong |
| `team_stats` | `nhl-data/stats/teams/summary_{season}.json` | Aggregerad säsong |
| `edge_*` (valfritt) | `nhl-data/edge/.../landing_{season}.json` | Om du använder EDGE-mått |

För **games** och **game_players**: loopa över alla prefix under `nhl-data-reorganized/games/by_date/`, för varje datum lista objekt, filtrera bort `games_summary.json`, och ladda varje `{gameId}.json`; parsa boxscore och skriv ut rader till respektive Parquet-tabell.

---

## 6. Rekommenderad Guld-nivå (DuckDB) i Mage

- **DuckDB:** Skapa en databas och importera (eller läsa direkt från) silver Parquet-filer.
- **Tabeller:** Motsvarande silver-tabeller (teams, players, roster, standings, games, game_players, skater_stats, goalie_stats, team_stats, eventuellt edge_*).
- **Primärnycklar:** t.ex. `games.game_id`, `game_players(game_id, player_id)`, `teams.id`, `players.id`.

### 6.1 Trender per match – vyer och frågor

All data ska kunna analyseras **per match** så att du kan se trender över tid. Detta bygger nästan helt på **game_players** (och **games**).

Exempel på användbara vyer eller frågor i DuckDB:

- **Poäng per match per spelare:**  
  `game_players` har redan `game_id`, `player_id`, `goals`, `assists`, `points`. Join med `games` på `game_id` för `game_date` så du kan gruppera per spelare och datum/säsong.
- **Rullande genomsnitt (t.ex. senaste 5 matcher):**  
  Window-funktion över `game_players` joinat med `games`, sorterat på `game_date`, partition by `player_id`.
- **Målvaktsräddningsprocent per match:**  
  I `game_players` (position = goalie): `saves`, `shots_against`, `save_pct` per `game_id`; join med `games` för datum.
- **Hemma/borta-splittring:**  
  I `games`: `home_team_abbr` / `away_team_abbr`; koppla till `game_players.team_abbr` för att veta om spelaren var hemma eller borta.

Exempelvy (koncept):

```sql
-- Exempel: poäng per match med datum (för trendanalys)
CREATE VIEW v_player_points_per_game AS
SELECT
  gp.game_id,
  g.game_date,
  g.season,
  gp.player_id,
  p.first_name || ' ' || p.last_name AS player_name,
  gp.team_abbr,
  gp.position,
  gp.goals,
  gp.assists,
  gp.points,
  gp.shots,
  gp.toi_seconds
FROM game_players gp
JOIN games g ON g.game_id = gp.game_id
JOIN players p ON p.id = gp.player_id
ORDER BY gp.player_id, g.game_date;
```

Du kan bygga fler vyer för rullande genomsnitt, säsongsuppdelning eller lag/prestanda över tid.

---

## 7. Sammanfattning – vad som finns i Hetzner och hur du använder det

- **All data** som projektet sparar i Hetzner finns under `nhl-data/` och `nhl-data-reorganized/`.
- **Matchnivå:** Använd **endast** `nhl-data-reorganized/games/by_date/{YYYY-MM-DD}/{gameId}.json`; där finns full boxscore inkl. `playerByGameStats` för trender per match.
- **Silver:** Parquet per entitet (teams, players, games, game_players, standings, stats, eventuellt edge och games_summary).
- **Guld:** DuckDB med samma tabeller + vyer/frågor som bygger på `games` och `game_players` för trendanalys över tid.

För exempel på S3-åtkomst (boto3, env-variabler) och pipeline-steg i Mage, se [DATA_INGESTION_MAGE_DB.md](DATA_INGESTION_MAGE_DB.md).

**Pipeline-översikt:** Se [documentation/DATA_SOURCES_S3.md](documentation/DATA_SOURCES_S3.md) för vilka S3-sökvägar som laddas idag och justeringar gjorda enligt denna dokumentation.
