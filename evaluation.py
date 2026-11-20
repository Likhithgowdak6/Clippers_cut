"""Score a Shortlist job manifest against timestamped gameplay labels."""

import argparse
import json
from pathlib import Path


def covers(interval, time):
    return interval[0] <= time < interval[1]


def covered_seconds(intervals):
    total, end = 0, 0
    for start, stop in sorted(intervals):
        if stop > end:
            total += stop - max(end, start)
            end = stop
    return round(total, 2)


def score(labels, job):
    source = job.get("video_id")
    if source not in labels["sources"]:
        raise ValueError(f"No labels for YouTube video {source!r}.")
    coverage = job.get("coverage") or []
    analyzed = job.get("analyzed_coverage")
    candidates = [(clip["start"], clip["end"]) for clip in job.get("candidates_found") or []]
    exports = job["clips"][:5]
    picks = [(clip["start"], clip["end"]) for clip in exports]
    events = []
    ordinary = []
    for label in labels["sources"][source]:
        anchor = (label["start"] + label["end"]) / 2
        if label["category"] == "ordinary":
            ordinary.append(anchor)
            continue
        matching_exports = [clip for clip, interval in zip(exports, picks) if covers(interval, anchor)]
        if matching_exports:
            expected = label.get("hud", {})
            outcome = "exported" if any(
                all((clip.get("hud") or {}).get(key) == value for key, value in expected.items())
                for clip in matching_exports
            ) else "exported_without_matching_hud"
        elif any(covers(interval, anchor) for interval in candidates):
            outcome = "candidate_not_exported"
        elif any(covers(interval, anchor) for interval in coverage):
            outcome = "scanned_not_shortlisted" if analyzed is not None and not any(
                covers(interval, anchor) for interval in analyzed
            ) else "scanned_not_detected"
        else:
            outcome = "outside_scan"
        events.append({**label, "outcome": outcome})
    event_times = [(item["start"] + item["end"]) / 2 for item in events]
    scanned = covered_seconds(coverage)
    duration = job.get("source_seconds")
    return {
        "video_id": source,
        "coverage_seconds": scanned,
        "coverage_percent": round(100 * scanned / duration, 3) if duration else None,
        "first_clip_seconds": job.get("first_clip_seconds"),
        "first_preview_seconds": job.get("first_preview_seconds"),
        "exported_clips": len(picks),
        "labeled_moments": len(events),
        "labeled_moments_exported": sum(event["outcome"] == "exported" for event in events),
        "exports_touching_only_ordinary_labels": sum(
            any(covers(pick, time) for time in ordinary) and not any(covers(pick, time) for time in event_times)
            for pick in picks
        ),
        "events": events,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("labels", type=Path)
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    try:
        report = score(
            json.loads(args.labels.read_text(encoding="utf-8")),
            json.loads(args.manifest.read_text(encoding="utf-8")),
        )
    except (ValueError, OSError, KeyError) as error:
        parser.error(str(error))
    print(json.dumps(report, indent=2))
