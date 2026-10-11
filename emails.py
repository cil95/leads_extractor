"""
Sucht E-Mail-Adressen auf den Webseiten der gefundenen Firmen.

Google-Profile enthalten keine E-Mail-Adressen, weder in der Places API
noch auf der Suchseite. Deshalb wird die hinterlegte Webseite geladen:
erst die Startseite, und falls dort keine Adresse steht, Impressum- und
Kontaktseite (deutsche Webseiten müssen ein Impressum haben, darin steht
fast immer eine E-Mail).

Läuft mit einfachen HTTP-Requests (kein Chromium) und mehreren Threads
parallel - das ist I/O-lastig und braucht kaum RAM, passt also auch auf
den 1-GB-Server.
"""

import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

import requests
from lxml import html as lhtml

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
TIMEOUT = 8
MAX_WORKERS = 12
# Unterseiten, auf denen typischerweise die E-Mail steht.
SUBPAGE_KEYWORDS = ("impressum", "kontakt", "contact", "imprint")
MAX_SUBPAGES = 3

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# Häufige Verschleierung im Impressum: "info [at] firma [dot] de"
AT_RE = re.compile(r"\s*[\[\(\{]\s*(?:at|@)\s*[\]\)\}]\s*", re.I)
DOT_RE = re.compile(r"\s*[\[\(\{]\s*(?:dot|punkt)\s*[\]\)\}]\s*", re.I)

# Treffer, die wie E-Mails aussehen, aber keine sind (Bilddateien wie
# "logo@2x.png") oder zu Baukasten-/Tracking-Anbietern gehören.
IGNORED_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".js", ".css")
IGNORED_DOMAINS = (
    "example.com",
    "sentry.io",
    "wixpress.com",
    "sentry.wixpress.com",
    "sentry-next.wixpress.com",
    "domain.de",
    "domain.com",
    "email.com",
    "jimdo.com",
    "google.com",
    # Verzeichnis-/Buchungsplattformen: deren Adresse ist nicht die der Firma
    "ivof.com",
    "treatwell.de",
    "planity.com",
    "fresha.com",
)


def _fetch(session: requests.Session, url: str) -> requests.Response | None:
    try:
        resp = session.get(url, timeout=TIMEOUT)
    except requests.RequestException:
        return None
    if resp.status_code != 200 or "html" not in resp.headers.get("Content-Type", "html"):
        return None
    return resp


def _extract_emails(text: str) -> list[str]:
    text = DOT_RE.sub(".", AT_RE.sub("@", text))
    found = []
    for e in EMAIL_RE.findall(text):
        e = e.strip(".").lower()
        domain = e.split("@", 1)[1]
        if e.endswith(IGNORED_SUFFIXES) or domain in IGNORED_DOMAINS:
            continue
        if e not in found:
            found.append(e)
    return found


def _emails_from_page(resp: requests.Response) -> tuple[list[str], list[str]]:
    """Gibt (E-Mails, Links auf Impressum/Kontakt) dieser Seite zurück."""
    try:
        tree = lhtml.fromstring(resp.text)
    except Exception:
        return _extract_emails(resp.text), []

    mailtos = [
        urllib.parse.unquote(href[7:].split("?", 1)[0])
        for href in tree.xpath("//a[starts-with(translate(@href,'MAILTO','mailto'),'mailto:')]/@href")
    ]
    # itertext statt text_content: sonst kleben Texte benachbarter Elemente
    # zusammen ("mail@firma.de" + "Internet" -> "mail@firma.deinternet").
    emails = _extract_emails(" ".join(mailtos) + " " + " ".join(tree.itertext()))

    subpages = []
    for a in tree.xpath("//a[@href]"):
        label = (a.get("href", "") + " " + a.text_content()).lower()
        if any(k in label for k in SUBPAGE_KEYWORDS):
            url = urllib.parse.urljoin(resp.url, a.get("href"))
            if url.startswith("http") and url not in subpages:
                subpages.append(url)
    return emails, subpages[:MAX_SUBPAGES]


def find_emails(website: str) -> tuple[list[str], str]:
    """Gibt (gefundene E-Mails, aufgelöste Webseiten-URL) zurück. Die URL
    ist nach Weiterleitungen die echte Domain - wichtig für die
    /goto?url=...-Links aus dem Scraping."""
    with requests.Session() as session:
        session.headers["User-Agent"] = USER_AGENT
        resp = _fetch(session, website)
        if resp is None:
            return [], website
        emails, subpages = _emails_from_page(resp)
        for url in subpages:
            if emails:
                break
            sub = _fetch(session, url)
            if sub is not None:
                emails = _emails_from_page(sub)[0]
        # Adressen mit der Domain der Webseite zuerst (info@firma.de vor
        # z.B. der Adresse des Webdesigners im Impressum).
        host = urllib.parse.urlparse(resp.url).netloc.lower().removeprefix("www.")
        emails.sort(key=lambda e: not host.endswith(e.split("@", 1)[1]))
        return emails, resp.url


def add_emails(results: list[dict]) -> None:
    """Ergänzt jeden Treffer mit Webseite um "email" (erste gefundene
    Adresse oder None) und ersetzt "website" durch die aufgelöste URL."""
    with_site = [r for r in results if r.get("website")]
    for r in results:
        r.setdefault("email", None)

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        for r, (emails, final_url) in zip(
            with_site, pool.map(lambda r: find_emails(r["website"]), with_site)
        ):
            r["email"] = emails[0] if emails else None
            r["website"] = final_url
