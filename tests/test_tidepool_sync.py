import base64
import gzip
import json
import sys
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "ingest"))
sys.path.insert(0, str(ROOT / "src" / "synthetic"))

import generate_tidepool  # noqa: E402
import tidepool_auth  # noqa: E402
import tidepool_sync  # noqa: E402
from tidepool_auth import Credentials, MemoryStore, ReauthRequired, TokenManager  # noqa: E402

T0 = datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc)
SYNTHETIC_USER = "synthetic-user-0001"


def fake_jwt(**claims) -> str:
    body = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"e30.{body}.sig"


class FakeTidepool:
    """Synthetic token endpoint + data API. Rotates refresh tokens like Keycloak."""

    def __init__(self, events=None, session_max=timedelta(hours=24), idle=timedelta(hours=8)):
        self.events = events or []
        self.session_max, self.idle = session_max, idle
        self.clock = T0
        self.auth_time = T0
        self.valid_refresh = {"rt-0": T0 + idle}
        self.counter = 0
        self.data_statuses: list[int] = []  # statuses to return before succeeding
        self.data_calls = []

    def http(self, method, url, headers, body):
        if url.endswith("/token"):
            return self._token(body)
        return self._data(url, headers)

    def _token(self, body):
        rt = urllib.parse.parse_qs(body.decode())["refresh_token"][0]
        expiry = self.valid_refresh.pop(rt, None)
        if expiry is None or expiry <= self.clock:
            return 400, {}, json.dumps({"error": "invalid_grant"}).encode()
        self.counter += 1
        new_rt = f"rt-{self.counter}"
        session_left = self.auth_time + self.session_max - self.clock
        refresh_life = min(self.idle, session_left)
        self.valid_refresh[new_rt] = self.clock + refresh_life
        access = fake_jwt(sub=SYNTHETIC_USER, auth_time=int(self.auth_time.timestamp()))
        return 200, {}, json.dumps({
            "access_token": access, "expires_in": 180,
            "refresh_token": new_rt, "refresh_expires_in": int(refresh_life.total_seconds()),
        }).encode()

    def _data(self, url, headers):
        self.data_calls.append(url)
        assert tidepool_sync.SESSION_HEADER in headers
        if self.data_statuses:
            return self.data_statuses.pop(0), {"Retry-After": "1"}, b"{}"
        q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        start, end = (tidepool_auth.parse_iso(q[k][0]) for k in ("startDate", "endDate"))
        hits = [e for e in self.events if start <= tidepool_auth.parse_iso(e["time"]) <= end]
        return 200, {}, json.dumps(hits).encode()


def make_tokens(fake: FakeTidepool, tmp_path: Path):
    store = MemoryStore(Credentials(
        client_id="synthetic-client", token_endpoint="https://auth.example.test/token",
        api_base_url="https://api.example.test", refresh_token="rt-0",
    ))
    return store, TokenManager(store, fake.http, probe_log=tmp_path / "probe.jsonl", clock=lambda: fake.clock)


def test_refresh_persists_rotated_token_before_use(tmp_path):
    fake = FakeTidepool()
    store, tokens = make_tokens(fake, tmp_path)
    tokens.access_token()
    assert store.creds.refresh_token == "rt-1"
    assert store.creds.user_id == SYNTHETIC_USER
    # Cached until near expiry: no second refresh
    tokens.access_token()
    assert fake.counter == 1
    fake.clock += timedelta(minutes=3)
    tokens.access_token()
    assert store.creds.refresh_token == "rt-2"


def test_probe_detects_absolute_session_limit(tmp_path):
    fake = FakeTidepool(session_max=timedelta(hours=20))
    store, tokens = make_tokens(fake, tmp_path)
    outcomes = []
    for _ in range(5):  # refresh every 6 hours
        try:
            tokens.access_token(force=True)
            outcomes.append("ok")
        except ReauthRequired:
            outcomes.append("reauth")
        fake.clock += timedelta(hours=6)
    records = [json.loads(l) for l in (tmp_path / "probe.jsonl").read_text().splitlines()]
    lifetimes = [r["refresh_expires_in"] for r in records if r["ok"]]
    assert lifetimes[:3] == [28800, 28800, 28800]
    assert lifetimes[3] == 2 * 3600  # 20h cap minus 18h elapsed
    assert outcomes[-1] == "reauth"
    summary = "\n".join(tidepool_auth.summarise_probe(records))
    assert "LAST ATTEMPT FAILED" in summary
    # Probe log never holds token values or the user id
    raw = (tmp_path / "probe.jsonl").read_text()
    assert "rt-" not in raw and SYNTHETIC_USER not in raw


