const ALLOWED_ORIGINS = new Set([
  "https://poetic-sunshine-55c175.netlify.app"
  "https://regal-croissant-fffaa0.netlify.app"
]);
const REPOSITORY = "viniurano/vavacomps";
const WORKFLOW = "v4-auto-sync.yml";
const cooldowns = new Map();

function response(status, payload, origin = "") {
  return new Response(JSON.stringify(payload), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
      ...(origin ? { "Access-Control-Allow-Origin": origin, "Vary": "Origin" } : {})
    }
  });
}

export default async (request) => {
  const origin = request.headers.get("origin") || "";
  if (request.method === "OPTIONS") {
    if (!ALLOWED_ORIGINS.has(origin)) return response(403, { error: "Origem nao autorizada" });
    return new Response(null, {
      status: 204,
      headers: {
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Methods": "POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
        "Access-Control-Max-Age": "600",
        "Vary": "Origin"
      }
    });
  }
  if (request.method !== "POST") return response(405, { error: "Metodo nao permitido" });
  if (!ALLOWED_ORIGINS.has(origin)) return response(403, { error: "Origem nao autorizada" });

  const token = process.env.GITHUB_TOKEN;
  if (!token) return response(503, { error: "GITHUB_TOKEN nao configurado nas variaveis do Netlify" }, origin);

  let body;
  try { body = await request.json(); }
  catch { return response(400, { error: "Corpo JSON invalido" }, origin); }

  const eventId = Number(body?.event_id);
  const teamId = Number(body?.team_id);
  if (!Number.isSafeInteger(eventId) || eventId <= 0 ||
      !Number.isSafeInteger(teamId) || teamId <= 0) {
    return response(400, { error: "IDs de campeonato/equipe invalidos" }, origin);
  }

  const cooldownKey = eventId + ":" + teamId;
  const now = Date.now();
  const last = cooldowns.get(cooldownKey) || 0;
  if (now - last < 120000) {
    return response(429, { error: "Ja existe uma solicitacao recente para esta equipe. Aguarde dois minutos." }, origin);
  }

  try {
    const result = await fetch(
      `https://api.github.com/repos/${REPOSITORY}/actions/workflows/${WORKFLOW}/dispatches`,
      {
        method: "POST",
        headers: {
          "Accept": "application/vnd.github+json",
          "Authorization": `Bearer ${token}`,
          "X-GitHub-Api-Version": "2022-11-28",
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          ref: "main",
          inputs: {
            task: "team_refresh",
            event_id: String(eventId),
            team_id: String(teamId)
          }
        })
      }
    );
    if (result.status !== 204) {
      const detail = await result.text();
      return response(502, {
        error: "GitHub recusou a solicitacao (" + result.status + "): " + detail.slice(0, 240)
      }, origin);
    }
    cooldowns.set(cooldownKey, now);
    return response(202, {
      status: "queued",
      event_id: eventId,
      team_id: teamId,
      message: "Atualizacao enviada ao GitHub Actions"
    }, origin);
  } catch (error) {
    return response(502, { error: "Falha ao contatar GitHub: " + String(error).slice(0, 180) }, origin);
  }
};
