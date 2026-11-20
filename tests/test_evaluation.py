import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

import numpy as np

import app
from app import gameplay_rank
from clipping import Clip, rank_gameplay, same_gameplay_moment
from evaluation import score
from vision import event_frames, review_event, visual_headline


class EvaluationTest(unittest.TestCase):
    def test_shortlist_keeps_audience_and_sustained_windows_over_motion_only(self):
        overall = [(8, None, 0, None, None), (7, None, 60, None, None), (6, None, 120, None, None)]
        audience = [(2, None, 180, None, None)]
        sustained = [(1, None, 240, None, None)]
        selected = app.choose_scout_windows(overall, audience, sustained, 3)
        self.assertEqual([window[2] for window in selected], [180, 240, 0])
        self.assertEqual(len(app.choose_scout_windows(overall, overall[:1], overall[:1], 3)), 3)

    def test_evaluation_distinguishes_scouted_and_analyzed_intervals(self):
        labels = {"sources": {"sample": [
            {"start": 10, "end": 12, "category": "pursuit"},
            {"start": 30, "end": 32, "category": "pursuit"},
        ]}}
        job = {"video_id": "sample", "coverage": [[0, 40]], "analyzed_coverage": [[20, 40]], "clips": []}
        result = score(labels, job)
        self.assertEqual([event["outcome"] for event in result["events"]],
                         ["scanned_not_shortlisted", "scanned_not_detected"])

    def test_scene_cut_filter_distinguishes_shot_change_and_movement(self):
        frames = np.zeros((12, 8, 8), dtype=np.uint8)
        frames[5:, :, :4] = 180
        frames[8:, :, :4] = 0
        frames[8:, :, 2:6] = 180
        change = (np.abs(np.diff(frames.astype(np.int16), axis=0)) > 22).mean(axis=(1, 2))
        cuts = app.adaptive_scene_cuts(frames, change, fps=3)
        self.assertEqual(np.flatnonzero(cuts).tolist(), [4])

    def test_replay_resume_reuses_validated_media_and_ranks_it_with_new_windows(self):
        video_id = "qSyo5d-dVzA"
        previous_id, current_id = "a" * 32, "b" * 32
        initial = {"video_id": video_id, "status": "scanning", "source_seconds": 120,
                   "scan_depth": "fast", "scan_plan": [[0, 20], [30, 20]],
                   "scan_checkpoint": [[0, "youtube.mkv", 0]], "scan_started_at": 1}
        with TemporaryDirectory() as temporary, patch("app.workspace", Path(temporary)), patch.dict(
            app.jobs, {previous_id: initial}, clear=True
        ), patch.dict(app.projects, clear=True):
            previous_folder = app.workspace / previous_id / "replay-scan" / "window-0"
            previous_folder.mkdir(parents=True)
            (previous_folder / "youtube.mkv").write_bytes(b"saved media")
            app.persist(previous_id)
            reopened_jobs, _, _, _ = app.load_projects(app.workspace, app.app.logger)
            app.jobs.update(reopened_jobs)
            self.assertEqual(app.jobs[previous_id]["status"], "error")
            output = app.workspace / current_id
            output.mkdir()
            app.update(current_id, video_id=video_id, status="queued", clips=[])

            def download(_video, folder, start, _size, _prepared):
                media = folder / "youtube.mkv"
                media.write_bytes(b"fresh media")
                return media, start

            def analyze(source, *_args, **_kwargs):
                saved = source.read_bytes() == b"saved media"
                clip = Clip(0, 15, "Saved highlight" if saved else "Fresh highlight", "", (), score=2 if saved else 1)
                return [(clip, np.full((15, 2, 2), 0 if saved else 100))]

            metadata = Mock(stdout=json.dumps({"duration": 120, "live_status": "was_live"}))
            signals = (np.zeros(20 * 16000), [], [], [], np.zeros((20, 2, 2)))
            with patch("app.subprocess.run", return_value=metadata), patch("app.import_scout_window", side_effect=download) as fetch, patch(
                "app.gameplay_signals", return_value=signals
            ), patch("app.analyze", side_effect=analyze), patch("app.render", return_value="clip.mp4"):
                app.process(current_id, output / "source", True, "en", "", video_id=video_id, depth="fast", visual_ai=False)
            self.assertEqual(fetch.call_count, 1)
            self.assertEqual(fetch.call_args.args[2], 30)
            result = app.jobs[current_id]
            self.assertEqual(result["status"], "complete")
            self.assertEqual(result["reused_windows"], 1)
            self.assertEqual([clip["title"] for clip in result["clips"]], ["Saved highlight", "Fresh highlight"])
            self.assertFalse(previous_folder.exists())

    def test_position_change_requires_matching_export_evidence(self):
        label = {"start": 10, "end": 12, "category": "position_change",
                 "hud": {"before": 5, "after": 6, "entrants": 14}}
        clip = {"start": 0, "end": 20, "hud": {"before": 6, "after": 5, "entrants": 14}}
        labels = {"sources": {"bike": [label]}}
        job = {"video_id": "bike", "clips": [clip]}
        self.assertEqual(score(labels, job)["events"][0]["outcome"], "exported_without_matching_hud")
        clip["hud"] = label["hud"]
        self.assertEqual(score(labels, job)["labeled_moments_exported"], 1)

    def test_repeated_deep_scan_prioritizes_unseen_footage(self):
        first = app.replay_windows(85_542, [], "deep")
        coverage = [(start, start + size) for start, size in first]
        second = app.replay_windows(85_542, [], "deep", coverage)
        self.assertEqual(sum(size for _, size in second), 48 * 60)
        self.assertTrue(all(start + size <= left or start >= right
                            for start, size in second for left, right in coverage))

    def test_wide_scan_covers_audience_neighborhood_and_keeps_windows_disjoint(self):
        windows = app.replay_windows(85_542, [], "wide", reactions=[(12_000, 1, "comments")])
        self.assertEqual(sum(size for _, size in windows), 120 * 60)
        for time in (11_880, 12_000, 12_120):
            self.assertTrue(any(start <= time < start + size for start, size in windows))
        self.assertTrue(all(start + size <= following for (start, size), (following, _) in zip(windows, windows[1:])))

    def test_direct_review_checks_hud_at_model_payoff_and_preserves_context(self):
        clip = Clip(0, 45, "", "Direct review.", ())
        hud = {"before": 5, "after": 6, "entrants": 14}
        with patch("app.update"), patch("app.inspect_hud", side_effect=[None, hud]) as inspect, patch(
            "app.review_cloud_clip", return_value=("The bike wobbles", 1, "The rider stays upright.", 20)
        ):
            _, _, reviewed = app.review_gameplay("test", [(Path("bike.mp4"), 50422, clip)], provider="cloud")[0]
        self.assertEqual(inspect.call_args.args[-1], 20)
        self.assertEqual((reviewed.start, reviewed.event_time, reviewed.end), (6, 20, 34))
        self.assertEqual(reviewed.title, "Drops from 5/14 to 6/14")

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

    def test_detail_frames_bracket_event_without_leaving_clip(self):
        self.assertEqual(event_frames(40, 60, 48, detail=True), [12, 14, 16, 18, 20])
        self.assertEqual(event_frames(40, 60, 40, detail=True), [0, 1, 3, 5])

    def test_second_pass_promotes_observed_maneuver_but_needs_support_for_fall(self):
        with patch("vision.describe", side_effect=[
            "A police van drives on a bridge.",
            "The police van turns sideways on the bridge.",
        ]) as describe:
            title, score, evidence = review_event(Path("clip.mp4"), 0, 18, 9, "")
        self.assertEqual(title, "The police van turns sideways on the bridge")
        self.assertGreater(score, .85)
        self.assertIn("Close look:", evidence)
        self.assertTrue(describe.call_args.kwargs["detail"])
        with patch("vision.describe", side_effect=[
            "A rider drives a bike.", "The rider falls off the bike.",
        ]):
            title, _, _ = review_event(Path("clip.mp4"), 0, 18, 9, "")
        self.assertEqual(title, "On two wheels")

    def test_conflicting_movement_descriptions_suppress_passing_title(self):
        with patch("vision.describe", side_effect=[
            "The player is driving on a highway with a police van driving by.",
            "The player's vehicle is moving forward, and the van is stationary.",
        ]):
            title, score, evidence = review_event(Path("clip.mp4"), 0, 18, 9, "")
        self.assertEqual((title, score), ("", 0))
        self.assertIn("stationary", evidence)
