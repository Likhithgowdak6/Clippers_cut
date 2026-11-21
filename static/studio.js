const form = document.querySelector("#source-form");
const statusText = document.querySelector("#status");
const jobProgress = document.querySelector("#job-progress");
const progressBar = document.querySelector("#progress-bar");
const elapsed = document.querySelector("#elapsed");
const visionNotice = document.querySelector("#vision-notice");
const youtubeUploadStatus = document.querySelector("#youtube-upload-status");
const youtubeUploadLink = document.querySelector("#youtube-upload-link");
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
const replayMap = document.querySelector("#replay-map");
const replayTracks = document.querySelector("#replay-tracks");
const replayPeaks = document.querySelector("#replay-peaks");
const replayTime = document.querySelector("#replay-time");
const replaySelection = document.querySelector("#replay-selection");
const watchReplay = document.querySelector("#watch-replay-point");
const rescanReplay = document.querySelector("#rescan-replay-point");
const earlyPreview = document.querySelector("#early-replay-preview");
const earlyPreviewVideo = document.querySelector("#early-preview-video");
let replayState = null;
let selectedReplayTime = null;

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
  document.querySelector("#gameplay-layout-field").hidden = scanWindow.hidden;
  document.querySelector("#gameplay-layout").disabled = scanWindow.hidden;
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

function parseReplayTime(value) {
  const parts = value.trim().split(":");
  if (parts.length > 3 || parts.some((part) => !/^\d+$/.test(part))) return NaN;
  const numbers = parts.map(Number);
  if (numbers.slice(1).some((part) => part >= 60)) return NaN;
  return numbers.reduce((seconds, part) => seconds * 60 + part, 0);
}

function selectReplayTime(seconds, rewriteInput = true) {
  selectedReplayTime = null;
  const valid = Number.isFinite(seconds) && seconds >= 0 && seconds < replayState.source_seconds;
  watchReplay.hidden = !valid;
  rescanReplay.disabled = !valid;
  if (!valid) {
    replaySelection.textContent = "Choose a time within the replay.";
    return;
  }
  selectedReplayTime = seconds;
  if (rewriteInput) replayTime.value = timestamp(seconds);
  const contains = (start, end) => start <= seconds && seconds < end;
  const exported = replayState.clips.find(({start, end}) => contains(start, end));
  const evidence = exported ? `Inside an exported clip · ${exported.title}`
    : replayState.candidates_found?.some(({start, end}) => contains(start, end)) ? "Inside a candidate that was not exported"
    : Array.isArray(replayState.analyzed_coverage) && replayState.coverage?.some(([start, end]) => contains(start, end))
      && !replayState.analyzed_coverage.some(([start, end]) => contains(start, end)) ? "Scanned for signals · not shortlisted for detailed analysis"
    : replayState.coverage?.some(([start, end]) => contains(start, end)) ? "Scanned · no candidate at this time"
    : "Outside the scanned footage";
  replaySelection.textContent = `${timestamp(seconds)} · ${evidence}`;
  watchReplay.href = `https://www.youtube.com/watch?v=${replayState.video_id}&t=${Math.floor(seconds)}s`;
  replayTracks.style.setProperty("--replay-cursor", `${100 * seconds / replayState.source_seconds}%`);
}

function renderReplayMap(state) {
  if (!state.video_id || !Number.isFinite(state.source_seconds) || state.source_seconds <= 0) return;
  replayState = state;
  const duration = state.source_seconds;
  const coverage = (state.coverage || []).map(([start, end]) => [Math.max(0, start), Math.min(end, duration)])
    .filter(([start, end]) => end > start).sort(([a], [b]) => a - b);
  let scanned = 0;
  let through = 0;
  for (const [start, end] of coverage) {
    scanned += Math.max(0, end - Math.max(start, through));
    through = Math.max(through, end);
  }
  document.querySelector("#replay-coverage").textContent =
    `Scanned ${timestamp(scanned)} of ${timestamp(duration)} · ${(100 * scanned / duration).toFixed(1)}%`;
  const reactions = (state.scan_reactions || []).filter(([time]) => time >= 0 && time < duration);
  replayPeaks.replaceChildren(new Option(reactions.length ? "Choose a moment" : "No audience peaks recorded", ""));
  replayPeaks.disabled = !reactions.length;
  for (const [index, [time, count, channel]] of reactions.entries()) {
    const viewers = count === 1 ? "viewer" : "viewers";
    replayPeaks.add(new Option(`${timestamp(time)} · ${count} ${viewers} · ${channel === "chat" ? "chat" : "comments"}`, index));
  }
  replayPeaks.onchange = () => {
    if (replayPeaks.value !== "") selectReplayTime(reactions[Number(replayPeaks.value)][0]);
  };
  const rangeMarks = (clips) => (clips || []).map(({start, end}) => [start, end]);
  const lanes = [
    ["Audience", "audience", reactions.map(([time, count]) => [time, time, count])],
    ["Scanned", "coverage", coverage],
    ...(Array.isArray(state.analyzed_coverage) ? [["Analyzed", "analyzed", state.analyzed_coverage]] : []),
    ["Candidates", "candidate", rangeMarks(state.candidates_found)],
    ["Exports", "export", rangeMarks(state.clips)]
  ];
  replayTracks.replaceChildren();
  for (const [label, kind, points] of lanes) {
    const lane = document.createElement("div");
    lane.className = "replay-lane";
    const name = document.createElement("span");
    name.textContent = label;
    const track = document.createElement("div");
    track.className = "replay-track";
    track.dataset.kind = kind;
    for (const [start, end, count] of points) {
      const mark = document.createElement("span");
      mark.className = "replay-mark";
      mark.dataset.time = start;
      mark.style.left = `${100 * Math.max(0, start) / duration}%`;
      mark.style.width = `${100 * Math.max(0, Math.min(end, duration) - start) / duration}%`;
      if (count) mark.style.height = `${Math.min(100, 25 + count * 8)}%`;
      track.append(mark);
    }
    track.addEventListener("click", (event) => {
      const mark = event.target.closest(".replay-mark");
      const bounds = track.getBoundingClientRect();
      const time = mark ? Number(mark.dataset.time)
        : Math.floor(Math.min(duration - 1, Math.max(0, duration * (event.clientX - bounds.left) / bounds.width)));
      const index = reactions.findIndex(([point]) => point === time);
      replayPeaks.value = index < 0 ? "" : index;
      selectReplayTime(time);
    });
    lane.append(name, track);
    replayTracks.append(lane);
  }
  selectReplayTime(reactions[0]?.[0] ?? state.clips[0]?.event_time ?? state.clips[0]?.start ?? 0);
  if (reactions.length) replayPeaks.value = "0";
  replayMap.hidden = false;
  results.hidden = false;
  viewResults.hidden = false;
}

