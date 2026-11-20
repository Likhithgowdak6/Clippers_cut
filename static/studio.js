const form = document.querySelector("#source-form");
const statusText = document.querySelector("#status");
const jobProgress = document.querySelector("#job-progress");
const progressBar = document.querySelector("#progress-bar");
const elapsed = document.querySelector("#elapsed");
const visionNotice = document.querySelector("#vision-notice");
const results = document.querySelector("#results");
const firstClipTime = document.querySelector("#first-clip-time");
const batchDownload = document.querySelector("#batch-download");
const batchForm = document.querySelector("#batch-form");
const batchStatus = document.querySelector("#batch-status");
const evaluationExport = document.querySelector("#evaluation-export");
const viewResults = document.querySelector("#view-results");
const clips = document.querySelector("#clips");
const button = form.querySelector("button[type=submit]");
const mode = document.querySelector("#mode");
const scanWindow = document.querySelector("#scan-window");
const scanStart = document.querySelector("#scan-start");
const talkOptions = document.querySelector("#talk-options");
const scanDepth = document.querySelector("#scan-depth");
const scanDepthField = document.querySelector("#scan-depth-field");
const visualAI = document.querySelector("#visual-ai");
const visualAIOff = document.querySelector("#visual-ai-off");
const visionProvider = document.querySelector("#vision-provider");
const recordingFolder = document.querySelector("#recording-folder");
const exampleButton = document.querySelector("#play-example");
const exampleVideo = document.querySelector("#example-video");

exampleButton.addEventListener("click", () => {
  exampleVideo.src = "/example-output";
  exampleButton.hidden = true;
  exampleVideo.hidden = false;
  exampleVideo.focus();
  exampleVideo.play().catch(() => {});
});

recordingFolder.addEventListener("change", () => {
  const video = Array.from(recordingFolder.files)
    .filter((file) => /\.(mp4|mov|mkv|webm|avi|m4v)$/i.test(file.name))
    .sort((left, right) => right.lastModified - left.lastModified)[0];
  const message = document.querySelector("#recording-status");
  if (!video) {
    message.textContent = "No supported video found in this folder.";
    return;
  }
  const selected = new DataTransfer();
  selected.items.add(video);
  document.querySelector("#source").files = selected.files;
  message.textContent = `Selected ${video.name}.`;
});

function updateScanWindow() {
  scanWindow.hidden = mode.value !== "stream";
  talkOptions.hidden = !scanWindow.hidden;
  scanStart.disabled = scanWindow.hidden;
  scanDepth.disabled = scanWindow.hidden || Boolean(scanStart.value.trim());
  scanDepthField.hidden = scanDepth.disabled;
  visualAI.disabled = scanWindow.hidden;
  visualAIOff.disabled = scanWindow.hidden || visualAI.checked;
  if (visionProvider) {
    visionProvider.disabled = scanWindow.hidden || !visualAI.checked;
  }
}

mode.addEventListener("change", updateScanWindow);
scanStart.addEventListener("input", updateScanWindow);
visualAI.addEventListener("change", updateScanWindow);
updateScanWindow();
form.addEventListener("invalid", (event) => {
  const section = event.target.closest("details");
  if (section) section.open = true;
}, true);

function timestamp(seconds) {
  const whole = Math.floor(seconds);
  const minutes = Math.floor(whole / 60);
  const tail = String(whole % 60).padStart(2, "0");
  if (minutes < 60) return `${minutes}:${tail}`;
  return `${Math.floor(minutes / 60)}:${String(minutes % 60).padStart(2, "0")}:${tail}`;
}

function showProgress(state) {
  jobProgress.dataset.state = state.status;
  if (statusText.textContent !== state.message) statusText.textContent = state.message;
  const notice = [
    state.cloud_reviewed ? `Gemini reviewed ${state.cloud_reviewed} ${state.cloud_reviewed === 1 ? "clip" : "clips"}.` : "",
    state.vision_notice,
  ].filter(Boolean).join(" ");
  if (visionNotice.textContent !== notice) visionNotice.textContent = notice;
  visionNotice.hidden = !notice;
  progressBar.hidden = state.status === "error";
  if (state.status === "complete") {
    progressBar.max = 1;
    progressBar.value = 1;
  } else if (state.status === "scanning") {
    progressBar.max = state.windows;
    progressBar.value = state.scanned;
  } else if (state.status === "reviewing") {
    progressBar.max = state.candidates;
    progressBar.value = state.reviewed;
  } else if (state.status === "rendering") {
    progressBar.max = state.total;
    progressBar.value = state.clips.length;
  } else {
    progressBar.removeAttribute("value");
  }
}

