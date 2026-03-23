# Bootstrap Prompt – NHL Analytics SaaS (Next.js)

> Klistra in detta i ett nytt Claude Code-projekt (tomt repo). Det är en komplett specifikation.

---

## Uppdraget

Bygg en **multi-tenant SaaS-applikation** för NHL-hockey-analys. Applikationen ska kunna säljas som en tjänst till hockeyentusiaster, lag, agenter och medier. Datakällan är ett välstrukturerat NHL-datalager med 16 säsongers data (2010–2026) i **MotherDuck** (molnhostad DuckDB).

Appens hjärta är en **AI-driven frågeassistent** som låter användare ställa frågor på naturligt språk och får svar baserade på riktig matchdata. Utöver det ska appen visa dashboards, spelartrender, lagstatistik och playoff-brackets.

---

## Tech stack – motiverade val

| Lager | Verktyg | Motivering |
|---|---|---|
| Frontend | **Next.js 15 (App Router)** | Full SaaS-kontroll, routing, API routes, React Server Components |
| UI | **shadcn/ui + Tailwind CSS** | Professionellt utseende, tillgängligt, komponenter inkluderade |
| Autentisering | **Clerk** | Gratis upp till 10 000 MAU, multi-tenant, enklast att sätta upp |
| Databas/queries | **MotherDuck HTTP API** | Kör DuckDB-queries direkt, inget mellanlager behövs |
| AI-lager | **LiteLLM proxy** | Routing till gratis/billiga modeller, kostnadsspärrar |
| Charts | **Recharts** | Bäst React-integration, enkel API |
| Deploy | **Vercel** | Gratis tier räcker för hockey-skala, zero-config |

**Streamlit används INTE** – det är ett internt devtool i datapipelinen, inte produktfrontend.

---

## Infrastruktur – vad som redan finns (rör INTE detta)

Det finns ett separat repo (`tur-mage-ai`) med:
- **Mage AI pipelines** som dagligen hämtar NHL-data → Bronze (S3) → Silver (Parquet) → Gold (DuckDB)
- **MotherDuck** som är det enda du behöver ansluta till – allt är redan synkat dit
- Data uppdateras automatiskt 07:00 UTC varje dag

Du behöver **bara ansluta till MotherDuck** – inga pipelines, ingen S3, ingen DuckDB-fil.

---

## Databasanslutning – MotherDuck

```
Database:  nhl
Token:     eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJlbWFpbCI6ImVtaWxpbmdlbWFya2FybHNzb25AZ21haWwuY29tIiwibWRSZWdpb24iOiJhd3MtdXMtZWFzdC0xIiwic2Vzc2lvbiI6ImVtaWxpbmdlbWFya2FybHNzb24uZ21haWwuY29tIiwicGF0IjoiTGFwQ1BxZzVSY2RRaFlHeTJtaGV1b2Z5cDltM3lpNEJ6WUZqSlNuZWJNdyIsInVzZXJJZCI6Ijk3M2U0OWU0LTg2YTAtNGEyZS1iYzdhLTY5ZTI0YmQ3Yjk5MyIsImlzcyI6Im1kX3BhdCIsInJlYWRPbmx5IjpmYWxzZSwidG9rZW5UeXBlIjoicmVhZF93cml0ZSIsImlhdCI6MTc3MTQzOTY0OX0.SPIbOFscVReE1mmVmowu8wI6jXqCLpqsuq01rCG7Cvc
Connection string: md:nhl?motherduck_token=<TOKEN>
```

MotherDuck har ett **REST API** och **WASM-klient** (`@motherduck/wasm-client`) för browser-queries. Använd Next.js API routes som proxy för queries (undvik att exponera token i browser).

Installera: `npm install @motherduck/wasm-client` eller använd MotherDuck REST API via `fetch`.

---

## LiteLLM – AI-proxy

```
Endpoint:  http://litellm-kkswc8gokk84c0o8oo84w44w.46.62.206.47.sslip.io
API Key:   sk-ECrtl9h4ELu5i6aHQHmduw
```

Tillgängliga modeller (OpenAI-kompatibelt API):

| Modell-ID | Bäst för | Kostnad |
|---|---|---|
| `gemini-flash` | Primär – Text-to-SQL, insikter, snabb | Låg |
| `gemini/gemini-2.5-flash` | Komplex reasoning, analys | Medel |
| `gemini-flash-lite` | Massanrop, enkla sammanfattningar | Mycket låg |
| `groq-llama-fast` | Sub-second latens, realtid | Låg/fri |
| `deepseek-chat` | SQL-generering backup | Låg |
| `gpt-4o-mini` | Fallback | Medel |

**Routing-strategi:**
- Text-to-SQL queries → `gemini-flash` (primär) → `deepseek-chat` (fallback)
- Realtidsförfrågningar i UI → `groq-llama-fast`
- Komplexa analyser → `gemini/gemini-2.5-flash`

