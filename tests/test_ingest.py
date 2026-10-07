import gzip
import json
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "ingest"))
sys.path.insert(0, str(ROOT / "src" / "synthetic"))

import generate_tidepool  # noqa: E402
import tidepool_export  # noqa: E402


def _write_export(tmp_path: Path, events: list[dict]) -> Path:
    path = tmp_path / "export.json"
    path.write_text(json.dumps(events))
    return path


def test_batch_matches_source(tmp_path):
    events = generate_tidepool.generate(days=2, seed=1)
    export = _write_export(tmp_path, events)

    batch_dir = tidepool_export.build_batch(export, tmp_path / "batches")
    manifest = json.loads((batch_dir / "manifest.json").read_text())

    with gzip.open(batch_dir / "events.ndjson.gz", "rt") as f:
        records = [json.loads(line) for line in f]
    assert manifest["row_count"] == len(records) == len(events)
    assert manifest["skipped_count"] == 0
    assert manifest["content_sha256"] == tidepool_export.sha256_file(batch_dir / "events.ndjson.gz")
    assert set(manifest["type_counts"]) == {
        "basal", "bolus", "cbg", "food", "smbg", "deviceEvent",
        "pumpSettings.basalSchedules", "pumpSettings.carbRatios",
        "pumpSettings.insulinSensitivities", "pumpSettings.bgTargets",
    }
    # Bronze keeps the source event unchanged
    assert json.loads(records[0]["event_json"]) == events[0]


def test_invalid_events_are_skipped_not_fatal(tmp_path):
    events = generate_tidepool.generate(days=1, seed=2)
    export = _write_export(tmp_path, events + [{"type": "cbg"}, "not-an-object"])

    manifest = json.loads((tidepool_export.build_batch(export, tmp_path / "b") / "manifest.json").read_text())
    assert manifest["row_count"] == len(events)
    assert manifest["skipped_count"] == 2


def test_rerun_is_idempotent(tmp_path, capsys):
    export = _write_export(tmp_path, generate_tidepool.generate(days=1, seed=3))
    out = tmp_path / "batches"

    tidepool_export.main([str(export), "--out-dir", str(out)])
    tidepool_export.main([str(export), "--out-dir", str(out)])
    assert len(list(out.iterdir())) == 1
    assert "already packaged" in capsys.readouterr().out


def test_synthetic_basal_duration_is_minutes():
    basal = [e for e in generate_tidepool.generate(days=1, seed=4) if e["type"] == "basal"]
    assert all(4.9 <= e["duration"] <= 5.1 for e in basal)


def _identity(record: dict) -> tuple:
    # Mirrors tidepool_events_current: (event_type, event_id, child_key), where
    # child_key splits exploded settings rows by schedule and segment start.
    event = json.loads(record["event_json"])
    child_key = ""
    if record["event_type"].startswith("pumpSettings."):
        start = next(v for k, v in event.items() if k.endswith(".start"))
        child_key = f'{event["scheduleName"]}|{start}'
    return record["event_type"], record["event_id"], child_key


def test_overlapping_exports_share_record_ids(tmp_path):
    # A later export covering a new time range overlaps the previous one. Both
    # batches land; the shared records carry the same id and identical content,
    # so silver's current-state upsert keeps one copy of each.
    history = generate_tidepool.generate(days=10, seed=5)
    start = generate_tidepool.DEFAULT_END - timedelta(days=10)
    first = generate_tidepool.export_window(history, start, start + timedelta(days=7))
    second = generate_tidepool.export_window(history, start + timedelta(days=4), start + timedelta(days=10))

    records = []
    for name, events in (("a", first), ("b", second)):
        (tmp_path / name).mkdir()
        batch_dir = tidepool_export.build_batch(_write_export(tmp_path / name, events), tmp_path / "batches")
        with gzip.open(batch_dir / "events.ndjson.gz", "rt") as f:
            records += [json.loads(line) for line in f]

    by_identity: dict[tuple, set] = {}
    for r in records:
        by_identity.setdefault(_identity(r), set()).add((r["batch_id"], r["record_sha256"]))
    overlap = [v for v in by_identity.values() if len({b for b, _ in v}) == 2]
    assert overlap, "windows should overlap"
    assert all(len({h for _, h in v}) == 1 for v in overlap), "overlapping records must have identical content"
    assert len(by_identity) == len(history)


def test_settings_snapshot_is_exploded_per_segment():
    events = generate_tidepool.generate(days=4, seed=6)
    basal_rows = [e for e in events if e["type"] == "pumpSettings.basalSchedules"]
    per_snapshot = {}
    for e in basal_rows:
        per_snapshot.setdefault(e["id"], []).append(e)
    assert len(per_snapshot) == 4  # one snapshot per day
    assert all(len(rows) == len(generate_tidepool.BASAL_SCHEDULE) for rows in per_snapshot.values())
    # Segment start: UTC time of day + row offset = local schedule start (export v1 rule)
    starts = sorted(
        (int(e["basalSchedule.start"][11:13]) * 60 + int(e["basalSchedule.start"][14:16]) + e["timezoneOffset"]) % 1440
        for e in next(iter(per_snapshot.values())))
    assert starts == [m for m, _ in generate_tidepool.BASAL_SCHEDULE]


def test_site_primes_and_overrides_present():
    events = generate_tidepool.generate(days=9, seed=7)
    subtypes = {e.get("subType") for e in events if e["type"] == "deviceEvent"}
    assert {"prime", "reservoirChange", "pumpSettingsOverride", "alarm"} <= subtypes
