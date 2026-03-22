# MotherDuck NHL – datatäckning

*Genererat: 2026-02-26 11:41*

Denna rapport beskriver vilken data som finns i MotherDuck NHL-databasen.
Kör `python scripts/analyze_motherduck_data.py` för att uppdatera.

---

## Sammanfattning

| Tabell | Rader |
|--------|-------|
| countries | 49 |
| database_snapshots | N/A |
| databases | N/A |
| draft | 63 |
| edge_goalies | 45 |
| edge_skaters | 56 |
| edge_teams | 63 |
| game_ids | 2832 |
| game_players | 47665 |
| games | 1190 |
| glossary | 321 |
| goalie_stats | 275 |
| owned_shares | N/A |
| player_game_stats | 47665 |
| players | 796 |
| query_history | N/A |
| recent_queries | N/A |
| roster | 1592 |
| schedule | 59 |
| shared_with_me | N/A |
| skater_stats | 275 |
| standings | 2756 |
| storage_info | N/A |
| storage_info_history | N/A |
| team_game_stats | 2380 |
| team_stats | 352 |
| teams | 32 |

**Matcher:** 1190 st, datumspann 2024-05-06 00:00:00 till 2026-02-22 00:00:00

**Game players (spelare × matcher):** 47665 rader

---

## Detaljer per tabell

### `countries`

| Attribut | Värde |
|----------|-------|
| Rader | 49 |
| Kolumner | 11 |

**Kolumner:**

| Kolumn | Typ |
|--------|-----|
| id | VARCHAR |
| country3Code | VARCHAR |
| countryCode | VARCHAR |
| countryName | VARCHAR |
| hasPlayerStats | BIGINT |
| imageUrl | VARCHAR |
| iocCode | VARCHAR |
| isActive | BIGINT |
| nationalityName | VARCHAR |
| olympicUrl | VARCHAR |
| thumbnailUrl | VARCHAR |

---

### `database_snapshots`

| Attribut | Värde |
|----------|-------|
| Rader | N/A |
| Kolumner | 10 |

**Kolumner:**

| Kolumn | Typ |
|--------|-----|
| database_name | VARCHAR |
| database_id | UUID |
| snapshot_id | UUID |
| snapshot_name | VARCHAR |
| created_ts | TIMESTAMP |
| active_bytes | UBIGINT |
| bytes_written | UBIGINT |
| bytes_deleted | UBIGINT |
| user_name | VARCHAR |
| user_id | UUID |

---

### `databases`

| Attribut | Värde |
|----------|-------|
| Rader | N/A |
| Kolumner | 6 |

**Kolumner:**

| Kolumn | Typ |
|--------|-----|
| name | VARCHAR |
| uuid | UUID |
| created_ts | TIMESTAMP WITH TIME ZONE |
| transient | BOOLEAN |
| historical_snapshot_retention | INTERVAL |
| type | VARCHAR |

---

### `draft`

| Attribut | Värde |
|----------|-------|
| Rader | 63 |
| Kolumner | 3 |

**Kolumner:**

| Kolumn | Typ |
|--------|-----|
| id | BIGINT |
| draftYear | BIGINT |
| rounds | BIGINT |

---

### `edge_goalies`

| Attribut | Värde |
|----------|-------|
| Rader | 45 |
| Kolumner | 8 |

**Kolumner:**

| Kolumn | Typ |
|--------|-----|
| season | BIGINT |
| category | VARCHAR |
| player_id | BIGINT |
| team_abbr | VARCHAR |
| value_savePctg | DOUBLE |
| value_saves | DOUBLE |
| value_goalsAgainst | DOUBLE |
| value_games | DOUBLE |

---

### `edge_skaters`

| Attribut | Värde |
|----------|-------|
| Rader | 56 |
| Kolumner | 12 |

**Kolumner:**

| Kolumn | Typ |
|--------|-----|
| season | BIGINT |
| category | VARCHAR |
| player_id | BIGINT |
| team_abbr | VARCHAR |
| value_shotSpeed_metric | DOUBLE |
| value_shotSpeed_imperial | DOUBLE |
| value_skatingSpeed_metric | DOUBLE |
| value_skatingSpeed_imperial | DOUBLE |
| value_distanceSkated_metric | DOUBLE |
| value_distanceSkated_imperial | DOUBLE |
| value_sog | DOUBLE |
| value_zoneTime | DOUBLE |

