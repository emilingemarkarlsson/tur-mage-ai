# Analys: Nycklar i källan vs vad vi plockar ut

Syfte: se vilka nycklar som finns i S3-källorna (enligt `JSON_KEY_INVENTORY.md`) mot vad pipelinen extraherar till Silver, och minimera luckor.

---

## 1. teams

| Källa (inventering) | Vad vi plockar ut | Status / åtgärd |
|---------------------|-------------------|------------------|
| `teams[].abbr`, `common_name`, `conference`, `division`, `franchise_id`, `logo`, `name` | `flatten_dict_for_row` → alla toppnycklar; nästlade `conference`/`division` som dict (serialiseras till JSON i export) | **Åtgärd:** platta ut `conference.abbr`, `conference.name`, `division.abbr`, `division.name` till egna kolumner så de blir enkla att fråga |

**Slutsats:** Vi lägger till `conference_abbr`, `conference_name`, `division_abbr`, `division_name` i team-raderna.

---

## 2. players

| Källa | Vad vi plockar ut | Status |
|-------|-------------------|--------|
| `[].forwards[]` / `defensemen[]` / `goalies[]` med `birthCity.default`, `birthCountry`, `birthDate`, `firstName.default`, `headshot`, `heightInCentimeters`, `id`, `lastName.default`, `positionCode`, `shootsCatches`, `sweaterNumber`, `weightInKilograms` | `flatten_player()` → alla skalära fält + `.default` för nästlade; listan byggs från alla lag (forwards/defensemen/goalies) | **OK** – vi får med det som behövs för analys |

---

## 3. standings

| Källa | Vad vi plockar ut | Status |
|-------|-------------------|--------|
| `standings[]` med t.ex. `conferenceAbbrev`, `divisionAbbrev`, `gamesPlayed`, `goalFor`/`goalAgainst`, `points`, `wins`, `losses`, `otLosses`, `teamAbbrev`, `teamName`, `placeName`, `streakCode`, `streakCount`, `homeWins`/`roadWins`, `l10Wins`, `standingsDateTimeUtc`, m.m. | `_flatten_standings`: `extract_list(..., ["standings", "records", ...])`; om `records[].teamRecords` plattas det ut; annars används raderna som de är | **Åtgärd:** Säkerställ att vi först provar `["standings"]` så att källor med root `standings` som array används. Därefter får alla nycklar per rad med (ingen explicit fältlista) |

**Slutsats:** Vi provar `["standings"]` först i `_flatten_standings` så att all data från `league_standings_*.json` kommer med.

---

## 4. schedule

| Källa | Vad vi plockar ut | Status / åtgärd |
|------|-------------------|------------------|
| `gameWeek[].games[]`: `id`, `awayTeam`/`homeTeam`, `startTimeUTC`, `venue.default`, `gameState`, `gameType`, `season`, `gameScheduleState`, `tvBroadcasts`, m.m. | `_schedule_to_rows`: idag bara `dates[].games[]` (NHL API); per match: `schedule_date`, `gamePk`, `gameDate`, `season`, `home_team_id`, `away_team_id`, `gameType`, `status` | **Åtgärd:** (1) Stöd även `gameWeek[].games[]`. (2) Lägg till i varje rad: `start_time_utc`, `game_state`, `venue`, `game_id` (id) |

**Slutsats:** Vi lägger till stöd för `gameWeek` och fler fält per match.

---

## 5. helpers (game_ids)

| Källa | Vad vi plockar ut | Status |
|-------|-------------------|--------|
| Root = array av game IDs (eller objekt med `gameIds`/`game_ids`) | `_helpers_to_rows`: list eller dict med gameIds; rad = `season`, `game_id`, `source_key` | **OK** |

---

## 6. countries

| Källa | Vad vi plockar ut | Status |
|-------|-------------------|--------|
| `[].country3Code`, `countryCode`, `countryName`, `hasPlayerStats`, `id`, `imageUrl`, `iocCode`, `isActive`, `nationalityName`, `olympicUrl`, `thumbnailUrl` | `extract_list` + fallback för dict-format; alla nycklar följer med i raden | **OK** |

---

## 7. glossary

| Källa | Vad vi plockar ut | Status |
|-------|-------------------|--------|
| `[].abbreviation`, `definition`, `firstSeasonForStat`, `fullName`, `id`, `languageCode`, `lastUpdated` | `_glossary_to_rows`: terms från flera vägar; hela term-objektet som rad | **OK** |

---

## 8. draft

| Källa | Vad vi plockar ut | Status |
|-------|-------------------|--------|
| `[].draftYear`, `id`, `rounds` | `_draft_to_rows`: items från rounds/years/data/items eller root-lista; hela objektet som rad | **OK** |

---

## 9. rosters

