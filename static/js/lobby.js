/* Lobby WebSocket handler */
/* Expects globals: ROOM_ID, IS_HOST, CURRENT_USER_ID */

let ws = null;

function initWebSocket() {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  ws = new WebSocket(`${protocol}//${window.location.host}/ws/game/${ROOM_ID}/`);

  ws.onopen = function () {
    console.log("Connected to lobby");
  };

  ws.onmessage = function (e) {
    const data = JSON.parse(e.data);

    if (data.type === "room_update") {
      updateRoom(data.room);
      if (data.room.status === "playing") {
        window.location.href = `/room/${ROOM_ID}/play/`;
      }
    } else if (data.type === "state_update") {
      // Game already started – redirect immediately
      window.location.href = `/room/${ROOM_ID}/play/`;
    } else if (data.type === "error") {
      console.error("Server error:", data.message);
    }
  };

  ws.onclose = function () {
    console.log("Disconnected from lobby");
  };
}

function updateRoom(room) {
  updatePlayerList(room.players);
  updatePlayerCount(room.players.length, room.max_players);
  if (IS_HOST) {
    updateStartButton(room.players.length);
  }
}

function updatePlayerList(players) {
  const listEl = document.getElementById("player-list");
  if (!listEl) return;

  listEl.innerHTML = players
    .map(
      (p) => `
        <div class="lobby-player">
          <span class="lobby-player-name">${escapeHtml(p.username)}</span>
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
  }
}

function escapeHtml(str) {
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

document.addEventListener("DOMContentLoaded", function () {
  initWebSocket();

  const startBtn = document.getElementById("start-btn");
  if (startBtn) {
    startBtn.addEventListener("click", startGame);
  }
});
