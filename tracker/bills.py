"""Normalize bill and hearing records from the API into the tracker's format."""
from __future__ import annotations

import datetime as dt
import re

from .api import bill_url, iter_text, pick

BILL_RE = re.compile(r"\b(HCR|SCR|HB|SB|HR|SR)\s?0*(\d{1,5})\b", re.IGNORECASE)

TYPE_NAMES = {
    "HB": "House Bill", "SB": "Senate Bill",
    "HR": "House Resolution", "SR": "Senate Resolution",
    "HCR": "House Concurrent Resolution", "SCR": "Senate Concurrent Resolution",
}

MONTHS = ("January|February|March|April|May|June|July|August|September|"
          "October|November|December")
HEARING_DATE_RE = re.compile(rf"({MONTHS})\s+(\d{{1,2}}),\s*(\d{{4}})", re.IGNORECASE)
TIME_RE = re.compile(r"(\d{1,2}:\d{2}\s*[AP]\.?M\.?)", re.IGNORECASE)
ROOM_RE = re.compile(r"Room\s+([0-9A-Z\-]+)", re.IGNORECASE)


def canon_bill_no(s: str) -> str | None:
    m = BILL_RE.search(s or "")
    if not m:
        return None
    return f"{m.group(1).upper()}{int(m.group(2))}"


def bill_prefix(bill_no: str) -> str:
    m = re.match(r"[A-Z]+", bill_no)
    return m.group(0) if m else ""


def _date(s: str | None) -> str:
    return (s or "")[:10]


def normalize_history(raw: list | None) -> list[dict]:
    out = []
    for h in raw or []:
        if not isinstance(h, dict):
            continue
        date = _date(pick(h, "session_date", "occurred_datetime", "occurred", "date"))
        committees = pick(h, "committee_names", default=[])
        if isinstance(committees, str):
            committees = [committees]
        out.append({
            "date": date,
            "datetime": pick(h, "occurred_datetime", "occurred", default=date),
            "chamber": pick(h, "chamber", default=""),
            "action": str(pick(h, "status", "action", "action_label", "description", default="")).strip(),
            "code": pick(h, "action_code", default=""),
            "committees": [str(c) for c in committees if c],
        })
    out.sort(key=lambda x: (x["datetime"] or "", x["date"]))
    return out


def stage_for(bill_no: str, raw_status: str, history: list[dict]) -> str:
    text = " | ".join(h["action"].lower() for h in history)
    last = history[-1]["action"].lower() if history else ""
    status = (raw_status or "").lower()
    is_res = bill_prefix(bill_no) in ("HR", "SR", "HCR", "SCR")

    if "approved by governor" in text or status == "enacted" or "became law without" in text:
        return "Enacted"
    if "veto" in last and "overrid" not in last:
        return "Vetoed"
    if "overrid" in last:
        return "Veto overridden"
    if status in ("dead", "died") or "died in" in last or "stricken" in last:
        return "Dead"
    if "presented to governor" in text or "enrolled and presented" in text:
        return "Sent to Governor"
    if is_res and "adopted" in text:
        return "Adopted"
    passed = set()
    for h in history:
        a = h["action"].lower()
        if ("final action" in a or "emergency final action" in a) and "passed" in a:
            passed.add((h["chamber"] or "").lower())
    if "conference committee" in text:
        return "In conference"
    if {"house", "senate"} <= passed:
        return "Passed both chambers"
    if "house" in passed:
        return "Passed House"
    if "senate" in passed:
        return "Passed Senate"
    if "committee report" in text:
        return "Reported by committee"
    if "hearing" in text:
        return "Hearing held/scheduled"
    if "referred to committee" in text:
        return "In committee"
    return "Introduced"