---

### `edge_teams`

| Attribut | Värde |
|----------|-------|
| Rader | 63 |
| Kolumner | 10 |

**Kolumner:**

| Kolumn | Typ |
|--------|-----|
| season | BIGINT |
| category | VARCHAR |
| team_id | BIGINT |
| team_abbr | VARCHAR |
| value_attempts | DOUBLE |
| value_bursts | DOUBLE |
| value_distanceSkated_metric | DOUBLE |
| value_distanceSkated_imperial | DOUBLE |
| value_sog | DOUBLE |
| value_zoneTime | DOUBLE |

---

### `game_ids`

| Attribut | Värde |
|----------|-------|
| Rader | 2832 |
| Kolumner | 3 |

**Kolumner:**

| Kolumn | Typ |
|--------|-----|
| season | VARCHAR |
| game_id | BIGINT |
| source_key | VARCHAR |

---

### `game_players`

| Attribut | Värde |
|----------|-------|
| Rader | 47665 |
| Kolumner | 33 |

**Kolumner:**

| Kolumn | Typ |
|--------|-----|
| game_id | BIGINT |
| game_date | DATE |
| player_id | BIGINT |
| team_abbr | VARCHAR |
| is_home | BOOLEAN |
| position | VARCHAR |
| sweater_number | BIGINT |
| goals | DOUBLE |
| assists | DOUBLE |
| points | DOUBLE |
| plus_minus | DOUBLE |
| shots | DOUBLE |
| pim | BIGINT |
| toi_seconds | BIGINT |
| hits | DOUBLE |
| power_play_goals | DOUBLE |
| short_handed_goals | VARCHAR |
| blocked_shots | DOUBLE |
| shifts | DOUBLE |
| giveaways | DOUBLE |
| takeaways | DOUBLE |
| faceoff_win_pct | DOUBLE |
| saves | DOUBLE |
| shots_against | DOUBLE |
| save_pct | DOUBLE |
| goals_against | DOUBLE |
| even_strength_goals_against | DOUBLE |
| power_play_goals_against | DOUBLE |
| shorthanded_goals_against | DOUBLE |
| even_strength_shots_against | VARCHAR |
| … (+3 till) | |

**Unika (game_id, player_id):**

- Total rader: 47665
- Unika par: 47665 (inga dubletter)

**Spelarstatistik-täckning:**

- Målvakter (position=G): 4756.0
- Skridskoåkare: 42909.0
- Har goals: 42909.0
- Har assists: 42909.0
- Har toi_seconds: 47624.0
- Har save_pct (målvakter): 2569.0

---

### `games`

| Attribut | Värde |
|----------|-------|
| Rader | 1190 |
| Kolumner | 41 |

**Kolumner:**

| Kolumn | Typ |
|--------|-----|
| game_id | BIGINT |
| game_date | DATE |
| season | BIGINT |
| home_team_abbr | VARCHAR |
| away_team_abbr | VARCHAR |
| home_team_id | BIGINT |
| away_team_id | BIGINT |
| home_score | BIGINT |
| away_score | BIGINT |
| home_points | BIGINT |
| away_points | BIGINT |
| status | VARCHAR |
| home_sog | BIGINT |
| away_sog | BIGINT |
| home_pp_goals | DOUBLE |
| away_pp_goals | DOUBLE |
| home_pp_opportunities | VARCHAR |
| away_pp_opportunities | VARCHAR |
| home_hits | BIGINT |
| away_hits | BIGINT |
| home_blocked | BIGINT |
| away_blocked | BIGINT |
| home_pim | BIGINT |
| away_pim | BIGINT |
| home_faceoff_pct | VARCHAR |
| away_faceoff_pct | VARCHAR |
| home_giveaways | BIGINT |
| away_giveaways | BIGINT |
| home_takeaways | BIGINT |
| away_takeaways | BIGINT |
| … (+11 till) | |

**Datums- och säsongsstatistik (games):**

