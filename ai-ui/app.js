const sessionsEl = document.getElementById("sessions");
const messagesEl = document.getElementById("messages");
const chatTitleEl = document.getElementById("chatTitle");
const chatMetaEl = document.getElementById("chatMeta");
const promptInput = document.getElementById("promptInput");
const chatForm = document.getElementById("chatForm");
const sendButton = document.getElementById("sendButton");
const newChatButton = document.getElementById("newChatButton");
const deleteChatButton = document.getElementById("deleteChatButton");
const backupNowButton = document.getElementById("backupNowButton");

const SETTINGS_KEY = "aiUiSettingsV1";
const STORAGE_KEY = "aiUiChatsV1";
const ACTIVE_KEY = "aiUiActiveChatIdV1";

function getRuntimeConfig() {
  if (typeof window === "undefined") return {};
  const value = window.__RAG_RUNTIME_CONFIG__;
  return value && typeof value === "object" ? value : {};
}

const DEFAULT_MODEL_ID = String(getRuntimeConfig().model || "local-rag").trim() || "local-rag";

function detectDefaultApiBaseUrl() {
  const runtimeValue = String(getRuntimeConfig().apiBaseUrl || "").trim();
  if (runtimeValue) return runtimeValue;

  const params = new URLSearchParams(window.location.search);
  const queryValue = (params.get("apiBaseUrl") || "").trim();
  if (queryValue) return queryValue;

  if (window.location.protocol === "http:" || window.location.protocol === "https:") {
    return window.location.origin;
  }

  return String(loadSettings().aiBaseUrl || "").trim();
}

function loadSettings() {
  try {
    const raw = localStorage.getItem(SETTINGS_KEY);
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

function defaultSettings() {
  return {
    aiBaseUrl: detectDefaultApiBaseUrl(),
    model: DEFAULT_MODEL_ID,
  };
}

function getSettings() {
  return { ...defaultSettings(), ...loadSettings() };
}

function saveSettings(settings) {
  localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
}

let settings = getSettings();
saveSettings(settings);

function getApiBaseUrl() {
  return String(settings.aiBaseUrl || detectDefaultApiBaseUrl()).trim().replace(/\/+$/, "");
}

function nowIso() {
  return new Date().toISOString();
}

function makeId() {
  if (typeof crypto !== "undefined" && crypto.randomUUID) return crypto.randomUUID();
  return `chat_${Math.random().toString(16).slice(2)}_${Date.now()}`;
}

function loadChats() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : { items: [] };
    if (!parsed || !Array.isArray(parsed.items)) return { items: [] };
    return parsed;
  } catch {
    return { items: [] };
  }
}

function saveChats(state) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
}

function roleLabel(role) {
  return role === "user" ? "Sen" : "Asistan";
}

function renderMessages(messages) {
  messagesEl.innerHTML = "";
  if (!messages.length) {
    const empty = document.createElement("div");
    empty.className = "message assistant";
    empty.innerHTML = '<span class="role">Asistan</span><div class="messageBody">Yeni sohbet baslatabilirsiniz.</div>';
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
    content.className = "messageBody";
    content.textContent = item.content || "";

    node.appendChild(role);
    node.appendChild(content);
    messagesEl.appendChild(node);
  }
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function chatPreview(chat) {
  const last = chat.messages[chat.messages.length - 1];
  if (!last) return "0 mesaj";
  const txt = String(last.content || "");
  return txt.length > 72 ? `${txt.slice(0, 72)}...` : txt;
}

let state = loadChats();
let activeChatId = localStorage.getItem(ACTIVE_KEY) || "";

async function importChatsFromBackend(limit = 20) {
  const baseUrl = getApiBaseUrl();
  const response = await fetch(`${baseUrl}/chat/sessions?limit=${limit}`);
  if (!response.ok) {
    throw new Error("Could not load chat history.");
  }

  const data = await response.json();
  const sessions = Array.isArray(data && data.items) ? data.items : [];
  if (!sessions.length) {
    return false;
  }

  const hydrated = await Promise.all(
    sessions.map(async (session) => {
      const details = await fetch(`${baseUrl}/chat/sessions/${session.id}`);
      if (!details.ok) {
        return null;
      }
      const payload = await details.json();
      const messages = Array.isArray(payload && payload.messages) ? payload.messages : [];
      return {
        id: session.id,
        title: session.title || "Chat",
        created_at: session.created_at || nowIso(),
        updated_at: session.updated_at || nowIso(),
        messages: messages.map((message) => ({
          role: message.role,
          content: typeof message.content === "string" ? message.content : String(message.content ?? ""),
        })),
        backend_session_id: session.id,
        backed_up: true,
        backup_session_id: session.id,
      };
    })
  );

  state.items = hydrated.filter(Boolean);
  saveChats(state);
  return state.items.length > 0;
}

function getActiveChat() {
  return state.items.find((c) => c.id === activeChatId) || null;
}

function setActiveChat(chatId) {
  activeChatId = chatId || "";
  if (activeChatId) localStorage.setItem(ACTIVE_KEY, activeChatId);
  else localStorage.removeItem(ACTIVE_KEY);
}

function ensureSomeChat() {
  if (state.items.length && state.items.some((c) => c.id === activeChatId)) {
    return;
  }
  if (state.items.length) {
    setActiveChat(state.items[0].id);
    return;
  }
  const chat = {
    id: makeId(),
    title: "Yeni sohbet",
    created_at: nowIso(),
    updated_at: nowIso(),
    messages: [],
    backend_session_id: null,
    backed_up: false,
    backup_session_id: null,
  };
  state.items.unshift(chat);
  saveChats(state);
  setActiveChat(chat.id);
}

function renderSessions() {
  sessionsEl.innerHTML = "";
  for (const chat of state.items) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `sessionButton ${chat.id === activeChatId ? "active" : ""}`;
    button.dataset.id = chat.id;

    const title = document.createElement("span");
    title.className = "sessionTitle";
    title.textContent = chat.title || "Sohbet";

    const preview = document.createElement("span");
    preview.className = "sessionPreview";
    preview.textContent = chatPreview(chat);

    button.appendChild(title);
    button.appendChild(preview);
    button.addEventListener("click", () => loadChat(chat.id));
    sessionsEl.appendChild(button);
  }
}

