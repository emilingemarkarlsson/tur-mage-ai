# Prompt: nästa session – health check, städning, sedan pipelines

Kopiera **hela rutan nedan** till Cursor Agent (ny chatt) när du vill säkerställa att allt är i ordning, lätt städa, och sedan fokusera på datapipelines.

---

## Copy-paste till Cursor Agent

```
Du jobbar i repot tur-mage-ai (Mage AI på Coolify, GHCR-image ghcr.io/emilingemarkarlsson/tur-mage-ai:latest).

Gör i denna ordning:

1) Snabb health check (kör kommandon själv, rapportera kort)
   - git status; ska vara rent eller tydlig lista på osparade filer
   - Om det finns lokala ändringar: föreslå commit-meddelande men committa bara om jag uttryckligen säger till
   - curl -sf -o /dev/null -w "mage %{http_code}\n" https://mage.theunnamedroads.com/ (förväntat 200)
   - valfritt: gh run list --repo emilingemarkarlsson/tur-mage-ai --workflow "Build and push Mage image" --limit 1 (senaste ska vara success om vi nyligen pushat)

2) Lätt städning i repot (endast om det är uppenbart säkert)
   - Ta bort tillfälliga filer, duplicerad skräp, felplacerade artefakter (inte rör mage_project/state, data_lake, eller gitignored secrets)
   - Rör inte dokumentation jag inte bett om; om du hittar föråldrade instruktioner som direkt motsäger MAGE_GIT_INTEGRATION.md / GITOPS_FLOW.md, flagga i en mening istället för stor omskrivning

3) Påminn om prod-flödet (en kort punktlista, inget nytt repo)
   - Ändra i mage_project/ → testa lokalt (docker compose) → git push main → vänta på GitHub Actions "Build and push Mage image" → Coolify Redeploy på mage-tur ELLER tur-coolify-setup: ./scripts/coolify-update.sh deploy k0oooc8ok4848880sk0g0kkc
   - Se documentation/MAGE_GIT_INTEGRATION.md checklist

4) Nästa steg: datapipelines
   - Jag vill börja bygga/iterera på pipelines imorgon: föreslå 2–3 konkreta första uppgifter baserat på befintliga pipelines i mage_project/ (läs metadata eller pipelines-mapp), utan att implementera stora ändringar förrän jag godkänner

Håll svaret kort och använd kodcitat med filepath när du refererar till filer.
```

---

## Snabb checklist för dig själv (utan AI)

- [ ] Spara alla öppna filer i Cursor (t.ex. `SAAS_BOOTSTRAP_PROMPT.md` om du redigerat den).
- [ ] `git status` – committa det du vill ha med: `git add -A && git commit -m "..." && git push origin main`.
- [ ] Imorgon: öppna `documentation/CURSOR_NEXT_SESSION_PROMPT.md`, kopiera prompten ovan, kör i ny agent-chatt innan du kodar pipelines.

---

## Relaterad dokumentation

- `documentation/MAGE_GIT_INTEGRATION.md` – lokal → prod-checklist
- `documentation/GITOPS_FLOW.md` – GHCR / Coolify
- `documentation/COOLIFY_MIGRATION.md` – kontext om server och volymer
