const byId = (id) => document.getElementById(id);
const escapeHtml = (value) => String(value).replace(/[&<>"']/g, (character) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
})[character]);

async function loadGames() {
  const response = await fetch("/api/v1/scoreboard");
  const data = await response.json();
  byId("game").innerHTML = data.games.map((game) =>
    `<option value="${escapeHtml(game.id)}">${escapeHtml(game.awayTeam.name)} @ ${escapeHtml(game.homeTeam.name)} — ${escapeHtml(game.status)}</option>`
  ).join("");
  byId("radio-game").innerHTML = byId("game").innerHTML;
}

byId("correction-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const updates = {};
  for (const [field, id] of [["homeScore", "home-score"], ["awayScore", "away-score"]]) {
    if (byId(id).value !== "") updates[field] = Number(byId(id).value);
  }
  if (byId("status").value) updates.status = byId("status").value;
  const response = await fetch("/api/v1/admin/corrections", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Authorization": ["Bearer", byId("token").value].join(" "),
    },
    body: JSON.stringify({
      gameId: byId("game").value, updates, reason: byId("reason").value,
      actor: byId("actor").value,
    }),
  });
  const data = await response.json();
  byId("result").textContent = response.ok
    ? `Saved correction ${data.correctionIds.join(", ")}.`
    : `Correction failed: ${data.error}`;
  if (response.ok) {
    byId("reason").value = "";
    await loadGames();
  }
});

loadGames().catch(() => { byId("result").textContent = "Could not load games."; });

async function adminPost(path, payload) {
  const response = await fetch(path, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Authorization": ["Bearer", byId("token").value].join(" "),
    },
    body: JSON.stringify(payload),
  });
  return [response, await response.json()];
}

byId("reporter-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const [response, data] = await adminPost("/api/v1/admin/reporters", {
    id: byId("new-reporter-id").value,
    name: byId("new-reporter-name").value,
    teamIds: byId("new-reporter-teams").value.split(",").map((value) => value.trim()).filter(Boolean),
    secret: byId("new-reporter-secret").value,
  });
  byId("reporter-result").textContent = response.ok
    ? `Reporter ${data.reporterId} enrolled.`
    : `Enrollment failed: ${data.error}`;
});

byId("source-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const [response, data] = await adminPost("/api/v1/admin/sources", {
    id: byId("source-id").value,
    name: byId("source-name").value,
    kind: byId("source-kind").value,
    homepageUrl: byId("source-homepage").value || null,
    streamUrl: byId("source-stream").value || null,
    permissionStatus: "granted",
    permissionNote: byId("source-note").value,
    enabled: true,
    attribution: byId("source-name").value,
  });

  byId("source-result").textContent = response.ok
    ? `Source ${data.sourceId} approved.`
    : `Source failed: ${data.error}`;
});

byId("radio-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const [response, data] = await adminPost("/api/v1/admin/radio-observations", {
    sourceId: byId("radio-source-id").value,
    gameId: byId("radio-game").value,
    transcript: byId("radio-transcript").value,
  });
  byId("radio-result").textContent = response.ok
    ? `Extracted ${data.extracted} observation(s); ${data.results.filter((item) => item.published).length} published.`
    : `Extraction failed: ${data.error}`;
  byId("radio-transcript").value = "";
});
