import unittest

from clipping import Clip, Segment, caption_cues
from editor import parse_edit


class EditorTest(unittest.TestCase):
    def setUp(self):
        self.clip = Clip(20, 29, "Title", "", (
            Segment(20, 22, "First caption"),
            Segment(22, 24, "Remove this"),
            Segment(25, 29, "Bridge ahead"),
        ), hook="Title")

    def test_passage_cut_retimes_caption_and_keyword(self):
        edited, export = parse_edit(self.clip, {
            "start": 1, "end": 9, "omit": [1], "broll_keyword": "bridge",
            "captions": ["Corrected", "Remove this", "Bridge ahead"],
            "formats": ["vertical", "square", "wide"],
        })
        self.assertEqual(export.kept_ranges, ((21, 22), (24, 29)))
        self.assertEqual((edited.start, edited.end), (0, 6))
        self.assertEqual(caption_cues(edited), [(0, 1, "Corrected"), (2, 6, "Bridge ahead")])
        self.assertEqual(export.broll_start, 2)
        self.assertEqual(export.formats, ("vertical", "square", "wide"))

    def test_caption_edit_preserves_original_media_time_without_cuts(self):
        edited, export = parse_edit(self.clip, {"start": 2, "end": 8})
        self.assertEqual((edited.start, edited.end), (22, 28))
        self.assertEqual(export.kept_ranges, ())
        self.assertEqual(caption_cues(edited), [(22, 24, "Remove this"), (25, 28, "Bridge ahead")])

    def test_bad_editor_input_rejected(self):
        for payload in ({"end": 0}, {"formats": []}, {"omit": [3]}, {"volume": "nan"}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                parse_edit(self.clip, payload)
