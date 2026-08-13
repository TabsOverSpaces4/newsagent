interface Env {
  DB: D1Database;
  HMAC_SECRET: string;
  EXPORT_SECRET: string;
  CAT_API_KEY: string;
}

async function verifyHmac(sid: string, score: string, token: string, secret: string): Promise<boolean> {
  const key = await crypto.subtle.importKey(
    "raw", new TextEncoder().encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"],
  );
  const sig = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(sid + score));
  const expected = [...new Uint8Array(sig)].map(b => b.toString(16).padStart(2, "0")).join("");
  return expected === token;
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);

    if (url.pathname === "/rate") {
      const sid = url.searchParams.get("sid") ?? "";
      const s = url.searchParams.get("s") ?? "";
      const t = url.searchParams.get("t") ?? "";
      if (!sid || !s || !t || !await verifyHmac(sid, s, t, env.HMAC_SECRET)) {
        return new Response("Forbidden", { status: 403 });
      }
      const score = parseInt(s, 10);
      if (isNaN(score) || score < 0 || score > 10) {
        return new Response("Bad score", { status: 400 });
      }
      await env.DB.prepare(
        "INSERT INTO ratings (story_id, url, source, title, score, run_date) VALUES (?, ?, ?, ?, ?, ?)",
      ).bind(
        sid,
        url.searchParams.get("url") ?? "",
        url.searchParams.get("source") ?? "",
        url.searchParams.get("title") ?? "",
        score,
        url.searchParams.get("rd") ?? "",
      ).run();

      const label = score === 0 ? "Skip" : score <= 4 ? "Meh" : score <= 7 ? "Good" : "Great";

      let catHtml = "";
      try {
        const catRes = await fetch("https://api.thecatapi.com/v1/images/search?mime_types=jpg,png", {
          headers: { "x-api-key": env.CAT_API_KEY },
        });
        const cats = await catRes.json<{ url: string }[]>();
        if (cats?.[0]?.url) {
          catHtml =
            `<p style="color:#4A5A66;margin-top:8px;">Here's a random cat as a reward \u2192</p>` +
            `<img src="${cats[0].url}" alt="Random cat" style="max-width:360px;width:100%;border-radius:12px;margin-top:12px;box-shadow:0 2px 12px rgba(0,0,0,0.1);" />`;
        }
      } catch { /* cat fetch failed, no big deal */ }

      return new Response(
        `<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Rated</title></head>` +
        `<body style="font-family:system-ui,sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;background:#F2F5F6;color:#0B1F2A;">` +
        `<div style="text-align:center;padding:32px;max-width:420px;">` +
        `<p style="font-size:24px;font-weight:600;margin-bottom:4px;">Thanks!</p>` +
        `<p style="color:#4A5A66;">You rated this story <strong>${score}/10</strong> (${label}).</p>` +
        `${catHtml}` +
        `</div></body></html>`,
        { headers: { "Content-Type": "text/html;charset=utf-8" } },
      );
    }

    if (url.pathname === "/export") {
      if (url.searchParams.get("secret") !== env.EXPORT_SECRET) {
        return new Response("Forbidden", { status: 403 });
      }
      const ratings = await env.DB.prepare(
        "SELECT story_id, url, source, title, score, run_date, rated_at FROM ratings WHERE rated_at >= datetime('now', '-90 days') ORDER BY rated_at DESC",
      ).all();
      const affinity = await env.DB.prepare(
        "SELECT source, ROUND(AVG(score), 2) AS avg_score, COUNT(*) AS count FROM ratings WHERE rated_at >= datetime('now', '-90 days') AND source != '' GROUP BY source ORDER BY avg_score DESC",
      ).all();
      return Response.json({ ratings: ratings.results, source_affinity: affinity.results });
    }

    return new Response("Not found", { status: 404 });
  },
} satisfies ExportedHandler<Env>;