Använd OpenAI SDK med `baseURL` och `apiKey` pekade mot LiteLLM.

---

## Dataschema – fullständig referens

Databasen heter `nhl` i MotherDuck. Alla tabeller är i `main`-schemat.

### Kärnfakta (game-level)

**`games`** – En rad per match
- `game_id` BIGINT (PK) – NHL API gamePk
- `game_date` DATE – Matchdatum
- `season` BIGINT – t.ex. 20242025
- `game_type` VARCHAR – '2'=grundserie, '3'=slutspel
- `status` VARCHAR – FINAL, LIVE, etc.
- `home_team_abbr`, `away_team_abbr` VARCHAR – t.ex. 'TOR', 'BOS'
- `home_score`, `away_score` BIGINT
- `home_points`, `away_points` BIGINT – 2/1/0 (NHL-poäng)
- `home_sog`, `away_sog` BIGINT – Skott på mål
- `home_hits`, `away_hits` BIGINT
- `home_pp_goals`, `away_pp_goals` DOUBLE
- `home_pp_opportunities`, `away_pp_opportunities` DOUBLE
- `last_period_type` VARCHAR – REG/OT/SO
- `ot_periods` BIGINT – antal OT-perioder
- `venue`, `venue_location` VARCHAR

**`team_game_stats`** – En rad per lag per match (unpivot av games) ← **primär för laganalys**
- `game_id`, `game_date`, `season`
- `team_abbr` VARCHAR – lagets förkortning
- `opponent_abbr` VARCHAR
- `is_home` BOOLEAN
- `goals_for`, `goals_against` BIGINT
- `team_points` BIGINT – 2/1/0
- `sog`, `hits`, `blocked_shots` BIGINT
- `pp_goals`, `pp_opportunities` DOUBLE
- `pim`, `faceoff_win_pct` DOUBLE

**`team_game_stats_extended`** – team_game_stats + konferens/division
- Alla kolumner från team_game_stats plus:
- `conference_abbr` (E/W), `conference_name`
- `division_abbr` (A/M/C/P), `division_name`

**`player_game_stats`** – En rad per spelare per match ← **primär för spelaranalys**
- `game_id`, `game_date`, `season`
- `player_id` BIGINT, `player_first_name`, `player_last_name` VARCHAR
- `team_abbr`, `is_home` BOOLEAN
- `position` VARCHAR – F/D/C/LW/RW/G
- `goals`, `assists`, `points` DOUBLE
- `plus_minus`, `shots`, `hits`, `blocked_shots` DOUBLE
- `toi_seconds` BIGINT – istid i sekunder (dela med 60 för minuter)
- `power_play_goals`, `short_handed_goals` DOUBLE
- `saves`, `shots_against`, `save_pct`, `goals_against` DOUBLE – (målvakter)

**`game_events`** – Play-by-play, 6.6M rader
- `game_id`, `game_date`
- `event_id` BIGINT, `period` BIGINT, `period_type` VARCHAR
- `time_remaining` VARCHAR – MM:SS
- `event_type` VARCHAR – GOAL/SHOT/PENALTY/FACEOFF/HIT/BLOCKED_SHOT
- `team_abbr`, `player_id`, `secondary_player_id`
- `description` VARCHAR

**`game_stories`** – Matchberättelser (sparse – inte alla matcher har)
- `game_id`, `game_date`, `headline`, `body` VARCHAR

### Dimensioner

**`teams`** – 32 lag
- `abbr` VARCHAR (PK) – t.ex. 'TOR' ← **join-nyckel mot alla game-tabeller**
- `name`, `common_name` VARCHAR
- `conference_abbr` (E/W), `conference_name`
- `division_abbr` (A/M/C/P), `division_name`

**`players`** – ~800 aktiva spelare
- `id` BIGINT (PK), `firstName`, `lastName`
- `positionCode`, `shootsCatches`
- `birthDate`, `birthCountry`
- `heightInCentimeters`, `weightInKilograms`

**`roster`** – Spelare per lag per säsong
- `season`, `team_id`, `team_abbr`, `player_id`

**`standings`** – Slutlig tabell per säsong 2010–2026
- `season`, `teamAbbrev` (PK), `teamName`
- `wins`, `losses`, `otLosses`, `points`, `pointPctg`, `gamesPlayed`
- `leagueSequence`, `conferenceSequence`, `divisionSequence`
- `conferenceAbbrev`, `divisionAbbrev`
- `goalFor`, `goalAgainst`, `goalDifferential`
- `homeWins`, `roadWins`, `regulationWins`
- `streakCode`, `streakCount`

### Säsongsstatistik