def normalize_bill(raw: dict, biennium: str) -> dict | None:
    bill_no = canon_bill_no(str(pick(raw, "BILLNO", "bill_no", "bill_number", "billno", default="")))
    if not bill_no:
        return None
    history = normalize_history(pick(raw, "HISTORY", "history", default=[]))
    sponsors = pick(raw, "SPONSOR_NAMES", "sponsor_names", "sponsors", default=[])
    if isinstance(sponsors, str):
        sponsors = [sponsors]
    sponsors = [s if isinstance(s, str) else str(pick(s, "name", "full_name", default=s)) for s in sponsors]
    original = pick(raw, "ORIGINAL_SPONSOR", "original_sponsor", default=[])
    if isinstance(original, str):
        original = [original]
    original = [o if isinstance(o, str) else str(pick(o, "name", "full_name", default=o)) for o in original]
    prefix = bill_prefix(bill_no)
    rec = {
        "bill_no": bill_no,
        "name": str(pick(raw, "NAME", "name", default=bill_no)),
        "type": TYPE_NAMES.get(prefix, prefix),
        "kind": "Resolution" if prefix in ("HR", "SR", "HCR", "SCR") else "Bill",
        "chamber": "House" if prefix.startswith("H") else "Senate",
        "short_title": str(pick(raw, "SHORTTITLE", "short_title", default="")).strip(),
        "long_title": str(pick(raw, "LONGTITLE", "long_title", default="")).strip(),
        "raw_status": str(pick(raw, "STATUS", "status", default="")),
        "sponsors": sponsors,
        "original_sponsor": original,
        "history": history,
        "has_history": bool(history),
        "url": bill_url(bill_no, biennium),
    }
    finalize(rec)
    return rec


def finalize(rec: dict) -> None:
    h = rec["history"]
    rec["stage"] = stage_for(rec["bill_no"], rec.get("raw_status", ""), h)
    rec["last_action"] = h[-1]["action"] if h else ""
    rec["last_action_date"] = h[-1]["date"] if h else ""
    rec["intro_date"] = h[0]["date"] if h else ""
    committees = []
    for e in h:
        for c in e.get("committees", []):
            if c not in committees:
                committees.append(c)
        m = re.search(r"Referred to Committee on (.+?)(?:$|;|\.)", e["action"])
        if m and m.group(1).strip() not in committees:
            committees.append(m.group(1).strip())
    rec["committees"] = committees


def bill_text(rec: dict) -> str:
    return iter_text(rec.get("short_title"), rec.get("long_title"), rec.get("name"))


# ---------------------------------------------------------------- hearings
def _parse_when(text: str) -> tuple[str, str, str]:
    date = ""
    m = HEARING_DATE_RE.search(text or "")
    if m:
        try:
            date = dt.datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", "%B %d %Y").date().isoformat()
        except ValueError:
            date = ""
    t = TIME_RE.search(text or "")
    r = ROOM_RE.search(text or "")
    return date, (t.group(1).upper().replace(".", "") if t else ""), (r.group(1) if r else "")


def hearings_from_history(rec: dict) -> list[dict]:
    out = []
    for h in rec["history"]:
        a = h["action"]
        if not (str(h.get("code", "")).startswith("misc_he") or a.lower().startswith("hearing")):
            continue
        date, time_, room = _parse_when(a)
        committee = ", ".join(h.get("committees") or []) or ""
        if not committee:
            for c in reversed(rec.get("committees") or []):
                committee = c
                break
        chamber = h.get("chamber") or rec["chamber"]
        if committee and not committee.lower().startswith(chamber.lower()):
            committee = f"{chamber} {committee}"
        out.append({
            "date": date or h["date"],
            "time": time_,
            "room": room,
            "chamber": h.get("chamber") or rec["chamber"],
            "committee": committee,
            "description": a,
            "bills": [rec["bill_no"]],
            "source": "Bill history",
            "url": rec["url"],
        })
    return out


