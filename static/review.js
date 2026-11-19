const player = document.querySelector("#review-video");
const form = document.querySelector("#review-form");
const statusText = document.querySelector("#review-status");
const comments = document.querySelector("#comments");
const note = document.querySelector("#review-note");
const url = location.pathname + "/notes";

function displayNotes(entries) {
  comments.replaceChildren();
  for (const {time, text} of entries) {
    const item = document.createElement("li");
    const seek = document.createElement("button");
    seek.textContent = `${time}s`;
    seek.addEventListener("click", () => { player.currentTime = time; });
    item.append(seek, " ", text);
    comments.append(item);
  }
}

async function loadNotes(options) {
  try {
    const response = await fetch(url, options);
    if (!response.ok) throw new Error("This review link or comment is unavailable.");
    displayNotes((await response.json()).notes);
    return true;
  } catch (error) {
    statusText.textContent = error.message;
    return false;
  }
}

loadNotes();
form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const saved = await loadNotes({method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({time: player.currentTime, text: note.value})});
  if (saved) note.value = "";
});
