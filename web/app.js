import { animate } from "https://cdn.jsdelivr.net/npm/motion@11.13.5/+esm";

const AUTOCOMPLETE_DEBOUNCE_MS = 200;
const AUTOCOMPLETE_MIN_LEN = 2; // mirrors the backend's MIN_AUTOCOMPLETE_PREFIX_LEN
const CONFETTI_COLORS = ["#F4B93C", "#42E08A", "#F6FAF5", "#E5483C", "#58C4DC"];

let gameId = null;
let clues = [];
let solved = false;
let autocompleteTimer = null;

const el = {
  newGameBtn: document.getElementById("new-game-btn"),
  difficulty: document.getElementById("difficulty"),
  game: document.getElementById("game"),
  cluesContainer: document.getElementById("clues-container"),
  reorderBtn: document.getElementById("reorder-btn"),
  hintBtn: document.getElementById("hint-btn"),
  hintsList: document.getElementById("hints-list"),
  guessForm: document.getElementById("guess-form"),
  guessInput: document.getElementById("guess-input"),
  autocompleteList: document.getElementById("autocomplete-list"),
  revealBtn: document.getElementById("reveal-btn"),
  feedback: document.getElementById("feedback"),
};

async function api(path, options = {}) {
  const resp = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!resp.ok) {
    throw new Error(`${options.method || "GET"} ${path} -> ${resp.status}`);
  }
  return resp.json();
}

function renderClueCard(clue) {
  const card = document.createElement("div");
  card.className = "clue-card";

  const avatars = document.createElement("div");
  avatars.className = "avatars";

  if (clue.teammate_photo_url) {
    const img = document.createElement("img");
    img.className = "teammate-photo";
    img.src = clue.teammate_photo_url;
    img.alt = clue.teammate_display_name;
    img.onerror = () => { img.replaceWith(photoPlaceholder()); };
    avatars.appendChild(img);
  } else {
    avatars.appendChild(photoPlaceholder());
  }

  if (clue.team_crest_url) {
    const crest = document.createElement("img");
    crest.className = "crest";
    crest.src = clue.team_crest_url;
    crest.alt = clue.team_name;
    crest.onerror = () => crest.remove();
    avatars.appendChild(crest);
  }

  card.appendChild(avatars);

  const name = document.createElement("div");
  name.className = "teammate-name";
  name.textContent = clue.teammate_display_name;
  card.appendChild(name);

  const clubSeason = document.createElement("div");
  clubSeason.className = "club-season";
  clubSeason.textContent = `${clue.team_name} — ${clue.season_name} ${clue.competition_name}`;
  card.appendChild(clubSeason);

  return card;
}

function photoPlaceholder() {
  const div = document.createElement("div");
  div.className = "photo-placeholder";
  div.textContent = "?";
  return div;
}

function renderClues(list) {
  el.cluesContainer.innerHTML = "";
  for (const clue of list) {
    el.cluesContainer.appendChild(renderClueCard(clue));
  }
}

function reorderChronologically() {
  // Client-side only -- no server call. A free, instant hint: the clues already
  // carry a real date, this just un-scrambles what's already on screen.
  const sorted = [...clues].sort((a, b) => a.season_start_year - b.season_start_year);
  renderClues(sorted);
}

function setFeedback(headline, detail, kind) {
  el.feedback.innerHTML = "";
  el.feedback.className = `feedback ${kind || ""}`;
  if (!headline) return;

  const h = document.createElement("span");
  h.className = "headline";
  h.textContent = headline;
  el.feedback.appendChild(h);

  if (detail) {
    const d = document.createElement("span");
    d.className = "detail";
    d.textContent = detail;
    el.feedback.appendChild(d);
  }

  animate(el.feedback, { opacity: [0, 1], scale: [0.85, 1] }, { duration: 0.35, ease: "easeOut" });
}

function addHint(text) {
  const li = document.createElement("li");
  li.textContent = text;
  el.hintsList.appendChild(li);
  animate(li, { opacity: [0, 1], x: [-12, 0] }, { duration: 0.3, ease: "easeOut" });
}

function shakeElement(element) {
  animate(element, { x: [0, -8, 8, -6, 6, 0] }, { duration: 0.4, ease: "easeInOut" });
}

function playVictorySound() {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const notes = [523.25, 659.25, 783.99, 1046.5]; // C5 E5 G5 C6 -- a bright ascending chime
    notes.forEach((freq, i) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "triangle";
      osc.frequency.value = freq;
      const startTime = ctx.currentTime + i * 0.1;
      gain.gain.setValueAtTime(0.0001, startTime);
      gain.gain.exponentialRampToValueAtTime(0.3, startTime + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, startTime + 0.35);
      osc.connect(gain).connect(ctx.destination);
      osc.start(startTime);
      osc.stop(startTime + 0.4);
    });
  } catch (e) {
    // Audio can fail (autoplay policy, unsupported browser, ...) -- never block the win over a sound.
    console.warn("Victory sound failed:", e);
  }
}

