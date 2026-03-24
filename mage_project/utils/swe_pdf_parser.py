"""
Parsers för Swehockey PDF-rapporter.

Hanterar:
  Official_Game_Report  → referees, period_stats, goals, penalties, gk_changes, on_ice
  Official_Team_Roster  → roster (birthdate, captain flags, coaches)
  Official_Line_Up      → referees (backup), starting lineup
  Player_Summary        → player_stats, goalie_stats (compact format)
  Media_Game_Summary    → player_stats, goalie_stats (verbose format)
"""

from __future__ import annotations

import io
import re
from typing import Any, Dict, List, Optional, Tuple

try:
    import pdfplumber
    _PDFPLUMBER_AVAILABLE = True
except ImportError:
    _PDFPLUMBER_AVAILABLE = False


# ---------------------------------------------------------------------------
# Hjälp-funktioner
# ---------------------------------------------------------------------------

def _require_pdfplumber():
    if not _PDFPLUMBER_AVAILABLE:
        raise ImportError("pdfplumber saknas. Installera: pip install pdfplumber")


def _open_pdf(pdf_bytes: bytes):
    _require_pdfplumber()
    return pdfplumber.open(io.BytesIO(pdf_bytes))


def _pdf_text(pdf_bytes: bytes) -> str:
    """Extrahera all text från PDF (sida för sida, newline-separerade)."""
    with _open_pdf(pdf_bytes) as pdf:
        return "\n".join(p.extract_text() or "" for p in pdf.pages)


def _to_float(s: str | None) -> Optional[float]:
    if not s or s.strip() in ("N/A", "-", ""):
        return None
    try:
        return float(str(s).replace(",", "."))
    except (ValueError, TypeError):
        return None


def _to_int(s: str | None) -> Optional[int]:
    if not s or str(s).strip() in ("N/A", "-", ""):
        return None
    try:
        return int(str(s).strip())
    except (ValueError, TypeError):
        return None


def _mmss_to_seconds(s: str | None) -> Optional[int]:
    """'01:40' → 100 sekunder."""
    if not s:
        return None
    s = s.strip()
    m = re.match(r"^(\d+):(\d{2})$", s)
    if m:
        return int(m.group(1)) * 60 + int(m.group(2))
    return None


def _compute_gaa(ga: Optional[int], toi_str: Optional[str]) -> Optional[float]:
    """Beräkna GAA (goals against average per 60 min) från GA och TOI (MM:SS)."""
    if ga is None or not toi_str:
        return None
    m = re.match(r"^(\d+):(\d{2})$", str(toi_str).strip())
    if not m:
        return None
    toi_minutes = int(m.group(1)) + int(m.group(2)) / 60
    if toi_minutes == 0:
        return None
    return round(ga / (toi_minutes / 60), 2)


def _extract_goal_players(
    rest: str,
) -> Tuple[str, str, Optional[str], Optional[str], Optional[str], Optional[str]]:
    """
    Extrahera målskytt och upp till 2 assistenter från rest-strängen efter goal_type.
    Format: "59 HEDLUND, Pelle [29 JOHANSSON, Mattias [7 BERGLUND, Gustav]]"
    Returnerar: (scorer_num, scorer_name, assist1_num, assist1_name, assist2_num, assist2_name)
    """
    # Dela vid varje nytt spelar-segment: <whitespace><1-3 siffror><mellanslag><stor bokstav>
    segments = re.split(r"\s+(?=\d{1,3}\s+[A-ZÄÅÖ])", rest.strip())
    players: List[Tuple[str, str]] = []
    for seg in segments:
        parts = seg.strip().split(None, 1)
        if parts and parts[0].isdigit():
            players.append((parts[0], parts[1].strip() if len(parts) > 1 else ""))

    scorer_num = players[0][0] if len(players) > 0 else ""
    scorer_name = players[0][1] if len(players) > 0 else ""
    assist1_num = players[1][0] if len(players) > 1 else None
    assist1_name = players[1][1] if len(players) > 1 else None
    assist2_num = players[2][0] if len(players) > 2 else None
    assist2_name = players[2][1] if len(players) > 2 else None
    return scorer_num, scorer_name, assist1_num, assist1_name, assist2_num, assist2_name


def _split_penalty_description(desc: str) -> Tuple[str, str]:
    """
    Dela upp straffbeskrivning i spelarnamn och straffrubrik.
    T.ex. "HEDLUND, Pelle Roughing" → ("HEDLUND, Pelle", "Roughing")
    """
    m = re.match(
        r"^([A-ZÄÅÖ][A-ZÄÅÖÜ\-]+,\s+[A-Za-zäåöü][a-zäåöü\-]+)\s+(.+)$",
        desc.strip(),
    )
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return desc.strip(), ""


# ---------------------------------------------------------------------------
# Official_Game_Report
# ---------------------------------------------------------------------------

_PERIOD_LABELS = {
    "1st": 1, "2nd": 2, "3rd": 3, "4th": 4,
    "ot": "OT", "overtime": "OT",
    "so": "SO", "shootout": "SO",
}

