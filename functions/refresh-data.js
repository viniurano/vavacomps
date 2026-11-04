const REPOSITORY = "viniurano/vavacomps";
const WORKFLOW = "v4-auto-sync.yml";

function json(status, payload) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store"
    }
  });
}

export async function onRequestPost({ request, env }) {
  const requestUrl = new URL(request.url);
  const origin = request.headers.get("Origin");

  // A chamada é feita pelo próprio site; bloqueia requisições vindas de outros sites.
  if (origin && origin !== requestUrl.origin) {
    return json(403, { error: "Origem nao autorizada" });
  }

  const token = env.GITHUB_TOKEN;
  if (!token) {
    return json(503, { error: "GITHUB_TOKEN nao configurado nas secrets do Cloudflare Pages" });
  }

  let body;
  try {
    body = await request.json();
  } catch {
    return json(400, { error: "Corpo JSON invalido" });
  }

  const eventId = Number(body?.event_id);
  const teamId = Number(body?.team_id);
  if (!Number.isSafeInteger(eventId) || eventId <= 0 ||
      !Number.isSafeInteger(teamId) || teamId <= 0) {
    return json(400, { error: "IDs de campeonato/equipe invalidos" });
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
      return json(502, {
        error: "GitHub recusou a solicitacao (" + result.status + "): " + detail.slice(0, 240)
      });
    }

    return json(202, {
      status: "queued",
      event_id: eventId,
      team_id: teamId,
      message: "Atualizacao enviada ao GitHub Actions"
    });
  } catch (error) {
    return json(502, { error: "Falha ao contatar GitHub: " + String(error).slice(0, 180) });
  }
}

export async function onRequest(context) {
  if (context.request.method !== "POST") {
    return json(405, { error: "Metodo nao permitido" });
  }
  return onRequestPost(context);
}
