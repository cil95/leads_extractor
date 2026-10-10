// Vercel Serverless Function: läuft server-seitig auf Vercel, nicht im
// Browser. Hält BACKEND_API_KEY geheim (aus Vercel-Env-Variablen) und
// reicht die Suche an den Oracle-Server weiter. Der Browser bekommt den
// Key nie zu Gesicht.

export default async function handler(req, res) {
  if (req.method !== "POST") {
    res.status(405).json({ error: "Method not allowed" });
    return;
  }

  const { query, mode, debug } = req.body || {};
  if (!query || typeof query !== "string" || !query.trim()) {
    res.status(400).json({ error: "query darf nicht leer sein." });
    return;
  }

  const backendUrl = process.env.BACKEND_URL;
  const backendApiKey = process.env.BACKEND_API_KEY;
  if (!backendUrl) {
    res.status(500).json({ error: "BACKEND_URL ist auf Vercel nicht konfiguriert." });
    return;
  }

  const path = mode === "scrape" ? "/api/search/scrape" : "/api/search/places";

  try {
    const upstream = await fetch(`${backendUrl}${path}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(backendApiKey ? { "X-API-Key": backendApiKey } : {}),
      },
      body: JSON.stringify({ query, debug: !!debug }),
    });

    // Bei unbehandelten Fehlern antwortet FastAPI mit Klartext statt JSON.
    const text = await upstream.text();
    let data;
    try {
      data = JSON.parse(text);
    } catch {
      data = { error: `Backend-Fehler (HTTP ${upstream.status}): ${text.slice(0, 200)}` };
    }
    res.status(upstream.status).json(data);
  } catch (err) {
    res.status(502).json({ error: "Oracle-Backend nicht erreichbar." });
  }
}
