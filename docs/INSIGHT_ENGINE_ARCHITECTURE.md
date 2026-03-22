# Insight Engine – Modern arkitektur och design

**Mål:** En välstrukturerad, kostnadseffektiv och extensibel motor som genererar insikter av hög kvalitet. Deterministisk, inga externa API-anrop i kärnan.

---

## 1. Arkitekturprinciper

| Princip | Betydelse |
|---------|-----------|
| **Deterministisk** | Samma data → samma insikter. Testbart, repeterbart, inga LLM-kostnader i detection |
| **Konfigurerbar** | Trösklar, aktiverade detectors, lookback-perioder – allt i YAML, ingen kodändring för att finjustera |
| **Plugin-baserad** | Nya detectors = ny fil som följer ett interface. Ingen ändring i kärnan |
| **Statistiskt rigorös** | Min sample size, jämför mot baseline, undvik noise som signal |
| **En query per typ** | Batch SQL – en fråga per detector istället för N anrop. DuckDB är extremt snabb |
| **Spårbar** | Varje insight vet vilken detector, vilken query, vilken config som genererade den |

---

## 2. Pipeline-faser

```
┌──────────────┐   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐
│ 1. CONTEXT   │ → │ 2. DETECT   │ → │ 3. SCORE     │ → │ 4. RANK      │ → │ 5. OUTPUT    │
│ Data + meta  │   │ Run detectors│   │ Significance │   │ Top-N, dedup │   │ Structured   │
└──────────────┘   └──────────────┘   └──────────────┘   └──────────────┘   └──────────────┘
```

1. **Context** – Ladda data, bestäm lookback-period, senaste matchdatum. En DuckDB-connection räcker.
2. **Detect** – Kör alla aktiverade detectors. Varje detector returnerar kandidater (raw findings).
3. **Score** – Beräkna significance (0–1) per kandidat. Styrka av avvikelse, sample size, recency.
4. **Rank** – Sortera, ta top-N, deduplicera (samma entity + typ inom X dagar = en).
5. **Output** – Strukturerade `Insight`-objekt, klara för formattering/Slack/export.

---

## 3. Modulär struktur (uppdaterad)

```
mage_project/insight_engine/
├── __init__.py
├── version.py                 # ENGINE_VERSION = "0.1.0"
│
├── core/                      # Kärnlogik – orkestrering
│   ├── __init__.py
│   ├── context.py            # RunContext: db_path, as_of_date, lookback_days
│   ├── engine.py             # run(context, config) → List[Insight]
│   ├── scorer.py             # Significance-scoring (optional, kan vara per-detector)
│   └── ranker.py             # Top-N, deduplication, prioritetsordning
│
├── models/                    # Datastrukturer (Pydantic för validering)
│   ├── __init__.py
│   ├── insight.py            # Insight, InsightType, InsightDirection
│   ├── detector_result.py    # RawFinding (innan score/rank)
│   └── context.py            # RunContext (om inte i core/)
│
├── detectors/                 # Plugin-mapp – en fil per mönstertyp
│   ├── __init__.py           # Registry: {"team_points_streak": TeamPointsStreakDetector}
│   ├── base.py               # BaseDetector-interface
│   ├── team_points_streak.py
│   ├── player_breakout.py
│   └── goalie_save_pct_trend.py
│
├── config/                    # Konfigurationsladdning
│   ├── __init__.py
│   ├── loader.py             # load_yaml, merge env overrides
│   └── schema.py             # Pydantic-modell för detectors.yaml
│
├── exporters/                 # Output-format (separat från formatters)
│   ├── __init__.py
│   ├── markdown.py           # Insight[] → Markdown-str
│   └── json_exporter.py      # Insight[] → JSON (för API/fil)
│
├── formatters/               # (Framtida) LLM-formulering
│   └── template.py           # Jinja2-template utan LLM
│
└── cli.py                     # python -m mage_project.insight_engine.cli
```

**Plugin-pattern:** I `detectors/__init__.py` registreras alla detectors. Engine läser `config.enabled` och instansierar bara de som ska köras.

---

## 4. Datamodeller (Pydantic v2)

### 4.1 Insight (output)

