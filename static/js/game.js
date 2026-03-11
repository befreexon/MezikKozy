/* Game WebSocket handler and renderer */
/* Expects globals: ROOM_ID, CURRENT_USER_ID */

let ws = null;
let state = null;
let levels = {};
let lastCurrentPlayer = null;
let countdownInterval = null;

// ── WebSocket ─────────────────────────────────────────────────────────────────

function initWebSocket() {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  ws = new WebSocket(`${protocol}//${window.location.host}/ws/game/${ROOM_ID}/`);

  ws.onopen = function () {
    setConnectionStatus("Připojeno", "connected");
  };

  ws.onmessage = function (e) {
    const data = JSON.parse(e.data);
    if (data.type === "state_update") {
      state = data.state;
      levels = data.levels || {};
      renderAll();
    } else if (data.type === "room_update" && data.room.status === "playing") {
      window.location.reload();
    } else if (data.type === "chat_message") {
      appendChatMessage(data.message);
    } else if (data.type === "chat_history") {
      loadChatHistory(data.messages);
    } else if (data.type === "error") {
      console.error("Server error:", data.message);
    }
  };

  ws.onclose = function () {
    setConnectionStatus("Odpojen od serveru — obnovte stránku", "disconnected");
  };

  ws.onerror = function () {
    setConnectionStatus("Chyba připojení", "disconnected");
  };
}

function sendAction(action, extra) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(Object.assign({ action }, extra || {})));
  }
}

function setConnectionStatus(text, cls) {
  const el = document.getElementById("connection-status");
  if (!el) return;
  el.textContent = text;
  el.className = "connection-status " + (cls || "");
}

// ── Render orchestration ──────────────────────────────────────────────────────

function renderAll() {
  if (!state) return;

  if (state.current !== lastCurrentPlayer) {
    lastCurrentPlayer = state.current;
    startTurnCountdown(state.turn_started_at);
  }

  renderPlayers();
  renderDice();
  renderControls();
  renderLog();

  if (state.phase === "game-over") {
    if (countdownInterval) { clearInterval(countdownInterval); countdownInterval = null; }
    showGameOver();
  }
}

function startTurnCountdown(turnStartedAt) {
  if (countdownInterval) { clearInterval(countdownInterval); countdownInterval = null; }
  if (!turnStartedAt) return;

  function tick() {
    const el = document.getElementById("turn-countdown");
    if (!el) return;
    const elapsed = (Date.now() - new Date(turnStartedAt).getTime()) / 1000;
    const rem = Math.max(0, 300 - elapsed);
    const m = Math.floor(rem / 60);
    const s = Math.floor(rem % 60);
    el.textContent = `⏱ ${m}:${s.toString().padStart(2, "0")}`;
    el.className = "turn-countdown" + (rem < 60 ? " warning" : "");
    if (rem === 0) { clearInterval(countdownInterval); countdownInterval = null; }
  }

  tick();
  countdownInterval = setInterval(tick, 1000);
}

// ── Players bar ───────────────────────────────────────────────────────────────

function renderPlayers() {
  const bar = document.getElementById("players-bar");
  const bankHTML = `
    <div class="bank-display">
      <div class="label">Banka</div>
      <div class="bank-amount">${state.bank} Kč</div>
    </div>`;

  const activePlayers = state.players.filter((p) => !p.eliminated);
  const cards = state.players.map((p) => playerCardHTML(p)).join("");

  if (activePlayers.length <= 2 && state.players.length === 2) {
    bar.style.gridTemplateColumns = "1fr auto 1fr";
    bar.innerHTML = playerCardHTML(state.players[0]) + bankHTML + playerCardHTML(state.players[1]);
  } else {
    bar.style.gridTemplateColumns = `repeat(${state.players.length}, 1fr) auto`;
    bar.innerHTML = cards + bankHTML;
  }
}

