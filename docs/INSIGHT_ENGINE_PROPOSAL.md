# Insight Engine – Analys och förslag

**Mål:** Bygga en deterministisk analysmotor som kontinuerligt identifierar prestationsmönster och skickar proaktiva insikter via Slack. LLM används endast för formulering. Kärnan (Insight Engine) blir din IP och konkurrensfördel.

---

## 1. Arkitekturöversikt

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  DATA (Gold DuckDB)                                                          │
│  games, game_players, player_game_stats, team_game_stats, edge_*, standings   │
└─────────────────────────────────────┬───────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  INSIGHT ENGINE (deterministisk – din IP)                                     │
│  • Mönsteridentifiering via regler + statistik                               │
│  • Konfigurerbara trösklar                                                   │
│  • Modulära detectors (hot_streak, breakout, goalie_trend, …)               │
│  • Output: strukturerade Insight-objekt (typ, entity, mått, värden)          │
└─────────────────────────────────────┬───────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  LLM FORMULATOR (valfritt)                                                   │
│  • Tar strukturerad Insight → genererar naturligt språk                       │
│  • Enbart presentation, ingen analyslogik                                    │
└─────────────────────────────────────┬───────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  SLACK NOTIFIER                                                              │
│  • Skickar insikter till kanal(er)                                           │
│  • Kan använda LLM-text eller template-baserad text                          │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Kärnprincip:** Insight Engine är helt deterministisk. Samma data ger samma insikter. LLM används bara för att översätta insikter till läsbar text.

---

## 2. Förslag på mappstruktur (Mage + Git)

```
mage_project/
├── insight_engine/              # Din IP – modulär Insight Engine
│   ├── __init__.py
│   ├── models.py                # Insight, InsightType, datastrukturer
│   ├── config.py                # Läs trösklar från YAML/env
│   ├── engine.py                # Kör alla detectors, returnerar lista av Insight
│   ├── detectors/               # En fil per mönstertyp
│   │   ├── __init__.py
│   │   ├── base.py              # BaseDetector-interface
│   │   ├── team_points_streak.py
│   │   ├── player_breakout.py
│   │   └── goalie_save_pct_trend.py
│   ├── formatters/              # LLM eller template
│   │   ├── __init__.py
│   │   ├── template.py          # Enkel template utan LLM
│   │   └── llm_formatter.py     # OpenAI/Anthropic för naturligt språk
│   └── notifiers/
│       ├── __init__.py
│       └── slack.py
├── data_loaders/
├── transformers/
├── data_exporters/
├── pipelines/
│   ├── dimensions_pipeline/
│   ├── seasonal_stats_pipeline/
│   ├── games_pipeline/
│   └── insights_pipeline/       # NY – kör efter data-pipelines
│       └── ...
└── io_config.yaml

insight_engine_config/            # Konfiguration (git-friendly, ingen hemlig data)
├── detectors.yaml               # Vilka detectors, trösklar
└── slack_channels.yaml          # Kanalmappning (kan vara .example + .env)

tests/
├── test_insight_engine/
│   ├── test_team_points_streak.py
│   └── test_player_breakout.py
└── ...
```

Allt i samma repo – `insight_engine` blir en ren Python-modul som Mage importerar. Versioneras i git tillsammans med pipelines.

---

## 3. Insight Engine – API och moduler

### 3.1 Datamodell (models.py)

```python
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

class InsightType(str, Enum):
    TEAM_POINTS_STREAK = "team_points_streak"
    PLAYER_BREAKOUT = "player_breakout"
    GOALIE_SAVE_PCT_TREND = "goalie_save_pct_trend"
    # Utöka vid behov

@dataclass
class Insight:
    type: InsightType
    entity_id: str          # player_id, team_abbr, etc.
    entity_name: str        # "Auston Matthews", "TOR"
    metric: str             # "points", "save_pct"
    value: float
    context: dict           # t.ex. {"last_n_games": 5, "baseline_avg": 0.8}
    significance: float     # 0–1, hur "viktig" insikten är
    raw_message: str        # Strukturerad beskrivning (för template/LLM)
```

### 3.2 Detector-interface (detectors/base.py)

