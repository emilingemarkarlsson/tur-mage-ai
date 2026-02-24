import json
import os
import re
import sys
from datetime import datetime

from mage_ai.settings.repo import get_repo_path

repo_path = get_repo_path()
if repo_path not in sys.path:
    sys.path.append(repo_path)

from utils.s3_utils import (
    get_s3_bucket,
    get_s3_client,
    list_keys,
    list_unique_dates_from_keys,
    read_json,
)

if "data_loader" not in globals():
    from mage_ai.data_preparation.decorators import data_loader


# State ligger bredvid data_lake (samma som export_games_parquet) så att container och host hittar samma filer.
def _state_dir():
    return os.path.join(os.path.dirname(os.getenv("DATA_LAKE_PATH", "/home/src/mage_project/data_lake")), "state")


def _candidate_state_dirs():
    """Flera kandidater så att games_year.txt hittas oavsett om repo är monterat som /home/src eller /home/src/mage_project."""
    data_lake = os.getenv("DATA_LAKE_PATH", "/home/src/mage_project/data_lake")
    repo = get_repo_path()
    candidates = [
        os.path.join(os.path.dirname(data_lake), "state"),
        os.path.join(repo, "state"),
    ]
    # Om repo är workspace-rot (t.ex. /home/src) finns state under mage_project/state.
    if not repo.rstrip("/").endswith("mage_project"):
        candidates.append(os.path.join(repo, "mage_project", "state"))
    return candidates

# Samma källa som i HETZNER_S3_DATA_STRUCTURE_FOR_MAGE.md: endast by_date (inga dubbletter).
PREFIX = "nhl-data-reorganized/games/by_date/"

def _get_runtime_var(kwargs: dict, key: str):
    """Försök hitta runtime-variabeln i flera vanliga Mage-containers."""
    if not isinstance(kwargs, dict):
        return None, None
    def _to_dict(value):
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            s = value.strip()
            # Mage kan ibland serialisera config/context som JSON-sträng
            if (s.startswith("{") and s.endswith("}")) or (s.startswith("[") and s.endswith("]")):
                try:
                    parsed = json.loads(s)
                    return parsed if isinstance(parsed, dict) else None
                except Exception:
                    return None
        return None
    # 1) direkt på kwargs
    if key in kwargs and kwargs.get(key) is not None:
        return kwargs.get(key), f"kwargs.{key}"
    # 2) nested: variables / configuration / context / env / event (och deras .variables)
    for container_key in ("variables", "configuration", "context", "env", "event"):
        container = kwargs.get(container_key)
        container_dict = _to_dict(container)
        # dict container
        if isinstance(container_dict, dict):
            if key in container_dict and container_dict.get(key) is not None:
                return container_dict.get(key), f"{container_key}.{key}"
            nested_vars = container_dict.get("variables") or container_dict.get("runtime_variables")
            if isinstance(nested_vars, dict) and key in nested_vars and nested_vars.get(key) is not None:
                return nested_vars.get(key), f"{container_key}.variables.{key}"
        # object container (pydantic/dataclass etc.)
        else:
            try:
                if hasattr(container, key):
                    value = getattr(container, key)
                    if value is not None:
                        return value, f"{container_key}.{key}"
                for attr_name in ("variables", "runtime_variables"):
                    if hasattr(container, attr_name):
                        nested_vars = getattr(container, attr_name)
                        if isinstance(nested_vars, dict) and key in nested_vars and nested_vars.get(key) is not None:
                            return nested_vars.get(key), f"{container_key}.{attr_name}.{key}"
            except Exception:
                pass
    return None, None


def _read_last_date(state_dir=None):
    path = os.path.join(state_dir or _state_dir(), "last_games_date.txt")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as handle:
            value = handle.read().strip()
            return value or None
    return None


def _write_last_date(value: str, state_dir=None):
    d = state_dir or _state_dir()
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "last_games_date.txt"), "w", encoding="utf-8") as handle:
        handle.write(value)