```python
# models/insight.py
from enum import Enum
from pydantic import BaseModel, Field
from datetime import date
from typing import Any

class InsightType(str, Enum):
    TEAM_POINTS_STREAK = "team_points_streak"
    PLAYER_BREAKOUT = "player_breakout"
    GOALIE_SAVE_PCT_TREND = "goalie_save_pct_trend"

class InsightDirection(str, Enum):
    POSITIVE = "positive"   # Hot streak, breakout
    NEGATIVE = "negative"   # Cold streak, slump
    NEUTRAL = "neutral"

class Insight(BaseModel):
    type: InsightType
    league_id: str = "nhl"      # "nhl", "shl", "liiga", ... – för multi-liga
    entity_id: str
    entity_name: str
    entity_type: str = "team" | "player" | "goalie"
    metric: str
    value: float
    direction: InsightDirection = InsightDirection.POSITIVE
    context: dict[str, Any] = Field(default_factory=dict)
    significance: float = Field(ge=0, le=1)
    as_of_date: date
    detector_id: str
    detector_version: str = "1.0"
    raw_message: str = ""
    sample_size: int = 0   # Antal matcher/data points som underlag
```

### 4.2 RunContext

```python
# core/context.py
from pydantic import BaseModel
from datetime import date
from pathlib import Path

class RunContext(BaseModel):
    db_path: str | Path
    as_of_date: date          # Senaste datum med data (t.ex. sista match)
    lookback_days: int = 90
    season: str | None = None  # t.ex. "20252026"
```

### 4.3 RawFinding (detector-output, innan score)

```python
# models/detector_result.py
from pydantic import BaseModel
from .insight import InsightType, InsightDirection

class RawFinding(BaseModel):
    """Utdata från en detector, innan scoring och ranking."""
    type: InsightType
    league_id: str = "nhl"
    entity_id: str
    entity_name: str
    entity_type: str
    metric: str
    value: float
    direction: InsightDirection
    context: dict
    raw_message: str
    sample_size: int
    # Significance beräknas i scorer eller i detectorn
    significance: float = 0.5

---

## 5. Detector-interface (modern)

```python
# detectors/base.py
from abc import ABC, abstractmethod
from typing import List
import duckdb

from ..models.detector_result import RawFinding
from ..core.context import RunContext
from ..config.schema import DetectorConfig

class BaseDetector(ABC):
    """Alla detectors implementerar detta. Konfiguration injiceras."""
    id: str  # t.ex. "team_points_streak"
    version: str = "1.0"

    @abstractmethod
    def run(
        self,
        conn: duckdb.DuckDBPyConnection,
        context: RunContext,
        config: DetectorConfig | None,
    ) -> List[RawFinding]:
        """Kör detection. Returnerar kandidater (raw findings)."""
        pass
```

**Fördelar:**
- En connection för alla – ingen reconnect per detector
- Context (as_of_date, lookback) delad – ingen duplicering
- Config per detector – trösklar från YAML

---

## 6. Effektivitet och kostnad

| Åtgärd | Implementering |
|--------|----------------|
| **Inga API-anrop** | All logik i Python + DuckDB. Noll kostnad per insikt |
| **En connection** | `duckdb.connect(db_path)` en gång, passas till alla detectors |
| **Batch-SQL** | Varje detector skriver en (eller få) SQL-frågor. DuckDB optimerar |
| **Lookback-begränsning** | `WHERE game_date >= ?` – bara relevanta rader |
| **Top-N** | Ranker tar max N insikter per typ – undvik spam |
| **Deduplication** | Samma entity + typ inom 7 dagar → behåll bara senaste |
| **Caching (framtida)** | Om `as_of_date` + data unchanged → cache result (optional) |

---

## 7. Statistisk rigor

| Princip | Exempel |
|--------|--------|
| **Min sample size** | PlayerBreakout: minst 3 matcher i "recent" och 5 i "baseline" |
| **Baseline-jämförelse** | Jämför mot säsongsmedel, inte bara "högt absolut" |
| **Recency** | Senaste 5 matcher väger mer än matcher för 2 månader sedan |
| **Significance-formel** | `(value - baseline) / baseline` eller liknande – normaliserad avvikelse |
| **Undvik noise** | 1 match med 5 poäng ≠ breakout. Kräv konsistens över flera matcher |

---

## 8. Config-schema (Pydantic)

```python
# config/schema.py
from pydantic import BaseModel, Field
from typing import List

