const SAMPLE_SCREENPLAY = `FADE IN:

1. INT. COMMUNITY RADIO STATION - MORNING
MAYA, 29, adjusts a microphone while TOM, 34, scans the day's rundown.
MAYA
Welcome back to the morning show. We have one hour to change someone's day.
Tom slides a coffee across the desk. A red ON AIR light glows above them.

2. EXT. CITY ROOFTOP - GOLDEN HOUR
Maya steps out onto the rooftop with a portable recorder. She calls her producer,
LENA, on her phone and looks across the skyline.
MAYA
I found the story. I just need the courage to ask the question.

3. INT. COMMUNITY RADIO STATION - NIGHT
The station is quiet. Lena sits at the console as Maya plays back the recording.
The ON AIR light clicks on. They listen together, headphones split between them.

FADE OUT.`;

const screenplay = document.querySelector("#screenplay");
const sampleButton = document.querySelector("#sample-button");
const analyzeButton = document.querySelector("#analyze-button");
const characterCount = document.querySelector("#character-count");
const errorBanner = document.querySelector("#error-banner");
const errorMessage = document.querySelector("#error-message");
const dismissError = document.querySelector("#dismiss-error");
const results = document.querySelector("#results");
const welcomeState = document.querySelector("#welcome-state");
const sceneList = document.querySelector("#scene-list");
const metrics = document.querySelector("#metrics");
const sceneSearch = document.querySelector("#scene-search");
const emptyFilter = document.querySelector("#empty-filter");
const newAnalysis = document.querySelector("#new-analysis");

function updateCount() {
  const count = screenplay.value.length;
  characterCount.textContent = `${count.toLocaleString()} character${count === 1 ? "" : "s"}`;
}

function showError(message) {
  errorMessage.textContent = ` ${message}`;
  errorBanner.hidden = false;
  errorBanner.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function hideError() { errorBanner.hidden = true; }

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;",
  }[char]));
}

function renderMetrics(summary) {
  const cards = [
    ["SCENES", summary.scene_count, "Scenes to shoot"],
    ["CAST", summary.cast_count, "Unique performers"],
    ["PROPS", summary.prop_count, "Items to stage"],
  ];
  metrics.innerHTML = cards.map(([label, value]) => `
    <div class="metric"><span class="metric-label">${label}</span><strong class="metric-value">${value}</strong></div>
  `).join("");
}

function detailsMarkup(scene, index) {
  const cast = scene.cast || [];
  const props = scene.props || [];
  const castContent = cast.length
    ? cast.map(person => `<li>${escapeHtml(person.name)}<small>${escapeHtml(person.call_time)}</small></li>`).join("")
    : "<li>No cast listed</li>";
  const propsContent = props.length
    ? props.map(prop => `<li>${escapeHtml(prop.name)}${prop.notes ? `<small>${escapeHtml(prop.notes)}</small>` : ""}</li>`).join("")
    : "<li>No props listed</li>";
  return `
    <div class="detail-row">
      <button class="detail-toggle" type="button" aria-expanded="false" aria-controls="cast-${index}">Cast & call times (${cast.length})</button>
      <div id="cast-${index}" class="detail-content"><ul class="detail-list">${castContent}</ul></div>
    </div>
    <div class="detail-row">
      <button class="detail-toggle" type="button" aria-expanded="false" aria-controls="props-${index}">Props (${props.length})</button>
      <div id="props-${index}" class="detail-content"><ul class="detail-list">${propsContent}</ul></div>
    </div>`;
}

function renderScenes(scenes) {
  const query = sceneSearch.value.trim().toLowerCase();
  const filtered = scenes.filter(scene => {
    if (!query) return true;
    return JSON.stringify(scene).toLowerCase().includes(query);
  });
  emptyFilter.hidden = filtered.length !== 0;
  sceneList.innerHTML = filtered.map((scene, index) => `
    <article class="scene-card">
      <div class="scene-number">SCENE ${escapeHtml(scene.scene_number)}</div>
      <div class="scene-title">
        <div class="scene-heading">${escapeHtml(scene.heading)}</div>
        <div class="scene-meta"><span>${escapeHtml(scene.location)}</span><span>${escapeHtml(scene.time_of_day)}</span></div>
      </div>
      <div class="scene-details">
        <p class="scene-summary">${escapeHtml(scene.summary || "No scene summary provided.")}</p>
        ${detailsMarkup(scene, index)}
      </div>
      <button class="scene-index" type="button" aria-label="Expand scene details" data-scene-index="${index}">+</button>
    </article>
  `).join("");
  sceneList.querySelectorAll(".detail-toggle").forEach(button => {
    button.addEventListener("click", () => {
      const content = document.getElementById(button.getAttribute("aria-controls"));
      const isOpen = button.getAttribute("aria-expanded") === "true";
      button.setAttribute("aria-expanded", String(!isOpen));
      content.classList.toggle("open", !isOpen);
    });
  });
  sceneList.querySelectorAll(".scene-index").forEach(button => {
    button.addEventListener("click", () => {
      const card = button.closest(".scene-card");
      const toggles = card.querySelectorAll(".detail-toggle");
      const shouldOpen = [...toggles].some(toggle => toggle.getAttribute("aria-expanded") !== "true");
      toggles.forEach(toggle => {
        const content = document.getElementById(toggle.getAttribute("aria-controls"));
        toggle.setAttribute("aria-expanded", String(shouldOpen));
        content.classList.toggle("open", shouldOpen);
      });
      button.setAttribute("aria-label", shouldOpen ? "Collapse scene details" : "Expand scene details");
    });
  });
}

function showResults(data) {
  renderMetrics(data.summary);
  renderScenes(data.scenes);
  results.hidden = false;
  welcomeState.hidden = true;
  results.scrollIntoView({ behavior: "smooth", block: "start" });
}

async function analyze() {
  hideError();
  if (!screenplay.value.trim()) {
    showError("Paste a screenplay or load the sample before analyzing.");
    screenplay.focus();
    return;
  }
  analyzeButton.disabled = true;
  analyzeButton.classList.add("loading");
  try {
    const response = await fetch("/api/parse", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ screenplay: screenplay.value }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || "The analysis service is unavailable.");
    showResults(data);
  } catch (error) {
    showError(error.message || "Please try again.");
  } finally {
    analyzeButton.disabled = false;
    analyzeButton.classList.remove("loading");
  }
}

screenplay.addEventListener("input", updateCount);
sampleButton.addEventListener("click", () => {
  screenplay.value = SAMPLE_SCREENPLAY;
  updateCount();
  hideError();
  screenplay.focus();
});
analyzeButton.addEventListener("click", analyze);
dismissError.addEventListener("click", hideError);
sceneSearch.addEventListener("input", () => {
  if (!results.hidden && window.currentCallSheet) renderScenes(window.currentCallSheet.scenes);
});
newAnalysis.addEventListener("click", () => {
  results.hidden = true;
  welcomeState.hidden = false;
  screenplay.focus();
  window.scrollTo({ top: 0, behavior: "smooth" });
});

const originalShowResults = showResults;
showResults = (data) => {
  window.currentCallSheet = data;
  originalShowResults(data);
};
updateCount();