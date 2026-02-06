# S3-källor och pipelines – översikt

Denna fil listar **alla S3-sökvägar** som pipelinen läser från (Hetzner) och vilken pipeline / Silver-tabell de hamnar i. Använd den för att säkerställa att all data i bucketen tas med.

**Full datastruktur i Hetzner:** Se [HETZNER_S3_DATA_STRUCTURE_FOR_MAGE.md](../HETZNER_S3_DATA_STRUCTURE_FOR_MAGE.md) för exakt S3-nyckelstruktur, JSON-struktur per filtyp och rekommenderad Silver/Gold-design. Pipelinen är anpassad enligt den dokumentationen.

**Kör först** `python scripts/list_s3_bucket.py` (i containern eller med .env) för att se vad som faktiskt finns i bucketen. Jämför sedan med tabellerna nedan.

---

## 1. Vad pipelinen läser idag

### dimensions_pipeline (load_dimensions)

| S3-sökväg | Laddas? | Silver-tabell | Kommentar |
|-----------|---------|----------------|-----------|
| `nhl-data/basic/teams/all_teams.json` | ✅ | teams | |
| `nhl-data/basic/players/all_players.json` | ✅ | players | |
| `nhl-data/basic/players/players_by_team.json` | ✅ | (används för roster) | |
| `nhl-data/misc/countries.json` | ✅ | countries | |
| `nhl-data/basic/teams/rosters/{season}/all_rosters.json` | ✅ | roster | Root = dict med franchise_id som nyckel (stöds i transformer) |
| `nhl-data/basic/teams/rosters/{season}/roster_{franchise_id}.json` | ✅ | roster | Samma prefix; alla .json under rosters/ laddas |
| `nhl-data/basic/teams/**/*.json` (roster i namn) | ✅ fallback | roster | Om rosters/ tom |
| `nhl-data/basic/schedule/**/*.json` | ✅ | schedule | daily_YYYY-MM-DD.json, weekly.json, etc. |
| `nhl-data/helpers/**/*.json` | ✅ | game_ids | t.ex. game_ids_{season}.json → season + game_id |
| `nhl-data/misc/glossary.json` | ✅ | glossary | Ordlista statistiktermer |
| `nhl-data/misc/draft_year_and_rounds.json` | ✅ | draft | Draft-info |

### seasonal_stats_pipeline (load_seasonal_stats)

| S3-sökväg | Laddas? | Silver-tabell | Kommentar |
|-----------|---------|----------------|-----------|
| `nhl-data/basic/standings/league_standings_{season}.json` | ✅ | standings | + season_standing_manifest.json om det finns |
| `nhl-data/stats/skaters/**/*.json` | ✅ | skater_stats | |
| `nhl-data/stats/goalies/**/*.json` | ✅ | goalie_stats | |
| `nhl-data/stats/teams/**/*.json` | ✅ | team_stats | |
| `nhl-data/edge/skaters/**/*.json` | ✅ | edge_skaters | t.ex. landing_20252026.json |
| `nhl-data/edge/goalies/**/*.json` | ✅ | edge_goalies | |
| `nhl-data/edge/teams/**/*.json` | ✅ | edge_teams | |

### games_pipeline (load_games_incremental)

| S3-sökväg | Laddas? | Silver-tabell | Kommentar |
|-----------|---------|----------------|-----------|
| `nhl-data-reorganized/games/by_date/**/*.json` | ✅ | games, game_players | Exkl. games_summary.json |

---

## 2. Mappar som finns i S3 men inte laddas

Dessa mappar innehåller **samma boxscore-JSON** som under `by_date/` – bara kopior per lag respektive per spelare för enkel sökning. Pipelinen läser bara `by_date/` och plockar ut alla spelare från varje match → **game_players** får full spelarstatistik. Att även läsa by_team eller by_player ger ingen extra data, bara dubbletter.

| S3-sökväg | Beskrivning |
|-----------|-------------|
| `nhl-data-reorganized/games/by_team/**` | Samma boxscore per lag (kopior av by_date). |
| `nhl-data-reorganized/games/by_player/{playerId}/{date}/{gameId}.json` | Samma boxscore per spelare (kopior av by_date). Används inte i pipelinen – spelarstatistik kommer redan från by_date. |

---

## 3. Säkerställa att allt kommer med

1. **Lista bucketen:**  
   `docker exec tur-mage-ai-mage-1 bash -c "cd /home/src && python scripts/list_s3_bucket.py"`  
   Notera vilka mappar som har filer (t.ex. basic/, stats/, edge/, misc/, schedule/, helpers/).

2. **Jämför med tabellerna ovan:**  
   Varje mapp under `nhl-data/` och `nhl-data-reorganized/` ska antingen:
   - finnas i tabell 1 (laddas av någon pipeline), eller  
   - stå i tabell 2 (medvetet valfria).

3. **Saknas en mapp i tabell 1?**  
   Om det finns en **ny mapp** som scrapern skriver till: ange prefix och vilken pipeline det ska tillhöra, så kan vi lägga till list_keys + read i rätt loader.

