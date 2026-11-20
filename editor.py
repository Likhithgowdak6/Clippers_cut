"""Validate edits and render platform formats from the original footage."""

import math
import re
import subprocess
from dataclasses import dataclass, replace
from functools import lru_cache

import imageio_ffmpeg
import numpy as np

from clipping import Segment, caption_cues, captions

FORMATS = {"vertical": (1080, 1920), "square": (1080, 1080), "wide": (1920, 1080)}


@dataclass(frozen=True)
class ExportOptions:
    formats: tuple = ("vertical",)
    framing: str = "smart"
    style: str = "bold"
    brand: str = ""
    color: str = "E3FF82"
    clean_audio: bool = False
    normalize: bool = False
    volume: float = 0
    broll_start: float = 0
    broll_duration: float = 3
    kept_ranges: tuple = ()


def parse_edit(clip, payload):
    def number(field, default, low, high):
        value = float(payload.get(field, default))
        if not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f"Invalid {field}.")
        return value

    duration = clip.end - clip.start
    start = number("start", 0, 0, duration)
    end = number("end", duration, 0, duration + .001)
    end = min(end, duration)
    if end - start < 1:
        raise ValueError("Keep at least one second of footage.")
    formats = tuple(dict.fromkeys(payload.get("formats", ["vertical"])))
    if not formats or any(name not in FORMATS for name in formats):
        raise ValueError("Choose at least one export format.")
    framing = payload.get("framing", "smart")
    style = payload.get("style", "bold")
    color = payload.get("color", "E3FF82").lstrip("#")
    headline = payload.get("headline", clip.hook).strip()
    brand = payload.get("brand", "").strip()
    if framing not in {"smart", "center", "fit"} or style not in {"bold", "minimal", "accent"}:
        raise ValueError("Choose a supported framing mode and caption style.")
    if not re.fullmatch(r"[0-9A-Fa-f]{6}", color) or len(headline) > 90 or len(brand) > 40:
        raise ValueError("Check the brand color and text lengths.")
    cues = caption_cues(clip)
    edits = payload.get("captions", [text for _, _, text in cues])
    if len(edits) != len(cues) or any(not isinstance(text, str) or len(text) > 200 for text in edits):
        raise ValueError("Each caption must have up to 200 characters.")
    absolute_start, absolute_end = clip.start + start, clip.start + end
    muted = payload.get("omit", [])
    if any(type(index) is not int or not 0 <= index < len(cues) for index in muted):
        raise ValueError("Invalid passage selection.")
    excluded = sorted((max(absolute_start, cues[index][0]), min(absolute_end, cues[index][1])) for index in set(muted))
    kept = []
    cursor = absolute_start
    for left, right in excluded:
        if right <= left or right <= cursor:
            continue
        if left > cursor:
            kept.append((cursor, left))
        cursor = right
    if cursor < absolute_end:
        kept.append((cursor, absolute_end))
    edited_duration = sum(b - a for a, b in kept)
    if edited_duration < 1:
        raise ValueError("Keep at least one second of footage.")
    has_cuts = kept != [(absolute_start, absolute_end)]
    segments = []
    for index, ((a, b, _), text) in enumerate(zip(cues, edits)):
        if index in muted or not text.strip():
            continue
        shift = 0
        for left, right in kept:
            low, high = max(a, left), min(b, right)
            if high > low:
                correction = shift - left if has_cuts else 0
                segments.append(Segment(low + correction, high + correction, text.strip()))
            shift += right - left
    base_time = 0 if has_cuts else absolute_start
    broll_start = number("broll_start", 0, 0, edited_duration)
    broll_duration = number("broll_duration", 3, .25, 20)
    keyword = payload.get("broll_keyword", "").strip().casefold()
    if keyword:
        match = next((segment for segment in segments if keyword in segment.text.casefold()), None)
        if match is None:
            raise ValueError("The B-roll keyword was not found in the retained captions.")
        broll_start = max(0, match.start - base_time)
    edited = replace(clip, start=base_time, end=base_time + edited_duration, hook=headline, segments=tuple(segments))
    options = ExportOptions(formats, framing, style, brand, color.upper(), bool(payload.get("clean_audio")),
                            bool(payload.get("normalize")), number("volume", 0, -18, 12),
                            broll_start, broll_duration, tuple(kept) if has_cuts else ())
    return edited, options


def join_passages(source, output, ranges):
    origin = ranges[0][0]
    filters = []
    for index, (start, end) in enumerate(ranges):
        bounds = f"start={start - origin:.6f}:end={end - origin:.6f}"
        filters.extend([f"[0:v]trim={bounds},setpts=PTS-STARTPTS[v{index}]",
                        f"[0:a]atrim={bounds},asetpts=PTS-STARTPTS[a{index}]"])
    inputs = "".join(f"[v{index}][a{index}]" for index in range(len(ranges)))
    filters.append(f"{inputs}concat=n={len(ranges)}:v=1:a=1[v][a]")
    subprocess.run(
        [imageio_ffmpeg.get_ffmpeg_exe(), "-nostdin", "-v", "error", "-ss", str(origin), "-i", str(source),
         "-t", str(sum(end - start for start, end in ranges)), "-filter_complex", ";".join(filters),
         "-map", "[v]", "-map", "[a]", "-c:v", "ffv1", "-level", "3", "-fps_mode", "passthrough",
         "-c:a", "pcm_f32le", "-f", "matroska", "-y", str(output)], check=True, capture_output=True, timeout=900,
    )
    return output


