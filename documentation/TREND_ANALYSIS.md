# Trendanalys per match (lag och spelare)

Med nuvarande datastruktur kan du ta ut **så detaljerade trender per match som källan tillåter** – för lag och spelare. Detta dokument beskriver vilka tabeller och fält som används samt exempel på frågor.

## Snabbreferens: tabell och nycklar per behov

| Behov | Tabell(er) | Nycklar |
|-------|------------|--------|
| Spelarstatistik per matchdatum | `player_game_stats` (eller `game_players` + `players`) | `game_date`, `player_id`, `team_abbr` |
| Lagstatistik per matchdatum | `team_game_stats` (eller `games`) | `game_date`, `team_abbr`, `opponent_abbr` |

- **Spelare:** Använd **`player_game_stats`** (har redan `player_first_name`, `player_last_name`). Filtrera på `game_date` / `player_id`.
- **Lag:** Använd **`team_game_stats`** (en rad per lag per match: `goals_for`, `goals_against`, `sog`, `is_home`). Filtrera på `team_abbr`. Alternativt `games` med hemma/borta-kolumner.
- Alla Gold-tabellnamn är på engelska; se **documentation/GOLD_SCHEMA.md** för full lista och namngivningsstandard.

---

## 1. Vilka tabeller och fält används?

### games (en rad per match)

| Fält | Beskrivning |
|------|-------------|
| `game_id`, `game_date`, `season` | Identifierare och tid |
| `home_team_abbr`, `away_team_abbr` | Lag |
| `home_score`, `away_score` | Mål |
| `home_points`, `away_points` | NHL-poäng (2 vinst, 1 OT/SO-förlust, 0 ordinarie förlust) |
| `status` | T.ex. FINAL |
| **Lagstatistik per match** | |
| `home_sog`, `away_sog` | Skott på mål |
| `home_pp_goals`, `away_pp_goals` | Powerplay-mål |
| `home_pp_opportunities`, `away_pp_opportunities` | Powerplay-chanser |
| `home_hits`, `away_hits` | Tacklingar |
| `home_blocked`, `away_blocked` | Blockade skott |
| `home_pim`, `away_pim` | Utvisningsminuter |
| `home_giveaways`, `away_giveaways` | Förluster av puck |
| `home_takeaways`, `away_takeaways` | Återtag av puck |
| `home_faceoff_pct`, `away_faceoff_pct` | Vunna tekningar (%) |
| **Plats** | |
| `venue`, `venue_location` | Arena och stad (för trend per arena) |

### game_players (en rad per spelare per match)

| Fält | Beskrivning |
|------|-------------|
| `game_id`, `game_date`, `player_id`, `team_abbr` | Identifierare |
| `is_home` | True = hemmamatch, False = bortamatch (enkel hemma/borta-trend) |
| `position`, `sweater_number` | Position och tröjnummer |
| **Skridsko** | |
| `goals`, `assists`, `points`, `plus_minus` | Poäng |
| `shots`, `pim`, `toi_seconds` | Skott, utvisning, speltid (sekunder) |
| `hits`, `blocked_shots`, `shifts` | Tacklingar, blockeringar, byten |
| `power_play_goals`, `short_handed_goals` | PP- och SH-mål |
| `giveaways`, `takeaways` | Puckförluster / återtag |
| `faceoff_win_pct` | Vunna tekningar (%) |
| **Målvakt** | |
| `saves`, `shots_against`, `save_pct`, `goals_against` | Grundstatistik |
| `even_strength_goals_against`, `power_play_goals_against`, `shorthanded_goals_against` | Mål insläppta per situation (trend per styrka) |

- **`home_points` / `away_points`** beräknas i pipelinen så att du direkt kan rita "poäng per match" för ett lag.

---

## 2. Trendkurva: poäng per match för ett lag

Du vill t.ex. se **poäng per match för TOR** över tid. Varje match ger laget antingen 0, 1 eller 2 poäng.

**Steg 1 – en rad per match med lagets poäng:**

```sql
SELECT
  game_date,
  game_id,
  CASE
    WHEN home_team_abbr = 'TOR' THEN home_points
    WHEN away_team_abbr = 'TOR' THEN away_points
  END AS team_points,
  CASE
    WHEN home_team_abbr = 'TOR' THEN home_score
    WHEN away_team_abbr = 'TOR' THEN away_score
  END AS goals_for,
  CASE
    WHEN home_team_abbr = 'TOR' THEN away_score
    WHEN away_team_abbr = 'TOR' THEN home_score
  END AS goals_against
FROM games
WHERE (home_team_abbr = 'TOR' OR away_team_abbr = 'TOR')
  AND game_date IS NOT NULL
  AND status LIKE 'Final%'
ORDER BY game_date;
```

**Steg 2 – glidande medel (t.ex. senaste 10 matcher):**

