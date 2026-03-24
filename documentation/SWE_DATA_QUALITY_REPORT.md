# Swehockey Data – Kvalitetsrapport
_Genererad 2026-03-24 baserat på sampling av S3-bucket `swehockey-data`_

---

## 1. Inventering

### S3-struktur
```
swehockey-data/
└── raw/
    ├── games/           1 908 filer  (YYYY-MM-DD.json, 2021-01-01 → 2026-03-23)
    ├── game_details/   113 020 filer  (game_id.json, numeriska id:n)
    ├── reports/        ~229 380 PDF:er (per game_id/XX_Namn.pdf)
    ├── checkpoint.json  (scraping-state)
    └── scraped_game_ids.json (~1,6 MB)
```

### Scraping-status (checkpoint.json, 2026-03-24)
| Fält | Värde |
|------|-------|
| `last_scraped_date` | 2021-07-19 |
| `total_games_scraped` | 526 324 |
| `failed_dates` | [] |

**Slutsats**: Scrapern är inne på säsong 2021 (juli). Datum-index-filer finns 2021–2026 (1 908 st), men `game_details` för datum efter 2021-07-19 är ännu inte scrapade.

### PDF-rapporter per typ
| Filnamn | Innehåll | Täckning |
|---------|----------|----------|
| `01_Official_Line_Up.pdf` | Laguppställning | Bred (flesta ligor) |
| `02_Official_Team_Roster.pdf` | Officiell spelarlista | Bred |
| `03_Official_Game_Report.pdf` | Matchrapport med mål/straff | Bred |
| `04_Media_Game_Summary.pdf` | Pressrapport | Allsvenskan+ |
| `05_Player_Summary.pdf` | Individuell statistik | Allsvenskan+ |
| `FaceOff_Chart.pdf` | Faceoff-data | Bara SHL/Allsvenskan (~245 matcher) |
| `Possession_Report.pdf` | Possession | Bara SHL/Allsvenskan (~245 matcher) |

---

## 2. Fält- och entitetskarta

### `raw/games/YYYY-MM-DD.json` – Matchlista per datum
| Fält | Typ | Täckning | Anmärkning |
|------|-----|----------|------------|
| `game_id` | string/null | **Varierar kraftigt** (se §3) | null = ej scrapbar match |
| `date` | string YYYY-MM-DD | 100% | |
| `time` | string HH:MM | 100% | |
| `home_team` | string | 100% | Kan innehålla `\xa0` (NBSP) |
| `away_team` | string | 100% | |
| `result` | string/null | Korrelerar med game_id | Format: `"N - N"` |
| `venue` | string | 100% | Kan ha dubbla mellanslag |
| `league` | string | 100% | Kan innehålla `\t` (tab) |
| `league_id` | string | 100% | Swehockey internt id |

### `raw/game_details/{id}.json` – Full matchdata
| Fält | Typ | Täckning | Anmärkning |
|------|-----|----------|------------|
| `game_id` | string | 100% | |
| `date` | string | 100% | |
| `home_team`, `away_team` | string | 100% | Kan ha NBSP |
| `home_score`, `away_score` | int | 100% | |
| `venue` | string | 100% | Kan ha dubbla mellanslag |
| `league` | string | 100% | |
| `period_scores` | list | **Partiell** – tom för ungdomsmatcher | |
| `home_team_stats` | object | 100% | Se §3 re: save_pct |
| `away_team_stats` | object | 100% | |
| `events` | list | 100% (men varierar i rikedom) | |
| `goalkeepers` | list | ~100% | |
| `player_stats` | list | **Nästan alltid tom** | Förväntad i SHL/Allsvenskan, men saknas |
| `referees`, `linesmen` | list | Bred täckning | |
| `home_team_lineup` | object | **Partiell** – tom för vissa matcher | |
| `away_team_lineup` | object | **Partiell** | |
| `metadata.scraped_at` | ISO string | 100% | |
| `metadata.scraper_version` | string | 100% | |

### Events (per match)
| Fält | Värden observerade |
|------|-------------------|
| `event_type` | `goal`, `penalty`, `goalkeeper_change`, `timeout`, `other` |
| `goal_type` | `even_strength`, `power_play`, `short_handed`, `penalty_shot`, `unknown` |
| `period` | 1, 2, 3, 4 (OT) |
| `assists` | Lista `[{number, name}]` (kan vara tom) |
| `positive_participants` / `negative_participants` | Spelarnummer (finns bara i SHL/Allsvenskan-events) |
| `powerplay_number` | Int (PP1, PP2...) – bara i högtier-matcher |