_STATS_HDR = re.compile(
    r"^Team\s+Goals\s+Shots\s+Saves\s+SVS%\s+PIM", re.MULTILINE
)
_PERIOD_HDR = re.compile(
    r"^(1st|2nd|3rd|4th|OT|Overtime|SO|Shootout)\s+period", re.MULTILINE | re.IGNORECASE
)
_SPECTATORS_PAT = re.compile(r"Spectators:\s*(\d[\d\s]*)")
_NAME_PAT = re.compile(r"^[A-ZÄÅÖ\s]+,\s+\w")   # "LASTNAME, Firstname"
_PERIOD_STAT_ROW = re.compile(
    r"^(.+?)\s+"              # team name (greedy minimal)
    r"(\d+)\s+"               # Goals
    r"(\d+)\s+"               # Shots
    r"(\d+)\s+"               # Saves
    r"([\d,]+|N/A)\s+"        # SVS%
    r"(\d+)\s+"               # PIM
    r"(\d{1,2}:\d{2})\s+"     # TPP
    r"(\d+)\s+"               # ADV
    r"([\d,]+|N/A)\s+"        # PP%
    r"(\d{1,2}:\d{2})\s+"     # TSH
    r"(\d+)\s+"               # DVG
    r"([\d,]+|N/A)"           # SH%
)
_GOAL_LINE = re.compile(
    r"^Goal\s+"
    r"(\d{2}:\d{2})\s+"                          # time
    r"(\S+)\s+"                                    # team abbr
    r"(\d+\s*[-–]\s*\d+)\s+"                      # score "0 - 1"
    r"(EQ|PP\d?|SH|EN|OT|PS|GWS|N/A)\s+"         # goal type
    r"(.*)"                                        # rest: "number name [Participation]"
)
_PENALTY_LINE = re.compile(
    r"^Penalty\s+(\d{2}:\d{2})\s+(\S+)\s+(\d+)\s+min\.\s+(\d+)\s+(.+)$"
)
_GK_LINE = re.compile(
    r"^Goalkeeper\s+(In|Out)\s+(\d{2}:\d{2})\s+(\S+)\s+(\d+)\s+(.+)$"
)
_ON_ICE_LINE = re.compile(r"^(\w+):\s+([\d\s]+)$")
_SCORE_PAT = re.compile(r"(\d+)\s*[-–]\s*(\d+)")


def _parse_referees_from_game_report(lines: List[str]) -> List[Dict]:
    """
    Hitta dömarblock i Official_Game_Report / Official_Line_Up.
    Headerblocket (kan upprepas per sida) ser ut så här:
      Referee(s)
      Home Team - Away Team LASTNAME, Firstname   ← första domaren
      LASTNAME, Firstname                          ← andra domaren
      YYYY-MM-DD HH:MM at Venue                   ← stopp för Referee-block
      HockeyXxx
      Linesman
      Group No. XXXX LASTNAME, Firstname
      Game No. YYYY  LASTNAME, Firstname  YYYY-MM-DD  ← stopp efter timestamp
    """
    referees: List[Dict] = []
    seen_names: set = set()

    # Vi behandlar bara FÖRSTA header-blocket (duplicerat per sida)
    # Hitta raden "Referee(s)" och hämta namn fram till datumraden
    mode = None
    header_done = False

    for line in lines:
        ls = line.strip()
        if not ls:
            continue

        # Hopp efter "Spectators:" – all header-info är behandlad
        if re.match(r"^Spectators:", ls):
            break

        # En ny sidas header – men vi bröt inte vid "Official Game Report"
        # (det är repetitioner); ignorera om vi redan hittat referees
        if ls in ("Official Game Report", "Official Line Up", "ReportName") and referees:
            header_done = True
            continue
        if header_done:
            continue

        # Referees-sektion
        if re.match(r"^Referee\(s\)\s*$", ls, re.IGNORECASE):
            mode = "ref"
            continue

        # Linesman-sektion
        if re.match(r"^Linesman\s*$", ls, re.IGNORECASE):
            mode = "linesman"
            continue

        if mode == "ref":
            # Stopp vid datumrad (YYYY-MM-DD) eller känd stopp-token
            if re.search(r"\d{4}-\d{2}-\d{2}", ls) or re.match(r"^(Final Score|Game Totals|1st|2nd|3rd)", ls):
                mode = None
                continue
            names = _extract_names_from_line(ls)
            for n in names:
                if n not in seen_names:
                    seen_names.add(n)
                    referees.append({"name": n, "role": "Referee"})

        elif mode == "linesman":
            # Linesman-namn finns på "Group No." och "Game No." rader
            if re.match(r"^(Group No\.|Game No\.)", ls):
                names = _extract_names_from_line(ls)
                for n in names:
                    if n not in seen_names:
                        seen_names.add(n)
                        referees.append({"name": n, "role": "Linesman"})
            elif re.search(r"\d{4}-\d{2}-\d{2}", ls):
                # Timestamp i slutet av Game No.-raden – ignorera
                pass
            elif re.match(r"^[A-Z]", ls) and not re.search(r"\d{4}-\d{2}-\d{2}", ls):
                # Kan vara extra linesman-namn utan Group/Game prefix
                names = _extract_names_from_line(ls)
                for n in names:
                    if n not in seen_names:
                        seen_names.add(n)
                        referees.append({"name": n, "role": "Linesman"})

    return referees


def _extract_names_from_line(line: str) -> List[str]:
    """Extrahera 'LASTNAME, Firstname'-mönster från en textrad."""
    # Pattern: UPPER_LAST, Firstname (possibly followed by more text)
    names = re.findall(r"([A-ZÄÅÖ][A-ZÄÅÖÜ\-]+,\s+[A-ZÄÅÖ][a-zäåöü]+)", line)
    return [n.strip() for n in names]


