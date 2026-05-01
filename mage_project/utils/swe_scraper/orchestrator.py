"""
Orchestrator för att scrapa historisk data och dagliga matcher
Hanterar batch-processing, incremental updates, och checkpointing
"""

import json
import time
import ssl
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Set

# Ladda .env-fil om python-dotenv finns
try:
    from dotenv import load_dotenv
    try:
        load_dotenv()  # Ladda .env-fil automatiskt
    except (PermissionError, IOError, OSError):
        # Ignorera permission-fel (t.ex. i sandbox)
        pass
except ImportError:
    pass  # python-dotenv är valfritt

# Konfigurera logging INNAN andra moduler importeras
# (förhindrar att undermodulernas basicConfig tar företräde)
Path('logs').mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/orchestrator.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Importera scraping-moduler (EFTER logging-setup)
from src.scraper_improved import scrape_games_by_date, save_games
from src.scrape_game_details_improved import scrape_game_details, GameDetails
from src.storage import HybridStorage, create_minio_storage_from_env

# SSL context
ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE


class ScrapingOrchestrator:
    """Orchestrator för att koordinera scraping av flera datum"""
    
    def __init__(
        self, 
        data_dir: Path = Path("data/scraped"),
        storage: Optional[HybridStorage] = None
    ):
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.checkpoint_file = data_dir / "checkpoint.json"
        self.scraped_games_file = data_dir / "scraped_game_ids.json"
        # Rate limiting med stealth (mänsklig-liknande delays)
        try:
            from src.stealth_config import StealthRateLimiter, human_like_delay
            self.rate_limiter = StealthRateLimiter(pattern="normal")
            self.use_stealth = True
        except ImportError:
            self.rate_limit_delay = 1.5  # Sekunder mellan requests (lite längre)
            self.use_stealth = False
        
        # Storage (MinIO + lokal backup)
        self.storage = storage
        if self.storage is None:
            # Skapa storage från miljövariabler om tillgängligt
            minio = create_minio_storage_from_env()
            self.storage = HybridStorage(minio_storage=minio, local_dir=data_dir)
        
        # Ladda checkpoint och scraped games
        self.checkpoint = self.load_checkpoint()
        self.scraped_game_ids: Set[str] = self.load_scraped_game_ids()
    
    def load_checkpoint(self) -> Dict:
        """Ladda checkpoint för återupptagning"""
        # Försök ladda från MinIO först
        if self.storage and self.storage.minio:
            checkpoint = self.storage.minio.load_checkpoint()
            if checkpoint:
                return checkpoint
        
        # Fallback till lokal fil
        if self.checkpoint_file.exists():
            try:
                with open(self.checkpoint_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                pass
        return {
            "last_scraped_date": None,
            "last_successful_date": None,
            "failed_dates": [],
            "total_games_scraped": 0,
            "start_date": None,
            "end_date": None
        }
    
    def save_checkpoint(self):
        """Spara checkpoint"""
        # Spara lokalt (backup)
        with open(self.checkpoint_file, 'w', encoding='utf-8') as f:
            json.dump(self.checkpoint, f, indent=2, ensure_ascii=False)
        
        # Spara till MinIO om tillgängligt
        if self.storage and self.storage.minio:
            self.storage.minio.save_checkpoint(self.checkpoint)
    
    def load_scraped_game_ids(self) -> Set[str]:
        """Ladda lista över redan scrapade match-ID:n"""
        # Försök ladda från MinIO först
        if self.storage and self.storage.minio:
            game_ids = self.storage.minio.load_scraped_game_ids()
            if game_ids:
                return set(game_ids)
        
        # Fallback till lokal fil
        if self.scraped_games_file.exists():
            try:
                with open(self.scraped_games_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return set(data.get("game_ids", []))
            except:
                pass
        return set()
    
    def save_scraped_game_ids(self):
        """Spara lista över scrapade match-ID:n"""
        data = {
            "timestamp": datetime.now().isoformat(),
            "count": len(self.scraped_game_ids),
            "game_ids": sorted(list(self.scraped_game_ids))
        }
        
        # Spara lokalt (backup)
        with open(self.scraped_games_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        # Spara till MinIO om tillgängligt
        if self.storage and self.storage.minio:
            self.storage.minio.save_scraped_game_ids(data["game_ids"])
    
    def get_date_range(self, start_date: str, end_date: str) -> List[str]:
        """Generera lista med datum mellan start och end"""
        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")
        dates = []
        current = start
        while current <= end:
            dates.append(current.strftime("%Y-%m-%d"))
            current += timedelta(days=1)
        return dates
    
    def scrape_date(self, date: str, fetch_details: bool = False) -> Dict:
        """
        Scrapa matcher för ett specifikt datum
        
        Args:
            date: Datum i format YYYY-MM-DD
            fetch_details: Om True, hämta även match-detaljer
        
        Returns:
            Dict med resultat
        """
        result = {
            "date": date,
            "success": False,
            "games_found": 0,
            "games_scraped": 0,
            "new_games": 0,
            "errors": []
        }
        
        try:
            # Kontrollera om datumet redan finns i S3 (om S3-only storage)
            if self.storage and getattr(self.storage, 's3_only', False) and self.storage.minio:
                object_name = f"raw/games/{date}.json"
                if self.storage.minio.object_exists(object_name):
                    logger.info(f"Datum {date} finns redan i S3, hoppar över")
                    result["success"] = True
                    result["games_found"] = 0
                    return result
            
            # Logga men inte printa om inga matcher (för renare output)
            logger.info(f"Scrapar datum: {date}")
            # Print kommer efter vi vet om det finns matcher
            games = scrape_games_by_date(date)
            
            result["games_found"] = len(games) if games else 0
            
            if not games:
                # Inga matcher - men spara ändå tom match-lista för att markera att datumet är kontrollerat
                logger.info(f"Inga matcher hittades för {date}")
                games = []  # Tom lista
                result["success"] = True  # Inga matcher är inte ett fel
            else:
                print(f"📅 {date}: ✅ {len(games)} matcher")
            
            # Spara matchlista ALLTID (även om tom) - markerar att datumet är kontrollerat
            # Lokal backup (endast om inte s3_only)
            if not (self.storage and getattr(self.storage, 's3_only', False)):
                output_file = self.data_dir / f"games_{date}.json"
                save_games(games, output_file)
            
            # Spara till MinIO om tillgängligt (alltid, även tomma listor)
            if self.storage:
                games_dict = [g.to_dict() for g in games] if games else []
                self.storage.save_games(games_dict, date)
            
            # Filtrera matcher för detalj-scraping:
            # 1. Måste ha game_id
            # 2. Måste ha resultat (spelad match, inte framtida)
            # 3. Inte redan scrapad (för att undvika dubbler)
            games_to_scrape = [
                g for g in games 
                if g.game_id 
                and g.result  # Endast matcher med resultat (spelade matcher)
                and g.game_id not in self.scraped_game_ids
            ]
            result["new_games"] = len(games_to_scrape)
            
            if games_to_scrape:
                print(f"   📊 {len(games_to_scrape)} nya matcher att scrapa (med resultat)")
            else:
                # Räkna matcher utan resultat
                games_without_result = [g for g in games if g.game_id and not g.result]
                if games_without_result:
                    print(f"   ℹ️  {len(games_without_result)} matcher utan resultat (hoppas över)")
                else:
                    print(f"   ℹ️  Alla matcher redan scrapade")
            
            # Hämta match-detaljer om begärt
            if fetch_details:
                # Skapa details_dir endast om inte s3_only
                if self.storage and not getattr(self.storage, 's3_only', False):
                    details_dir = self.data_dir / "game_details"
                    details_dir.mkdir(parents=True, exist_ok=True)
                else:
                    details_dir = None
                
                for game in games_to_scrape:
                        try:
                            print(f"   🔍 Hämtar detaljer för match {game.game_id}...")
                            details = scrape_game_details(game.game_id, storage=self.storage)
                            
                            if details:
                                details_dict = details.to_dict()
                                
                                # Spara lokalt endast om inte s3_only
                                if details_dir:
                                    details_file = details_dir / f"game_{game.game_id}.json"
                                    with open(details_file, 'w', encoding='utf-8') as f:
                                        json.dump(details_dict, f, indent=2, ensure_ascii=False)
                                
                                # Spara till MinIO om tillgängligt
                                if self.storage:
                                    self.storage.save_game_details(game.game_id, details_dict)
                                
                                self.scraped_game_ids.add(game.game_id)
                                result["games_scraped"] += 1
                            
                            # Använd stealth delay (mänsklig-liknande)
                            if self.use_stealth:
                                self.rate_limiter.wait()
                            else:
                                time.sleep(self.rate_limit_delay)
                        except Exception as e:
                            error_msg = f"Fel vid hämtning av match {game.game_id}: {e}"
                            print(f"   ❌ {error_msg}")
                            result["errors"].append(error_msg)
            
            # Uppdatera scraped game IDs
            for game in games:
                if game.game_id:
                    self.scraped_game_ids.add(game.game_id)
            
            result["success"] = True
            self.checkpoint["last_successful_date"] = date
            self.checkpoint["total_games_scraped"] += len(games)
            
        except Exception as e:
            error_msg = f"Fel vid scraping av {date}: {e}"
            logger.error(error_msg, exc_info=True)
            print(f"   ❌ {error_msg}")
            result["errors"].append(error_msg)
            result["success"] = False
            if date not in self.checkpoint.get("failed_dates", []):
                self.checkpoint.setdefault("failed_dates", []).append(date)
        
        # Spara checkpoint och scraped game IDs
        self.checkpoint["last_scraped_date"] = date
        self.save_checkpoint()
        self.save_scraped_game_ids()
        
        # Rate limiting med stealth (mänsklig-liknande delay)
        if self.use_stealth:
            self.rate_limiter.wait()
        else:
            time.sleep(self.rate_limit_delay)
        
        return result
    
    def scrape_date_range(
        self, 
        start_date: str, 
        end_date: str, 
        fetch_details: bool = False,
        resume: bool = True
    ) -> Dict:
        """
        Scrapa matcher för ett datumintervall
        
        Args:
            start_date: Startdatum (YYYY-MM-DD)
            end_date: Slutdatum (YYYY-MM-DD)
            fetch_details: Om True, hämta även match-detaljer
            resume: Om True, återuppta från checkpoint
        
        Returns:
            Dict med sammanfattning
        """
        dates = self.get_date_range(start_date, end_date)
        
        # Återuppta från checkpoint om begärt
        if resume and self.checkpoint.get("last_scraped_date"):
            last_date = self.checkpoint["last_scraped_date"]
            if last_date in dates:
                idx = dates.index(last_date)
                dates = dates[idx + 1:]  # Börja från nästa datum
                print(f"🔄 Återupptar från {last_date}, {len(dates)} datum kvar")
        
        print(f"\n{'='*70}")
        print(f"Scrapar datumintervall: {start_date} till {end_date}")
        print(f"Totalt {len(dates)} datum att scrapa")
        if fetch_details:
            print(f"⚠️  Med match-detaljer (långsammare)")
        print(f"{'='*70}\n")
        
        results = []
        successful = 0
        failed = 0
        start_time = time.time()
        
        for i, date in enumerate(dates, 1):
            print(f"[{i}/{len(dates)}] ", end="", flush=True)
            result = self.scrape_date(date, fetch_details)
            results.append(result)
            
            if result["success"]:
                successful += 1
            else:
                failed += 1
            
            # Visa progress var 50:e datum
            if i % 50 == 0 or i == len(dates):
                elapsed = time.time() - start_time
                rate = i / elapsed if elapsed > 0 else 0
                remaining = len(dates) - i
                eta_seconds = remaining / rate if rate > 0 else 0
                eta_minutes = eta_seconds / 60
                print(f"\n   📊 Progress: {i}/{len(dates)} ({i*100//len(dates)}%) | "
                      f"Hastighet: {rate:.1f} datum/s | "
                      f"ETA: {eta_minutes:.1f} min", flush=True)
        
        # Sammanfattning
        summary = {
            "start_date": start_date,
            "end_date": end_date,
            "total_dates": len(dates),
            "successful_dates": successful,
            "failed_dates": failed,
            "total_games_found": sum(r["games_found"] for r in results),
            "total_new_games": sum(r["new_games"] for r in results),
            "total_games_scraped": sum(r["games_scraped"] for r in results),
            "results": results
        }
        
        # Spara sammanfattning
        summary_file = self.data_dir / f"scraping_summary_{start_date}_{end_date}.json"
        with open(summary_file, 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
        
        print(f"\n{'='*70}")
        print("SAMMANFATTNING")
        print(f"{'='*70}")
        print(f"✅ Framgångsrika datum: {successful}/{len(dates)}")
        print(f"❌ Misslyckade datum: {failed}/{len(dates)}")
        print(f"📊 Totalt matcher hittade: {summary['total_games_found']}")
        print(f"🆕 Nya matcher: {summary['total_new_games']}")
        print(f"💾 Match-detaljer scrapade: {summary['total_games_scraped']}")
        print(f"{'='*70}\n")
        
        return summary
    
    def scrape_historical_data(
        self,
        start_date: str,
        end_date: Optional[str] = None,
        fetch_details: bool = False
    ) -> Dict:
        """
        Scrapa historisk data
        
        Args:
            start_date: Startdatum (YYYY-MM-DD) - t.ex. "2020-01-01"
            end_date: Slutdatum (YYYY-MM-DD) - om None, använd idag
            fetch_details: Om True, hämta även match-detaljer
        
        Returns:
            Dict med sammanfattning
        """
        if end_date is None:
            end_date = datetime.now().strftime("%Y-%m-%d")
        
        print(f"\n{'='*70}")
        print("HISTORISK DATA SCRAPING")
        print(f"{'='*70}")
        print(f"Startdatum: {start_date}")
        print(f"Slutdatum: {end_date}")
        print(f"Hämta detaljer: {'Ja' if fetch_details else 'Nej'}")
        print(f"{'='*70}\n")
        
        self.checkpoint["start_date"] = start_date
        self.checkpoint["end_date"] = end_date
        self.save_checkpoint()
        
        return self.scrape_date_range(start_date, end_date, fetch_details, resume=True)
    
    def scrape_daily(self, fetch_details: bool = False) -> Dict:
        """
        Scrapa dagens matcher (för daglig körning)
        
        Args:
            fetch_details: Om True, hämta även match-detaljer
        
        Returns:
            Dict med resultat
        """
        today = datetime.now().strftime("%Y-%m-%d")
        
        print(f"\n{'='*70}")
        print("DAGLIG SCRAPING")
        print(f"{'='*70}")
        print(f"Datum: {today}")
        print(f"{'='*70}\n")
        
        result = self.scrape_date(today, fetch_details)
        
        return {
            "date": today,
            "success": result["success"],
            "games_found": result["games_found"],
            "new_games": result["new_games"],
            "games_scraped": result["games_scraped"],
            "errors": result["errors"]
        }
    
    def get_statistics(self) -> Dict:
        """Hämta statistik över scrapad data"""
        stats = {
            "total_scraped_games": len(self.scraped_game_ids),
            "last_scraped_date": self.checkpoint.get("last_scraped_date"),
            "last_successful_date": self.checkpoint.get("last_successful_date"),
            "total_games_scraped": self.checkpoint.get("total_games_scraped", 0),
            "failed_dates_count": len(self.checkpoint.get("failed_dates", [])),
            "failed_dates": self.checkpoint.get("failed_dates", [])
        }
        return stats


def main():
    """Exempel på användning"""
    orchestrator = ScrapingOrchestrator()
    
    import sys
    
    if len(sys.argv) > 1:
        command = sys.argv[1]
        
        if command == "daily":
            # Daglig scraping (dagens datum i UTC)
            result = orchestrator.scrape_daily(fetch_details=True)
            print(f"\n✅ Daglig scraping klar: {result['games_found']} matcher")

        elif command == "yesterday":
            # Scrapa gårdagens datum (användbart för CI som kör tidigt på morgonen)
            yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
            print(f"\n{'='*70}")
            print("GÅRDAG SCRAPING")
            print(f"{'='*70}")
            print(f"Datum: {yesterday}")
            print(f"{'='*70}\n")
            result = orchestrator.scrape_date(yesterday, fetch_details=True)
            print(f"\n✅ Scraping klar: {result['games_found']} matcher för {yesterday}")

        elif command == "historical":
            # Historisk data
            start_date = sys.argv[2] if len(sys.argv) > 2 else "2024-01-01"
            end_date = sys.argv[3] if len(sys.argv) > 3 else None
            fetch_details = "--details" in sys.argv
            
            orchestrator.scrape_historical_data(start_date, end_date, fetch_details)
        
        elif command == "range":
            # Specifikt datumintervall
            start_date = sys.argv[2]
            end_date = sys.argv[3]
            fetch_details = "--details" in sys.argv
            resume = "--no-resume" not in sys.argv

            orchestrator.scrape_date_range(start_date, end_date, fetch_details, resume=resume)
        
        elif command == "stats":
            # Statistik
            stats = orchestrator.get_statistics()
            print("\n📊 STATISTIK")
            print("="*70)
            for key, value in stats.items():
                print(f"{key}: {value}")
        
        else:
            print("Okänt kommando. Använd: daily, historical, range, eller stats")
    else:
        # Interaktivt läge
        print("="*70)
        print("Swehockey Scraping Orchestrator")
        print("="*70)
        print("\nAnvändning:")
        print("  python orchestrator.py daily                    # Scrapa idag")
        print("  python orchestrator.py historical [start] [end] # Historisk data")
        print("  python orchestrator.py range [start] [end]      # Specifikt intervall")
        print("  python orchestrator.py stats                     # Statistik")
        print("\nExempel:")
        print("  python orchestrator.py daily")
        print("  python orchestrator.py historical 2024-01-01")
        print("  python orchestrator.py range 2024-12-01 2024-12-31 --details")
        print("="*70)


if __name__ == "__main__":
    main()

