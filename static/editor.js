const field = (name) => document.getElementById(name);
const project = JSON.parse(field("project").textContent);
const preview = field("preview");
const form = field("edit-form");
const statusText = field("status");
const feedback = field("feedback");
const notesUrl = `${location.pathname}/notes`;
const inputs = [];
const omissions = [];
let chosenStock = null;
const tablist = form.querySelector("[role=tablist]");
const tabs = Array.from(tablist.querySelectorAll("[role=tab]"));
const panels = tabs.map((tab) => field(tab.getAttribute("aria-controls")));

function selectTab(index, focus = false) {
  tabs.forEach((tab, current) => {
    tab.setAttribute("aria-selected", String(current === index));
    tab.tabIndex = current === index ? 0 : -1;
    panels[current].hidden = current !== index;
  });
  if (focus) tabs[index].focus();
}

tablist.hidden = false;
selectTab(0);
tabs.forEach((tab, index) => {
  tab.addEventListener("click", () => selectTab(index));
  tab.addEventListener("keydown", (event) => {
    const destinations = {ArrowRight: (index + 1) % tabs.length,
      ArrowLeft: (index + tabs.length - 1) % tabs.length, Home: 0, End: tabs.length - 1};
    if (Object.hasOwn(destinations, event.key)) {
      event.preventDefault();
      selectTab(destinations[event.key], true);
    }
  });
});
form.addEventListener("invalid", (event) => {
  const panel = event.target.closest("[role=tabpanel]");
  if (panel?.hidden) selectTab(panels.indexOf(panel));
}, true);

field("framing").value = project.framing;
field("color").value = "#" + project.color;
field("word-highlight").checked = project.wordHighlight;
const seconds = (number) => Number(number.toFixed(3));
for (const name of ["start", "end"]) field(name).max = seconds(project.duration);
field("end").value = seconds(project.duration);

const openingFeedback = field("opening-feedback");
let openingPreview = null;

function finishOpeningPreview() {
  if (!openingPreview) return;
  preview.muted = openingPreview.wasMuted;
  openingPreview = null;
}

preview.addEventListener("pause", finishOpeningPreview);
preview.addEventListener("ended", finishOpeningPreview);
preview.addEventListener("timeupdate", () => {
  if (openingPreview && !preview.seeking && preview.currentTime >= openingPreview.end) {
    preview.pause();
    finishOpeningPreview();
  }
});

field("preview-opening").addEventListener("click", async () => {
  const start = field("start").valueAsNumber;
  const end = field("end").valueAsNumber;
  if (!Number.isFinite(start) || !Number.isFinite(end) || start < 0 || end <= start || end > project.duration + .001) {
    openingFeedback.textContent = "Choose a valid start and end to preview the opening.";
    return;
  }
  finishOpeningPreview();
  const stop = Math.min(start + 3, end);
  openingPreview = {end: stop, wasMuted: preview.muted};
  preview.muted = true;
  preview.currentTime = start;
  try {
    await preview.play();
    openingFeedback.textContent = `Previewing ${seconds(stop - start)} seconds on mute. Check whether the action is clear.`;
  } catch {
    finishOpeningPreview();
    openingFeedback.textContent = "The opening preview could not play.";
  }
});

field("tighten-opening")?.addEventListener("click", () => {
  const current = field("start").valueAsNumber;
  const end = field("end").valueAsNumber;
  if (end < project.moment + 1 || project.moment - current <= 3 || !Number.isFinite(current) || !Number.isFinite(end)) {
    openingFeedback.textContent = "Keep at least three seconds before the moment and one second afterward for this trim.";
    return;
  }
  const target = project.moment - 3;
  const cue = project.cues.find(({start, end}) => start < target && target < end);
  const start = seconds(Math.max(current, cue?.start ?? target));
  if (start <= current) {
    openingFeedback.textContent = "The current opening already starts at the relevant caption boundary.";
    return;
  }
  preview.pause();
  field("start").value = start;
  preview.currentTime = start;
  openingFeedback.textContent = `Start set to ${start}s. Preview it on mute or adjust the start before exporting.`;
});

