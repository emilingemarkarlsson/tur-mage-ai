# Tur Mage AI Project

Detta är ett Mage AI-projekt för databehandling och pipeline-utveckling.

## Översikt

Mage AI är ett modernt verktyg för att bygga, köra och hantera data pipelines. Detta projekt innehåller pipelines och konfigurationer för våra dataprocesser.

## Kom igång

### Förutsättningar

- Docker och Docker Compose
- Git

### Installation och start

1. Klona repositoriet:
   ```bash
   git clone <repository-url>
   cd tur-mage
   ```

2. Starta tjänsterna med Docker Compose:
   ```bash
   docker-compose up -d
   ```

3. Öppna Mage AI i din webbläsare:
   ```
   http://localhost:6789
   ```

### Tjänster

- **Mage AI**: Tillgänglig på port 6789
- **PostgreSQL**: Databas tillgänglig på port 5433

### Projektstruktur

- `default_repo/`: Mage AI-projekt med pipelines, data loaders, transformers och exporters
- `docker-compose.yml`: Docker Compose-konfiguration
- `Dockerfile`: Anpassad Docker-image för projektet
- `requirements.txt`: Python-dependencies
- `.env`: Miljövariabler (ignoreras av Git)

### Development

För att utveckla nya pipelines:

1. Öppna Mage AI-gränssnittet på http://localhost:6789
2. Skapa nya pipelines, data loaders, transformers eller exporters
3. Koden sparas automatiskt i `default_repo/`-mappen
4. Committa dina ändringar till Git

### Stopp av tjänster

```bash
docker-compose down
```

För att också ta bort volymer:
```bash
docker-compose down -v
```

## Bidrag

1. Skapa en feature branch
2. Gör dina ändringar
3. Committa med tydliga meddelanden
4. Skapa en pull request

## Licens

[Lägg till licensinformation här]
