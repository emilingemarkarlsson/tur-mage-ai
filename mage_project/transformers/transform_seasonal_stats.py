from typing import Any, Dict, List
import sys

import pandas as pd
from mage_ai.settings.repo import get_repo_path

repo_path = get_repo_path()
if repo_path not in sys.path:
    sys.path.append(repo_path)

from utils.transform_utils import extract_list, get_nested_list

if "transformer" not in globals():
    from mage_ai.data_preparation.decorators import transformer

# Nycklar i leaders-objekt som vi inte plattar till kolumner (entity + nästlade strukturer)
_LEADERS_SKIP_KEYS = frozenset({"player", "team", "overlay", "shotLocationDetails"})


def _flatten_leader_value(obj: Dict[str, Any]) -> Dict[str, Any]:
    """Platta mätvärden från ett leader-objekt (t.ex. leaders.hardestShot) till skalära kolumner."""
    out: Dict[str, Any] = {}
    for k, v in obj.items():
        if k in _LEADERS_SKIP_KEYS or v is None:
            continue
        if isinstance(v, (int, float, str, bool)):
            out[f"value_{k}"] = v
        elif isinstance(v, dict):
            if "default" in v:
                out[f"value_{k}"] = v.get("default")
            elif "metric" in v and "imperial" in v:
                out[f"value_{k}_metric"] = v.get("metric")
                out[f"value_{k}_imperial"] = v.get("imperial")
            elif "metric" in v:
                out[f"value_{k}_metric"] = v.get("metric")
            elif "imperial" in v:
                out[f"value_{k}_imperial"] = v.get("imperial")
            else:
                for subk, subv in v.items():
                    if isinstance(subv, dict) and ("metric" in subv or "imperial" in subv):
                        out[f"value_{k}_{subk}_metric"] = subv.get("metric")
                        out[f"value_{k}_{subk}_imperial"] = subv.get("imperial")
                    elif isinstance(subv, (int, float, str, bool)):
                        out[f"value_{k}_{subk}"] = subv
    return out


def _flatten_edge_leaders(
    items: List[Dict[str, Any]],
    entity: str,
) -> pd.DataFrame:
    """
    Plattar edge landing_*.json där root är { leaders: { category: { player|team, ... } } }.
    entity: "player" (edge_skaters, edge_goalies) eller "team" (edge_teams).
    Returnerar en rad per kategori per säsong med entity_id och plattade mätvärden.
    """
    rows: List[Dict[str, Any]] = []
    for item in items:
        season = item.get("season")
        payload = item.get("payload") or {}
        leaders = payload.get("leaders") if isinstance(payload, dict) else {}
        if not isinstance(leaders, dict):
            continue
        for category, obj in leaders.items():
            if not isinstance(obj, dict):
                continue
            if entity == "player":
                player = obj.get("player") or {}
                entity_id = player.get("id") if isinstance(player, dict) else None
                team_obj = (player.get("team") or {}) if isinstance(player, dict) else {}
                team_abbr = team_obj.get("abbrev") if isinstance(team_obj, dict) else None
                row: Dict[str, Any] = {
                    "season": season,
                    "category": category,
                    "player_id": entity_id,
                    "team_abbr": team_abbr,
                }
            else:
                team = obj.get("team") or {}
                entity_id = team.get("id") if isinstance(team, dict) else None
                team_abbr = team.get("abbrev") if isinstance(team, dict) else None
                row = {
                    "season": season,
                    "category": category,
                    "team_id": entity_id,
                    "team_abbr": team_abbr,
                }
            row.update(_flatten_leader_value(obj))
            rows.append(row)
    return pd.DataFrame(rows)


def _extract_list_any(payload: Any, key_paths: List[List[str]]) -> List:
    """Provar flera nyckelvägar tills en returnerar en icke-tom lista (för edge landing_*.json)."""
    if payload is None:
        return []
    if isinstance(payload, list) and payload:
        return payload
    for path in key_paths:
        if not path:
            continue
        data = get_nested_list(payload, path)
        if isinstance(data, list) and data:
            return data
    for path in key_paths:
        data = extract_list(payload, path)
        if data:
            return data
    return []


