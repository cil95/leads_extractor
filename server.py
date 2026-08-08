"""
Kleiner API-Server, der leads.py (Google-Scraping via Chromium) und
leads_places.py (offizielle Places API) über HTTP verfügbar macht.
Läuft auf dem Oracle-Server, das Vercel-Frontend spricht darüber mit
den Skripten statt sie direkt aufzurufen.

Start (lokal):
    uvicorn server:app --reload

Start (Produktion, siehe deploy/leads-api.service):
    uvicorn server:app --host 0.0.0.0 --port 8000

Env-Variablen (.env):
    GOOGLE_MAPS_API_KEY  - für leads_places.py
    API_KEY              - eigener Schlüssel, den das Frontend im Header
                            "X-API-Key" mitschicken muss. Ohne diesen Key
                            kann jeder deinen Server für Suchen missbrauchen.

Der /api/search/scrape-Endpunkt startet einen echten Chromium-Browser
(Playwright). Der Oracle-Server hat nur 1 GB RAM, deshalb läuft davon
IMMER nur eine Anfrage gleichzeitig (siehe SCRAPE_LOCK) - eine zweite
gleichzeitige Anfrage wartet, statt eine zweite Chromium-Instanz zu
starten und den Server zum Absturz zu bringen.
"""

import asyncio
import os

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import leads
import leads_places

load_dotenv()

API_KEY = os.environ.get("API_KEY")
ALLOWED_ORIGINS = [
    o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()
]

app = FastAPI(title="Leads API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS or ["*"],
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)

# Nur eine Chromium-Instanz gleichzeitig - der Server hat nur 1 GB RAM.
scrape_lock = asyncio.Lock()


class SearchRequest(BaseModel):
    query: str
    debug: bool = False


def check_api_key(x_api_key: str | None):
    if not API_KEY:
        # Kein Key konfiguriert -> Server bewusst offen (z.B. lokales Testen).
        return
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Ungültiger oder fehlender X-API-Key Header.")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/search/places")
async def search_places_endpoint(req: SearchRequest, x_api_key: str | None = Header(default=None)):
    check_api_key(x_api_key)
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="query darf nicht leer sein.")

    try:
        result = await asyncio.to_thread(leads_places.search, req.query, None, req.debug)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))

    return result


@app.post("/api/search/scrape")
async def search_scrape_endpoint(req: SearchRequest, x_api_key: str | None = Header(default=None)):
    check_api_key(x_api_key)
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="query darf nicht leer sein.")

    if scrape_lock.locked():
        raise HTTPException(
            status_code=429,
            detail="Es läuft bereits eine Chromium-Suche. Bitte kurz warten und erneut versuchen.",
        )

    async with scrape_lock:
        try:
            result = await asyncio.to_thread(leads.search, req.query, req.debug)
        except leads.CaptchaError as e:
            raise HTTPException(status_code=429, detail=str(e))
        except leads.NoResultsError as e:
            raise HTTPException(status_code=404, detail=str(e))

    return result
