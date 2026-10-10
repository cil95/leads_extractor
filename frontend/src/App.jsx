import { useState } from "react";

const MODES = {
  places: {
    label: "Places API (schnell, zuverlässig, kostenpflichtig)",
  },
  scrape: {
    label: "Google-Scraping (Chromium, langsamer, Captcha-Risiko)",
  },
};

const GROUPS = [
  { key: "none", title: "Weder Webseite noch Terminbuchung", defaultOpen: true },
  { key: "booking_only", title: "Nur Terminbuchung, keine Webseite", defaultOpen: true },
  { key: "website_only", title: "Nur Webseite, keine Terminbuchung", defaultOpen: false },
  { key: "both", title: "Webseite und Terminbuchung", defaultOpen: false },
];

function LeadTable({ title, rows, showWebsite, collapsible, defaultOpen = true }) {
  const [open, setOpen] = useState(defaultOpen);

  if (!rows || rows.length === 0) return null;

  return (
    <div className="result-block">
      <h3
        className={collapsible ? "collapsible" : ""}
        onClick={collapsible ? () => setOpen((o) => !o) : undefined}
      >
        {collapsible && <span className="chevron">{open ? "▾" : "▸"}</span>}
        {title} ({rows.length})
      </h3>
      {(!collapsible || open) && (
        <table>
          <thead>
            <tr>
              <th>Name</th>
              <th>Adresse</th>
              <th>Telefon</th>
              <th>Bewertung</th>
              {showWebsite && <th>Webseite</th>}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}>
                <td>{r.name}</td>
                <td>{r.address || "-"}</td>
                <td>{r.phone || "-"}</td>
                <td>{r.rating || "-"}</td>
                {showWebsite && (
                  <td>
                    <a href={r.website} target="_blank" rel="noreferrer">
                      {new URL(r.website).hostname}
                    </a>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

export default function App() {
  const [query, setQuery] = useState("");
  const [mode, setMode] = useState("places");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);

  async function handleSubmit(e) {
    e.preventDefault();
    if (!query.trim()) return;

    setLoading(true);
    setError(null);
    setResult(null);

    try {
      const res = await fetch("/api/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query, mode }),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.error || data.detail || "Unbekannter Fehler");
      }
      setResult(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="app">
      <h1>Leads Finder</h1>
      <p className="subtitle">
        Firmen ohne eigene Webseite finden – als Leads für Webdesign-Akquise.
      </p>

      <form onSubmit={handleSubmit} className="search-form">
        <input
          type="text"
          placeholder='z.B. "Friseure in Münster"'
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />

        <div className="mode-toggle">
          {Object.entries(MODES).map(([key, { label }]) => (
            <label key={key} className={mode === key ? "active" : ""}>
              <input
                type="radio"
                name="mode"
                value={key}
                checked={mode === key}
                onChange={() => setMode(key)}
              />
              {label}
            </label>
          ))}
        </div>

        <button type="submit" disabled={loading || !query.trim()}>
          {loading ? "Suche läuft..." : "Suchen"}
        </button>
      </form>

      {error && <div className="error">{error}</div>}

      {result && (
        <div className="results">
          <p className="summary">
            {result.total} Treffer für "{result.query}" –{" "}
            {GROUPS.map((g) => `${result[g.key]?.length || 0} ${g.title.toLowerCase()}`).join(", ")}
          </p>
          {mode === "places" && (
            <p className="hint">
              Hinweis: Die Places API kennt den „Online buchen“-Button nicht. Terminbuchung wird hier
              nur erkannt, wenn das Website-Feld auf eine Buchungsplattform zeigt. Für den Button
              Google-Scraping verwenden.
            </p>
          )}
          {GROUPS.map((g) => (
            <LeadTable
              key={g.key}
              title={g.title}
              rows={result[g.key]}
              showWebsite={g.key === "website_only" || g.key === "both"}
              collapsible
              defaultOpen={g.defaultOpen}
            />
          ))}
        </div>
      )}
    </div>
  );
}