function addClip(clip, videoId) {
  const card = document.createElement("article");
  card.className = "surface clip-card";
  const video = document.createElement("video");
  video.src = clip.preview;
  video.controls = true;
  video.playsInline = true;
  video.preload = "metadata";
  const title = document.createElement("h3");
  title.textContent = clip.title;
  const range = document.createElement("small");
  range.textContent = `${timestamp(clip.start)} – ${timestamp(clip.end)} in source`;
  if (videoId) {
    const source = document.createElement("a");
    source.href = `https://www.youtube.com/watch?v=${videoId}&t=${Math.floor(clip.start)}s`;
    source.style.color = "inherit";
    source.textContent = range.textContent;
    range.replaceChildren(source);
    if (Number.isFinite(clip.event_time)) {
      const moment = document.createElement("a");
      moment.href = `https://www.youtube.com/watch?v=${videoId}&t=${Math.floor(clip.event_time)}s`;
      moment.textContent = `Jump to ${timestamp(clip.event_time)}`;
      range.append(" · ", moment);
    }
  }
  const evidence = document.createElement("dl");
  evidence.className = "clip-evidence";
  function addEvidence(label, text) {
    const term = document.createElement("dt");
    term.textContent = label;
    const value = document.createElement("dd");
    value.textContent = text;
    evidence.append(term, value);
  }
  if (clip.audience) {
    const {channel, count, time} = clip.audience;
    if (channel === "chat") {
      addEvidence("Replay chat", `${count} distinct viewers around ${timestamp(time)}`);
    } else {
      addEvidence("Video comments", `${count} ${count === 1 ? "viewer referenced" : "viewers referenced"} ${timestamp(time)}`);
    }
  }
  if (clip.hud?.result === "did_not_finish") {
    addEvidence("Race HUD", "Race result says the player did not finish");
  } else if (clip.hud && clip.hud.before !== clip.hud.after) {
    addEvidence("Race HUD", `Position ${clip.hud.before} to ${clip.hud.after} out of ${clip.hud.entrants}`);
  }
  const reason = document.createElement("p");
  reason.textContent = clip.reason;
  const download = document.createElement("a");
  download.className = "download";
  download.href = clip.preview + "?download";
  download.textContent = "Download MP4";
  const actions = document.createElement("div");
  actions.className = "clip-actions";
  if (clip.editor) {
    const edit = document.createElement("a");
    edit.href = clip.editor;
    edit.textContent = "Edit clip";
    edit.className = "secondary-button";
    actions.append(edit);
  }
  actions.append(download);
  card.append(video, title, range);
  if (evidence.children.length) {
    card.append(evidence);
    const details = document.createElement("details");
    const summary = document.createElement("summary");
    summary.textContent = "Detection details";
    details.append(summary, reason);
    card.append(details);
  } else {
    card.append(reason);
  }
  card.append(actions);
  clips.append(card);
  results.hidden = false;
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  button.disabled = true;
  clips.replaceChildren();
  results.hidden = true;
  firstClipTime.hidden = true;
  batchDownload.hidden = true;
  batchForm.hidden = true;
  batchStatus.textContent = "";
  evaluationExport.hidden = true;
  viewResults.hidden = true;
  jobProgress.hidden = false;
  elapsed.hidden = false;
  const started = performance.now();
  const tick = () => {
    elapsed.textContent = `Elapsed ${timestamp((performance.now() - started) / 1000)}`;
  };
  tick();
  const timer = setInterval(tick, 1000);
  showProgress({status: "uploading", message: "Submitting the source…"});
  try {
    const response = await fetch("/jobs", { method: "POST", body: new FormData(form) });
    const job = await response.json();
    if (!response.ok) throw new Error(job.error);
    batchDownload.href = `/jobs/${job.id}/download`;
    batchForm.dataset.jobId = job.id;
    while (true) {
      const progress = await fetch(`/jobs/${job.id}`, { cache: "no-store" });
      if (!progress.ok) throw new Error("Could not retrieve the job.");
      const state = await progress.json();
      showProgress(state);
      if (state.first_clip_seconds !== undefined) {
        firstClipTime.textContent = `First clip ready in ${state.first_clip_seconds} s`;
        firstClipTime.hidden = false;
      }
      state.clips.slice(clips.children.length).forEach((clip) => addClip(clip, state.video_id));
      batchDownload.hidden = !state.clips.length;
      viewResults.hidden = !state.clips.length;
      if (state.status === "complete" || state.status === "error") {
        evaluationExport.href = `/jobs/${job.id}/evaluation`;
        evaluationExport.hidden = false;
        batchForm.hidden = !state.clips.some((clip) => clip.editor);
      }
      if (state.status === "complete" || state.status === "error") break;
      await new Promise((resolve) => setTimeout(resolve, 1200));
    }
  } catch (error) {
    showProgress({status: "error", message: error.message || "Could not generate clips."});
  } finally {
    clearInterval(timer);
    tick();
    button.disabled = false;
  }
});

batchForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const jobId = batchForm.dataset.jobId;
  const submit = batchForm.querySelector("button");
  submit.disabled = true;
  batchStatus.textContent = "Queuing batch…";
  try {
    const formats = new FormData(batchForm).getAll("format");
    const response = await fetch(`/jobs/${jobId}/batch`, {
      method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({formats})
    });
    const batch = await response.json();
    if (!response.ok) throw new Error(batch.error);
    while (batchForm.dataset.jobId === jobId) {
      const exports = await Promise.all(batch.polls.map(async (url) => {
        const state = await fetch(url, {cache: "no-store"});
        if (!state.ok) throw new Error("Could not check the batch.");
        return state.json();
      }));
      const ready = exports.filter((item) => item.status === "complete").length;
      const failed = exports.filter((item) => item.status === "error").length;
      batchStatus.textContent = `${ready}/${exports.length} clips exported${failed ? ` · ${failed} failed` : ""}.`;
      if (ready + failed === exports.length) {
        if (ready) batchStatus.textContent += " Open Download all exports to get the files.";
        break;
      }
      await new Promise((resolve) => setTimeout(resolve, 1000));
    }
  } catch (error) {
    batchStatus.textContent = error.message;
  } finally {
    submit.disabled = false;
  }
});