def _split_into_periods(text: str) -> Dict[Any, str]:
    """
    Dela upp texten i perioder. Returnerar {period_label: text_block}.
    Hanterar 1st/2nd/3rd/OT/SO.
    """
    # Find all period headers
    pat = re.compile(
        r"(?m)^(1st|2nd|3rd|4th|OT|Overtime|SO|Shootout)\s+period\b",
        re.IGNORECASE
    )
    matches = list(pat.finditer(text))
    if not matches:
        return {}

    periods = {}
    for i, m in enumerate(matches):
        label_str = m.group(1).lower()
        period_num = _PERIOD_LABELS.get(label_str, label_str)
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        periods[period_num] = text[start:end]

    return periods


def _parse_period_stats(period_text: str, period_label) -> List[Dict]:
    """Parsa periodstatistiktabell (Goals Shots Saves SVS% ...)."""
    rows = []
    lines = period_text.split("\n")
    in_stats = False
    for line in lines:
        ls = line.strip()
        if _STATS_HDR.match(ls):
            in_stats = True
            continue
        if in_stats and ls:
            m = _PERIOD_STAT_ROW.match(ls)
            if m:
                team, goals, shots, saves, svs_pct, pim, tpp, adv, pp_pct, tsh, dvg, sh_pct = m.groups()
                rows.append({
                    "period": period_label,
                    "team": team.strip(),
                    "goals": _to_int(goals),
                    "shots": _to_int(shots),
                    "saves": _to_int(saves),
                    "svs_pct": _to_float(svs_pct),
                    "pim": _to_int(pim),
                    "tpp_sec": _mmss_to_seconds(tpp),
                    "adv": _to_int(adv),
                    "pp_pct": _to_float(pp_pct),
                    "tsh_sec": _mmss_to_seconds(tsh),
                    "dvg": _to_int(dvg),
                    "sh_pct": _to_float(sh_pct),
                })
            else:
                # Om raden inte matchar, sluta leta (nästa block börjar)
                if rows:
                    in_stats = False
    return rows


def _parse_period_actions(period_text: str, period_label, home_abbr: str, away_abbr: str) -> Tuple[List, List, List, List]:
    """
    Parsa actions (Goal, Penalty, Goalkeeper) i en period.
    Returnerar: (goals, penalties, gk_changes, on_ice_events)
    """
    goals: List[Dict] = []
    penalties: List[Dict] = []
    gk_changes: List[Dict] = []
    on_ice_events: List[Dict] = []

    lines = period_text.split("\n")
    last_goal_time: Optional[str] = None
    last_goal_score: Optional[str] = None
    last_goal_team: Optional[str] = None
    expecting_on_ice = False

    for line in lines:
        ls = line.strip()
        if not ls:
            continue

        # Goal
        m = _GOAL_LINE.match(ls)
        if m:
            event_time, team_abbr, score, goal_type, rest = m.groups()
            score = score.strip()
            rest = rest.strip()
            rest = re.sub(r"\s*Participation\s*\(On ice\).*", "", rest).strip()
            scorer_num, scorer_name, a1_num, a1_name, a2_num, a2_name = _extract_goal_players(rest)
            goals.append({
                "period": period_label,
                "event_time": event_time,
                "team_abbr": team_abbr.strip(),
                "score": score,
                "goal_type": goal_type.strip(),
                "scorer_number": scorer_num,
                "scorer_name": scorer_name,
                "assist1_number": a1_num,
                "assist1_name": a1_name,
                "assist2_number": a2_num,
                "assist2_name": a2_name,
            })
            last_goal_time = event_time
            last_goal_score = score
            last_goal_team = team_abbr.strip()
            expecting_on_ice = "Participation" in ls
            continue

        # On-ice participation (after goal)
        if expecting_on_ice:
            mo = _ON_ICE_LINE.match(ls)
            if mo:
                team_key, numbers_str = mo.groups()
                numbers = [n.strip() for n in numbers_str.split() if n.strip().isdigit()]
                # Determine side: goal scoring team = positive, other = negative
                side = "positive" if team_key.upper() == (last_goal_team or "").upper() else "negative"
                for num in numbers:
                    on_ice_events.append({
                        "period": period_label,
                        "event_time": last_goal_time,
                        "score": last_goal_score,
                        "event_type": "goal",
                        "team_abbr": team_key,
                        "side": side,
                        "player_number": num,
                    })
                continue
            else:
                expecting_on_ice = False

        # Penalty
        m = _PENALTY_LINE.match(ls)
        if m:
            event_time, team_abbr, minutes, player_number, rest = m.groups()
            player_name, infraction = _split_penalty_description(rest)
            penalties.append({
                "period": period_label,
                "event_time": event_time,
                "team_abbr": team_abbr.strip(),
                "minutes": _to_int(minutes),
                "player_number": player_number,
                "player_name": player_name,
                "infraction": infraction,
            })
            continue

        # Goalkeeper change
        m = _GK_LINE.match(ls)
        if m:
            direction, event_time, team_abbr, player_number, player_name = m.groups()
            gk_changes.append({
                "period": period_label,
                "event_time": event_time,
                "team_abbr": team_abbr.strip(),
                "direction": direction,
                "player_number": player_number,
                "player_name": player_name.strip(),
            })
            continue

    return goals, penalties, gk_changes, on_ice_events


