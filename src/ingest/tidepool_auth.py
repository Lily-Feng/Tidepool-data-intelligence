"""Tidepool OAuth credentials: Keychain storage, refresh, and a token-lifetime probe.

Runs on your own machine. The refresh token lives in macOS Keychain (via the
`keyring` package); the short-lived access token is never stored. Every refresh
persists the newest refresh token *before* returning, because Keycloak may
rotate it and the old one can stop working.

The probe answers one question: can a scheduled refresh keep the session alive
indefinitely? Keycloak reports `refresh_expires_in` as the smaller of the idle
timeout and the time left before the absolute session limit. While it stays at
its full value, refreshing extends the session; once it starts shrinking, the
absolute limit is in sight and re-sign-in will be required.

Probe records go to private/state/token-probe.jsonl and contain timings only:
no tokens, user IDs or health data.

Usage:
    # One-time: move the captured browser session into Keychain
    python src/ingest/tidepool_auth.py import-session tidepool-session.json

    # Refresh once and record the lifetimes Tidepool returns
    python src/ingest/tidepool_auth.py probe

    # Summarise what the probe has observed so far
    python src/ingest/tidepool_auth.py status
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Protocol

KEYCHAIN_SERVICE = "twiistlab.tidepool"
DEFAULT_ACCOUNT = "subject_001"
STATE_DIR = Path("private/state")
PROBE_LOG = STATE_DIR / "token-probe.jsonl"
# Refresh when the access token has less than this left; it lasts ~3 minutes.
ACCESS_MARGIN = timedelta(seconds=30)


class ReauthRequired(Exception):
    """The refresh token was rejected; a new interactive sign-in is needed."""


class TokenEndpointError(Exception):
    """The token endpoint failed for a reason other than an invalid grant."""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime | None) -> str | None:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if dt else None


def parse_iso(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def jwt_claims(token: str) -> dict:
    """Read a JWT's claims WITHOUT verifying the signature.

    Used only to read timing claims (iat, exp, auth_time, typ) for the probe and
    the subject for the data URL. Never use this to make a trust decision.
    """
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))
    except (IndexError, ValueError):
        return {}


# ── Credential storage ──────────────────────────────────────────────────


@dataclass
class Credentials:
    client_id: str
    token_endpoint: str
    api_base_url: str
    refresh_token: str
    refresh_expires_at: datetime | None = None
    user_id: str | None = None
    session_auth_time: datetime | None = None

    def to_json(self) -> str:
        return json.dumps({
            "client_id": self.client_id,
            "token_endpoint": self.token_endpoint,
            "api_base_url": self.api_base_url,
            "refresh_token": self.refresh_token,
            "refresh_expires_at": iso(self.refresh_expires_at),
            "user_id": self.user_id,
            "session_auth_time": iso(self.session_auth_time),
        })

    @classmethod
    def from_json(cls, raw: str) -> "Credentials":
        d = json.loads(raw)
        return cls(
            client_id=d["client_id"],
            token_endpoint=d["token_endpoint"],
            api_base_url=d["api_base_url"],
            refresh_token=d["refresh_token"],
            refresh_expires_at=parse_iso(d.get("refresh_expires_at")),
            user_id=d.get("user_id"),
            session_auth_time=parse_iso(d.get("session_auth_time")),
        )


class CredentialStore(Protocol):
    def load(self) -> Credentials: ...
    def save(self, creds: Credentials) -> None: ...


class KeychainStore:
    """One Keychain item per account alias, holding the credential bundle as JSON."""

    def __init__(self, account: str = DEFAULT_ACCOUNT):
        import keyring  # imported lazily so tests need not install it

        self._keyring = keyring
        self.account = account

    def load(self) -> Credentials:
        raw = self._keyring.get_password(KEYCHAIN_SERVICE, self.account)
        if raw is None:
            raise ReauthRequired(f"no Tidepool credentials in Keychain for '{self.account}'")
        return Credentials.from_json(raw)

    def save(self, creds: Credentials) -> None:
        self._keyring.set_password(KEYCHAIN_SERVICE, self.account, creds.to_json())


class MemoryStore:
    """In-memory store for tests."""

    def __init__(self, creds: Credentials | None = None):
        self.creds = creds
        self.saves = 0

    def load(self) -> Credentials:
        if self.creds is None:
            raise ReauthRequired("no credentials")
        return self.creds

    def save(self, creds: Credentials) -> None:
        self.creds = creds
        self.saves += 1


# ── Token endpoint ──────────────────────────────────────────────────────

# (method, url, headers, body) -> (status, headers, body)
HttpFn = Callable[[str, str, dict, bytes | None], tuple[int, dict, bytes]]


def urllib_http(method: str, url: str, headers: dict, body: bytes | None) -> tuple[int, dict, bytes]:
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers or {}), e.read()


@dataclass
class AccessToken:
    token: str
    expires_at: datetime


@dataclass
class RefreshResult:
    access: AccessToken
    expires_in: int
    refresh_expires_in: int | None
    rotated: bool
    refresh_typ: str | None
    session_auth_time: datetime | None


def refresh(store: CredentialStore, http: HttpFn = urllib_http, now: datetime | None = None) -> RefreshResult:
    """Exchange the stored refresh token and persist the newest one before returning."""
    now = now or utc_now()
    creds = store.load()
    old_refresh = creds.refresh_token
    body = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "client_id": creds.client_id,
        "refresh_token": creds.refresh_token,
    }).encode()
    status, _, raw = http("POST", creds.token_endpoint,
                          {"Content-Type": "application/x-www-form-urlencoded"}, body)
    # Never log the request or response body: both carry tokens.
    try:
        payload = json.loads(raw or b"{}")
    except ValueError:
        payload = {}
    if status in (400, 401) and payload.get("error") in ("invalid_grant", "invalid_token", "unauthorized_client"):
        raise ReauthRequired(f"token endpoint returned {payload.get('error')}")
    if status != 200 or "access_token" not in payload:
        raise TokenEndpointError(f"token endpoint returned HTTP {status}")

    new_refresh = payload.get("refresh_token") or creds.refresh_token
    refresh_expires_in = payload.get("refresh_expires_in")
    access_claims = jwt_claims(payload["access_token"])
    auth_time = access_claims.get("auth_time")
    creds.refresh_token = new_refresh
    if refresh_expires_in is not None:
        creds.refresh_expires_at = now + timedelta(seconds=int(refresh_expires_in))
    if auth_time:
        creds.session_auth_time = datetime.fromtimestamp(auth_time, timezone.utc)
    creds.user_id = creds.user_id or access_claims.get("sub")
    rotated = new_refresh != old_refresh
    store.save(creds)  # persist BEFORE any caller uses the access token

    expires_in = int(payload.get("expires_in", 0))
    return RefreshResult(
        access=AccessToken(payload["access_token"], now + timedelta(seconds=expires_in)),
        expires_in=expires_in,
        refresh_expires_in=int(refresh_expires_in) if refresh_expires_in is not None else None,
        rotated=rotated,
        refresh_typ=jwt_claims(new_refresh).get("typ"),
        session_auth_time=creds.session_auth_time,
    )


class TokenManager:
    """Hands out a valid access token, refreshing only when it is about to expire."""

    def __init__(self, store: CredentialStore, http: HttpFn = urllib_http,
                 probe_log: Path | None = PROBE_LOG, clock: Callable[[], datetime] = utc_now):
        self.store, self.http, self.probe_log, self.clock = store, http, probe_log, clock
        self._access: AccessToken | None = None

    def access_token(self, force: bool = False) -> str:
        now = self.clock()
        if force or self._access is None or self._access.expires_at - now < ACCESS_MARGIN:
            try:
                result = refresh(self.store, self.http, now)
            except (ReauthRequired, TokenEndpointError) as e:
                self._record({"ok": False, "error": type(e).__name__, "detail": str(e)}, now)
                raise
            self._access = result.access
            self._record(probe_record(result, now), now)
        return self._access.token

    @property
    def user_id(self) -> str | None:
        return self.store.load().user_id

    @property
    def api_base_url(self) -> str:
        return self.store.load().api_base_url

    def _record(self, record: dict, now: datetime) -> None:
        if self.probe_log:
            append_probe(self.probe_log, {"at_utc": iso(now), **record})


def probe_record(result: RefreshResult, now: datetime) -> dict:
    session_age = (now - result.session_auth_time).total_seconds() if result.session_auth_time else None
    return {
        "ok": True,
        "expires_in": result.expires_in,
        "refresh_expires_in": result.refresh_expires_in,
        "refresh_valid_until_utc": iso(now + timedelta(seconds=result.refresh_expires_in))
        if result.refresh_expires_in is not None else None,
        "refresh_rotated": result.rotated,
        "refresh_typ": result.refresh_typ,
        "session_age_hours": round(session_age / 3600, 2) if session_age is not None else None,
    }


def append_probe(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
    os.chmod(path, 0o600)


def summarise_probe(records: list[dict]) -> list[str]:
    ok = [r for r in records if r.get("ok")]
    lines = [f"refreshes recorded: {len(ok)} ok, {len(records) - len(ok)} failed"]
    if not ok:
        return lines
    first, last = ok[0], ok[-1]
    lines.append(f"first ok refresh: {first['at_utc']}   last ok refresh: {last['at_utc']}")
    lines.append(f"refresh valid until: {last.get('refresh_valid_until_utc')}")
    if last.get("session_age_hours") is not None:
        lines.append(f"session age at last refresh: {last['session_age_hours']} h")
    lines.append(f"refresh token type: {last.get('refresh_typ')}   rotated on last refresh: {last.get('refresh_rotated')}")
    lifetimes = [r["refresh_expires_in"] for r in ok if r.get("refresh_expires_in") is not None]
    if lifetimes:
        full = max(lifetimes)
        if lifetimes[-1] < full:
            lines.append(f"refresh lifetime shrinking ({lifetimes[-1]}s < {full}s): absolute session limit reached; "
                         "expect re-sign-in by the 'valid until' time")
        else:
            lines.append(f"refresh lifetime still at full {full}s: each refresh is extending the session")
    if records[-1].get("ok") is False:
        lines.append(f"LAST ATTEMPT FAILED: {records[-1].get('error')} at {records[-1].get('at_utc')}")
    return lines


# ── Commands ────────────────────────────────────────────────────────────


def import_session(session_path: Path, store: CredentialStore) -> Credentials:
    """Copy a captured session file into the store. Only the refresh token is kept."""
    s = json.loads(session_path.read_text())
    access_claims = jwt_claims(s.get("access_token", ""))
    auth_time = access_claims.get("auth_time")
    creds = Credentials(
        client_id=s["client_id"],
        token_endpoint=s["token_endpoint"],
        api_base_url=s["api_base_url"],
        refresh_token=s["refresh_token"],
        refresh_expires_at=parse_iso(s.get("refresh_expires_at")),
        user_id=access_claims.get("sub"),
        session_auth_time=datetime.fromtimestamp(auth_time, timezone.utc) if auth_time else None,
    )
    store.save(creds)
    return creds


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--account", default=DEFAULT_ACCOUNT, help="Keychain account alias (not a real identifier)")
    sub = parser.add_subparsers(dest="command", required=True)
    imp = sub.add_parser("import-session", help="store a captured session's refresh token in Keychain")
    imp.add_argument("session", type=Path)
    sub.add_parser("probe", help="refresh once and record the returned lifetimes")
    sub.add_parser("status", help="summarise the probe log")
    args = parser.parse_args(argv)

    if args.command == "status":
        records = [json.loads(line) for line in PROBE_LOG.read_text().splitlines()] if PROBE_LOG.exists() else []
        print("\n".join(summarise_probe(records)))
        return 0

    store = KeychainStore(args.account)
    if args.command == "import-session":
        creds = import_session(args.session, store)
        print(f"stored refresh token in Keychain ({KEYCHAIN_SERVICE}/{args.account}); "
              f"valid until {iso(creds.refresh_expires_at)}")
        print(f"you can now delete {args.session}: it holds plaintext tokens")
        return 0

    try:
        TokenManager(store).access_token(force=True)
    except ReauthRequired as e:
        print(f"re-sign-in required: {e}")
        return 2
    except TokenEndpointError as e:
        print(f"refresh failed: {e}")
        return 1
    print("\n".join(summarise_probe([json.loads(l) for l in PROBE_LOG.read_text().splitlines()])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
