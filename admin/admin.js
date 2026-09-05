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