def parse_game_report(pdf_bytes: bytes, game_id: str, game_date: str) -> Dict[str, Any]:
    """
    Parsa Official_Game_Report.pdf.
    Returnerar dict med nycklar: referees, spectators, period_stats, goals,
    penalties, gk_changes, on_ice_events.
    """
    try:
        text = _pdf_text(pdf_bytes)
    except Exception as exc:
        print(f"[pdf parser] Official_Game_Report {game_id}: kunde inte läsa PDF: {exc}")
        return {}

    lines = text.split("\n")

    # Referees (first occurrence only)
    referees = []
    for ref in _parse_referees_from_game_report(lines):
        ref["game_id"] = game_id
        ref["game_date"] = game_date
        referees.append(ref)

    # Spectators
    spectators = None
    for line in lines:
        m = _SPECTATORS_PAT.search(line)
        if m:
            try:
                spectators = int(m.group(1).replace(" ", ""))
            except ValueError:
                pass
            break

    # Split into per-period blocks
    periods = _split_into_periods(text)

    # Try to extract team abbreviations from header for on-ice side determination
    # They appear as short tokens before scores: "AIS: 14 15..."  "MoDo: 6 12..."
    all_team_abbrs = set(re.findall(r"\b(\w{2,6}):\s+\d", text))

    all_period_stats: List[Dict] = []
    all_goals: List[Dict] = []
    all_penalties: List[Dict] = []
    all_gk_changes: List[Dict] = []
    all_on_ice: List[Dict] = []

    for period_label, period_text in periods.items():
        pstats = _parse_period_stats(period_text, period_label)
        for row in pstats:
            row.update({"game_id": game_id, "game_date": game_date})
        all_period_stats.extend(pstats)

        goals, penalties, gk_changes, on_ice = _parse_period_actions(
            period_text, period_label, "", ""
        )
        for row in goals + penalties + gk_changes + on_ice:
            row.update({"game_id": game_id, "game_date": game_date})
        all_goals.extend(goals)
        all_penalties.extend(penalties)
        all_gk_changes.extend(gk_changes)
        all_on_ice.extend(on_ice)

    # Full game totals (text before first period)
    first_period_m = _PERIOD_HDR.search(text)
    if first_period_m:
        preamble = text[: first_period_m.start()]
        game_totals = _parse_period_stats(preamble, "total")
        for row in game_totals:
            row.update({"game_id": game_id, "game_date": game_date})
        all_period_stats.extend(game_totals)

    return {
        "referees": referees,
        "spectators": spectators,
        "period_stats": all_period_stats,
        "goals": all_goals,
        "penalties": all_penalties,
        "gk_changes": all_gk_changes,
        "on_ice_events": all_on_ice,
    }


# ---------------------------------------------------------------------------
# Official_Team_Roster
# ---------------------------------------------------------------------------

_PLAYER_ROW = re.compile(
    r"^(GK|LD|RD|LW|CE|RW|G|D|F)\s+"   # position
    r"(\d{1,3})\s+"                       # number
    r"([A-ZÄÅÖ][^\s]+(?:,[A-ZÄÅÖ][^\s]+)?)\s+"  # Name (LAST,First or LAST FIRST)
    r"([CA]\s+)?"                          # captain flag (optional)
    r"(\d{4}-\d{2}-\d{2})"                # birthdate
)
_COACH_SECTION = re.compile(r"Team Officials", re.IGNORECASE)
_COACH_ROW = re.compile(
    r"^([A-ZÄÅÖ][A-ZÄÅÖÜ\-]+,\s+\w[^\s]+)\s+"  # LASTNAME, Firstname
    r"(.+?)(?:\s+[A-ZÄÅÖ][A-ZÄÅÖÜ\-]+,\s+\w.*)?$"  # role (+ optional second coach)
)
_LINE_LABEL = re.compile(r"^(\d+(?:st|nd|rd|th)\s+line|Extra players|Goalkeepers?)", re.IGNORECASE)


def parse_team_roster(pdf_bytes: bytes, game_id: str, game_date: str) -> Dict[str, Any]:
    """
    Parsa Official_Team_Roster.pdf.
    Returnerar dict med nycklar: roster (spelare + tränare per lag).
    """
    try:
        text = _pdf_text(pdf_bytes)
    except Exception as exc:
        print(f"[pdf parser] Official_Team_Roster {game_id}: kunde inte läsa PDF: {exc}")
        return {}

    lines = text.split("\n")
    roster_rows: List[Dict] = []

    # Find team names (appear after "Team Team" header)
    teams = _find_team_names(lines)
    home_team = teams[0] if len(teams) > 0 else ""
    away_team = teams[1] if len(teams) > 1 else ""

    current_line_label = ""
    in_coaches = False

    for line in lines:
        ls = line.strip()
        if not ls:
            continue

        # Skip repeated page headers
        if ls in ("Team Team", "Pos. No. Name Birthdate Starts Pos. No. Name Birthdate Starts",
                  "Name Official Type Name Official Type"):
            continue
        if ls in ("Official Game Report", "ReportName"):
            continue

        # Detect "Team Officials" section
        if _COACH_SECTION.search(ls):
            in_coaches = True
            continue

        # Detect line label (1st line, Goalkeepers, Extra players)
        lm = _LINE_LABEL.match(ls)
        if lm:
            current_line_label = lm.group(1)
            in_coaches = False
            continue

        if in_coaches:
            # Coach rows: two coaches per line side by side
            # E.g. "KARLIN, Mattias Head Coach ZACKRISSON, Mattias Head Coach"
            _parse_coach_line(ls, game_id, game_date, home_team, away_team, roster_rows)
            continue

        # Try to match player rows (two players per line)
        _parse_roster_line(ls, game_id, game_date, home_team, away_team,
                           current_line_label, roster_rows)

    return {"roster": roster_rows}