function celebrateConfetti(count = 60) {
  const layer = document.getElementById("confetti-layer");
  for (let i = 0; i < count; i++) {
    const piece = document.createElement("div");
    piece.className = "confetti-piece";
    piece.style.left = `${Math.random() * 100}%`;
    piece.style.background = CONFETTI_COLORS[i % CONFETTI_COLORS.length];
    layer.appendChild(piece);

    const fallDistance = window.innerHeight + 40;
    const duration = 1.8 + Math.random() * 1.4;
    const delay = Math.random() * 0.4;

    animate(
      piece,
      {
        y: [-20, fallDistance],
        x: [0, (Math.random() - 0.5) * 160],
        rotate: [0, 360 + Math.random() * 720],
        opacity: [1, 1, 0],
      },
      { duration, delay, ease: "easeIn" }
    );

    setTimeout(() => piece.remove(), (duration + delay) * 1000 + 100);
  }
}

function lockGame() {
  solved = true;
  el.hintBtn.disabled = true;
  el.guessForm.querySelector("button[type=submit]").disabled = true;
  el.guessInput.disabled = true;
  el.revealBtn.disabled = true;
}

async function startGame() {
  setFeedback("", "", "");
  el.hintsList.innerHTML = "";
  el.cluesContainer.innerHTML = "";
  el.guessInput.value = "";
  clearTimeout(autocompleteTimer);
  hideAutocomplete();
  solved = false;
  el.hintBtn.disabled = false;
  el.revealBtn.disabled = false;
  el.guessInput.disabled = false;
  el.guessForm.querySelector("button[type=submit]").disabled = false;

  const difficulty = el.difficulty.value;
  const data = await api(`/api/games?difficulty=${encodeURIComponent(difficulty)}`, {
    method: "POST",
  });

  gameId = data.game_id;
  clues = data.clues;
  el.game.hidden = false;
  renderClues(clues);
}

async function getHint() {
  if (!gameId || solved) return;
  el.hintBtn.disabled = true;
  try {
    const data = await api(`/api/games/${gameId}/hint`, { method: "POST" });
    addHint(data.hint_text);
  } finally {
    el.hintBtn.disabled = solved;
  }
}

async function submitGuess(guess) {
  if (!gameId || !guess.trim() || solved) return;
  const data = await api(`/api/games/${gameId}/guess`, {
    method: "POST",
    body: JSON.stringify({ guess }),
  });
  if (data.correct) {
    const detail = data.message.replace(/^Correct!\s*/, "");
    setFeedback("GOAL!", detail, "correct");
    playVictorySound();
    celebrateConfetti();
    lockGame();
  } else {
    setFeedback("OFFSIDE!", data.message, "incorrect");
    shakeElement(el.guessInput);
  }
}

async function reveal() {
  if (!gameId || solved) return;
  const data = await api(`/api/games/${gameId}/reveal`, { method: "POST" });
  setFeedback("FULL TIME", `It was ${data.player_name}.`, "reveal");
  lockGame();
}

function hideAutocomplete() {
  el.autocompleteList.hidden = true;
  el.autocompleteList.innerHTML = "";
}

async function fetchAutocomplete(prefix) {
  if (prefix.length < AUTOCOMPLETE_MIN_LEN) {
    hideAutocomplete();
    return;
  }
  const results = await api(`/api/players/autocomplete?prefix=${encodeURIComponent(prefix)}`);
  if (results.length === 0) {
    hideAutocomplete();
    return;
  }
  el.autocompleteList.innerHTML = "";
  for (const r of results) {
    const li = document.createElement("li");
    li.textContent = r.player_nickname || r.player_name;
    li.addEventListener("click", () => {
      el.guessInput.value = r.player_nickname || r.player_name;
      clearTimeout(autocompleteTimer); // a stale pending fetch from a prior keystroke
      hideAutocomplete();              // could otherwise re-show the dropdown after this
      el.guessInput.focus();
    });
    el.autocompleteList.appendChild(li);
  }
  el.autocompleteList.hidden = false;
}

el.newGameBtn.addEventListener("click", () => startGame().catch((e) => setFeedback("Error", e.message, "incorrect")));
el.hintBtn.addEventListener("click", () => getHint().catch((e) => setFeedback("Error", e.message, "incorrect")));
el.reorderBtn.addEventListener("click", reorderChronologically);
el.revealBtn.addEventListener("click", () => reveal().catch((e) => setFeedback("Error", e.message, "incorrect")));

el.guessForm.addEventListener("submit", (event) => {
  event.preventDefault();
  clearTimeout(autocompleteTimer); // a pending debounced fetch would otherwise re-show
  hideAutocomplete();              // the dropdown right after it's hidden here
  submitGuess(el.guessInput.value).catch((e) => setFeedback("Error", e.message, "incorrect"));
});

el.guessInput.addEventListener("input", () => {
  clearTimeout(autocompleteTimer);
  const value = el.guessInput.value.trim();
  autocompleteTimer = setTimeout(() => {
    fetchAutocomplete(value).catch(() => hideAutocomplete());
  }, AUTOCOMPLETE_DEBOUNCE_MS);
});

document.addEventListener("click", (event) => {
  if (!el.autocompleteList.contains(event.target) && event.target !== el.guessInput) {
    hideAutocomplete();
  }
});
