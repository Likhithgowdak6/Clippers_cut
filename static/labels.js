const get = (id) => document.getElementById(id);
const labels = {sources: Object.create(null)};
let videoUrl;

get("media").addEventListener("change", (event) => {
  if (videoUrl) URL.revokeObjectURL(videoUrl);
  const file = event.target.files[0];
  const player = get("player");
  player.hidden = !file;
  if (file) {
    videoUrl = URL.createObjectURL(file);
    player.src = videoUrl;
  } else {
    player.removeAttribute("src");
    player.load();
  }
  document.querySelectorAll("[data-capture]").forEach((button) => { button.disabled = !file; });
});

document.querySelectorAll("[data-capture]").forEach((button) => {
  button.addEventListener("click", () => {
    get(button.dataset.capture).value = get("player").currentTime.toFixed(2);
  });
});

function videoId(value) {
  if (/^[\w-]{11}$/.test(value)) return value;
  try {
    const url = new URL(value);
    if (url.hostname === "youtu.be") return url.pathname.split("/")[1];
    if (["youtube.com", "www.youtube.com", "m.youtube.com"].includes(url.hostname)) {
      return url.searchParams.get("v") || url.pathname.split("/")[2];
    }
  } catch {
    return null;
  }
  return null;
}

get("label-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const source = videoId(get("source").value.trim());
  const start = Number(get("start").value);
  const end = Number(get("end").value);
  const offset = Number(get("offset").value);
  const note = get("note").value.trim();
  if (!source || !/^[\w-]{11}$/.test(source) || end <= start || !note) {
    get("status").textContent = "Enter a valid YouTube link, a positive time range, and an observation.";
    return;
  }
  const label = {start: +(start + offset).toFixed(2), end: +(end + offset).toFixed(2),
    category: get("category").value, note};
  (labels.sources[source] ??= []).push(label);
  const item = document.createElement("li");
  item.textContent = `${source} · ${label.start}–${label.end} s · ${label.category.replaceAll("_", " ")} · ${note}`;
  get("labels").append(item);
  get("export").hidden = false;
  get("status").textContent = "Label added.";
});

get("export").addEventListener("click", () => {
  const url = URL.createObjectURL(new Blob([JSON.stringify(labels, null, 2)], {type: "application/json"}));
  const link = document.createElement("a");
  link.href = url;
  link.download = "gameplay-labels.json";
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
