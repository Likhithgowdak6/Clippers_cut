import json
import unittest
from pathlib import Path
from unittest.mock import patch

import app
import numpy as np
from audience import chat_peaks, comment_peaks
from clipping import Clip


class AudienceTest(unittest.TestCase):
    def test_audience_support_ranks_above_motion_but_below_confirmed_hud(self):
        motion = Clip(0, 20, "", "", (), score=10)
        audience = Clip(20, 40, "", "", (), audience={"time": 30, "count": 5, "channel": "comments"})
        hud = Clip(40, 60, "", "", (), hud={"before": 5, "after": 6, "entrants": 14})
        picks = sorted([(None, 0, clip) for clip in (motion, audience, hud)], key=app.gameplay_rank, reverse=True)
        self.assertEqual([pick[2] for pick in picks], [hud, audience, motion])

    def test_comment_offsets_and_unique_viewers(self):
        comments = [
            {"author_id": "one", "text": "14:03:06 was wild. 14:03:07!"},
            {"author_id": "one", "text": "14:03:07 again"},
            {"author_id": "two", "text": "look at 843:06"},
            {"author_id": "three", "text": "Funny, posted yesterday"},
        ]
        self.assertEqual(comment_peaks(comments, 85542), [(50586, 2, "comments")])

    def test_chat_burst_uses_replay_offsets_and_ignores_repeat_spam(self):
        def message(author):
            return json.dumps({"replayChatItemAction": {
                "videoOffsetTimeMsec": "312000",
                "actions": [{"addChatItemAction": {"item": {"liveChatTextMessageRenderer": {
                    "authorExternalChannelId": author,
                }}}}],
            }})

        self.assertEqual(chat_peaks(map(message, ["one"] * 10), 800), [])
        self.assertEqual(chat_peaks(map(message, ["one", "two", "three"]), 800), [(311, 3, "chat")])

    def test_reaction_places_a_scan_window_and_can_surface_a_clip(self):
        windows = app.replay_windows(85542, None, "fast", reactions=[(50586, 4, "comments")])
        self.assertEqual(len(windows), 4)
        self.assertTrue(any(start <= 50586 < start + size for start, size in windows))
        signals = (np.zeros(40 * 16000), [], [], [], np.zeros((40, 2, 2)))
        with patch("app.transcribe", return_value=[]), patch("app.scan_hud_changes", return_value=[]):
            matches = app.analyze(Path("replay.mkv"), "en", True, signals=signals, audience_time=20)
        self.assertEqual(len(matches), 1)
        self.assertEqual((matches[0][0].start, matches[0][0].end), (12, 33))
