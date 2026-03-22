# Data Dictionary – NHL Gold

Dokumentation av tabeller och kolumner för Insight Engine och analys.
Källa: `documentation/DATA_DICTIONARY.yaml`.
Kör `python scripts/validate_data_dictionary.py` för att uppdatera denna fil.

---

## `games`

En rad per match. Innehåller hemmalag, bortalag, mål, status, lagnivå-statistik (SOG, PP, hits, etc.).

**Grain:** En rad per game_id

### Kolumner

| Kolumn | Typ | Beskrivning |
|--------|-----|-------------|
| game_id | BIGINT | Unikt match-ID (NHL API gamePk) |
| game_date | DATE | Datum för matchen. Använd för sortering och lookback. |
| season | BIGINT | Säsong (t.ex. 20242025). Format YYYY(YYYY+1). |
| home_team_abbr | VARCHAR | Hemmalag förkortning (t.ex. TOR, BOS) |
| away_team_abbr | VARCHAR | Bortalag förkortning |
| home_team_id | BIGINT | Hemmalag NHL ID |
| away_team_id | BIGINT | Bortalag NHL ID |
| home_score | BIGINT | Mål hemmalag |
| away_score | BIGINT | Mål bortalag |
| home_points | BIGINT | NHL-poäng hemmalag (2 vinst, 1 OT/SO-förlust, 0 förlust) |
| away_points | BIGINT | NHL-poäng bortalag |
| status | VARCHAR | Matchens status (t.ex. FINAL, LIVE) |
| home_sog | BIGINT | Skott på mål hemmalag |
| away_sog | BIGINT | Skott på mål bortalag |
| home_pp_goals | DOUBLE | Powerplay-mål hemmalag |
| away_pp_goals | DOUBLE | Powerplay-mål bortalag |
| home_hits | BIGINT | Tacklingar hemmalag |
| away_hits | BIGINT | Tacklingar bortalag |
| home_blocked | BIGINT | Blockade skott hemmalag |
| away_blocked | BIGINT | Blockade skott bortalag |
| venue | VARCHAR | Arenanamn |
| venue_location | VARCHAR | Stad/plats för arenan |
| start_time_utc | VARCHAR | Starttid UTC |

---

## `team_game_stats`

En rad per lag per match. Unpivot av games – enklare för lag-trender (poäng per match, mål per match).

**Grain:** En rad per (game_id, team_abbr)

**Insight Engine – primär för:** team_points_streak, team_goals_trend, team_sog_trend

### Kolumner

| Kolumn | Typ | Beskrivning |
|--------|-----|-------------|
| game_id | BIGINT | Match-ID |
| game_date | DATE | Datum. Använd ORDER BY game_date för trendanalys. |
| season | BIGINT | Säsong |
| team_abbr | VARCHAR | Lagförkortning (t.ex. TOR) |
| opponent_abbr | VARCHAR | Motståndarlag |
| is_home | BOOLEAN | True = hemmamatch, False = bortamatch. För hemma/borta-splits. |
| goals_for | BIGINT | Mål gjorda av laget denna match |
| goals_against | BIGINT | Mål insläppta |
| team_points | BIGINT | Poäng denna match (2 vinst, 1 OT-förlust, 0 förlust). Huvudsaklig för points-per-game-trender. |
| sog | BIGINT | Skott på mål |
| pp_goals | DOUBLE | Powerplay-mål |
| hits | BIGINT | Tacklingar |
| blocked_shots | BIGINT | Blockade skott |
| venue | VARCHAR | Arena (för arena-trender) |

---

## `player_game_stats`

En rad per spelare per match, med spelarnamn. Använd för spelar-trender (poäng, mål, assist, TOI).

**Grain:** En rad per (game_id, player_id)

**Insight Engine – primär för:** player_breakout, player_points_trend, player_goals_streak

### Kolumner

| Kolumn | Typ | Beskrivning |
|--------|-----|-------------|
| game_id | BIGINT | Match-ID |
| game_date | DATE | Datum |
| player_id | BIGINT | Spelar-ID (NHL) |
| player_first_name | VARCHAR | Förnamn (för human-readable output) |
| player_last_name | VARCHAR | Efternamn |
| team_abbr | VARCHAR | Lag |
| is_home | BOOLEAN | Hemma eller borta |
| position | VARCHAR | F, D, C, LW, RW, G. Filtrera position='G' för målvakter. |
| goals | DOUBLE | Mål denna match |
| assists | DOUBLE | Assists |
| points | DOUBLE | Poäng (mål + assist). Huvudsaklig för breakout/trend-detection. |
| plus_minus | DOUBLE | Plus/minus |
| shots | DOUBLE | Skott på mål (SOG) |
| toi_seconds | BIGINT | Speltid i sekunder |
| hits | DOUBLE | Tacklingar |
| blocked_shots | DOUBLE | Blockade skott |
| power_play_goals | DOUBLE | Powerplay-mål |
| short_handed_goals | VARCHAR | Uppspelade mål |
| faceoff_win_pct | DOUBLE | Vunna tekningar (0–1 eller procent) |
| saves | DOUBLE | Räddningar (målvakter) |
| shots_against | DOUBLE | Skott mot (målvakter) |
| save_pct | DOUBLE | Räddningsprocent (0–1). Huvudsaklig för goalie_trend-detection. |
| goals_against | DOUBLE | Insläppta mål (målvakter) |
| even_strength_goals_against | DOUBLE | Insläppta jämnstyrka (målvakter) |
| power_play_goals_against | DOUBLE | Insläppta powerplay (målvakter) |
| shorthanded_goals_against | DOUBLE | Insläppta short-handed (målvakter) |

