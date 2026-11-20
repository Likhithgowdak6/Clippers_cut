import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

import app
import youtube_publish


class YouTubePublishTest(unittest.TestCase):
    settings = ("test-client", "test-secret", "http://127.0.0.1:5052/youtube/callback")
    clip = {"title": "Race highlight", "start": 20, "end": 40}

    def test_starts_a_private_upload_and_deduplicates(self):
        with TemporaryDirectory() as scratch, patch("youtube_publish.exchange", return_value={"access_token": "test"}), patch(
            "youtube_publish.requests.post"
        ) as start, patch("youtube_publish.requests.put") as transfer:
            root = Path(scratch)
            (root / ".youtube-connection.json").write_text(json.dumps(
                {"client_id": "test-client", "channel_id": "channel", "refresh_token": "test", "title": "Channel"}
            ), encoding="utf-8")
            source = root / "clip-1.mp4"
            source.write_bytes(b"test file")
            start.return_value.headers = {"Location": "https://www.googleapis.com/upload/youtube/v3/videos?upload_id=test"}
            transfer.return_value = Mock(status_code=201)
            transfer.return_value.json.return_value = {"id": "abcdefghijk"}
            args = root, self.settings, "channel", source, self.clip, "qSyo5d-dVzA"
            self.assertEqual(youtube_publish.upload_private(*args), ("abcdefghijk", False))
            self.assertEqual(start.call_args.kwargs["json"]["status"]["privacyStatus"], "private")
            self.assertEqual(youtube_publish.upload_private(*args), ("abcdefghijk", True))
            transfer.assert_called_once()

    def test_unconfirmed_transfer_does_not_upload_twice(self):
        with TemporaryDirectory() as scratch, patch("youtube_publish.exchange", return_value={"access_token": "test"}), patch(
            "youtube_publish.requests.post"
        ) as start, patch("youtube_publish.requests.put", return_value=Mock(status_code=503)) as transfer:
            root = Path(scratch)
            (root / ".youtube-connection.json").write_text(json.dumps(
                {"client_id": "test-client", "channel_id": "channel", "refresh_token": "test", "title": "Channel"}
            ), encoding="utf-8")
            source = root / "clip-1.mp4"
            source.write_bytes(b"test file")
            start.return_value.headers = {"Location": "https://www.googleapis.com/upload/youtube/v3/videos?upload_id=test"}
            args = root, self.settings, "channel", source, self.clip, "qSyo5d-dVzA"
            with self.assertRaises(ValueError):
                youtube_publish.upload_private(*args)
            with self.assertRaisesRegex(ValueError, "unconfirmed"):
                youtube_publish.upload_private(*args)
            transfer.assert_called_once()

    def test_oauth_state_is_used_once_and_cross_origin_upload_is_rejected(self):
        base = "http://127.0.0.1:5052"
        with patch("app.youtube_publish.config", return_value=self.settings), patch("app.youtube_publish.connect") as connect:
            with app.app.test_client() as client:
                response = client.get("/youtube/connect", base_url=base)
                state = parse_qs(urlsplit(response.location).query)["state"][0]
                response = client.get(f"/youtube/callback?state={state}&code=test", base_url=base)
                self.assertEqual(response.status_code, 303)
                self.assertEqual(client.get(f"/youtube/callback?state={state}&code=test", base_url=base).status_code, 400)
                connect.assert_called_once()
                response = client.post("/jobs", base_url=base, headers={"Origin": "https://other.example"},
                                       data={"youtube": "https://www.youtube.com/watch?v=qSyo5d-dVzA", "upload_youtube": "on"})
                self.assertEqual(response.status_code, 403)
