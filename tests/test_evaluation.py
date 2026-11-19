import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import app
from app import gameplay_rank
from clipping import Clip, rank_gameplay, same_gameplay_moment
from evaluation import score
from vision import visual_headline


class EvaluationTest(unittest.TestCase):
    def test_separates_coverage_detection_and_ranking_misses(self):
        labels = {"sources": {"sample": [
            {"start": time, "end": time + 2, "category": "crash"} for time in (0, 20, 40, 60)
        ]}}
        job = {
            "video_id": "sample",
            "coverage": [[0, 35], [30, 45]],
            "candidates_found": [{"start": 0, "end": 8}, {"start": 20, "end": 28}],
            "clips": [{"start": 0, "end": 8}],
        }
        result = score(labels, job)
        self.assertEqual(result["coverage_seconds"], 45)
        self.assertEqual([entry["outcome"] for entry in result["events"]], [
            "exported", "candidate_not_exported", "scanned_not_detected", "outside_scan",
        ])

    def test_visual_action_claim_needs_spoken_support(self):
        description = "A motorcycle jumps off a ramp."
        self.assertEqual(visual_headline(description), ("", 0))
        self.assertEqual(visual_headline(description, "I just jumped off the ramp.")[0], "The bike goes airborne")
        self.assertEqual(visual_headline("A biker rides a motorcycle down a dirt road.")[0],
                         "Motorcycle ride on a dirt road")
        self.assertEqual(visual_headline("The police van turns sideways on the bridge.")[0],
                         "The police van turns sideways on the bridge")
        self.assertEqual(visual_headline("A police car pulls alongside the sedan at the intersection.")[0],
                         "A police car pulls alongside at the intersection")
        self.assertEqual(visual_headline("The player is driving on a highway with a police van driving by.")[0],
                         "A police van passes on the highway")

    def test_generic_and_duplicate_titles_do_not_get_burned_into_video(self):
        title = "The police van turns sideways on the bridge"
        first = Clip(10, 30, title, "", ())
        second = Clip(40, 60, title, "", (), event_time=49)
        generic = Clip(80, 100, "The pace picks up", "", ())
        result = app.gameplay_titles([(Path("sample"), 0, clip) for clip in (first, second, generic)])
        self.assertEqual([(clip.title, clip.hook) for _, _, clip in result], [
            (title, title), ("Gameplay at 0:49", ""), ("Gameplay at 1:20", ""),
        ])

    def test_verified_change_outranks_generic_and_unchanged_hud(self):
        source = Path("sample")
        ordinary = Clip(0, 20, "The action picks up", "", (), score=5)
        steady = Clip(22, 42, "On two wheels", "", (), score=4, hud={"before": 5, "after": 5})
        verified = Clip(44, 64, "Drops from 5/14 to 6/14", "", (), score=1, hud={"before": 5, "after": 6})
        matches = [(source, 0, clip) for clip in (ordinary, steady, verified)]
        self.assertEqual([match[2] for match in sorted(matches, key=gameplay_rank, reverse=True)],
                         [verified, ordinary, steady])

    def test_same_title_does_not_drop_distinct_footage(self):
        title = "The action picks up"
        candidates = [(Clip(0, 20, title, "", ()), None), (Clip(80, 101, title, "", ()), None)]
        job_id = "test-distinct-footage"
        app.update(job_id, status="queued", clips=[])
        self.addCleanup(app.jobs.pop, job_id, None)
        with TemporaryDirectory() as folder:
            source = Path(folder) / "source"
            source.touch()
            with (patch("app.gameplay_signals", return_value=([], [], [], [])),
                  patch("app.analyze", return_value=candidates),
                  patch("app.render", side_effect=["clip-1.mp4", "clip-2.mp4"])):
                app.process(job_id, source, True, "en", "", visual_ai=False)
        self.assertEqual(app.jobs[job_id]["status"], "complete")
        self.assertEqual([item["start"] for item in app.jobs[job_id]["clips"]], [0, 80])

    def test_sustained_motion_can_surface_separate_quiet_action(self):
        picks = rank_gameplay([], [(78, 1)], [(78, 1)], 120, sustained=[(65, 1)])
        self.assertEqual([clip.event_time for clip in picks], [78, 65])
        self.assertFalse(same_gameplay_moment(*picks))
        self.assertTrue(same_gameplay_moment(picks[0], picks[0]))
        self.assertIn("motion stayed elevated", picks[1].reason)
