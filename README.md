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
Om du använder den här repots uppsatta default-owner, logga in med: `admin@example.com` / `admin`.  
Källa: Mage Quickstart-dokumentationen.  

## Verifiera att projektet sparas lokalt

När du skapar pipelines/blocks i Mage skrivs de som filer i `mage_project/` lokalt.
Ett snabbt sätt att verifiera:

1. Skapa en ny pipeline i UI
2. Kontrollera att en ny mapp/fil dyker upp under `mage_project/`

Om du raderar containern men behåller mappen `mage_project/` så ligger allt kvar.

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
