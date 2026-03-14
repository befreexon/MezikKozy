/* Chat module – works alongside lobby.js or game.js.
   Requires: ws (WebSocket), escapeHtml()  */

function initChat() {
  const input = document.getElementById("chat-input");
  const sendBtn = document.getElementById("chat-send");
  if (!input || !sendBtn) return;

  function sendChatMessage() {
    const text = input.value.trim();
    if (!text) return;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ action: "send_chat", text }));
      input.value = "";
    } else {
      input.placeholder = "Připojování… zkuste za chvíli";
      setTimeout(() => { input.placeholder = "Napište zprávu…"; }, 2000);
    }
  }

  sendBtn.addEventListener("click", sendChatMessage);
  input.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendChatMessage();
    }
  });
}

function appendChatMessage(msg) {
  const list = document.getElementById("chat-messages");
  if (!list) return;

  const div = document.createElement("div");
  div.className = "chat-msg";
  div.innerHTML = `<span class="chat-user">${escapeHtml(msg.username)}</span>` +
                  `<span class="chat-ts">${escapeHtml(msg.ts)}</span>` +
                  `<div class="chat-text">${escapeHtml(msg.text)}</div>`;
  list.appendChild(div);
  list.scrollTop = list.scrollHeight;
}

function loadChatHistory(messages) {
  const list = document.getElementById("chat-messages");
  if (!list) return;
  list.innerHTML = "";
  messages.forEach(appendChatMessage);
}

document.addEventListener("DOMContentLoaded", initChat);