class TeamPointsStreakConfig(BaseModel):
    min_streak_games: int = 3
    min_pts_per_game: float = 1.6
    lookback_days: int = 90

class PlayerBreakoutConfig(BaseModel):
    lookback_games: int = 5
    multiplier_vs_baseline: float = 2.0
    min_games_played: int = 3

class GoalieSavePctTrendConfig(BaseModel):
    min_games: int = 3
    min_save_pct: float = 0.92
    lookback_days: int = 30

class EngineConfig(BaseModel):
    enabled: List[str] = Field(default_factory=lambda: ["team_points_streak", "player_breakout", "goalie_save_pct_trend"])
    max_insights_per_run: int = 20
    dedup_days: int = 7
    team_points_streak: TeamPointsStreakConfig = Field(default_factory=TeamPointsStreakConfig)
    player_breakout: PlayerBreakoutConfig = Field(default_factory=PlayerBreakoutConfig)
    goalie_save_pct_trend: GoalieSavePctTrendConfig = Field(default_factory=GoalieSavePctTrendConfig)
```

---

## 9. Engine-run (pseudokod)

```python
# core/engine.py
def run(context: RunContext, config_path: str | Path) -> list[Insight]:
    config = load_config(config_path)
    conn = duckdb.connect(str(context.db_path), read_only=True)

    all_findings: list[RawFinding] = []
    for detector_id in config.enabled:
        detector = get_detector(detector_id)
        detector_config = getattr(config, detector_id, None)
        findings = detector.run(conn, context, detector_config)
        all_findings.extend(findings)

    conn.close()

    # Convert RawFinding → Insight (same structure, add metadata)
    insights = [finding_to_insight(f, context) for f in all_findings]

    # Rank: sort by significance, dedup, take top N
    insights = rank_and_dedup(insights, config.max_insights_per_run, config.dedup_days)

    return insights
```

---

## 10. Detector-registry (plugin-loading)

```python
# detectors/__init__.py
from .base import BaseDetector
from .team_points_streak import TeamPointsStreakDetector
from .player_breakout import PlayerBreakoutDetector
from .goalie_save_pct_trend import GoalieSavePctTrendDetector

REGISTRY: dict[str, type[BaseDetector]] = {
    "team_points_streak": TeamPointsStreakDetector,
    "player_breakout": PlayerBreakoutDetector,
    "goalie_save_pct_trend": GoalieSavePctTrendDetector,
}

def get_detector(id: str) -> BaseDetector:
    if id not in REGISTRY:
        raise ValueError(f"Unknown detector: {id}")
    return REGISTRY[id]()
```

**Utökning:** Lägg ny detector i `detectors/`, registrera i `REGISTRY`, lägg till i `detectors.yaml` under `enabled`. Ingen ändring i engine.

---

## 11. Beroenden

Lägg till i `requirements.txt` (Mage har redan mycket):

```
pydantic>=2.0
pyyaml
```

DuckDB finns redan. Ingen LLM-SDK i kärnan.

---

## 12. Testbarhet

| Nivå | Vad testas |
|------|------------|
| **Unit** | Varje detector med mockad DuckDB (in-memory, fixture-data) |
| **Integration** | Engine.run() med riktig Gold-fil (fixture eller liten export) |
| **Determinism** | Samma input → samma output (snapshot-test) |

```python
# tests/test_insight_engine/test_team_points_streak.py
def test_team_points_streak_detects_hot_team(duckdb_fixture):
    conn = duckdb.connect(":memory:")
    conn.execute("CREATE TABLE team_game_stats AS SELECT * FROM read_parquet('fixtures/team_game_stats_sample.parquet')")
    detector = TeamPointsStreakDetector()
    findings = detector.run(conn, context, config)
    assert len(findings) >= 1
    assert findings[0].entity_id == "TOR"
