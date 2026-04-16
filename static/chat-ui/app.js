const chatForm = document.getElementById("chatForm");
const questionInput = document.getElementById("questionInput");
const sendButton = document.getElementById("sendButton");
const messages = document.getElementById("messages");
const messageTemplate = document.getElementById("messageTemplate");
const statusPill = document.getElementById("statusPill");
const welcomeCard = document.getElementById("welcomeCard");
const themeToggle = document.getElementById("themeToggle");
const sunIcon = document.querySelector(".sun-icon");
const moonIcon = document.querySelector(".moon-icon");
const sourcesModal = document.getElementById("sourcesModal");
const modalBody = document.getElementById("modalBody");
const modalClose = document.getElementById("modalClose");

function extractSources(text) {
  const match = text.match(/\n*Sources:\s*(.+)$/s);
  if (!match) return { content: text, sources: null };
  const content = text.slice(0, text.indexOf(match[0])).trim();
  return { content, sources: match[1].trim() };
}

function parseSources(sourcesStr) {
  // Format: S1=services.foo/bar, S2=services.baz/qux,...
  const items = [];
  const parts = sourcesStr.split(/,\s*(?=S\d+=)/);
  for (const part of parts) {
    const eq = part.indexOf("=");
    if (eq === -1) continue;
    const id = part.slice(0, eq).trim();
    const value = part.slice(eq + 1).trim();
    items.push({ id, value });
  }
  return items;
}

function showSourcesModal(sourcesStr, content) {
  let items = parseSources(sourcesStr);

  // Filter to only sources actually cited in the content ([S1], [S2], etc.)
  const cited = new Set([...content.matchAll(/\[S(\d+)\]/g)].map(m => `S${m[1]}`));
  if (cited.size > 0) {
    items = items.filter(item => cited.has(item.id));
  }

  // Deduplicate by id+value
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

// Theme Management
function initializeTheme() {
  const savedTheme = localStorage.getItem("theme");
  const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  const theme = savedTheme || (prefersDark ? "dark" : "light");
  setTheme(theme);
}

function setTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  localStorage.setItem("theme", theme);

  // Update icon visibility
  if (theme === "dark") {
    sunIcon.style.display = "none";
    moonIcon.style.display = "block";
  } else {
    sunIcon.style.display = "block";
    moonIcon.style.display = "none";
  }
}

function toggleTheme() {
  const currentTheme = document.documentElement.getAttribute("data-theme") || "dark";
  const newTheme = currentTheme === "dark" ? "light" : "dark";
  setTheme(newTheme);
}

themeToggle.addEventListener("click", toggleTheme);

// Listen for system theme changes
window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", (e) => {
  if (!localStorage.getItem("theme")) {
    setTheme(e.matches ? "dark" : "light");
  }
});

function autoResizeInput() {
  questionInput.style.height = "auto";
  questionInput.style.height = `${Math.min(questionInput.scrollHeight, 180)}px`;
}

function setPendingState(pending) {
  isPending = pending;
  sendButton.disabled = pending;
  questionInput.disabled = pending;
  statusPill.textContent = pending ? "Thinking..." : "Ready";
}

function removeWelcomeCard() {
  if (welcomeCard && welcomeCard.parentNode) {
    welcomeCard.parentNode.removeChild(welcomeCard);
  }
}

function createMessage(role, content, isLoading = false) {
  const fragment = messageTemplate.content.cloneNode(true);
  const row = fragment.querySelector(".message-row");
  const speaker = fragment.querySelector(".speaker");
  const bubble = fragment.querySelector(".bubble");

  row.classList.add(role);
  speaker.textContent = role === "user" ? "You" : "Control Tower AI";

  if (isLoading) {
    bubble.classList.add("loading");
    bubble.innerHTML = '<span class="dot"></span><span class="dot"></span><span class="dot"></span>';
  } else if (role === "user") {
    bubble.textContent = content;
  } else {
    const { content: mainContent, sources } = extractSources(content);
    bubble.innerHTML = marked.parse(mainContent);
    if (sources) {
      const btn = document.createElement("button");
      btn.className = "sources-btn";
      btn.textContent = "Sources";
      btn.addEventListener("click", () => showSourcesModal(sources, mainContent));
      fragment.querySelector(".bubble-wrap").appendChild(btn);
    }
  }

  messages.appendChild(fragment);
  messages.scrollTop = messages.scrollHeight;

  return messages.lastElementChild;
}

async function askQuestion(questionText) {
  const question = questionText.trim();
  if (!question || isPending) {
    return;
  }

  removeWelcomeCard();
  createMessage("user", question);

  const loadingRow = createMessage("assistant", "", true);
  const loadingBubble = loadingRow.querySelector(".bubble");

  setPendingState(true);

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ question }),
    });

    const payload = await response.json().catch(() => ({}));

    if (!response.ok) {
      const errorMessage = payload.detail || "The chat endpoint returned an error.";
      throw new Error(errorMessage);
    }

    const rawAnswer = (payload.answer || "No answer returned.").trim();
    const { content: mainContent, sources } = extractSources(rawAnswer);
    loadingBubble.classList.remove("loading");
    loadingBubble.innerHTML = marked.parse(mainContent);
    if (sources) {
      const btn = document.createElement("button");
      btn.className = "sources-btn";
      btn.textContent = "Sources";
      btn.addEventListener("click", () => showSourcesModal(sources, mainContent));
      loadingRow.querySelector(".bubble-wrap").appendChild(btn);
    }
  } catch (error) {
    loadingBubble.classList.remove("loading");
    loadingBubble.textContent = `I could not get a response. ${error.message}`;
  } finally {
    setPendingState(false);
    questionInput.value = "";
    autoResizeInput();
    questionInput.focus();
    messages.scrollTop = messages.scrollHeight;
  }
}

chatForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  await askQuestion(questionInput.value);
});

questionInput.addEventListener("input", autoResizeInput);
questionInput.addEventListener("keydown", async (event) => {
  if (event.key === "Enter") {
    if (event.shiftKey) {
      // Allow Shift+Enter to insert a new line
      return;
    }
    // Enter alone sends the message
    event.preventDefault();
    await askQuestion(questionInput.value);
  }
});

sampleButtons.forEach((button) => {
  button.addEventListener("click", async () => {
    const question = button.getAttribute("data-question") || "";
    questionInput.value = question;
    autoResizeInput();
    await askQuestion(question);
  });
});

questionInput.focus();
autoResizeInput();

// Initialize theme
initializeTheme();