def normalize_hearing(raw: dict) -> dict:
    """A row from /api/v1/hearings/. Live shape (Nov 2026): committee_kpid, committee_title,
    chamber, hearing_date, hearing_time, hearing_datetime, room, status, hearing_type,
    bill_numbers, is_past, streaming."""
    committee = pick(raw, "committee_title", "committee", "committee_name", default="")
    if isinstance(committee, dict):
        committee = pick(committee, "title", "display_name", "name", default="")
    chamber = str(pick(raw, "chamber", default="")).title()
    bills_raw = pick(raw, "bill_numbers", "bills", "measures", default=[])
    bills = []
    for b in bills_raw if isinstance(bills_raw, list) else [bills_raw]:
        s = b if isinstance(b, str) else iter_text(*(v for v in (b.values() if isinstance(b, dict) else []) if isinstance(v, str)))
        no = canon_bill_no(s)
        if no and no not in bills:
            bills.append(no)
    htype = str(pick(raw, "hearing_type", default="")).strip()
    desc = str(pick(raw, "description", "text", "title", "topic", "subject", default=""))
    for m in BILL_RE.finditer(desc):
        no = canon_bill_no(m.group(0))
        if no and no not in bills:
            bills.append(no)
    start = str(pick(raw, "hearing_date", "date", "start_time", "start", "hearing_datetime", "occurred", default=""))
    date = start[:10] if re.match(r"\d{4}-\d{2}-\d{2}", start) else _parse_when(desc)[0]
    time_ = str(pick(raw, "hearing_time", default=""))
    if not time_:
        m = re.match(r"\d{4}-\d{2}-\d{2}[T ](\d{2}):(\d{2})", str(pick(raw, "start_time", "start", default="")))
        if m:
            hh, mm = int(m.group(1)), m.group(2)
            time_ = f"{(hh % 12) or 12}:{mm} {'PM' if hh >= 12 else 'AM'}"
        else:
            time_ = _parse_when(desc)[1]
    if committee and chamber and not str(committee).lower().startswith(chamber.lower()):
        committee = f"{chamber} {committee}"
    status = str(pick(raw, "status", default="")).strip().lower()
    if not desc:
        desc = (htype.rstrip(":") or "Hearing") + (f" {', '.join(bills)}" if bills else "")
    return {
        "date": date,
        "time": time_,
        "room": str(pick(raw, "room", "location", default="") or _parse_when(desc)[2]),
        "chamber": chamber,
        "committee": str(committee),
        "committee_kpid": str(pick(raw, "committee_kpid", default="")),
        "description": desc,
        "status": "Cancelled" if "cancel" in status else ("" if status in ("", "scheduled") else status.title()),
        "bills": bills,
        "source": "Hearing schedule",
        "stream_url": str(pick(raw, "streaming", "stream_url", default="")),
        "url": str(pick(raw, "url", default="")) or "",
    }


def hearing_key(h: dict) -> str:
    bills = ",".join(sorted(h.get("bills") or []))
    if bills:
        return f"{h.get('date')}|{bills}"
    return f"{h.get('date')}|{(h.get('committee') or '').lower()}|{(h.get('description') or '')[:60].lower()}"


VOTE_ACTION_RE = re.compile(r"yea|final action|adopted|concurred|nonconcurred|overrid|motion to|passed", re.IGNORECASE)


def has_floor_votes(rec: dict) -> bool:
    """Only bills with floor action can have roll calls; skip the rest to save API calls."""
    return any(VOTE_ACTION_RE.search(h["action"]) for h in rec.get("history", []))


def normalize_vote(raw: dict) -> dict:
    tally = pick(raw, "tally", default={}) or {}
    je = pick(raw, "journal_element", default={}) or {}
    occurred = str(pick(raw, "occurred", default="") or pick(je, "occurred", default=""))
    def n(k):
        try:
            return int(tally.get(k) or 0)
        except (TypeError, ValueError):
            return 0
    return {
        "date": occurred[:10],
        "chamber": str(pick(raw, "chamber", default="") or pick(je, "chamber", default="")).title(),
        "motion": str(pick(raw, "motion", default="")).strip(),
        "action": str(pick(je, "action_label", default="")).strip().rstrip(";"),
        "yea": n("yea"), "nay": n("nay"), "present": n("present"),
        "absent": n("absent"), "not_voting": n("not_voting"),
        "rcs_num": str(pick(raw, "rcs_num", default="")),
        "journal_page": pick(je, "page_number", default=None),
    }