```

---

## 13. Versionshantering och spårbarhet

Varje `Insight` innehåller:
- `detector_id`, `detector_version`
- `as_of_date`

Engine kan logga: `ENGINE_VERSION`, `config_hash` (SHA av detectors.yaml). Vid export (JSON/MD) – inkludera meta:
```json
{
  "generated_at": "2026-02-24T12:00:00Z",
  "engine_version": "0.1.0",
  "config_hash": "abc123",
  "as_of_date": "2026-02-22",
  "insights": [...]
}
```

---

## 14. Multi-liga, historisk data och variabel datadetalj

Planen tar höjd för att du kommer:
1. **Fylla på med mer historisk NHL-data** (t.ex. 2010–2030)
2. **Lägga till flera ligor** (SHL, Liiga, AHL, etc.)
3. **Hantera olika datadetalj per liga** – vissa ligor har bara mål/assist, andra har hits, blocks, TOI, faceoffs, målvaktsstatistik per situation, etc.

### 14.1 Datamodell för flera ligor

**Alternativ A: En databas per liga** (nuvarande NHL-setup, enkel att utöka)
```
data_lake/gold/
├── nhl.duckdb
├── shl.duckdb
├── liiga.duckdb
└── ...
```
- Varje liga har egen pipeline och egen Gold-fil
- Insight Engine får `db_path` + `league_id` i context
- Kör engine en gång per liga (eller batch i en loop)

**Alternativ B: Enad databas med league_id**
```
data_lake/gold/hockey.duckdb
```
- Alla tabeller har `league_id` (NHL, SHL, LIIGA, …)
- Vyer: `team_game_stats` innehåller `league_id`, filtrera i queries
- En engine-run kan processa alla ligor i samma körning (eller filtrera per liga)

**Rekommendation:** Börja med **Alternativ A** (en db per liga). Enklare att lägga till nya ligor utan att ändra befintlig schema. Engine design stöder båda – `RunContext` tar `league_id` och `db_path`.

### 14.2 RunContext utökad med liga

```python
class RunContext(BaseModel):
    db_path: str | Path
    league_id: str                    # "nhl", "shl", "liiga", ...
    as_of_date: date
    lookback_days: int = 90
    season: str | None = None
    # Framtida: league_config override
```

Varje `Insight` får `league_id` – viktigt för export ("NHL-insikter" vs "SHL-insikter") och för liga-specifik formattering.

### 14.3 Data capability matrix – variabel datadetalj

Olika ligor har olika detaljgrad. Exempel:

| Kolumn / vy | NHL | SHL | Liiga | Mindre liga |
|-------------|-----|-----|-------|-------------|
| goals_for, goals_against | ✓ | ✓ | ✓ | ✓ |
| home_points, away_points | ✓ | ✓ (annan poängfördelning) | ✓ | ? |
| sog, hits, blocks | ✓ | ✓ | ✓ | kanske inte |
| faceoff_win_pct | ✓ | ✓ | ? | ? |
| toi_seconds | ✓ | ? | ? | sällan |
| save_pct (målvakt) | ✓ | ✓ | ✓ | ✓ |
| even_strength_goals_against | ✓ | ? | ? | sällan |
| edge_skaters (NHL EDGE) | ✓ | ✗ | ✗ | ✗ |

**Lösning: Detector capability requirements**

Varje detector deklarerar vilka kolumner/vyer den behöver:

```python
# detectors/base.py
class BaseDetector(ABC):
    id: str
    version: str = "1.0"

    # Ny: vilka kolumner måste finnas för att detectorn ska köras?
    required_columns: dict[str, list[str]] = {}
    # T.ex. {"team_game_stats": ["team_abbr", "game_date", "goals_for", "home_points"]}
    # Eller: required_views: ["team_game_stats"]  # Mina queries behöver denna vy

    def can_run(self, conn: duckdb.DuckDBPyConnection, league_id: str) -> bool:
        """Kontrollera om databasen har nödvändiga kolumner."""
        for view, cols in self.required_columns.items():
            try:
                result = conn.execute(f"SELECT {', '.join(cols)} FROM {view} LIMIT 1").fetchone()
                if result is None:
                    return False
            except duckdb.Error:
                return False  # Vy eller kolumn saknas
        return True

    @abstractmethod
    def run(self, conn, context, config) -> List[RawFinding]:
        pass