**`skater_stats`** – Säsongsagg per skridskospelare 2010–2026
- `playerId`, `season`, `skaterFullName`, `positionCode`, `teamAbbrevs`
- `gamesPlayed`, `goals`, `assists`, `points`, `pointsPerGame`
- `plusMinus`, `penaltyMinutes`, `ppGoals`, `ppPoints`
- `shots`, `shootingPct`, `timeOnIcePerGame`, `faceoffWinPct`

**`goalie_stats`** – Säsongsagg per målvakt 2010–2026
- `playerId`, `season`, `goalieFullName`, `teamAbbrevs`
- `gamesPlayed`, `wins`, `losses`, `otLosses`
- `savePct`, `goalsAgainstAverage`, `shutouts`

**`team_stats`** – Säsongsagg per lag 2010–2026
- `teamId`, `season`, `teamFullName`
- `wins`, `losses`, `otLosses`, `points`, `pointPct`
- `goalsFor`, `goalsAgainst`, `goalsForPerGame`, `goalsAgainstPerGame`
- `powerPlayPct`, `penaltyKillPct`, `shotsForPerGame`, `faceoffWinPct`

**`playoff_brackets`** – Slutspelsträd 2010–2026 (263 serier)
- `season`, `series_letter` (PK)
- `series_title` – "1st Round", "Conference Final", "Stanley Cup Final"
- `playoff_round` BIGINT – 1-4
- `top_seed_team_abbr`, `bottom_seed_team_abbr`
- `top_seed_wins`, `bottom_seed_wins`
- `winning_team_id`, `losing_team_id`

### EDGE (NHL tracking)
- `edge_skaters`, `edge_goalies`, `edge_teams` – NHL EDGE ledare per kategori per säsong

### Datastorlek
- games: 21 402 rader (2010–2026)
- player_game_stats: 853 700 rader
- game_events: 6 666 178 rader
- skater_stats: 15 639 rader (17 säsonger)
- standings: 524 rader
- playoff_brackets: 263 serier

---

## Text-to-SQL system prompt

Använd följande som `system`-meddelande till LiteLLM när du genererar SQL:

```
You are a DuckDB SQL expert for NHL hockey analytics. Generate valid DuckDB SQL queries.

DATABASE: nhl (MotherDuck / DuckDB)

KEY RULES:
- Always use table names without schema prefix (just: games, team_game_stats, player_game_stats, etc.)
- team_abbr values are uppercase 3-letter codes: TOR, BOS, MTL, NYR, EDM, CGY, VAN, etc.
- season format is BIGINT like 20242025 (year the season starts + year it ends)
- game_type = '2' for regular season, '3' for playoffs
- For player trends: use player_game_stats (has names). For raw: use game_players + JOIN players.
- For team trends: use team_game_stats (one row per team per game). For game level: use games.
- toi_seconds: divide by 60 for minutes
- is_home BOOLEAN: true = home game
- Always add LIMIT (default 100, max 1000) unless aggregating
- For "recent games" use ORDER BY game_date DESC
- For standings points use team_points (2=win, 1=OT loss, 0=loss)
- JOIN key: teams.abbr = team_game_stats.team_abbr (NOT teams.id)

TABLES AVAILABLE:
games, team_game_stats, team_game_stats_extended, player_game_stats, game_players,
game_events, game_stories, teams, players, roster, schedule, playoff_brackets,
standings, skater_stats, goalie_stats, team_stats, edge_skaters, edge_goalies, edge_teams

Return ONLY the SQL query, no explanation, no markdown code blocks.
```

---

## Produkt – features att bygga (prioriterad ordning)

### Fas 1 – MVP (bygg detta först)

**1. Layout + auth**
- Clerk-integration (signup/login)
- Navbar med: Hem | Lag | Spelare | AI Chat | Standings
- Mörkt tema (hockey-känsla: mörkblå/svart bakgrund, vit text, accent i guld/röd)

**2. AI Chat (`/chat`)**
- Chattfält där användaren skriver fri text
- Next.js API route kallar LiteLLM med Text-to-SQL system prompt
- SQL körs mot MotherDuck via API route
- Resultat visas som tabell + LLM-genererad sammanfattning på svenska
- Visa SQL-frågan (kollapsad) för transparens
- Exempel-frågor som knappar: "Vilka spelare har flest poäng 2025?", "Visar mig Leafs senaste 10 matcher"

**3. Lag-dashboard (`/teams/[abbr]`)**
- Dropdown/sök för att välja lag
- Senaste 10 matcherna (W/L/OT, poäng, mål, skott) – tabell + sparkline
- Säsongsstatistik (nuvarande + föregående)
- Hemma/borta-split
- Data: team_game_stats + team_stats

**4. Standings (`/standings`)**
- Aktuell säsong, grupperat per division
- Kolumner: Lag | GP | W | L | OTL | PTS | GF | GA | DIFF | Streak
- Data: standings (filtrera på nuvarande säsong)