| Mätvärde | Värde |
|----------|-------|
| Första match | 2024-05-06 00:00:00 |
| Senaste match | 2026-02-22 00:00:00 |
| Unika matcher (game_id) | 1190 |
| Totala rader | 1190 |
| Dubletter (rader - unika) | 0 |
| Antal säsonger | 3 |

**Matcher per säsong:**

| Säsong | Matcher |
|--------|---------|
| 20232024 | 5 |
| 20242025 | 813 |
| 20252026 | 372 |

**Null-täckning (viktiga kolumner):**

- game_id: 1190/1190 (100.0%)
- game_date: 1190/1190 (100.0%)
- home_team_abbr: 1190/1190 (100.0%)
- away_team_abbr: 1190/1190 (100.0%)
- home_score: 1189/1190 (99.9%)
- away_score: 1189/1190 (99.9%)

**Exempel – senaste 3 matcher:**

| game_id | game_date | home_team_abbr | away_team_abbr | home_score | away_score | status |
|---|---|---|---|---|---|---|
| 2025090030 | 2026-02-22 00:00:00 | CAN | USA | 1 | 2 | FINAL |
| 2025090029 | 2026-02-21 00:00:00 | SVK | FIN | 1 | 6 | FINAL |
| 2025090028 | 2026-02-20 00:00:00 | USA | SVK | 6 | 2 | FINAL |

---

### `glossary`

| Attribut | Värde |
|----------|-------|
| Rader | 321 |
| Kolumner | 7 |

**Kolumner:**

| Kolumn | Typ |
|--------|-----|
| id | BIGINT |
| abbreviation | VARCHAR |
| definition | VARCHAR |
| firstSeasonForStat | DOUBLE |
| fullName | VARCHAR |
| languageCode | VARCHAR |
| lastUpdated | VARCHAR |

---

### `goalie_stats`

| Attribut | Värde |
|----------|-------|
| Rader | 275 |
| Kolumner | 24 |

**Kolumner:**

| Kolumn | Typ |
|--------|-----|
| assists | BIGINT |
| gamesPlayed | BIGINT |
| gamesStarted | BIGINT |
| goalieFullName | VARCHAR |
| goals | BIGINT |
| goalsAgainst | BIGINT |
| goalsAgainstAverage | DOUBLE |
| lastName | VARCHAR |
| losses | BIGINT |
| otLosses | BIGINT |
| penaltyMinutes | BIGINT |
| playerId | BIGINT |
| points | BIGINT |
| savePct | DOUBLE |
| saves | BIGINT |
| seasonId | BIGINT |
| shootsCatches | VARCHAR |
| shotsAgainst | BIGINT |
| shutouts | BIGINT |
| teamAbbrevs | VARCHAR |
| ties | VARCHAR |
| timeOnIce | BIGINT |
| wins | BIGINT |
| season | BIGINT |

---

### `owned_shares`

| Attribut | Värde |
|----------|-------|
| Rader | N/A |
| Kolumner | 9 |

**Kolumner:**

| Kolumn | Typ |
|--------|-----|
| name | VARCHAR |
| url | VARCHAR |
| source_db_name | VARCHAR |
| source_db_uuid | UUID |
| access | VARCHAR |
| visibility | VARCHAR |
| update | VARCHAR |
| created_ts | TIMESTAMP WITH TIME ZONE |
| grants | STRUCT(grantee_name VARCHAR, "access" VARCHAR)[] |

---

### `player_game_stats`

| Attribut | Värde |
|----------|-------|
| Rader | 47665 |
| Kolumner | 35 |

**Kolumner:**

| Kolumn | Typ |
|--------|-----|
| game_id | BIGINT |
| game_date | DATE |
| player_id | BIGINT |
| team_abbr | VARCHAR |
| is_home | BOOLEAN |
| position | VARCHAR |
| sweater_number | BIGINT |
| goals | DOUBLE |
| assists | DOUBLE |
| points | DOUBLE |
| plus_minus | DOUBLE |
| shots | DOUBLE |
| pim | BIGINT |
| toi_seconds | BIGINT |
| hits | DOUBLE |
| power_play_goals | DOUBLE |
| short_handed_goals | VARCHAR |
| blocked_shots | DOUBLE |
| shifts | DOUBLE |
| giveaways | DOUBLE |
| takeaways | DOUBLE |
| faceoff_win_pct | DOUBLE |
| saves | DOUBLE |
| shots_against | DOUBLE |
| save_pct | DOUBLE |
| goals_against | DOUBLE |
| even_strength_goals_against | DOUBLE |
| power_play_goals_against | DOUBLE |
| shorthanded_goals_against | DOUBLE |
| even_strength_shots_against | VARCHAR |
| … (+5 till) | |