### Lineup-format (2 varianter – se §3)
**Ny format** (vanligast): `lines[].forwards[] + lines[].defense[]` med `{number, name, position, starting}`
**Gammalt format** (oklart om det förekommer): `lines[].left_wing, center, right_wing, left_defense, right_defense`

---

## 3. Kvalitetsrapport

### 3.1 game_id-täckning per datum (kritisk)
| Period | Täckning game_id | Orsak |
|--------|-----------------|-------|
| 2021-01-01 (ny år) | **0%** | Scraper hann ej (eller matcher ej inlagda) |
| 2021-01-15 | 80% | Delvis täckt |
| 2021-09 (pre-season) | 29–31% | Pre-season-matcher registreras senare i systemet |
| 2021-10 (seriestart) | 89% | Reguljär säsong bättre täckt |
| 2021-12 | 99% | Nästan komplett |

**Konsekvens**: Matcher utan `game_id` kan aldrig länkas till `game_details` eller PDF:er. De är **matchlista-only** och ger bara lag+liga+datum+resultat.

**Rekommendation**: Sätt `null`-flagga i Silver; inkludera i `games`-tabell men markera `has_details=FALSE`.

### 3.2 save_percentage-logik (kritisk schemainsikt)
`home_team_stats.save_percentage` är **hemmalaget målvaktens räddningsprocent**, INTE skott-procent.

**Korrekt formel**:
```
home_save_pct = home_team_stats.saves / away_team_stats.shots
away_save_pct = away_team_stats.saves / home_team_stats.shots
```

Validerat på 3 matcher – avvikelse < 0.01%. Min transform-kod måste använda cross-referens vid beräkning, inte `saves/own_shots`.

**Ytterligare check**: `home_score = away_shots - home_saves` (och vice versa). Verifierat på alla 3 filer – ger korrekt målkontroll.

### 3.3 Encoding/whitespace-problem
| Problem | Fält | Frekvens | Fix |
|---------|------|----------|-----|
| `\xa0` (NBSP) | `home_team`, `away_team` | Sällsynt men existerar | `str.replace('\xa0', ' ').strip()` |
| `\t` (tab) | `league` | Observerat: `"Preseason ATG Hockeyettan\t"` | `str.strip()` |
| Dubbla mellanslag | `venue` | Observerat: `"Ljungby Arena  A-hallen"` | `re.sub(r' +', ' ', s).strip()` |
| Sammansatta lagnamn | `home_team` | `"Helsingborg HC Ungdom\xa0-\xa0IF Troja"` (2 lag spelar som ett) | Bevara som-är, dokumentera |

### 3.4 period_scores-problem
- **Tom lista** i ~50% av granskade filer (framför allt ungdomsmatcher)
- **OT/förlängning**: Ingen explicit indikation i game-objektet – kan bara detekteras via `len(period_scores) > 3` eller via events med `period=4`
- **Score-summering**: Period-summor stämmer med slutresultat i alla validerade filer

### 3.5 Lineup-formatvarianter
Två distinkta format hittade i fältet `lines`:

**Format A (nytt, vanligast)**:
```json
{"line": 1, "forwards": [{number, name, position, starting}], "defense": [...]}
```
- `position` = `"LW"`, `"C"`, `"RW"`, `"MV"` (målvakt)
- `starting` = bool

**Format B (gammalt, oklart om det finns i data)**:
```json
{"line_number": 1, "left_wing": {number, name}, "center": {...}, ...}
```
Vår nuvarande transformer i `transform_swe_games.py` implementerar Format B. **Behöver uppdateras till Format A.**

### 3.6 player_stats – i princip alltid tom
Även Allsvenskan-matcher (t.ex. MoDo–Almtuna 2021-12-15) har `player_stats: []`. Individuell statistik per spelare finns **inte i JSON** som standard – bara i PDF-rapporterna (`05_Player_Summary.pdf`).

### 3.7 Liga-strängar – ojämnt format
Liganamnet är fri text med inkonsistenser:
- Blandat prefix: `"ATG Hockeyettan Södra vår"` vs `"AllEttan Södra"` (troligen samma liga)
- Distriktssuffix: `"HockeyTvåan Södra A , Region Syd"` (mellanslag före komma)
- `league_id` (numeriskt) är **den stabila nyckeln** – använd den som primärnyckel, inte liga-strängen

---

