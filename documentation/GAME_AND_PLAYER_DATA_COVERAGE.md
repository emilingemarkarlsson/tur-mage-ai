# Data coverage: per game and per player per game

This document ensures **all available data** from the game/boxscore source is extracted into `games` and `game_players`. Source: `nhl-data-reorganized/games/by_date/{date}/{gameId}.json` (boxscore + gameData + liveData).

---

## 1. Source vs extraction: games (one row per game)

| Source path (boxscore / gameData / liveData) | Extracted to `games` | Status |
|---------------------------------------------|----------------------|--------|
| `boxscore.id` / `gameId` / `gameData.game.pk` | `game_id` | ✅ |
| `game_date` (from loader) / `boxscore.gameDate` | `game_date` | ✅ |
| `boxscore.season` / `gameData.game.season` | `season` | ✅ |
| `boxscore.homeTeam.abbrev`, `awayTeam.abbrev` | `home_team_abbr`, `away_team_abbr` | ✅ |
| `boxscore.homeTeam.id`, `awayTeam.id` | `home_team_id`, `away_team_id` | ✅ added |
| `homeTeam.score`, `awayTeam.score` / linescore | `home_score`, `away_score` | ✅ |
| Computed from score + status | `home_points`, `away_points` | ✅ |
| `gameData.status.detailedState` / `boxscore.gameState` | `status` | ✅ |
| `boxscore.gameState` | `game_state` | ✅ added |
| `boxscore.startTimeUTC` | `start_time_utc` | ✅ |
| `boxscore.regPeriods` | `reg_periods` | ✅ |
| `boxscore.gameType` / `gameData.game.type` | `game_type` | ✅ |
| `boxscore.limitedScoring` | `limited_scoring` | ✅ |
| `boxscore.gameOutcome.otPeriods` | `ot_periods` | ✅ added |
| `boxscore.gameOutcome.lastPeriodType` | `last_period_type` | ✅ added |
| `boxscore.periodDescriptor.number` | `period_number` | ✅ added |
| `boxscore.periodDescriptor.periodType` | `period_type` | ✅ added |
| Team-level SOG, PP, hits, blocked, PIM, faceoff, giveaways, takeaways | `home_*` / `away_*` | ✅ |
| `boxscore.venue`, `venueLocation` | `venue`, `venue_location` | ✅ |
| `boxscore.clock`, `tvBroadcasts`, `easternUTCOffset` | — | Omitted (optional; can add if needed) |

**Conclusion:** Games table now includes all scalar game-level fields needed for analysis; optional fields (clock, broadcasts) can be added later if required.

---

## 2. Source vs extraction: game_players (one row per player per game)

### 2.1 Skaters (forwards + defense)

| Source (playerByGameStats.*.forwards/defense[]) | Extracted | Status |
|-------------------------------------------------|-----------|--------|
| `playerId` | `player_id` | ✅ |
| `position`, `sweaterNumber` | `position`, `sweater_number` | ✅ |
| `goals`, `assists`, `points`, `plusMinus` | `goals`, `assists`, `points`, `plus_minus` | ✅ |
| `sog` | `shots` | ✅ |
| `pim`, `toi` | `pim`, `toi_seconds` | ✅ |
| `hits`, `blockedShots`, `shifts` | `hits`, `blocked_shots`, `shifts` | ✅ |
| `powerPlayGoals`, `shortHandedGoals` | `power_play_goals`, `short_handed_goals` | ✅ |
| `giveaways`, `takeaways` | `giveaways`, `takeaways` | ✅ |
| `faceoffWinningPctg` | `faceoff_win_pct` | ✅ |
| `name` (default) | — | Join to `players` for names; `player_game_stats` has `player_first_name`, `player_last_name` |

**Conclusion:** All skater stats from the source are extracted.

### 2.2 Goalies

| Source (playerByGameStats.*.goalies[]) | Extracted | Status |
|----------------------------------------|-----------|--------|
| `playerId`, `position`, `sweaterNumber` | `player_id`, `position`, `sweater_number` | ✅ |
| `saves`, `shotsAgainst`, `savePctg` | `saves`, `shots_against`, `save_pct` | ✅ |
| `goalsAgainst` | `goals_against` | ✅ |
| `evenStrengthGoalsAgainst`, `powerPlayGoalsAgainst`, `shorthandedGoalsAgainst` | `even_strength_goals_against`, `power_play_goals_against`, `shorthanded_goals_against` | ✅ |
| Computed: goals_against * 3600 / toi_seconds | `gaa` | ✅ |
| `evenStrengthShotsAgainst` | `even_strength_shots_against` | ✅ added |
| `powerPlayShotsAgainst` | `power_play_shots_against` | ✅ added |
| `shorthandedShotsAgainst` | `shorthanded_shots_against` | ✅ added |
| `toi` | `toi_seconds` (skaters get from skater stats; goalies from toi) | ✅ |

**Conclusion:** All goalie stats from the source are now extracted, including shots-against by situation.

---

## 3. Two source formats supported

The transformer supports:

1. **Reorganized format:** `boxscore.homeTeam` / `awayTeam` (abbrev, score, id), `boxscore.playerByGameStats` with `homeTeam`/`awayTeam` and `forwards`/`defense`/`goalies` arrays.
2. **NHL API format:** `gameData.teams.home`/`away`, `liveData.boxscore.teams.home`/`away.players`, each player with `stats.skaterStats` or `stats.goalieStats`.

Both paths produce the same set of columns (snake_case) so that Silver Parquet and Gold DuckDB have a single, consistent schema.

---

## 4. How to verify you get “all data”

- **Games:** Query `games` and check that rows have non-null values for `game_id`, `game_date`, `home_team_abbr`, `away_team_abbr`, and that `home_team_id`/`away_team_id` are present when the source has them. Use `player_game_stats` / `team_game_stats` for per-player and per-team views.
- **Game players:** Query `game_players` (or `player_game_stats`). For skaters, check goals, assists, toi_seconds, shots, etc. For goalies, check saves, shots_against, and the new columns `even_strength_shots_against`, `power_play_shots_against`, `shorthanded_shots_against`.
- **Row counts:** One row per game in `games`; one row per player per game in `game_players` (no duplicate `(game_id, player_id)`). Run `scripts/validate_games_players.py` to check duplicates.

After running **games_pipeline**, Silver and Gold will contain the above; re-run the pipeline after any schema change so that new columns appear in Parquet and DuckDB.
