import json
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from secrets import token_urlsafe
from tempfile import SpooledTemporaryFile, TemporaryDirectory
from threading import Lock, Thread
from time import monotonic
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4
from zipfile import ZIP_STORED, ZipFile

import imageio_ffmpeg
import numpy as np
import requests
from flask import Blueprint, Flask, abort, jsonify, render_template, request, send_file, send_from_directory

from clipping import Clip, Segment, caption_cues, rank_clips, rank_gameplay, same_gameplay_moment
from editor import ExportOptions, face_commands, join_passages, parse_edit, render_format
from project_store import load_projects, save_project
from stock import download_still, lookup
from race_hud import inspect_hud
from replay_import import download_replay_window, prepare_replay
from yt_dlp.utils import DownloadError
from vision import describe, visual_headline

app = Flask(__name__)
review_pages = Blueprint("review_pages", __name__)
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024**3
app.config["TRUSTED_HOSTS"] = ["localhost", "127.0.0.1", "[::1]"]
workspace = Path(os.environ.get("SHORTLIST_DATA_DIR", Path(__file__).resolve().parent / ".shortlist-data")).resolve()
workspace.mkdir(parents=True, exist_ok=True)
jobs, projects, edits, review_notes = load_projects(workspace, app.logger)
lock = Lock()
worker = ThreadPoolExecutor(max_workers=1)
model = None


def youtube_id(value):
    url = urlsplit(value)
    if url.scheme not in {"http", "https"}:
        return None
    parts = url.path.strip("/").split("/")
    identifier = ""
    if url.hostname == "youtu.be" and len(parts) == 1:
        identifier = parts[0]
    if url.hostname in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
        if url.path == "/watch":
            identifier = parse_qs(url.query).get("v", [""])[0]
        elif len(parts) == 2 and parts[0] in {"shorts", "live", "embed"}:
            identifier = parts[1]
    return identifier if re.fullmatch(r"[A-Za-z0-9_-]{11}", identifier) else None


def recording_link(value):
    url = urlsplit(value)
    if url.scheme != "https" or url.username or url.password or url.port not in {None, 443}:
        return None
    host = url.hostname or ""
    if host in {"vimeo.com", "www.vimeo.com", "player.vimeo.com"}:
        video = re.fullmatch(r"/(?:video/)?(\d+)(?:/([A-Za-z0-9]+))?/?", url.path)
        if video:
            access = video[2] or parse_qs(url.query).get("h", [""])[0]
            suffix = f"?h={access}" if re.fullmatch(r"[A-Za-z0-9]+", access) else ""
            return "Vimeo", f"https://player.vimeo.com/video/{video[1]}{suffix}"
    if (host == "zoom.us" or host.endswith(".zoom.us")) and re.fullmatch(
            r"/rec(?:ording)?/(?:share|play)/[A-Za-z0-9._~-]+/?", url.path):
        return "Zoom", value
    return None


def import_recording(url, directory):
    subprocess.run(
        [sys.executable, "-m", "yt_dlp", "--ignore-config", "--no-playlist", "--no-progress",
         "--socket-timeout", "15", "--retries", "1", "--ffmpeg-location", imageio_ffmpeg.get_ffmpeg_exe(),
         "--format", "bv*[height<=?1080]+ba/b[height<=?1080]", "--max-filesize", "2G",
         "--merge-output-format", "mkv", "--output", "recording.%(ext)s", url],
        cwd=directory, capture_output=True, check=True, timeout=1800,
    )
    files = [path for path in directory.glob("recording.*") if path.suffix in {".mkv", ".mp4", ".webm", ".mov"}]
    if len(files) != 1 or files[0].stat().st_size > 2 * 1024**3:
        raise ValueError("No supported recording was returned.")
    return files[0]


def update(job_id, **fields):
    with lock:
        jobs[job_id] = {**jobs.get(job_id, {}), **fields}
        persist(job_id)


def persist(job_id):
    save_project(workspace, job_id, jobs[job_id], projects, edits, review_notes)


def import_youtube(video_id, directory, start=None, length=180):
    section = [] if start is None else ["--download-sections", f"*{start}-{start + length}"]
    resolution = 1080 if start is None else 720
    command = (
        [sys.executable, "-m", "yt_dlp", "--ignore-config", "--no-playlist",
         "--no-progress", "--socket-timeout", "20", "--retries", "2",
         "--js-runtimes", "node", "--ffmpeg-location", imageio_ffmpeg.get_ffmpeg_exe(),
         "--break-match-filter", "live_status != post_live & !is_live & !is_upcoming",
         "--format", f"bv*[height<={resolution}]+ba/b[height<={resolution}]",
         "--merge-output-format", "mkv", "--output", "youtube.%(ext)s",
         *(["--max-filesize", "2G"] if start is None else section),
         f"https://www.youtube.com/watch?v={video_id}"]
    )
    offset = start or 0
    try:
        subprocess.run(command, cwd=directory, capture_output=True, check=True,
                       timeout=1800 if start is None else 120)
    except subprocess.CalledProcessError as error:
        if start is None or b"does not pass filter" not in error.stdout + error.stderr:
            raise
        replay = subprocess.run(
            [sys.executable, str(Path(__file__).with_name("replay_import.py").resolve()), video_id, str(start), str(length)],
            cwd=directory, capture_output=True, timeout=150,
        )
        match = re.search(rb"^REPLAY_START=([0-9.]+)$", replay.stdout.replace(b"\r", b""), re.MULTILINE)
        if replay.returncode or not match:
            raise error
        offset = float(match[1])
    files = [item for item in directory.glob("youtube.*") if item.suffix in {".mkv", ".mp4", ".webm"}]
    if len(files) != 1:
        raise ValueError("YouTube import did not produce a video.")
    return files[0], offset


