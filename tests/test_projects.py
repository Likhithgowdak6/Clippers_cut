import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import app
from clipping import Clip, Segment
from project_store import load_projects, save_project


class ProjectTest(unittest.TestCase):
    def test_project_roundtrip_preserves_source_cues_and_notes(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            folder = root / "project"
            folder.mkdir()
            source = folder / "source"
            source.touch()
            clip = Clip(1, 8, "Title", "", (Segment(1, 2, "Hello", ((1, 2, "Hello"),)),))
            job = {"status": "complete", "clips": []}
            notes = {("project", 1): [{"time": 2, "text": "Review this"}]}
            save_project(root, "project", job, {("project", 1): (source, clip, False)}, {}, notes)
            jobs, projects, _, restored = load_projects(root, app.app.logger)
            self.assertEqual(jobs["project"], job)
            self.assertEqual(projects["project", 1], (source.resolve(), clip, False))
            self.assertEqual(restored, notes)

    def test_review_listener_cannot_edit_projects_and_links_are_revocable(self):
        clip = Clip(0, 8, "Title", "", (), hook="Title")
        with TemporaryDirectory() as temp:
            root = Path(temp)
            folder = root / "review"
            folder.mkdir()
            source = folder / "source"
            source.touch()
            jobs = {"review": {"status": "complete", "clips": []}}
            projects = {("review", 1): (source, clip, False)}
            with (patch.object(app, "workspace", root), patch.object(app, "jobs", jobs),
                  patch.object(app, "projects", projects), patch.object(app, "review_notes", {})):
                owner = app.app.test_client()
                reviewer = app.review_service().test_client()
                editor = "/jobs/review/editor/1"
                invite = owner.post(editor + "/share", json={}).json["url"]
                self.assertEqual(reviewer.get("/library").status_code, 404)
                self.assertEqual(reviewer.get(editor).status_code, 404)
                self.assertEqual(reviewer.get(invite).status_code, 200)
                self.assertEqual(reviewer.post(invite + "/notes", json={"time": 2, "text": "Great"}).status_code, 200)
                self.assertEqual(owner.get(editor + "/notes").json["notes"][0]["text"], "Great")
                self.assertEqual(owner.delete(editor + "/share", json={}).status_code, 200)
                self.assertEqual(reviewer.get(invite).status_code, 404)

    def test_recording_links_accept_only_supported_hosts_and_paths(self):
        self.assertEqual(app.recording_link("https://vimeo.com/123"),
                         ("Vimeo", "https://player.vimeo.com/video/123"))
        self.assertEqual(app.recording_link("https://us02web.zoom.us/rec/share/code")[0], "Zoom")
        for url in ("https://zoom.us.example.com/rec/share/code", "https://vimeo.com:8080/123",
                    "http://127.0.0.1/123", "https://zoom.us/profile"):
            self.assertIsNone(app.recording_link(url))
