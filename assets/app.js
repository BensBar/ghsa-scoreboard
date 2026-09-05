const REFRESH_MS = 45000;
const API_URL = "api/v1/scoreboard";
const STREAM_URL = "api/v1/stream";
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
  delayed: "status-half",
  postponed: "status-scheduled",
  canceled: "status-final",
};

let schoolsCatalog = { schools: [], opponents: [], suggested: [] };
/** @type {Record<string, any>} */
let teamIndex = {};
let latestScores = null;
/** @type {string[]|null} */
let pendingSelection = null;

function isLiveStatus(status) {
  return ["Q1", "Q2", "Q3", "Q4", "HALF", "OT", "delayed"].includes(status);
}

function formatKickoff(iso) {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleString("en-US", {
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
    return "Updated " + new Date(iso).toLocaleString("en-US", {
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

function statusBadge(status, stale = false) {
  const cls = STATUS_CLASS[status] || "status-scheduled";
  const label = stale ? `${status || "scheduled"} · delayed feed` : status || "scheduled";
  return `<span class="status-badge ${cls}${stale ? " status-stale" : ""}">${escapeHtml(label)}</span>`;
}

function sourceMeta(game) {
  const confidence = Math.round((game.confidence ?? 0) * 100);
  const checked = game.lastFeedCheck ? `Checked ${formatUpdated(game.lastFeedCheck).replace("Updated ", "")}` : "Feed not checked";
  const changed = game.lastScoreChange ? `Score changed ${formatUpdated(game.lastScoreChange).replace("Updated ", "")}` : "No score change reported";
  return `<div class="source-meta">${escapeHtml(game.source || "unknown source")} · ${confidence}% confidence<br>${escapeHtml(checked)} · ${escapeHtml(changed)}</div>`;
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

function rebuildTeamIndex() {
  teamIndex = {};
  for (const s of schoolsCatalog.schools || []) {
    teamIndex[s.id] = s;
  }
  for (const o of schoolsCatalog.opponents || []) {
    teamIndex[o.id] = o;
  }
}

function teamMeta(id, fallbackName) {
  const t = (id && teamIndex[id]) || null;
  const color = t?.primaryColor || "#3dff9a";
  const logo = t?.logo || (id ? `assets/logos/${id}.png` : null);
  const name = t?.name || fallbackName || id || "Team";
  return { id: id || null, name, color, logo };
}

function logoImg(meta, extraClass = "") {
  const src = meta.logo || "";
  const alt = escapeHtml(meta.name);
  const color = escapeHtml(meta.color || "#3dff9a");
  if (!src) {
    return `<div class="logo-fallback ${extraClass}" style="--team:${color}" aria-hidden="true">${escapeHtml((meta.name || "?").slice(0, 2).toUpperCase())}</div>`;
  }
  return `<img class="team-logo ${extraClass}" src="${escapeHtml(src)}" alt="${alt}" loading="lazy" style="--team:${color}" onerror="this.classList.add('logo-broken');this.replaceWith(Object.assign(document.createElement('div'),{className:'logo-fallback ${extraClass}',style:'--team:${color}',textContent:'${escapeHtml((meta.name || "?").slice(0, 2).toUpperCase())}'}))" />`;
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
    sub.textContent = favoriteIds
      .map((id) => teamMeta(id).name)
      .join(" · ");
  }

  root.innerHTML = favoriteIds.map((id) => {
    const game = gamesById[id];
    const us = teamMeta(id);
    if (!game) {
      return `
        <article class="card card-empty stadium-card" role="listitem" data-id="${escapeHtml(id)}" style="--team:${escapeHtml(us.color)}">
          <div class="card-glow" aria-hidden="true"></div>
          <div class="card-logos solo">
            ${logoImg(us, "logo-xl")}
          </div>
          <h3 class="school-name">${escapeHtml(us.name)}</h3>
          <p class="vs-line muted-line">No game listed</p>
          <span class="status-badge status-scheduled">BYE</span>
        </article>`;
    }

    const opp = teamMeta(game.opponentId, game.opponent);
    const { ours, theirs } = displayScores(game);
    const ha = game.isHome ? "HOME" : "AWAY";
    return `
      <article class="card stadium-card" role="listitem" data-id="${escapeHtml(game.id)}" style="--team:${escapeHtml(us.color)}; --opp:${escapeHtml(opp.color)}">
        <div class="card-glow" aria-hidden="true"></div>
        <div class="card-top">
          <div class="matchup-names">
            <h3 class="school-name">${escapeHtml(game.name)}</h3>
            <p class="vs-line">vs <strong>${escapeHtml(game.opponent)}</strong>
              <span class="ha-tag">${ha}</span>
            </p>
          </div>
          ${statusBadge(game.status, game.stale)}
        </div>
        <div class="scoreboard neon-board">
          <div class="team-col">
            ${logoImg(us, "logo-hero")}
            <div class="team-name">${escapeHtml(game.name)}</div>
            <div class="score ours glow-score">${scoreText(ours)}</div>
          </div>
          <div class="mid">
            <span class="mid-vs">VS</span>
            <span class="mid-kick">${formatKickoff(game.kickoff)}</span>
          </div>
          <div class="team-col right">
            ${logoImg(opp, "logo-hero")}
            <div class="team-name">${escapeHtml(game.opponent)}</div>
            <div class="score theirs glow-score">${scoreText(theirs)}</div>
          </div>
        </div>
        ${sourceMeta(game)}
        <button class="game-detail-link" type="button" data-game-id="${escapeHtml(game.gameId || game.id)}">Game details</button>
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
    const school = teamMeta(g.schoolId || g.id, g.name);
    const opp = teamMeta(g.opponentId, g.opponent);
    const away = g.isHome ? opp : school;
    const home = g.isHome ? school : opp;
    return `
      <article class="game-row stadium-row" role="listitem" data-id="${escapeHtml(g.id)}" style="--team:${escapeHtml(school.color)}; --opp:${escapeHtml(opp.color)}">
        <div class="row-logos">
          ${logoImg(away, "logo-row")}
          <span class="at">@</span>
          ${logoImg(home, "logo-row")}
        </div>
        <div class="row-body">
          <div class="game-matchup">${escapeHtml(away.name)} <span>@</span> ${escapeHtml(home.name)}</div>
          <div class="game-meta">
            ${statusBadge(g.status, g.stale)}
            <span>${formatKickoff(g.kickoff)}</span>
          </div>
        </div>
        <div class="game-scores neon-mini" aria-label="Score">
          <span class="glow-score">${scoreText(g.awayScore)}</span>
          <span class="sep">–</span>
          <span class="glow-score">${scoreText(g.homeScore)}</span>
        </div>
        <button class="game-detail-link row-detail" type="button" data-game-id="${escapeHtml(g.gameId || g.id)}">Details</button>
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
    const meta = teamMeta(s.id, s.name);
    return `
      <button type="button"
        class="logo-tile${on ? " selected" : ""}${isSuggested ? " suggested" : ""}"
        role="option"
        aria-selected="${on}"
        data-id="${escapeHtml(s.id)}"
        style="--team:${escapeHtml(meta.color)}">
        <span class="tile-check" aria-hidden="true">${on ? "✓" : ""}</span>
        ${isSuggested ? '<span class="tile-tag">Suggested</span>' : ""}
        <span class="tile-logo-wrap">${logoImg(meta, "logo-tile-img")}</span>
        <span class="tile-name">${escapeHtml(s.name)}</span>
        <span class="tile-city">${escapeHtml(s.city || "")}</span>
      </button>`;
  }).join("");

  grid.querySelectorAll(".logo-tile").forEach((btn) => {
    btn.addEventListener("click", () => {
      const id = btn.dataset.id;
      const set = new Set(pendingSelection || []);
      if (set.has(id)) set.delete(id);
      else set.add(id);
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

function effectiveFavorites() {
  const saved = getFavorites();
  if (saved && saved.length) return saved;
  const suggested = schoolsCatalog?.suggested || [];
  if (suggested.length) return [...suggested];
  return [];
}

function applyBoard() {
  if (!latestScores) return;
  const favs = effectiveFavorites();
  renderPinnedFromFavorites(latestScores, favs);
  renderTop(filteredTopGames(latestScores.topGames || []));
  updateLivePill(latestScores, favs);
  wireGameDetails();
}

function filteredTopGames(games) {
  const query = (document.getElementById("game-search")?.value || "").toLowerCase();
  const group = document.getElementById("game-group")?.value || "all";
  const date = document.getElementById("game-date")?.value || "";
  const classification = document.getElementById("game-classification")?.value || "";
  return games.filter((game) => {
    const text = `${game.name} ${game.opponent}`.toLowerCase();
    if (query && !text.includes(query)) return false;
    if (date && !game.kickoff.startsWith(date)) return false;
    if (classification) {
      const ours = teamIndex[game.schoolId]?.ghsaClass;
      const theirs = teamIndex[game.opponentId]?.ghsaClass;
      if (ours !== classification && theirs !== classification) return false;
    }
    if (group === "live") return isLiveStatus(game.status);
    if (group === "upcoming") return game.status === "scheduled";
    if (group === "final") return game.status === "FINAL";
    if (group === "top25") {
      return Boolean(teamIndex[game.schoolId]?.ranking || teamIndex[game.opponentId]?.ranking);
    }
    return true;
  });
}

function normalizeApi(data) {
  const games = (data.games || []).map((game) => ({
    id: game.homeTeam.id,
    gameId: game.id,
    schoolId: game.homeTeam.id,
    name: game.homeTeam.name,
    opponentId: game.awayTeam.id,
    opponent: game.awayTeam.name,
    homeScore: game.homeScore,
    awayScore: game.awayScore,
    status: game.status,
    kickoff: game.kickoff,
    isHome: true,
    period: game.period,
    clock: game.clock,
    stale: game.stale,
    source: game.source,
    confidence: game.confidence,
    lastFeedCheck: game.lastFeedCheck,
    lastSuccessfulUpdate: game.lastSuccessfulUpdate,
    lastScoreChange: game.lastScoreChange,
  }));
  const pinned = [];
  for (const game of games) {
    pinned.push(game);
    pinned.push({
      ...game,
      id: game.opponentId,
      schoolId: game.opponentId,
      name: game.opponent,
      opponentId: game.schoolId,
      opponent: game.name,
      isHome: false,
    });
  }
  return {
    updatedAt: data.lastSuccessfulUpdate,
    generatedAt: data.generatedAt,
    pinned,
    topGames: games,
    providerHealth: data.providerHealth || [],
  };
}

async function loadSchools() {
  const res = await fetch(`${SCHOOLS_URL}?t=${Date.now()}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`schools HTTP ${res.status}`);
  schoolsCatalog = await res.json();
  rebuildTeamIndex();
}

async function loadScores() {
  let res = await fetch(`${API_URL}?t=${Date.now()}`, { cache: "no-store" });
  let data;
  if (res.ok) {
    data = normalizeApi(await res.json());
  } else {
    res = await fetch(`${SCORES_URL}?t=${Date.now()}`, { cache: "no-store" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    data = await res.json();
  }
  latestScores = data;
  document.getElementById("updated").textContent = formatUpdated(data.updatedAt);
  document.getElementById("updated").dateTime = data.updatedAt || "";
  applyBoard();
}

async function openGameDetails(gameId) {
  const dialog = document.getElementById("game-dialog");
  const body = document.getElementById("game-dialog-body");
  try {
    const response = await fetch(`api/v1/games/${encodeURIComponent(gameId)}`);
    if (!response.ok) throw new Error("details unavailable");
    const game = await response.json();
    const events = (game.scoringEvents || []).map((event) =>
      `<li><strong>${escapeHtml(event.period || "")} ${escapeHtml(event.clock || "")}</strong> ${escapeHtml(event.description)}</li>`
    ).join("");
    body.innerHTML = `
      <h2>${escapeHtml(game.awayTeam.name)} @ ${escapeHtml(game.homeTeam.name)}</h2>
      <p class="detail-score">${scoreText(game.awayScore)} – ${scoreText(game.homeScore)}</p>
      <p>${statusBadge(game.status, game.stale)} ${escapeHtml(game.clock || "")}</p>
      <p>${escapeHtml(game.venue || "Venue not reported")}</p>
      ${sourceMeta(game)}
      <h3>Scoring timeline</h3><ol>${events || "<li>No scoring events reported.</li>"}</ol>
      <button type="button" id="share-game" class="btn-edit">Share game</button>`;
    dialog.showModal();
    document.getElementById("share-game")?.addEventListener("click", async () => {
      const url = `${location.origin}${location.pathname}#game=${encodeURIComponent(game.id)}`;
      if (navigator.share) await navigator.share({ title: `${game.awayTeam.name} at ${game.homeTeam.name}`, url });
      else await navigator.clipboard.writeText(url);
    });
  } catch {
    body.textContent = "Game details are unavailable while using the static fallback.";
    dialog.showModal();
  }
}

function wireGameDetails() {
  document.querySelectorAll(".game-detail-link").forEach((button) => {
    button.addEventListener("click", () => openGameDetails(button.dataset.gameId));
  });
}

function connectLiveUpdates() {
  if (!window.EventSource) return;
  const stream = new EventSource(STREAM_URL);
  stream.addEventListener("scoreboard", tick);
  stream.onerror = () => {
    stream.close();
    setTimeout(connectLiveUpdates, REFRESH_MS);
  };
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

    function wireDiscovery() {
      document.getElementById("game-search")?.addEventListener("input", applyBoard);
      document.getElementById("game-group")?.addEventListener("change", applyBoard);
      document.getElementById("game-date")?.addEventListener("change", applyBoard);
      document.getElementById("game-classification")?.addEventListener("change", applyBoard);
      document.getElementById("game-dialog-close")?.addEventListener("click", () => {
        document.getElementById("game-dialog").close();
      });
    }
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && getFavorites()) closePicker();
  });
}

async function boot() {
  wirePicker();
  wireDiscovery();
  try {
    await loadSchools();
  } catch (err) {
    console.warn("Schools catalog failed:", err);
  }

  const favs = getFavorites();
  if (favs === null) {
    // Preload suggested so the board isn't blank behind the picker
    const suggested = schoolsCatalog?.suggested || [];
    if (suggested.length) saveFavorites(suggested);
    openPicker({ firstVisit: true });
  }

  await tick();
  connectLiveUpdates();
  setInterval(tick, REFRESH_MS);
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("service-worker.js");
}

boot();