def read_audio(source):
    audio = subprocess.run(
        [imageio_ffmpeg.get_ffmpeg_exe(), "-nostdin", "-loglevel", "error", "-i", str(source),
         "-map", "0:a:0", "-ac", "1", "-ar", "16000", "-f", "f32le", "pipe:1"],
        capture_output=True, check=True, timeout=900,
    )
    return np.frombuffer(audio.stdout, dtype="<f4")


def transcribe(samples, language):
    global model
    from faster_whisper import WhisperModel

    if model is None:
        model = WhisperModel(os.environ.get("SHORTLIST_MODEL", "base"), device="cpu", compute_type="int8")
    segments, _ = model.transcribe(samples, language=language, vad_filter=True, word_timestamps=True)
    return [
        Segment(segment.start, segment.end, segment.text.strip(), tuple(
            (word.start, word.end, word.word) for word in segment.words or []
        ))
        for segment in segments if segment.text.strip()
    ]


def audio_peaks(samples):
    window = 4000
    blocks = samples[:len(samples) // window * window].reshape(-1, window)
    if len(blocks) < 4:
        return []
    loudness = np.sqrt(np.mean(blocks * blocks, axis=1))
    peaks = []
    for index in range(1, len(loudness) - 1):
        level = max(loudness[index], loudness[index + 1])
        before = loudness[max(0, index - 16):index]
        baseline = float(np.median(before))
        if level < max(0.035, baseline * 1.8):
            continue
        peaks.append((index / 4, min(1.0, float(level - baseline) * 7)))
    selected = []
    for time, strength in sorted(peaks, key=lambda peak: peak[1], reverse=True):
        if all(abs(time - other) >= 12 for other, _ in selected):
            selected.append((time, strength))
            if len(selected) == 30:
                break
    return selected


def sustained_motion(frames, fps):
    center = frames[:, 10:-8, 22:-14].astype(np.int16)
    change = (np.abs(np.diff(center, axis=0)) > 20).mean(axis=(1, 2))
    candidates = []
    for index in range(8 * fps, len(change) - 4 * fps):
        before = float(np.median(change[index - 8 * fps:index]))
        activity = change[index:index + 4 * fps]
        during = float(np.median(activity))
        if during - before >= .07 and before <= .18 and during >= .21:
            candidates.append(((index + fps) / fps, min(1.0, (during - before) * 4)))
    selected = []
    for time, strength in sorted(candidates, key=lambda item: (-item[1], item[0])):
        if all(abs(time - other) >= 16 for other, _ in selected):
            selected.append((time, strength))
            if len(selected) == 3:
                break
    return selected


def visual_peaks(source):
    width, height, fps = 96, 54, 3
    decoded = subprocess.run(
        [imageio_ffmpeg.get_ffmpeg_exe(), "-nostdin", "-v", "error", "-i", str(source),
         "-map", "0:v:0", "-vf", f"fps={fps},scale={width}:{height},format=gray",
         "-an", "-c:v", "rawvideo", "-threads", "1", "-f", "rawvideo", "pipe:1"],
        capture_output=True, check=True, timeout=300,
    )
    frames = np.frombuffer(decoded.stdout, dtype=np.uint8).reshape(-1, height, width)
    if len(frames) < 4:
        return [], [], frames
    differences = np.abs(np.diff(frames.astype(np.int16), axis=0))
    change = (differences > 22).mean(axis=(1, 2))
    change[change > .70] = 0  # Ignore most hard cuts and fades to a different scene.
    rate = np.convolve(change, np.ones(3) / 3, mode="same")
    baseline = float(np.median(rate))
    candidates = [
        ((index + 1) / fps, min(1.0, (value - baseline) * 4))
        for index, value in enumerate(rate) if value >= max(.14, baseline + .075)
    ]
    peaks = []
    for time, strength in sorted(candidates, key=lambda item: item[1], reverse=True):
        if all(abs(time - other) >= 3 for other, _ in peaks):
            peaks.append((time, strength))
            if len(peaks) == 120:
                break
    return peaks, sustained_motion(frames, fps), frames[::fps, 3:-3:3, 6:-6:3]


def gameplay_signals(source):
    samples = read_audio(source)
    motion, sustained, frames = visual_peaks(source)
    return samples, audio_peaks(samples), motion, sustained, frames


def scout_score(signals):
    _, audio, motion, sustained, _ = signals
    peaks = [(point, strength) for point, strength in motion]
    peaks.extend((point, strength * 1.20) for point, strength in sustained)
    return max((strength + .65 * max((level for time, level in audio if abs(time - point) < 3), default=0)
                for point, strength in peaks), default=0)


def analyze(source, language, stream, signals=None, clip_count=5, clip_length=60):
    if stream:
        samples, audio, motion, sustained, frames = signals if signals is not None else gameplay_signals(source)
    else:
        samples = read_audio(source)
    segments = transcribe(samples, language)
    duration = len(samples) / 16000
    if stream:
        clips = rank_gameplay(segments, audio, motion, duration, sustained=sustained)
        return [(clip, frames[int(clip.start):int(clip.end)].astype(np.int16)) for clip in clips]
    clips = rank_clips(segments, limit=clip_count, max_duration=clip_length)
    if not clips and segments and 5 <= duration <= clip_length:
        title = " ".join(segments[0].text.split()[:9])
        clips = [Clip(0, duration, title, "The source is already short enough for a single clip.", tuple(segments))]
    return [(clip, None) for clip in clips]


def repeats_footage(left, right):
    for shift in range(-4, 5):
        left_start, right_start = max(0, shift), max(0, -shift)
        size = min(len(left) - left_start, len(right) - right_start)
        if size < 10:
            continue
        differences = np.abs(left[left_start:left_start + size] - right[right_start:right_start + size])
        if np.count_nonzero(differences.mean(axis=(1, 2)) < 10) >= max(10, .70 * size):
            return True
    return False


SCAN_PLANS = {"fast": (4, 60, 4), "balanced": (12, 40, 6), "deep": (36, 40, 8)}


def replay_windows(length, heatmap, depth="balanced"):
    if length <= 180:
        return [(0, 180)]
    limit, size, _ = SCAN_PLANS[depth]
    if length <= limit * size:
        return [(start, min(size, length - start)) for start in range(0, length, size)]
    last_start = length - size
    starts = []
    if heatmap:
        scores = [point["value"] for point in heatmap]
        threshold = float(np.median(scores)) + 0.15
        for point in sorted(heatmap, key=lambda item: item["value"], reverse=True):
            middle = (point["start_time"] + point["end_time"]) / 2
            if point["value"] < threshold:
                break
            if not size / 2 <= middle <= length - size / 2:
                continue
            start = round(middle - size / 2)
            if all(abs(start - other) >= size for other in starts):
                starts.append(start)
                if len(starts) == max(1, limit // 4):
                    break
    samples = [round(point) for point in np.linspace(0, last_start, limit * 4)]
    while len(starts) < limit:
        candidates = [point for point in samples if point not in starts]
        start = max(candidates, key=lambda point: min(
            (abs(point - other) for other in starts), default=length - point
        ))
        starts.append(start)
    return [(start, size) for start in sorted(starts)]


def import_scout_window(video_id, folder, start, size, prepared=None):
    if prepared is not None:
        try:
            return download_replay_window(prepared, folder)
        except (ValueError, OSError, subprocess.SubprocessError):
            app.logger.warning("Refreshing replay media for window at %s", start)
    # A failed partial import must not be mistaken for the refreshed source.
    for path in folder.glob("youtube.*"):
        path.unlink(missing_ok=True)
    return import_youtube(video_id, folder, start, size)


def search_replay(job_id, directory, video_id, language, depth):
    update(job_id, status="importing", message="Finding scan windows across the replay.")
    metadata = subprocess.run(
        [sys.executable, "-m", "yt_dlp", "--ignore-config", "--no-playlist",
         "--js-runtimes", "node", "--socket-timeout", "15", "--skip-download",
         "--print", "%(.{duration,live_status,heatmap})j", f"https://www.youtube.com/watch?v={video_id}"],
        capture_output=True, check=True, timeout=45, text=True,
    )
    replay = json.loads(metadata.stdout)
    if replay.get("live_status") in {"is_live", "is_upcoming"}:
        raise ValueError("Automatic scanning needs an available replay.")
    if not replay.get("duration"):
        raise ValueError("Replay duration unavailable.")
    windows = replay_windows(int(replay["duration"]), replay.get("heatmap"), depth)
    replay_segments = None
    if replay.get("live_status") == "post_live":
        try:
            replay_segments = prepare_replay(video_id, windows, shift_tail=True)
        except (DownloadError, ValueError):
            app.logger.warning("Shared replay manifest unavailable for %s", video_id)
    update(job_id, status="scanning", scanned=0, windows=len(windows),
           message=f"Scanning replay windows (0 of {len(windows)} checked).")
    shortlisted = []
    coverage = []
    completed = 0
    scanned = 0
    with ThreadPoolExecutor(max_workers=min(4, len(windows))) as imports:
        pending = {}
        for start, size in windows:
            folder = directory / f"window-{start}"
            folder.mkdir()
            prepared = replay_segments.get(start) if replay_segments else None
            future = imports.submit(import_scout_window, video_id, folder, start, size, prepared)
            pending[future] = start
        for future in as_completed(pending):
            try:
                source, offset = future.result()
                signals = gameplay_signals(source)
            except (subprocess.SubprocessError, ValueError, OSError):
                app.logger.warning("Could not scan window at %s for %s", pending[future], video_id)
            else:
                scanned += 1
                coverage.append((offset, offset + len(signals[0]) / 16000))
                shortlisted.append((scout_score(signals), source, offset, signals))
            completed += 1
            update(job_id, status="scanning", scanned=completed, windows=len(windows),
                   message=f"Scanning replay windows ({completed} of {len(windows)} checked).")
    update(job_id, scanned=scanned, windows=len(windows), coverage=sorted(coverage),
           source_seconds=replay["duration"])
    if not scanned:
        raise ValueError("None of the selected replay windows could be read.")
    matches = []
    shortlist = sorted(shortlisted, key=lambda item: (-item[0], item[2]))[:SCAN_PLANS[depth][2]]
    for index, (_, source, offset, signals) in enumerate(shortlist, 1):
        update(job_id, status="transcribing", message=f"Transcribing shortlisted window {index} of {len(shortlist)}.")
        clips = analyze(source, language, stream=True, signals=signals)
        matches.extend((source, offset, clip, signature) for clip, signature in clips)
    update(job_id, candidates_found=[
        {"start": offset + clip.start, "end": offset + clip.end}
        for _, offset, clip, _ in matches
    ])
    selected = []
    for source, offset, clip, signature in sorted(matches, key=lambda match: (-match[2].score, match[1] + match[2].start)):
        if any(
            same_gameplay_moment(clip, other, offset, origin)
            or repeats_footage(signature, existing)
            for _, origin, other, existing in selected
        ):
            continue
        selected.append((source, offset, clip, signature))
        if len(selected) == 8:
            break
    return [(source, offset, clip) for source, offset, clip, _ in selected]


def review_gameplay(job_id, matches, limit=4):
    candidates = matches[:limit]
    reviewed = []
    vision_available = True
    for index, (source, offset, clip) in enumerate(candidates):
        update(job_id, status="reviewing", reviewed=index, candidates=len(candidates),
               message=f"Visual AI is checking highlight {index + 1} of {len(candidates)}. First use may download the model.")
        hud = None
        try:
            hud = inspect_hud(source, clip.start, clip.end, clip.event_time)
        except Exception:
            app.logger.warning("Race HUD could not be read", exc_info=True)
        description = ""
        decisive_hud = hud and (hud.get("result") or hud["before"] != hud["after"])
        if vision_available and not decisive_hud:
            try:
                description = describe(source, clip.start, clip.end, event_time=clip.event_time)
            except Exception:
                app.logger.exception("Local visual review failed")
                update(job_id, vision_notice="Visual AI was unavailable. Picks can still use race HUD, motion, audio and speech.")
                vision_available = False
        transcript = " ".join(segment.text for segment in clip.segments)
        title, boost = visual_headline(description, transcript)
        reason = clip.reason
        if hud:
            old, new, entrants = hud["before"], hud["after"], hud["entrants"]
            if hud.get("result") == "did_not_finish":
                title = "The race ends without a finish"
                reason += " The race HUD reports that the player did not finish."
                boost += 1.5
            else:
                reason += f" Race HUD reads {old}/{entrants} before and {new}/{entrants} after."
            if new is not None and old != new:
                action = "Drops" if new > old else "Moves up"
                title = f"{action} from {old}/{entrants} to {new}/{entrants}"
                boost += 1.5
        elif description:
            reason += f" Visual AI observation (unverified): {description}"
        reviewed.append((source, offset, replace(clip, title=title or clip.title,
                                                score=clip.score + boost, reason=reason, hud=hud,
                                                visual_event=bool(title and boost >= .85))))
    return sorted(reviewed + matches[len(candidates):], key=gameplay_rank, reverse=True)


def gameplay_rank(match):
    clip = match[2]
    hud = clip.hud
    verified_event = bool(hud and (hud.get("result") or hud["before"] != hud["after"]))
    return verified_event, clip.visual_event, clip.score


GENERIC_GAMEPLAY_HEADLINES = {
    "things get chaotic", "things go sideways fast", "the action picks up",
    "the pace picks up", "on two wheels", "behind the wheel", "that was way too close",
    "a moment from the bike race", "a tense moment in the bike race", "the bike race gets wild",
}


def gameplay_titles(matches):
    seen = set()
    titled = []
    for source, offset, clip in matches:
        title_key = " ".join(re.findall(r"\w+", clip.title.casefold()))
        if title_key in GENERIC_GAMEPLAY_HEADLINES or title_key in seen or not title_key:
            seconds = int(offset + (clip.event_time if clip.event_time is not None else clip.start))
            hours, remainder = divmod(seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            timestamp = f"{hours}:{minutes:02}:{seconds:02}" if hours else f"{minutes}:{seconds:02}"
            clip = replace(clip, title=f"Gameplay at {timestamp}", hook="")
        else:
            seen.add(title_key)
            clip = replace(clip, hook=clip.title)
        titled.append((source, offset, clip))
    return titled


def render(source: Path, clip: Clip, index: int, stream=False):
    output = f"clip-{index}.mp4"
    options = ExportOptions(framing="fit" if stream else "smart")
    tracking = track_faces(source, clip, source.parent, options)
    render_format(source, clip, source.parent / output, options, "vertical", tracking=tracking)
    return output


def track_faces(source, clip, directory, options):
    if options.framing != "smart":
        return None
    try:
        return face_commands(source, clip, directory)
    except (ImportError, subprocess.SubprocessError, OSError, ValueError):
        app.logger.warning("Face tracking unavailable. Using center framing.")
        return None


def render_edit(edit_id, job_id, source, clip, options, broll, directory, stock_id=None):
    intermediate = directory / "passages.mp4"
    try:
        with lock:
            edits[edit_id].update(status="rendering", message="Preparing export.")
        if stock_id is not None:
            broll, credit = download_still(stock_id, directory)
            (directory / "credits.txt").write_text(credit + "\n", encoding="utf-8")
            with lock:
                edits[edit_id]["credits"] = f"/jobs/{job_id}/edits/{edit_id}/credits.txt"
                persist(job_id)
        if options.kept_ranges:
            source = join_passages(source, intermediate, options.kept_ranges)
        tracking = track_faces(source, clip, directory, options)
        for shape in options.formats:
            with lock:
                edits[edit_id]["message"] = f"Rendering {shape} export."
            render_format(source, clip, directory / f"{shape}.mp4", options, shape, broll=broll, tracking=tracking)
            with lock:
                edits[edit_id]["files"].append({"label": shape, "url": f"/jobs/{job_id}/edits/{edit_id}/{shape}.mp4"})
                persist(job_id)
        with lock:
            edits[edit_id].update(status="complete", message="Exports ready.")
            persist(job_id)
    except Exception:
        app.logger.exception("Edited clip export failed")
        with lock:
            edits[edit_id].update(status="error", message="Export failed. Check the B-roll file or try another framing option.")
            persist(job_id)
    finally:
        intermediate.unlink(missing_ok=True)
        if broll:
            broll.unlink(missing_ok=True)


def process(job_id, source, stream, language, hook, video_id=None, scan_start=None, visual_ai=True, depth="balanced",
            clip_count=5, clip_length=60, recording=None):
    started_at = monotonic()
    directory = source.parent
    scouting = None
    retained = {}
    try:
        offset = 0
        automatic = stream and video_id and not source.exists() and scan_start is None
        if recording and not source.exists():
            provider, url = recording
            update(job_id, status="importing", message=f"Importing the {provider} recording.")
            try:
                source = import_recording(url, directory)
            except (ValueError, OSError, subprocess.SubprocessError):
                update(job_id, status="error", message=f"Could not import the {provider} recording. Check its playback and download permissions, or use a local copy.")
                return
            finally:
                for partial in directory.glob("recording.*"):
                    if partial != source:
                        partial.unlink(missing_ok=True)
        if automatic:
            scouting = TemporaryDirectory(prefix="scan-", dir=directory)
            try:
                matches = search_replay(job_id, Path(scouting.name), video_id, language, depth)
            except (subprocess.SubprocessError, ValueError, OSError):
                update(job_id, status="error", message="Could not scan this replay. Check that it plays publicly or enter a specific start time.")
                return
        elif video_id and not source.exists():
            offset = scan_start if stream else 0
            message = (
                f"Importing three minutes from {offset // 60}:{offset % 60:02}."
                if stream else "Importing the YouTube video."
            )
            update(job_id, status="importing", message=message)
            try:
                source, offset = import_youtube(video_id, source.parent, offset if stream else None)
            except (subprocess.SubprocessError, ValueError, OSError) as error:
                output = (getattr(error, "stdout", None) or b"") + (getattr(error, "stderr", None) or b"")
                if b"does not pass filter" in output or b"Breaking on filtered video" in output:
                    message = "YouTube is still processing or broadcasting this stream. Try again once the finished replay is available."
                elif isinstance(error, subprocess.TimeoutExpired):
                    message = "YouTube did not send the footage in time. Try again or choose a different starting point."
                else:
                    message = "Could not import the video. Check that it plays publicly at the selected starting point."
                app.logger.warning("YouTube import failed for video %s (%s)", video_id, type(error).__name__)
                update(job_id, status="error", message=message)
                return
            finally:
                for partial in source.parent.glob("youtube.*"):
                    if partial != source:
                        partial.unlink(missing_ok=True)
        if not automatic:
            update(job_id, status="transcribing", message="Analyzing the video. The first run may download the speech model.")
            signals = gameplay_signals(source) if stream else None
            if signals is not None:
                update(job_id, coverage=[(offset, offset + len(signals[0]) / 16000)])
            matches = [(source, offset, clip) for clip, _ in analyze(
                source, language, stream, signals=signals, clip_count=clip_count, clip_length=clip_length
            )]
            update(job_id, candidates_found=[
                {"start": origin + clip.start, "end": origin + clip.end}
                for _, origin, clip in matches
            ])
        if not matches:
            message = (
                "No strong highlight found in the footage scanned. Try another start time."
                if stream else "No complete spoken moments found. Try a longer video with clear speech."
            )
            update(job_id, status="error", message=message)
            return
        if stream and visual_ai:
            matches = review_gameplay(job_id, matches, limit={"fast": 2, "balanced": 5, "deep": 6}[depth])
        matches = matches[:5 if stream else clip_count]
        if stream and not hook:
            matches = gameplay_titles(matches)
        results = []
        for index, (clip_source, offset, clip) in enumerate(matches, 1):
            if clip_source.parent != directory:
                if clip_source not in retained:
                    retained[clip_source] = clip_source.replace(directory / f"source-{index}{clip_source.suffix}")
                clip_source = retained[clip_source]
            update(job_id, status="rendering", total=len(matches), message=f"Rendering short {index} of {len(matches)}.")
            clip = replace(clip, hook=hook or (clip.hook if stream else clip.title))
            filename = render(clip_source, clip, index, stream)
            with lock:
                projects[job_id, index] = (clip_source, clip, stream)
            results.append({
                "title": hook or clip.title, "reason": clip.reason, "start": offset + clip.start, "end": offset + clip.end,
                "preview": f"/jobs/{job_id}/clips/{filename}",
                "hud": clip.hud,
                "editor": f"/jobs/{job_id}/editor/{index}",
            })
            if index == 1:
                update(job_id, first_clip_seconds=round(monotonic() - started_at, 1))
            update(job_id, clips=list(results))
        with lock:
            coverage = jobs[job_id].get("scanned") if automatic else None
            windows = jobs[job_id].get("windows")
        message = f"{len(results)} {'short' if len(results) == 1 else 'shorts'} ready."
        if coverage is not None:
            message += f" Checked {coverage} of {windows} selected replay windows."
        update(job_id, status="complete", message=message)
    except Exception:
        app.logger.exception("Clip job failed")
        update(job_id, status="error", message="Processing stopped. Check the server log for model or media errors.")
    finally:
        with lock:
            has_edits = any(key[0] == job_id for key in projects)
        if not has_edits:
            source.unlink(missing_ok=True)
            for media in retained.values():
                media.unlink(missing_ok=True)
        if scouting is not None:
            scouting.cleanup()


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/example-output")
def example_output():
    return send_from_directory(Path(__file__).resolve().parent, "bike-race-hud-verified.mp4")


@app.get("/library")
def library():
    with lock:
        entries = [(job_id, job) for job_id, job in jobs.items() if job.get("clips")]
    entries.reverse()
    return render_template("library.html", entries=entries)


@app.get("/stock")
def stock_search():
    keyword = request.args.get("q", "").strip()
    if not 2 <= len(keyword) <= 100:
        return jsonify(error="Enter a stock search from 2 to 100 characters."), 400
    try:
        return jsonify(images=lookup(keyword))
    except (requests.RequestException, ValueError):
        return jsonify(error="Wikimedia Commons search is unavailable right now."), 502


@app.get("/benchmark")
def benchmark():
    return render_template("benchmark.html")


@app.get("/labels")
def labels():
    return render_template("labels.html")


@app.post("/jobs")
def create_job():
    mode = request.form.get("mode", "talk")
    language = request.form.get("language", "").strip().lower()
    hook = request.form.get("hook", "").strip()
    start = request.form.get("scan_start", "").strip()
    depth = request.form.get("depth", "balanced")
    try:
        clip_count = int(request.form.get("clip_count", 5))
        clip_length = int(request.form.get("clip_length", 60))
    except ValueError:
        return jsonify(error="Choose a supported clip count and duration."), 400
    if clip_count not in {5, 10, 15, 20} or clip_length not in {30, 60, 90, 120}:
        return jsonify(error="Choose a supported clip count and duration."), 400
    if depth not in SCAN_PLANS:
        return jsonify(error="Choose a supported replay search depth."), 400
    if start and not re.fullmatch(r"\d{1,5}:[0-5]\d", start):
        return jsonify(error="Enter the start time in minutes and seconds, such as 45:00."), 400
    scan_start = None
    if start:
        minutes, seconds = map(int, start.split(":"))
        scan_start = minutes * 60 + seconds
    if mode not in {"talk", "stream"} or len(hook) > 90 or (language and not re.fullmatch(r"[a-z]{2,3}", language)):
        return jsonify(error="Choose a supported mode and language, and keep hook text under 91 characters."), 400
    if language:
        from faster_whisper.tokenizer import _LANGUAGE_CODES

        if language not in _LANGUAGE_CODES:
            return jsonify(error="Enter a Whisper language code, such as en, hi, kn, or es."), 400
    link = request.form.get("youtube", "").strip()
    try:
        video_id = youtube_id(link) if link else None
        recording = recording_link(link) if link and not video_id else None
    except ValueError:
        video_id = None
        recording = None
    if link and not video_id and not recording:
        return jsonify(error="Enter a YouTube, Vimeo, or Zoom recording link."), 400
    source_file = request.files.get("source")
    if not video_id and not recording and not source_file:
        return jsonify(error="Paste a supported video link or choose a video file."), 400
    job_id = uuid4().hex
    directory = workspace / job_id
    directory.mkdir()
    source = directory / "source"
    if source_file:
        source_file.save(source)
    source_name = Path(source_file.filename).name if source_file else f"{recording[0]} recording" if recording else ""
    update(job_id, status="queued", message="Waiting to process video.", clips=[], video_id=video_id, source_name=source_name)
    visual_ai = request.form.get("visual_ai", "on") == "on"
    worker.submit(process, job_id, source, mode == "stream", language or None, hook, video_id,
                  scan_start, visual_ai, depth, clip_count, clip_length, recording)
    return jsonify(id=job_id), 202


@app.errorhandler(413)
def too_large(_error):
    return jsonify(error="The upload exceeds the 2 GB request limit."), 413


@app.get("/jobs/<job_id>")
def job_status(job_id):
    with lock:
        job = jobs.get(job_id)
    if job is None:
        abort(404)
    return jsonify({key: value for key, value in job.items() if key != "review_access"})


@app.get("/jobs/<job_id>/evaluation")
def evaluation_manifest(job_id):
    with lock:
        job = jobs.get(job_id)
    if job is None:
        abort(404)
    if job["status"] not in {"complete", "error"}:
        return jsonify(error="Wait for the job to finish."), 409
    manifest = {key: job.get(key) for key in ("video_id", "coverage", "candidates_found",
                                               "source_seconds", "first_clip_seconds", "clips", "status")}
    response = jsonify(manifest)
    response.headers["Content-Disposition"] = 'attachment; filename="shortlist-evaluation.json"'
    return response


@app.get("/jobs/<job_id>/clips/<filename>")
def clip_file(job_id, filename):
    with lock:
        job = jobs.get(job_id)
    if job is None or not any(clip["preview"].endswith("/" + filename) for clip in job["clips"]):
        abort(404)
    return send_from_directory(workspace / job_id, filename, as_attachment="download" in request.args)


@app.route("/jobs/<job_id>/editor/<int:index>", methods=["GET", "POST"])
def edit_clip(job_id, index):
    with lock:
        project = projects.get((job_id, index))
        previous_exports = [(list(edit["files"]), edit.get("credits")) for edit in edits.values()
                            if edit["job"] == job_id and edit["index"] == index and edit["files"]]
    if project is None:
        abort(404)
    source, clip, stream = project
    if request.method == "GET":
        cues = [{"start": start - clip.start, "end": end - clip.start, "text": text}
                for start, end, text in caption_cues(clip)]
        return render_template("editor.html", previous_exports=previous_exports, project={"jobId": job_id, "index": index,
            "duration": clip.end - clip.start, "headline": clip.hook, "cues": cues,
            "framing": "fit" if stream else "smart"})
    try:
        payload = json.loads(request.form.get("edit", "{}"))
        edited, options = parse_edit(clip, payload)
        stock_id = payload.get("stock_id")
        if stock_id is not None and (type(stock_id) is not int or not 1 <= stock_id < 2**53):
            raise ValueError("Choose a valid stock image.")
    except (ValueError, TypeError, AttributeError) as error:
        return jsonify(error=str(error)), 400
    asset = request.files.get("broll")
    if asset and stock_id:
        return jsonify(error="Choose either uploaded B-roll or a stock image."), 400
    suffix = Path(asset.filename).suffix.lower() if asset and asset.filename else ""
    if asset and suffix not in {".jpg", ".jpeg", ".png", ".mp4", ".mov", ".webm"}:
        return jsonify(error="B-roll must be a JPG, PNG, MP4, MOV, or WebM file."), 400
    edit_id = uuid4().hex
    directory = workspace / job_id / edit_id
    directory.mkdir()
    broll = directory / ("broll" + suffix) if asset else None
    if broll:
        asset.save(broll)
    with lock:
        edits[edit_id] = {"job": job_id, "index": index, "status": "queued", "files": [], "message": "Queued for export."}
        persist(job_id)
    worker.submit(render_edit, edit_id, job_id, source, edited, options, broll, directory, stock_id)
    return jsonify(poll=f"/jobs/{job_id}/edits/{edit_id}"), 202


@app.get("/jobs/<job_id>/edits/<edit_id>")
def edit_status(job_id, edit_id):
    with lock:
        edit = edits.get(edit_id)
        if not edit or edit["job"] != job_id:
            abort(404)
        return jsonify(edit)


@app.route("/jobs/<job_id>/editor/<int:index>/notes", methods=["GET", "POST"])
def notes(job_id, index):
    with lock:
        project = projects.get((job_id, index))
        if not project:
            abort(404)
        entries = review_notes.setdefault((job_id, index), [])
        if request.method == "POST":
            data = request.get_json(silent=True)
            if not isinstance(data, dict):
                return jsonify(error="Enter a note or import notes from Shortlist."), 400
            incoming = data.get("notes", [data])
            duration = project[1].end - project[1].start
            if not isinstance(incoming, list) or len(incoming) > 500:
                return jsonify(error="Import up to 500 review notes."), 400
            pending = []
            for item in incoming:
                if not isinstance(item, dict):
                    return jsonify(error="Invalid review note."), 400
                note, time = item.get("text"), item.get("time")
                if (not isinstance(note, str) or not 1 <= len(note.strip()) <= 500
                        or type(time) not in {int, float} or not 0 <= time <= duration + .01):
                    return jsonify(error="Enter a review note within the clip."), 400
                pending.append({"time": round(time, 2), "text": note.strip()})
            entries.extend(entry for entry in pending if entry not in entries)
            persist(job_id)
        response = jsonify(notes=sorted(entries, key=lambda entry: entry["time"]))
        if "download" in request.args:
            response.headers["Content-Disposition"] = 'attachment; filename="clip-review-notes.json"'
        return response


@app.route("/jobs/<job_id>/editor/<int:index>/share", methods=["POST", "DELETE"])
def share_clip(job_id, index):
    if not request.is_json:
        abort(415)
    with lock:
        if (job_id, index) not in projects:
            abort(404)
        gates = jobs[job_id].setdefault("review_access", {})
        if request.method == "DELETE":
            gates.pop(str(index), None)
            persist(job_id)
            return jsonify(revoked=True)
        token = token_urlsafe(32)
        gates[str(index)] = sha256(token.encode()).hexdigest()
        persist(job_id)
    base = os.environ.get("SHORTLIST_REVIEW_URL", "").rstrip("/")
    return jsonify(url=f"{base}/review/{token}")


def shared_project(token):
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
        abort(404)
    signature = sha256(token.encode()).hexdigest()
    with lock:
        for job_id, job in jobs.items():
            for index, digest in job.get("review_access", {}).items():
                if digest == signature and (job_id, int(index)) in projects:
                    return job_id, int(index)
    abort(404)


@review_pages.after_request
def private_review_response(response):
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    return response


@review_pages.get("/review/<token>")
def shared_review(token):
    job_id, index = shared_project(token)
    with lock:
        title = projects[job_id, index][1].hook
    return render_template("review.html", token=token, title=title)


@review_pages.get("/review/<token>/media")
def shared_media(token):
    job_id, index = shared_project(token)
    return send_from_directory(workspace / job_id, f"clip-{index}.mp4")


@review_pages.route("/review/<token>/notes", methods=["GET", "POST"])
def shared_notes(token):
    return notes(*shared_project(token))


@app.get("/jobs/<job_id>/edits/<edit_id>/<filename>")
def edit_file(job_id, edit_id, filename):
    with lock:
        edit = edits.get(edit_id)
        if not edit or edit["job"] != job_id or not (
            any(item["url"].endswith("/" + filename) for item in edit["files"])
            or (filename == "credits.txt" and edit.get("credits"))
        ):
            abort(404)
    return send_from_directory(workspace / job_id / edit_id, filename,
                               as_attachment="download" in request.args)


@app.get("/jobs/<job_id>/download")
def download_batch(job_id):
    with lock:
        job = jobs.get(job_id)
        if not job or not job["clips"]:
            abort(404)
        originals = [Path(item["preview"]).name for item in job["clips"]]
        variants = [(edit_id, edit["index"], Path(item["url"]).name) for edit_id, edit in edits.items()
                    if edit["job"] == job_id for item in edit["files"]]
        credits = [(edit_id, edit["index"]) for edit_id, edit in edits.items()
                   if edit["job"] == job_id and edit.get("credits")]
        notes = [(index, sorted(entries, key=lambda item: item["time"]))
                 for (source_job, index), entries in review_notes.items() if source_job == job_id and entries]
    root = workspace / job_id
    archive = SpooledTemporaryFile(max_size=8 * 1024**2)
    with ZipFile(archive, "w", compression=ZIP_STORED) as bundle:
        for filename in originals:
            bundle.write(root / filename, filename)
        for edit_id, index, filename in variants:
            bundle.write(root / edit_id / filename, f"clip-{index}/{edit_id[:8]}-{filename}")
        for edit_id, index in credits:
            bundle.write(root / edit_id / "credits.txt", f"clip-{index}/{edit_id[:8]}-credits.txt")
        for index, entries in notes:
            bundle.writestr(f"clip-{index}/review-notes.json", json.dumps({"notes": entries}, ensure_ascii=False))
    archive.seek(0)
    return send_file(archive, mimetype="application/zip", download_name="shortlist-exports.zip", as_attachment=True)


@app.post("/jobs/<job_id>/batch")
def create_batch(job_id):
    data = request.get_json(silent=True)
    formats = data.get("formats") if isinstance(data, dict) else None
    if not isinstance(formats, list) or not formats or any(
            not isinstance(shape, str) or shape not in {"vertical", "square", "wide"} for shape in formats):
        return jsonify(error="Choose at least one export format."), 400
    formats = tuple(dict.fromkeys(formats))
    with lock:
        job = jobs.get(job_id)
        if not job:
            abort(404)
        if job["status"] not in {"complete", "error"}:
            return jsonify(error="Wait for the original export to finish."), 409
        entries = [(index, project) for (project_job, index), project in projects.items() if project_job == job_id]
    if not entries:
        return jsonify(error="No editable clips are available."), 400
    urls = []
    for index, (source, clip, stream) in entries:
        edit_id = uuid4().hex
        directory = workspace / job_id / edit_id
        directory.mkdir()
        options = ExportOptions(formats=formats, framing="fit" if stream else "smart")
        with lock:
            edits[edit_id] = {"job": job_id, "index": index, "status": "queued", "files": [], "message": "Queued for export."}
            persist(job_id)
        worker.submit(render_edit, edit_id, job_id, source, clip, options, None, directory)
        urls.append(f"/jobs/{job_id}/edits/{edit_id}")
    return jsonify(polls=urls), 202


app.register_blueprint(review_pages)


def review_service():
    service = Flask("shortlist_review", template_folder=app.template_folder, static_folder=app.static_folder,
                    root_path=app.root_path)
    service.config["MAX_CONTENT_LENGTH"] = 600000
    service.register_blueprint(review_pages)
    return service


if __name__ == "__main__":
    if os.environ.get("SHORTLIST_REVIEW_BIND"):
        from werkzeug.serving import make_server

        listener = make_server(os.environ["SHORTLIST_REVIEW_BIND"],
                               int(os.environ.get("SHORTLIST_REVIEW_PORT", "5051")), review_service(), threaded=True)
        Thread(target=listener.serve_forever, daemon=True).start()
    app.run(host="127.0.0.1", port=5050)