```python
from abc import ABC, abstractmethod
from typing import List
import duckdb
from ..models import Insight

class BaseDetector(ABC):
    """Alla detectors implementerar detta."""
    @abstractmethod
    def run(self, conn: duckdb.DuckDBPyConnection) -> List[Insight]:
        pass
```

### 3.3 Exempel: TeamPointsStreak (starta smått)

Med begränsad data (2025 + del av 2026) fungerar **glidande medel** och **streak** bra:

```python
# detectors/team_points_streak.py
# Regel: Lag med ≥3 poäng i senaste 3 matcher (2 pts/avg per match) = hot streak
```

**SQL som utgångspunkt** (från TREND_ANALYSIS.md):

```sql
WITH team_games AS (
  SELECT game_date, team_abbr,
    CASE WHEN is_home THEN goals_for ELSE goals_against END AS goals_for,
    CASE WHEN is_home THEN goals_against ELSE goals_for END AS goals_against,
    CASE WHEN is_home THEN home_points ELSE away_points END AS pts
  FROM team_game_stats
  WHERE game_date >= date_trunc('month', current_date) - interval '3 month'
)
SELECT team_abbr, game_date, pts,
  AVG(pts) OVER (PARTITION BY team_abbr ORDER BY game_date ROWS 4 PRECEDING) AS pts_rolling_5
FROM team_games
ORDER BY team_abbr, game_date;
```

Detectorn kör liknande logik, hittar lag där `pts_rolling_5 > tröskel` (t.ex. 1.8), och returnerar `Insight`.

---

## 4. Tre detectors att börja med (litet databas)

| Detector | Data | Regel (förenklad) | Min data |
|----------|------|-------------------|----------|
| **TeamPointsStreak** | team_game_stats | Senaste 5 matcher: poäng/match > 1.6 | ~10 matcher/lag |
| **PlayerBreakout** | player_game_stats | Senaste 5 > 2× säsongsmedel (points/game) | ~10 matcher |
| **GoalieSavePctTrend** | game_players (G) | Senaste 3: save_pct > 0.92 | ~3 matcher |

Med 2025 + 2026 har du flera hundra matcher – mer än tillräckligt för dessa tre.

---

## 5. Mage-insats: insights_pipeline

### 5.1 Pipeline-flöde

| Steg | Block | Beskrivning |
|------|-------|-------------|
| 1 | **load_from_gold** | Läser Gold DuckDB (lokalt eller S3), returnerar connection/DataFrame |
| 2 | **run_insight_engine** | Importerar `insight_engine.engine.run()`, returnerar `List[Insight]` |
| 3 | **format_insights** | Template eller LLM: `Insight` → str (Slack-meddelande) |
| 4 | **send_to_slack** | Skickar till Slack via webhook eller API |

### 5.2 Trigger

- **Alternativ A:** Mage Schedule som kör efter `games_pipeline` (t.ex. 06:00 varje dag efter att data uppdaterats).
- **Alternativ B:** Mage Trigger: när `games_pipeline` är klar → starta `insights_pipeline`.
- **Alternativ C:** Extern (cron/n8n): `docker exec ... mage run insights_pipeline`.

### 5.3 Beroenden

- **Inget LLM krävs för MVP** – använd template-formatering. LLM kan läggas till senare.
- **Slack:** Webhook URL i `.env` (`SLACK_INSIGHTS_WEBHOOK_URL`). Inga extra Mage-blocks för Slack – vanlig Python (`requests.post`).

---

## 6. Git och versionshantering

| Aspekt | Förslag |
|-------|---------|
| **Kod** | Allt under `mage_project/insight_engine/` – committas som vanlig Python |
| **Config** | `insight_engine_config/detectors.yaml` – trösklar, aktiverade detectors |
| **Secrets** | `.env` – `SLACK_INSIGHTS_WEBHOOK_URL`, eventuellt `OPENAI_API_KEY` (om LLM) |
| **Tester** | `tests/test_insight_engine/` – unit-tester per detector, mockad DuckDB |
| **CI** | `pytest tests/test_insight_engine` vid push (valfritt men rekommenderat) |

**Determinism:** Varje detector ska ha tester som verifierar att samma indata ger samma insikter.

---

## 7. Implementationsplan – starta smått

### Fas 1: Grund (1–2 dagar)