**Täckning (player_game_stats):**

- Unika spelare: 1241
- Unika matcher: 1189
- Datumspann: 2024-05-06 00:00:00 till 2026-02-22 00:00:00

---

### `players`

| Attribut | Värde |
|----------|-------|
| Rader | 796 |
| Kolumner | 15 |

**Kolumner:**

| Kolumn | Typ |
|--------|-----|
| id | BIGINT |
| headshot | VARCHAR |
| firstName | VARCHAR |
| lastName | VARCHAR |
| sweaterNumber | DOUBLE |
| positionCode | VARCHAR |
| shootsCatches | VARCHAR |
| heightInInches | BIGINT |
| weightInPounds | BIGINT |
| heightInCentimeters | BIGINT |
| weightInKilograms | BIGINT |
| birthDate | VARCHAR |
| birthCity | VARCHAR |
| birthCountry | VARCHAR |
| birthStateProvince | VARCHAR |

---

### `query_history`

| Attribut | Värde |
|----------|-------|
| Rader | N/A |
| Kolumner | 23 |

**Kolumner:**

| Kolumn | Typ |
|--------|-----|
| query_id | UUID |
| query_text | VARCHAR |
| start_time | TIMESTAMP WITH TIME ZONE |
| end_time | TIMESTAMP WITH TIME ZONE |
| execution_time | INTERVAL |
| wait_time | INTERVAL |
| total_elapsed_time | INTERVAL |
| error_message | VARCHAR |
| error_type | VARCHAR |
| user_agent | VARCHAR |
| user_name | VARCHAR |
| query_nr | UBIGINT |
| transaction_nr | UBIGINT |
| connection_id | UUID |
| duckdb_id | UUID |
| duckdb_version | VARCHAR |
| instance_type | VARCHAR |
| query_type | VARCHAR |
| bytes_uploaded | UBIGINT |
| bytes_downloaded | UBIGINT |
| bytes_spilled_to_disk | UBIGINT |
| duckling_id | VARCHAR |
| session_name | VARCHAR |

---

### `recent_queries`

| Attribut | Värde |
|----------|-------|
| Rader | N/A |
| Kolumner | 23 |

**Kolumner:**

| Kolumn | Typ |
|--------|-----|
| query_id | UUID |
| query_text | VARCHAR |
| start_time | TIMESTAMP WITH TIME ZONE |
| end_time | TIMESTAMP WITH TIME ZONE |
| execution_time | INTERVAL |
| wait_time | INTERVAL |
| total_elapsed_time | INTERVAL |
| error_message | VARCHAR |
| error_type | VARCHAR |
| user_agent | VARCHAR |
| user_name | VARCHAR |
| query_nr | UBIGINT |
| transaction_nr | UBIGINT |
| connection_id | UUID |
| duckdb_id | UUID |
| duckdb_version | VARCHAR |
| instance_type | VARCHAR |
| query_type | VARCHAR |
| bytes_uploaded | UBIGINT |
| bytes_downloaded | UBIGINT |
| bytes_spilled_to_disk | UBIGINT |
| duckling_id | VARCHAR |
| session_name | VARCHAR |

---

### `roster`

| Attribut | Värde |
|----------|-------|
| Rader | 1592 |
| Kolumner | 4 |

**Kolumner:**

| Kolumn | Typ |
|--------|-----|
| season | BIGINT |
| team_id | VARCHAR |
| player_id | BIGINT |
| team_abbr | VARCHAR |

---

### `schedule`

| Attribut | Värde |
|----------|-------|
| Rader | 59 |
| Kolumner | 12 |

**Kolumner:**