@data_loader
def load_games_incremental(*args, **kwargs):
    client = get_s3_client()
    bucket = get_s3_bucket()
    if not bucket:
        raise ValueError("S3 bucket is not configured (HETZNER_BUCKET or S3_BUCKET).")

    keys = list(list_keys(client, bucket, PREFIX))
    available_dates = list_unique_dates_from_keys(keys, PREFIX)

    state_dir = _state_dir()
    last_date = _read_last_date(state_dir)
    start_date = (os.getenv("GAMES_START_DATE") or "").strip()  # t.ex. 2010-01-01 för full historik (första datum i S3 är 2010-10-01)
    # År kan sättas i Mage UI (Variables → games_year), .env (GAMES_YEAR) eller state/games_year.txt.
    def _valid_year(v):
        s = (v is not None and str(v).strip()) or ""
        return s if re.match(r"^(19|20)\d{2}$", s) else None

    _year, _year_src = _get_runtime_var(kwargs, "games_year")
    _year = _valid_year(_year)
    if _year is None:
        _year, _year_src = _get_runtime_var(kwargs, "GAMES_YEAR")
        _year = _valid_year(_year)
    if _year is None:
        _year = _valid_year(os.getenv("GAMES_YEAR"))
        _year_src = "env.GAMES_YEAR" if _year else None
    # Fallback: årtal ur trigger_name (t.ex. "games_2026").
    if _year is None:
        trigger_name = kwargs.get("trigger_name")
        if isinstance(trigger_name, str) and trigger_name.strip():
            m = re.search(r"(19|20)\d{2}", trigger_name)
            if m:
                _year = m.group(0)
                _year_src = "kwargs.trigger_name"
    # state/games_year.txt vinner om filen finns och innehåller ett giltigt årtal (så du kan köra 2025 genom att skriva 2025 i filen).
    for cand_dir in _candidate_state_dirs():
        games_year_path = os.path.join(cand_dir, "games_year.txt")
        if os.path.isfile(games_year_path):
            try:
                with open(games_year_path, "r", encoding="utf-8-sig") as f:
                    raw = (f.read() or "").strip().lstrip("\ufeff").strip()
                m = re.search(r"(19|20)\d{2}", raw)
                if m:
                    _year = m.group(0)
                    _year_src = "state/games_year.txt"
                    print(f"[games loader] games_year={_year} från fil: {games_year_path}")
                    break
            except Exception as e:
                print(f"[games loader] Kunde inte läsa {games_year_path}: {e}")
    games_year = (str(_year).strip() if _year is not None and str(_year).strip() else "")

    trigger_name = kwargs.get("trigger_name")
    is_schedule_run = bool(trigger_name)
    # Skydda mot att en schedule-run råkar försöka ladda hela historiken utan year/state (risk för 95% memory-limit).
    if is_schedule_run and not games_year and not last_date:
        raise ValueError(
            "Schedule-run saknar games_year (och ingen state finns ännu). "
            "Detta skulle försöka ladda hela historiken (2010–2026) och riskerar memory-limit. "
            "Åtgärd: sätt runtime variable games_year på själva schedule:n, eller kör manuellt via 'Run pipeline', "
            "eller sätt GAMES_BATCH_SIZE (manuell batch utan år) och kör flera gånger."
        )
    if start_date:
        available_dates = [d for d in available_dates if d >= start_date]
    # Filtrera på år. För att ladda om hela året (t.ex. uppdaterad data i S3): skapa state/games_force_refresh.txt med årtal.
    if games_year:
        available_dates = [d for d in available_dates if len(d) >= 4 and d[:4] == games_year]
        force_refresh = False
        for cand_dir in _candidate_state_dirs():
            path = os.path.join(cand_dir, "games_force_refresh.txt")
            if os.path.isfile(path):
                try:
                    with open(path, "r", encoding="utf-8-sig") as f:
                        raw = (f.read() or "").strip()
                    m = re.search(r"(19|20)\d{2}", raw)
                    if m and m.group(0) == games_year:
                        force_refresh = True
                        print(f"[games loader] games_force_refresh.txt={games_year} – laddar hela året (uppdaterar från S3).")
                        break
                except Exception:
                    pass
        if force_refresh:
            pass  # behåll alla datum för året
        elif last_date and len(last_date) >= 4 and last_date[:4] == games_year:
            available_dates = [d for d in available_dates if d > last_date]
        elif last_date and len(last_date) >= 4 and last_date[:4] != games_year:
            print(f"[games loader] State är från {last_date[:4]} – laddar hela året {games_year} (ignorerar state).")
    else:
        if last_date:
            available_dates = [d for d in available_dates if d > last_date]

    if games_year:
        print(f"[games loader] games_year={games_year} (från {_year_src}) | {len(available_dates)} datum för året.")

    # Automatisk batch-körning för ett år: load → transform → export i loop tills året är klart (minnesbesparande).
    if games_year and available_dates:
        _batch_raw = kwargs.get("games_batch_size") or kwargs.get("GAMES_BATCH_SIZE") or os.getenv("GAMES_BATCH_SIZE")
        auto_batch_size = 30
        if _batch_raw is not None:
            try:
                auto_batch_size = max(1, int(_batch_raw))
            except (TypeError, ValueError):
                pass
        try:
            from transformers.transform_games import transform_games
            from data_exporters.export_games_parquet import export_games_parquet
        except ImportError:
            from mage_project.transformers.transform_games import transform_games
            from mage_project.data_exporters.export_games_parquet import export_games_parquet

        total_games = 0
        all_errors = []
        num_batches = (len(available_dates) + auto_batch_size - 1) // auto_batch_size
        print(f"[games loader] År {games_year}: kör automatiskt i {num_batches} batchar (max {auto_batch_size} datum per batch).")
        for start in range(0, len(available_dates), auto_batch_size):
            batch_dates = available_dates[start : start + auto_batch_size]
            batch_num = start // auto_batch_size + 1
            games_batch = []
            errors_batch = []
            for game_date in batch_dates:
                date_prefix = f"{PREFIX}{game_date}/"
                for key in keys:
                    if not key.startswith(date_prefix):
                        continue
                    if not key.endswith(".json") or key.endswith("games_summary.json"):
                        continue
                    try:
                        payload = read_json(client, bucket, key)
                    except json.JSONDecodeError as exc:
                        errors_batch.append({"key": key, "error": str(exc)})
                        continue
                    games_batch.append({"game_date": game_date, "key": key, "payload": payload})
            total_games += len(games_batch)
            all_errors.extend(errors_batch)
            if errors_batch:
                for item in errors_batch:
                    print(f"  [batch {batch_num}] Invalid JSON: {item['key']}: {item['error']}")
            newest_in_batch = max(batch_dates)
            payload_batch = {
                "games": games_batch,
                "last_date": newest_in_batch,
                "last_date_previous": last_date,
                "count": len(games_batch),
                "errors": errors_batch,
            }
            transformed = transform_games(payload_batch, *args, **kwargs)
            export_games_parquet(transformed, *args, **kwargs)
            last_date = newest_in_batch
            print(f"[games loader] Batch {batch_num}/{num_batches} klar: {batch_dates[0]}–{newest_in_batch} ({len(games_batch)} matcher).")
        newest_date = max(available_dates)
        for cand_dir in _candidate_state_dirs():
            path = os.path.join(cand_dir, "games_force_refresh.txt")
            if os.path.isfile(path):
                try:
                    os.remove(path)
                    print(f"[games loader] Tog bort {path} (nästa körning blir inkrementell).")
                except Exception:
                    pass
                break
        if all_errors:
            error_log_path = os.path.join(state_dir, "games_load_errors.log")
            try:
                with open(error_log_path, "w", encoding="utf-8") as f:
                    f.write(f"# Games loader: ogiltig JSON (senast {newest_date}, år {games_year})\n")
                    for item in all_errors:
                        f.write(f"{item['key']}\t{item['error']}\n")
                print(f"[games loader] {len(all_errors)} fel sparade i {error_log_path}")
            except Exception as e:
                print(f"[games loader] Kunde inte skriva fellogg: {e}")
        print(f"[games loader] År {games_year} klart: {total_games} matcher i {num_batches} batchar. Nästa körning: sätt games_year till nästa år.")
        return {
            "games": [],
            "game_players": [],
            "last_date": newest_date,
            "last_date_previous": _read_last_date(),
            "count": total_games,
            "errors": all_errors,
            "batched": True,
            "games_year": games_year,
            "total_batches": num_batches,
        }

    # Minnesbesparande utan år: bara ett antal datum per körning (manuell batch). Kör pipelinen flera gånger tills inga datum kvar.
    _batch_raw = kwargs.get("games_batch_size") or kwargs.get("GAMES_BATCH_SIZE") or os.getenv("GAMES_BATCH_SIZE")
    batch_size = None
    if _batch_raw is not None:
        try:
            batch_size = int(_batch_raw)
        except (TypeError, ValueError):
            batch_size = None
    if batch_size and batch_size > 0:
        available_dates = available_dates[:batch_size]

    # Tydlig logg i Mage UI så man ser varför 2010–2026 inte laddas (state eller GAMES_START_DATE)
    print(f"[games loader] GAMES_START_DATE={start_date or '(alla)'} | last_games_date (state)={last_date or '(ingen)'}" + (f" | GAMES_YEAR={games_year}" if games_year else ""))
    if batch_size:
        print(f"[games loader] Batch-läge: max {batch_size} datum per körning (minnesbesparande).")
    if available_dates:
        print(f"[games loader] Laddar {len(available_dates)} datum: från {available_dates[0]} till {available_dates[-1]}" + (f" (endast år {games_year})" if games_year else ""))
    if last_date and available_dates:
        print(f"[games loader] INCREMENTELL: endast datum > {last_date}. För full laddning 2010–2026: ta bort state (reset_full_games_load.sh) och kör igen.")

    if not available_dates:
        if games_year:
            print(f"[games loader] Inga datum kvar för år {games_year}. Om state är från ett annat år ska du se 'laddar hela året' ovan; annars skapa mage_project/state/games_year.txt med innehåll {games_year} och kör igen.")
        elif last_date:
            print(f"[games loader] Inga nya datum att hämta (senaste sparade: {last_date}). För 2025: skapa mage_project/state/games_year.txt med '2025'. För omstart från 2010: kör scripts/reset_full_games_load.sh.")
        return {"games": [], "game_players": [], "last_date": last_date}

    games = []
    errors = []
    for game_date in available_dates:
        date_prefix = f"{PREFIX}{game_date}/"
        for key in keys:
            if not key.startswith(date_prefix):
                continue
            if not key.endswith(".json") or key.endswith("games_summary.json"):
                continue
            try:
                payload = read_json(client, bucket, key)
            except json.JSONDecodeError as exc:
                errors.append({"key": key, "error": str(exc)})
                continue
            games.append({"game_date": game_date, "key": key, "payload": payload})

    newest_date = max(available_dates)
    if errors:
        print(f"Invalid JSON files skipped ({len(errors)}):")
        for item in errors:
            print(f"- {item['key']}: {item['error']}")
        error_log_path = os.path.join(state_dir, "games_load_errors.log")
        try:
            with open(error_log_path, "w", encoding="utf-8") as f:
                f.write(f"# Games loader: ogiltig JSON (senast {newest_date})\n")
                for item in errors:
                    f.write(f"{item['key']}\t{item['error']}\n")
            print(f"[games loader] {len(errors)} fel sparade i {error_log_path}")
        except Exception as e:
            print(f"[games loader] Kunde inte skriva fellogg: {e}")

    return {
        "games": games,
        "last_date": newest_date,
        "last_date_previous": last_date,
        "count": len(games),
        "errors": errors,
    }