1. Skapa `mage_project/insight_engine/` med `models.py`, `config.py`, `engine.py`.
2. Implementera **en** detector: `TeamPointsStreak` (använd `team_game_stats`).
3. Lägg till `insight_engine_config/detectors.yaml` med tröskel (t.ex. `min_streak_games: 3`, `min_pts_per_game: 1.6`).
4. Skriv ett enkelt script: `python -m insight_engine.cli` som läser Gold lokalt, kör engine och skriver insikter till stdout (ingen Slack ännu).
5. Lägg till `tests/test_insight_engine/test_team_points_streak.py` med mockad DuckDB.

### Fas 2: Mage + Slack (1 dag)

1. Skapa `insights_pipeline` i Mage med blocks: load_from_gold, run_insight_engine, format_insights (template), send_to_slack.
2. `load_from_gold`: använd `duckdb.connect()` mot `data_lake/gold/nhl.duckdb` (eller S3-sökväg från env).
3. `send_to_slack`: `requests.post(webhook_url, json={"text": message})`.
4. Sätt `SLACK_INSIGHTS_WEBHOOK_URL` i `.env` och testa manuell körning i Mage UI.

### Fas 3: Fler detectors + LLM (valfritt)

1. Lägg till `PlayerBreakout` och `GoalieSavePctTrend`.
2. Om du vill ha LLM-formulering: skapa `formatters/llm_formatter.py` som tar `Insight` och anropar OpenAI/Anthropic för att generera en kort mening.
3. Koppla LLM-formateraren i `format_insights`-blocket (endast när `USE_LLM_FORMATTER=true` eller liknande).

### Fas 4: Schemaläggning

1. Mage Schedule: `insights_pipeline` dagligen kl 07:00 (efter att games_pipeline kört).
2. Eller: n8n/cron som triggar `mage run insights_pipeline` efter datauppdatering.

---

## 8. Konfiguration – detectors.yaml (exempel)

```yaml
# insight_engine_config/detectors.yaml
enabled:
  - team_points_streak
  - player_breakout
  - goalie_save_pct_trend

team_points_streak:
  min_streak_games: 3
  min_pts_per_game: 1.6
  lookback_days: 90

player_breakout:
  lookback_games: 5
  multiplier_vs_baseline: 2.0
  min_games_played: 3

goalie_save_pct_trend:
  min_games: 3
  min_save_pct: 0.92
  lookback_days: 30
```

---

## 9. Sammanfattning

| Komponent | Ansvar | IP / sekretess |
|-----------|--------|----------------|
| **Insight Engine** | Determinisk mönsteridentifiering | Din IP – logiken, trösklarna, detectors |
| **LLM formatter** | Formulera insikter i naturligt språk | Generisk – kan bytas (OpenAI, Anthropic, lokalt) |
| **Slack notifier** | Leveranskanal | Standard integration |
| **Mage pipelines** | Orchestrering, körordning | Mage OSS – öppen struktur |

**Startpunkt:** Implementera `TeamPointsStreak`-detectorn och ett enkelt `run_insights.py`-script som läser Gold, kör engine och skriver ut insikter. När det fungerar – koppla in Mage-pipeline och Slack. Utöka sedan med fler detectors och LLM-formatering när behovet finns.

**Teknisk design:** För full arkitektur, modulstruktur, Pydantic-modeller, plugin-pattern och kostnadseffektivitet, se **[INSIGHT_ENGINE_ARCHITECTURE.md](INSIGHT_ENGINE_ARCHITECTURE.md)**.

**Data dictionary:** Beskrivningar av tabeller och kolumner finns i **`documentation/DATA_DICTIONARY.yaml`**. Insight Engine använder detta för att veta vilka kolumner som finns och vad de betyder. Kör `python scripts/validate_data_dictionary.py` för att validera mot MotherDuck och generera `DATA_DICTIONARY.md`.

---

## 10. Leverans: validering + bloggpublicering

Du vill få insikter till dig för att (1) validera dem och (2) snabbt kunna posta dem som blogginlägg på din hockey analytics-site. Här är ett konkret förslag.

### 10.1 Två kanaler – varje körning