| Källa | Vad vi plockar ut | Status |
|-------|-------------------|--------|
| `{franchise_id}.defensemen[]`, `forwards[]`, `goalies[]` med spelardetaljer | `_roster_rows_from_franchise_keyed_payload` → `season`, `team_id`, `player_id`; `team_abbr` fylls från teams | **OK** – spelardetaljer finns i dimensionen `players` |

---

## 10. skater_stats / goalie_stats / team_stats

| Källa | Vad vi plockar ut | Status |
|-------|-------------------|--------|
| Skaters: `assists`, `evGoals`, `evPoints`, `faceoffWinPct`, `gameWinningGoals`, `gamesPlayed`, `goals`, `points`, `ppGoals`, `shGoals`, `shootingPct`, `timeOnIcePerGame`, m.m. | `_flatten`: lista från payload; **hela dict per rad** → alla nycklar kommer med | **OK** |
| Goalies: `gamesStarted`, `goalsAgainst`, `savePct`, `shutouts`, m.m. | Samma | **OK** |
| Teams: `faceoffWinPct`, `goalsForPerGame`, `penaltyKillPct`, `powerPlayPct`, m.m. | Samma | **OK** |

---

## 11. edge_skaters / edge_goalies / edge_teams

| Källa | Vad vi plockar ut | Status |
|-------|-------------------|--------|
| `leaders.*` (t.ex. `hardestShot`, `defensiveZoneTime`, `highDangerSOG`) med `player`/`team` och mätvärden | `_flatten_edge`: söker efter `data.skaters.items`, `data.items` osv. – **källfilerna har root `leaders`**, inte `data.items` | **Lucka:** Edge-filer har struktur `{ leaders: { hardestShot: {...}, ... }, seasonsWithEdgeStats: [] }`. Vi får idag ingen data om vi bara letar efter listor. För att få med “så mycket som möjligt” kan man antingen: (a) exportera raw payload per fil, eller (b) lägga till logik som plattar `leaders` till en rad per kategori (t.ex. `category=hardestShot`, `player_id`, `shotSpeed.metric`) och skriver till edge-tabeller. – nu implementerat.) | **OK**

**Slutsats:** Edge-leaders plattas nu till Silver (en rad per kategori per säsong).

---

## 12. games (boxscore / gameStory)

| Källa | Vad vi plockar ut | Status / åtgärd |
|-------|-------------------|------------------|
| `boxscore`: `id`, `gameDate`, `season`, `homeTeam`/`awayTeam`, `venue`, `venueLocation`, `periodDescriptor`, `startTimeUTC`, `regPeriods`, `gameType`, `limitedScoring`, `gameState`, `clock`, `tvBroadcasts`, `playerByGameStats` (alla fält) | Games: `game_id`, `game_date`, `season`, `home/away_team_abbr`, poäng, status, SOG, PP, hits, blocked, PIM, faceoff, giveaways/takeaways, venue, venue_location | **Åtgärd:** Lägg till `start_time_utc`, `reg_periods`, `game_type`, `limited_scoring` i game-raderna |
| `boxscore.playerByGameStats`: defense/forwards/goalies med `assists`, `blockedShots`, `faceoffWinningPctg`, `giveaways`, `goals`, `hits`, `pim`, `plusMinus`, `points`, `powerPlayGoals`, `shifts`, `sog`, `toi`, `takeaways`; målvakter: `evenStrengthGoalsAgainst`, `powerPlayGoalsAgainst`, `shorthandedGoalsAgainst`, `saves`, `shotsAgainst`, `savePctg` | Game_players: game_id, player_id, team_abbr, is_home, position, sweater_number, goals, assists, points, plus_minus, shots, pim, toi_seconds, hits, power_play_goals, short_handed_goals, blocked_shots, shifts, giveaways, takeaways, faceoff_win_pct, målvaktsfält | **OK** – täcker inventerade nycklar |

**Slutsats:** Vi lägger till de fyra game-fälten ovan.

---

## Sammanfattning åtgärder

| Område | Åtgärd |
|--------|--------|
| **teams** | Platta `conference` och `division` till `conference_abbr`, `conference_name`, `division_abbr`, `division_name`. |
| **standings** | Prova `["standings"]` först i `_flatten_standings`. |
| **schedule** | Stöd `gameWeek[].games[]` och lägg till `start_time_utc`, `game_state`, `venue`, samt säkerställ `game_id`/`gamePk`. |
| **games** | Lägg till `start_time_utc`, `reg_periods`, `game_type`, `limited_scoring` i `_extract_game_row`. |
| **edge_*** | **Klart:** `_flatten_edge_leaders` plattar `leaders` till en rad per kategori med player_id/team_id och mätvärden. |

Efter dessa ändringar får vi med mer av de nycklar som finns i källorna, med fokus på skalära och enkelt plattade fält som passar Parquet/export.
