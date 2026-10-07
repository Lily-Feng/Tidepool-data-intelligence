"""Package a Tidepool JSON export into an ingest batch and optionally upload it.

Runs on your own machine. Reads an export file (a JSON array of events),
writes a batch directory with `events.ndjson.gz` and `manifest.json`, and with
`--upload` copies the batch to a Unity Catalog volume using the Databricks CLI.

Logs only counts, IDs and timestamps, never health values.

Usage:
    # Package only (dry run; nothing leaves this machine)
    python src/ingest/tidepool_export.py private/raw/export.json

    # Package and upload to the volume created by the bundle
    python src/ingest/tidepool_export.py private/raw/export.json --upload \
        --volume /Volumes/twiistlab/private_raw/landing --profile DEFAULT
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import subprocess
import sys
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

COLLECTOR_VERSION = "0.1.0"
SOURCE = "tidepool_export"
# Twiist exports carry basal `duration` in minutes; see docs/data-contract.md.
SOURCE_CONTRACT_VERSION = "tidepool-export-v1"
REQUIRED_FIELDS = ("id", "type", "time")
DEFAULT_OUT_DIR = Path("private/raw/batches")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_events(export_path: Path) -> list[dict]:
    with export_path.open(encoding="utf-8") as f:
        events = json.load(f)
    if not isinstance(events, list):
        raise ValueError("export must be a JSON array of events")
    return events


def find_existing_batch(out_dir: Path, source_sha256: str) -> Path | None:
    for manifest in out_dir.glob("*/manifest.json"):
        if json.loads(manifest.read_text()).get("source_sha256") == source_sha256:
            return manifest.parent
    return None


def build_batch(export_path: Path, out_dir: Path) -> Path:
    events = load_events(export_path)
    batch_id = str(uuid.uuid4())
    retrieved_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    batch_dir = out_dir / batch_id
    batch_dir.mkdir(parents=True)

    type_counts: Counter[str] = Counter()
    skipped = 0
    times = []
    events_path = batch_dir / "events.ndjson.gz"
    with gzip.open(events_path, "wt", encoding="utf-8") as out:
        for index, event in enumerate(events):
            if not isinstance(event, dict) or any(k not in event for k in REQUIRED_FIELDS):
                skipped += 1
                continue
            event_json = json.dumps(event, sort_keys=True, separators=(",", ":"))
            record = {
                "batch_id": batch_id,
                "retrieved_at_utc": retrieved_at,
                "source": SOURCE,
                "source_contract_version": SOURCE_CONTRACT_VERSION,
                "record_index": index,
                "record_sha256": hashlib.sha256(event_json.encode()).hexdigest(),
                "event_type": event["type"],
                "event_id": event["id"],
                "event_time": event["time"],
                "event_json": event_json,
            }
            out.write(json.dumps(record, separators=(",", ":")) + "\n")
            type_counts[event["type"]] += 1
            times.append(event["time"])

    manifest = {
        "batch_id": batch_id,
        "source": SOURCE,
        "source_contract_version": SOURCE_CONTRACT_VERSION,
        "collector_version": COLLECTOR_VERSION,
        "retrieved_at_utc": retrieved_at,
        "source_sha256": sha256_file(export_path),
        "row_count": sum(type_counts.values()),
        "skipped_count": skipped,
        "type_counts": dict(sorted(type_counts.items())),
        "event_time_min_utc": min(times) if times else None,
        "event_time_max_utc": max(times) if times else None,
        "content_sha256": sha256_file(events_path),
        "status": "complete",
    }
    (batch_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return batch_dir


def upload_batch(batch_dir: Path, volume: str, profile: str | None) -> None:
    dest = f"dbfs:{volume.rstrip('/')}/tidepool/{batch_dir.name}"
    profile_args = ["--profile", profile] if profile else []

    def cli(*args: str) -> None:
        result = subprocess.run(["databricks", "fs", *args, *profile_args], capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"databricks fs {args[0]} failed: {result.stderr.strip()}")

    cli("mkdir", dest)
    # Events first, manifest last: a manifest in the volume means the batch is complete.
    for name in ("events.ndjson.gz", "manifest.json"):
        cli("cp", "--overwrite", str(batch_dir / name), f"{dest}/{name}")
    print(f"uploaded batch {batch_dir.name} to {dest}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("export", type=Path, help="Tidepool export JSON file")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR, help="local batch directory (git-ignored)")
    parser.add_argument("--upload", action="store_true", help="upload the batch to the volume")
    parser.add_argument("--volume", default="/Volumes/twiistlab/private_raw/landing", help="target volume path")
    parser.add_argument("--profile", default=None, help="Databricks CLI profile")
    parser.add_argument("--force", action="store_true", help="re-package even if this export was already batched")
    args = parser.parse_args(argv)

    source_sha = sha256_file(args.export)
    existing = None if args.force else find_existing_batch(args.out_dir, source_sha)
    if existing:
        print(f"export already packaged as batch {existing.name}; use --force to repackage")
        batch_dir = existing
    else:
        batch_dir = build_batch(args.export, args.out_dir)

    manifest = json.loads((batch_dir / "manifest.json").read_text())
    print(f"batch {manifest['batch_id']}: {manifest['row_count']} events "
          f"({manifest['skipped_count']} skipped), "
          f"{manifest['event_time_min_utc']} .. {manifest['event_time_max_utc']}")
    for kind, count in manifest["type_counts"].items():
        print(f"  {kind}: {count}")

    if args.upload:
        upload_batch(batch_dir, args.volume, args.profile)
    else:
        print("dry run: not uploaded (pass --upload)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