function cueButton(label, callback) {
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = label;
  button.addEventListener("click", callback);
  return button;
}

project.cues.forEach((cue, index) => {
  const row = document.createElement("div");
  row.className = "cue";
  const caption = document.createElement("input");
  caption.value = cue.text;
  caption.maxLength = 200;
  caption.setAttribute("aria-label", `Caption ${index + 1}`);
  inputs.push(caption);
  const controls = document.createElement("div");
  controls.className = "row";
  const omit = document.createElement("input");
  omit.type = "checkbox";
  omit.addEventListener("change", () => row.classList.toggle("is-excluded", omit.checked));
  omissions.push(omit);
  const label = document.createElement("label");
  label.append(omit, "Exclude passage");
  controls.append(cueButton("Start here", () => { field("start").value = seconds(cue.start); }),
    cueButton("End here", () => { field("end").value = seconds(cue.end); }), label);
  row.append(cueButton(cue.start.toFixed(1), () => { preview.currentTime = cue.start; }), caption, controls);
  field("cues").append(row);
});
if (!inputs.length) field("cues").textContent = "No speech captions were detected in this clip.";

const captionPreview = field("caption-style-preview");
const captionSample = field("caption-style-sample");
function updateCaptionPreview() {
  captionPreview.dataset.style = field("style").value;
  captionPreview.dataset.font = field("caption-font").value;
  captionPreview.style.setProperty("--caption-accent", field("color").value);
  captionSample.textContent = (inputs[0]?.value.trim() || "Caption preview").slice(0, 80);
}

for (const name of ["style", "caption-font", "color"]) {
  field(name).addEventListener("input", updateCaptionPreview);
}
inputs[0]?.addEventListener("input", updateCaptionPreview);
updateCaptionPreview();

const presetFields = ["style", "caption-font", "brand", "color"];
field("save-preset").addEventListener("click", () => {
  localStorage.setItem("shortlist-brand", JSON.stringify(Object.fromEntries(presetFields.map((name) => [name, field(name).value]))));
  feedback.textContent = "Brand preset saved in this browser.";
});
field("load-preset").addEventListener("click", () => {
  const preset = JSON.parse(localStorage.getItem("shortlist-brand") || "null");
  if (preset) {
    presetFields.forEach((name) => {
      if (typeof preset[name] === "string") field(name).value = preset[name];
    });
    updateCaptionPreview();
  }
  feedback.textContent = preset ? "Brand preset loaded." : "No brand preset saved yet.";
});

const facecamFields = ["facecam-x", "facecam-y", "facecam-width", "facecam-height"];
const cropSource = field("facecam-source");
const cropFrame = new Image();
cropFrame.alt = "Original video frame";
cropSource.prepend(cropFrame);
const cropBox = field("facecam-box");
const cropStatus = field("facecam-status");
const cropPresets = field("crop-presets");
const cropValues = () => facecamFields.map((name) => field(name).valueAsNumber);
const validCrop = ([x, y, width, height]) =>
  x >= 0 && y >= 0 && width >= 5 && height >= 5 && x + width <= 100.000001 && y + height <= 100.000001;
let frameOffset = null;

function drawFacecamBox() {
  const values = cropValues();
  cropBox.hidden = !validCrop(values);
  if (!cropBox.hidden) {
    for (const [index, property] of ["left", "top", "width", "height"].entries()) {
      cropBox.style[property] = `${values[index]}%`;
    }
  }
}

function setCrop(values) {
  facecamFields.forEach((name, index) => { field(name).value = Math.round(values[index] * 10) / 10; });
  drawFacecamBox();
}

function loadCropFrame() {
  const offset = field("start").valueAsNumber;
  if (!Number.isFinite(offset) || offset < 0 || offset >= project.duration || offset === frameOffset) return;
  frameOffset = offset;
  cropSource.hidden = true;
  cropStatus.textContent = "Loading original frame…";
  cropFrame.src = `${location.pathname}/crop-frame?at=${offset}`;
}

