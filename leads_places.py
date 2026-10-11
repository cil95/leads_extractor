"""
Sucht Firmen über die offizielle Google Places API (New) - Text Search -
nach einem Begriff wie "Friseure in Münster" und listet die, die KEINE
Webseite hinterlegt haben (kein "websiteUri"-Feld in der API-Antwort).

Im Gegensatz zu leads.py wird hier NICHT die Google-Suchseite gescraped,
sondern die offizielle, kostenpflichtige Places API benutzt. Kein
CAPTCHA-Risiko, dafür strukturierte und zuverlässige Daten.

Nutzung:
    Entweder in einer .env-Datei im selben Verzeichnis:
        GOOGLE_MAPS_API_KEY=dein-api-key
    oder als Umgebungsvariable:
        export GOOGLE_MAPS_API_KEY="dein-api-key"

    python leads_places.py "Friseure in Münster"

Der API-Key wird bewusst NICHT als Kommandozeilen-Argument akzeptiert,
damit er nicht versehentlich in der Shell-History oder in Logs landet.

API-Dokumentation:
    https://developers.google.com/maps/documentation/places/web-service/text-search
"""

import os
import sys
import time
import urllib.parse

import requests
from dotenv import load_dotenv

from emails import add_emails
from lead_groups import group_leads, print_groups

load_dotenv()

TEXT_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"

# Places API hat kein Feld "hat Online-Terminbuchung". Heuristik: wenn die
# hinterlegte Website-Domain zu einer bekannten Buchungsplattform gehört
# (z.B. "dein-schnitt.mytreatwell.de"), werten wir das als Terminbuchung
# vorhanden. Erkennt nicht jedes eigene Buchungswidget auf eigener Domain,
# deckt aber die gängigsten Anbieter im DACH-Raum ab.
BOOKING_PLATFORM_DOMAINS = [
    "mytreatwell.de",
    "treatwell.de",
    "fresha.com",
    "shore.com",
    "terminland.de",
    "salonized.com",
    "bookitit.de",
    "calendly.com",
    "doctolib.de",
    "samedi.de",
    "reservio.com",
    "planity.com",
    "setmore.com",
    "simplybook.me",
    "terminplaner24.de",
]


def has_booking_platform(website: str | None) -> bool:
    if not website:
        return False
    host = urllib.parse.urlparse(website).netloc.lower()
    return any(host == d or host.endswith(f".{d}") for d in BOOKING_PLATFORM_DOMAINS)

# Felder, die wir pro Treffer brauchen. Explizit angeben (FieldMask),
# sonst lehnt die API die Anfrage ab bzw. es werden unnötig viele
# (kostenpflichtige) Felder zurückgegeben.
FIELD_MASK = ",".join(
    [
        "places.displayName",
        "places.formattedAddress",
        "places.internationalPhoneNumber",
        "places.rating",
        "places.userRatingCount",
        "places.websiteUri",
        "nextPageToken",
    ]
)

# Places API gibt max. 20 Treffer pro Seite zurück, max. 60 insgesamt
# (3 Seiten) für Text Search.
MAX_PAGES = 3


def search_places(query: str, api_key: str, debug: bool = False) -> list[dict]:
    """Holt alle Seiten der Text-Search-Ergebnisse und gibt die rohen
    Place-Objekte zurück."""
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": FIELD_MASK,
    }

    all_places = []
    body = {"textQuery": query, "languageCode": "de"}

    for page_num in range(1, MAX_PAGES + 1):
        resp = requests.post(TEXT_SEARCH_URL, headers=headers, json=body, timeout=15)
        if resp.status_code != 200:
            raise RuntimeError(f"Fehler bei der API-Anfrage ({resp.status_code}): {resp.text}")

        data = resp.json()
        places = data.get("places", [])
        all_places.extend(places)
        if debug:
            print(f"[debug] Seite {page_num}: {len(places)} Treffer")

        next_token = data.get("nextPageToken")
        if not next_token:
            break

        # Google verlangt eine kurze Wartezeit, bevor der nextPageToken
        # gültig wird.
        time.sleep(2)
        body = {"textQuery": query, "languageCode": "de", "pageToken": next_token}

    return all_places


def search(
    query: str, api_key: str | None = None, debug: bool = False, with_emails: bool = True
) -> dict:
    """Führt die komplette Places-Suche aus und gibt ein strukturiertes
    Ergebnis zurück, statt es auf stdout zu drucken. Wird sowohl vom
    CLI-Einstieg (main()) als auch vom API-Server (server.py) genutzt.
    """
    api_key = api_key or os.environ.get("GOOGLE_MAPS_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Kein API-Key gefunden. Bitte GOOGLE_MAPS_API_KEY setzen (.env oder Umgebungsvariable)."
        )

    places = search_places(query, api_key, debug=debug)

    results = []
    for p in places:
        name = p.get("displayName", {}).get("text", "(unbekannt)")
        address = p.get("formattedAddress")
        phone = p.get("internationalPhoneNumber")
        rating = p.get("rating")
        rating_count = p.get("userRatingCount")
        website = p.get("websiteUri")
        # Den separaten "Online buchen"-Button liefert die Places API nicht.
        # Erkennbar ist nur, ob das Website-Feld selbst auf eine
        # Buchungsplattform zeigt - dann ist das keine eigene Webseite.
        booking = has_booking_platform(website)
        if booking:
            website = None

        rating_str = None
        if rating is not None:
            rating_str = f"{rating} ({rating_count or 0})"

        results.append(
            {
                "name": name,
                "address": address,
                "phone": phone,
                "rating": rating_str,
                "website": website,
                "booking": booking,
            }
        )

    if with_emails:
        add_emails(results)

    return {
        "query": query,
        "total": len(results),
        **group_leads(results),
    }


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    debug = "--debug" in sys.argv

    if not args:
        print('Nutzung: python leads_places.py "Suchbegriff, z.B. Friseure in Münster" [--debug]')
        sys.exit(1)

    query = args[0]
    print(f"Suche über Places API: {query!r} ...")

    try:
        result = search(query, debug=debug)
    except RuntimeError as e:
        print(str(e))
        sys.exit(1)

    print(f"\n{result['total']} Treffer gefunden.\n")
    print_groups(result)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