def _find_team_names(lines: List[str]) -> List[str]:
    """
    Extrahera lagnamn från matchup-raden: 'Home Team - Away Team LASTNAME, Ref'
    Alternativt från 'Team Team'-raden i Official_Team_Roster.
    """
    # Primärt: matcha "Home - Away REFEREE" på t.ex. raden efter "Referee(s)"
    matchup_pat = re.compile(r"^(.+?)\s+-\s+(.+?)\s+[A-ZÄÅÖÜ]+,\s+\w")
    for line in lines:
        m = matchup_pat.match(line.strip())
        if m:
            return [m.group(1).strip(), m.group(2).strip()]

    # Fallback: 'Team Team' + nästa rad "Home Away" (tvåkolumns-layout)
    for i, line in enumerate(lines):
        if line.strip() == "Team Team":
            if i + 1 < len(lines):
                next_line = lines[i + 1].strip()
                if next_line.startswith("Pos."):
                    continue
                # Försök dela med 2+ mellanslag
                parts = re.split(r"\s{2,}", next_line)
                if len(parts) >= 2:
                    return [p.strip() for p in parts[:2]]
                # Om inga dubbelmellanslag: försök dela på känd avg-token (Hockey, IS, BK, HC, IK)
                # t.ex. "MoDo Hockey Almtuna IS" → split efter "Hockey"
                m2 = re.match(r"^(.+?(?:Hockey|HC|BK|IK|IS|FF|IF|SK))\s+(.+)$", next_line)
                if m2:
                    return [m2.group(1).strip(), m2.group(2).strip()]
    return []


def _parse_roster_line(line: str, game_id: str, game_date: str,
                        home_team: str, away_team: str,
                        line_label: str, rows: List[Dict]):
    """
    Parsa en spelarrad (kan ha 1 eller 2 spelare per rad, side by side).
    """
    # Find all player segments on this line
    player_segments = list(re.finditer(
        r"(GK|LD|RD|LW|CE|RW|G|D|F)\s+"
        r"(\d{1,3})\s+"
        r"([A-ZÄÅÖ][A-ZÄÅÖa-zäåöü,\-]+)\s+"
        r"([CA]\s+)?"
        r"(\d{4}-\d{2}-\d{2})",
        line
    ))

    teams = [home_team, away_team]
    for idx, m in enumerate(player_segments):
        team = teams[idx] if idx < len(teams) else ""
        pos, number, name_raw, captain_flag, birthdate = m.groups()
        captain_role = (captain_flag or "").strip() or None
        # Clean name: "LASTNAME,Firstname" → "LASTNAME, Firstname"
        name = re.sub(r",(?=[^\s])", ", ", name_raw)
        rows.append({
            "game_id": game_id,
            "game_date": game_date,
            "team": team,
            "position": pos,
            "number": number,
            "name": name,
            "birthdate": birthdate,
            "captain_role": captain_role,
            "line_label": line_label,
            "is_coach": False,
            "coach_role": None,
        })


def _parse_coach_line(line: str, game_id: str, game_date: str,
                       home_team: str, away_team: str, rows: List[Dict]):
    """
    Parsa en tränarrad.
    Format: "LASTNAME, Firstname Head Coach LASTNAME2, Firstname2 Head Coach"
    """
    # Find all coach name + role pairs
    coach_pat = re.compile(
        r"([A-ZÄÅÖ][A-ZÄÅÖÜ\-]+,\s+[A-Za-zäåöü]+)\s+"
        r"(Head Coach|Assistant Coach|Coach|Manager|Doctor|Physiotherapist|Other|Team Official|[A-Za-z\s]+Coach)",
        re.IGNORECASE
    )
    teams = [home_team, away_team]
    for idx, m in enumerate(coach_pat.finditer(line)):
        team = teams[idx] if idx < len(teams) else ""
        name, role = m.groups()
        rows.append({
            "game_id": game_id,
            "game_date": game_date,
            "team": team,
            "position": None,
            "number": None,
            "name": name.strip(),
            "birthdate": None,
            "captain_role": None,
            "line_label": None,
            "is_coach": True,
            "coach_role": role.strip(),
        })


# ---------------------------------------------------------------------------
# Official_Line_Up
# ---------------------------------------------------------------------------

_LINEUP_PLAYER = re.compile(
    r"(\d{1,3})\s+([A-ZÄÅÖ][A-ZÄÅÖÜ,\s\-]+?)\s+\((LW|CE|RW|LD|RD|GK|G|D|F)\)"
)
_LINEUP_TEAM = re.compile(r"^Team\s*$")


