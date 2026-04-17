const chatForm       = document.getElementById("chatForm");
const questionInput  = document.getElementById("questionInput");
const sendButton     = document.getElementById("sendButton");
const messages       = document.getElementById("messages");
const messageTemplate = document.getElementById("messageTemplate");
const statusPill     = document.getElementById("statusPill");
const welcomeCard    = document.getElementById("welcomeCard");
const themeToggle    = document.getElementById("themeToggle");
const sunIcon        = document.querySelector(".sun-icon");
const moonIcon       = document.querySelector(".moon-icon");
const sourcesModal   = document.getElementById("sourcesModal");
const modalBody      = document.getElementById("modalBody");
const modalClose     = document.getElementById("modalClose");
const BOT_ICON_MARKUP = `
  <div class="bot-icon bot-small" aria-hidden="true">
    <span class="bot-eye bot-eye-left">&gt;</span>
    <span class="bot-eye bot-eye-right">&lt;</span>
    <span class="bot-foot bot-foot-left"></span>
    <span class="bot-foot bot-foot-right"></span>
  </div>
`;
const USER_ICON_MARKUP = `
  <svg class="user-avatar-icon" viewBox="0 0 64 64" role="img" aria-label="User">
    <circle cx="32" cy="32" r="32" fill="#d8d8d8"></circle>
    <circle cx="32" cy="22" r="12" fill="#000000"></circle>
    <path d="M15 53c0-9.9 8.1-18 18-18h-2c9.9 0 18 8.1 18 18v2H15v-2z" fill="#000000"></path>
  </svg>
`;

function extractSources(text) {
  const match = text.match(/\n*Sources:\s*(.+)$/s);
  if (!match) return { content: text, sources: null };
  const content = text.slice(0, text.indexOf(match[0])).trim();
  return { content, sources: match[1].trim() };
}

function parseSources(sourcesStr) {
  const items = [];
  const parts = sourcesStr.split(/,\s*(?=S\d+=)/);
  for (const part of parts) {
    const eq = part.indexOf("=");
    if (eq === -1) continue;
    const id    = part.slice(0, eq).trim();
    const value = part.slice(eq + 1).trim();
    items.push({ id, value });
  }
  return items;
}

function showSourcesModal(sourcesStr, content) {
  let items = parseSources(sourcesStr);

  const cited = new Set([...content.matchAll(/\[S(\d+)\]/g)].map(m => `S${m[1]}`));
  if (cited.size > 0) items = items.filter(item => cited.has(item.id));

  const seen = new Set();
  items = items.filter(({ id, value }) => {
    const key = id + value;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });

  modalBody.innerHTML = items.map(({ id, value }) =>
    `<div class="source-item"><span class="source-id">${id}</span>${value}</div>`
  ).join("");
  sourcesModal.hidden = false;
}

modalClose.addEventListener("click", () => { sourcesModal.hidden = true; });
sourcesModal.addEventListener("click", (e) => {
  if (e.target === sourcesModal) sourcesModal.hidden = true;
});

const sampleButtons = document.querySelectorAll("[data-question]");
let isPending = false;

// ── Theme ───────────────────────────────────────────────────
function initializeTheme() {
  const saved = localStorage.getItem("theme");
  const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  setTheme(saved || (prefersDark ? "dark" : "light"));
}

function setTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  localStorage.setItem("theme", theme);
  if (theme === "dark") {
    sunIcon.style.display  = "none";
    moonIcon.style.display = "block";
  } else {
    sunIcon.style.display  = "block";
    moonIcon.style.display = "none";
  }
}

function toggleTheme() {
  const current = document.documentElement.getAttribute("data-theme") || "dark";
  setTheme(current === "dark" ? "light" : "dark");
}

themeToggle.addEventListener("click", toggleTheme);
window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", (e) => {
  if (!localStorage.getItem("theme")) setTheme(e.matches ? "dark" : "light");
});

// ── Input auto-resize ────────────────────────────────────────
function autoResizeInput() {
  questionInput.style.height = "auto";
  questionInput.style.height = `${Math.min(questionInput.scrollHeight, 180)}px`;
}

// ── Pending state ────────────────────────────────────────────
function setPendingState(pending) {
  isPending = pending;
  sendButton.disabled  = pending;
  questionInput.disabled = pending;
  statusPill.textContent   = pending ? "Thinking…" : "Ready";
  statusPill.dataset.thinking = pending ? "true" : "false";
}

