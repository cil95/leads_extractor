"""
Sucht bei Google (normale Websuche) nach einem Begriff wie "Friseure in Münster"
und teilt die Firmen aus dem lokalen Ergebnis-Block danach ein, ob sie eine
eigene Webseite (echter href-Link hinter dem "Website"-Button) und/oder eine
Online-Terminbuchung ("Termine"-Button) im Google-Profil hinterlegt haben.

Nutzung:
    python leads.py "Friseure in Münster"
    python leads.py "Friseure in Münster" --debug   (Stopp nach jeder Karte zur Kontrolle)

Hinweis:
    Google blockiert automatisierte Zugriffe auf /search sehr aggressiv
    (CAPTCHA). Dieses Skript tut deshalb so, als würde jemand ganz normal
    auf google.de tippen: erst die Startseite laden, Cookie-Banner
    wegklicken, den Suchbegriff Zeichen für Zeichen eintippen, Enter.
    Trotzdem kann es passieren, dass Google irgendwann ein CAPTCHA zeigt,
    vor allem bei häufigen/schnellen Wiederholungen. Das Skript bricht dann
    mit einer verständlichen Meldung ab statt falsche Ergebnisse zu liefern.

    Jede Karte im lokalen Ergebnis-Block besteht aus einem
    div[@class='rllt__details'] (Name, Bewertung, Öffnungszeiten, Telefon)
    und mehreren following-sibling <a>-Buttons auf derselben Ebene (Route,
    Website, ...). Der Name wird gezielt aus der Überschrift innerhalb von
    rllt__details gelesen statt aus einer beliebigen CSS-Klasse, weil
    Anzeigen-Karten dieselbe Klasse mehrfach für andere Texte
    (Anzeigentext, Dialogtitel) wiederverwenden.

    Die verwendeten Klassen/Struktur sind von Google selbst vergeben und
    können sich jederzeit ändern. Wenn das Skript plötzlich 0 Treffer
    findet, ist das der wahrscheinlichste Grund.
"""

import re
import sys
import urllib.parse

from lxml import html as lhtml
from playwright.sync_api import sync_playwright

from lead_groups import group_leads, print_groups

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Von jedem rllt__details-Div aus: 5x hoch zum gemeinsamen Vorfahren, dann
# unter dessen following-sibling-Buttons nach "Website" bzw. der Routen-URL
# suchen. Diese Buttons liegen NICHT innerhalb von rllt__details selbst.
XPATH_UP_TO_SIBLINGS = "../../../../../following-sibling::a"


def dismiss_button(page, texts, debug: bool = False) -> bool:
    """Klickt den ersten gefundenen Button aus `texts`, falls vorhanden.
    Für Pop-ups wie Cookie-Consent oder die Standortabfrage."""
    for text in texts:
        try:
            btn = page.get_by_role("button", name=text)
            if btn.count() > 0:
                btn.first.click(timeout=3000)
                page.wait_for_timeout(800)
                if debug:
                    print(f"[debug] Pop-up-Button geklickt: {text!r}")
                return True
        except Exception:
            pass
    return False


XPATH_NEXT_PAGE_BUTTON = "//a[@id='pnnext']//span"


def safe_content(page, retries: int = 5) -> str:
    """page.content() schlägt fehl, wenn die Seite gerade noch navigiert
    ("Unable to retrieve content because the page is navigating"). Auf
    einem langsamen Server (wenig RAM/CPU) dauert das Laden länger als
    die festen wait_for_timeout-Pausen einkalkulieren, deshalb hier
    zusätzlich auf den Ladezustand warten und notfalls mehrfach versuchen.
    """
    last_error = None
    for _ in range(retries):
        try:
            page.wait_for_load_state("domcontentloaded", timeout=5000)
        except Exception:
            pass
        try:
            return page.content()
        except Exception as e:
            last_error = e
            page.wait_for_timeout(500)
    raise last_error