function levelBadgeHTML(level) {
  const cls = level >= 2 ? "level--up" : level <= 0 ? "level--down" : "level--base";
  return `<span class="level-badge ${cls}">Lv ${level}</span>`;
}

function playerCardHTML(p) {
  const idx = state.players.indexOf(p);
  const isActive = idx === state.current && !p.eliminated;
  const lv = levels[p.user_id] !== undefined ? levels[p.user_id] : 1;
  return `
    <div class="player-card ${isActive ? "active" : ""} ${p.eliminated ? "eliminated" : ""}">
      ${isActive ? '<div class="active-indicator"></div>' : ""}
      <h3>${escapeHtml(p.name)} ${levelBadgeHTML(lv)}</h3>
      <div class="player-money">${p.money} <span>Kč</span></div>
      ${p.eliminated ? '<div style="font-size:0.75rem;color:#e06060;margin-top:4px;">VYŘAZEN</div>' : ""}
    </div>`;
}

// ── Dice ──────────────────────────────────────────────────────────────────────

function renderDice() {
  const d1 = document.getElementById("d1");
  const d2 = document.getElementById("d2");
  const d3 = document.getElementById("d3");
  const rangeEl = document.getElementById("range-display");
  const bonusWrapper = document.getElementById("bonus-die-wrapper");
  const dBonus = document.getElementById("d-bonus");

  if (!state.first_roll) {
    setDie(d1, null);
    setDie(d2, null);
    setDie(d3, null);
    d1.className = "die empty";
    d2.className = "die empty";
    d3.className = "die empty";
    rangeEl.classList.add("hidden");
    bonusWrapper.style.display = "none";
    return;
  }

  const [lo, mid, hi] = state.first_roll;
  setDie(d1, lo);
  setDie(d2, mid);
  setDie(d3, hi);
  d1.className = "die highlight-min";
  d2.className = "die";
  d3.className = "die highlight-max";

  rangeEl.classList.remove("hidden");
  rangeEl.textContent = `Rozsah: ${lo} – ${hi}  •  Musíte hodit mezi ${lo} a ${hi}`;

  if (state.bonus_roll !== null && state.bonus_roll !== undefined) {
    bonusWrapper.style.display = "flex";
    setDie(dBonus, state.bonus_roll);
    const inBetween = state.bonus_roll > lo && state.bonus_roll < hi;
    dBonus.className = "die " + (inBetween ? "highlight-between" : "highlight-miss");
  } else if (state.phase === "betting") {
    bonusWrapper.style.display = "flex";
    setDie(dBonus, null);
    dBonus.className = "die empty";
  } else {
    bonusWrapper.style.display = "none";
  }
}

function setDie(el, val) {
  el.textContent = val === null || val === undefined ? "?" : val;
}

function animateDice(ids) {
  ids.forEach((id) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.classList.add("rolling");
    setTimeout(() => el.classList.remove("rolling"), 500);
  });
}

// ── Controls ──────────────────────────────────────────────────────────────────

