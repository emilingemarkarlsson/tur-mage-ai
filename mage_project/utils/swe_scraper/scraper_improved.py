"""
Förbättrad scraper med retry-logik, bättre error handling och logging
Production-ready version
"""

import urllib.request
import urllib.error
import ssl
import re
import json
import html as html_lib
import time
import logging
import gzip
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional
from functools import wraps

BASE_URL = "https://stats.swehockey.se"

# Konfigurera logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('scraping.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# SSL context
ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

# Använd stealth headers (roterande, ser mer mänskliga ut)
try:
    from src.stealth_config import get_random_headers
    # Generera headers per request (mer mänskligt)
    def get_headers():
        return get_random_headers()
    headers = get_headers()  # Initial headers
except ImportError:
    # Fallback om stealth_config inte finns
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "sv-SE,sv;q=0.9,en;q=0.8",
    }

# Retry-konfiguration
MAX_RETRIES = 3
INITIAL_RETRY_DELAY = 1  # sekunder
MAX_RETRY_DELAY = 60  # sekunder
TIMEOUT = 30  # sekunder


def retry_with_backoff(max_retries=MAX_RETRIES, initial_delay=INITIAL_RETRY_DELAY, max_delay=MAX_RETRY_DELAY):
    """
    Decorator för retry med exponential backoff
    
    Args:
        max_retries: Max antal försök
        initial_delay: Initial delay i sekunder
        max_delay: Max delay i sekunder
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            delay = initial_delay
            last_exception = None
            
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
                    last_exception = e
                    
                    if attempt < max_retries - 1:
                        # Exponential backoff med extra delay för DNS-fel
                        delay = min(delay * 2, max_delay)
                        error_str = str(e)
                        if "nodename" in error_str.lower() or "servname" in error_str.lower():
                            # Extra delay för DNS-fel
                            delay = min(delay + 5, max_delay)
                        logger.warning(
                            f"Retry {attempt + 1}/{max_retries} för {func.__name__} efter {delay}s: {e}"
                        )
                        time.sleep(delay)
                    else:
                        logger.error(f"Alla {max_retries} försök misslyckades för {func.__name__}: {e}")
                except Exception as e:
                    # För oväntade fel, kasta direkt
                    logger.error(f"Oväntat fel i {func.__name__}: {e}")
                    raise
            
            # Om alla försök misslyckades
            raise last_exception
        
        return wrapper
    return decorator


class Game:
    """Datamodell för en match"""
    
    def __init__(self):
        self.game_id: Optional[str] = None
        self.date: Optional[str] = None
        self.time: Optional[str] = None
        self.home_team: Optional[str] = None
        self.away_team: Optional[str] = None
        self.result: Optional[str] = None
        self.venue: Optional[str] = None
        self.league: Optional[str] = None
        self.league_id: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return {
            "game_id": self.game_id,
            "date": self.date,
            "time": self.time,
            "home_team": self.home_team,
            "away_team": self.away_team,
            "result": self.result,
            "venue": self.venue,
            "league": self.league,
            "league_id": self.league_id,
        }
    
    def validate(self) -> bool:
        """Validera att match har minsta nödvändiga data"""
        return bool(self.date and (self.home_team or self.away_team))
    
    def __repr__(self):
        return f"Game(id={self.game_id}, {self.home_team} vs {self.away_team}, {self.result})"


@retry_with_backoff(max_retries=MAX_RETRIES)
def fetch_page(url: str) -> Optional[str]:
    """
    Hämta en HTML-sida med retry-logik
    
    Args:
        url: URL att hämta
    
    Returns:
        HTML-content eller None vid fel
    """
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=ssl_context) as response:
            status_code = response.getcode()
            
            # Hantera HTTP-fel
            if status_code == 429:
                logger.warning(f"Rate limited (429) för {url}, väntar längre...")
                time.sleep(60)  # Vänta 1 minut vid rate limit
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
        elif e.code == 429:
            logger.warning(f"429 Too Many Requests: {url}")
            raise  # Låt retry-logiken hantera
        else:
            logger.error(f"HTTP {e.code} för {url}: {e.reason}")
            raise
    except urllib.error.URLError as e:
        error_reason = str(e.reason) if e.reason else str(e)
        logger.error(f"URL Error för {url}: {error_reason}")
        # För DNS/nätverksfel, vänta lite längre innan retry
        if "nodename" in error_reason.lower() or "servname" in error_reason.lower():
            logger.warning(f"DNS/nätverksfel - väntar längre innan retry...")
            time.sleep(5)  # Extra delay för DNS-fel
        raise
    except TimeoutError:
        logger.error(f"Timeout för {url}")
        raise
    except Exception as e:
        logger.error(f"Oväntat fel vid hämtning av {url}: {e}")
        raise


def extract_games_from_html(html: str, date: Optional[str] = None) -> List[Game]:
    """
    Extrahera match-data från HTML
    
    Struktur som identifierats:
    - Tabell med klasser: tblContent
    - Match-rader: <tr> med <td class="tdOdd"> eller <td class="tdNormal">
    - Kolumner: Tid, Lag, Resultat (med länk till /Game/Events/{id}), Arena
    - Liga/grupp: <tr> med colspan="5" och länk till /ScheduleAndResults/Schedule/{id}
    """
    games = []
    current_league = None
    current_league_id = None
    
    try:
        # Extrahera datum från sidan om inte angivet
        if not date:
            date_match = re.search(r'<th[^>]*>(\d{4}-\d{2}-\d{2})</th>', html)
            if date_match:
                date = date_match.group(1)
        
        # Hitta alla tabellrader med match-data
        table_rows = re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.DOTALL)
        
        for row in table_rows:
            # Kolla om det är en liga/grupp-rad (colspan="5")
            # Det finns två typer: /ScheduleAndResults/Schedule/{id} och /ScheduleAndResults/Overview/{id}
            league_match = re.search(
                r'<td[^>]*colspan="5"[^>]*>.*?<a[^>]*href="(/ScheduleAndResults/(?:Schedule|Overview)/(\d+))"[^>]*>(.*?)</a>',
                row,
                re.DOTALL
            )
            if league_match:
                current_league = league_match.group(3).strip()
                current_league_id = league_match.group(2)
                # Rensa HTML-taggar från liga-namnet
                current_league = re.sub(r'<[^>]+>', '', current_league).strip()
                current_league = html_lib.unescape(current_league)
                logger.debug(f"Hittade liga: {current_league} (ID: {current_league_id})")
                continue
            
            # Kolla om det är en match-rad
            cells = re.findall(r'<td[^>]*class="(tdOdd|tdNormal)"[^>]*>(.*?)</td>', row, re.DOTALL)
            
            if len(cells) >= 4:
                # Extrahera data från celler
                time_cell = cells[0][1].strip() if len(cells) > 0 else ""
                teams_cell = cells[1][1].strip() if len(cells) > 1 else ""
                result_cell = cells[2][1].strip() if len(cells) > 2 else ""
                venue_cell = cells[3][1].strip() if len(cells) > 3 else ""
                
                # Extrahera match-ID från resultat-länken
                # Kan vara i href="/Game/Events/123" eller javascript:openonlinewindow('/Game/Events/123',...)
                game_id_match = re.search(r'/Game/Events/(\d+)', result_cell)
                game_id = game_id_match.group(1) if game_id_match else None
                
                # Extrahera resultat
                # Kan vara i <a>text</a> eller [1 - 2](javascript:...)
                result_match = re.search(r'\[([^\]]+)\]\(|>([^<]+)</a>', result_cell)
                if result_match:
                    result = result_match.group(1) or result_match.group(2)
                    result = result.strip() if result else None
                else:
                    result = None
                
                # Om resultat är tomt eller bara whitespace, sätt till None
                if result and (not result.strip() or result.strip().isspace()):
                    result = None
                
                # Extrahera lag
                teams_text = re.sub(r'<[^>]+>', '', teams_cell).strip()
                teams_text = html_lib.unescape(teams_text)
                teams_parts = teams_text.split(' - ')
                
                # Dekoda andra fält
                time_cell = html_lib.unescape(time_cell)
                venue_cell = html_lib.unescape(venue_cell)
                if result:
                    result = html_lib.unescape(result)
                if current_league:
                    current_league = html_lib.unescape(current_league)
                
                if game_id or result or (len(teams_parts) == 2):
                    game = Game()
                    game.game_id = game_id
                    game.date = date
                    game.time = time_cell
                    game.venue = venue_cell
                    game.league = current_league
                    game.league_id = current_league_id
                    
                    if len(teams_parts) == 2:
                        game.home_team = teams_parts[0].strip()
                        game.away_team = teams_parts[1].strip()
                    elif teams_text:
                        game.home_team = teams_text
                    
                    game.result = result
                    
                    # Validera innan läggning till lista
                    if game.validate():
                        games.append(game)
                    else:
                        logger.warning(f"Match validerades inte: {game}")
        
        logger.info(f"Extraherade {len(games)} validerade matcher från HTML")
        return games
        
    except Exception as e:
        logger.error(f"Fel vid extraktion av matcher från HTML: {e}")
        return []


def scrape_games_by_date(date: str) -> List[Game]:
    """
    Scrapa matcher för ett specifikt datum
    
    Args:
        date: Datum i format YYYY-MM-DD
    
    Returns:
        Lista med Game-objekt
    """
    url = f"{BASE_URL}/GamesByDate/{date}/ByTime/null"
    logger.info(f"Hämtar matcher för {date}")
    
    try:
        html = fetch_page(url)
        if not html:
            logger.warning(f"Kunde inte hämta HTML för {date}")
            return []
        
        logger.info(f"Hämtad {len(html)} bytes för {date}")
        
        games = extract_games_from_html(html, date)
        logger.info(f"Extraherade {len(games)} matcher för {date}")
        
        return games
        
    except Exception as e:
        logger.error(f"Kritiskt fel vid scraping av {date}: {e}")
        return []


def save_games(games: List[Game], output_file: Path):
    """Spara matcher till JSON-fil"""
    try:
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        data = {
            "timestamp": datetime.now().isoformat(),
            "count": len(games),
            "games": [game.to_dict() for game in games]
        }
        
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Sparat {len(games)} matcher till {output_file}")
        
    except Exception as e:
        logger.error(f"Fel vid sparande till {output_file}: {e}")
        raise