| Kanal | Syfte | Format |
|-------|-------|--------|
| **Slack** | Validering, snabb feedback | Kort meddelande med lista av insikter, länk till full export |
| **Markdown-export** | Bloggpublicering | Klar Markdown-fil du kan kopiera in i din CMS |

### 10.2 Flöde per körning

```
insights_pipeline körs
       │
       ├──► Slack: "3 nya insikter idag. [Öppna export]"
       │
       └──► Filer skrivs till insight_engine_output/
            ├── 2026-02-24.md          (blog-ready Markdown)
            ├── 2026-02-24.json        (strukturerad data, backup)
            └── 2026-02-24-blog-draft.md  (optional: med intro, signatur)
```

### 10.3 Blog-ready Markdown-format

Varje körning skriver `insight_engine_output/YYYY-MM-DD.md` med innehåll i stil:

```markdown
# NHL-insikter – 24 februari 2026

*Genererat av Insight Engine. Data: senaste matcher fram till 2026-02-22.*

---

## Lagtrender

**Toronto Maple Leafs** har vunnit 2,0 poäng/match i snitt de senaste 5 matcherna (över säsongsmedel 1,4). Formtopp.

**Colorado Avalanche** – tre raka segrar. Poäng per match stigit till 2,3.

---

## Spelare att följa

**Auston Matthews** (TOR) – 8 poäng på 5 matcher (säsongsmedel: 1,2/match). Upptrappning.

---

## Målvakter

**Igor Sheshterkin** (NYR) – 94,2 % räddningsprocent senaste 3 matcher.
```

Du öppnar filen, kopierar innehållet och klistrar in i din blogg-CMS. Klart.

### 10.4 Utökad variant: blog-draft med intro

Om du vill ha ett färdigt "draft"-inlägg med intro kan du skapa `2026-02-24-blog-draft.md`:

```markdown
---
title: "NHL-insikter vecka 8: Toronto i form, Matthews exploderar"
date: 2026-02-24
tags: [nhl, insights, analytics]
---

Här är veckans automatiska insikter från vår analysmotor – baserat på matchdata fram till 22 februari.

## Lagtrender
...
```

LLM kan generera titel och intro om du vill – annars använder du en enkel template.

### 10.5 Var sparas exporten?

| Miljö | Sökväg | Synlig |
|-------|--------|--------|
| **Lokal** | `mage_project/insight_engine_output/` eller `./insight_engine_output/` | Direkt i filsystem |
| **Docker** | Volymmonterad: `.:/home/src` → `./insight_engine_output` finns lokalt | Ja, under projektrot |
| **S3** | `s3://bucket/nhl-analytics/insights/YYYY-MM-DD.md` | Ladda ner eller synka till lokal mapp |

**Rekommendation:** Skriv till lokal mapp som är monterad i Docker (`./insight_engine_output`). Då kan du öppna filen direkt efter körning. Lägg mappen i `.gitignore` så du inte committar genererade insikter.

### 10.6 Slack + länk till export

Slack-meddelandet kan innehålla:

- Antal insikter
- Kort lista (1 rad per insikt)
- Länk till filen (om du exponerar via enkel webbserver) eller instruktion: *"Filen finns i insight_engine_output/2026-02-24.md"*

Om du kör lokalt/Docker: öppna mappen i Cursor/Explorer – filen ligger där direkt.

### 10.7 Workflow för validering → blogg

1. **Kör** `insights_pipeline` (manuellt eller via schema).
2. **Slack** – du får notis och kan snabbt se om det ser vettigt ut.
3. **Öppna** `insight_engine_output/2026-02-24.md` – full text.
4. **Validera** – ta bort eller justera insikter som känns fel.
5. **Kopiera** – markera allt, klistra in i WordPress/Ghost/annat CMS.
6. **Publicera** – eller spara som utkast för redigering.

### 10.8 Framtida utökning: direkt till blogg-CMS

Om din site har API (WordPress REST, Ghost Admin API, etc.) kan du lägga till en **blog publisher** som skickar draft direkt:

- Block i pipeline: `publish_insights_to_blog`
- Skapar utkast via API med titel och Markdown-body
- Du godkänner och publicerar i CMS:s UI

Det kräver API-nycklar och lite integration – men fungerar bra när grunden med Markdown-export sitter.