```

**Engine-logik:** Innan `detector.run()` anropar engine `detector.can_run(conn, context.league_id)`. Om `False` → hoppa över den detectorn för denna liga (logga "Skipping X for league Y: missing columns").

### 14.4 Ligaspecifik konfiguration

Några ligor har annorlunda regler:
- **Poängsystem:** NHL 2-1-0 (vinst/OT-förlust/förlust). SHL 3-0. Liiga 3-2-1-0.
- **Säsongslängd:** NHL ~82 matcher, SHL ~52, Liiga ~60.
- **Trösklar:** "Hot streak" kanske är 1.8 pts/match i NHL men 2.0 i SHL (färre matcher, högre variance).

**Config-struktur:**
```yaml
# detectors.yaml
enabled:
  - team_points_streak
  - player_breakout
  - goalie_save_pct_trend

# Default för alla ligor
team_points_streak:
  min_streak_games: 3
  min_pts_per_game: 1.6
  lookback_days: 90

# Liga-specifika override (valfritt)
league_overrides:
  nhl:
    team_points_streak:
      min_pts_per_game: 1.6
  shl:
    team_points_streak:
      min_pts_per_game: 2.0   # SHL har 3-0-system, högre snitt
      lookback_days: 60
  liiga:
    player_breakout:
      min_games_played: 5     # Längre säsong, kräv mer data
```

Engine: vid `run()` slår ihop `config[detector_id]` med `config.league_overrides.get(league_id, {}).get(detector_id, {})`.

### 14.5 Historisk data – skalning

| Aspekt | Hantering |
|--------|-----------|
| **Volym** | DuckDB + Parquet skalar bra. 10 år NHL = ~20k matcher, ~400k game_players-rader – ingen problem |
| **Lookback** | `lookback_days` begränsar vilka rader som läses. Du behöver aldrig scanna hela historiken |
| **Prestanda** | Partitionerad Silver (game_date=YYYY-MM-DD) gör att DuckDB kan predicate-pushdown. Snabbt |
| **Minnesättning** | DuckDB är columnar – läser bara kolumner som används. Ingen full-scan i minnet |

Mer historik = bättre baselines (säsongsmedel, långsiktiga trender). Det påverkar inte negativt – det förbättrar kvaliteten på insikterna.

### 14.6 Schema-unifiering för flera ligor (Alternativ B)

Om du senare väljer **enad databas** med `league_id` i alla tabeller:
- Silver-struktur: samma kolumner, men `league_id` i varje rad
- Kolumner som saknas för en liga: `NULL`. Detectorn `can_run()` kollar `WHERE league_id = ?` och att kolumner är non-null tillräckligt ofta
- Vyer kan vara `team_game_stats` med `league_id` – engine filtrerar i varje query

Detalj för detta är en senare fas. Alternativ A räcker för att starta med NHL + eventuellt SHL/Liiga som separata pipelines.

### 14.7 Sammanfattning: multi-liga + variabel detalj

| Krav | Lösning |
|------|---------|
| **Flera ligor** | `league_id` i RunContext och Insight. En db per liga (eller enad med league_id) |
| **Mer historisk NHL-data** | Lookback + partitioner. Ingen kodändring. Bättre baselines |
| **Variabel datadetalj** | `required_columns` per detector. `can_run()` – hoppa över om data saknas |
| **Liga-specifika trösklar** | `league_overrides` i config. Merge vid run |
| **Poängsystem m.m.** | Kolumnnamn kan vara generiska (`points`); league override anger tröskel |

---

## 15. Sammanfattning

| Aspekt | Rekommendation |
|--------|----------------|
| **Struktur** | core/ (engine, context, ranker) + models/ + detectors/ + config/ |
| **Datamodeller** | Pydantic v2 – validering, serialisering |
| **Detector-interface** | `run(conn, context, config) → List[RawFinding]` |
| **Config** | YAML + Pydantic schema, env overrides |
| **Plugin** | Registry i detectors/__init__, en fil per detector |
| **Efficiency** | En connection, batch SQL, lookback, top-N, dedup |
| **Cost** | Noll – ingen extern API i detection |
| **Quality** | Min sample size, baseline-jämförelse, significance |
| **Extensibility** | Ny detector = ny fil + registry-entry |
| **Multi-liga** | `league_id` i context/insight. En db per liga eller enad med league_id |
| **Variabel detalj** | `required_columns` + `can_run()`. Hoppa över detector om data saknas |
| **Historisk skalning** | Lookback + partitionering. DuckDB skalar, mer historik = bättre baselines |
