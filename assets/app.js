const REFRESH_MS = 45000;
const SCORES_URL = "public/scores.json";
const SCHOOLS_URL = "data/schools.json";
const FAVORITES_KEY = "ghsa-favorites";

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

let schoolsCatalog = { schools: [], suggested: [] };
let latestScores = null;
/** @type {string[]|null} */
let pendingSelection = null;

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

function escapeHtml(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function getFavorites() {
  try {
    const raw = localStorage.getItem(FAVORITES_KEY);
    if (raw === null) return null;
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return null;
    return parsed.map(String).filter(Boolean);
  } catch {
    return null;
  }
}

function saveFavorites(ids) {
  localStorage.setItem(FAVORITES_KEY, JSON.stringify(ids));
}

function schoolById(id) {
  return (schoolsCatalog.schools || []).find((s) => s.id === id);
}

function renderPinnedFromFavorites(data, favoriteIds) {
  const root = document.getElementById("pinned");
  const sub = document.getElementById("pinned-sub");
  const gamesById = Object.fromEntries((data.pinned || []).map((g) => [g.id, g]));

  if (!favoriteIds || !favoriteIds.length) {
    root.innerHTML = `<div class="empty">No favorites yet — tap Edit favorites to pick teams.</div>`;
    if (sub) sub.textContent = "Pick teams to pin them here";
    return;
  }

  if (sub) {
    const names = favoriteIds
      .map((id) => schoolById(id)?.name || gamesById[id]?.name || id)
      .join(", ");
    sub.textContent = names;
  }

  root.innerHTML = favoriteIds.map((id) => {
    const game = gamesById[id];
    if (!game) {
      const school = schoolById(id);
      const name = school?.name || id;
      return `
        <article class="card card-empty" role="listitem" data-id="${escapeHtml(id)}">
          <div class="card-top">
            <div>
              <h3 class="school-name">${escapeHtml(name)}</h3>
              <p class="vs-line muted-line">No game listed</p>
            </div>
            <span class="status-badge status-scheduled">BYE</span>
          </div>
          <p class="kickoff">This school has no entry in scores.json for this week.</p>
        </article>`;
    }

    const { ours, theirs } = displayScores(game);
    const ha = game.isHome ? "HOME" : "AWAY";
    return `
      <article class="card" role="listitem" data-id="${escapeHtml(game.id)}">
        <div class="card-top">
          <div>
            <h3 class="school-name">${escapeHtml(game.name)}</h3>
            <p class="vs-line">vs <strong>${escapeHtml(game.opponent)}</strong>
              <span class="ha-tag">${ha}</span>
            </p>
          </div>
          ${statusBadge(game.status)}
        </div>
        <div class="scoreboard">
          <div class="team-col">
            <div class="team-label">Us</div>
            <div class="team-name">${escapeHtml(game.name)}</div>
            <div class="score ours">${scoreText(ours)}</div>
          </div>
          <div class="mid">VS</div>
          <div class="team-col right">
            <div class="team-label">Opp</div>
            <div class="team-name">${escapeHtml(game.opponent)}</div>
            <div class="score theirs">${scoreText(theirs)}</div>
          </div>
        </div>
        <p class="kickoff">${formatKickoff(game.kickoff)}</p>
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
    const awayName = g.isHome ? g.opponent : g.name;
    const homeName = g.isHome ? g.name : g.opponent;
    return `
      <article class="game-row" role="listitem" data-id="${escapeHtml(g.id)}">
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

function updateLivePill(data, favoriteIds) {
  const pill = document.getElementById("live-pill");
  const favSet = new Set(favoriteIds || []);
  const pinnedLive = (data.pinned || [])
    .filter((g) => favSet.has(g.id))
    .some((g) => isLiveStatus(g.status));
  const topLive = (data.topGames || []).some((g) => isLiveStatus(g.status));
  const anyLive = pinnedLive || topLive;
  pill.textContent = anyLive ? "LIVE" : "BOARD";
  pill.classList.toggle("idle", !anyLive);
}

function updatePickerCount() {
  const n = (pendingSelection || []).length;
  const el = document.getElementById("picker-count");
  if (el) el.textContent = `${n} selected`;
  const save = document.getElementById("picker-save");
  if (save) save.disabled = n === 0;
}

function renderPickerGrid(selectedIds) {
  const grid = document.getElementById("picker-grid");
  const suggested = new Set(schoolsCatalog.suggested || []);
  const selected = new Set(selectedIds);

  grid.innerHTML = (schoolsCatalog.schools || []).map((s) => {
    const on = selected.has(s.id);
    const isSuggested = suggested.has(s.id);
    return `
      <button type="button"
        class="school-chip${on ? " selected" : ""}${isSuggested ? " suggested" : ""}"
        role="option"
        aria-selected="${on}"
        data-id="${escapeHtml(s.id)}">
        <span class="chip-check" aria-hidden="true">${on ? "✓" : ""}</span>
        <span class="chip-body">
          <span class="chip-name">${escapeHtml(s.name)}</span>
          <span class="chip-city">${escapeHtml(s.city || "")}</span>
        </span>
        ${isSuggested ? '<span class="chip-tag">Suggested</span>' : ""}
      </button>`;
  }).join("");

  grid.querySelectorAll(".school-chip").forEach((btn) => {
    btn.addEventListener("click", () => {
      const id = btn.dataset.id;
      const set = new Set(pendingSelection || []);
      if (set.has(id)) set.delete(id);
      else set.add(id);
      // Preserve save order: keep existing order, append new at end
      const next = (pendingSelection || []).filter((x) => set.has(x));
      for (const x of set) {
        if (!next.includes(x)) next.push(x);
      }
      pendingSelection = next;
      renderPickerGrid(pendingSelection);
      updatePickerCount();
    });
  });

  updatePickerCount();
}

function openPicker({ firstVisit = false } = {}) {
  const overlay = document.getElementById("favorites-picker");
  const saved = getFavorites();
  if (saved && saved.length) {
    pendingSelection = [...saved];
  } else if (firstVisit || !saved) {
    pendingSelection = [...(schoolsCatalog.suggested || [])];
  } else {
    pendingSelection = [];
  }

  const title = document.getElementById("picker-title");
  if (title) {
    title.textContent = firstVisit ? "Pick your favorite teams" : "Edit favorites";
  }

  renderPickerGrid(pendingSelection);
  overlay.hidden = false;
  overlay.setAttribute("aria-hidden", "false");
  document.body.classList.add("picker-open");
  document.getElementById("picker-save")?.focus();
}

function closePicker() {
  const overlay = document.getElementById("favorites-picker");
  overlay.hidden = true;
  overlay.setAttribute("aria-hidden", "true");
  document.body.classList.remove("picker-open");
  pendingSelection = null;
}

function applyBoard() {
  if (!latestScores) return;
  const favs = getFavorites() || [];
  renderPinnedFromFavorites(latestScores, favs);
  renderTop(latestScores.topGames);
  updateLivePill(latestScores, favs);
}

async function loadSchools() {
  const res = await fetch(`${SCHOOLS_URL}?t=${Date.now()}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`schools HTTP ${res.status}`);
  schoolsCatalog = await res.json();
}

async function loadScores() {
  const res = await fetch(`${SCORES_URL}?t=${Date.now()}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const data = await res.json();
  latestScores = data;
  document.getElementById("updated").textContent = formatUpdated(data.updatedAt);
  document.getElementById("updated").dateTime = data.updatedAt || "";
  applyBoard();
}

async function tick() {
  try {
    await loadScores();
  } catch (err) {
    console.warn("Score refresh failed:", err);
    document.getElementById("updated").textContent = "Refresh failed — retrying…";
  }
}

function wirePicker() {
  document.getElementById("edit-favorites")?.addEventListener("click", () => {
    openPicker({ firstVisit: false });
  });
  document.getElementById("picker-save")?.addEventListener("click", () => {
    const ids = pendingSelection || [];
    if (!ids.length) return;
    saveFavorites(ids);
    closePicker();
    applyBoard();
  });
  document.getElementById("favorites-picker")?.addEventListener("click", (e) => {
    if (e.target === e.currentTarget && getFavorites()) {
      closePicker();
    }
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && getFavorites()) closePicker();
  });
}

async function boot() {
  wirePicker();
  try {
    await loadSchools();
  } catch (err) {
    console.warn("Schools catalog failed:", err);
  }

  const favs = getFavorites();
  if (favs === null) {
    openPicker({ firstVisit: true });
  }

  await tick();
  setInterval(tick, REFRESH_MS);
}

boot();
