const tools = ["Shortlist", "OpusClip", "Eklipse"];
const setup = document.querySelector("#setup");
const setupForm = document.querySelector("#setup-form");
const review = document.querySelector("#review");
const ratingForm = document.querySelector("#rating-form");
const player = document.querySelector("#candidate");
const summary = document.querySelector("#summary");
const metrics = document.querySelector("#metrics");
const clips = [];
let sourceName;
let index = 0;
let mediaUrl;
let timings = {};

tools.forEach((tool, i) => {
  const fieldset = document.createElement("fieldset");
  const label = document.createElement("legend");
  label.textContent = tool;
  fieldset.append(label);
  fieldset.insertAdjacentHTML("beforeend", `
    <label>MP4 exports <input name="clips-${i}" type="file" accept="video/mp4,.mp4" multiple></label>
    <label>Time to the first clip, in seconds <input name="seconds-${i}" type="number" min="0"></label>
  `);
  document.querySelector("#tools").append(fieldset);
});

function showClip() {
  if (mediaUrl) URL.revokeObjectURL(mediaUrl);
  if (index === clips.length) {
    player.removeAttribute("src");
    player.load();
    review.hidden = true;
    showSummary();
    return;
  }
  document.querySelector("#clip-label").textContent = `Clip ${index + 1} of ${clips.length}`;
  mediaUrl = URL.createObjectURL(clips[index].file);
  player.src = mediaUrl;
}

setupForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const form = new FormData(setupForm);
  const groups = tools.map((tool, i) => ({
    tool,
    files: form.getAll(`clips-${i}`).filter((file) => file.size),
    latency: form.get(`seconds-${i}`),
  }));
  if (groups.filter((group) => group.files.length).length < 2 || groups.some((group) => group.files.length > 5)) {
    window.alert("Choose one to five clips from at least two tools.");
    return;
  }
  sourceName = form.get("sourceName").trim();
  timings = Object.fromEntries(groups.map(({tool, latency}) => [tool, latency ? Number(latency) : null]));
  groups.forEach(({tool, files}) => files.forEach((file) => clips.push({tool, file})));
  for (let i = clips.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [clips[i], clips[j]] = [clips[j], clips[i]];
  }
  setup.hidden = true;
  review.hidden = false;
  showClip();
});

ratingForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const data = new FormData(ratingForm);
  const minutes = data.get("editMinutes");
  clips[index].rating = {
    post: data.get("post") === "Yes",
    accuracy: data.get("accuracy"),
    editMinutes: minutes ? Number(minutes) : null,
  };
  ratingForm.reset();
  index++;
  showClip();
});

function showSummary() {
  summary.hidden = false;
  for (const tool of tools) {
    const ratings = clips.filter((clip) => clip.tool === tool).map((clip) => clip.rating);
    if (!ratings.length) continue;
    const ratedMinutes = ratings.map((rating) => rating.editMinutes).filter((value) => value !== null);
    const average = ratedMinutes.length ? ratedMinutes.reduce((a, b) => a + b, 0) / ratedMinutes.length : null;
    const row = document.createElement("tr");
    const values = [tool, `${ratings.filter((r) => r.post).length}/${ratings.length}`,
      `${ratings.filter((r) => r.accuracy === "Accurate").length}/${ratings.length}`,
      average === null ? "—" : average.toFixed(1), timings[tool] === null ? "—" : `${timings[tool]} s`];
    values.forEach((value) => {
      const cell = document.createElement("td");
      cell.textContent = value;
      row.append(cell);
    });
    metrics.append(row);
  }
}

document.querySelector("#export").addEventListener("click", () => {
  const data = {
    source: sourceName,
    timeToFirstClipSeconds: timings,
    clips: clips.map(({tool, file, rating}) => ({tool, file: file.name, ...rating})),
  };
  const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], {type: "application/json"}));
  const link = document.createElement("a");
  link.href = url;
  link.download = "shortlist-benchmark.json";
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