def test_six_hourly_refresh_survives_while_session_allows(tmp_path):
    fake = FakeTidepool(session_max=timedelta(days=30))
    _, tokens = make_tokens(fake, tmp_path)
    for _ in range(12):  # three days
        tokens.access_token(force=True)
        fake.clock += timedelta(hours=6)
    records = [json.loads(l) for l in (tmp_path / "probe.jsonl").read_text().splitlines()]
    assert all(r["ok"] and r["refresh_expires_in"] == 28800 for r in records)


def test_gap_longer_than_idle_timeout_requires_reauth(tmp_path):
    fake = FakeTidepool()
    _, tokens = make_tokens(fake, tmp_path)
    tokens.access_token()
    fake.clock += timedelta(hours=9)  # e.g. laptop asleep past the 8h idle window
    with pytest.raises(ReauthRequired):
        tokens.access_token()


def test_plan_windows_overlap_and_bounds():
    now = T0
    first = tidepool_sync.plan_windows(None, now - timedelta(days=10), now)
    assert len(first) == 2 and first[0][0] == now - timedelta(days=10) and first[-1][1] == now
    later = tidepool_sync.plan_windows(now - timedelta(hours=6), None, now)
    assert later == [(now - timedelta(hours=78), now)]
    with pytest.raises(ValueError):
        tidepool_sync.plan_windows(None, None, now)


def test_sync_end_to_end_dedupes_overlap_and_advances_checkpoint(tmp_path):
    events = generate_tidepool.generate(days=2, seed=3)
    fake = FakeTidepool(events=events)
    times = sorted(tidepool_auth.parse_iso(e["time"]) for e in events)
    fake.clock = fake.auth_time = times[-1] + timedelta(hours=1)
    fake.valid_refresh = {"rt-0": fake.clock + fake.idle}
    _, tokens = make_tokens(fake, tmp_path)
    paths = dict(checkpoint_path=tmp_path / "cp.json", export_dir=tmp_path / "api", batch_dir=tmp_path / "batches")

    r1 = tidepool_sync.run_sync(tokens, now=fake.clock, initial_start=times[0], sleep=lambda s: None, **paths)
    assert r1["last_event_count"] == len({e["id"] for e in events})
    manifest = json.loads((tmp_path / "batches" / r1["last_batch_id"] / "manifest.json").read_text())
    assert manifest["row_count"] == r1["last_event_count"]

    # Six hours later: overlap re-fetches recent events; checkpoint moves forward
    fake.clock += timedelta(hours=6)
    r2 = tidepool_sync.run_sync(tokens, now=fake.clock, initial_start=times[0], sleep=lambda s: None, **paths)
    assert r2["last_success_end_utc"] == tidepool_auth.iso(fake.clock)
    with gzip.open(tmp_path / "batches" / r2["last_batch_id"] / "events.ndjson.gz", "rt") as f:
        ids = [json.loads(line)["event_id"] for line in f]
    assert len(ids) == len(set(ids))


def test_failed_fetch_leaves_checkpoint_unchanged(tmp_path):
    fake = FakeTidepool(events=[])
    _, tokens = make_tokens(fake, tmp_path)
    cp = tmp_path / "cp.json"
    tidepool_sync.save_checkpoint({"last_success_end_utc": tidepool_auth.iso(T0 - timedelta(hours=6))}, cp)
    fake.data_statuses = [503] * tidepool_sync.MAX_ATTEMPTS
    with pytest.raises(RuntimeError):
        tidepool_sync.run_sync(tokens, now=T0, initial_start=None, checkpoint_path=cp,
                               export_dir=tmp_path / "api", batch_dir=tmp_path / "b", sleep=lambda s: None)
    assert json.loads(cp.read_text())["last_success_end_utc"] == tidepool_auth.iso(T0 - timedelta(hours=6))


def test_401_refreshes_once_then_succeeds(tmp_path):
    fake = FakeTidepool(events=[])
    _, tokens = make_tokens(fake, tmp_path)
    fake.data_statuses = [401]
    assert tidepool_sync.fetch_window(tokens, T0 - timedelta(hours=1), T0, http=fake.http,
                                      sleep=lambda s: None) == []
    assert fake.counter == 2


def test_lock_blocks_concurrent_run(tmp_path):
    lock = tmp_path / "sync.lock"
    with tidepool_sync.exclusive_lock(lock):
        with pytest.raises(tidepool_sync.AlreadyRunning):
            with tidepool_sync.exclusive_lock(lock):
                pass
