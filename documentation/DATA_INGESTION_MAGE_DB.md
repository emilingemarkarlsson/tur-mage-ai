# Hämta NHL-datan: S3 → Mage AI → databas → Streamlit & n8n

Steg-för-steg hur du **hämtar datan från Hetzner S3**, bygger **strukturerade tabeller i en databas** med Mage AI, och kopplar **Streamlit** samt **n8n** mot samma databas.

---

## 1. S3-åtkomst (Hetzner)

### 1.1 Uppgifter

| Variabel | Värde | Beskrivning |
|----------|--------|-------------|
| **Endpoint** | `hel1.your-objectstorage.com` | S3 endpoint (utan https://) |
| **Bucket** | `nhlhockey-data` | Bucket-namn |
| **Access Key** | (din nyckel) | Hetzner Object Storage access key |
| **Secret Key** | (din nyckel) | Hetzner Object Storage secret key |
| **Region** | `eu-central` | Använd vid client-init |

### 1.2 Hämta enstaka fil med Python (boto3)

```python
import boto3
import json

client = boto3.client(
    "s3",
    endpoint_url="https://hel1.your-objectstorage.com",
    aws_access_key_id="DIN_ACCESS_KEY",
    aws_secret_access_key="DIN_SECRET_KEY",
    region_name="eu-central",
)

bucket = "nhlhockey-data"

# Exempel: ladda ner en fil
key = "nhl-data/basic/teams/all_teams.json"
response = client.get_object(Bucket=bucket, Key=key)
data = json.loads(response["Body"].read())
# data är nu ett dict/list
```

### 1.3 Lista alla objekt under ett prefix

```python
paginator = client.get_paginator("list_objects_v2")
pages = paginator.paginate(Bucket=bucket, Prefix="nhl-data/")

for page in pages:
    for obj in page.get("Contents", []):
        key = obj["Key"]
        size = obj["Size"]
        # key t.ex. "nhl-data/basic/teams/all_teams.json"
```

### 1.4 Ladda ner alla filer under prefix (sync till lokal mapp)

```python
import os

def download_prefix(client, bucket, prefix, local_dir):
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.endswith("/"):
                continue
            local_path = os.path.join(local_dir, key)
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            client.download_file(bucket, key, local_path)
            print(key)

# Användning:
# download_prefix(client, bucket, "nhl-data/", "./sync/nhl-data")
# download_prefix(client, bucket, "nhl-data-reorganized/games/by_date/", "./sync/games_by_date")
```

**Rekommendation:** Använd **miljövariabler** för credentials (t.ex. `HETZNER_ACCESS_KEY`, `HETZNER_SECRET_KEY`) och läs dem i Mage/script – hårdkoda inte nycklar i kod.

---

## 2. Exakta S3-nycklar att hämta (i vilken ordning)

Använd dessa **S3 Key-prefix/nycklar** i Mage (eller i ett script som skriver till din databas).

### 2.1 Dimensioner och grunddata (hämtas först)

| S3 Key | Tabell / användning |
|--------|----------------------|
| `nhl-data/basic/teams/all_teams.json` | `teams` |
| `nhl-data/basic/players/all_players.json` | `players` |
| `nhl-data/misc/countries.json` | `countries` (valfritt) |

### 2.2 Trupper per säsong

| S3 Key | Tabell / användning |
|--------|----------------------|
| `nhl-data/basic/teams/rosters/{season}/all_rosters.json` | `roster` (player_id, team_id, season) |

`{season}` = t.ex. `20252026`. Lista objekt under `nhl-data/basic/teams/rosters/` för att hitta tillgängliga säsonger.

### 2.3 Ställningar

| S3 Key | Tabell / användning |
|--------|----------------------|
| `nhl-data/basic/standings/league_standings_{season}.json` | `standings` (eller liknande) |
| Filer under `nhl-data/basic/standings/` | Lista med ListObjects och ladda de filer du behöver. |

### 2.4 Schema (matcher per datum)

| S3 Key | Tabell / användning |
|--------|----------------------|
| `nhl-data-reorganized/games/by_date/{YYYY-MM-DD}/games_summary.json` | `schedule` / `games_overview` (datum, match-id:n) |

Lista först objekt under `nhl-data-reorganized/games/by_date/` för att få alla datum-mappar, sedan ladda `games_summary.json` per datum.

### 2.5 Matchdata (boxscore) – en fil per match

| S3 Key | Tabell / användning |
|--------|----------------------|
| `nhl-data-reorganized/games/by_date/{YYYY-MM-DD}/{gameId}.json` | `games` + `game_players` (och eventuellt `goals`, `penalties`) |

**Viktigt:** Använd **endast** `by_date` för att undvika dubbletter (samma match finns även under `by_team` och `by_player`). Lista alla nycklar under `nhl-data-reorganized/games/by_date/` som slutar med `.json` och där filnamnet är ett numeriskt gameId (inte `games_summary.json`).

### 2.6 Säsongsstatistik (aggregerad)

| S3 Key | Tabell / användning |
|--------|----------------------|
| `nhl-data/stats/skaters/summary_{season}.json` | `skater_stats` |
| `nhl-data/stats/goalies/summary_{season}.json` | `goalie_stats` |
| `nhl-data/stats/teams/summary_{season}.json` | `team_stats` |
| `nhl-data/edge/skaters/landing_{season}.json` | `edge_skaters` (valfritt) |
| `nhl-data/edge/goalies/landing_{season}.json` | `edge_goalies` (valfritt) |
| `nhl-data/edge/teams/landing_{season}.json` | `edge_teams` (valfritt) |

Lista objekt under `nhl-data/stats/skaters/` etc. för att se vilka `{season}` som finns.

---

## 3. Föreslagen databasschema

Nedan är ett **normerat schema** som passar både Streamlit och n8n. Justera datatyper efter din DB (PostgreSQL, MySQL, SQLite).

```sql
-- Dimensioner
CREATE TABLE teams (
    id          INTEGER PRIMARY KEY,
    name        TEXT,
    abbreviation TEXT UNIQUE NOT NULL,
    division    TEXT,
    conference  TEXT,
    -- lägg gärna till fler fält från all_teams.json
);

CREATE TABLE players (
    id          INTEGER PRIMARY KEY,
    first_name  TEXT,
    last_name   TEXT,
    primary_position TEXT,
    sweater_number INTEGER,
    birth_date  DATE,
    nationality TEXT
    -- fler fält från all_players.json
);

CREATE TABLE countries (
    code        TEXT PRIMARY KEY,
    name        TEXT
);

-- Trupp per säsong (player – team – season)
CREATE TABLE roster (
    season      TEXT NOT NULL,
    team_id     INTEGER NOT NULL,
    player_id   INTEGER NOT NULL,
    PRIMARY KEY (season, team_id, player_id),
    FOREIGN KEY (team_id) REFERENCES teams(id),
    FOREIGN KEY (player_id) REFERENCES players(id)
);

-- Matcher (en rad per match)
CREATE TABLE games (
    game_id     BIGINT PRIMARY KEY,
    game_date   DATE NOT NULL,
    season      TEXT,
    home_team_abbr TEXT NOT NULL,
    away_team_abbr TEXT NOT NULL,
    home_score  INTEGER,
    away_score  INTEGER,
    status      TEXT,
    -- eventuellt: perioder, OT/SO
);

-- Spelarstatistik per match (en rad per spelare per match)
CREATE TABLE game_players (
    game_id     BIGINT NOT NULL,
    player_id   INTEGER NOT NULL,
    team_abbr   TEXT NOT NULL,
    position    TEXT,
    goals       INTEGER DEFAULT 0,
    assists     INTEGER DEFAULT 0,
    points      INTEGER DEFAULT 0,
    plus_minus  INTEGER,
    shots       INTEGER,
    pim         INTEGER,
    toi_seconds INTEGER,
    -- målvakt: saves, shots_against, save_pct
    PRIMARY KEY (game_id, player_id),
    FOREIGN KEY (game_id) REFERENCES games(game_id),
    FOREIGN KEY (player_id) REFERENCES players(id)
);

-- Ställningar (en rad per lag per säsong/datum)
CREATE TABLE standings (
    season      TEXT NOT NULL,
    team_abbr   TEXT NOT NULL,
    team_name   TEXT,
    conference  TEXT,
    division    TEXT,
    gp          INTEGER,
    w           INTEGER,
    l           INTEGER,
    ot          INTEGER,
    pts         INTEGER,
    gf          INTEGER,
    ga          INTEGER,
    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (season, team_abbr)
);

-- Säsongsstatistik skaters
CREATE TABLE skater_stats (
    season      TEXT NOT NULL,
    player_id   INTEGER NOT NULL,
    team_abbr   TEXT,
    games       INTEGER,
    goals       INTEGER,
    assists     INTEGER,
    points      INTEGER,
    plus_minus  INTEGER,
    pim         INTEGER,
    PRIMARY KEY (season, player_id),
    FOREIGN KEY (player_id) REFERENCES players(id)
);

-- Säsongsstatistik goalies
CREATE TABLE goalie_stats (
    season      TEXT NOT NULL,
    player_id   INTEGER NOT NULL,
    team_abbr   TEXT,
    games       INTEGER,
    wins        INTEGER,
    saves       INTEGER,
    shots_against INTEGER,
    save_pct    REAL,
    gaa         REAL,
    shutouts    INTEGER,
    PRIMARY KEY (season, player_id),
    FOREIGN KEY (player_id) REFERENCES players(id)
);

-- Schema-översikt (vilka matcher finns)
CREATE TABLE schedule_days (
    game_date   DATE PRIMARY KEY,
    game_ids    TEXT  -- JSON-array eller komma-separerade ID:n
);
```

Du kan lägga till fler tabeller (t.ex. `goals`, `penalties`) genom att plocka ut från boxscore-JSON i Mage.

---

## 4. Mage AI: pipeline-struktur

### 4.1 Inställning

- **Mage-projekt:** Skapa ett projekt (t.ex. `nhl_ingestion`).
- **Credentials:** Sätt miljövariabler för S3 (eller använd Mage Secrets):  
  `HETZNER_ACCESS_KEY`, `HETZNER_SECRET_KEY`.  
  Eventuellt: `HETZNER_ENDPOINT=hel1.your-objectstorage.com`, `HETZNER_BUCKET=nhlhockey-data`.
- **Databas:** Konfigurera en DB (PostgreSQL/MySQL/SQLite) och connection string (env eller Mage IO Config).

### 4.2 Block 1: Data Loader (S3 → JSON/DataFrame)

Ett **Python Data Loader**-block som:

1. Skapar en boto3-klient mot Hetzner (endpoint + credentials från env).
2. För **dimensioner:** anropar `get_object` på exakt nyckel (t.ex. `nhl-data/basic/teams/all_teams.json`), läser body, `json.loads`, konverterar till pandas DataFrame.
3. För **matchfiler:** använder `list_objects_v2` med prefix `nhl-data-reorganized/games/by_date/`, filtrerar på nycklar som slutar med `{gameId}.json`, och för varje nyckel anropar `get_object`, parsar JSON och samlar till en lista av dicts – sedan `pd.DataFrame(list_of_dicts)` eller bygg två DataFrames (games + game_players) genom att plocka ut fält från varje boxscore.

Exempel på hur du kan returnera data (Mage förväntar sig ofta en DataFrame eller dict med DataFrames):

```python
# I Mage Data Loader
import boto3
import json
import os
import pandas as pd

def get_s3_client():
    return boto3.client(
        "s3",
        endpoint_url="https://" + os.getenv("HETZNER_ENDPOINT", "hel1.your-objectstorage.com"),
        aws_access_key_id=os.getenv("HETZNER_ACCESS_KEY"),
        aws_secret_access_key=os.getenv("HETZNER_SECRET_KEY"),
        region_name="eu-central",
    )

def load_teams(client, bucket):
    r = client.get_object(Bucket=bucket, Key="nhl-data/basic/teams/all_teams.json")
    data = json.loads(r["Body"].read())
    teams = data.get("teams", data) if isinstance(data, dict) else data
    return pd.DataFrame(teams)

# Returnera dict med namngivna DataFrames så nästa block kan använda dem
def load_all_dimensions(client, bucket):
    return {
        "teams": load_teams(client, bucket),
        # "players": load_players(...),
    }
```

### 4.3 Block 2: Transformers (JSON-struktur → tabellformat)

- **Input:** DataFrames från loader (t.ex. rå-teams, rå-players, lista av boxscore-dicts).
- **Transform:**  
  - Mappa kolumner från `all_teams.json` till `teams`-tabellen (id, name, abbreviation, division, conference).  
  - Mappa `all_players.json` till `players`.  
  - För varje boxscore-fil: extrahera en rad till `games` (game_id, game_date, home_team_abbr, away_team_abbr, home_score, away_score) och flera rader till `game_players` (game_id, player_id, team_abbr, goals, assists, toi_seconds, …). NHL använder både `boxscore.playerByGameStats` och ibland `boxscore.gameData` / `liveData` – inspektera en exempel-JSON och skriv omvandlingslogik därefter.  
  - Ställningar: mappa från `league_standings_*.json` till `standings`.  
  - Skater/goalie summary: mappa till `skater_stats` och `goalie_stats`.
- **Output:** DataFrames som matchar dina tabeller (samma kolumnnamn som i CREATE TABLE).

### 4.4 Block 3: Data Exporter (DataFrame → databas)

- Använd Mage **Export to database** (eller ett Python-block med sqlalchemy/pandas `to_sql`).
- Skriv till rätt tabell: `teams`, `players`, `games`, `game_players`, `standings`, `skater_stats`, `goalie_stats`.
- Strategi: antingen **full refresh** (truncate + insert) per tabell eller **upsert** på t.ex. `game_id` / `(season, player_id)` så du inte duplicerar vid omkörning.

Exempel (i Python-block):

```python
from sqlalchemy import create_engine

engine = create_engine(os.getenv("DATABASE_URL"))

# df_teams, df_games, df_game_players från tidigare block
df_teams.to_sql("teams", engine, if_exists="replace", index=False)
df_games.to_sql("games", engine, if_exists="append", index=False)  # eller replace/upsert
df_game_players.to_sql("game_players", engine, if_exists="append", index=False)
```

### 4.5 Körordning

1. **Dimensioner:** teams, players (och countries om du använder dem).  
2. **Roster:** all_rosters per säsong.  
3. **Standings:** league_standings.  
4. **Games + game_players:** lista by_date, ladda varje `{gameId}.json`, transformera till games + game_players.  
5. **Säsongsstatistik:** skater_stats, goalie_stats (och team_stats).

Du kan ha en pipeline som kör alla steg, eller dela upp i flera pipelines (t.ex. en för dimensioner, en för matcher) och köra dem i ordning eller via n8n.

---

## 5. Streamlit-dashboard

- **Anslutning:** Samma databas som Mage skriver till (läs med `sqlalchemy` + `pandas.read_sql` eller `st.experimental_connection` om du använder Snowflake/duckdb).
- **Queries:**  
  - Ställning: `SELECT * FROM standings WHERE season = ? ORDER BY pts DESC`.  
  - Senaste matcher: `SELECT * FROM games ORDER BY game_date DESC LIMIT 20`.  
  - Spelarstatistik: `SELECT * FROM skater_stats WHERE season = ? ORDER BY points DESC`.  
  - Spelare per match: `SELECT * FROM game_players WHERE game_id = ?`.
- **Trigger av ny data:** Kör Mage-pipelinen (t.ex. dagligen eller efter scraper-uppdatering) så att Streamlit alltid läser senaste data från samma DB.

---

## 6. n8n: automatiska artiklar och integration

- **Källa till innehåll:**  
  - Antingen **databasen direkt:** n8n-nod "Postgres" / "MySQL" (eller generisk "Execute Command" med `psql`/script) som kör SELECT (t.ex. dagens resultat, topppoäng, ställning) och skickar raderna till nästa steg.  
  - Eller **Mage som API:** om du exponerar Mage-pipeline som HTTP-endpoint (t.ex. "run pipeline och returnera senaste games") kan n8n anropa den och sedan använda svaret för textgenerering.
- **Flöde typiskt:**  
  1. Trigger (schemalagd eller webhook).  
  2. Hämta data (DB-nod eller HTTP till egen API som läser från DB).  
  3. Formatera till text (template eller liten script).  
  4. Skicka till LLM (eller mall) för att skriva artikel.  
  5. Publicera (CMS, e-post, Slack, etc.).
- **Uppdatering av datan:**  
  - Scrapern (denna repo) fyller S3 (webb/n8n trigger).  
  - Mage-pipelinen körs (schemalagt eller triggat av n8n efter scraper) och uppdaterar DB.  
  - Streamlit och n8n läser från DB – ingen direktkoppling till S3 i n8n/Streamlit behövs om du vill.

---

## 7. Sammanfattning: flöde från S3 till artikel

```
Hetzner S3 (nhlhockey-data)
    │
    ▼  (boto3: list_objects_v2 + get_object)
Mage AI: Data Loader → Transform → Export to DB
    │
    ▼
Databas (PostgreSQL / MySQL / SQLite)
    │
    ├──► Streamlit: read_sql → dashboard
    │
    └──► n8n: Postgres/MySQL-nod → template → LLM → artikel
```

Exakta S3-nycklar och föreslagen tabellstruktur finns ovan; justera JSON→tabell-mappningen i Mage efter den faktiska strukturen i dina JSON-filer (särskilt boxscore) genom att inspektera ett par filer från S3.
