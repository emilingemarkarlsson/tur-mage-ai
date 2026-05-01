"""
Validerar resultatet av swe_scrape_pipeline och loggar en tydlig sammanfattning.
Misslyckas hårt om kritiska fel uppstod under scrapingen.
"""

if "data_exporter" not in globals():
    from mage_ai.data_preparation.decorators import data_exporter


@data_exporter
def validate_swe_scrape(result: dict, *args, **kwargs):
    """
    Input: dict från scrape_swe_games
    Kastar ValueError om för många fel inträffade.
    """
    if not isinstance(result, dict):
        raise TypeError(f"Oväntat resultat från scrape_swe_games: {type(result)}")

    mode = result.get("mode", "?")
    dates = result.get("dates_attempted", 0)
    found = result.get("games_found", 0)
    scraped = result.get("games_scraped", 0)
    errors = result.get("errors", [])
    date_from = result.get("date_from", "?")
    date_to = result.get("date_to", "?")

    print("=" * 60)
    print(f"[swe_scrape] VALIDERING – mode={mode}")
    print(f"  Period:          {date_from} → {date_to}")
    print(f"  Datum körda:     {dates}")
    print(f"  Matcher hittade: {found}")
    print(f"  Detaljer hämtade:{scraped}")
    print(f"  Fel:             {len(errors)}")
    if errors:
        for e in errors[:5]:
            print(f"    ⚠ {e}")
    print("=" * 60)

    # Varna men misslyckas inte om en liten del misslyckades
    if dates > 0 and len(errors) > dates * 0.5:
        raise ValueError(
            f"För många fel: {len(errors)} av {dates} datum misslyckades. "
            f"Kontrollera nätverket eller stats.swehockey.se-tillgängligheten."
        )

    return result
