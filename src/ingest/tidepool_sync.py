"""Scheduled Tidepool API pull: refresh, fetch an overlapping window, package a batch.

Designed to run every six hours from launchd (see scripts/launchd/). Each run:

1. Takes an exclusive file lock, so two runs never refresh the same token.
2. Gets a valid access token (refreshing and persisting the newest refresh token).
3. Fetches GET /data/{userId} from the last successful window end minus the
   overlap, in bounded windows. Tidepool boundaries are inclusive, so events
   are de-duplicated by id; the pipeline also upserts by id downstream.
4. Writes the events as an export file and packages it with tidepool_export,
   so API pulls and manual exports produce the same batch format.
5. Advances the checkpoint only after the batch is written (and uploaded, with
   --upload). A failed run leaves the checkpoint unchanged and is safe to rerun.

On a rejected refresh token the run records `reauth_required`, shows a macOS
notification, and exits 2 without retrying.

Logs contain counts, batch IDs and timestamps only.

Usage:
    python src/ingest/tidepool_sync.py --initial-start 2026-10-10T00:00:00Z
    python src/ingest/tidepool_sync.py --upload --profile DEFAULT
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import subprocess
import sys
import time
import urllib.parse
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import tidepool_auth
import tidepool_export
from tidepool_auth import ReauthRequired, TokenEndpointError, TokenManager, iso, parse_iso, utc_now

STATE_DIR = tidepool_auth.STATE_DIR
CHECKPOINT = STATE_DIR / "tidepool-sync.json"
LOCK_FILE = STATE_DIR / "tidepool-sync.lock"
API_EXPORT_DIR = Path("private/raw/api")
OVERLAP = timedelta(hours=72)
MAX_WINDOW = timedelta(days=7)
MAX_ATTEMPTS = 4
# The data spec names this header; confirm it for a registered OAuth client.
SESSION_HEADER = "X-Tidepool-Session-Token"


class AlreadyRunning(Exception):
    pass


@contextmanager
def exclusive_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise AlreadyRunning("another sync holds the lock") from None
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def load_checkpoint(path: Path = CHECKPOINT) -> dict:
    return json.loads(path.read_text()) if path.exists() else {}


def save_checkpoint(state: dict, path: Path = CHECKPOINT) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2))
    os.replace(tmp, path)


def plan_windows(last_end: datetime | None, initial_start: datetime | None, now: datetime,
                 overlap: timedelta = OVERLAP, max_window: timedelta = MAX_WINDOW) -> list[tuple[datetime, datetime]]:
    if last_end is None:
        if initial_start is None:
            raise ValueError("first run needs --initial-start")
        start = initial_start
    else:
        start = last_end - overlap
        if initial_start is not None:
            start = max(start, initial_start)
    windows = []
    while start < now:
        end = min(start + max_window, now)
        windows.append((start, end))
        start = end
    return windows


def fetch_window(tokens: TokenManager, start: datetime, end: datetime,
                 http=None, sleep=time.sleep) -> list[dict]:
    http = http or tokens.http
    tokens.access_token()  # the first refresh also fills in the user id
    user_id = tokens.user_id
    if not user_id:
        raise ReauthRequired("no user id stored with the credentials")
    query = urllib.parse.urlencode({"startDate": iso(start), "endDate": iso(end)})
    url = f"{tokens.api_base_url.rstrip('/')}/data/{urllib.parse.quote(user_id)}?{query}"
    refreshed_after_401 = False
    for attempt in range(1, MAX_ATTEMPTS + 1):
        headers = {SESSION_HEADER: tokens.access_token(), "Accept": "application/json"}
        try:
            status, resp_headers, body = http("GET", url, headers, None)
        except OSError:
            status, resp_headers, body = None, {}, b""
        if status == 200:
            events = json.loads(body)
            if not isinstance(events, list):
                raise ValueError("data response is not a JSON array")
            return events
        if status == 401 and not refreshed_after_401:
            tokens.access_token(force=True)
            refreshed_after_401 = True
            continue
        if status == 401:
            raise ReauthRequired("data API rejected a freshly refreshed token")
        if status == 403:
            raise PermissionError("data API returned 403: check account permissions")
        if status is None or status == 429 or status >= 500:
            if attempt == MAX_ATTEMPTS:
                break
            retry_after = resp_headers.get("Retry-After", "")
            sleep(int(retry_after) if retry_after.isdigit() else min(2 ** attempt * 5, 120))
            continue
        # Do not include the URL (it carries the user id) or the body.
        raise RuntimeError(f"data API returned HTTP {status}")
    raise RuntimeError(f"data API still failing after {MAX_ATTEMPTS} attempts (last HTTP {status})")


def dedupe(events: list[dict]) -> list[dict]:
    seen: dict[str, dict] = {}
    unkeyed = []
    for e in events:
        if isinstance(e, dict) and e.get("id"):
            seen[e["id"]] = e  # a later window's copy wins
        else:
            unkeyed.append(e)  # tidepool_export skips and counts these
    return list(seen.values()) + unkeyed


def run_sync(tokens: TokenManager, *, now: datetime, initial_start: datetime | None,
             checkpoint_path: Path = CHECKPOINT, export_dir: Path = API_EXPORT_DIR,
             batch_dir: Path = tidepool_export.DEFAULT_OUT_DIR, upload=None,
             http=None, sleep=time.sleep) -> dict:
    state = load_checkpoint(checkpoint_path)
    windows = plan_windows(parse_iso(state.get("last_success_end_utc")), initial_start, now)
    run_id = str(uuid.uuid4())

    events: list[dict] = []
    for start, end in windows:
        events.extend(fetch_window(tokens, start, end, http=http, sleep=sleep))
    events = dedupe(events)

    batch_id = None
    if events:
        export_dir.mkdir(parents=True, exist_ok=True)
        export_path = export_dir / f"{run_id}.json"
        export_path.write_text(json.dumps(events))
        os.chmod(export_path, 0o600)
        batch = tidepool_export.build_batch(export_path, batch_dir)
        if upload:
            upload(batch)
        batch_id = batch.name

    result = {
        "last_success_end_utc": iso(windows[-1][1]) if windows else state.get("last_success_end_utc"),
        "last_run_id": run_id,
        "last_run_utc": iso(now),
        "last_status": "ok",
        "last_batch_id": batch_id,
        "last_event_count": len(events),
        "last_window_count": len(windows),
    }
    save_checkpoint(result, checkpoint_path)
    return result


def record_failure(status: str, checkpoint_path: Path = CHECKPOINT) -> None:
    state = load_checkpoint(checkpoint_path)
    state.update({"last_status": status, "last_failure_utc": iso(utc_now())})
    save_checkpoint(state, checkpoint_path)


def notify(message: str) -> None:
    subprocess.run(["osascript", "-e", f'display notification "{message}" with title "TwiistLab"'],
                   capture_output=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--account", default=tidepool_auth.DEFAULT_ACCOUNT)
    parser.add_argument("--initial-start", type=parse_iso, help="UTC start for the first run, e.g. 2026-10-10T00:00:00Z")
    parser.add_argument("--upload", action="store_true", help="upload each batch to the volume")
    parser.add_argument("--volume", default="/Volumes/twiistlab/private_raw/landing")
    parser.add_argument("--profile", default=None, help="Databricks CLI profile")
    args = parser.parse_args(argv)

    upload = (lambda b: tidepool_export.upload_batch(b, args.volume, args.profile)) if args.upload else None
    tokens = TokenManager(tidepool_auth.KeychainStore(args.account))
    try:
        with exclusive_lock(LOCK_FILE):
            result = run_sync(tokens, now=utc_now(), initial_start=args.initial_start, upload=upload)
    except AlreadyRunning as e:
        print(f"skipped: {e}")
        return 0
    except ReauthRequired as e:
        record_failure("reauth_required")
        notify("Tidepool sign-in required; scheduled sync stopped.")
        print(f"reauth_required: {e}")
        return 2
    except (TokenEndpointError, PermissionError, RuntimeError, ValueError) as e:
        record_failure("failed")
        print(f"failed: {type(e).__name__}: {e}")
        return 1
    print(f"run {result['last_run_id']}: {result['last_event_count']} events in "
          f"{result['last_window_count']} window(s); batch {result['last_batch_id']}; "
          f"checkpoint {result['last_success_end_utc']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