def parse_lineup(pdf_bytes: bytes, game_id: str, game_date: str) -> Dict[str, Any]:
    """
    Parsa Official_Line_Up.pdf.
    Returnerar: referees (backup) och starting_lineup.
    """
    try:
        text = _pdf_text(pdf_bytes)
    except Exception as exc:
        print(f"[pdf parser] Official_Line_Up {game_id}: kunde inte läsa PDF: {exc}")
        return {}

    lines = text.split("\n")
    referees = []
    for ref in _parse_referees_from_game_report(lines):
        ref["game_id"] = game_id
        ref["game_date"] = game_date
        referees.append(ref)

    # Extract starting lineup entries
    lineup: List[Dict] = []
    current_team = ""
    current_line = None

    for line in lines:
        ls = line.strip()
        if not ls:
            continue

        # Team label (standalone "Team" followed by team name on next line)
        # Or directly "MoDo Hockey" / "Almtuna IS"
        if ls == "Team":
            continue

        # Line number labels: "1st", "2nd", "3rd", "4th", "Extra players"
        line_m = re.match(r"^(1st|2nd|3rd|4th|Extra players)$", ls, re.IGNORECASE)
        if line_m:
            current_line = line_m.group(1)
            continue

        # Player entries with position in parens: "31 TIKKANEN, Henrik"
        # or "7 NÄSÉN, Pontus (RD) 2 HASA, Filip (LD)"
        for pm in _LINEUP_PLAYER.finditer(ls):
            number, name, position = pm.groups()
            lineup.append({
                "game_id": game_id,
                "game_date": game_date,
                "team": current_team,
                "line_number": current_line,
                "number": number.strip(),
                "name": name.strip().rstrip(","),
                "position": position,
            })
            continue

        # Goalkeeper entries without position in parens: "1 WILLIAMSSON, Tex"
        gk_m = re.match(r"^(\d{1,2})\s+([A-ZÄÅÖ][A-ZÄÅÖÜ,\s\-]+)$", ls)
        if gk_m and current_team:
            number, name = gk_m.groups()
            lineup.append({
                "game_id": game_id,
                "game_date": game_date,
                "team": current_team,
                "line_number": "Goalkeepers",
                "number": number.strip(),
                "name": name.strip().rstrip(","),
                "position": "GK",
            })
            continue

        # Team name detection: multi-word capitalized not matching other patterns
        if re.match(r"^[A-ZÄÅÖ][A-Za-zäåöüÄÅÖÜ\s\-]+$", ls) and len(ls) > 3 and not re.search(r"\d", ls):
            if ls not in ("Official Line Up", "HockeyAllsvenskan", "J20 Nationell", "Linesman"):
                current_team = ls
                current_line = None

    return {"referees": referees, "starting_lineup": lineup}


# ---------------------------------------------------------------------------
# Player_Summary.pdf
# ---------------------------------------------------------------------------

_SKATER_HDR_PLAYER_SUMMARY = re.compile(
    r"^Name\s+No\.\s+Pos\.\s+G\s+A\s+TP"
)
_GOALIE_HDR_PLAYER_SUMMARY = re.compile(
    r"^Name\s+No\.\s+Pos\.\s+SOG\s+GA\s+SVS\s+SVS%\s+MIP"
)
_SKATER_ROW_PLAYER_SUMMARY = re.compile(
    r"^([A-ZÄÅÖ][A-ZÄÅÖa-zäåöü,\s\-\.]+?),\s+([A-Za-zäåöü\-]+)\s+"  # LAST, First
    r"(\d{1,2})\s+"   # number
    r"(GK|LD|RD|LW|CE|RW|G|D|F)\s+"  # position
    r"(-?\d+)\s+"     # G
    r"(-?\d+)\s+"     # A
    r"(-?\d+)\s+"     # TP
    r"(-?\d+)\s+"     # +/-
    r"(\d+)\s+"       # PIM
    r"(\d+)\s+"       # SOG
    r"([\d/]+)\s+"    # FO+/-
    r"([\d,]+|N/A)"   # FO%
)
_GOALIE_ROW_PLAYER_SUMMARY = re.compile(
    r"^([A-ZÄÅÖ][A-ZÄÅÖa-zäåöü,\s\-\.]+?),\s+([A-Za-zäåöü\-]+)\s+"  # LAST, First
    r"(\d{1,2})\s+"   # number
    r"GK\s+"          # position
    r"(\d+)\s+"       # SOG
    r"(\d+)\s+"       # GA
    r"(\d+)\s+"       # SVS
    r"([\d,]+)\s+"    # SVS%
    r"(\d{1,2}:\d{2})\s+"  # MIP
    r"([\d,]+)"       # GAA
)