---

## `game_players`

Samma som player_game_stats men utan spelarnamn (join till players). Raw spelarstatistik per match.

**Grain:** En rad per (game_id, player_id)

---

## `game_events`

Play-by-play händelser från playByPlay (mål, skott, straff, faceoff, hit, etc.). Finns bara om källfilen har playByPlay.

**Grain:** En rad per (game_id, event_id)

### Kolumner

| Kolumn | Typ | Beskrivning |
|--------|-----|-------------|
| game_id | BIGINT | Match-ID |
| game_date | DATE | Datum |
| event_id | BIGINT | Unikt ID per händelse |
| period | BIGINT | Period (1, 2, 3, 4 för OT) |
| period_type | VARCHAR | REGULAR, OVERTIME, SHOOTOUT |
| time_remaining | VARCHAR | T.ex. "15:30" |
| event_type | VARCHAR | Goal, Shot, Penalty, Faceoff, Hit, Block, etc. |
| team_abbr | VARCHAR | Lag |
| player_id | BIGINT | Huvudspelare (t.ex. målskytt) |
| secondary_player_id | BIGINT | Assisterande (mål) |
| description | VARCHAR | Händelsebeskrivning |

---

## `game_stories`

Game story (rubrik, brödtext) från gameStory. Finns bara om källfilen har gameStory. För texthantering/LLM.

**Grain:** En rad per game_id

### Kolumner

| Kolumn | Typ | Beskrivning |
|--------|-----|-------------|
| game_id | BIGINT | Match-ID |
| game_date | DATE | Datum |
| headline | VARCHAR | Rubrik |
| body | VARCHAR | Brödtext |

---

## `teams`

En rad per lag. Conference, division, namn.

**Grain:** En rad per team

### Kolumner

| Kolumn | Typ | Beskrivning |
|--------|-----|-------------|
| id | BIGINT | NHL team ID |
| abbr | VARCHAR | Förkortning (TOR, BOS, …) |
| name | VARCHAR | Fullt namn |
| conference | VARCHAR | Conference |
| division | VARCHAR | Division |

---

## `players`

En rad per spelare. Namn, position, födelsedatum.

**Grain:** En rad per player

### Kolumner

| Kolumn | Typ | Beskrivning |
|--------|-----|-------------|
| id | BIGINT | NHL player ID |
| firstName | VARCHAR | Förnamn |
| lastName | VARCHAR | Efternamn |
| positionCode | VARCHAR | Position (F, D, G, …) |

---

## `skater_stats`

Säsongsstatistik per skridskoåkare. Använd för baseline (poäng/säsong, poäng/match).

**Grain:** En rad per (season, playerId)

**Insight Engine – primär för:** player_breakout

### Kolumner

| Kolumn | Typ | Beskrivning |
|--------|-----|-------------|
| playerId | BIGINT | Spelar-ID |
| season | BIGINT | Säsong |
| gamesPlayed | BIGINT | Matcher spelade |
| goals | BIGINT | Mål säsongen |
| assists | BIGINT | Assists |
| points | BIGINT | Poäng (baseline för breakout) |
| pointsPerGame | DOUBLE | Poäng per match (baseline) |

---

## `goalie_stats`

Säsongsstatistik per målvakt. Baseline för save_pct, GAA.

**Grain:** En rad per (season, playerId)

**Insight Engine – primär för:** goalie_save_pct_trend

### Kolumner

| Kolumn | Typ | Beskrivning |
|--------|-----|-------------|
| playerId | BIGINT | Spelar-ID |
| season | BIGINT | Säsong |
| savePct | DOUBLE | Räddningsprocent säsongen (baseline) |
| goalsAgainstAverage | DOUBLE | GAA |

---

## `team_stats`

Säsongsstatistik per lag. Baseline för lag-trender.

**Grain:** En rad per (season, teamId)

**Insight Engine – primär för:** team_points_streak

### Kolumner

| Kolumn | Typ | Beskrivning |
|--------|-----|-------------|
| teamId | BIGINT | Lag-ID |
| season | BIGINT | Säsong |
| points | BIGINT | Poäng säsongen |
| gamesPlayed | BIGINT | Matcher |
| pointPct | DOUBLE | Poängprocent |

---

## `standings`

Tabellställning per datum. Konferens, division, poäng.

**Grain:** En rad per (team, season, date)

---

## `edge_skaters`

NHL EDGE skater-mått (skotthastighet, åkhastighet, etc.). Endast NHL.

**Grain:** En rad per (season, category, player_id)

---

## `edge_goalies`

NHL EDGE målvakts-mått. Endast NHL.

**Grain:** En rad per (season, category, player_id)

---

## `edge_teams`

NHL EDGE lag-mått. Endast NHL.

**Grain:** En rad per (season, category, team_id)

---
