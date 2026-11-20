"""Local channel authorization and private YouTube uploads."""

import json
import os
import re
import sqlite3
from contextlib import closing
from hashlib import file_digest, sha256
from tempfile import NamedTemporaryFile
from urllib.parse import urlencode, urlsplit

import requests

TOKEN_URL = "https://oauth2.googleapis.com/token"
API_URL = "https://www.googleapis.com"
SCOPE = "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly"


def config():
    client = os.getenv("SHORTLIST_YOUTUBE_CLIENT_ID", "").strip()
    secret = os.getenv("SHORTLIST_YOUTUBE_CLIENT_SECRET", "").strip()
    callback = os.getenv("SHORTLIST_YOUTUBE_CALLBACK", "http://127.0.0.1:5052/youtube/callback")
    try:
        url = urlsplit(callback)
    except ValueError:
        return None
    if client and secret and url.scheme == "http" and url.hostname in {"127.0.0.1", "localhost"} and (
        url.path == "/youtube/callback" and not any((url.username, url.password, url.query, url.fragment))
    ):
        return client, secret, callback
    return None


def authorization_url(settings, state):
    client, _, callback = settings
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode({
        "client_id": client, "redirect_uri": callback, "response_type": "code",
        "scope": SCOPE, "state": state, "access_type": "offline", "prompt": "consent select_account",
    })


def connection(directory):
    try:
        data = json.loads((directory / ".youtube-connection.json").read_text(encoding="utf-8"))
        return data if data["channel_id"] and data["refresh_token"] and data["client_id"] and data["title"] else None
    except (ValueError, KeyError, TypeError, OSError):
        return None


def exchange(settings, **payload):
    client, secret, _ = settings
    response = requests.post(TOKEN_URL, data={"client_id": client, "client_secret": secret, **payload},
                             timeout=20, allow_redirects=False)
    response.raise_for_status()
    return response.json()


def connect(directory, settings, code):
    token = exchange(settings, code=code, grant_type="authorization_code", redirect_uri=settings[2])
    response = requests.get(f"{API_URL}/youtube/v3/channels",
                            params={"part": "snippet", "mine": "true"},
                            headers={"Authorization": f"Bearer {token['access_token']}"},
                            timeout=20, allow_redirects=False)
    response.raise_for_status()
    channels = response.json().get("items", [])
    if len(channels) != 1 or not token.get("refresh_token"):
        raise ValueError("Choose a YouTube channel and allow offline access.")
    channel = channels[0]
    data = {"client_id": settings[0], "channel_id": channel["id"], "title": channel["snippet"]["title"],
            "refresh_token": token["refresh_token"]}
    with NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory, delete=False) as handle:
        json.dump(data, handle)
    pending = directory / os.path.basename(handle.name)
    try:
        pending.replace(directory / ".youtube-connection.json")
    finally:
        pending.unlink(missing_ok=True)


def upload_private(directory, settings, channel_id, source, clip, video_id):
    account = connection(directory)
    if not settings or not account or account["channel_id"] != channel_id or account["client_id"] != settings[0]:
        raise ValueError("Reconnect the YouTube channel selected for this job.")
    if not 0 < clip["end"] - clip["start"] <= 180:
        raise ValueError("The private upload must be no longer than three minutes.")
    if video_id:
        identity = f"{video_id}:{round(clip['start'])}:{round(clip['end'])}"
    else:
        with source.open("rb") as media:
            identity = file_digest(media, "sha256").hexdigest()
    key = sha256(f"{channel_id}:{identity}".encode()).hexdigest()
    with closing(sqlite3.connect(directory / ".youtube-uploads.sqlite3")) as ledger, ledger:
        ledger.execute("CREATE TABLE IF NOT EXISTS uploads (key TEXT PRIMARY KEY, video_id TEXT)")
        previous = ledger.execute("SELECT video_id FROM uploads WHERE key = ?", (key,)).fetchone()
        if previous:
            if previous[0]:
                return previous[0], True
            raise ValueError("An earlier upload has an unconfirmed result. Check YouTube Studio before trying again.")

        token = exchange(settings, grant_type="refresh_token", refresh_token=account["refresh_token"])
        headers = {"Authorization": f"Bearer {token['access_token']}"}
        size = source.stat().st_size
        title = " ".join(clip["title"].replace("<", "").replace(">", "").split())[:100] or "Shortlist highlight"
        description = "Edited with Shortlist Studio."
        if video_id:
            description += f"\n\nSource: https://www.youtube.com/watch?v={video_id}&t={int(clip['start'])}s"
        response = requests.post(f"{API_URL}/upload/youtube/v3/videos",
                                 params={"uploadType": "resumable", "part": "snippet,status"},
                                 headers={**headers, "X-Upload-Content-Length": str(size),
                                          "X-Upload-Content-Type": "video/mp4"},
                                 json={"snippet": {"title": title, "description": description, "categoryId": "22"},
                                       "status": {"privacyStatus": "private"}},
                                 timeout=25, allow_redirects=False)
        response.raise_for_status()
        upload_url = response.headers["Location"]
        parsed = urlsplit(upload_url)
        if parsed.scheme != "https" or parsed.netloc != "www.googleapis.com" or parsed.path != "/upload/youtube/v3/videos":
            raise ValueError("YouTube returned an unexpected upload session.")
        if not ledger.execute("INSERT OR IGNORE INTO uploads VALUES (?, NULL)", (key,)).rowcount:
            raise ValueError("An upload for this clip is already recorded.")
        ledger.commit()
        with source.open("rb") as media:
            response = requests.put(upload_url, headers={**headers, "Content-Length": str(size), "Content-Type": "video/mp4"},
                                    data=media, timeout=(15, 180), allow_redirects=False)
        if response.status_code not in (200, 201):
            raise ValueError("YouTube did not confirm the upload. Check YouTube Studio before trying again.")
        result = response.json()["id"]
        if not re.fullmatch(r"[A-Za-z0-9_-]{11}", result):
            raise ValueError("YouTube did not return a valid video ID. Check YouTube Studio.")
        ledger.execute("UPDATE uploads SET video_id = ? WHERE key = ?", (result, key))
        return result, False