def _flatten(items: List[Dict[str, Any]], preferred_key_paths: List[Any]) -> pd.DataFrame:
    """Extraherar lista från payload via första träffande nyckelväg; flattar till rader med season.
    preferred_key_paths: lista av antingen ['key1','key2'] eller 'key' för extract_list.
    """
    rows: List[Dict[str, Any]] = []
    for item in items:
        season = item.get("season")
        payload = item.get("payload") or {}
        data = []
        for path in preferred_key_paths:
            if isinstance(path, list):
                data = get_nested_list(payload, path)
            else:
                data = extract_list(payload, [path] if isinstance(path, str) else path)
            if isinstance(data, list) and data:
                break
        if not data and isinstance(payload, list):
            data = payload
        for row in data:
            row = dict(row) if isinstance(row, dict) else {}
            row["season"] = season
            rows.append(row)
    return pd.DataFrame(rows)


def _flatten_standings(items: List[Dict[str, Any]]) -> pd.DataFrame:
    """Standings kan vara records[].teamRecords (NHL API) eller en platt lista."""
    rows: List[Dict[str, Any]] = []
    for item in items:
        season = item.get("season")
        payload = item.get("payload") or {}
        # Platt lista: standings (t.ex. league_standings_*.json), records (NHL API), data.items
        data = extract_list(payload, ["standings", "records", "data", "items", "teamRecords"])
        if not data:
            data = get_nested_list(payload, ["standings", "records"])
        if data and isinstance(data[0], dict) and "teamRecords" in data[0]:
            # NHL API: records[] med teamRecords[] inuti
            for rec in data:
                parent = {k: v for k, v in rec.items() if k != "teamRecords"}
                for tr in rec.get("teamRecords") or []:
                    row = dict(tr)
                    row["season"] = season
                    for k, v in parent.items():
                        if k not in row and not isinstance(v, (dict, list)):
                            row[f"division_{k}" if k in ("division", "conference") else k] = v
                    rows.append(row)
        else:
            for row in data:
                row = dict(row) if isinstance(row, dict) else {}
                row["season"] = season
                rows.append(row)
    return pd.DataFrame(rows)


def _flatten_edge(items: List[Dict[str, Any]], key_paths: List[List[str]]) -> pd.DataFrame:
    """Som _flatten men provar flera nyckelvägar (för edge landing_*.json)."""
    rows: List[Dict[str, Any]] = []
    for item in items:
        season = item.get("season")
        payload = item.get("payload")
        data = _extract_list_any(payload, key_paths)
        for row in data:
            row = dict(row) if isinstance(row, dict) else {}
            row["season"] = season
            rows.append(row)
    return pd.DataFrame(rows)


@transformer
def transform_seasonal_stats(payload: Dict[str, Any], *args, **kwargs):
    standings_df = _flatten_standings(payload.get("standings", []))
    if standings_df.empty:
        standings_df = _flatten(payload.get("standings", []), [["records"], ["standings"], ["data", "items"], ["teamRecords"]])
    skaters_df = _flatten(payload.get("skaters", []), [["data", "skaters", "items"], ["skaters"], ["data", "items"]])
    goalies_df = _flatten(payload.get("goalies", []), [["data", "goalies", "items"], ["goalies"], ["data", "items"]])
    teams_df = _flatten(payload.get("teams", []), [["data", "teams", "items"], ["teams"], ["data", "items"]])
    # Edge landing_*.json: källorna har root "leaders" (inte data.items) – platta leaders till en rad per kategori
    edge_skaters_df = _flatten_edge(
        payload.get("edge_skaters", []),
        [["data", "skaters", "items"], ["data", "items"], ["skaters", "data", "items"]],
    )
    if edge_skaters_df.empty:
        edge_skaters_df = _flatten_edge_leaders(payload.get("edge_skaters", []), entity="player")

    edge_goalies_df = _flatten_edge(
        payload.get("edge_goalies", []),
        [["data", "goalies", "items"], ["data", "items"], ["goalies", "data", "items"]],
    )
    if edge_goalies_df.empty:
        edge_goalies_df = _flatten_edge_leaders(payload.get("edge_goalies", []), entity="player")

    edge_teams_df = _flatten_edge(
        payload.get("edge_teams", []),
        [["data", "teams", "items"], ["data", "items"], ["teams", "data", "items"]],
    )
    if edge_teams_df.empty:
        edge_teams_df = _flatten_edge_leaders(payload.get("edge_teams", []), entity="team")

    return {
        "standings": standings_df,
        "skater_stats": skaters_df,
        "goalie_stats": goalies_df,
        "team_stats": teams_df,
        "edge_skaters": edge_skaters_df,
        "edge_goalies": edge_goalies_df,
        "edge_teams": edge_teams_df,
    }
