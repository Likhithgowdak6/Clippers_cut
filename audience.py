"""Extract aggregate reaction timestamps from public YouTube audience activity."""

import json
import re
import subprocess
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from itertools import islice


TIMESTAMP = re.compile(r"(?<![\w:/])(?:(\d{1,2}):)?(\d{1,3}):([0-5]\d)(?![\w:])")


def comment_peaks(comments, duration):
    votes = defaultdict(dict)
    for index, comment in enumerate(comments):
        if not isinstance(comment, dict):
            continue
        author = comment.get("author_id") or f"comment-{index}"
        for hours, minutes, seconds in TIMESTAMP.findall(comment.get("text") or ""):
            if hours and int(minutes) >= 60:
                continue
            time = 3600 * int(hours or 0) + 60 * int(minutes) + int(seconds)
            if 0 < time < duration:
                votes[time // 10].setdefault(author, time)
    return [(sorted(authors.values())[len(authors) // 2], len(authors), "comments") for authors in votes.values()]


def chat_peaks(lines, duration):
    viewers = defaultdict(set)
    for line in islice(lines, 100_000):
        try:
            action = json.loads(line)["replayChatItemAction"]
            time = int(action["videoOffsetTimeMsec"]) / 1000
        except (KeyError, TypeError, ValueError):
            continue
        if not 0 <= time < duration:
            continue
        for item in action.get("actions", []):
            message = item.get("addChatItemAction", {}).get("item", {})
            for kind in ("liveChatTextMessageRenderer", "liveChatPaidMessageRenderer"):
                renderer = message.get(kind, {})
                if renderer.get("authorExternalChannelId"):
                    viewers[int(time) // 10].add(renderer["authorExternalChannelId"])
    counts = {bucket: len(authors) for bucket, authors in viewers.items()}
    return [
        (bucket * 10 + 1, count, "chat")
        for bucket, count in counts.items()
        if count >= 3 and count >= 1.5 * sum(
            counts.get(neighbor, 0) for neighbor in range(bucket - 3, bucket + 4) if neighbor != bucket
        ) / 6
    ]


def collect_reactions(video_id, duration, directory, has_chat):
    command = [sys.executable, "-m", "yt_dlp", "--ignore-config", "--no-playlist",
               "--js-runtimes", "node", "--socket-timeout", "8", "--skip-download",
               f"https://www.youtube.com/watch?v={video_id}"]

    def fetch(args):
        try:
            return subprocess.run(command + args, cwd=directory, capture_output=True, timeout=22).stdout
        except (subprocess.SubprocessError, OSError):
            return b""

    with ThreadPoolExecutor(max_workers=2) as pool:
        comments = pool.submit(fetch, ["--write-comments", "--extractor-args",
                                       "youtube:max_comments=120,120,0,0", "--dump-single-json"])
        if has_chat:
            pool.submit(fetch, ["--write-subs", "--sub-langs", "live_chat", "-o", "audience.%(ext)s"])
    try:
        points = comment_peaks(json.loads(comments.result()).get("comments") or [], duration)
    except ValueError:
        points = []
    for name in ("audience.live_chat.json", "audience.live_chat.json.part"):
        chat = directory / name
        if chat.is_file():
            with chat.open(encoding="utf-8", errors="replace") as lines:
                points.extend(chat_peaks(lines, duration))
            break
    return sorted(points, key=lambda point: (-min(point[1], 30) * (2 if point[2] == "comments" else 1), point[0]))