@lru_cache(maxsize=1)
def face_detector():
    import cv2

    return cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")


def face_commands(source, clip, directory):
    import cv2

    width, height, fps = 384, 216, 4
    data = subprocess.run(
        [imageio_ffmpeg.get_ffmpeg_exe(), "-nostdin", "-v", "error", "-ss", str(clip.start), "-i", str(source),
         "-t", str(clip.end - clip.start), "-an", "-vf", f"fps={fps},scale={width}:{height},format=gray",
         "-pix_fmt", "gray", "-threads", "1", "-c:v", "rawvideo", "-f", "rawvideo", "pipe:1"],
        check=True, capture_output=True, timeout=45,
    ).stdout
    frames = np.frombuffer(data, dtype=np.uint8).reshape(-1, height, width)
    detector = face_detector()
    center = None
    previous = None
    centers = []
    for index, frame in enumerate(frames):
        faces = detector.detectMultiScale(frame, scaleFactor=1.12, minNeighbors=5, minSize=(30, 30))
        if len(faces):
            def prominence(face):
                x, y, w, h = face
                mouth = np.s_[y + 2 * h // 3:y + h, x + w // 4:x + 3 * w // 4]
                activity = cv2.absdiff(frame[mouth], previous[mouth]).mean() if previous is not None else 0
                return w * h / 4500 + min(activity, 20) / 14

            x, y, w, h = max(faces, key=prominence)
            target = np.array([(x + w / 2) / width, (y + h * .65) / height])
            center = target if center is None else .7 * center + .3 * target
        if center is not None:
            centers.append((index / fps, *center))
        previous = frame
    if not centers:
        return "", "crop"
    commands = []
    for time, x, y in [(0, *centers[0][1:]), *centers]:
        commands.append(f"{time:.2f} crop@focus x clip(iw*{x:.5f}-ow/2\\,0\\,iw-ow),"
                        f"crop@focus y clip(ih*{y:.5f}-oh/2\\,0\\,ih-oh);")
    (directory / "focus.txt").write_text("\n".join(commands), encoding="utf-8")
    return "sendcmd=f=focus.txt,", "crop@focus"


def render_format(source, clip, output, options, shape, *, broll=None, tracking=None):
    width, height = FORMATS[shape]
    directory = output.parent
    subtitle = output.with_suffix(".ass")
    subtitle.write_text(captions(clip, width, height, options.style, options.brand, options.color), encoding="utf-8")
    dimensions = f"{width}:{height}"
    if options.framing == "fit":
        framing = (f"scale={dimensions}:flags=lanczos:force_original_aspect_ratio=decrease:force_divisible_by=2,"
                   f"pad={dimensions}:(ow-iw)/2:(oh-ih)/2:0x151515")
    else:
        send, crop = tracking or ("", "crop")
        framing = f"scale={dimensions}:flags=lanczos:force_original_aspect_ratio=increase:force_divisible_by=2,{send}{crop}={dimensions}"
    base = [imageio_ffmpeg.get_ffmpeg_exe(), "-nostdin", "-v", "error", "-ss", str(clip.start), "-i", str(source)]
    if broll:
        start, end = options.broll_start, options.broll_start + options.broll_duration
        loop = ["-f", "image2", "-loop", "1", "-framerate", "30"] if broll.suffix.lower() in {".jpg", ".jpeg", ".png"} else ["-stream_loop", "-1"]
        base.extend([*loop, "-i", str(broll), "-filter_complex",
                     f"[0:v]{framing},setsar=1[main];"
                     f"[1:v]scale={dimensions}:flags=lanczos:force_original_aspect_ratio=increase:force_divisible_by=2,"
                     f"crop={dimensions},setsar=1[cut];"
                     f"[main][cut]overlay=enable='between(t,{start:.3f},{end:.3f})',ass={subtitle.name}[video]",
                     "-map", "[video]"])
    else:
        base.extend(["-map", "0:v:0", "-vf", f"{framing},setsar=1,ass={subtitle.name}"])
    audio = []
    if options.clean_audio:
        audio.append("afftdn")
    if options.volume:
        audio.append(f"volume={options.volume}dB")
    if options.normalize:
        audio.append("loudnorm=I=-16:TP=-1.5:LRA=11")
    if audio:
        base.extend(["-af", ",".join(audio)])
    base.extend(["-map", "0:a:0", "-t", str(clip.end - clip.start), "-c:v", "libx264", "-preset", "medium",
                 "-crf", "17", "-profile:v", "high", "-pix_fmt", "yuv420p", "-fps_mode", "vfr",
                 "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-y", str(output)])
    subprocess.run(base, cwd=directory, capture_output=True, check=True, timeout=900)
    return output
