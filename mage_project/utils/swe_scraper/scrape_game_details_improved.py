"""
Förbättrad scraper för match-detaljer med komplett statistik
Extraherar boxscore, events, spelarstatistik, målvaktsstatistik
"""

import urllib.request
import urllib.error
import ssl
import re
import json
import html as html_lib
import gzip
from pathlib import Path
from datetime import datetime
from datetime import timezone
from typing import Dict, Optional, List
from functools import wraps
import time
import logging

# Importera lineups-scraper (hantera circular import)
try:
    from src.scrape_lineups import scrape_lineups
except ImportError:
    scrape_lineups = None

BASE_URL = "https://stats.swehockey.se"

# Konfigurera logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# SSL context
ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

headers = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "sv-SE,sv;q=0.9,en;q=0.8",
}

MAX_RETRIES = 3
TIMEOUT = 30


def retry_with_backoff(max_retries=MAX_RETRIES):
    """Decorator för retry med exponential backoff"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            delay = 1
            last_exception = None
            
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        delay = min(delay * 2, 60)
                        logger.warning(f"Retry {attempt + 1}/{max_retries} för {func.__name__} efter {delay}s")
                        time.sleep(delay)
                    else:
                        logger.error(f"Alla {max_retries} försök misslyckades för {func.__name__}")
                except Exception as e:
                    logger.error(f"Oväntat fel i {func.__name__}: {e}")
                    raise
            
            raise last_exception
        return wrapper
    return decorator


class GameDetails:
    """Detaljerad match-information med komplett statistik"""
    
    def __init__(self):
        # Grundläggande info
        self.game_id: Optional[str] = None
        self.date: Optional[str] = None
        self.time: Optional[str] = None
        self.home_team: Optional[str] = None
        self.away_team: Optional[str] = None
        self.home_score: Optional[int] = None
        self.away_score: Optional[int] = None
        self.venue: Optional[str] = None
        self.league: Optional[str] = None
        
        # Periodresultat
        self.period_scores: List[Dict] = []  # [{"period": 1, "home": 0, "away": 0}, ...]
        
        # Boxscore-statistik
        self.home_team_stats: Dict = {
            "shots": None,
            "shots_by_period": [],  # [11, 10, 2]
            "saves": None,
            "saves_by_period": [],
            "save_percentage": None,
            "penalty_minutes": None,
            "penalty_minutes_by_period": [],
            "powerplay_percentage": None,
            "powerplay_time": None,
        }
        self.away_team_stats: Dict = {
            "shots": None,
            "shots_by_period": [],
            "saves": None,
            "saves_by_period": [],
            "save_percentage": None,
            "penalty_minutes": None,
            "penalty_minutes_by_period": [],
            "powerplay_percentage": None,
            "powerplay_time": None,
        }
        
        # Events (mål, utvisningar, etc.)
        self.events: List[Dict] = []  # [{"time": "26:37", "period": 2, "type": "goal", "team": "FRÖ", ...}]
        
        # Målvaktsstatistik
        self.goalkeepers: List[Dict] = []  # [{"team": "FRÖ", "name": "Otto Berggren", "number": "30", "save_percentage": 92.00, ...}]
        
        # Spelarstatistik (mål, assist, etc.)
        self.player_stats: List[Dict] = []  # [{"team": "FRÖ", "name": "...", "goals": 1, "assists": 0, ...}]
        
        # Lineups och domare
        self.referees: List[str] = []
        self.linesmen: List[str] = []
        self.home_team_lineup: Dict = {
            "head_coach": None,
            "assistant_coach": None,
            "goalies": [],
            "lines": [],
            "extra_players": []
        }
        self.away_team_lineup: Dict = {
            "head_coach": None,
            "assistant_coach": None,
            "goalies": [],
            "lines": [],
            "extra_players": []
        }
        
        # Metadata för källhänvisning
        self.metadata: Dict = {
            "source_urls": {
                "events": None,      # /Game/Events/{id}
                "lineups": None,      # /Game/LineUps/{id}
                "reports": None,      # /Game/Reports/{id}
            },
            "scraped_at": None,       # När data scrapades
            "scraper_version": "1.0", # Version av scraper
            "data_version": "1.0",    # Version av data-struktur
        }
    
    def to_dict(self) -> Dict:
        return {
            "game_id": self.game_id,
            "date": self.date,
            "time": self.time,
            "home_team": self.home_team,
            "away_team": self.away_team,
            "home_score": self.home_score,
            "away_score": self.away_score,
            "venue": self.venue,
            "league": self.league,
            "period_scores": self.period_scores,
            "home_team_stats": self.home_team_stats,
            "away_team_stats": self.away_team_stats,
            "events": self.events,
            "goalkeepers": self.goalkeepers,
            "player_stats": self.player_stats,
            "referees": self.referees,
            "linesmen": self.linesmen,
            "home_team_lineup": self.home_team_lineup,
            "away_team_lineup": self.away_team_lineup,
            "metadata": self.metadata,
        }


@retry_with_backoff(max_retries=MAX_RETRIES)
def fetch_page(url: str, use_stealth: bool = True) -> Optional[str]:
    """Hämta en HTML-sida med retry-logik"""
    try:
        # Använd roterande headers för varje request (mer mänskligt)
        if use_stealth:
            try:
                from src.stealth_config import get_random_headers
                current_headers = get_random_headers()
            except ImportError:
                current_headers = headers
        else:
            current_headers = headers
        
        req = urllib.request.Request(url, headers=current_headers)
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=ssl_context) as response:
            status_code = response.getcode()
            
            if status_code == 429:
                logger.warning(f"Rate limited (429) för {url}, väntar...")
                time.sleep(60)
                raise urllib.error.HTTPError(url, 429, "Rate Limited", response.headers, None)
            elif status_code >= 400:
                raise urllib.error.HTTPError(url, status_code, "HTTP Error", response.headers, None)
            
            # Läs content
            content = response.read()
            
            # Kolla om det är gzip-komprimerat
            content_encoding = response.headers.get('Content-Encoding', '').lower()
            if content_encoding == 'gzip' or content.startswith(b'\x1f\x8b'):
                # Gzip-komprimerad
                try:
                    html = gzip.decompress(content).decode('utf-8', errors='ignore')
                    logger.debug(f"Hämtade {len(content)} bytes (gzip) → {len(html)} bytes (dekomprimerat) från {url}")
                except Exception as e:
                    logger.warning(f"Kunde inte dekomprimera gzip för {url}: {e}, försöker som vanlig text")
                    html = content.decode('utf-8', errors='ignore')
            else:
                # Vanlig text
                html = content.decode('utf-8', errors='ignore')
                logger.debug(f"Hämtade {len(html)} bytes från {url}")
            
            return html
            
    except urllib.error.HTTPError as e:
        if e.code == 404:
            logger.warning(f"404 Not Found: {url}")
            return None
        raise
    except Exception as e:
        logger.error(f"Fel vid hämtning av {url}: {e}")
        raise


def extract_team_names(html: str) -> tuple:
    """Extrahera lag-namn från HTML"""
    # Lag-namn finns i <h2> taggar: <h2>Väsby IK HK - Wings HC Arlanda</h2>
    team_pattern = r'<h2>([^<]+)\s*-\s*([^<]+)</h2>'
    match = re.search(team_pattern, html)
    if match:
        home_team = html_lib.unescape(match.group(1).strip())
        away_team = html_lib.unescape(match.group(2).strip())
        return home_team, away_team
    
    # Alternativ: Leta efter i title tag
    title_pattern = r'<title>([^<]+)\s*-\s*([^<]+)'
    title_match = re.search(title_pattern, html)
    if title_match:
        home_team = html_lib.unescape(title_match.group(1).strip())
        away_team = html_lib.unescape(title_match.group(2).strip())
        return home_team, away_team
    
    return None, None


def extract_period_scores(html: str) -> List[Dict]:
    """Extrahera periodresultat"""
    # Format: (0-0, 1-1, 0-1) eller liknande
    period_pattern = r'\((\d+)-(\d+),\s*(\d+)-(\d+),\s*(\d+)-(\d+)\)'
    match = re.search(period_pattern, html)
    
    if match:
        periods = []
        periods.append({"period": 1, "home": int(match.group(1)), "away": int(match.group(2))})
        periods.append({"period": 2, "home": int(match.group(3)), "away": int(match.group(4))})
        periods.append({"period": 3, "home": int(match.group(5)), "away": int(match.group(6))})
        return periods
    
    return []


def extract_boxscore_stats(html: str) -> tuple:
    """Extrahera boxscore-statistik för båda lagen"""
    home_stats = {}
    away_stats = {}
    
    # Shots
    shots_pattern = r'<td[^>]*>Shots</td><td[^>]*><strong>(\d+)</strong></td>.*?<td[^>]*>Shots</td><td[^>]*><strong>(\d+)</strong></td>'
    shots_match = re.search(shots_pattern, html, re.DOTALL)
    if shots_match:
        home_stats["shots"] = int(shots_match.group(1))
        away_stats["shots"] = int(shots_match.group(2))
        
        # Shots per period (format: (11:10:2))
        shots_period_pattern = r'Shots</td><td[^>]*><strong>\d+</strong></td><td[^>]*>\((\d+):(\d+):(\d+)\)'
        shots_period_matches = re.findall(shots_period_pattern, html)
        if len(shots_period_matches) >= 2:
            home_stats["shots_by_period"] = [int(x) for x in shots_period_matches[0]]
            away_stats["shots_by_period"] = [int(x) for x in shots_period_matches[1]]
    
    # Saves
    saves_pattern = r'<td[^>]*>Saves</td><td[^>]*><strong>(\d+)</strong></td>.*?<td[^>]*>Saves</td><td[^>]*><strong>(\d+)</strong></td>'
    saves_match = re.search(saves_pattern, html, re.DOTALL)
    if saves_match:
        home_stats["saves"] = int(saves_match.group(1))
        away_stats["saves"] = int(saves_match.group(2))
        
        # Saves per period
        saves_period_pattern = r'Saves</td><td[^>]*><strong>\d+</strong></td><td[^>]*>\((\d+):(\d+):(\d+)\)'
        saves_period_matches = re.findall(saves_period_pattern, html)
        if len(saves_period_matches) >= 2:
            home_stats["saves_by_period"] = [int(x) for x in saves_period_matches[0]]
            away_stats["saves_by_period"] = [int(x) for x in saves_period_matches[1]]
    
    # Save percentage (finns på raden efter Saves-raden i tdOddSlimPrc)
    # Format: <tr><td>Saves</td>...</tr><tr><td class="tdOddSlimPrc">92,00%</td>...</tr>
    save_pct_pattern = r'Saves.*?tdOddSlimPrc.*?(\d+,\d+)%.*?tdOddSlimPrc.*?(\d+,\d+)%'
    save_pct_match = re.search(save_pct_pattern, html, re.DOTALL)
    if save_pct_match:
        home_stats["save_percentage"] = float(save_pct_match.group(1).replace(',', '.'))
        away_stats["save_percentage"] = float(save_pct_match.group(2).replace(',', '.'))
    
    # Penalty minutes (PIM)
    pim_pattern = r'<td[^>]*>PIM</td><td[^>]*><strong>(\d+)</strong></td>.*?<td[^>]*>PIM</td><td[^>]*><strong>(\d+)</strong></td>'
    pim_match = re.search(pim_pattern, html, re.DOTALL)
    if pim_match:
        home_stats["penalty_minutes"] = int(pim_match.group(1))
        away_stats["penalty_minutes"] = int(pim_match.group(2))
        
        # PIM per period
        pim_period_pattern = r'PIM</td><td[^>]*><strong>\d+</strong></td><td[^>]*>\((\d+):(\d+):(\d+)\)'
        pim_period_matches = re.findall(pim_period_pattern, html)
        if len(pim_period_matches) >= 2:
            home_stats["penalty_minutes_by_period"] = [int(x) for x in pim_period_matches[0]]
            away_stats["penalty_minutes_by_period"] = [int(x) for x in pim_period_matches[1]]
    
    # Powerplay percentage
    pp_pattern = r'<td[^>]*>PP</td><td[^>]*><strong>([\d,]+)%</strong></td>.*?<td[^>]*>PP</td><td[^>]*><strong>([\d,]+)%</strong></td>'
    pp_match = re.search(pp_pattern, html, re.DOTALL)
    if pp_match:
        home_stats["powerplay_percentage"] = float(pp_match.group(1).replace(',', '.'))
        away_stats["powerplay_percentage"] = float(pp_match.group(2).replace(',', '.'))
    
    # Powerplay time
    pp_time_pattern = r'\((\d{2}:\d{2})\)</td><td[^>]*>.*?PP.*?\((\d{2}:\d{2})\)'
    pp_time_match = re.search(pp_time_pattern, html, re.DOTALL)
    if pp_time_match:
        home_stats["powerplay_time"] = pp_time_match.group(1)
        away_stats["powerplay_time"] = pp_time_match.group(2)
    
    return home_stats, away_stats


def extract_events(html: str) -> List[Dict]:
    """
    Extrahera events (mål, utvisningar, etc.)
    
    Hanterar olika event-typer robustt:
    - Kända typer: goal, penalty, timeout, goalkeeper_change, powerbreak, etc.
    - Okända typer: sparas som "other" med raw_type för analys
    - Saknade fält: hanteras gracefully med None-värden
    """
    events = []
    
    # Först, hitta alla period-headers och deras positioner i HTML
    # Format: <th class="tdSubTitle"><h3>1st period</h3></th>
    # Alternativt: <h3>1st period</h3> (om tdSubTitle saknas)
    period_markers = []
    
    # Försök med tdSubTitle först
    for match in re.finditer(r'<th[^>]*class="tdSubTitle"[^>]*><h3>([^<]+)</h3></th>', html, re.IGNORECASE):
        header = match.group(1).strip().lower()
        position = match.start()
        
        period_num = None
        if "1st" in header or ("1" in header and "period" in header):
            period_num = 1
        elif "2nd" in header or ("2" in header and "period" in header):
            period_num = 2
        elif "3rd" in header or ("3" in header and "period" in header):
            period_num = 3
        elif "overtime" in header or "ot" in header:
            period_num = 4
        
        if period_num:
            period_markers.append((position, period_num))
    
    # Fallback: leta efter h3 direkt om tdSubTitle inte hittades
    if not period_markers:
        for match in re.finditer(r'<h3>([^<]*period[^<]*)</h3>', html, re.IGNORECASE):
            header = match.group(1).strip().lower()
            position = match.start()
            
            period_num = None
            if "1st" in header or ("1" in header and "period" in header):
                period_num = 1
            elif "2nd" in header or ("2" in header and "period" in header):
                period_num = 2
            elif "3rd" in header or ("3" in header and "period" in header):
                period_num = 3
            elif "overtime" in header or "ot" in header:
                period_num = 4
            
            if period_num:
                period_markers.append((position, period_num))
    
    # Sortera period markers efter position (från början av HTML)
    period_markers.sort(key=lambda x: x[0])
    
    # Hitta alla event-rader i Actions-tabellen med deras positioner
    # Format: <tr><td>time</td><td>type</td><td>team</td><td>player</td></tr>
    # Försök flexibel parsing - kan ha olika style-attribut eller inga
    event_patterns = [
        # Standard format med style-attribut
        r'<tr><td[^>]*style="[^"]*">([^<]*)</td><td[^>]*style="[^"]*">([^<]*)</td><td[^>]*style="[^"]*">([^<]*)</td><td[^>]*style="[^"]*">(.*?)</td>',
        # Format utan style-attribut
        r'<tr><td[^>]*>([^<]*)</td><td[^>]*>([^<]*)</td><td[^>]*>([^<]*)</td><td[^>]*>(.*?)</td>',
        # Format med class-attribut
        r'<tr><td[^>]*class="[^"]*">([^<]*)</td><td[^>]*class="[^"]*">([^<]*)</td><td[^>]*class="[^"]*">([^<]*)</td><td[^>]*class="[^"]*">(.*?)</td>',
    ]
    
    event_matches = []
    for pattern in event_patterns:
        matches = list(re.finditer(pattern, html, re.DOTALL))
        if matches:
            event_matches = matches
            break
    
    # Om inga matches hittades, returnera tom lista
    if not event_matches:
        logger.debug("Inga event-rader hittades i Actions-tabellen")
        return events
    
    event_rows = [(m.group(1), m.group(2), m.group(3), m.group(4), m.start()) for m in event_matches]
    
    current_period = None
    
    for i, (time_str_raw, event_type_raw, team_raw, player_info_raw, event_pos) in enumerate(event_rows):
        time_str = time_str_raw.strip()
        event_type = event_type_raw.strip()
        team = team_raw.strip()
        player_info = player_info_raw.strip()
        
        # Identifiera period från headers (uppdatera current_period)
        if "period" in time_str.lower() or "overtime" in time_str.lower():
            if "1st" in time_str or ("1" in time_str and "period" in time_str.lower()):
                current_period = 1
            elif "2nd" in time_str or ("2" in time_str and "period" in time_str.lower()):
                current_period = 2
            elif "3rd" in time_str or ("3" in time_str and "period" in time_str.lower()):
                current_period = 3
            elif "overtime" in time_str.lower():
                current_period = 4
            continue
        
        # Bestäm period baserat på position i HTML
        # Hitta vilken period detta event tillhör baserat på period markers
        for j, (period_pos, period_num) in enumerate(period_markers):
            if event_pos > period_pos:
                # Om detta är sista period marker eller nästa marker är längre bort
                    if j == len(period_markers) - 1 or event_pos < period_markers[j + 1][0]:
                        current_period = period_num
                        break
        
        # Om ingen period identifierad, försök inferera från tid
        if current_period is None:
            try:
                minutes = int(time_str.split(":")[0])
                if minutes >= 40:
                    current_period = 4  # Övertid
                elif minutes >= 20:
                    current_period = 3
                elif minutes >= 0:
                    current_period = 2  # Eller 1, men vi gissar 2
            except:
                pass
        
        # Extrahera spelarnamn och nummer
        player_name = None
        player_number = None
        assists = []
        
        if player_info:
            # Format: "30. Berggren, Otto" eller "3. Irani, Leon"
            player_match = re.search(r'(\d+)\.\s*([^,<]+)', player_info)
            if player_match:
                player_number = player_match.group(1)
                player_name = html_lib.unescape(player_match.group(2).strip())
            
            # Hitta assist (format: "31. Alvudd, Isak" i div)
            assist_matches = re.findall(r'(\d+)\.\s*([^,<]+)', player_info)
            if len(assist_matches) > 1:
                assists = [{"number": m[0], "name": html_lib.unescape(m[1].strip())} for m in assist_matches[1:]]
        
        # Identifiera event-typ
        # Om period fortfarande är None, försök inferera från tid
        event_period = current_period
        if event_period is None:
            try:
                minutes = int(time_str.split(":")[0])
                if minutes >= 40:
                    event_period = 4  # Övertid
                elif minutes >= 20:
                    event_period = 3
                elif minutes >= 0:
                    event_period = 2  # Eller 1, men vi gissar 2
            except:
                pass
        
        event_dict = {
            "time": time_str,
            "period": event_period,
            "team": team,
            "type": event_type,
            "player_number": player_number,
            "player_name": player_name,
            "assists": assists
        }
        
        # Extrahera Pos. Part. och Neg. Part. (spelare involverade)
        positive_participants = []
        negative_participants = []
        
        # Pos. Part.: 13 , 19 , 20 , 27 , 31 , 74
        pos_part_match = re.search(r'Pos\.\s*Part\.:\s*([\d\s,]+)', player_info, re.IGNORECASE)
        if pos_part_match:
            pos_nums = re.findall(r'(\d+)', pos_part_match.group(1))
            positive_participants = [int(n) for n in pos_nums]
        
        # Neg. Part.: 12 , 16 , 19 , 28 , 77 , 78
        neg_part_match = re.search(r'Neg\.\s*Part\.:\s*([\d\s,]+)', player_info, re.IGNORECASE)
        if neg_part_match:
            neg_nums = re.findall(r'(\d+)', neg_part_match.group(1))
            negative_participants = [int(n) for n in neg_nums]
        
        if positive_participants:
            event_dict["positive_participants"] = positive_participants
        if negative_participants:
            event_dict["negative_participants"] = negative_participants
        
        # Specifik hantering per typ
        event_type_lower = event_type.lower()
        
        if "goal" in event_type_lower or re.match(r'\d+-\d+', event_type):
            event_dict["event_type"] = "goal"
            # Extrahera resultat från event_type (t.ex. "1-2", "5-2 (EQ)", "3-0 (PP1)")
            score_match = re.search(r'(\d+)-(\d+)', event_type)
            if score_match:
                event_dict["score_home"] = int(score_match.group(1))
                event_dict["score_away"] = int(score_match.group(2))
            
            # Extrahera måltyp: EQ (Even Strength), PP (Power Play), SH (Short Handed), ENG (Empty Net)
            if "(EQ)" in event_type:
                event_dict["goal_type"] = "even_strength"
            elif "(PP" in event_type or "PP1" in event_type or "PP2" in event_type:
                event_dict["goal_type"] = "power_play"
                # Extrahera PP-nummer
                pp_match = re.search(r'PP(\d+)', event_type)
                if pp_match:
                    event_dict["powerplay_number"] = int(pp_match.group(1))
            elif "(SH)" in event_type:
                event_dict["goal_type"] = "short_handed"
            elif "ENG" in event_type:
                event_dict["goal_type"] = "empty_net"
                event_dict["empty_net"] = True
            else:
                event_dict["goal_type"] = "unknown"
                
        elif "min" in event_type_lower or "penalty" in event_type_lower:
            event_dict["event_type"] = "penalty"
            # Extrahera utvisningsminuter
            penalty_match = re.search(r'(\d+)\s*min', event_type)
            if penalty_match:
                event_dict["penalty_minutes"] = int(penalty_match.group(1))
            
            # Extrahera utvisningstyp (om finns i player_info)
            # Format: "Boarding (48:20 - 50:20)"
            penalty_type_match = re.search(r'([A-Za-z\s]+)\s*\(', player_info)
            if penalty_type_match:
                event_dict["penalty_type"] = penalty_type_match.group(1).strip()
            
            # Extrahera tidsintervall för utvisningen
            time_range_match = re.search(r'\((\d{2}:\d{2})\s*-\s*(\d{2}:\d{2})\)', player_info)
            if time_range_match:
                event_dict["penalty_start"] = time_range_match.group(1)
                event_dict["penalty_end"] = time_range_match.group(2)
                
        elif "timeout" in event_type_lower or event_type == "TO":
            event_dict["event_type"] = "timeout"
            
        elif "gk" in event_type_lower or "goalkeeper" in event_type_lower:
            event_dict["event_type"] = "goalkeeper_change"
            if "GK In" in event_type:
                event_dict["goalkeeper_action"] = "in"
            elif "GK Out" in event_type:
                event_dict["goalkeeper_action"] = "out"
                
        elif "powerbreak" in event_type_lower:
            event_dict["event_type"] = "powerbreak"
            
        elif "shootout" in event_type_lower or "so" in event_type_lower:
            event_dict["event_type"] = "shootout"
            # Extrahera shootout-resultat om finns
            so_match = re.search(r'(\d+)-(\d+)', event_type)
            if so_match:
                event_dict["score_home"] = int(so_match.group(1))
                event_dict["score_away"] = int(so_match.group(2))
                
        elif "review" in event_type_lower or "challenge" in event_type_lower:
            event_dict["event_type"] = "video_review"
            
        elif "offside" in event_type_lower or "icing" in event_type_lower:
            event_dict["event_type"] = "stoppage"
            
        elif "faceoff" in event_type_lower:
            event_dict["event_type"] = "faceoff"
            
        elif "hit" in event_type_lower and "min" not in event_type_lower:
            event_dict["event_type"] = "hit"
            
        elif "block" in event_type_lower or "blocked" in event_type_lower:
            event_dict["event_type"] = "blocked_shot"
            
        elif "save" in event_type_lower and "percentage" not in event_type_lower:
            event_dict["event_type"] = "save"
            
        else:
            # Okänd event-typ - spara som "other" men logga för analys
            event_dict["event_type"] = "other"
            event_dict["raw_type"] = event_type  # Spara original-typ för analys
            logger.debug(f"Okänd event-typ hittad: '{event_type}' för match (tid: {time_str}, period: {event_period})")
        
        events.append(event_dict)
    
    return events


def extract_goalkeepers(html: str) -> List[Dict]:
    """Extrahera målvaktsstatistik"""
    goalkeepers = []
    
    # Hitta Goalkeeper Summary-sektionen
    gk_section = re.search(r'Goalkeeper Summary.*?<h3>', html, re.DOTALL | re.IGNORECASE)
    if gk_section:
        gk_html = gk_section.group(0)
        
        # Hitta alla rader med målvaktsstatistik (har stats)
        rows = re.findall(r'<tr>.*?</tr>', gk_html, re.DOTALL)
        
        for row in rows:
            # Hitta stats först (detta identifierar en målvaktsrad)
            stats_match = re.search(r'<strong>([\d,]+)%</strong>\s*\((\d+)/(\d+)\)', row)
            if not stats_match:
                continue
            
            save_pct = float(stats_match.group(1).replace(',', '.'))
            saves = int(stats_match.group(2))
            shots_against = int(stats_match.group(3))
            
            # Hitta number och name först (detta fungerar alltid)
            name_match = re.search(r'(\d+)\.\s*([^<]+)</td><td[^>]*><strong>', row, re.DOTALL)
            if not name_match:
                continue
            
            number = name_match.group(1).strip()
            name_raw = name_match.group(2).strip()
            name = html_lib.unescape(re.sub(r'\s+', ' ', name_raw.replace('\n', ' ').replace('\r', '')))
            
            # Hitta team - leta efter alla td med text, team är den som innehåller bara bokstäver/siffror
            # och kommer före number-td (kan innehålla svenska tecken som Ö, Ä, Å)
            all_td_text = re.findall(r'<td[^>]*>([^<]+)</td>', row)
            team = None
            for td_text in all_td_text:
                text = td_text.strip()
                # Team är vanligtvis 2-10 tecken, bara bokstäver/siffror (inkl svenska tecken)
                # Exkludera text som innehåller newlines eller är för långt
                if '\n' not in text and len(text) >= 2 and len(text) <= 10:
                    # Kontrollera att det inte är ett nummer följt av punkt (det är number)
                    if not re.match(r'^\d+\.', text):
                        team = text
                        break
            
            if not team:
                continue
            
            goalkeepers.append({
                "team": team,
                "number": number,
                "name": name,
                "save_percentage": save_pct,
                "saves": saves,
                "shots_against": shots_against
            })
    
    return goalkeepers


def scrape_game_details(game_id: str, storage=None) -> Optional[GameDetails]:
    """
    Scrapa detaljerad information för en match med komplett statistik
    
    Args:
        game_id: Match-ID
    
    Returns:
        GameDetails-objekt eller None
    """
    url = f"{BASE_URL}/Game/Events/{game_id}"
    logger.info(f"Hämtar detaljer för match {game_id}")
    
    html_content = fetch_page(url)
    if not html_content:
        return None
    
    logger.info(f"Hämtad {len(html_content)} bytes för match {game_id}")
    
    details = GameDetails()
    details.game_id = game_id
    
    # Sätt metadata
    details.metadata["source_urls"]["events"] = url
    details.metadata["scraped_at"] = datetime.now(timezone.utc).isoformat()
    
    # Extrahera lag-namn
    home_team, away_team = extract_team_names(html_content)
    details.home_team = home_team
    details.away_team = away_team
    
    # Extrahera datum och tid
    date_pattern = r'(\d{4}-\d{2}-\d{2})'
    date_match = re.search(date_pattern, html_content)
    if date_match:
        details.date = date_match.group(1)
    
    time_pattern = r'(\d{2}:\d{2})'
    time_matches = re.findall(time_pattern, html_content)
    if time_matches:
        details.time = time_matches[0]
    
    # Extrahera resultat - kan finnas i flera format
    # Format 1: <div>5 - 2</div> (Final Score)
    score_pattern = r'<div[^>]*style="[^"]*font-weight:\s*bold[^"]*"[^>]*>(\d+)\s*-\s*(\d+)</div>'
    score_match = re.search(score_pattern, html_content)
    if not score_match:
        # Format 2: <div>5 - 2</div> (enklare)
        score_pattern = r'<div[^>]*>(\d+)\s*-\s*(\d+)</div>'
        score_match = re.search(score_pattern, html_content)
    if score_match:
        details.home_score = int(score_match.group(1))
        details.away_score = int(score_match.group(2))
    
    # Extrahera spectators
    spectators_pattern = r'Spectators:\s*(\d+)'
    spectators_match = re.search(spectators_pattern, html_content, re.IGNORECASE)
    if spectators_match:
        details.attendance = int(spectators_match.group(1))
    
    # Extrahera arena
    venue_pattern = r'<h3[^>]*><b>([^<]+)</b></h3>'
    venue_match = re.search(venue_pattern, html_content)
    if venue_match:
        details.venue = html_lib.unescape(venue_match.group(1).strip())
    
    # Extrahera liga - finns i <h3> med center alignment
    # Format: <h3>Hockeyettan Norra</h3> (mellan datum och arena)
    league_pattern = r'<td[^>]*style="[^"]*text-align:\s*center[^"]*"[^>]*><h3>([^<]+)</h3>'
    league_match = re.search(league_pattern, html_content)
    if league_match:
        details.league = html_lib.unescape(league_match.group(1).strip())
    else:
        # Fallback: leta efter i alla h3
        league_pattern = r'<h3[^>]*>([^<]+)</h3>'
        league_matches = re.findall(league_pattern, html_content)
        for match in league_matches:
            match_clean = match.strip()
            # Skippa datum/tid och arena
            if not re.match(r'\d{4}-\d{2}-\d{2}', match_clean) and not re.match(r'\d{2}:\d{2}', match_clean):
                if "cup" in match_clean.lower() or "liga" in match_clean.lower() or "serie" in match_clean.lower() or "hockey" in match_clean.lower():
                    details.league = html_lib.unescape(match_clean)
                    break
    
    # Extrahera periodresultat (hantera saknade data gracefully)
    try:
        details.period_scores = extract_period_scores(html_content)
    except Exception as e:
        logger.warning(f"Fel vid extraktion av periodresultat för match {game_id}: {e}")
        details.period_scores = []
    
    # Extrahera boxscore-statistik (hantera saknade data gracefully)
    try:
        details.home_team_stats, details.away_team_stats = extract_boxscore_stats(html_content)
    except Exception as e:
        logger.warning(f"Fel vid extraktion av boxscore för match {game_id}: {e}")
        # Sätt tomma stats vid fel
        details.home_team_stats = {}
        details.away_team_stats = {}
    
    # Extrahera events (hanterar olika event-typer robustt)
    try:
        details.events = extract_events(html_content)
        # Logga om okända event-typer hittades
        unknown_events = [e for e in details.events if e.get("event_type") == "other"]
        if unknown_events:
            logger.info(f"Hittade {len(unknown_events)} okända event-typer för match {game_id} (sparade som 'other')")
    except Exception as e:
        logger.warning(f"Fel vid extraktion av events för match {game_id}: {e}")
        details.events = []  # Sätt tom lista vid fel
    
    # Förbättra period-identifiering i events (fixa null-perioder)
    # Events har period-headers som vi kan använda
    current_period = None
    for event in details.events:
        if event.get("period") is None:
            # Försök inferera period från tid
            time_str = event.get("time", "")
            if time_str:
                # Övertid är vanligtvis > 40:00
                try:
                    minutes = int(time_str.split(":")[0])
                    if minutes >= 40:
                        event["period"] = 4  # Övertid
                    elif minutes >= 20:
                        event["period"] = 3
                    elif minutes >= 0:
                        event["period"] = 2  # Eller 1, men vi gissar 2
                except:
                    pass
    
    # Extrahera målvaktsstatistik (hantera saknade data gracefully)
    try:
        details.goalkeepers = extract_goalkeepers(html_content)
    except Exception as e:
        logger.warning(f"Fel vid extraktion av målvaktsstatistik för match {game_id}: {e}")
        details.goalkeepers = []
    
    # Extrahera lineups och domare
    if scrape_lineups:
        try:
            lineup = scrape_lineups(game_id, home_team, away_team)
            if lineup:
                details.referees = lineup.referees
                details.linesmen = lineup.linesmen
                details.home_team_lineup = lineup.home_team_lineup
                details.away_team_lineup = lineup.away_team_lineup
                # Lägg till lineup URL i metadata
                details.metadata["source_urls"]["lineups"] = f"{BASE_URL}/Game/LineUps/{game_id}"
                logger.info(f"Extraherade lineups: {len(details.referees)} domare, {len(details.linesmen)} linjedomare")
        except Exception as e:
            logger.warning(f"Kunde inte hämta lineups för match {game_id}: {e}")
    
    # Extrahera rapporter och ladda ner PDF-filer
    try:
        from src.scrape_reports import scrape_reports as scrape_game_reports
        reports_output_dir = Path("data/scraped/reports") / game_id
        reports = scrape_game_reports(game_id, download_pdfs=True, output_dir=reports_output_dir)
        if reports and reports.reports:
            details.metadata["source_urls"]["reports"] = f"{BASE_URL}/Game/Reports/{game_id}"
            logger.info(f"Extraherade {len(reports.reports)} rapporter för match {game_id}")

            downloaded_pdfs = [r for r in reports.reports if r.get("downloaded_path")]
            if downloaded_pdfs:
                logger.info(f"Laddade ner {len(downloaded_pdfs)} PDF-filer för match {game_id}")

            # Ladda upp PDFs till S3 och radera lokalt
            if storage and downloaded_pdfs:
                uploaded = 0
                for report in downloaded_pdfs:
                    local_file = Path(report["downloaded_path"])
                    if local_file.exists():
                        if storage.save_report_pdf(game_id, local_file.name, local_file):
                            local_file.unlink()
                            uploaded += 1
                        else:
                            logger.warning(f"S3-uppladdning misslyckades för {local_file.name}, behåller lokalt")
                # Rensa tom katalog
                try:
                    reports_output_dir.rmdir()
                except OSError:
                    pass
                if uploaded:
                    logger.info(f"Uppladdade {uploaded} PDFs till S3 och raderade lokalt för match {game_id}")
    except Exception as e:
        logger.debug(f"Kunde inte hämta rapporter för match {game_id}: {e}")
    
    logger.info(
        f"Extraherade detaljer: {details.home_team} vs {details.away_team}, "
        f"{details.home_score}-{details.away_score}, {len(details.events)} events"
    )
    
    return details


def main():
    """Testa förbättrad scraper"""
    print("=" * 70)
    print("Förbättrad Match-detaljer Scraper")
    print("=" * 70)
    print()
    
    # Testa med ett känt match-ID
    test_game_id = "1067970"
    
    print(f"Testar med match-ID: {test_game_id}\n")
    details = scrape_game_details(test_game_id)
    
    if details:
        print(f"\n📊 Match-detaljer:")
        print(f"   ID: {details.game_id}")
        print(f"   Datum: {details.date}")
        print(f"   Tid: {details.time}")
        print(f"   Hemmalag: {details.home_team}")
        print(f"   Bortalag: {details.away_team}")
        print(f"   Resultat: {details.home_score} - {details.away_score}")
        print(f"   Arena: {details.venue}")
        print(f"   Liga: {details.league}")
        print(f"\n📈 Periodresultat:")
        for period in details.period_scores:
            print(f"   Period {period['period']}: {period['home']}-{period['away']}")
        print(f"\n📊 Boxscore:")
        print(f"   Hemmalag - Skott: {details.home_team_stats.get('shots')}, "
              f"Sparningar: {details.home_team_stats.get('saves')}, "
              f"Save %: {details.home_team_stats.get('save_percentage')}")
        print(f"   Bortalag - Skott: {details.away_team_stats.get('shots')}, "
              f"Sparningar: {details.away_team_stats.get('saves')}, "
              f"Save %: {details.away_team_stats.get('save_percentage')}")
        print(f"\n🎯 Events: {len(details.events)} händelser")
        for event in details.events[:5]:  # Visa första 5
            print(f"   {event.get('time')} - {event.get('type')} - {event.get('team')}")
        print(f"\n🥅 Målvakter: {len(details.goalkeepers)}")
        for gk in details.goalkeepers:
            print(f"   {gk['team']} - {gk['name']} (#{gk['number']}): {gk['save_percentage']}%")
        
        # Spara till fil
        output_dir = Path("data/scraped/game_details")
        output_dir.mkdir(parents=True, exist_ok=True)
        output_file = output_dir / f"game_{test_game_id}_detailed.json"
        
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(details.to_dict(), f, indent=2, ensure_ascii=False)
        
        print(f"\n💾 Sparat till: {output_file}")
    else:
        print(f"❌ Kunde inte hämta detaljer för match {test_game_id}")


if __name__ == "__main__":
    main()