### Fas 2

**5. Spelare (`/players/[id]`)**
- Sök spelare (autocomplete mot players-tabellen)
- Poängkurva senaste 20 matcher (linjediagram)
- Karriärsstatistik per säsong (tabell)
- Data: player_game_stats + skater_stats

**6. Playoff Bracket (`/playoffs/[season]`)**
- Visualisering av playoff-träd
- Data: playoff_brackets

**7. Proaktiva insikter (startsida)**
- "Senaste 24h": summering av gårdagens matcher via LLM
- Hot streaks: lag/spelare med ovanligt bra form senaste 5 matcher
- Data: team_game_stats + player_game_stats, LLM-sammanfattning

### Fas 3 (SaaS-lager)

**8. Betalning**
- Stripe integration
- Free tier: standings + basic stats
- Pro tier: AI chat + full historik + insikter

**9. Multi-tenancy**
- Clerk organizations för lag/bolag
- Per-tenant API-nycklar mot LiteLLM (kostnadsspårning per kund)

---

## Projektstruktur (förslag)

```
/
├── app/
│   ├── (auth)/
│   │   └── sign-in/  sign-up/
│   ├── (dashboard)/
│   │   ├── layout.tsx        ← Navbar, Clerk auth guard
│   │   ├── page.tsx          ← Startsida / insikter
│   │   ├── chat/page.tsx     ← AI Chat
│   │   ├── teams/[abbr]/page.tsx
│   │   ├── players/[id]/page.tsx
│   │   ├── standings/page.tsx
│   │   └── playoffs/[season]/page.tsx
│   └── api/
│       ├── query/route.ts    ← MotherDuck proxy
│       └── ai/route.ts       ← LiteLLM proxy + Text-to-SQL
├── components/
│   ├── ui/                   ← shadcn komponenter
│   ├── charts/               ← Recharts wrappers
│   └── hockey/               ← Domänspecifika komponenter
├── lib/
│   ├── motherduck.ts         ← MotherDuck klient
│   ├── litellm.ts            ← LiteLLM/OpenAI klient
│   └── sql-prompts.ts        ← System prompts för Text-to-SQL
└── .env.local
    MOTHERDUCK_TOKEN=...
    LITELLM_BASE_URL=http://litellm-kkswc8gokk84c0o8oo84w44w.46.62.206.47.sslip.io
    LITELLM_API_KEY=sk-ECrtl9h4ELu5i6aHQHmduw
    NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=...
    CLERK_SECRET_KEY=...
```

---

## Viktiga tekniska beslut

### MotherDuck-anslutning
Använd **aldrig** MotherDuck-token på klientsidan. Skapa alltid en Next.js API route som proxy:

```typescript
// app/api/query/route.ts
import { createConnection } from '@motherduck/wasm-client'

export async function POST(req: Request) {
  const { sql } = await req.json()
  // Whitelist-validera SQL här (SELECT only, max LIMIT)
  const conn = await createConnection(`md:nhl?motherduck_token=${process.env.MOTHERDUCK_TOKEN}`)
  const result = await conn.execute(sql)
  return Response.json(result)
}
```

### SQL-säkerhet
Validera alltid att LLM-genererad SQL:
- Börjar med SELECT (ingen INSERT/UPDATE/DELETE/DROP)
- Innehåller LIMIT
- Max 2000 rader

### LiteLLM-anrop
```typescript
// lib/litellm.ts
import OpenAI from 'openai'

export const litellm = new OpenAI({
  baseURL: process.env.LITELLM_BASE_URL + '/v1',
  apiKey: process.env.LITELLM_API_KEY,
})

export async function textToSQL(userQuestion: string): Promise<string> {
  const response = await litellm.chat.completions.create({
    model: 'gemini-flash',
    messages: [
      { role: 'system', content: SQL_SYSTEM_PROMPT },
      { role: 'user', content: userQuestion }
    ],
    max_tokens: 500,
    temperature: 0,
  })
  return response.choices[0].message.content ?? ''
}
```

---

## Starta projektet

```bash
npx create-next-app@latest nhl-saas --typescript --tailwind --app --src-dir
cd nhl-saas
npx shadcn@latest init
npx shadcn@latest add button card table input badge tabs
npm install openai recharts @clerk/nextjs
npm install @motherduck/wasm-client
```

Skapa `.env.local` med variablerna ovan och börja med Fas 1.

---

## Kontext – vad detta är

Detta är del av ett sportanalytics-bolag under uppbyggnad. Datapipelinen (tur-mage-ai) är produktionsklar och kör dagligen. Denna frontend är nästa lager – SaaS-produkten som säljs till kunder. Prioritera **snabb time-to-market** och **snygg UX** framför överkomplexitet. Undvik over-engineering.
