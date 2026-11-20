# Shortlist Studio

Local studio for turning videos into captioned clips. It transcribes with faster-whisper, selects speech or gaming highlights, and renders MP4s with FFmpeg. Both modes can request up to 20 clips and may return fewer when there are fewer distinct highlights. Podcast jobs can also set a 30- to 120-second duration limit.

Exports use 1080p-class frames, Lanczos resizing, source frame cadence, H.264 High Profile at CRF 17, and 192 kbps AAC audio. Passage edits use a lossless intermediate before the final encode. Full-video and timestamped YouTube imports can request up to 1080p where available. Automatic replay scouting keeps a lower source ceiling to limit download time. Export sharpness still depends on the source.

## Run in Docker

With Docker Desktop running, start Shortlist from the project directory:

```powershell
docker compose up -d --build --wait
```

Open [Shortlist Studio in Docker](http://127.0.0.1:5052/). Set `SHORTLIST_PORT` if you need a different host port. The Compose volume keeps projects and downloaded model weights across container restarts, separately from the local installation. The container runs models on the CPU and downloads weights as needed. Local review works without an API key. If you use Gemini, set `SHORTLIST_GEMINI_API_KEY` in the PowerShell environment before starting the container.

Use `docker compose logs -f shortlist` to follow processing or `docker compose down` to stop the container while keeping its data volume.

## Run locally

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

Open http://127.0.0.1:5050, paste an accessible YouTube, Vimeo, or Zoom recording link you have permission to clip, and select **Generate Shorts**. Gaming replay window search applies to YouTube. Link imports use yt-dlp with Node.js 22 or newer on PATH. Recordings that require a login or password can be supplied as a local video file. The first run downloads the Whisper base model. Use the `SHORTLIST_MODEL` environment variable to select another faster-whisper model or a local model folder.

Choose **Podcast / interview** for transcript-led picks and automatic face tracking. **Gaming stream / GTA highlights** ranks moments using changes in motion, sound and spoken reactions. Gaming exports preserve the full source frame in a vertical layout so the HUD stays visible. The detector still misses some quiet gameplay moments and can produce ordinary picks.

YouTube gaming mode offers Quick (up to four minutes), Balanced (up to eight), Deep (up to 48), and Wide (up to two hours of sampled footage) coverage across long replays. Wide also looks before and after isolated audience references, and can take substantially longer. Shortlist scans motion and audio first, then transcribes the most promising windows. Quick visually reviews up to two candidates. YouTube replay-activity peaks help select windows when available. Shortlist filters repeated footage by timestamp and visual similarity, so distinct moments can both survive when their suggested titles match. Enter a specific start time to scan three minutes from that point. If that import times out, Shortlist retries with 45 seconds. For a broadcast YouTube is still processing, Shortlist can reuse the public replay manifest across windows. Active broadcasts remain unsupported.

Spoken language defaults to auto-detection. You can also enter a Whisper language code such as `en`, `hi`, `kn`, or `es`. Captions use the spoken language. Automatic language detection applies to the file as a whole. Install fonts for the scripts used in your footage if your system lacks them. The ranking uses general punctuation and pacing cues, plus English hook and contrast words.

Each clip starts with an editable headline and separate timed speech captions. **Saved projects** reopens original footage, exported variants and review notes after restart. The app stores them in `.shortlist-data` by default. Set `SHORTLIST_DATA_DIR` to use another local directory.

## Edit and export

- Open **Edit clip** to correct caption text, set the start and end from the transcript or in seconds, or exclude a passage. Excluding a passage cuts both its audio and video and retimes the remaining captions.
- **Follow faces** adjusts the crop using detected faces and mouth movement. Choose **Fit entire frame** to preserve the gaming HUD or **Center crop** for a fixed position.
- Choose a caption style, accent color and optional brand text. The brand preset is saved in the current browser.
- Upload a B-roll image or video, or search Wikimedia Commons for a still. Set its start time or match it to a caption keyword. The source audio continues under the B-roll. Stock exports provide an attribution file to accompany the clip. Gain, steady-noise reduction and loudness normalization are available in the audio controls.
- Render the same edit in 9:16, 1:1 and 16:9, or use **Render batch** to create additional formats for every original clip in a job. **Download all exports** packages the original clips and rendered variants in a ZIP.
- Add timed review notes on the original preview, exchange them as JSON, or create a revocable review link. Review links give access to the original exported clip and its comments.

Face tracking estimates the subject from the video and can miss speaker changes in multi-person or obscured shots. Stock searches return stills with supported Commons license metadata. The editor suggests the current caption as a search query and lets you choose the asset. In Chromium browsers you can select a local recording folder, such as an OBS output folder, and Shortlist selects its newest video.

## Review from another device

The editor runs on loopback. To make only the review page reachable from another device, configure `SHORTLIST_REVIEW_BIND` for a separate review listener, optionally set `SHORTLIST_REVIEW_PORT` (default 5051), and set `SHORTLIST_REVIEW_URL` to the address reviewers can open. For hosted review, put the review-only listener behind HTTPS. Links grant access to a single clip until revoked or replaced. The listener serves preview and comments without editing or administrative routes. This is a link-based workflow with no hosted accounts or billing.

Gaming mode can review shortlisted clips with a local SmolVLM2 model. The first run downloads its weights. Visual review samples the beginning, strongest moment and ending of each reviewed clip and uses visible actions, vehicles and settings to refine the ranking and headline. When a gaming headline is generic or repeats a stronger pick's title, the card shows its timestamp and the rendered video leaves the headline blank for you to write in the editor. Turn off visual review for faster motion, audio, and transcript-based results. See [the research and benchmarking notes](RESEARCH.md).

For cloud review, set `SHORTLIST_GEMINI_API_KEY` to a key from a Google AI Studio project on the Free tier with billing disabled. Restart Shortlist and select **Gemini 3.8 Flash** under **Gameplay review model**. Shortlist sends up to six shortlisted excerpts (video and audio), depending on the replay coverage setting. Gemini reviews the setup and payoff, can downrank routine footage, and can abstain from writing a headline. If the free quota runs out or a request fails, Shortlist continues with local review. Local review is the default and works without an API key. Replay coverage still follows the selected scan depth.

With Gemini selected, a manual start time or a gameplay file of up to 45 seconds can go to direct review when the detector finds no candidates. For a start time, direct review checks the first 45 seconds of the imported footage. Shortlist exports the excerpt only if Gemini identifies a specific payoff or the race HUD confirms a change.

Repeat automatic scans of an unchanged replay prioritize footage outside the coverage of completed scans. When Gemini identifies a payoff time, Shortlist can check the HUD around that time and use it to trim a longer direct-review excerpt.

If an automatic scan stops or the server restarts, submit the same YouTube link and scan depth again. Shortlist reuses saved windows from the interrupted run and includes them in highlight ranking. The results show how many windows were reused.

Automatic YouTube gaming scans also look for timestamps in public video comments and bursts of unique viewers in public replay chat. These signals can steer scan windows and surface candidate clips even before the footage has a clear local signal. Shortlist looks for a limited sample of audience activity and continues with video and audio when that data is unavailable. The app retains aggregate signals for the job rather than saving downloaded chat transcripts.

Gaming clip cards show matching audience activity and readable race position changes when available. YouTube cards can jump to the detected moment in the original replay, and the detection details show the underlying observations.

Balanced and Deep can take a second look at closely spaced frames around a top candidate when the first review is weak. Quick uses one pass per reviewed candidate. This adds inference time and can clarify a movement, but specific crashes and other severe claims still need supporting evidence.

When Visual AI is enabled, local OCR checks the lower-right race HUD on three frames before and three after each reviewed gaming moment. A position-change headline requires repeated readings with race context and the same displayed field size. A did-not-finish headline requires repeated, player-specific result text. Other HUD layouts may produce no reading.

Open [Clip benchmark](http://127.0.0.1:5050/benchmark) to compare MP4s from the same source. Import one to five candidates per tool, enter each tool's time to first clip, and have a reviewer rate the randomized set. The page calculates postability, headline accuracy, and editing effort, then exports the ratings as JSON. Shortlist shows its time to first clip in the results. The benchmark uses local browser file previews.

Use [Label gameplay moments](http://127.0.0.1:5050/labels) to create timestamped ground truth. Enter the source video's time offset if labeling an excerpt. After generating Shorts, use **Download evaluation data**, then score the run locally:

```powershell
python evaluation.py benchmarks/gameplay-labels.json path-to-shortlist-evaluation.json
```

The scorer distinguishes moments outside the scan from detection and ranking misses. It measures the union of the decoded audio intervals as scan coverage and matches each label by its midpoint. The included labels are a small exploratory set. They do not substitute for blind ratings.