replayTime.addEventListener("change", () => {
  if (!replayState) return;
  replayPeaks.value = "";
  selectReplayTime(parseReplayTime(replayTime.value), false);
});
replayTime.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    replayTime.dispatchEvent(new Event("change"));
  }
});
rescanReplay.addEventListener("click", () => {
  if (selectedReplayTime === null) return;
  document.querySelector("#youtube").value = `https://www.youtube.com/watch?v=${replayState.video_id}`;
  document.querySelector("#source").value = "";
  recordingFolder.value = "";
  mode.value = "stream";
  const start = Math.max(0, Math.floor(selectedReplayTime) - 15);
  scanStart.value = `${Math.floor(start / 60)}:${String(start % 60).padStart(2, "0")}`;
  updateScanWindow();
  scanWindow.open = true;
  scanStart.focus();
});

function showProgress(state) {
  jobProgress.dataset.state = state.status;
  if (statusText.textContent !== state.message) statusText.textContent = state.message;
  const notice = [
    state.cloud_reviewed ? `Gemini reviewed ${state.cloud_reviewed} ${state.cloud_reviewed === 1 ? "clip" : "clips"}.` : "",
    state.vision_notice,
  ].filter(Boolean).join(" ");
  if (visionNotice.textContent !== notice) visionNotice.textContent = notice;
  visionNotice.hidden = !notice;
  youtubeUploadStatus.hidden = !state.publishing;
  if (state.publishing) youtubeUploadStatus.textContent = state.publishing.message;
  youtubeUploadLink.hidden = !state.publishing?.url;
  if (state.publishing?.url) youtubeUploadLink.href = state.publishing.url;
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

function showEarlyPreview(state) {
  if (!state.early_preview) return;
  const source = state.early_preview;
  if (earlyPreviewVideo.getAttribute("src") !== source.preview) earlyPreviewVideo.src = source.preview;
  document.querySelector("#early-preview-title").textContent =
    `${source.title} · ${timestamp(source.start)} · ready in ${state.first_preview_seconds}s`;
  document.querySelector("#early-preview-status").textContent = state.status === "error"
    ? "The scan stopped before final ranking finished."
    : "The scan is still running. Final picks may change.";
  if (state.clips.length || state.status === "complete") {
    earlyPreviewVideo.pause();
    earlyPreview.hidden = true;
  } else {
    earlyPreview.hidden = false;
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
  earlyPreviewVideo.pause();
  earlyPreviewVideo.removeAttribute("src");
  earlyPreview.hidden = true;
  replayMap.hidden = true;
  replayState = null;
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
      showEarlyPreview(state);
      if (state.first_clip_seconds !== undefined) {
        firstClipTime.textContent = `First clip ready in ${state.first_clip_seconds} s`;
        firstClipTime.hidden = false;
      }
      state.clips.slice(clips.children.length).forEach((clip) => addClip(clip, state.video_id));
      batchDownload.hidden = !state.clips.length;
      viewResults.hidden = !state.clips.length;
      if (state.status === "complete" || state.status === "error") {
        if (replayMap.hidden) renderReplayMap(state);
        evaluationExport.href = `/jobs/${job.id}/evaluation`;
        evaluationExport.hidden = false;
        batchForm.hidden = !state.clips.some((clip) => clip.editor);
      }
      const uploading = ["queued", "uploading"].includes(state.publishing?.status);
      if ((state.status === "complete" || state.status === "error") && !uploading) break;
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

const savedReplayJob = new URLSearchParams(location.search).get("job");
if (/^[a-f0-9]{32}$/.test(savedReplayJob || "")) {
  fetch(`/jobs/${savedReplayJob}`, {cache: "no-store"}).then(async (response) => {
    if (!response.ok) throw new Error("Could not open the saved replay.");
    const state = await response.json();
    state.clips.forEach((clip) => addClip(clip, state.video_id));
    renderReplayMap(state);
    if (state.publishing) {
      jobProgress.hidden = false;
      showProgress(state);
    }
    if (!replayMap.hidden && location.hash === "#replay-map") replayMap.scrollIntoView();
  }).catch((error) => {
    jobProgress.hidden = false;
    showProgress({status: "error", message: error.message});
  });
}

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
