"""
Stealth configuration för att göra scraping mer mänsklig
Reducerar risken för upptäckt och blocking
"""

import random
import time
from typing import Dict, List

# Roterande User-Agents (ser mer mänskliga ut)
USER_AGENTS = [
    # Chrome på Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    # Chrome på macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    # Firefox på Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    # Firefox på macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:121.0) Gecko/20100101 Firefox/121.0",
    # Safari på macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
    # Edge på Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
]

# Accept headers (ser mer legitima ut)
ACCEPT_HEADERS = [
    "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
]

# Accept-Language headers
ACCEPT_LANGUAGE_HEADERS = [
    "sv-SE,sv;q=0.9,en-US;q=0.8,en;q=0.7",
    "sv-SE,sv;q=0.9,en;q=0.8",
    "sv,en-US;q=0.9,en;q=0.8",
]


def get_random_headers() -> Dict[str, str]:
    """
    Generera slumpmässiga headers som ser mänskliga ut
    
    Returns:
        Dict med headers
    """
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": random.choice(ACCEPT_HEADERS),
        "Accept-Language": random.choice(ACCEPT_LANGUAGE_HEADERS),
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0",
        "DNT": "1",  # Do Not Track
    }


def get_stealth_delay(base_delay: float = 1.0, variance: float = 0.5) -> float:
    """
    Generera slumpmässig delay (ser mer mänsklig ut än fast delay)
    
    Args:
        base_delay: Bas-delay i sekunder
        variance: Varians (slumpmässig variation)
        
    Returns:
        Delay i sekunder
    """
    # Lägg till lite slumpmässighet
    delay = base_delay + random.uniform(-variance, variance)
    # Minimum 0.5 sekunder
    return max(0.5, delay)


def human_like_delay(base_delay: float = 1.0):
    """
    Vänta med mänsklig-liknande delay (med slumpmässighet)
    
    Args:
        base_delay: Bas-delay i sekunder
    """
    delay = get_stealth_delay(base_delay)
    time.sleep(delay)


# Rate limiting konfiguration
RATE_LIMIT_CONFIG = {
    "base_delay": 1.5,  # Bas-delay mellan requests (sekunder)
    "variance": 0.5,    # Slumpmässig variation
    "min_delay": 0.5,    # Minimum delay
    "max_delay": 3.0,   # Maximum delay
    "burst_delay": 5.0, # Extra delay efter burst (t.ex. efter 10 requests)
    "burst_size": 10,   # Antal requests innan extra delay
}

# Request patterns (för att simulera mänskligt beteende)
REQUEST_PATTERNS = {
    "normal": {
        "delay": (1.0, 2.0),  # Delay mellan 1-2 sekunder
        "burst_after": 10,    # Extra delay efter 10 requests
        "burst_delay": 5.0,   # Extra delay vid burst
    },
    "slow": {
        "delay": (2.0, 4.0),  # Delay mellan 2-4 sekunder
        "burst_after": 5,     # Extra delay efter 5 requests
        "burst_delay": 10.0,  # Extra delay vid burst
    },
    "very_slow": {
        "delay": (3.0, 6.0),  # Delay mellan 3-6 sekunder
        "burst_after": 3,     # Extra delay efter 3 requests
        "burst_delay": 15.0,  # Extra delay vid burst
    },
}


class StealthRateLimiter:
    """Smart rate limiter som simulerar mänskligt beteende"""
    
    def __init__(self, pattern: str = "normal"):
        """
        Initiera rate limiter
        
        Args:
            pattern: Request pattern ("normal", "slow", "very_slow")
        """
        self.pattern = REQUEST_PATTERNS.get(pattern, REQUEST_PATTERNS["normal"])
        self.request_count = 0
    
    def wait(self):
        """Vänta med mänsklig-liknande delay"""
        self.request_count += 1
        
        # Normal delay
        min_delay, max_delay = self.pattern["delay"]
        delay = random.uniform(min_delay, max_delay)
        
        # Extra delay efter burst
        if self.request_count % self.pattern["burst_after"] == 0:
            delay += self.pattern["burst_delay"]
            print(f"   ⏸️  Paus efter {self.request_count} requests...")
        
        time.sleep(delay)
    
    def reset(self):
        """Återställ request count"""
        self.request_count = 0


def get_referer_url(base_url: str, path: str = "") -> str:
    """
    Generera referer URL (ser mer legitim ut)
    
    Args:
        base_url: Base URL
        path: Path (valfritt)
        
    Returns:
        Referer URL
    """
    if path:
        return f"{base_url}{path}"
    return base_url