| Kolumn | Typ |
|--------|-----|
| schedule_date | VARCHAR |
| schedule_source_key | VARCHAR |
| gamePk | BIGINT |
| gameDate | VARCHAR |
| season | BIGINT |
| home_team_id | BIGINT |
| away_team_id | BIGINT |
| gameType | BIGINT |
| status | VARCHAR |
| start_time_utc | VARCHAR |
| game_state | VARCHAR |
| venue | VARCHAR |

---

### `shared_with_me`

| Attribut | Värde |
|----------|-------|
| Rader | N/A |
| Kolumner | 8 |

**Kolumner:**

| Kolumn | Typ |
|--------|-----|
| name | VARCHAR |
| url | VARCHAR |
| owner | VARCHAR |
| visibility | VARCHAR |
| created_ts | TIMESTAMP WITH TIME ZONE |
| updated_ts | TIMESTAMP WITH TIME ZONE |
| update_mode | VARCHAR |
| access | VARCHAR |

---

### `skater_stats`

| Attribut | Värde |
|----------|-------|
| Rader | 275 |
| Kolumner | 27 |

**Kolumner:**

| Kolumn | Typ |
|--------|-----|
| assists | BIGINT |
| evGoals | BIGINT |
| evPoints | BIGINT |
| faceoffWinPct | DOUBLE |
| gameWinningGoals | BIGINT |
| gamesPlayed | BIGINT |
| goals | BIGINT |
| lastName | VARCHAR |
| otGoals | BIGINT |
| penaltyMinutes | BIGINT |
| playerId | BIGINT |
| plusMinus | BIGINT |
| points | BIGINT |
| pointsPerGame | DOUBLE |
| positionCode | VARCHAR |
| ppGoals | BIGINT |
| ppPoints | BIGINT |
| seasonId | BIGINT |
| shGoals | BIGINT |
| shPoints | BIGINT |
| shootingPct | DOUBLE |
| shootsCatches | VARCHAR |
| shots | BIGINT |
| skaterFullName | VARCHAR |
| teamAbbrevs | VARCHAR |
| timeOnIcePerGame | DOUBLE |
| season | BIGINT |

---

### `standings`

| Attribut | Värde |
|----------|-------|
| Rader | 2756 |
| Kolumner | 91 |

**Kolumner:**

| Kolumn | Typ |
|--------|-----|
| conferenceAbbrev | VARCHAR |
| conferenceHomeSequence | DOUBLE |
| conferenceL10Sequence | DOUBLE |
| conferenceName | VARCHAR |
| conferenceRoadSequence | DOUBLE |
| conferenceSequence | DOUBLE |
| date | VARCHAR |
| divisionAbbrev | VARCHAR |
| divisionHomeSequence | DOUBLE |
| divisionL10Sequence | DOUBLE |
| divisionName | VARCHAR |
| divisionRoadSequence | DOUBLE |
| divisionSequence | DOUBLE |
| gameTypeId | DOUBLE |
| gamesPlayed | DOUBLE |
| goalDifferential | DOUBLE |
| goalDifferentialPctg | DOUBLE |
| goalAgainst | DOUBLE |
| goalFor | DOUBLE |
| goalsForPctg | DOUBLE |
| homeGamesPlayed | DOUBLE |
| homeGoalDifferential | DOUBLE |
| homeGoalsAgainst | DOUBLE |
| homeGoalsFor | DOUBLE |
| homeLosses | DOUBLE |
| homeOtLosses | DOUBLE |
| homePoints | DOUBLE |
| homeRegulationPlusOtWins | DOUBLE |
| homeRegulationWins | DOUBLE |
| homeTies | DOUBLE |
| … (+61 till) | |

---

### `storage_info`

| Attribut | Värde |
|----------|-------|
| Rader | N/A |
| Kolumner | 13 |

**Kolumner:**

| Kolumn | Typ |
|--------|-----|
| database_name | VARCHAR |
| database_id | UUID |
| created_ts | TIMESTAMP_S |
| deleted_ts | TIMESTAMP_S |
| username | VARCHAR |
| active_bytes | BIGINT |
| historical_bytes | BIGINT |
| kept_for_cloned_bytes | BIGINT |
| retained_for_clone_bytes | BIGINT |
| failsafe_bytes | BIGINT |
| transient | BOOLEAN |
| historical_snapshot_retention | INTERVAL |
| computed_ts | TIMESTAMP_S |