function renderControls() {
  const p = state.players[state.current];
  const isMyTurn = p.user_id === CURRENT_USER_ID;

  document.getElementById("turn-text").textContent = `Na tahu: ${p.name} (${p.money} Kč)`;

  const phaseTitleEl = document.getElementById("phase-title");
  const areaEl = document.getElementById("control-area");

  if (!isMyTurn) {
    phaseTitleEl.textContent = `Čeká se na tah hráče ${escapeHtml(p.name)}…`;
    areaEl.innerHTML = '<p class="spectator-label">Sledujete hru</p>';
    return;
  }

  if (state.phase === "new-round") {
    phaseTitleEl.textContent = "Hoďte třemi kostkami";
    areaEl.innerHTML = `<button class="action-btn primary" id="roll-first-btn">🎲 Hodit třemi kostkami</button>`;
    document.getElementById("roll-first-btn").addEventListener("click", function () {
      animateDice(["d1", "d2", "d3"]);
      sendAction("roll_first");
    });
  } else if (state.phase === "rolled") {
    phaseTitleEl.textContent = "Vsaďte si – nebo přeskočte";
    areaEl.innerHTML = buildBetUI(p);
  } else if (state.phase === "betting") {
    phaseTitleEl.textContent = `Vsadili jste ${state.selected_bet} Kč – hoďte!`;
    areaEl.innerHTML = `<button class="action-btn primary" id="roll-bonus-btn">🎲 Hodit kostkou</button>`;
    document.getElementById("roll-bonus-btn").addEventListener("click", function () {
      animateDice(["d-bonus"]);
      sendAction("roll_bonus");
    });
  } else if (state.phase === "result") {
    phaseTitleEl.textContent = state.last_result === "win" ? "✨ Výhra!" : "💸 Prohra!";
    areaEl.innerHTML = `<button class="action-btn primary" id="next-player-btn">Další hráč →</button>`;
    document.getElementById("next-player-btn").addEventListener("click", function () {
      sendAction("next_player");
    });
  } else if (state.phase === "game-over") {
    phaseTitleEl.textContent = "Hra skončila!";
    areaEl.innerHTML = "";
  }
}

function buildBetUI(p) {
  const baseBet = state.base_bet || 10;
  const bank = state.bank;
  const maxBet = Math.min(p.money, bank);
  const selected = state.selected_bet;

  const presets = [1, 2, 3, 5].map((m) => m * baseBet).filter((b) => b < maxBet);

  let html = '<div class="bet-row">';
  presets.forEach((b) => {
    html += `<button class="bet-btn ${selected === b ? "selected" : ""}" onclick="selectBetAction(${b})">${b} Kč</button>`;
  });
  if (maxBet > 0) {
    const allInSelected = selected === maxBet;
    html += `<button class="bet-btn ${allInSelected ? "selected" : ""}" onclick="selectBetAction('all-in')">All-in (${maxBet} Kč)</button>`;
  }
  html += "</div>";

  html += `
    <div class="bet-input-row">
      <input type="number" id="bet-custom-input" class="bet-input"
        min="1" max="${maxBet}" placeholder="Vlastní částka…"
        value="${selected !== null && selected !== undefined ? selected : ""}"
        oninput="selectBetAction(parseInt(this.value) || null)">
      <span class="bet-input-hint">max ${maxBet} Kč</span>
    </div>`;

  const hasBet = selected !== null && selected !== undefined && selected > 0;
  html += `
    <div class="btn-group">
      <button class="action-btn primary" ${!hasBet ? "disabled" : ""} onclick="confirmBetAction()">Vsadit a hrát</button>
      <button class="action-btn secondary" onclick="sendAction('skip')">Přeskočit</button>
    </div>`;
  return html;
}

function selectBetAction(amount) {
  sendAction("select_bet", { amount });
}

function confirmBetAction() {
  sendAction("confirm_bet");
}

// ── Log ───────────────────────────────────────────────────────────────────────

function renderLog() {
  const logEl = document.getElementById("log");
  logEl.innerHTML = "";
  (state.log || []).forEach((entry) => {
    const div = document.createElement("div");
    div.className = `log-entry ${entry.type}`;
    div.textContent = entry.message;
    logEl.appendChild(div);
  });
}

// ── Game Over modal ───────────────────────────────────────────────────────────

function showGameOver() {
  const modal = document.getElementById("gameover-screen");
  if (!modal || !modal.classList.contains("hidden")) return;

  const winner = state.players.find((p) => p.user_id === state.winner_id);
  if (winner) {
    document.getElementById("winner-title").textContent = `🏆 ${escapeHtml(winner.name)} vyhrál!`;
    document.getElementById("winner-text").textContent =
      `Gratulujeme! ${escapeHtml(winner.name)} přežil a odnáší si ${winner.money} Kč.`;
  }
  modal.classList.remove("hidden");
}

// ── Utility ───────────────────────────────────────────────────────────────────

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

// ── Boot ──────────────────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", initWebSocket);
