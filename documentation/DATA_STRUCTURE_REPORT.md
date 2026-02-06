# Data Structure Report

Genererad: 2026-02-06T17:39:15.373525Z

Använd denna rapport för att se alla källor (Bronze/S3), Silver-tabeller och struktur, så att du kan uppdatera pipelinen och få ut all data till Silver/Gold.

---

## 1. S3 (Bronze) – inventering

*S3 hoppades över (--no-s3).*

---

## 2. S3 (Bronze) – struktur per källtyp (sample)

---

## 3. Silver – tabeller och kolumner

*Inga Silver-tabeller hittades (kör pipelines först).*
---

## 4. Mapping: Källa → Pipeline → Silver

| S3-prefix | Pipeline | Silver-tabeller | S3 filer | Silver-status |
|-----------|----------|-----------------|----------|---------------|

---

## 5. Nästa steg för att få ut all data

1. **Jämför** S3-struktur (avsnitt 2) med Silver-kolumnerna (avsnitt 3). Fält som finns i Bronze men saknas i Silver kan läggas till i respektive transformer/export.
2. **Kontrollera** att alla prefix som ska användas står i avsnitt 1 och att rätt pipeline läser dem (se [DATA_SOURCES_S3.md](DATA_SOURCES_S3.md)).
3. **Kör** pipelinen efter ändringar och kör sedan `refresh_duckdb_views` så att Gold uppdateras.
