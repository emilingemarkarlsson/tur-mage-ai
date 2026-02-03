# Mage AI i Docker (med MinIO)

Detta repo är en "by the book"-setup för Mage OSS i Docker Compose med:
- ihållande volymer
- enkel uppgradering via version i `.env`
- MinIO/S3-konfiguration via extern endpoint
- `io_config.yaml` färdig för MinIO

## Snabbstart

1. Kopiera exempel-ENV:
   ```bash
   cp .env.example .env
   ```
2. Starta:
   ```bash
   docker compose up -d --build
   ```
3. Öppna Mage: `http://localhost:6789`

Standard-inlogg (Mage OSS): `admin` / `admin`. Byt lösenord direkt efter första inloggningen.  
Källa: Mage Quickstart-dokumentationen.  

## MinIO (externt)

Ange din externa MinIO‑endpoint i `.env` som `MINIO_ENDPOINT` och dina nycklar som `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`.
Mage kopplar då mot din befintliga MinIO.

## S3/MinIO-konfiguration (io_config.yaml)

`mage_project/io_config.yaml` använder variabler från `.env`:
- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`
- `AWS_REGION`
- `MINIO_ENDPOINT`

Mage stödjer MinIO genom att ange `AWS_ENDPOINT` i `io_config.yaml`.  
Källa: Mage S3-integrationsdokumentation (MinIO support).

## Uppgradera Mage

1. Uppdatera `MAGE_VERSION` i `.env`
2. Kör:
   ```bash
   docker compose pull
   docker compose up -d --build
   ```

## Git (valfritt men rekommenderat)

```bash
git init
git add .
git commit -m "Init Mage + MinIO docker setup"
```

## Referenser

- Mage Quickstart (Docker/Compose): https://docs.mage.ai/getting-started/setup
- Compose template: https://github.com/mage-ai/compose-quickstart
- S3/MinIO-konfiguration: https://docs.mage.ai/integrations/databases/S3