function loadChat(chatId) {
  const chat = state.items.find((c) => c.id === chatId);
  if (!chat) return;
  setActiveChat(chat.id);
  chatTitleEl.textContent = chat.title || "Sohbet";
  const metaParts = [`${chat.messages.length} mesaj`, settings.model || DEFAULT_MODEL_ID];
  if (chat.backed_up && chat.backup_session_id) {
    metaParts.push(`Yedek id: ${chat.backup_session_id}`);
  }
  chatMetaEl.textContent = metaParts.join(" | ");
  renderMessages(chat.messages);
  renderSessions();
  promptInput.focus();
}

async function backupChat(chat) {
  if (!chat || !chat.messages.length) return null;
  const baseUrl = getApiBaseUrl();
  const response = await fetch(`${baseUrl}/chat/backup`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      title: chat.title || null,
      messages: chat.messages.map((m) => ({ role: m.role, content: m.content })),
    }),
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || "Yedekleme basarisiz.");
  }
  return await response.json();
}

async function createNewChat({ backupPrevious } = { backupPrevious: true }) {
  const previous = getActiveChat();

  if (backupPrevious && previous && previous.messages.length) {
    try {
      const result = await backupChat(previous);
      previous.backed_up = true;
      previous.backup_session_id = result && result.session_id ? result.session_id : null;
    } catch {
      previous.backed_up = false;
    }
  }

  const chat = {
    id: makeId(),
    title: "Yeni sohbet",
    created_at: nowIso(),
    updated_at: nowIso(),
    messages: [],
    backend_session_id: null,
    backed_up: false,
    backup_session_id: null,
  };
  state.items.unshift(chat);
  saveChats(state);
  setActiveChat(chat.id);
  loadChat(chat.id);
}

function deleteActiveChat() {
  const chat = getActiveChat();
  if (!chat) return;
  state.items = state.items.filter((c) => c.id !== chat.id);
  saveChats(state);
  if (state.items.length) {
    setActiveChat(state.items[0].id);
    loadChat(state.items[0].id);
  } else {
    setActiveChat("");
    ensureSomeChat();
    loadChat(activeChatId);
  }
}

async function ensureBackendSession(chat) {
  if (chat.backend_session_id) return chat.backend_session_id;
  const baseUrl = getApiBaseUrl();
  const response = await fetch(`${baseUrl}/chat/sessions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title: chat.title || null }),
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || "Session olusturma basarisiz.");
  }
  const session = await response.json();
  chat.backend_session_id = session && session.id ? session.id : null;
  saveChats(state);
  return chat.backend_session_id;
}

async function sendMessage(text) {
  const chat = getActiveChat();
  if (!chat) return;

  chat.updated_at = nowIso();
  chat.messages.push({ role: "user", content: text });
  chat.messages.push({ role: "assistant", content: "Yanit hazirlaniyor..." });
  saveChats(state);
  loadChat(chat.id);

  sendButton.disabled = true;
  promptInput.disabled = true;

  try {
    const baseUrl = getApiBaseUrl();
    const sessionId = await ensureBackendSession(chat);
    const response = await fetch(`${baseUrl}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: text,
        session_id: sessionId,
      }),
    });

    if (!response.ok) {
      const detail = await response.text();
      throw new Error(detail || "Istek basarisiz.");
    }

    const data = await response.json();
    if (data && data.session_id && !chat.backend_session_id) {
      chat.backend_session_id = data.session_id;
    }

    const backendMessages = Array.isArray(data && data.messages) ? data.messages : null;
    if (backendMessages) {
      chat.messages = backendMessages.map((m) => ({
        role: m.role,
        content: typeof m.content === "string" ? m.content : String(m.content ?? ""),
      }));
    } else {
      const answer = (data && data.answer) || "";
      chat.messages[chat.messages.length - 1] = { role: "assistant", content: String(answer || "") };
    }
    chat.updated_at = nowIso();
    saveChats(state);
    loadChat(chat.id);
  } catch (error) {
    chat.messages[chat.messages.length - 1] = { role: "assistant", content: `Hata: ${error.message}` };
    saveChats(state);
    loadChat(chat.id);
  } finally {
    sendButton.disabled = false;
    promptInput.disabled = false;
    promptInput.focus();
  }
}

chatForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const text = promptInput.value.trim();
  if (!text) return;
  promptInput.value = "";
  await sendMessage(text);
});

newChatButton.addEventListener("click", () => createNewChat({ backupPrevious: true }));
deleteChatButton.addEventListener("click", deleteActiveChat);
backupNowButton.addEventListener("click", async () => {
  const chat = getActiveChat();
  if (!chat) return;
  try {
    const result = await backupChat(chat);
    chat.backed_up = true;
    chat.backup_session_id = result && result.session_id ? result.session_id : null;
    saveChats(state);
    loadChat(chat.id);
  } catch (e) {
    chatMetaEl.textContent = `Yedekleme hatasi: ${e.message}`;
  }
});

async function bootstrap() {
  if (!state.items.length) {
    try {
      await importChatsFromBackend();
    } catch {
      // Fall back to an empty local chat if server history cannot be loaded.
    }
  }

  ensureSomeChat();
  loadChat(activeChatId);
}

bootstrap();
