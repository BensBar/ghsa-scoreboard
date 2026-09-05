const byId = (id) => document.getElementById(id);
const option = (game) => {
  const element = document.createElement("option");
  element.value = game.id;
  element.textContent = `${game.awayTeam.name} @ ${game.homeTeam.name}`;
  return element;
};

async function loadGames() {
  const response = await fetch("../api/v1/scoreboard");
  const data = await response.json();
  byId("game").replaceChildren(...data.games.map(option));
}

byId("report-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const response = await fetch("../api/v1/reporters/score", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({
      reporterId: byId("reporter-id").value,
      secret: byId("secret").value,
      gameId: byId("game").value,
      homeScore: Number(byId("home-score").value),
      awayScore: Number(byId("away-score").value),
      status: byId("status").value,
      clock: byId("clock").value || null,
    }),
  });
  const data = await response.json();
  byId("result").textContent = response.ok
    ? "Verified update published."
    : `Update rejected: ${data.error}`;
});

loadGames().catch(() => { byId("result").textContent = "Could not load games."; });
