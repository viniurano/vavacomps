const ALLOWED_ORIGINS = new Set([
  "https://poetic-sunshine-55c175.netlify.app"
]);
const REPOSITORY = "viniurano/vavacomps";
const WORKFLOW = "v4-auto-sync.yml";

function json(statusCode, payload, origin) {
  return {
    statusCode,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
      ...(origin ? { "Access-Control-Allow-Origin": origin, "Vary": "Origin" } : {})
    },
    body: JSON.stringify(payload)
  };
}

export default async (request) => {
  const origin = request.headers.get("origin") || "";
  if (request.method === "OPTIONS") {
    if (!ALLOWED_ORIGINS.has(origin)) return json(403, { error: "Origem nao autorizada" });
    return {
      statusCode: 204,
      headers: {
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Methods": "POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
        "Access-Control-Max-Age": "600",
        "Vary": "Origin"
      }
    };
  }
  if (request.method !== "POST") return json(405, { error: "Metodo nao permitido" });
  if (!ALLOWED_ORIGINS.has(origin)) return json(403, { error: "Origem nao autorizada" });

  const token = process.env.GITHUB_TOKEN;
  if (!token) return json(503, { error: "GITHUB_TOKEN nao configurado nas variaveis do Netlify" }, origin);

  let body;
  try { body = await request.json(); }
  catch { return json(400, { error: "Corpo JSON invalido" }, origin); }

  const eventId = Number(body?.event_id);
  const teamId = Number(body?.team_id);
  if (!Number.isSafeInteger(eventId) || eventId <= 0 ||
      !Number.isSafeInteger(teamId) || teamId <= 0) {
    return json(400, { error: "IDs de campeonato/equipe invalidos" }, origin);
  }

  try {
    const response = await fetch(
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
    if (response.status !== 204) {
      const detail = await response.text();
      return json(502, {
        error: "GitHub recusou a solicitacao (" + response.status + "): " + detail.slice(0, 240)
      }, origin);
    }
    return json(202, {
      status: "queued",
      event_id: eventId,
      team_id: teamId,
      message: "Atualizacao enviada ao GitHub Actions"
    }, origin);
  } catch (error) {
    return json(502, { error: "Falha ao contatar GitHub: " + String(error).slice(0, 180) }, origin);
  }
};