cropFrame.addEventListener("load", () => {
  cropSource.hidden = false;
  cropStatus.textContent = "";
  drawFacecamBox();
});
cropFrame.addEventListener("error", () => {
  frameOffset = null;
  cropStatus.textContent = "Could not load the original frame. Exact crop values are still available.";
});

let cropDrag = null;
cropBox.addEventListener("pointerdown", (event) => {
  if (!event.isPrimary || event.button !== 0) return;
  event.preventDefault();
  cropBox.setPointerCapture(event.pointerId);
  cropDrag = {pointer: event.pointerId, x: event.clientX, y: event.clientY, values: cropValues(),
    resize: event.target.hasAttribute("data-resize"), bounds: cropSource.getBoundingClientRect()};
});
cropBox.addEventListener("pointermove", (event) => {
  if (cropDrag?.pointer !== event.pointerId) return;
  const [x, y, width, height] = cropDrag.values;
  const deltaX = (event.clientX - cropDrag.x) * 100 / cropDrag.bounds.width;
  const deltaY = (event.clientY - cropDrag.y) * 100 / cropDrag.bounds.height;
  const within = (value, min, max) => Math.min(max, Math.max(min, value));
  setCrop(cropDrag.resize
    ? [x, y, within(width + deltaX, 5, 100 - x), within(height + deltaY, 5, 100 - y)]
    : [within(x + deltaX, 0, 100 - width), within(y + deltaY, 0, 100 - height), width, height]);
});
cropBox.addEventListener("lostpointercapture", () => {
  cropDrag = null;
  cropStatus.textContent = "Crop updated. Render the preview to check it.";
});
for (const name of facecamFields) field(name).addEventListener("input", drawFacecamBox);

let namedCrops = new Map();
try {
  namedCrops = new Map(JSON.parse(localStorage.getItem("shortlist-facecam-crops") || "[]"));
} catch {
  // The crop editor can still be used when local storage is unavailable.
}
function refreshCropPresets() {
  cropPresets.replaceChildren(new Option("Choose a saved crop", ""));
  for (const name of namedCrops.keys()) cropPresets.add(new Option(name, name));
}
refreshCropPresets();
field("save-crop-preset").addEventListener("click", () => {
  const name = field("crop-preset-name").value.trim();
  const values = cropValues();
  if (!name || !validCrop(values)) {
    cropStatus.textContent = "Enter a preset name and keep the crop inside the frame.";
    return;
  }
  const next = new Map(namedCrops).set(name, values);
  try {
    localStorage.setItem("shortlist-facecam-crops", JSON.stringify([...next]));
    namedCrops = next;
    refreshCropPresets();
    cropPresets.value = name;
    cropStatus.textContent = `Saved “${name}” in this browser.`;
  } catch {
    cropStatus.textContent = "This browser could not save the crop.";
  }
});
cropPresets.addEventListener("change", () => {
  const values = namedCrops.get(cropPresets.value);
  if (!Array.isArray(values) || !validCrop(values)) return;
  setCrop(values);
  field("crop-preset-name").value = cropPresets.value;
  cropStatus.textContent = "Crop loaded. Render the preview to check it.";
});

function usesFacecam() {
  return ["gameplay", "reaction"].includes(field("framing").value);
}

function updateFramingControls() {
  const split = usesFacecam();
  field("facecam-crop").hidden = !split;
  for (const name of facecamFields) field(name).disabled = !split;
  if (split) loadCropFrame();
}
field("framing").addEventListener("change", updateFramingControls);
field("start").addEventListener("change", () => {
  if (usesFacecam()) loadCropFrame();
});
setCrop(project.facecam);
updateFramingControls();

function appearanceSettings() {
  return {
    framing: field("framing").value,
    style: field("style").value,
    caption_font: field("caption-font").value,
    word_highlight: field("word-highlight").checked,
    brand: field("brand").value,
    color: field("color").value,
    ...Object.fromEntries(facecamFields.map((name) => [name.replace("-", "_"), field(name).valueAsNumber]))
  };
}

