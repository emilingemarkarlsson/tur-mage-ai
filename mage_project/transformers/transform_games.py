from typing import Any, Dict, List
import sys

import pandas as pd
from mage_ai.settings.repo import get_repo_path

repo_path = get_repo_path()
if repo_path not in sys.path:
    sys.path.append(repo_path)

from utils.transform_utils import parse_date, parse_time_to_seconds, to_float, to_int


def _goalie_gaa(goals_against: int | None, toi_seconds: int | float | None) -> float | None:
    """GAA = goals against per 60 minutes. Return None if not computable."""
    if goals_against is None or toi_seconds is None or toi_seconds <= 0:
        return None
    return round(to_float(goals_against * 3600 / toi_seconds), 4)

if "transformer" not in globals():
    from mage_ai.data_preparation.decorators import transformer


def _aggregate_team_stats_from_player_by_game_stats(pgs: Dict[str, Any], side_key: str) -> Dict[str, Any]:
    """Summerar lagstatistik från boxscore.playerByGameStats (forwards + defense + goalies)."""
    out = {"sog": 0, "hits": 0, "blockedShots": 0, "pim": 0, "powerPlayGoals": 0, "giveaways": 0, "takeaways": 0}
    team_data = (pgs or {}).get(side_key, {})
    for group in ("forwards", "defense", "goalies"):
        for p in (team_data.get(group) or []):
            if not isinstance(p, dict):
                continue
            out["sog"] += to_int(p.get("sog")) or 0
            out["hits"] += to_int(p.get("hits")) or 0
            out["blockedShots"] += to_int(p.get("blockedShots")) or 0
            out["pim"] += to_int(p.get("pim")) or 0
            out["powerPlayGoals"] += to_int(p.get("powerPlayGoals")) or 0
            out["giveaways"] += to_int(p.get("giveaways")) or 0
            out["takeaways"] += to_int(p.get("takeaways")) or 0
    return out


