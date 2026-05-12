const sessionsEl = document.getElementById("sessions");
const messagesEl = document.getElementById("messages");
const chatTitleEl = document.getElementById("chatTitle");
const chatMetaEl = document.getElementById("chatMeta");
const promptInput = document.getElementById("promptInput");
const chatForm = document.getElementById("chatForm");
const sendButton = document.getElementById("sendButton");
const newChatButton = document.getElementById("newChatButton");
const deleteChatButton = document.getElementById("deleteChatButton");

let activeSessionId = localStorage.getItem("activeSessionId") || "";
let sessions = [];

function roleLabel(role) {
  return role === "user" ? "Sen" : "Asistan";
}

function renderMessages(messages) {
  messagesEl.innerHTML = "";
  if (!messages.length) {
    const empty = document.createElement("div");
    empty.className = "message assistant";
    empty.innerHTML = '<span class="role">Asistan</span>Yeni sohbet başlatabilirsiniz.';
    messagesEl.appendChild(empty);
    return;
  }

  for (const item of messages) {
    const node = document.createElement("div");
    node.className = `message ${item.role === "user" ? "user" : "assistant"}`;

    const role = document.createElement("span");
    role.className = "role";
    role.textContent = roleLabel(item.role);

    const content = document.createElement("div");
    content.textContent = item.content || "";

    node.appendChild(role);
    node.appendChild(content);
    messagesEl.appendChild(node);
  }
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function renderSessions() {
  sessionsEl.innerHTML = "";
  for (const session of sessions) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `sessionButton ${session.id === activeSessionId ? "active" : ""}`;
    button.dataset.id = session.id;

    const title = document.createElement("span");
    title.className = "sessionTitle";
    title.textContent = session.title || "Sohbet";

    const preview = document.createElement("span");
    preview.className = "sessionPreview";
    preview.textContent = session.last_message || `${session.message_count || 0} mesaj`;

    button.appendChild(title);
    button.appendChild(preview);
    button.addEventListener("click", () => loadSession(session.id));
    sessionsEl.appendChild(button);
  }
}

async function loadSessions() {
  const response = await fetch("/chat/sessions");
  const data = await response.json();
  sessions = data.items || [];
  renderSessions();

  if (activeSessionId) {
    await loadSession(activeSessionId, false);
  } else {
    chatTitleEl.textContent = "Yeni sohbet";
    chatMetaEl.textContent = "Yeni düğmesine basarak bağımsız sohbet açın.";
    renderMessages([]);
  }
}

async function loadSession(sessionId, refreshList = true) {
  const response = await fetch(`/chat/sessions/${sessionId}`);
  if (!response.ok) {
    activeSessionId = "";
    localStorage.removeItem("activeSessionId");
    renderMessages([]);
    return;
  }

  const data = await response.json();
  activeSessionId = data.session.id;
  localStorage.setItem("activeSessionId", activeSessionId);
  chatTitleEl.textContent = data.session.title || "Sohbet";
  chatMetaEl.textContent = `${data.messages.length} mesaj`;
  renderMessages(data.messages || []);
  if (refreshList) {
    await loadSessions();
  } else {
    renderSessions();
  }
}

async function createNewSession() {
  const response = await fetch("/chat/sessions", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({}),
  });
  const session = await response.json();
  activeSessionId = session.id;
  localStorage.setItem("activeSessionId", activeSessionId);
  chatTitleEl.textContent = session.title;
  chatMetaEl.textContent = "0 mesaj";
  renderMessages([]);
  await loadSessions();
  promptInput.focus();
}

async function deleteActiveSession() {
  if (!activeSessionId) {
    return;
  }
  await fetch(`/chat/sessions/${activeSessionId}`, {method: "DELETE"});
  activeSessionId = "";
  localStorage.removeItem("activeSessionId");
  chatTitleEl.textContent = "Yeni sohbet";
  chatMetaEl.textContent = "Yeni düğmesine basarak bağımsız sohbet açın.";
  renderMessages([]);
  await loadSessions();
}

async function sendMessage(text) {
  if (!activeSessionId) {
    await createNewSession();
  }

  sendButton.disabled = true;
  promptInput.disabled = true;

  const pending = [
    {role: "user", content: text},
    {role: "assistant", content: "Yanıt hazırlanıyor..."},
  ];
  renderMessages(pending);

  try {
    const response = await fetch("/chat", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        message: text,
        session_id: activeSessionId || null,
      }),
    });

    if (!response.ok) {
      const detail = await response.text();
      throw new Error(detail || "İstek başarısız oldu.");
    }

    const data = await response.json();
    activeSessionId = data.session_id;
    localStorage.setItem("activeSessionId", activeSessionId);
    chatTitleEl.textContent = data.session?.title || "Sohbet";
    renderMessages(data.messages || []);
    await loadSessions();
  } catch (error) {
    renderMessages([
      {role: "user", content: text},
      {role: "assistant", content: `Hata: ${error.message}`},
    ]);
  } finally {
    sendButton.disabled = false;
    promptInput.disabled = false;
    promptInput.focus();
  }
}

chatForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const text = promptInput.value.trim();
  if (!text) {
    return;
  }
  promptInput.value = "";
  await sendMessage(text);
});

newChatButton.addEventListener("click", createNewSession);
deleteChatButton.addEventListener("click", deleteActiveSession);

loadSessions();