---

### `storage_info_history`

| Attribut | Värde |
|----------|-------|
| Rader | N/A |
| Kolumner | 13 |

**Kolumner:**

| Kolumn | Typ |
|--------|-----|
| database_name | VARCHAR |
| database_id | UUID |
| created_ts | TIMESTAMP_S |
| deleted_ts | TIMESTAMP_S |
| username | VARCHAR |
| active_bytes | BIGINT |
| historical_bytes | BIGINT |
| kept_for_cloned_bytes | BIGINT |
| retained_for_clone_bytes | BIGINT |
| failsafe_bytes | BIGINT |
| transient | BOOLEAN |
| historical_snapshot_retention | INTERVAL |
| computed_ts | TIMESTAMP_S |

---

### `team_game_stats`

| Attribut | Värde |
|----------|-------|
| Rader | 2380 |
| Kolumner | 31 |

**Kolumner:**

| Kolumn | Typ |
|--------|-----|
| game_id | BIGINT |
| game_date | DATE |
| season | BIGINT |
| status | VARCHAR |
| game_state | VARCHAR |
| ot_periods | DOUBLE |
| last_period_type | VARCHAR |
| period_number | BIGINT |
| period_type | VARCHAR |
| is_home | BOOLEAN |
| team_id | BIGINT |
| team_abbr | VARCHAR |
| opponent_abbr | VARCHAR |
| goals_for | BIGINT |
| goals_against | BIGINT |
| team_points | BIGINT |
| sog | BIGINT |
| pp_goals | DOUBLE |
| pp_opportunities | VARCHAR |
| hits | BIGINT |
| blocked_shots | BIGINT |
| pim | BIGINT |
| giveaways | BIGINT |
| takeaways | BIGINT |
| faceoff_win_pct | VARCHAR |
| venue | VARCHAR |
| venue_location | VARCHAR |
| start_time_utc | VARCHAR |
| reg_periods | BIGINT |
| game_type | BIGINT |
| … (+1 till) | |

**Täckning (team_game_stats):**

- Unika lag: 44
- Unika matcher: 1190
- Datumspann: 2024-05-06 00:00:00 till 2026-02-22 00:00:00

---

### `team_stats`

| Attribut | Värde |
|----------|-------|
| Rader | 352 |
| Kolumner | 26 |

**Kolumner:**

| Kolumn | Typ |
|--------|-----|
| faceoffWinPct | DOUBLE |
| gamesPlayed | BIGINT |
| goalsAgainst | BIGINT |
| goalsAgainstPerGame | DOUBLE |
| goalsFor | BIGINT |
| goalsForPerGame | DOUBLE |
| losses | BIGINT |
| otLosses | BIGINT |
| penaltyKillNetPct | DOUBLE |
| penaltyKillPct | DOUBLE |
| pointPct | DOUBLE |
| points | BIGINT |
| powerPlayNetPct | DOUBLE |
| powerPlayPct | DOUBLE |
| regulationAndOtWins | BIGINT |
| seasonId | BIGINT |
| shotsAgainstPerGame | DOUBLE |
| shotsForPerGame | DOUBLE |
| teamFullName | VARCHAR |
| teamId | BIGINT |
| teamShutouts | BIGINT |
| ties | VARCHAR |
| wins | BIGINT |
| winsInRegulation | BIGINT |
| winsInShootout | BIGINT |
| season | BIGINT |

---

### `teams`

| Attribut | Värde |
|----------|-------|
| Rader | 32 |
| Kolumner | 11 |

**Kolumner:**

| Kolumn | Typ |
|--------|-----|
| conference | VARCHAR |
| division | VARCHAR |
| name | VARCHAR |
| common_name | VARCHAR |
| abbr | VARCHAR |
| logo | VARCHAR |
| franchise_id | BIGINT |
| conference_abbr | VARCHAR |
| conference_name | VARCHAR |
| division_abbr | VARCHAR |
| division_name | VARCHAR |

---
