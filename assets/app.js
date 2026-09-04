const REFRESH_MS = 45000;
const SCORES_URL = "public/scores.json";

const STATUS_CLASS = {
  scheduled: "status-scheduled",
  Q1: "status-live",
  Q2: "status-live",
  Q3: "status-live",
  Q4: "status-live",
  HALF: "status-half",
  FINAL: "status-final",
  OT: "status-ot",
};

function isLiveStatus(status) {
  return ["Q1", "Q2", "Q3", "Q4", "HALF", "OT"].includes(status);
}

function formatKickoff(iso) {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    return d.toLocaleString("en-US", {
      timeZone: "America/New_York",
      weekday: "short",
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
      timeZoneName: "short",
    });
  } catch {
    return iso;
  }
}

function formatUpdated(iso) {
  if (!iso) return "Updated —";
  try {
    const d = new Date(iso);
    return "Updated " + d.toLocaleString("en-US", {
      timeZone: "America/New_York",
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
      second: "2-digit",
      timeZoneName: "short",
    });
  } catch {
    return "Updated " + iso;
  }
}

function displayScores(game) {
  // homeScore/awayScore are stadium home/away.
  // For pinned cards we show OUR school score on the left, opponent on the right.
  const ours = game.isHome ? game.homeScore : game.awayScore;
  const theirs = game.isHome ? game.awayScore : game.homeScore;
  return { ours, theirs };
}

function scoreText(n) {
  return n === null || n === undefined ? "—" : String(n);
}

function statusBadge(status) {
  const cls = STATUS_CLASS[status] || "status-scheduled";
  return `<span class="status-badge ${cls}">${status || "scheduled"}</span>`;
}

function renderPinned(games) {
  const root = document.getElementById("pinned");
  if (!games || !games.length) {
    root.innerHTML = `<div class="empty">No pinned games yet.</div>`;
    return;
  }
  root.innerHTML = games.map((g) => {
    const { ours, theirs } = displayScores(g);
    const ha = g.isHome ? "HOME" : "AWAY";
    return `
      <article class="card" role="listitem" data-id="${g.id}">
        <div class="card-top">
          <div>
            <h3 class="school-name">${escapeHtml(g.name)}</h3>
            <p class="vs-line">vs <strong>${escapeHtml(g.opponent)}</strong>
              <span class="ha-tag">${ha}</span>
            </p>
          </div>
          ${statusBadge(g.status)}
        </div>
        <div class="scoreboard">
          <div class="team-col">
            <div class="team-label">Us</div>
            <div class="team-name">${escapeHtml(g.name)}</div>
            <div class="score ours">${scoreText(ours)}</div>
          </div>
          <div class="mid">VS</div>
          <div class="team-col right">
            <div class="team-label">Opp</div>
            <div class="team-name">${escapeHtml(g.opponent)}</div>
            <div class="score theirs">${scoreText(theirs)}</div>
          </div>
        </div>
        <p class="kickoff">${formatKickoff(g.kickoff)}</p>
      </article>`;
  }).join("");
}

function renderTop(games) {
  const root = document.getElementById("top-games");
  if (!games || !games.length) {
    root.innerHTML = `<div class="empty">No top games listed.</div>`;
    return;
  }
  root.innerHTML = games.map((g) => {
    const left = g.isHome ? g.name : g.opponent;
    const right = g.isHome ? g.opponent : g.name;
    // For top games, name may be away or home; show matchup + stadium scores
    const awayName = g.isHome ? g.opponent : g.name;
    const homeName = g.isHome ? g.name : g.opponent;
    return `
      <article class="game-row" role="listitem" data-id="${g.id}">
        <div>
          <div class="game-matchup">${escapeHtml(awayName)} <span>@</span> ${escapeHtml(homeName)}</div>
          <div class="game-meta">
            ${statusBadge(g.status)}
            <span>${formatKickoff(g.kickoff)}</span>
          </div>
        </div>
        <div class="game-scores" aria-label="Score">
          <span>${scoreText(g.awayScore)}</span>
          <span class="sep">–</span>
          <span>${scoreText(g.homeScore)}</span>
        </div>
      </article>`;
  }).join("");
}

function escapeHtml(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function updateLivePill(data) {
  const pill = document.getElementById("live-pill");
  const anyLive = [...(data.pinned || []), ...(data.topGames || [])]
    .some((g) => isLiveStatus(g.status));
  pill.textContent = anyLive ? "LIVE" : "BOARD";
  pill.classList.toggle("idle", !anyLive);
}

async function loadScores() {
  const res = await fetch(`${SCORES_URL}?t=${Date.now()}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const data = await res.json();
  document.getElementById("updated").textContent = formatUpdated(data.updatedAt);
  document.getElementById("updated").dateTime = data.updatedAt || "";
  renderPinned(data.pinned);
  renderTop(data.topGames);
  updateLivePill(data);
}

async function tick() {
  try {
    await loadScores();
  } catch (err) {
    console.warn("Score refresh failed:", err);
    document.getElementById("updated").textContent = "Refresh failed — retrying…";
  }
}

tick();
setInterval(tick, REFRESH_MS);
