"""Generate a synthetic Tidepool-style export (JSON array) for tests and demos.

Shapes mirror a Twiist/Tidepool file export (cbg, smbg, basal, bolus, food,
deviceEvent, flattened pumpSettings.* rows) but every value is invented. Nothing
here has lineage to a real person.

Usage:
    python src/synthetic/generate_tidepool.py --days 14 --out /tmp/synthetic.json

    # Two overlapping exports of the same history, to exercise incremental loads
    python src/synthetic/generate_tidepool.py --days 14 --window 0:9 --out /tmp/a.json
    python src/synthetic/generate_tidepool.py --days 14 --window 6:14 --out /tmp/b.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

DEVICE_ID = "synthetic_pump_0001"
SERIAL = "synthetic_serial_0001"
UPLOAD_ID = "synthetic_upload_0001"
TZ_OFFSET_MIN = -420
MEALS = [(7, 30, 45), (12, 30, 60), (18, 45, 70)]  # local hour, minute, grams
SITE_EVERY_DAYS = 3
# Synthetic settings: (local start minute, value). The basal schedule changes
# halfway through the history so settings versioning has something to find.
BASAL_SCHEDULE = [(0, 0.7), (360, 0.9), (1260, 0.8)]
BASAL_SCHEDULE_CHANGED = [(0, 0.7), (360, 1.0), (1260, 0.8)]
CARB_RATIOS = [(0, 10)]
SENSITIVITIES = [(0, 50), (720, 45)]
BG_TARGETS = [(0, 100, 120)]
DEFAULT_END = datetime(2026, 1, 15, tzinfo=timezone.utc)
SETTINGS_REF_DATE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _iso(ts: datetime) -> str:
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


class _Rng(random.Random):
    def __init__(self, seed: int):
        super().__init__(seed)
        self.seed_value = seed


def _event_id(seed: int, kind: str, ts: datetime, extra: str = "") -> str:
    # Deterministic per (kind, time): overlapping exports of the same history
    # carry the same id for the same record, as real Tidepool exports do.
    return hashlib.sha256(f"{seed}|{kind}|{_iso(ts)}|{extra}".encode()).hexdigest()[:32]


def _event(rng: _Rng, kind: str, ts: datetime, extra: str = "", **fields) -> dict:
    return {
        "deviceId": DEVICE_ID,
        "id": _event_id(rng.seed_value, kind, ts, extra),
        "time": _iso(ts),
        "timezoneOffset": TZ_OFFSET_MIN,
        "type": kind,
        "uploadId": UPLOAD_ID,
        **fields,
    }


def generate(days: int, seed: int, end_utc: datetime | None = None) -> list[dict]:
    rng = _Rng(seed)
    end = (end_utc or DEFAULT_END).replace(second=0, microsecond=0)
    start = end - timedelta(days=days)
    events: list[dict] = []

    # Meals and boluses
    meal_times = []
    for d in range(days + 1):
        local_midnight = (start - timedelta(minutes=TZ_OFFSET_MIN)).replace(hour=0, minute=0) + timedelta(days=d)
        for hour, minute, grams in MEALS:
            ts = local_midnight + timedelta(hours=hour, minutes=minute + rng.randint(-20, 20)) + timedelta(minutes=TZ_OFFSET_MIN)
            if not (start <= ts < end):
                continue
            carbs = max(10, int(rng.gauss(grams, 12)))
            meal_times.append(ts)
            nutrition = {"carbohydrate": {"net": carbs, "units": "grams"}, "estimatedAbsorptionDuration": 10800}
            events.append(_event(rng, "food", ts, name="synthetic meal", nutrition=json.dumps(nutrition)))
            units = round(carbs / 10, 2)
            events.append(_event(rng, "bolus", ts - timedelta(minutes=rng.randint(0, 15)),
                                 subType="normal", normal=units, expectedNormal=units))

    # CGM every 5 minutes and automated basal intervals
    ts = start
    while ts < end:
        hours_local = ((ts + timedelta(minutes=TZ_OFFSET_MIN)).hour + ts.minute / 60)
        meal_effect = sum(60 * math.exp(-((ts - m).total_seconds() / 3600 - 1.0) ** 2) for m in meal_times
                          if timedelta(0) <= ts - m <= timedelta(hours=4))
        glucose = 115 + 20 * math.sin(2 * math.pi * (hours_local - 4) / 24) + meal_effect + rng.gauss(0, 8)
        events.append(_event(rng, "cbg", ts, units="mg/dL", value=round(min(max(glucose, 45), 380), 0)))

        step = timedelta(seconds=300 + rng.randint(-3, 3))
        nxt = ts + step
        rate = round(max(0.0, 0.8 + (glucose - 120) / 100 + rng.gauss(0, 0.2)), 2)
        payload = {"deliveredState": "BasalClosedLoop", "nextState": "BasalClosedLoop",
                   "nextStateTime": nxt.strftime("%Y-%m-%dT%H:%M:%S.000Z")}
        events.append(_event(rng, "basal", ts, deliveryType="automated", rate=rate,
                             duration=step.total_seconds() / 60, payload=json.dumps(payload)))
        ts = nxt

    events += _device_events(rng, start, end)
    events += _settings_snapshots(rng, start, end)
    events.sort(key=lambda e: e["time"], reverse=True)  # exports are newest-first
    return events


def _device_events(rng: _Rng, start: datetime, end: datetime) -> list[dict]:
    events = []
    day = 0
    while (ts := start + timedelta(days=day, hours=27 + rng.random())) < end:  # ~20:00 local
        if day % SITE_EVERY_DAYS == 0:
            events.append(_event(rng, "deviceEvent", ts - timedelta(minutes=10), subType="reservoirChange"))
            events.append(_event(rng, "deviceEvent", ts, subType="prime", primeTarget="cannula", volume=0.3))
            if rng.random() < 0.3:  # occasional re-prime of the same site
                events.append(_event(rng, "deviceEvent", ts + timedelta(minutes=6), subType="prime",
                                     primeTarget="cannula", volume=0.3))
        if day % 5 == 2:
            events.append(_event(rng, "deviceEvent", ts - timedelta(hours=3), subType="pumpSettingsOverride",
                                 duration=float(rng.choice([60, 90, 120])), **{
                                     "bgTarget.low": 140.0, "bgTarget.high": 160.0, "units.bg": "mg/dL"}))
        if day % 7 == 4:
            events.append(_event(rng, "deviceEvent", ts - timedelta(hours=8), subType="alarm", alarmType="occlusion"))
        if day % 4 == 0:
            events.append(_event(rng, "smbg", ts - timedelta(hours=12), subType="manual", units="mg/dL",
                                 value=float(rng.randint(80, 200))))
        day += 1
    return events


def _segment_start(local_minute: int) -> str:
    # Export v1 writes a segment start as a UTC timestamp whose time of day, plus
    # the row's offset, is the local schedule start.
    utc = SETTINGS_REF_DATE + timedelta(minutes=(local_minute - TZ_OFFSET_MIN) % 1440)
    return utc.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _settings_snapshots(rng: _Rng, start: datetime, end: datetime) -> list[dict]:
    """One full settings snapshot per day (one per upload), exploded into one row
    per schedule segment as the file export does."""
    events = []
    days = (end - start).days
    common = {"scheduleName": "Standard", "activeSchedule": "Standard", "serialNumber": SERIAL,
              "manufacturers": "synthetic", "model": "synthetic"}
    for day in range(days):
        ts = start + timedelta(days=day, hours=12)
        basal = BASAL_SCHEDULE if day < days // 2 else BASAL_SCHEDULE_CHANGED
        snapshot = [
            ("pumpSettings.basalSchedules", "basalSchedule", [{"rate": v} for _, v in basal], basal),
            ("pumpSettings.carbRatios", "carbRatio", [{"amount": v} for _, v in CARB_RATIOS], CARB_RATIOS),
            ("pumpSettings.insulinSensitivities", "insulinSensitivity",
             [{"amount": float(v)} for _, v in SENSITIVITIES], SENSITIVITIES),
            ("pumpSettings.bgTargets", "bgTarget",
             [{"low": float(lo), "high": float(hi)} for _, lo, hi in BG_TARGETS], BG_TARGETS),
        ]
        for kind, prefix, values, segments in snapshot:
            record_id = _event_id(rng.seed_value, kind, ts)
            for seg, vals in zip(segments, values):
                row = _event(rng, kind, ts, **common, **{f"{prefix}.start": _segment_start(seg[0])},
                             **{f"{prefix}.{k}": v for k, v in vals.items()})
                row["id"] = record_id  # one id per snapshot, repeated across segment rows
                if kind != "pumpSettings.basalSchedules":
                    row["units.bg"] = "mg/dL"
                events.append(row)
    return events


def export_window(events: list[dict], start_utc: datetime, end_utc: datetime) -> list[dict]:
    """The events a file export covering [start_utc, end_utc) would contain."""
    return [e for e in events if _iso(start_utc) <= e["time"] < _iso(end_utc)]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--window", default=None, help="START:END day offsets to export a slice, e.g. 6:14")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    events = generate(args.days, args.seed)
    if args.window:
        first, last = (int(x) for x in args.window.split(":"))
        start = DEFAULT_END - timedelta(days=args.days)
        events = export_window(events, start + timedelta(days=first), start + timedelta(days=last))
    args.out.write_text(json.dumps(events))
    print(f"wrote {len(events)} synthetic events to {args.out}")


if __name__ == "__main__":
    main()