4. **Efter ändringar:**  
   Kör respektive pipeline (dimensions, seasonal_stats, games), sedan **refresh_duckdb_views**, så hamnar allt i Gold och blir synligt i Streamlit.

---

## 4. Snabbreferens: prefix → pipeline

| Prefix | Pipeline |
|--------|----------|
| nhl-data/basic/ (teams, players, rosters, schedule) + nhl-data/helpers/ + nhl-data/misc/ (countries, glossary, draft) | dimensions_pipeline |
| nhl-data/basic/standings/ | seasonal_stats_pipeline |
| nhl-data/stats/ | seasonal_stats_pipeline |
| nhl-data/edge/ | seasonal_stats_pipeline |
| nhl-data-reorganized/games/by_date/ | games_pipeline |

---

## 5. Varför Bronze (~100 GB) är mycket större än Silver

**Bronze** = all rådata i S3 (raw JSON). För matcher finns **samma matchfil många gånger**:

- **by_date/** – en kopia per match (det pipelinen läser).
- **by_team/** – samma fil igen, en kopia per lag som spelar (2× per match).
- **by_player/** – samma fil igen, en kopia per spelare (30+ gånger per match).

Dessutom är varje JSON-fil stor: full **play-by-play** (hundratals events), **rosterSpots**, **gameStory**, nästlade objekt. Det ger snabbt tiotals GB bara för by_date, och med by_team + by_player blir det lätt ~100 GB.

**Silver** = det pipelinen skriver ut:

- Vi läser **bara by_date/** (en kopia per match).
- Vi sparar bara **utplockade fält**: matchnivå (resultat, datum, arena, lag, SOG, etc.) och spelarnivå (mål, assist, SOG, hits, PIM, etc.) – **inte** hela play-by-play eller gameStory.
- **Parquet** är kolumnformat och komprimerar mycket bättre än JSON.

Därför är Silver i GB mycket mindre än Bronze, **men du får med alla matcher och all spelarstatistik** som finns i by_date. För att verifiera täckning och storlek:

```bash
docker exec tur-mage-ai-mage-1 bash -c "cd /home/src && python scripts/compare_bronze_silver_volume.py"
```

Scriptet visar antal matcher i S3 (by_date) vs Silver samt förklaring till storleksskillnaden.

**Strukturerad analys av alla filer och strukturer (för att uppdatera pipelinen):**  
Kör `python scripts/analyze_data_structure.py` (i containern: `docker exec tur-mage-ai-mage-1 bash -c "cd /home/src && python scripts/analyze_data_structure.py"`). Det skapar `documentation/DATA_STRUCTURE_REPORT.md` och `DATA_STRUCTURE_REPORT.json` med:
- S3-inventering (alla prefix, antal filer, exempelnyckel)
- JSON-struktur per källtyp (sample)
- Silver-tabeller med kolumner och antal rader
- Mapping källa → pipeline → Silver

Använd rapporten för att se vad som finns i Bronze vs vad som finns i Silver och uppdatera transformer/export så att all data kommer med. Alternativ: `--no-s3` (bara Silver) eller `--s3-quick` (max 500 filer per prefix, snabbare).

**Inventering av alla JSON-nycklar (per filtyp):** Kör `python scripts/inventory_json_keys_from_s3.py`. Scriptet läser en sample-fil per källa från S3 och skriver alla nyckelvägar till `documentation/JSON_KEY_INVENTORY.md`. Jämför med transform/export så att ingen data saknas.

---

## 6. Justeringar enligt HETZNER_S3_DATA_STRUCTURE_FOR_MAGE.md

Pipelinen har granskats mot [HETZNER_S3_DATA_STRUCTURE_FOR_MAGE.md](../HETZNER_S3_DATA_STRUCTURE_FOR_MAGE.md). Gjorda anpassningar:

| Område | Status |
|--------|--------|
| **Matcher** | Endast `by_date/` används; `games_summary.json` exkluderas. ✅ |
| **Boxscore** | Både reorganized-format (boxscore.homeTeam/awayTeam, playerByGameStats) och API-format (gameData/liveData) stöds i transform_games. ✅ |
| **game_players** | TOI konverteras till sekunder (`toi_seconds`), faceoffWinningPctg, saves, shots_against, save_pct, goals_against m.m. extraheras. ✅ |
| **Roster** | `all_rosters.json` med root = dict (franchise_id som nyckel) stöds nu i transform_dimensions. ✅ |
| **Standings / schedule / stats / edge** | Sökvägar och filnamn (league_standings_{season}.json, summary_{season}.json, landing_{season}.json) täcks av nuvarande list_keys. ✅ |
| **Misc** | countries, glossary, draft_year_and_rounds.json laddas. ✅ |
| **Helpers** | game_ids_{season}.json används; all_players_* och all_players_summary_* behöver inte egna Silver-tabeller enligt dokumentationen. ✅ |

Filer som finns i S3 men inte krävs för Silver enligt dokumentationen: `all_teams.csv`, `franchises.json`, `games_summary.json` (valfritt).
