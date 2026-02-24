# Games-data: år-för-år, batch och dagliga uppdateringar

## Tre sätt att köra

1. **År för år (rekommenderat)** – sätt bara `games_year` (t.ex. `2010`) i Mage. Pipelinen **delar upp jobbet i batchar automatiskt** och kör tills det året är klart (minnesbesparande, en körning per år).
2. **Manuell batch (utan år)** – sätt `games_batch_size=30` utan `games_year`; kör pipelinen flera gånger tills "Inga nya datum".
3. **Dagliga uppdateringar** – när all historik är inne, ta bort `games_year`; pipelinen hämtar då bara nya datum efter senaste körning.

---

## Setup 1: Ladda historik år för år – automatiskt batchat (rekommenderat)

Du anger **bara vilket år** som ska köras. Pipelinen **batchar automatiskt** (t.ex. 30 datum åt gången) så minnet håller sig under 95 % – du behöver inte köra flera gånger per år.

**Förberedelse (en gång)**

- I `.env`: `GAMES_START_DATE=2010-01-01` (låt stå).
- Rensa state så första året laddas från början:
  ```bash
  ./scripts/reset_full_games_load.sh
  ```

**För varje år (2010, 2011, … 2026) – en körning per år i Mage UI**

**Alternativ A – fil (fungerar även om Mage inte skickar variables)**  
Skapa eller redigera `mage_project/state/games_year.txt` och skriv bara årtalet, t.ex. `2025`. Kör **games_pipeline** – loadern läser året från filen.

**Alternativ B – Variables i Mage**  
1. Öppna **Mage** → **games_pipeline**.
2. Öppna **Variables** och skapa/redigera:
   - **Namn:** `games_year`
   - **Värde:** `2010` (första körningen).
3. Spara. Kör **games_pipeline** (Run pipeline) **en gång**.
4. Pipelinen loggar t.ex. *"År 2010: kör automatiskt i 12 batchar …"* och kör load → transform → export i batchar tills året är klart.
5. När den är klar: ändra `games_year` (i filen eller Variables) till `2011`, kör pipelinen igen. Upprepa till `2026`.

Valfritt: du kan sätta `games_batch_size` (t.ex. `20`) om du vill mindre batchar och ännu lägre minnesanvändning; standard är 30 datum per batch.

**Alternativ: via .env (kräver omstart av Mage)**

Om du hellre vill styra via `.env`:
1. `./scripts/run_games_year.sh 2010`
2. `docker compose restart mage`
3. Kör games_pipeline i Mage. Nästa år: `./scripts/run_games_year.sh 2011`, restart, kör igen.

**Inga dubbletter**

- State (`last_games_date.txt`) sparar senaste laddade datum; nästa körning hämtar bara datum **efter** det.
- Export rensar den aktuella partitionen (lokal + S3) innan den skriver, så om du kör om ett år skrivs bara det årets data om.

---

## Manuell batch (utan games_year)

Om du **inte** använder `games_year` men vill begränsa minnet: sätt `games_batch_size=30` i Variables. Då laddas max 30 datum per körning och du kör pipelinen upprepade gånger tills "Inga nya datum". Via `.env`: `GAMES_BATCH_SIZE=30`.

---

## Setup 2: Dagliga uppdateringar (efter att historik är inne)

När du laddat alla år (eller gjort en full körning) och bara vill ha nya matcher:

**I Mage UI:** Ta bort variabeln `games_year` (eller sätt värdet till tomt) under Variables. Kör **games_pipeline** när du vill – den hämtar då endast datum **större än** `last_games_date` (inga dubbletter).

**Eller via .env:** Kör `./scripts/run_games_daily.sh`, starta om Mage, kör games_pipeline som vanligt.

---

## Snabbreferens

| Mål | Vad du gör |
|-----|-------------|
| **År för år (automatisk batch)** | Rensa state (`reset_full_games_load.sh`). Variables → `games_year` = `2010` → Run pipeline **en gång** – året batchas automatiskt. När klar: `games_year` = `2011`, kör igen … tills `2026`. |
| **Manuell batch (utan år)** | Variables → `games_batch_size` = `30`. Kör pipeline upprepade gånger tills "Inga nya datum". |
| **Dagliga uppdateringar** | Ta bort variabeln `games_year` i Mage (Variables) eller kör `./scripts/run_games_daily.sh` + restart Mage. Kör games_pipeline vid behov. |
| **Kolla vad som laddas** | `python scripts/scope_games_pipeline.py` (visar även GAMES_YEAR/games_year om satt) |
