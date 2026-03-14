/* Lobby WebSocket handler */
/* Expects globals: ROOM_ID, IS_HOST, CURRENT_USER_ID */

let ws = null;
let reconnectTimeout = null;

function setLobbyStatus(text, ok) {
  const el = document.getElementById("lobby-connection-status");
  if (!el) return;
  el.textContent = text;
  el.className = "lobby-status " + (ok ? "lobby-status--ok" : "lobby-status--err");
}

function initWebSocket() {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  ws = new WebSocket(`${protocol}//${window.location.host}/ws/game/${ROOM_ID}/`);

  ws.onopen = function () {
    setLobbyStatus("Připojeno", true);
    if (reconnectTimeout) { clearTimeout(reconnectTimeout); reconnectTimeout = null; }
  };

  ws.onmessage = function (e) {
    const data = JSON.parse(e.data);

    if (data.type === "room_update") {
      if (data.room.status === "playing") {
        window.location.href = `/room/${ROOM_ID}/play/`;
        return;
      }
      updateRoom(data.room);
    } else if (data.type === "state_update") {
      window.location.href = `/room/${ROOM_ID}/play/`;
    } else if (data.type === "room_deleted") {
      window.location.href = "/";
    } else if (data.type === "chat_message") {
      appendChatMessage(data.message);
    } else if (data.type === "chat_history") {
      loadChatHistory(data.messages);
    } else if (data.type === "error") {
      console.error("Server error:", data.message);
    }
  };

  ws.onclose = function () {
    setLobbyStatus("Odpojeno – znovu se připojuji…", false);
    reconnectTimeout = setTimeout(initWebSocket, 3000);
  };

  ws.onerror = function () {
    setLobbyStatus("Chyba připojení", false);
  };
}

function updateRoom(room) {
  updatePlayerList(room.players);
  updatePlayerCount(room.players.length, room.max_players);
  if (IS_HOST) {
    updateStartButton(room.players.length);
  }
}

function levelBadgeHTML(level) {
  const tiers = {
    3: { cls: "level--gold",   icon: "🥇" },
    2: { cls: "level--silver", icon: "🥈" },
    1: { cls: "level--bronze", icon: "🥉" },
    0: { cls: "level--potato", icon: "🥔" },
  };
  const t = tiers[level] || tiers[1];
  return `<span class="level-badge ${t.cls}">${t.icon}</span>`;
}

function updatePlayerList(players) {
  const listEl = document.getElementById("player-list");
  if (!listEl) return;

  listEl.innerHTML = players
    .map(
      (p) => `
        <div class="lobby-player">
          <span class="lobby-player-name">${escapeHtml(p.username)} ${levelBadgeHTML(p.level !== undefined ? p.level : 1)}</span>
          ${p.id === ROOM_HOST_ID ? '<span class="host-badge">Hostitel</span>' : ""}
        </div>`
    )
    .join("");
}

function updatePlayerCount(count, max) {
  const el = document.getElementById("player-count");
  if (el) el.textContent = `${count}/${max}`;
}

function updateStartButton(count) {
  const btn = document.getElementById("start-btn");
  const hint = document.getElementById("start-hint");
  if (!btn) return;

  btn.disabled = count < 2;
  if (hint) {
    hint.textContent = count < 2 ? "Čeká se na dalšího hráče…" : "Připraveni ke hře!";
  }
}

function startGame() {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ action: "start_game" }));
  } else {
    setLobbyStatus("Nejste připojeni – počkejte na reconnect…", false);
  }
}

function escapeHtml(str) {
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

// Fallback: poll room status every 4s so redirect works even if WS message is missed
let _statusPollInterval = null;
function startStatusPoll() {
  if (_statusPollInterval) return;
  _statusPollInterval = setInterval(function () {
    fetch(`/game/api/rooms/${ROOM_ID}/status/`)
      .then((r) => r.json())
      .then((data) => {
        if (data.status === "playing") {
          window.location.href = `/room/${ROOM_ID}/play/`;
        }
      })
      .catch(() => {});
  }, 4000);
}

document.addEventListener("DOMContentLoaded", function () {
  initWebSocket();
  startStatusPoll();

  const startBtn = document.getElementById("start-btn");
  if (startBtn) {
    startBtn.addEventListener("click", startGame);
  }
});

// Reinitialize when restored from browser back-forward cache
window.addEventListener("pageshow", function (e) {
  if (e.persisted) {
    if (ws) { try { ws.close(); } catch (_) {} ws = null; }
    initWebSocket();
  }
});