## 4. Målschema

### `swe_games`
```sql
game_id          VARCHAR PRIMARY KEY,   -- Swehockey-id (kan vara NULL för okänd match)
game_date        DATE NOT NULL,
season           VARCHAR(4),            -- Kalenderår: '2021', '2022' etc.
league           VARCHAR,               -- Rensat (strip, NBSP->space)
league_id        VARCHAR,               -- Stabil nyckel till liga-dimension
home_team        VARCHAR,               -- Rensat
away_team        VARCHAR,
home_score       INTEGER,
away_score       INTEGER,
home_points      INTEGER,               -- 2/1/0 (OT-förlust=1)
away_points      INTEGER,
went_to_ot       BOOLEAN,               -- len(period_scores)>3 OR period=4 i events
venue            VARCHAR,               -- Rensat
match_time       VARCHAR(5),            -- HH:MM
home_shots       INTEGER,
away_shots       INTEGER,
home_saves       INTEGER,               -- Hemmalaget målvaktens räddningar (mot bortalagets skott)
away_saves       INTEGER,
home_save_pct    FLOAT,                 -- home_saves/away_shots
away_save_pct    FLOAT,                 -- away_saves/home_shots
home_pim         INTEGER,
away_pim         INTEGER,
periods          INTEGER,               -- Antal perioder (3=reg, 4=OT, etc.)
has_details      BOOLEAN,               -- FALSE om game_id=null i datum-index
scraped_at       TIMESTAMP,
source_url       VARCHAR                -- metadata.source_urls.events
```

### `swe_game_events`
```sql
game_id          VARCHAR NOT NULL,
game_date        DATE,
period           INTEGER,
event_time       VARCHAR(10),           -- "MM:SS" eller "" (ibland saknas)
event_type       VARCHAR,               -- goal|penalty|goalkeeper_change|timeout|other
team             VARCHAR,               -- Lagförkortning (varierar i längd)
player_name      VARCHAR,
player_number    VARCHAR,
goal_type        VARCHAR,               -- even_strength|power_play|short_handed|penalty_shot|unknown|NULL
penalty_minutes  INTEGER,
penalty_start    VARCHAR,
penalty_end      VARCHAR,
score_home       INTEGER,
score_away       INTEGER,
assists          JSON,                  -- [{number, name}]
powerplay_number INTEGER,               -- NULL om ej PP
PRIMARY KEY (game_id, period, event_time, event_type, player_name)
```

### `swe_game_goalkeepers`
```sql
game_id          VARCHAR NOT NULL,
game_date        DATE,
team             VARCHAR,
name             VARCHAR,
number           VARCHAR,
saves            INTEGER,
shots_against    INTEGER,               -- = motståndarlaget shots (cross-referens)
save_pct         FLOAT,                 -- saves/shots_against
PRIMARY KEY (game_id, team, name)
```

### `swe_game_lineups`
```sql
game_id          VARCHAR NOT NULL,
game_date        DATE,
team             VARCHAR,
is_home          BOOLEAN,
head_coach       VARCHAR,
assistant_coach  VARCHAR,
line_number      INTEGER,               -- NULL för målvakter och extra
position         VARCHAR,               -- G|LW|C|RW|LD|RD|EXTRA|MV (Swedish format)
player_name      VARCHAR,
player_number    VARCHAR,
is_starting      BOOLEAN,               -- Från lineup.starting-fältet
PRIMARY KEY (game_id, team, position, player_number)
```

### `swe_leagues` (dimension, byggs separat)
```sql
league_id        VARCHAR PRIMARY KEY,
league_name      VARCHAR,               -- Kanoniserat namn
level            INTEGER,               -- 1=SHL, 2=Allsvenskan, 3=Hockeyettan, ...
gender           VARCHAR,               -- M/F/U (ungdom)
age_group        VARCHAR,               -- Senior|J20|J18|U16|U15|U14|...
district         VARCHAR,               -- Svenska Ishockeyförbundet | Stockholms IHF | ...
```

---

## 5. Valideringsregler

### Nivå 1 – Obligatorisk (blockerar Silver-godkännande)
```python
# R1: Mål-konsistens (kan bara kontrolleras om period_scores finns)
assert away_shots - home_saves == home_score  # eller diff <= 1 (OT-mål kan sakna period_score)
assert home_shots - away_saves == away_score

# R2: Poängräkning
assert home_score + away_score >= 0
assert home_score != away_score or went_to_ot  # oavgjort bara OK om OT (ingen SO i SWE?)

# R3: save_pct beräknas korrekt (cross-referens)
expected_home_sv = home_saves / away_shots if away_shots else None
assert abs(expected_home_sv - home_save_pct) < 0.01  # max 0.01% avvikelse

# R4: Inga negativa mål
assert home_score >= 0 and away_score >= 0
```