def _extract_game_row(payload: Dict[str, Any], game_date: str) -> Dict[str, Any]:
    boxscore = payload.get("boxscore", {}) or {}
    game_data = boxscore.get("gameData") or payload.get("gameData") or {}
    live_data = payload.get("liveData", {}) or {}
    linescore = live_data.get("linescore", {}) or {}

    game_id = payload.get("gameId") or boxscore.get("id") or game_data.get("game", {}).get("pk")
    status = (game_data.get("status") or {}).get("detailedState") or boxscore.get("gameState")

    if boxscore.get("homeTeam"):
        home = boxscore.get("homeTeam", {})
        away = boxscore.get("awayTeam", {})
        home_abbr = home.get("abbrev")
        away_abbr = away.get("abbrev")
        home_score = home.get("score")
        away_score = away.get("score")
        season = boxscore.get("season")
        home_team_id = to_int(home.get("id"))
        away_team_id = to_int(away.get("id"))
    else:
        teams = (game_data.get("teams") or {})
        home = teams.get("home", {})
        away = teams.get("away", {})
        home_abbr = home.get("abbreviation") or home.get("triCode")
        away_abbr = away.get("abbreviation") or away.get("triCode")
        home_score = linescore.get("teams", {}).get("home", {}).get("goals")
        away_score = linescore.get("teams", {}).get("away", {}).get("goals")
        season = game_data.get("game", {}).get("season")
        home_team_id = to_int(home.get("id"))
        away_team_id = to_int(away.get("id"))

    h = to_int(home_score)
    a = to_int(away_score)
    # NHL: 2 pts vinst, 1 pt förlust efter OT/SO, 0 pt förlust i ordinarie tid
    ot_or_so = status and ("OT" in str(status) or "SO" in str(status) or "Shootout" in str(status))
    if h is not None and a is not None:
        if h > a:
            home_pts, away_pts = 2, (1 if ot_or_so else 0)
        elif a > h:
            home_pts, away_pts = (1 if ot_or_so else 0), 2
        else:
            home_pts, away_pts = None, None  # oavgjort / inte slut
    else:
        home_pts, away_pts = None, None

    # Lagstatistik: använd teamnivå sog om det finns (t.ex. by_player-filer), annars aggregera från playerByGameStats
    home_team_obj = boxscore.get("homeTeam") or {}
    away_team_obj = boxscore.get("awayTeam") or {}
    home_sog = to_int(home_team_obj.get("sog"))
    away_sog = to_int(away_team_obj.get("sog"))
    pgs = boxscore.get("playerByGameStats")
    if isinstance(pgs, dict):
        home_agg = _aggregate_team_stats_from_player_by_game_stats(pgs, "homeTeam")
        away_agg = _aggregate_team_stats_from_player_by_game_stats(pgs, "awayTeam")
        if home_sog is None:
            home_sog = home_agg["sog"] or None
        if away_sog is None:
            away_sog = away_agg["sog"] or None
        home_pp_goals = home_agg["powerPlayGoals"] or None
        away_pp_goals = away_agg["powerPlayGoals"] or None
        home_pp_opps = None
        away_pp_opps = None
        home_hits = home_agg["hits"] or None
        away_hits = away_agg["hits"] or None
        home_blocked = home_agg["blockedShots"] or None
        away_blocked = away_agg["blockedShots"] or None
        home_pim = home_agg["pim"] or None
        away_pim = away_agg["pim"] or None
        home_faceoff_pct = None
        away_faceoff_pct = None
        home_giveaways = home_agg["giveaways"] or None
        away_giveaways = away_agg["giveaways"] or None
        home_takeaways = home_agg["takeaways"] or None
        away_takeaways = away_agg["takeaways"] or None
    else:
        home_team_obj = boxscore.get("homeTeam") or {}
        away_team_obj = boxscore.get("awayTeam") or {}
        bs_teams = (live_data.get("boxscore") or {}).get("teams", {})
        home_ld = bs_teams.get("home", {})
        away_ld = bs_teams.get("away", {})

        def _team_stat(obj: dict, ld: dict, *keys) -> int | None:
            for k in keys:
                v = (obj or {}).get(k) or (ld.get("teamStats", {}).get("teamSkaterStats") or {}).get(k) or (ld.get("teamStats", {}).get("teamGoalieStats") or {}).get(k)
                if v is not None:
                    return to_int(v)
            return None

        home_sog = _team_stat(home_team_obj, home_ld, "sog", "shots", "shotsOnGoal")
        away_sog = _team_stat(away_team_obj, away_ld, "sog", "shots", "shotsOnGoal")
        home_pp_goals = _team_stat(home_team_obj, home_ld, "powerPlayGoals", "powerPlayGoalCount")
        away_pp_goals = _team_stat(away_team_obj, away_ld, "powerPlayGoals", "powerPlayGoalCount")
        home_pp_opps = _team_stat(home_team_obj, home_ld, "powerPlayOpportunities", "powerPlayOpportunities")
        away_pp_opps = _team_stat(away_team_obj, away_ld, "powerPlayOpportunities", "powerPlayOpportunities")
        home_hits = _team_stat(home_team_obj, home_ld, "hits")
        away_hits = _team_stat(away_team_obj, away_ld, "hits")
        home_blocked = _team_stat(home_team_obj, home_ld, "blocked", "blockedShots")
        away_blocked = _team_stat(away_team_obj, away_ld, "blocked", "blockedShots")
        home_pim = _team_stat(home_team_obj, home_ld, "pim", "penaltyMinutes")
        away_pim = _team_stat(away_team_obj, away_ld, "pim", "penaltyMinutes")
        home_faceoff_pct = home_ld.get("teamStats", {}).get("teamSkaterStats", {}).get("faceOffWinPercentage")
        away_faceoff_pct = away_ld.get("teamStats", {}).get("teamSkaterStats", {}).get("faceOffWinPercentage")
        home_faceoff_pct = to_float(home_faceoff_pct) if home_faceoff_pct is not None else None
        away_faceoff_pct = to_float(away_faceoff_pct) if away_faceoff_pct is not None else None
        home_giveaways = _team_stat(home_team_obj, home_ld, "giveaways")
        away_giveaways = _team_stat(away_team_obj, away_ld, "giveaways")
        home_takeaways = _team_stat(home_team_obj, home_ld, "takeaways")
        away_takeaways = _team_stat(away_team_obj, away_ld, "takeaways")

    # Venue för trendanalys per arena
    venue_obj = boxscore.get("venue") or {}
    venue_loc = boxscore.get("venueLocation") or {}
    venue = venue_obj.get("default") if isinstance(venue_obj, dict) else None
    venue_location = venue_loc.get("default") if isinstance(venue_loc, dict) else None
    if not venue and game_data:
        venue = (game_data.get("venue") or {}).get("name") if isinstance(game_data.get("venue"), dict) else None

    # Fler nycklar från inventering: startTimeUTC, regPeriods, gameType, limitedScoring, gameState, gameOutcome, periodDescriptor
    start_time_utc = boxscore.get("startTimeUTC")
    reg_periods = boxscore.get("regPeriods")
    game_type = boxscore.get("gameType") or (game_data.get("game") or {}).get("type")
    limited_scoring = boxscore.get("limitedScoring")
    game_state = boxscore.get("gameState")
    game_outcome = boxscore.get("gameOutcome") or {}
    ot_periods = to_int(game_outcome.get("otPeriods")) if isinstance(game_outcome, dict) else None
    last_period_type = game_outcome.get("lastPeriodType") if isinstance(game_outcome, dict) else None
    period_descriptor = boxscore.get("periodDescriptor") or {}
    period_number = to_int(period_descriptor.get("number")) if isinstance(period_descriptor, dict) else None
    period_type = period_descriptor.get("periodType") if isinstance(period_descriptor, dict) else None

    return {
        "game_id": to_int(game_id),
        "game_date": parse_date(game_date) or parse_date(payload.get("date")) or parse_date(boxscore.get("gameDate")),
        "season": season,
        "home_team_abbr": home_abbr,
        "away_team_abbr": away_abbr,
        "home_team_id": home_team_id,
        "away_team_id": away_team_id,
        "home_score": h,
        "away_score": a,
        "home_points": home_pts,
        "away_points": away_pts,
        "status": status,
        "home_sog": home_sog,
        "away_sog": away_sog,
        "home_pp_goals": home_pp_goals,
        "away_pp_goals": away_pp_goals,
        "home_pp_opportunities": home_pp_opps,
        "away_pp_opportunities": away_pp_opps,
        "home_hits": home_hits,
        "away_hits": away_hits,
        "home_blocked": home_blocked,
        "away_blocked": away_blocked,
        "home_pim": home_pim,
        "away_pim": away_pim,
        "home_faceoff_pct": home_faceoff_pct,
        "away_faceoff_pct": away_faceoff_pct,
        "home_giveaways": home_giveaways,
        "away_giveaways": away_giveaways,
        "home_takeaways": home_takeaways,
        "away_takeaways": away_takeaways,
        "venue": venue,
        "venue_location": venue_location,
        "start_time_utc": start_time_utc,
        "reg_periods": reg_periods,
        "game_type": game_type,
        "limited_scoring": limited_scoring,
        "game_state": game_state,
        "ot_periods": ot_periods,
        "last_period_type": last_period_type,
        "period_number": period_number,
        "period_type": period_type,
    }


