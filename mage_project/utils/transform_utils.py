from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional


def extract_list(payload: Any, preferred_keys: Iterable[str]) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in preferred_keys:
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []


def get_nested_list(payload: Any, key_path: List[str]) -> List:
    """Följ en nyckelväg (t.ex. ['rosters', 'teams', 'data', 'items']) och returnera listan."""
    if not key_path:
        return [] if not isinstance(payload, list) else payload
    current = payload
    for key in key_path:
        current = (current or {}).get(key) if isinstance(current, dict) else None
        if current is None:
            return []
    return current if isinstance(current, list) else []


def to_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_time_to_seconds(value: Any) -> Optional[int]:
    if not value or not isinstance(value, str):
        return None
    try:
        minutes, seconds = value.split(":")
        return int(minutes) * 60 + int(seconds)
    except ValueError:
        return None


def parse_date(value: Any) -> Optional[str]:
    if not value:
        return None
    if isinstance(value, str):
        if len(value) >= 10:
            return value[:10]
    if isinstance(value, datetime):
        return value.date().isoformat()
    return None


def flatten_player(player: Dict[str, Any]) -> Dict[str, Any]:
    """
    Plattar ett spelarobjekt från NHL API till skalära kolumner.
    Nästlade fält (firstName: {default: 'X', sv: ...}) blir t.ex. firstName: 'X'.
    """
    if not isinstance(player, dict):
        return {}
    out: Dict[str, Any] = {}
    int_keys = {"heightInCentimeters", "heightInInches", "weightInKilograms", "weightInPounds", "id"}
    for key, value in player.items():
        if value is None:
            out[key] = None
            continue
        if isinstance(value, dict) and "default" in value:
            out[key] = value.get("default")
        elif key in int_keys:
            out[key] = to_int(value)
        else:
            out[key] = value
    return out


def flatten_dict_for_row(obj: Dict[str, Any]) -> Dict[str, Any]:
    """
    Plattar ett dict till skalära kolumner för Parquet.
    Nästlade fält (name: {default: 'X'}) blir name: 'X'.
    Listor och dict utan 'default' serialiseras inte här – användaren kan konvertera till str senare.
    """
    if not isinstance(obj, dict):
        return {}
    out: Dict[str, Any] = {}
    for key, value in obj.items():
        if value is None:
            out[key] = None
            continue
        if isinstance(value, dict) and "default" in value:
            out[key] = value.get("default")
        elif isinstance(value, dict) and len(value) == 1 and "default" in value:
            out[key] = value.get("default")
        elif isinstance(value, (list, dict)) and key not in out:
            # Behåll som är för senare JSON-serialisering i export
            out[key] = value
        else:
            out[key] = value
    return out
