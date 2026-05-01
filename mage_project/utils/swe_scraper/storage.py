"""
Storage layer för att spara data till MinIO (S3-kompatibel objektlagring)
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List
import os
import io

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

# MinIO är valfritt
try:
    from minio import Minio
    from minio.error import S3Error
    MINIO_AVAILABLE = True
except ImportError:
    MINIO_AVAILABLE = False
    Minio = None
    S3Error = Exception


class MinIOStorage:
    """Storage-klass för MinIO"""
    
    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket_name: str,
        secure: bool = True,
        region: Optional[str] = None
    ):
        """
        Initiera MinIO-klient
        
        Args:
            endpoint: MinIO endpoint (t.ex. "localhost:9000" eller "minio.example.com")
            access_key: Access key
            secret_key: Secret key
            bucket_name: Bucket-namn
            secure: Använd HTTPS (True) eller HTTP (False)
            region: Region (valfritt)
        """
        if not MINIO_AVAILABLE:
            raise ImportError("MinIO-biblioteket är inte installerat. Installera med: pip install minio")
        
        # Ta bort port från endpoint om secure=True (MinIO hanterar HTTPS automatiskt)
        if secure and ':' in endpoint:
            # För HTTPS, ta bort porten från endpoint
            endpoint = endpoint.split(':')[0]
        
        self.client = Minio(
            endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
            region=region
        )
        self.bucket_name = bucket_name
        self.endpoint = endpoint  # Spara för referens
        self._ensure_bucket()
    
    def _ensure_bucket(self):
        """Säkerställ att bucket finns"""
        try:
            if not self.client.bucket_exists(self.bucket_name):
                self.client.make_bucket(self.bucket_name)
                print(f"✅ Skapade bucket: {self.bucket_name}")
        except S3Error as e:
            print(f"❌ Fel vid skapande av bucket: {e}")
            raise
    
    def save_file(
        self,
        file_path: Path,
        object_name: str,
        content_type: Optional[str] = None
    ) -> bool:
        """
        Spara en fil till MinIO
        
        Args:
            file_path: Sökväg till filen att ladda upp
            object_name: Objektnamn i MinIO (t.ex. "raw/reports/1009803/file.pdf")
            content_type: Content-type (t.ex. "application/pdf"). Auto-detekteras om None
        
        Returns:
            True om lyckat, False annars
        """
        try:
            if not file_path.exists():
                print(f"⚠️  Filen finns inte: {file_path}")
                return False
            
            # Auto-detektera content-type baserat på filändelse
            if not content_type:
                if file_path.suffix.lower() == '.pdf':
                    content_type = 'application/pdf'
                elif file_path.suffix.lower() == '.json':
                    content_type = 'application/json'
                else:
                    content_type = 'application/octet-stream'
            
            file_size = file_path.stat().st_size
            
            with open(file_path, 'rb') as file_data:
                self.client.put_object(
                    self.bucket_name,
                    object_name,
                    file_data,
                    length=file_size,
                    content_type=content_type
                )
            
            return True
        except Exception as e:
            print(f"❌ Fel vid uppladdning av {file_path} till {object_name}: {e}")
            return False
    
    def save_json(
        self,
        data: Dict[str, Any],
        object_name: str,
        metadata: Optional[Dict[str, str]] = None
    ) -> bool:
        """
        Spara JSON-data till MinIO
        
        Args:
            data: Data att spara (dict)
            object_name: Objektnamn (t.ex. "raw/games/2024-12-27.json")
            metadata: Ytterligare metadata (valfritt)
        
        Returns:
            True om lyckat, False annars
        """
        try:
            json_str = json.dumps(data, indent=2, ensure_ascii=False)
            json_bytes = json_str.encode('utf-8')
            json_stream = io.BytesIO(json_bytes)
            
            # Metadata - endast använda om det finns custom metadata
            # content-type sätts via content_type-parametern istället
            meta = metadata or {}
            if not meta:
                meta = None
            
            self.client.put_object(
                self.bucket_name,
                object_name,
                json_stream,
                length=len(json_bytes),
                content_type='application/json',
                metadata=meta
            )
            
            return True
        except S3Error as e:
            print(f"❌ Fel vid sparande till MinIO: {e}")
            return False
    
    def load_json(self, object_name: str) -> Optional[Dict[str, Any]]:
        """
        Ladda JSON-data från MinIO
        
        Args:
            object_name: Objektnamn
        
        Returns:
            Data som dict, eller None vid fel
        """
        try:
            response = self.client.get_object(self.bucket_name, object_name)
            data = json.loads(response.read().decode('utf-8'))
            response.close()
            response.release_conn()
            return data
        except S3Error as e:
            print(f"❌ Fel vid laddning från MinIO: {e}")
            return None
    
    def save_games(self, games: List[Dict], date: str) -> bool:
        """
        Spara matchlista för ett datum
        
        Args:
            games: Lista med match-dicts
            date: Datum (YYYY-MM-DD)
        
        Returns:
            True om lyckat
        """
        data = {
            "timestamp": datetime.now().isoformat(),
            "date": date,
            "count": len(games),
            "games": games
        }
        
        object_name = f"raw/games/{date}.json"
        return self.save_json(data, object_name)
    
    def save_game_details(self, game_id: str, details: Dict) -> bool:
        """
        Spara match-detaljer
        
        Args:
            game_id: Match-ID
            details: Match-detaljer som dict
        
        Returns:
            True om lyckat
        """
        object_name = f"raw/game_details/{game_id}.json"
        return self.save_json(details, object_name)
    
    def save_checkpoint(self, checkpoint: Dict) -> bool:
        """Spara checkpoint"""
        object_name = "raw/checkpoint.json"
        return self.save_json(checkpoint, object_name)
    
    def load_checkpoint(self) -> Optional[Dict]:
        """Ladda checkpoint"""
        return self.load_json("raw/checkpoint.json")
    
    def save_scraped_game_ids(self, game_ids: List[str]) -> bool:
        """Spara lista över scrapade match-ID:n"""
        data = {
            "timestamp": datetime.now().isoformat(),
            "count": len(game_ids),
            "game_ids": sorted(game_ids)
        }
        object_name = "raw/scraped_game_ids.json"
        return self.save_json(data, object_name)
    
    def load_scraped_game_ids(self) -> List[str]:
        """Ladda lista över scrapade match-ID:n"""
        data = self.load_json("raw/scraped_game_ids.json")
        if data:
            return data.get("game_ids", [])
        return []
    
    def list_objects(self, prefix: str = "") -> List[str]:
        """
        Lista objekt med prefix
        
        Args:
            prefix: Prefix (t.ex. "raw/games/")
        
        Returns:
            Lista med objektnamn
        """
        try:
            objects = self.client.list_objects(
                self.bucket_name,
                prefix=prefix,
                recursive=True
            )
            return [obj.object_name for obj in objects]
        except S3Error as e:
            print(f"❌ Fel vid listning: {e}")
            return []
    
    def object_exists(self, object_name: str) -> bool:
        """Kontrollera om objekt finns"""
        try:
            self.client.stat_object(self.bucket_name, object_name)
            return True
        except S3Error:
            return False


class HybridStorage:
    """
    Hybrid storage som sparar både lokalt och i MinIO
    Användbart för backup och lokal utveckling
    """
    
    def __init__(
        self,
        minio_storage: Optional[MinIOStorage] = None,
        local_dir: Optional[Path] = None,
        s3_only: bool = False
    ):
        """
        Initiera hybrid storage
        
        Args:
            minio_storage: MinIO storage-instans (valfritt)
            local_dir: Lokal katalog för backup (None = ingen lokal lagring)
            s3_only: Om True, spara endast till S3 (ignorera local_dir)
        """
        self.minio = minio_storage
        self.s3_only = s3_only
        self.local_dir = local_dir
        if local_dir and not s3_only:
            self.local_dir.mkdir(parents=True, exist_ok=True)
    
    def save_games(self, games: List[Dict], date: str) -> bool:
        """Spara matchlista (både lokalt och i MinIO)"""
        # Spara lokalt om inte s3_only
        if not self.s3_only and self.local_dir:
            local_file = self.local_dir / f"games_{date}.json"
            with open(local_file, 'w', encoding='utf-8') as f:
                json.dump({
                    "timestamp": datetime.now().isoformat(),
                    "date": date,
                    "count": len(games),
                    "games": games
                }, f, indent=2, ensure_ascii=False)
        
        # Spara i MinIO om tillgängligt
        if self.minio:
            return self.minio.save_games(games, date)
        
        return True
    
    def save_game_details(self, game_id: str, details: Dict) -> bool:
        """Spara match-detaljer (både lokalt och i MinIO)"""
        # Spara lokalt om inte s3_only
        if not self.s3_only and self.local_dir:
            details_dir = self.local_dir / "game_details"
            details_dir.mkdir(parents=True, exist_ok=True)
            local_file = details_dir / f"game_{game_id}.json"
            with open(local_file, 'w', encoding='utf-8') as f:
                json.dump(details, f, indent=2, ensure_ascii=False)

        # Spara i MinIO om tillgängligt
        if self.minio:
            return self.minio.save_game_details(game_id, details)

        return True

    def save_report_pdf(self, game_id: str, filename: str, file_path: Path) -> bool:
        """Ladda upp PDF-rapport till S3. Returnerar True om lyckat."""
        if self.minio:
            object_name = f"raw/reports/{game_id}/{filename}"
            return self.minio.save_file(file_path, object_name, content_type='application/pdf')
        return False


def create_minio_storage_from_env() -> Optional[MinIOStorage]:
    """
    Skapa MinIO storage från miljövariabler
    
    Miljövariabler:
    - MINIO_ENDPOINT
    - MINIO_ACCESS_KEY
    - MINIO_SECRET_KEY
    - MINIO_BUCKET_NAME
    - MINIO_SECURE (valfritt, default: "true")
    - MINIO_REGION (valfritt, för S3-kompatibla tjänster som Hetzner)
    """
    endpoint = os.getenv("MINIO_ENDPOINT")
    access_key = os.getenv("MINIO_ACCESS_KEY")
    secret_key = os.getenv("MINIO_SECRET_KEY")
    bucket_name = os.getenv("MINIO_BUCKET_NAME") or os.getenv("MINIO_BUCKET")
    secure = os.getenv("MINIO_SECURE", "true").lower() == "true"
    region = os.getenv("MINIO_REGION")  # För S3-kompatibla tjänster som Hetzner
    
    if not all([endpoint, access_key, secret_key, bucket_name]):
        print("⚠️  MinIO miljövariabler saknas, använder endast lokal lagring")
        return None
    
    try:
        return MinIOStorage(
            endpoint=endpoint,
            access_key=access_key,
            secret_key=secret_key,
            bucket_name=bucket_name,
            secure=secure,
            region=region
        )
    except Exception as e:
        print(f"❌ Fel vid skapande av MinIO storage: {e}")
        return None