def _extract_players(payload: Dict[str, Any], game_id: int, game_date: str) -> List[Dict[str, Any]]:
    players_rows: List[Dict[str, Any]] = []
    boxscore = payload.get("boxscore", {}) or {}
    pgs = boxscore.get("playerByGameStats")

    if isinstance(pgs, dict):
        for side, team in (("away", boxscore.get("awayTeam")), ("home", boxscore.get("homeTeam"))):
            team_abbr = (team or {}).get("abbrev")
            is_home = side == "home"
            team_stats = pgs.get(f"{side}Team", {})
            for group in ("forwards", "defense", "goalies"):
                for player in team_stats.get(group, []) or []:
                    is_goalie = group == "goalies" or player.get("position") == "G"
                    players_rows.append({
                        "game_id": game_id,
                        "game_date": parse_date(game_date) or parse_date(payload.get("date")),
                        "player_id": to_int(player.get("playerId")),
                        "team_abbr": team_abbr,
                        "is_home": is_home,
                        "position": player.get("position"),
                        "sweater_number": to_int(player.get("sweaterNumber")),
                        "goals": to_int(player.get("goals")),
                        "assists": to_int(player.get("assists")),
                        "points": to_int(player.get("points")),
                        "plus_minus": to_int(player.get("plusMinus")),
                        "shots": to_int(player.get("sog")),
                        "pim": to_int(player.get("pim")),
                        "toi_seconds": parse_time_to_seconds(player.get("toi")),
                        "hits": to_int(player.get("hits")),
                        "power_play_goals": to_int(player.get("powerPlayGoals")),
                        "short_handed_goals": to_int(player.get("shortHandedGoals")),
                        "blocked_shots": to_int(player.get("blockedShots")),
                        "shifts": to_int(player.get("shifts")),
                        "giveaways": to_int(player.get("giveaways")),
                        "takeaways": to_int(player.get("takeaways")),
                        "faceoff_win_pct": to_float(player.get("faceoffWinningPctg")),
                        "saves": to_int(player.get("saves")) if is_goalie else None,
                        "shots_against": to_int(player.get("shotsAgainst")) if is_goalie else None,
                        "save_pct": to_float(player.get("savePctg")) if is_goalie else None,
                        "goals_against": to_int(player.get("goalsAgainst")) if is_goalie else None,
                        "even_strength_goals_against": to_int(player.get("evenStrengthGoalsAgainst")) if is_goalie else None,
                        "power_play_goals_against": to_int(player.get("powerPlayGoalsAgainst")) if is_goalie else None,
                        "shorthanded_goals_against": to_int(player.get("shorthandedGoalsAgainst")) if is_goalie else None,
                        "even_strength_shots_against": to_int(player.get("evenStrengthShotsAgainst")) if is_goalie else None,
                        "power_play_shots_against": to_int(player.get("powerPlayShotsAgainst")) if is_goalie else None,
                        "shorthanded_shots_against": to_int(player.get("shorthandedShotsAgainst")) if is_goalie else None,
                        "gaa": _goalie_gaa(to_int(player.get("goalsAgainst")) if is_goalie else None, parse_time_to_seconds(player.get("toi"))) if is_goalie else None,
                    })
        return players_rows

    live_data = payload.get("liveData", {})
    teams = (live_data.get("boxscore") or {}).get("teams", {})

    for side in ("home", "away"):
        team = teams.get(side, {})
        team_abbr = (team.get("team") or {}).get("triCode")
        is_home = side == "home"
        players = team.get("players") or {}
        for player in players.values():
            person = player.get("person") or {}
            stats = player.get("stats") or {}
            skater = stats.get("skaterStats") or {}
            goalie = stats.get("goalieStats") or {}
            pos_abbr = (player.get("position") or {}).get("abbreviation")
            is_goalie = pos_abbr == "G"

            players_rows.append({
                "game_id": game_id,
                "game_date": parse_date(game_date),
                "player_id": to_int(person.get("id")),
                "team_abbr": team_abbr,
                "is_home": is_home,
                "position": pos_abbr,
                "sweater_number": to_int(player.get("jerseyNumber")),
                "goals": to_int(skater.get("goals")),
                "assists": to_int(skater.get("assists")),
                "points": to_int(skater.get("points")),
                "plus_minus": to_int(skater.get("plusMinus")),
                "shots": to_int(skater.get("shots")),
                "pim": to_int(skater.get("penaltyMinutes")),
                "toi_seconds": parse_time_to_seconds(skater.get("timeOnIce")),
                "hits": to_int(skater.get("hits")),
                "power_play_goals": to_int(skater.get("powerPlayGoals")),
                "short_handed_goals": to_int(skater.get("shortHandedGoals")),
                "blocked_shots": to_int(skater.get("blocked")),
                "shifts": to_int(skater.get("shift")),
                "giveaways": to_int(skater.get("giveaways")),
                "takeaways": to_int(skater.get("takeaways")),
                "faceoff_win_pct": to_float(skater.get("faceOffWinPercentage")),
                "saves": to_int(goalie.get("saves")) if is_goalie else None,
                "shots_against": to_int(goalie.get("shots")) if is_goalie else None,
                "save_pct": to_float(goalie.get("savePercentage")) if is_goalie else None,
                "goals_against": to_int(goalie.get("goalsAgainst")) if is_goalie else None,
                "even_strength_goals_against": to_int(goalie.get("evenStrengthGoalsAgainst")) if is_goalie else None,
                "power_play_goals_against": to_int(goalie.get("powerPlayGoalsAgainst")) if is_goalie else None,
                "shorthanded_goals_against": to_int(goalie.get("shortHandedGoalsAgainst")) if is_goalie else None,
                "even_strength_shots_against": to_int(goalie.get("evenStrengthShotsAgainst")) if is_goalie else None,
                "power_play_shots_against": to_int(goalie.get("powerPlayShotsAgainst")) if is_goalie else None,
                "shorthanded_shots_against": to_int(goalie.get("shorthandedShotsAgainst")) if is_goalie else None,
                "gaa": _goalie_gaa(to_int(goalie.get("goalsAgainst")) if is_goalie else None, parse_time_to_seconds(goalie.get("timeOnIce")) or parse_time_to_seconds(skater.get("timeOnIce"))) if is_goalie else None,
            })

    return players_rows