### Nivå 2 – Varning (loggas, men blockerar ej)
```python
# W1: Encoding-issues
if '\xa0' in home_team or '\t' in league:
    log_warning("encoding_issue", game_id, field, value)

# W2: event_type=other (okänt händelseformat)
for e in events:
    if e['event_type'] == 'other':
        log_warning("unknown_event", game_id, e.get('raw_type'))

# W3: Matcher utan game_id i datum-index
if game_id is None:
    log_warning("no_game_id", date, home_team, away_team)

# W4: goal_type=unknown
if goal_type == 'unknown':
    log_warning("unknown_goal_type", game_id, period, event_time)

# W5: Slutresultat ≠ summa periods (om period_scores finns och är icke-tom)
if period_scores:
    ps_sum_home = sum(p['home'] for p in period_scores)
    if ps_sum_home != home_score:
        log_warning("period_sum_mismatch", game_id, ps_sum_home, home_score)
```

### Nivå 3 – Statistisk anomali (för analytics-pipeline)
```python
# A1: Ovanligt högt antal mål (>15 total → sannolikt ungdomsmatch eller felregistrering)
if home_score + away_score > 15:
    log_anomaly("high_score", game_id, home_score, away_score)

# A2: 0-0 slutresultat (troligen ej avslutat eller felregistrerat)
if home_score == 0 and away_score == 0:
    log_anomaly("zero_zero_result", game_id)

# A3: Save_pct > 100% (pekar på datafel)
if home_save_pct > 100 or away_save_pct > 100:
    log_anomaly("impossible_save_pct", game_id)
```

---

## 6. Nästa 5 konkreta steg

### Steg 1: Fixa transform_swe_games.py – lineup-format
Nuvarande transformer implementerar Format B (gammalt). Faktisk data använder Format A:
```python
# lines[].forwards[]/defense[] istället för lines[].left_wing etc.
```
→ Uppdatera `_extract_lineups()` i `mage_project/transformers/transform_swe_games.py`.

### Steg 2: Fixa save_pct-beräkning i transformer
Lägg till cross-referens-beräkning i `_extract_game_row()`:
```python
home_save_pct = home_saves / away_shots if away_shots else None
away_save_pct = away_saves / home_shots if home_shots else None
```

### Steg 3: Bygg `scripts/validate_swe_sample.py`
Kör valideringsreglerna (Nivå 1+2) mot ett urval game_details och ger rapport:
- Antal filer med encoding-issues
- Antal filer med period_score-mismatch
- Histogram över `event_type`-fördelning per liga-level
- game_id-täckning per datumintervall

### Steg 4: Bygg liga-dimensionstabellen
Läs alla unika `(league_id, league)` ur games/-index → bygg `swe_leagues`-tabell med manuellt annoterade `level`, `age_group`, `gender`-kolumner för top-50 liga_id:n (täcker >90% av matcher).

### Steg 5: Kör swe_games_pipeline för första gången mot färdig data
När scrapern kommit upp i säsong 2022+:
```bash
# Mage UI → swe_games_pipeline → Run with variables:
swe_games_year = 2022
```
→ Verifiera Silver-parquet + MotherDuck `swe.games` ser ut som förväntat.

---

## Bilagor

### Observerade event.type="other" – raw_type-värden
- `"2 - 1"` (troligen numerisk straff-duration utan rätt typ)
- Bör filtreras ut vid aggregering men bevaras i rådata

### Lineup-position-vocabulary
| Värde i data | Svensk term | Standardisera till |
|---|---|---|
| `LW` | Vänsterforward | `LW` |
| `C` | Center | `C` |
| `RW` | Högerforward | `RW` |
| `MV` | Målvakt | `G` |
| `LD` / `RD` | Backs | `LD` / `RD` |

### OT/SO-detektering (ingen explicit flagga)
```python
# Period 4 = OT, period 5 = 2OT, etc.
went_to_ot = any(e.get('period', 0) > 3 for e in events)
# Alternativt:
went_to_ot = len(period_scores) > 3
```
Inga SO-matcher observerade (SE-hockey har inte SO i reguljär serie för seniorer).