```sql
WITH team_games AS (
  SELECT
    game_date,
    CASE WHEN home_team_abbr = 'TOR' THEN home_points ELSE away_points END AS pts
  FROM games
  WHERE (home_team_abbr = 'TOR' OR away_team_abbr = 'TOR')
    AND status LIKE 'Final%'
)
SELECT
  game_date,
  pts,
  AVG(pts) OVER (ORDER BY game_date ROWS BETWEEN 9 PRECEDING AND CURRENT ROW) AS pts_rolling_10
FROM team_games
ORDER BY game_date;
```

Du kan rita `game_date` på x-axeln och `pts` respektive `pts_rolling_10` i t.ex. Streamlit/Plotly/Excel.

---

## 3. Trendkurva: mål per match för ett lag

Samma idé, men med mål istället för poäng:

```sql
SELECT
  game_date,
  CASE WHEN home_team_abbr = 'TOR' THEN home_score ELSE away_score END AS goals_for,
  CASE WHEN home_team_abbr = 'TOR' THEN away_score ELSE home_score END AS goals_against
FROM games
WHERE (home_team_abbr = 'TOR' OR away_team_abbr = 'TOR')
  AND status LIKE 'Final%'
ORDER BY game_date;
```

---

## 4. Trendkurva: poäng per match för en spelare

Använd **game_players** (en rad per spelare per match):

```sql
SELECT
  game_date,
  game_id,
  player_id,
  team_abbr,
  points,
  goals,
  assists
FROM game_players
WHERE player_id = 8479318   -- byt till önskat player_id
  AND game_date IS NOT NULL
ORDER BY game_date;
```

Glidande medel (t.ex. senaste 10 matcher):

```sql
SELECT
  game_date,
  points,
  AVG(points) OVER (ORDER BY game_date ROWS BETWEEN 9 PRECEDING AND CURRENT ROW) AS points_rolling_10
FROM game_players
WHERE player_id = 8479318
ORDER BY game_date;
```

---

## 5. Trendanalys: hemma vs borta (spelare)

Med `is_home` i **game_players** kan du enkelt splittra trender på hemmamatch vs bortamatch:

```sql
SELECT
  game_date,
  is_home,
  points,
  goals,
  shots,
  toi_seconds / 60.0 AS toi_minutes
FROM game_players
WHERE player_id = 8479318
ORDER BY game_date;
```

Glidande medel per kontext:

```sql
SELECT
  game_date,
  is_home,
  points,
  AVG(points) OVER (
    PARTITION BY is_home
    ORDER BY game_date
    ROWS BETWEEN 9 PRECEDING AND CURRENT ROW
  ) AS points_rolling_10
FROM game_players
WHERE player_id = 8479318
ORDER BY game_date;
```

---

## 6. Trendanalys per arena (lag)

Med `venue` och `venue_location` i **games** kan du analysera lagprestation per arena:

```sql
SELECT
  venue,
  venue_location,
  COUNT(*) AS games,
  SUM(CASE WHEN home_team_abbr = 'TOR' THEN home_points ELSE away_points END) AS total_pts,
  SUM(CASE WHEN home_team_abbr = 'TOR' THEN home_score ELSE away_score END) AS goals_for
FROM games
WHERE (home_team_abbr = 'TOR' OR away_team_abbr = 'TOR')
  AND status LIKE 'Final%'
GROUP BY venue, venue_location
ORDER BY games DESC;
```

---

## 7. Målvakt: trend per situation (ES/PP/SH)

Använd `even_strength_goals_against`, `power_play_goals_against`, `shorthanded_goals_against` för att följa målvaktsinsläpp per styrka:

```sql
SELECT
  game_date,
  goals_against,
  even_strength_goals_against,
  power_play_goals_against,
  shorthanded_goals_against,
  save_pct,
  shots_against
FROM game_players
WHERE player_id = 8471239
  AND position = 'G'
ORDER BY game_date;
```

---

## 8. Sammanfattning

- **Lag:** Använd **team_game_stats** (en rad per lag per match) eller **games** (en rad per match). Kolumner: goals_for, goals_against, sog, hits, venue, m.m.
- **Spelare:** Använd **player_game_stats** (med namn) eller **game_players** för statistik per match (mål, assist, TOI, hits, målvakt per situation).
- **Hemma/borta:** Filtrera på `is_home` i `game_players` / `player_game_stats` eller `team_game_stats`.
- **Arena:** `games.venue` / `games.venue_location`.

Alla vy-/tabellnamn i Gold är på engelska (se **GOLD_SCHEMA.md**). Efter **games_pipeline** + **refresh_duckdb_views** finns vyer som `games`, `game_players`, `player_game_stats`, `team_game_stats` i DuckDB; använd dem i Streamlit eller SQL.
