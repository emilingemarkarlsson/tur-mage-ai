-- =============================================================================
-- MotherDuck NHL-databas: valideringsfrågor
-- Kör i MotherDuck: öppna databasen "nhl", klistra in och kör varje fråga
-- =============================================================================

-- 1. Antal rader per tabell (kommentera bort tabeller som inte finns ännu)
SELECT 'teams' AS tabell, count(*) AS rader FROM main.teams
UNION ALL SELECT 'players', count(*) FROM main.players
UNION ALL SELECT 'countries', count(*) FROM main.countries
UNION ALL SELECT 'games', count(*) FROM main.games
UNION ALL SELECT 'game_players', count(*) FROM main.game_players
UNION ALL SELECT 'player_game_stats', count(*) FROM main.player_game_stats
UNION ALL SELECT 'team_game_stats', count(*) FROM main.team_game_stats
UNION ALL SELECT 'standings', count(*) FROM main.standings
UNION ALL SELECT 'skater_stats', count(*) FROM main.skater_stats
UNION ALL SELECT 'goalie_stats', count(*) FROM main.goalie_stats
UNION ALL SELECT 'edge_skaters', count(*) FROM main.edge_skaters
UNION ALL SELECT 'roster', count(*) FROM main.roster
UNION ALL SELECT 'schedule', count(*) FROM main.schedule
UNION ALL SELECT 'game_ids', count(*) FROM main.game_ids
ORDER BY tabell;


-- 2. Datumspann för matcher
SELECT 
  min(game_date) AS forsta_match,
  max(game_date) AS senaste_match,
  count(DISTINCT game_id) AS antal_matcher
FROM main.games;


-- 3. Inga dubletter på game_id
SELECT 
  count(*) AS total_rader,
  count(DISTINCT game_id) AS unika_game_id,
  CASE WHEN count(*) = count(DISTINCT game_id) THEN 'OK' ELSE 'FEL: dubletter' END AS status
FROM main.games;


-- 4. Senaste 5 matcher
SELECT game_id, game_date, home_team_abbr, away_team_abbr, home_score, away_score, status
FROM main.games
ORDER BY game_date DESC
LIMIT 5;


-- 5. Referentiell integritet: game_players finns för alla games?
SELECT 
  (SELECT count(DISTINCT game_id) FROM main.games) AS antal_games,
  (SELECT count(DISTINCT game_id) FROM main.game_players) AS antal_games_i_game_players,
  CASE 
    WHEN (SELECT count(DISTINCT game_id) FROM main.game_players) >= (SELECT count(*) FROM main.games) * 0.99 
    THEN 'OK' 
    ELSE 'Kolla: matcher saknar game_players' 
  END AS status;


-- 6. Spelare med flest matcher (topp 10)
SELECT p.firstName || ' ' || p.lastName AS namn, count(*) AS antal_matcher
FROM main.game_players gp
JOIN main.players p ON p.id = gp.player_id
GROUP BY p.id, p.firstName, p.lastName
ORDER BY antal_matcher DESC
LIMIT 10;


-- 7. Lag med flest matcher
SELECT team_abbr, count(*) AS antal_matcher
FROM main.team_game_stats
GROUP BY team_abbr
ORDER BY antal_matcher DESC
LIMIT 10;


-- 8. Säsonger i datan
SELECT DISTINCT season FROM main.games ORDER BY season;


-- 9. Kolla null i viktiga kolumner (games)
SELECT 
  count(*) AS total,
  count(game_id) AS har_game_id,
  count(game_date) AS har_game_date
FROM main.games;


-- 10. Exempel: spelare med bäst poäng/match (min 10 matcher)
SELECT 
  player_first_name || ' ' || player_last_name AS namn,
  count(*) AS matcher,
  sum(points) AS total_poang,
  round(sum(points)::FLOAT / count(*), 2) AS poang_per_match
FROM main.player_game_stats
GROUP BY player_id, player_first_name, player_last_name
HAVING count(*) >= 10
ORDER BY poang_per_match DESC
LIMIT 10;