def parse_player_summary(pdf_bytes: bytes, game_id: str, game_date: str) -> Dict[str, Any]:
    """
    Parsa Player_Summary.pdf.
    Returnerar: player_stats, goalie_stats (per spelare).
    """
    try:
        text = _pdf_text(pdf_bytes)
    except Exception as exc:
        print(f"[pdf parser] Player_Summary {game_id}: kunde inte läsa PDF: {exc}")
        return {}

    # Extrahera lag från matchup-rad
    teams = _extract_teams_from_matchup(text)
    team_section_idx = 0

    lines = text.split("\n")
    player_stats: List[Dict] = []
    goalie_stats: List[Dict] = []
    mode = None  # "skaters" | "goalies"

    for line in lines:
        ls = line.strip()
        if not ls:
            continue

        if _SKATER_HDR_PLAYER_SUMMARY.match(ls):
            mode = "skaters"
            continue
        if _GOALIE_HDR_PLAYER_SUMMARY.match(ls):
            mode = "goalies"
            continue

        # "Player Summary" markerar ny lagsida
        if ls == "Player Summary":
            if mode is not None:
                team_section_idx += 1
            mode = None
            continue

        current_team = teams[team_section_idx] if team_section_idx < len(teams) else ""

        if mode == "skaters":
            m = _SKATER_ROW_PLAYER_SUMMARY.match(ls)
            if m:
                last, first, number, pos, goals, assists, tp, pm, pim, sog, fo_ratio, fo_pct = m.groups()
                fo_parts = fo_ratio.split("/") if "/" in fo_ratio else [None, None]
                player_stats.append({
                    "game_id": game_id,
                    "game_date": game_date,
                    "team": current_team,
                    "number": number,
                    "name": f"{last.strip()}, {first.strip()}",
                    "position": pos,
                    "goals": _to_int(goals),
                    "assists": _to_int(assists),
                    "points": _to_int(tp),
                    "plus_minus": _to_int(pm),
                    "pim": _to_int(pim),
                    "sog": _to_int(sog),
                    "fo_won": _to_int(fo_parts[0]),
                    "fo_lost": _to_int(fo_parts[1]),
                    "fo_pct": _to_float(fo_pct),
                    "hits": None,
                    "blocks": None,
                    "shifts": None,
                    "toi": None,
                    "source": "Player_Summary",
                })
        elif mode == "goalies":
            m = _GOALIE_ROW_PLAYER_SUMMARY.match(ls)
            if m:
                last, first, number, sog, ga, saves, svs_pct, mip, gaa = m.groups()
                goalie_stats.append({
                    "game_id": game_id,
                    "game_date": game_date,
                    "team": current_team,
                    "number": number,
                    "name": f"{last.strip()}, {first.strip()}",
                    "sog": _to_int(sog),
                    "ga": _to_int(ga),
                    "saves": _to_int(saves),
                    "svs_pct": _to_float(svs_pct),
                    "toi": mip,
                    "gaa": _to_float(gaa),
                    "pp_svs": None,
                    "pp_shots_against": None,
                    "source": "Player_Summary",
                })

    return {"player_stats": player_stats, "goalie_stats": goalie_stats}


# ---------------------------------------------------------------------------
# Media_Game_Summary.pdf
# ---------------------------------------------------------------------------

_SKATER_HDR_MEDIA = re.compile(
    r"^Skaters\s+SOG\s+Goals\s+Assists\s+Points"
)
_GOALIE_HDR_MEDIA = re.compile(
    r"^Goalies\s+Saves\s+GA\s+SOG"
)
# Media_Game_Summary format: "NUM LASTNAME Firstname SOG Goals Assists Points +/- PIM Hits Blocks FO FO% [Shifts TOI]"
# LASTNAME = all-uppercase word(s), Firstname = Title-case word
_SKATER_ROW_MEDIA = re.compile(
    r"^(\d{1,3})\s+"                        # number
    r"([A-ZÄÅÖÜ][A-ZÄÅÖÜ\-]+)\s+"          # LASTNAME (all caps)
    r"([A-Za-zäåöü][a-zäåöüA-Z\-]*(?:\s+[A-Za-zäåöü][a-zäåöüA-Z\-]*)?)\s+"  # Firstname
    r"(-?\d+)\s+"         # SOG
    r"(-?\d+)\s+"         # Goals
    r"(-?\d+)\s+"         # Assists
    r"(-?\d+)\s+"         # Points
    r"(-?\d+)\s+"         # +/-
    r"(-?\d+)\s+"         # PIM
    r"(\d+|-)\s+"         # Hits
    r"(\d+|-)\s+"         # Blocks
    r"(\d+|-)\s+"         # FO
    r"([\d,]+|N/A|-)"     # FO%  (end may be here for older data)
    r"(?:\s+(\d+|-))??"    # Shifts (optional)
    r"(?:\s+([\d:]+|N/A))?" # TOI (optional)
    r"\s*$"
)
_GOALIE_ROW_MEDIA = re.compile(
    r"^(\d{1,3})\s+"               # number
    r"([A-ZÄÅÖÜ][A-ZÄÅÖÜ\-]+)\s+"  # LASTNAME (all caps)
    r"([A-Za-zäåöü][a-zäåöüA-Z\-]*)\s+"  # Firstname
    r"(\d+)\s+"          # Saves
    r"(\d+)\s+"          # GA
    r"(\d+)\s+"          # SOG
    r"([\d,]+)\s+"       # SVS%
    r"(\d+|-)\s+"        # PP SVS
    r"(\d+|-)\s+"        # PP shots against
    r"([\d:]+)"          # TOI
)


def _extract_teams_from_matchup(text: str) -> List[str]:
    """
    Hitta 'Home Team - Away Team' på en rad.
    Hanterar:
      - Ren rad: "MoDo Hockey - Almtuna IS"
      - Med domare: "MoDo Hockey - Almtuna IS NORMAN, Petter"
    Undviker att matcha score-rader: inga siffror i lagnamnen.
    """
    # Mönster 1: ren matchup-rad (Media_Game_Summary)
    # Använd [ ] istf \s för att inte matcha \n i character class
    clean_pat = re.compile(
        r"^([A-ZÄÅÖ][A-Za-zäåöü -]+?) - ([A-ZÄÅÖ][A-Za-zäåöü -]+)$",
        re.MULTILINE
    )
    # Mönster 2: matchup + referee (Official_Game_Report, Player_Summary)
    ref_pat = re.compile(
        r"^([A-ZÄÅÖ][A-Za-zäåöü -]+?)\s+-\s+([A-ZÄÅÖ][A-Za-zäåöü -]+?)\s+[A-ZÄÅÖÜ]{2,},",
        re.MULTILINE
    )

    for pat in (clean_pat, ref_pat):
        for m in pat.finditer(text):
            home = m.group(1).strip()
            away = m.group(2).strip()
            # Validera: ≥ 3 tecken, inga siffror
            if len(home) >= 3 and len(away) >= 3 and not re.search(r"\d", home + away):
                return [home, away]
    return []