const layoutStage = field("layout-preview-stage");
const layoutVideo = field("layout-preview-video");
const layoutStatus = field("layout-preview-status");
field("preview-guides").addEventListener("change", (event) => {
  layoutStage.classList.toggle("show-guides", event.target.checked);
});
field("render-layout-preview").addEventListener("click", async (event) => {
  if (!field("start").reportValidity() || !field("end").reportValidity()
      || facecamFields.some((name) => !field(name).reportValidity())) return;
  if (usesFacecam()) {
    if (!validCrop(cropValues())) {
      layoutStatus.textContent = "Keep the facecam crop inside the original frame.";
      return;
    }
    loadCropFrame();
  }
  const button = event.currentTarget;
  button.disabled = true;
  layoutStatus.textContent = "Rendering vertical preview…";
  try {
    const response = await fetch(`${location.pathname}/layout-preview`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        ...appearanceSettings(),
        headline: field("headline").value,
        start: field("start").valueAsNumber,
        end: field("end").valueAsNumber,
        captions: inputs.map((input) => input.value)
      })
    });
    if (!response.ok) {
      const failure = await response.json().catch(() => ({}));
      throw new Error(failure.error || "Could not render the vertical preview.");
    }
    if (layoutVideo.src.startsWith("blob:")) URL.revokeObjectURL(layoutVideo.src);
    layoutVideo.src = URL.createObjectURL(await response.blob());
    layoutStage.hidden = false;
    layoutStatus.textContent = "Preview ready. Play it to check your layout.";
  } catch (error) {
    layoutStatus.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});

field("stock-caption").addEventListener("click", () => {
  const cue = project.cues.find(({start, end}) => start <= preview.currentTime && preview.currentTime <= end);
  if (cue) field("stock-query").value = cue.text.slice(0, 100);
  else field("stock-status").textContent = "Play a caption to use it as a search.";
});

field("stock-search").addEventListener("click", async () => {
  const query = field("stock-query").value.trim();
  const results = field("stock-results");
  results.replaceChildren();
  field("stock-status").textContent = "Searching Wikimedia Commons…";
  try {
    const response = await fetch(`/stock?q=${encodeURIComponent(query)}`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error);
    field("stock-status").textContent = data.images.length ? "Choose an image to use as B-roll." : "No supported stock images found.";
    for (const image of data.images) {
      const card = document.createElement("div");
      const thumb = document.createElement("img");
      thumb.src = image.thumbnail;
      thumb.alt = image.title;
      thumb.loading = "lazy";
      thumb.style.width = "100%";
      const source = document.createElement("a");
      source.href = image.source;
      source.target = "_blank";
      source.rel = "noopener";
      source.textContent = image.license;
      const select = cueButton("Use image", () => {
        chosenStock = image.id;
        field("broll").value = "";
        field("stock-status").textContent = `Selected ${image.title} · ${image.license}`;
      });
      card.append(thumb, select, " ", source);
      results.append(card);
    }
    if (data.images.length) results.append(cueButton("Clear stock selection", () => {
      chosenStock = null;
      field("stock-status").textContent = "Stock selection cleared.";
    }));
  } catch (error) {
    field("stock-status").textContent = error.message;
  }
});

