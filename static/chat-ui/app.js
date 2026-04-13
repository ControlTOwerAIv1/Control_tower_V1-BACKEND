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
  } else {
    bubble.textContent = content;
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

    const answer = (payload.answer || "No answer returned.").trim();
    loadingBubble.classList.remove("loading");
    loadingBubble.textContent = answer;
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
  if (event.key === "Enter" && !event.shiftKey) {
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