# #region agent log
def _debug_log(msg: str, data: dict, hypothesis_id: str = "B"):
    try:
        import os
        import json
        from mage_ai.settings.repo import get_repo_path
        rp = get_repo_path()
        p = os.getenv("DEBUG_LOG_PATH") or os.path.normpath(os.path.join(rp, "..", ".cursor", "debug.log"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps({"hypothesisId": hypothesis_id, "location": "transform_games", "message": msg, "data": data, "timestamp": __import__("time").time() * 1000}) + "\n")
    except Exception:
        pass
# #endregion

@transformer
def transform_games(payload: Dict[str, Any], *args, **kwargs):
    # Automatisk batch-körning: loadern har redan kört load→transform→export i loop; bara vidarebefordra.
    if isinstance(payload, dict) and payload.get("batched"):
        return payload
    games_raw = payload.get("games", [])
    _debug_log("Transform entry", {"games_raw_len": len(games_raw), "payload_keys": list(payload.keys()) if isinstance(payload, dict) else "not_dict"}, "B")

    game_rows: List[Dict[str, Any]] = []
    player_rows: List[Dict[str, Any]] = []

    for item in games_raw:
        game_date = item.get("game_date")
        data = item.get("payload") or {}
        game_row = _extract_game_row(data, game_date)
        game_rows.append(game_row)

        game_id = game_row.get("game_id")
        if game_id:
            player_rows.extend(_extract_players(data, game_id, game_date))

    games_df = pd.DataFrame(game_rows)
    players_df = pd.DataFrame(player_rows)

    # Ta bort dubletter (samma match eller samma spelare i samma match flera gånger)
    if not games_df.empty and "game_id" in games_df.columns:
        games_df = games_df.drop_duplicates(subset=["game_id"], keep="first")
    if not players_df.empty and "game_id" in players_df.columns and "player_id" in players_df.columns:
        players_df = players_df.drop_duplicates(subset=["game_id", "player_id"], keep="first")

    _debug_log("Transform exit", {"games_rows": len(games_df), "players_rows": len(players_df), "games_empty": games_df.empty, "players_empty": players_df.empty}, "B")
    return {
        "games": games_df,
        "game_players": players_df,
        "newest_date": payload.get("last_date"),  # för state-skrivning i export (efter lyckad skriv)
    }