def parse_media_summary(pdf_bytes: bytes, game_id: str, game_date: str) -> Dict[str, Any]:
    """
    Parsa Media_Game_Summary.pdf.
    Returnerar: player_stats, goalie_stats.

    Sidlayout: sida 1 = matchöversikt/scoring/penalties,
               sida 2 = hemmalaget player summary,
               sida 3 = bortalaget player summary.
    Lagnamn extraheras från matchup-raden "Home - Away".
    """
    try:
        text = _pdf_text(pdf_bytes)
    except Exception as exc:
        print(f"[pdf parser] Media_Game_Summary {game_id}: kunde inte läsa PDF: {exc}")
        return {}

    # Extrahera lagnamn från matchup-rad: "Home Team - Away Team" (inga siffror)
    teams = _extract_teams_from_matchup(text)
    team_section_idx = 0  # 0 = hemmalag, 1 = bortalag

    lines = text.split("\n")
    player_stats: List[Dict] = []
    goalie_stats: List[Dict] = []
    mode = None

    for line in lines:
        ls = line.strip()
        if not ls:
            continue

        # "Player Summary" markerar ny lagsida
        if ls == "Player Summary":
            # Återstarta mode – nästa Skaters/Goalies-block är nästa lag
            if mode is not None:
                team_section_idx += 1
            mode = None
            continue

        if _SKATER_HDR_MEDIA.match(ls):
            mode = "skaters"
            continue
        if _GOALIE_HDR_MEDIA.match(ls):
            mode = "goalies"
            continue

        # Avsluta parse vid kända sidhuvud-mönster
        if re.match(r"^(HockeyAllsvenskan|SHL|J20|U\d+|Game Summary|Scoring Summary|Penalty Summary)", ls):
            mode = None
            continue
        if re.match(r"^(Period \d|Total|Power Play|Penalty Killing)", ls):
            mode = None
            continue

        current_team = teams[team_section_idx] if team_section_idx < len(teams) else ""

        if mode == "skaters":
            m = _SKATER_ROW_MEDIA.match(ls)
            if m:
                number, lastname, firstname, sog, goals, assists, points, pm, pim, hits, blocks, fo, fo_pct, shifts, toi = m.groups()
                player_stats.append({
                    "game_id": game_id,
                    "game_date": game_date,
                    "team": current_team,
                    "number": number,
                    "name": f"{lastname} {firstname}".strip(),
                    "position": None,
                    "goals": _to_int(goals),
                    "assists": _to_int(assists),
                    "points": _to_int(points),
                    "plus_minus": _to_int(pm),
                    "pim": _to_int(pim),
                    "sog": _to_int(sog),
                    "fo_won": None,
                    "fo_lost": None,
                    "fo_pct": _to_float(fo_pct),
                    "hits": _to_int(hits),
                    "blocks": _to_int(blocks),
                    "shifts": _to_int(shifts),
                    "toi": toi if toi and toi not in ("-", "N/A") else None,
                    "source": "Media_Game_Summary",
                })
        elif mode == "goalies":
            m = _GOALIE_ROW_MEDIA.match(ls)
            if m:
                number, lastname, firstname, saves, ga, sog, svs_pct, pp_svs, pp_shots, toi = m.groups()
                ga_int = _to_int(ga)
                goalie_stats.append({
                    "game_id": game_id,
                    "game_date": game_date,
                    "team": current_team,
                    "number": number,
                    "name": f"{lastname} {firstname}",
                    "sog": _to_int(sog),
                    "ga": ga_int,
                    "saves": _to_int(saves),
                    "svs_pct": _to_float(svs_pct),
                    "toi": toi,
                    "gaa": _compute_gaa(ga_int, toi),
                    "pp_svs": _to_int(pp_svs),
                    "pp_shots_against": _to_int(pp_shots),
                    "source": "Media_Game_Summary",
                })

    return {"player_stats": player_stats, "goalie_stats": goalie_stats}


# ---------------------------------------------------------------------------
# Huvud-dispatcher
# ---------------------------------------------------------------------------

_PDF_TYPE_MAP = {
    "Official_Game_Report": parse_game_report,
    "Official_Team_Roster": parse_team_roster,
    "Official_Line_Up": parse_lineup,
    "Player_Summary": parse_player_summary,
    "Media_Game_Summary": parse_media_summary,
}


def parse_pdf(pdf_type: str, pdf_bytes: bytes, game_id: str, game_date: str) -> Dict[str, Any]:
    """
    Huvud-entry-point. Väljer rätt parser baserat på pdf_type.
    pdf_type: en av nycklarna i _PDF_TYPE_MAP.
    """
    parser = _PDF_TYPE_MAP.get(pdf_type)
    if parser is None:
        return {}
    try:
        return parser(pdf_bytes, game_id, game_date)
    except Exception as exc:
        print(f"[pdf parser] {pdf_type} game_id={game_id}: parse-fel: {exc}")
        return {}
