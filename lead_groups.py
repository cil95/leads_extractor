"""
Gemeinsame Einteilung der Treffer aus leads.py und leads_places.py in
vier Gruppen - je nachdem, ob eine Webseite und/oder eine Online-
Terminbuchung im Google-Profil hinterlegt ist.

Jeder Treffer braucht dafür die Felder "website" (URL oder None) und
"booking" (bool).
"""

GROUP_TITLES = {
    "none": "Weder Webseite noch Terminbuchung",
    "booking_only": "Nur Terminbuchung, keine Webseite",
    "website_only": "Nur Webseite, keine Terminbuchung",
    "both": "Webseite und Terminbuchung",
}


def group_leads(results: list[dict]) -> dict:
    return {
        "none": [r for r in results if not r["website"] and not r["booking"]],
        "booking_only": [r for r in results if not r["website"] and r["booking"]],
        "website_only": [r for r in results if r["website"] and not r["booking"]],
        "both": [r for r in results if r["website"] and r["booking"]],
    }


def print_groups(result: dict):
    """CLI-Ausgabe der vier Gruppen."""
    for key, title in GROUP_TITLES.items():
        rows = result[key]
        print(f"=== {title} ({len(rows)}) ===\n")
        for r in rows:
            print(f"- {r['name']}")
            if r["website"]:
                print(f"    Webseite : {r['website']}")
            if r["address"]:
                print(f"    Adresse  : {r['address']}")
            if r["phone"]:
                print(f"    Telefon  : {r['phone']}")
            if r["rating"]:
                print(f"    Bewertung: {r['rating']}")
        print()