function removeWelcomeCard() {
  if (welcomeCard && welcomeCard.parentNode) {
    welcomeCard.parentNode.removeChild(welcomeCard);
  }
}

// ── Typing animation ─────────────────────────────────────────
async function typeText(bubble, text, speed = 10) {
  return new Promise(resolve => {
    const words = text.split(/(\s+)/);
    let i = 0;
    bubble.classList.add("typing");

    function tick() {
      i++;
      bubble.innerHTML = marked.parse(words.slice(0, i).join(""));
      messages.scrollTop = messages.scrollHeight;
      if (i < words.length) {
        setTimeout(tick, speed);
      } else {
        bubble.classList.remove("typing");
        resolve();
      }
    }
    setTimeout(tick, speed);
  });
}

// ── Create message ───────────────────────────────────────────
function createMessage(role, content, isLoading = false) {
  const fragment = messageTemplate.content.cloneNode(true);
  const row     = fragment.querySelector(".message-row");
  const speaker = fragment.querySelector(".speaker");
  const bubble  = fragment.querySelector(".bubble");
  const avatar  = fragment.querySelector(".avatar");

  row.classList.add(role);
  speaker.textContent = role === "user" ? "You" : "Control Tower AI";
  if (role === "user") {
    avatar.innerHTML = USER_ICON_MARKUP;
  } else {
    avatar.innerHTML = BOT_ICON_MARKUP;
  }

  if (isLoading) {
    row.classList.add("is-thinking");
    bubble.classList.add("loading");
    bubble.innerHTML = '<span class="dot"></span><span class="dot"></span><span class="dot"></span>';
  } else if (role === "user") {
    bubble.textContent = content;
  } else {
    const { content: main, sources } = extractSources(content);
    bubble.innerHTML = marked.parse(main);
    if (sources) {
      const btn = document.createElement("button");
      btn.className = "sources-btn";
      btn.textContent = "Sources";
      btn.addEventListener("click", () => showSourcesModal(sources, main));
      fragment.querySelector(".bubble-wrap").appendChild(btn);
    }
  }

  messages.appendChild(fragment);
  messages.scrollTop = messages.scrollHeight;
  return messages.lastElementChild;
}

// ── Main ask fn ──────────────────────────────────────────────
async function askQuestion(questionText) {
  const question = questionText.trim();
  if (!question || isPending) return;

  removeWelcomeCard();
  createMessage("user", question);

  const loadingRow    = createMessage("assistant", "", true);
  const loadingBubble = loadingRow.querySelector(".bubble");

  setPendingState(true);

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });

    const payload = await response.json().catch(() => ({}));

    if (!response.ok) {
      throw new Error(payload.detail || "The chat endpoint returned an error.");
    }

    const rawAnswer = (payload.answer || "No answer returned.").trim();
    const { content: main, sources } = extractSources(rawAnswer);

    loadingBubble.classList.remove("loading");
    await typeText(loadingBubble, main);

    if (sources) {
      const btn = document.createElement("button");
      btn.className = "sources-btn";
      btn.textContent = "Sources";
      btn.addEventListener("click", () => showSourcesModal(sources, main));
      loadingRow.querySelector(".bubble-wrap").appendChild(btn);
    }
  } catch (error) {
    loadingBubble.classList.remove("loading");
    loadingBubble.textContent = `Could not get a response. ${error.message}`;
  } finally {
    loadingRow.classList.remove("is-thinking");
    setPendingState(false);
    questionInput.value = "";
    autoResizeInput();
    questionInput.focus();
    messages.scrollTop = messages.scrollHeight;
  }
}

// ── Event listeners ──────────────────────────────────────────
chatForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  await askQuestion(questionInput.value);
});

questionInput.addEventListener("input", autoResizeInput);
questionInput.addEventListener("keydown", async (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    await askQuestion(questionInput.value);
  }
});

sampleButtons.forEach((btn) => {
  btn.addEventListener("click", async () => {
    const q = btn.getAttribute("data-question") || "";
    questionInput.value = q;
    autoResizeInput();
    await askQuestion(q);
  });
});

questionInput.focus();
autoResizeInput();
initializeTheme();