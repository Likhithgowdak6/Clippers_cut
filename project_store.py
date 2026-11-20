"""Persist Shortlist's local project metadata beside its media files."""

import json
from dataclasses import asdict

from clipping import Clip, Segment


def save_project(root, job_id, job, projects, edits, notes):
    directory = root / job_id
    if not directory.is_dir():
        return
    data = {
        "job": job,
        "clips": {index: {"source": source.relative_to(directory).as_posix(), "clip": asdict(clip), "stream": stream}
                  for (key, index), (source, clip, stream) in projects.items() if key == job_id},
        "edits": {key: edit for key, edit in edits.items() if edit["job"] == job_id},
        "notes": {index: entries for (key, index), entries in notes.items() if key == job_id},
    }
    pending = directory / "project.tmp"
    pending.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    pending.replace(directory / "project.json")


def load_projects(root, logger):
    jobs, projects, edits, notes = {}, {}, {}, {}
    for manifest in root.glob("*/project.json"):
        job_id = manifest.parent.name
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            job = data["job"]
            if job["status"] not in {"complete", "error"}:
                job.update(status="error", message="The server restarted before the job finished.")
            publishing = job.get("publishing")
            if publishing and publishing.get("status") in {"queued", "uploading"}:
                publishing.update(status="error", message="The server restarted before YouTube confirmed the upload. Check YouTube Studio.")
            current = {}
            for index, record in data["clips"].items():
                source = (manifest.parent / record["source"]).resolve()
                if not source.is_relative_to(manifest.parent.resolve()) or not source.is_file():
                    continue
                fields = record["clip"]
                fields["segments"] = tuple(
                    Segment(item["start"], item["end"], item["text"], tuple(tuple(word) for word in item["words"]))
                    for item in fields["segments"]
                )
                current[job_id, int(index)] = source, Clip(**fields), record["stream"]
            for edit in data["edits"].values():
                if edit["status"] not in {"complete", "error"}:
                    edit.update(status="error", message="The server restarted before this export finished.")
            restored_notes = {(job_id, int(index)): entries for index, entries in data["notes"].items()}
        except (ValueError, TypeError, KeyError, OSError):
            logger.warning("Could not restore project %s", job_id, exc_info=True)
            continue
        jobs[job_id] = job
        projects.update(current)
        edits.update(data["edits"])
        notes.update(restored_notes)
    return jobs, projects, edits, notes