def fetch_search_html(query: str, debug: bool = False) -> list[str]:
    """Sammelt das HTML aller Ergebnisseiten. Klickt so lange auf den
    "Weiter"-Button (//a[@id='pnnext']), bis dieser nicht mehr
    existiert - das ist dann die letzte Seite."""
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=not debug,
            slow_mo=150 if debug else 0,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            locale="de-DE",
            user_agent=USER_AGENT,
            viewport={"width": 1366, "height": 900},
        )
        page = context.new_page()
        page.goto("https://www.google.de/", timeout=60000)
        page.wait_for_timeout(1200)

        dismiss_button(page, ["Alle akzeptieren", "Ich stimme zu", "Accept all"], debug)

        box = page.locator("textarea[name=q], input[name=q]").first
        box.click()
        box.type(query, delay=70)
        page.wait_for_timeout(300)
        box.press("Enter")
        page.wait_for_timeout(3000)

        if debug:
            input(
                "[debug] Falls jetzt ein CAPTCHA angezeigt wird, bitte im Browser-"
                "Fenster von Hand lösen und danach hier Enter drücken ..."
            )

        # Google fragt bei lokalen Suchen manchmal per Pop-up nach dem Standort.
        dismiss_button(page, ["Später", "Nicht jetzt", "Not now"], debug)

        # Direkt zur lokalen Ergebnisliste (Tab "Orte") wechseln, statt nach
        # "Weitere Geschäfte"/"Orte"-Buttons zu suchen - deren Markup ändert
        # Google ständig, der URL-Parameter tbm=lcl bleibt dagegen stabil.
        # Ohne diesen Schritt landet die Paginierung in den normalen
        # Web-Ergebnissen, in denen es keine rllt__details-Karten gibt.
        page.goto(page.url + "&tbm=lcl", timeout=60000)
        page.wait_for_timeout(3000)
        if debug:
            print(f"[debug] Lokale Ergebnisliste geöffnet: {page.url}")

        if debug:
            page.wait_for_timeout(3000)  # Zeit, das Ergebnis im Browserfenster zu sehen

        pages_html = []
        page_num = 1
        while True:
            html = safe_content(page)
            pages_html.append(html)
            if debug:
                print(f"[debug] Seite {page_num} eingesammelt ({len(html)} Zeichen)")

            next_button = page.locator(f"xpath={XPATH_NEXT_PAGE_BUTTON}")
            if next_button.count() == 0:
                if debug:
                    print(
                        "[debug] Kein 'Weiter'-Button mehr gefunden - letzte Seite erreicht"
                    )
                break

            try:
                next_button.first.click(timeout=3000)
                page.wait_for_timeout(2000)
                page_num += 1
            except Exception as e:
                if debug:
                    print(f"[debug] Klick auf 'Weiter' fehlgeschlagen: {e}")
                break

        browser.close()
        return pages_html


def looks_like_captcha(html: str) -> bool:
    return (
        "g-recaptcha" in html
        or "unser System hat" in html.lower()
        or "captcha-form" in html
    )


def extract_name(details) -> str | None:
    """Titel = //div[@class='rllt__details']//div[@role='heading']/span."""
    heading = details.xpath(".//div[@role='heading']/span")
    return heading[0].text_content().strip() if heading else None


def extract_website(details) -> tuple[str | None, str | None]:
    """Prüft den Website-Button auf gleicher Ebene wie rllt__details:
    .../following-sibling::a//span[text()='Website'], und liest dessen href.

    Gibt (gewertete_url_oder_None, roher_href_oder_None) zurück. Die rohe
    href wird immer zurückgegeben, damit man im --debug-Modus sieht, WAS
    gefunden wurde, auch wenn es als "keine echte Webseite" gewertet wird
    (z.B. ein /aclk-Anzeigen-Redirect statt einer echten Domain).
    """
    website_span = details.xpath(f"{XPATH_UP_TO_SIBLINGS}//span[text()='Website']")
    if not website_span:
        return None, None
    a = website_span[0].xpath("ancestor::a[1]")
    if not a:
        return None, None
    href = a[0].get("href")
    if href and href.startswith("http") and "google." not in href:
        return href, href
    # Google verlinkt Firmenwebsites inzwischen über die eigene Weiterleitung
    # /goto?url=<verschlüsselt> statt direkt. Das ist trotzdem eine echte
    # Website (Anzeigen laufen dagegen über /aclk).
    if href and href.startswith("/goto?"):
        return f"https://www.google.com{href}", href
    return None, href


def extract_booking(details) -> bool:
    """Prüft den Termine-Button auf gleicher Ebene wie rllt__details:
    .../following-sibling::a//div[text()='Termine']. Der Link dahinter
    (z.B. Planity, Treatwell) ist egal - nur ob es den Button gibt."""
    return bool(details.xpath(f"{XPATH_UP_TO_SIBLINGS}//div[text()='Termine']"))


def extract_address(details) -> str | None:
    dir_a = details.xpath(f"{XPATH_UP_TO_SIBLINGS}[starts-with(@href, '/maps/dir/')]")
    if not dir_a:
        return None
    m = re.search(r"/maps/dir//([^/]+)/data=", dir_a[0].get("href", ""))
    return urllib.parse.unquote_plus(m.group(1)) if m else None


