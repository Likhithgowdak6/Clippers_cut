"""Import a bounded window from YouTube's public post-live DASH fragments."""

import math
import subprocess
import sys
from itertools import islice
from pathlib import Path

import imageio_ffmpeg
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError


OPTIONS = {
    "quiet": True,
    "noprogress": True,
    "js_runtimes": {"node": {}},
    "format": "bv[height<=720]+ba",
    "socket_timeout": 10,
    "fragment_retries": 1,
    "skip_unavailable_fragments": False,
    "concurrent_fragment_downloads": 8,
}


def prepare_replay(video_id, windows, *, shift_tail=False):
    with YoutubeDL(OPTIONS) as client:
        info = client.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
        formats = info.get("requested_formats", [])
        if info.get("live_status") != "post_live" or len(formats) != 2:
            raise ValueError("Replay fragments are unavailable.")
        step = formats[0].get("target_duration")
        if not step or formats[1].get("target_duration") != step:
            raise ValueError("Replay tracks do not share a fragment duration.")
        available = None
        if shift_tail:
            counts = [next(iter(media["fragments"]), {}).get("fragment_count") for media in formats]
            if all(counts):
                available = min(counts)
        prepared = {}
        for start, length in sorted(windows):
            first = int(start // step)
            count = math.ceil(length / step)
            if available is not None:
                first = min(first, max(0, available - count))
            stop = first + count
            tracks = [
                {**media, "fragments": [{"url": item["url"]} for item in islice(media["fragments"], first, stop)]}
                for media in formats
            ]
            if all(track["fragments"] for track in tracks):
                prepared[start] = (first * step, tracks)
        return prepared


def download_replay_window(prepared, directory):
    offset, formats = prepared
    tracks = []
    source = directory / "youtube.mkv"
    try:
        with YoutubeDL(OPTIONS) as client:
            for index, media in enumerate(formats):
                track = directory / f"youtube.track{index}.{media['ext']}"
                tracks.append(track)
                ok, _ = client.dl(str(track), media)
                if not ok:
                    raise ValueError("Replay fragment download failed.")
    except DownloadError as error:
        raise ValueError("Replay fragment download failed.") from error
    try:
        subprocess.run(
            [imageio_ffmpeg.get_ffmpeg_exe(), "-nostdin", "-v", "error",
             "-i", str(tracks[0]), "-i", str(tracks[1]), "-map", "0:v:0", "-map", "1:a:0",
             "-c", "copy", "-shortest", "-y", str(source)],
            check=True, capture_output=True, timeout=30,
        )
    finally:
        for track in tracks:
            track.unlink(missing_ok=True)
    return source, offset


def import_replay(video_id, start, length):
    prepared = prepare_replay(video_id, [(start, length)]).get(start)
    if not prepared:
        raise ValueError("No replay fragments at the selected time.")
    return download_replay_window(prepared, Path.cwd())[1]


if __name__ == "__main__":
    print(f"REPLAY_START={import_replay(sys.argv[1], int(sys.argv[2]), int(sys.argv[3]))}")
