"""Read stable race placements from a lower-right gameplay HUD."""

import re
import subprocess
from collections import Counter
from functools import lru_cache

import imageio_ffmpeg
import numpy as np


PLACEMENT = re.compile(r"^(?:(?:POS(?:ITION)?)[.: ]*)?(\d{1,2})\s*/\s*(\d{1,2})$", re.I)
RACE_CONTEXT = re.compile(r"\b(?:LAP|POS(?:ITION)?|RACE)\b", re.I)
PLAYER_DNF = re.compile(r"\b(?:you did not finish(?: the race)?|you failed to finish the race)\b", re.I)


@lru_cache(maxsize=1)
def ocr_engine():
    from rapidocr_onnxruntime import RapidOCR

    return RapidOCR(intra_op_num_threads=2, inter_op_num_threads=1, use_cls=False)


def read_placement(lines):
    found = set()
    race = False
    for _, text, confidence in lines or ():
        if confidence < .75:
            continue
        race |= bool(RACE_CONTEXT.search(text))
        match = PLACEMENT.fullmatch(text.strip())
        if match:
            rank, total = map(int, match.groups())
            if 3 <= total <= 48 and 1 <= rank <= total:
                found.add((rank, total))
    return (next(iter(found)) if len(found) == 1 else None), race


def stable_placement(frames):
    readings = Counter(rank for rank, _ in frames if rank)
    if not readings or not any(race for _, race in frames):
        return None
    rank, count = readings.most_common(1)[0]
    return rank if count >= 2 else None


def inspect_hud(source, start, end, event_time):
    if event_time is None or event_time - start < 4 or end - event_time < 4:
        return None
    width, height = 576, 384
    # Three snapshots before and three after the event. Only the cropped HUD is decoded.
    origin = event_time - 4
    raw = subprocess.run(
        [imageio_ffmpeg.get_ffmpeg_exe(), "-nostdin", "-v", "error", "-ss", str(origin),
         "-i", str(source), "-t", "8.5", "-map", "0:v:0",
         "-vf", "fps=1,select='lte(n,2)+gte(n,6)',"
                f"crop=iw*0.24:ih*0.35:iw*0.76:ih*0.65,scale={width}:{height}",
         "-an", "-frames:v", "6", "-fps_mode", "vfr", "-c:v", "rawvideo", "-threads", "1",
         "-pix_fmt", "bgr24", "-f", "rawvideo", "pipe:1"],
        check=True, capture_output=True, timeout=30,
    ).stdout
    frames = np.frombuffer(raw, dtype=np.uint8).reshape(-1, height, width, 3)
    if len(frames) != 6:
        return None
    engine = ocr_engine()
    lines = [engine(frame, use_cls=False)[0] for frame in frames]
    return compare_placements(lines)


def compare_placements(lines):
    observations = [read_placement(frame) for frame in lines]
    before = stable_placement(observations[:3])
    after = stable_placement(observations[3:])
    if not before:
        return None
    if after and before[1] == after[1]:
        return {"before": before[0], "after": after[0], "entrants": before[1]}
    dnf_frames = sum(any(score >= .85 and PLAYER_DNF.search(text) for _, text, score in frame or ())
                     for frame in lines[3:])
    if not any(rank for rank, _ in observations[3:]) and dnf_frames >= 2:
        return {"before": before[0], "after": None, "entrants": before[1], "result": "did_not_finish"}
    return None