def extract_phone(details) -> str | None:
    text = details.text_content()
    m = re.search(r"0\d{2,4}[\s/-]?\d{3,}[\d\s/-]*", text)
    return m.group(0).strip() if m else None


def extract_rating(details) -> str | None:
    rating_el = details.xpath(".//span[contains(@class,'yi40Hd')]")
    count_el = details.xpath(".//span[contains(@class,'RDApEe')]")
    if not rating_el:
        return None
    rating = rating_el[0].text_content().strip()
    count = count_el[0].text_content().strip() if count_el else ""
    return f"{rating} {count}".strip()


def is_sponsored(details) -> bool:
    return bool(details.xpath(".//span[normalize-space(text())='Gesponsert']"))


class CaptchaError(Exception):
    """Google hat statt Ergebnissen ein CAPTCHA gezeigt."""


class NoResultsError(Exception):
    """Kein lokaler Ergebnis-Block im HTML gefunden."""


def search(query: str, debug: bool = False) -> dict:
    """Führt die komplette Suche aus und gibt ein strukturiertes Ergebnis
    zurück, statt es auf stdout zu drucken. Wird sowohl vom CLI-Einstieg
    (main()) als auch vom API-Server (server.py) genutzt.

    Wirft CaptchaError bzw. NoResultsError statt sys.exit(), damit der
    Aufrufer (z.B. eine HTTP-Route) den Fehler sauber behandeln kann.
    """
    pages_html = fetch_search_html(query, debug=debug)

    if debug:
        for i, html in enumerate(pages_html, start=1):
            fname = f"debug_full_seite{i}.html"
            with open(fname, "w", encoding="utf-8") as f:
                f.write(html)

    if any(looks_like_captcha(html) for html in pages_html):
        raise CaptchaError(
            "Google hat ein CAPTCHA angezeigt statt der Suchergebnisse. "
            "Das passiert v.a. bei zu häufigen/schnellen Anfragen von derselben IP."
        )

    detail_cards = []
    for html in pages_html:
        tree = lhtml.fromstring(html)
        detail_cards.extend(tree.xpath("//div[@class='rllt__details']"))

    if not detail_cards:
        raise NoResultsError(
            "Kein lokaler Ergebnis-Block gefunden. Entweder liefert Google für "
            "diesen Suchbegriff keinen lokalen Block, oder Google hat sein HTML "
            "geändert und die XPath-Ausdrücke im Skript müssen aktualisiert werden."
        )

    results = []
    for i, details in enumerate(detail_cards, start=1):
        name = extract_name(details) or "(unbekannt)"
        sponsored = is_sponsored(details)
        website, raw_href = extract_website(details)
        booking = extract_booking(details)
        address = extract_address(details)
        phone = extract_phone(details)
        rating = extract_rating(details)

        if debug:
            print(f"\n{'=' * 70}")
            print(f"[debug] Karte {i}/{len(detail_cards)} - rohes HTML dieser Karte:\n")
            print(lhtml.tostring(details, pretty_print=True, encoding="unicode"))

        results.append(
            {
                "name": name,
                "sponsored": sponsored,
                "website": website,
                "booking": booking,
                "address": address,
                "phone": phone,
                "rating": rating,
            }
        )

    organic = [r for r in results if not r["sponsored"]]
    sponsored_results = [r for r in results if r["sponsored"]]

    return {
        "query": query,
        "total": len(results),
        **group_leads(organic),
        "sponsored": sponsored_results,
    }


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    debug = "--debug" in sys.argv

    if not args:
        print(
            'Nutzung: python leads.py "Suchbegriff, z.B. Friseure in Münster" [--debug]'
        )
        sys.exit(1)

    query = args[0]
    print(f"Suche bei Google: {query!r} ...")

    try:
        result = search(query, debug=debug)
    except CaptchaError as e:
        print(str(e))
        sys.exit(2)
    except NoResultsError as e:
        print(str(e))
        sys.exit(3)

    sponsored_results = result["sponsored"]

    print(f"\n{result['total']} Treffer im lokalen Ergebnis-Block gefunden.")
    if sponsored_results:
        print(
            f"  -> {len(sponsored_results)} davon Anzeigen (Gesponsert) - ausgeschlossen, da unzuverlässig"
        )
    print()

    print_groups(result)

    if sponsored_results:
        print(
            "=== Ausgeschlossen (Anzeigen, keine verlässliche Aussage über Webseite) ===\n"
        )
        for r in sponsored_results:
            print(
                f"- {r['name']}  (roher Website-Link: {r['website'] or 'keiner/Ad-Redirect'})"
            )


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