field("broll").addEventListener("change", () => {
  if (field("broll").files.length) {
    chosenStock = null;
    field("stock-status").textContent = "Using your uploaded B-roll.";
  }
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = form.querySelector("button[type=submit]");
  button.disabled = true;
  field("exports").replaceChildren();
  statusText.textContent = "Submitting edits…";
  feedback.textContent = "";
  const asset = field("broll").files[0];
  const hasBroll = asset || chosenStock;
  const edit = {
    headline: field("headline").value,
    start: Number(field("start").value),
    end: Number(field("end").value),
    captions: inputs.map((input) => input.value),
    omit: omissions.flatMap((box, index) => box.checked ? [index] : []),
    formats: Array.from(form.querySelectorAll("[name=shape]:checked"), (input) => input.value),
    ...appearanceSettings(),
    stock_id: chosenStock,
    broll_keyword: hasBroll ? field("broll-keyword").value : "",
    broll_start: hasBroll ? Number(field("broll-start").value) : 0,
    broll_duration: hasBroll ? Number(field("broll-duration").value) : 3,
    volume: Number(field("volume").value),
    clean_audio: field("clean-audio").checked,
    normalize: field("normalize").checked
  };
  const payload = new FormData();
  payload.set("edit", JSON.stringify(edit));
  if (asset) payload.set("broll", asset);
  try {
    const response = await fetch(location.pathname, {method: "POST", body: payload});
    const job = await response.json();
    if (!response.ok) throw new Error(job.error || "Could not submit changes.");
    while (true) {
      const status = await fetch(job.poll, {cache: "no-store"});
      if (!status.ok) throw new Error("Could not check export progress.");
      const state = await status.json();
      statusText.textContent = state.message;
      state.files.slice(field("exports").children.length).forEach(({label, url}) => {
        const item = document.createElement("li");
        const watch = document.createElement("a");
        watch.href = url;
        watch.target = "_blank";
        watch.rel = "noopener";
        watch.textContent = `Preview ${label}`;
        const download = document.createElement("a");
        download.href = url + "?download";
        download.textContent = "Download MP4";
        item.append(watch, " · ", download);
        field("exports").append(item);
      });
      if (state.status === "error") throw new Error(state.message);
      if (state.status === "complete") {
        if (state.credits) {
          const item = document.createElement("li");
          const credit = document.createElement("a");
          credit.href = state.credits + "?download";
          credit.textContent = "Download stock attribution";
          item.append(credit);
          field("exports").append(item);
        }
        break;
      }
      await new Promise((resolve) => setTimeout(resolve, 900));
    }
  } catch (error) {
    feedback.textContent = error.message;
    statusText.textContent = "";
  } finally {
    button.disabled = false;
  }
});

function showNotes(notes) {
  const list = field("notes");
  list.replaceChildren();
  notes.forEach(({time, text}) => {
    const item = document.createElement("li");
    item.append(cueButton(`${time}s`, () => { preview.currentTime = time; }), " ", text);
    list.append(item);
  });
}

fetch(notesUrl).then((response) => response.json()).then((data) => showNotes(data.notes)).catch(() => {});
field("note-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const result = await fetch(notesUrl, {method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({time: preview.currentTime, text: field("note").value})});
    const data = await result.json();
    if (!result.ok) throw new Error(data.error);
    showNotes(data.notes);
    field("note").value = "";
  } catch (error) {
    statusText.textContent = error.message;
  }
});

field("notes-import").addEventListener("change", async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  try {
    if (file.size > 600000) throw new Error("This notes file is too large.");
    const data = JSON.parse(await file.text());
    if (!Array.isArray(data.notes)) throw new Error("Choose a Shortlist notes JSON file.");
    const response = await fetch(notesUrl, {method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify(data)});
    const result = await response.json();
    if (!response.ok) throw new Error(result.error);
    showNotes(result.notes);
    statusText.textContent = "Review notes imported.";
  } catch (error) {
    statusText.textContent = error.message;
  } finally {
    event.target.value = "";
  }
});

async function changeShareLink(method) {
  try {
    const response = await fetch(location.pathname + "/share", {
      method, headers: {"Content-Type": "application/json"}, body: "{}"
    });
    if (!response.ok) throw new Error("Could not update the review link.");
    const result = await response.json();
    const output = field("share-url");
    output.hidden = !result.url;
    output.value = result.url ? new URL(result.url, location.origin).href : "";
    if (result.url) { output.focus(); output.select(); }
    statusText.textContent = result.url ? "Copy this link for your reviewer." : "Review link revoked.";
  } catch (error) {
    statusText.textContent = error.message;
  }
}

field("share-review").addEventListener("click", () => changeShareLink("POST"));
field("revoke-review").addEventListener("click", () => changeShareLink("DELETE"));
