"""Main entry point: python -m tracker.scan [--force] [--monthly YYYY-MM] [--today YYYY-MM-DD]

Runs on a schedule in GitHub Actions. Each run:
  1. decides whether to scan today (daily in session, weekly out of session),
  2. downloads Kansas bill status and finds measures matching your topics,
  3. records what changed since the last scan, and collects hearings,
  4. writes the data the web page reads (docs/data/) and a Markdown update,
  5. on the first run of a month after an in-session month, writes a monthly report.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import datetime as dt
import json
import os
import shutil
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from . import reports
from .api import KansasLegAPI, biennium_for, pick
from .bills import (bill_text, canon_bill_no, finalize, has_floor_votes, hearing_key,
                    hearings_from_history, normalize_bill, normalize_hearing, normalize_vote)
from .matching import TopicMatcher
from .session import in_session_window, month_was_in_session, recent_floor_activity

ROOT = Path(os.environ.get("TRACKER_ROOT", Path(__file__).resolve().parent.parent))
DATA = ROOT / "docs" / "data"
REPORTS = ROOT / "reports"
OUT = ROOT / "out"  # files the workflow turns into GitHub Issues (not committed)
TZ = ZoneInfo("America/Chicago")


def load_json(p: Path, default):
    try:
        return json.loads(p.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def write_json(p: Path, data) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")


def site_url() -> str | None:
    if os.environ.get("SITE_URL"):
        return os.environ["SITE_URL"]
    repo = os.environ.get("GITHUB_REPOSITORY")
    if repo and "/" in repo:
        owner, name = repo.split("/", 1)
        return f"https://{owner.lower()}.github.io/{name}/"
    return None


def chamber_status_in_session(raw) -> bool:
    """Best effort: does the chamber_status endpoint say either chamber is in session?"""
    if raw is None:
        return False
    text = json.dumps(raw).lower()
    return '"in_session": true' in text or "now in session" in text or '"status": "in session"' in text


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="scan even if today is not a scan day")
    ap.add_argument("--monthly", help="(re)build the monthly report for YYYY-MM and exit")
    ap.add_argument("--today", help="pretend today is YYYY-MM-DD (testing)")
    ap.add_argument("--fixtures", help="read API responses from this folder (offline testing)")
    args = ap.parse_args(argv)

    cfg = yaml.safe_load((ROOT / "config.yml").read_text())
    topics_cfg = cfg.get("topics") or {}
    matcher = TopicMatcher(topics_cfg, cfg.get("exclude_keywords") or [])
    topic_names = list(matcher.topics.keys())
    session_end = str(cfg.get("session_end", "05-31"))
    today = dt.date.fromisoformat(args.today) if args.today else dt.datetime.now(TZ).date()
    biennium = biennium_for(today.year)
    state = load_json(DATA / "state.json", {})
    url = site_url()
    OUT.mkdir(exist_ok=True)

    # ---------------------------------------------------- monthly-only rebuild
    if args.monthly:
        y, m = (int(x) for x in args.monthly.split("-"))
        bills = load_json(DATA / "bills.json", {}).get("bills", [])
        hearings = load_json(DATA / "hearings.json", {}).get("hearings", [])
        write_monthly(y, m, bills, hearings, topic_names, url, state, cfg)
        write_json(DATA / "state.json", state)
        return 0

    api = KansasLegAPI(fixtures_dir=args.fixtures)

    # ---------------------------------------------------- should we scan today?
    in_window = in_session_window(today, session_end)
    weekly_day = int(cfg.get("weekly_scan_day", 0))
    prev_month = (today.replace(day=1) - dt.timedelta(days=1))
    monthly_due = (month_was_in_session(prev_month.year, prev_month.month, session_end)
                   and f"{prev_month:%Y-%m}" not in state.get("monthly_reports", []))
    chamber_live = False
    if not in_window:
        chamber_live = chamber_status_in_session(api.chamber_status())
    in_session = in_window or chamber_live or state.get("special_session_active", False)

    if in_session:
        mode = "Daily (in session)"
    elif today.weekday() == weekly_day:
        mode = "Weekly (out of session)"
    elif args.force:
        mode = "Manual"
    elif monthly_due:
        mode = "Monthly report"
    else:
        print(f"{today}: out of session and not the weekly scan day — nothing to do.")
        return 0
    print(f"{today}: {mode} scan for biennium {biennium}")

    # ---------------------------------------------------- new biennium? archive old data
    prev_bills_doc = load_json(DATA / "bills.json", {})
    if prev_bills_doc.get("biennium") and prev_bills_doc["biennium"] != biennium:
        arch = DATA / "archive"
        arch.mkdir(parents=True, exist_ok=True)
        for name in ("bills.json", "hearings.json", "tracked_bills.csv"):
            if (DATA / name).exists():
                shutil.copy(DATA / name, arch / f"{prev_bills_doc['biennium']}_{name}")
        prev_bills_doc = {}
        write_json(DATA / "hearings.json", {"hearings": []})
    prev = {b["bill_no"]: b for b in prev_bills_doc.get("bills", [])}

    # ---------------------------------------------------- 1. all bills, title matching
    raw_list = api.bill_status_list()
    print(f"  downloaded {len(raw_list)} bill-status records")
    all_bills: dict[str, dict] = {}
    for raw in raw_list:
        rec = normalize_bill(raw, biennium)
        if rec:  # one row per bill; keep the one with the most history
            old = all_bills.get(rec["bill_no"])
            if not old or len(rec["history"]) >= len(old["history"]):
                all_bills[rec["bill_no"]] = rec
    if not all_bills and prev:
        print("  ERROR: the API returned no bills; keeping previous data unchanged.")
        return 1

    matches: dict[str, dict] = {}
    for no, rec in all_bills.items():
        t, k = matcher.match(bill_text(rec))
        if t:
            matches[no] = {"topics": t, "keywords": k, "sources": ["Title"]}

    # ---------------------------------------------------- 2. full-text search (optional)
    search_ok = True
    if cfg.get("full_text_search", True):
        failures = 0
        for kw in matcher.all_keywords():
            try:
                results = api.search_bills(kw)
            except Exception as e:
                failures += 1
                print(f"  search failed for '{kw}': {e}")
                continue
            for r in results:
                if isinstance(r, str):
                    s = r
                else:  # only look at identifying fields, never at snippets
                    s = json.dumps({k: v for k, v in r.items()
                                    if any(x in k.lower() for x in ("bill", "name", "id", "url", "slug", "number"))
                                    or k.lower() == "title"})
                no = canon_bill_no(s)
                if not no:
                    continue
                m = matches.setdefault(no, {"topics": [], "keywords": [], "sources": []})
                for t in matcher.topics_for_keyword(kw):
                    if t not in m["topics"]:
                        m["topics"].append(t)
                if kw not in m["keywords"]:
                    m["keywords"].append(kw)
                if "Bill text" not in m["sources"]:
                    m["sources"].append("Bill text")
        search_ok = failures < max(3, len(matcher.all_keywords()) // 2)
        if not search_ok:  # search service down: keep earlier text matches
            for no, b in prev.items():
                if no not in matches and "Bill text" in b.get("match_sources", []):
                    matches[no] = {"topics": b["topics"], "keywords": b["matched_keywords"],
                                   "sources": ["Bill text"]}
    # Keep topic order consistent with config
    for m in matches.values():
        m["topics"] = [t for t in topic_names if t in m["topics"]]

    # ---------------------------------------------------- 3. details for tracked bills
    tracked: list[dict] = []
    for no, m in sorted(matches.items()):
        rec = all_bills.get(no)
        if rec is None or not rec["has_history"]:
            raw = api.bill_status_detail(no)
            if raw:
                detail = normalize_bill(raw, biennium)
                if detail:
                    rec = detail
        if rec is None:
            continue
        rec = dict(rec)
        rec.update(topics=m["topics"], matched_keywords=m["keywords"], match_sources=m["sources"])
        finalize(rec)
        tracked.append(rec)
    print(f"  tracking {len(tracked)} measures")

    # Roll-call votes: fetched once per bill and again only when its history changes.
    vote_cache = load_json(DATA / "votes.json", {}) if prev_bills_doc else {}
    fetched = 0
    for rec in tracked:
        no, sig = rec["bill_no"], f"{len(rec['history'])}|{rec['last_action_date']}"
        cached = vote_cache.get(no)
        if not has_floor_votes(rec):
            rec["votes"] = []
            continue
        if cached and cached.get("sig") == sig:
            rec["votes"] = cached.get("votes", [])
            continue
        try:
            votes = [normalize_vote(v) for v in api.votes(no)]
            votes.sort(key=lambda v: (v["date"], v["rcs_num"]))
            vote_cache[no] = {"sig": sig, "votes": votes}
            rec["votes"] = votes
            fetched += 1
        except Exception as e:
            print(f"  votes unavailable for {no}: {e}")
            rec["votes"] = (cached or {}).get("votes", [])
    vote_cache = {k: v for k, v in vote_cache.items() if k in {b["bill_no"] for b in tracked}}
    print(f"  votes: refreshed {fetched} bills")

    # Special-session detection outside the normal window
    if not in_window:
        active = recent_floor_activity(list(all_bills.values()), today)
        state["special_session_active"] = bool(active or chamber_live)

    # ---------------------------------------------------- 4. what changed?
    today_s = today.isoformat()
    new_bills, changed = [], []
    for b in tracked:
        old = prev.get(b["bill_no"])
        if not old:
            b["first_seen"] = today_s
            b["last_changed"] = today_s
            if prev:  # don't flood the first-ever scan with "new" items
                new_bills.append(b)
            continue
        b["first_seen"] = old.get("first_seen", today_s)
        old_keys = {(h["date"], h["action"]) for h in old.get("history", [])}
        new_acts = [h for h in b["history"] if (h["date"], h["action"]) not in old_keys]
        if new_acts or old.get("stage") != b["stage"]:
            b["last_changed"] = today_s
            changed.append((b, new_acts))
        else:
            b["last_changed"] = old.get("last_changed", b["first_seen"])
    first_run = not prev
    cfg_hash = hashlib.sha1(json.dumps([topics_cfg, cfg.get("exclude_keywords"), cfg.get("full_text_search", True),
                                        "v2"], sort_keys=True, default=str).encode()).hexdigest()[:12]
    settings_changed = bool(prev) and state.get("config_hash") != cfg_hash
    state["config_hash"] = cfg_hash

    # ---------------------------------------------------- 5. hearings
    # A hearing is tracked when it is on a tracked bill (title or text matched your keywords)
    # or when the committee name or hearing description itself matches a keyword.
    tracked_by_no = {b["bill_no"]: b for b in tracked}
    lookup = dict(all_bills)
    lookup.update(tracked_by_no)

    def classify(h: dict) -> bool:
        on_tracked = [x for x in h.get("bills", []) if x in tracked_by_no]
        text_topics, text_kws = matcher.match(" ".join([h.get("description", ""), h.get("committee", "")]))
        bill_topics = {t for x in on_tracked for t in tracked_by_no[x]["topics"]}
        topics = [t for t in topic_names if t in set(text_topics) | bill_topics]
        if not topics:
            return False
        kws = []
        for x in on_tracked:
            kws += [k for k in tracked_by_no[x]["matched_keywords"] if k not in kws]
        kws += [k for k in text_kws if k not in kws]
        h["topics"], h["matched_keywords"] = topics, kws
        h["matched_by"] = (["Tracked bill"] if on_tracked else []) + (["Committee / description"] if text_topics else [])
        h["bill_details"] = [{"bill_no": x, "name": lookup[x]["name"],
                              "title": lookup[x]["short_title"] or lookup[x]["long_title"],
                              "url": lookup[x]["url"], "tracked": x in tracked_by_no}
                             for x in h.get("bills", []) if x in lookup]
        if not h.get("url"):
            if h["bill_details"]:
                h["url"] = h["bill_details"][0]["url"]
            elif h.get("committee_kpid"):
                h["url"] = f"https://www.kslegislature.gov/li/{biennium}/committees/{h['committee_kpid']}/"
            else:
                h["url"] = f"https://www.kslegislature.gov/li/{biennium}/"
        return True

    prev_hearings = {hearing_key(h): h for h in load_json(DATA / "hearings.json", {}).get("hearings", [])}
    hearings: dict[str, dict] = {}
    for b in tracked:
        for h in hearings_from_history(b):
            if classify(h):
                hearings[hearing_key(h)] = h
    # Whole biennium so far plus the look-ahead window (a few requests; the feed pages by 500)
    frm = f"{biennium[1:5]}-01-01"
    to = (today + dt.timedelta(days=int(cfg.get("hearings_lookahead_days", 30)))).isoformat()
    schedule_ok = False
    try:
        raw_hearings = api.hearings(frm, to)
        print(f"  downloaded {len(raw_hearings)} scheduled hearings")
        for raw in raw_hearings:
            h = normalize_hearing(raw)
            if not h.get("date") or not classify(h):
                continue
            k = hearing_key(h)
            if k in hearings:  # merge with the bill-history copy; schedule data is richer
                merged = dict(hearings[k])
                merged.update({kk: vv for kk, vv in h.items() if vv})
                merged["source"] = "Hearing schedule"
                hearings[k] = merged
            else:
                hearings[k] = h
        schedule_ok = True
    except Exception as e:
        print(f"  hearing schedule unavailable ({e}); using bill histories only")

    for k, h in prev_hearings.items():  # keep earlier hearings that are still relevant
        if k in hearings:
            continue
        dropped_from_schedule = (schedule_ok and h.get("source") == "Hearing schedule"
                                 and (h.get("date") or "") >= today_s)
        if not dropped_from_schedule and classify(h):  # vanished future hearings were likely cancelled
            hearings[k] = h
    new_hearings = []
    recent_cut = (today - dt.timedelta(days=1)).isoformat()
    for k, h in hearings.items():
        h["first_seen"] = prev_hearings.get(k, {}).get("first_seen", today_s)
        if k not in prev_hearings and not first_run and (h.get("date") or "") >= recent_cut:
            new_hearings.append(h)
    hearing_list = sorted(hearings.values(), key=lambda h: (h.get("date") or "", h.get("time") or ""))
    upcoming = [h for h in hearing_list if (h.get("date") or "") >= today_s][:25]

    # ---------------------------------------------------- 6. write outputs
    now = dt.datetime.now(TZ).isoformat(timespec="minutes")
    for b in tracked:
        b.pop("has_history", None)
    if first_run or prev_bills_doc.get("biennium") != biennium:
        state["first_scan"] = today_s
    write_json(DATA / "bills.json", {
        "generated_at": now, "scan_date": today_s, "scan_mode": mode, "biennium": biennium,
        "first_scan": state.get("first_scan", today_s),
        "in_session": in_session, "topics": topic_names, "count": len(tracked), "bills": tracked,
    })
    write_json(DATA / "votes.json", vote_cache)
    write_json(DATA / "hearings.json", {"generated_at": now, "topics": topic_names,
                                        "hearings": hearing_list})
    with open(DATA / "tracked_bills.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Bill", "Type", "Chamber", "Short title", "Topics", "Stage", "Last action",
                    "Last action date", "Sponsors", "Matched keywords", "Found in", "Link"])
        for b in tracked:
            w.writerow([b["name"], b["type"], b["chamber"], b["short_title"] or b["long_title"],
                        "; ".join(b["topics"]), b["stage"], b["last_action"], b["last_action_date"],
                        "; ".join(b["sponsors"]), "; ".join(b["matched_keywords"]),
                        "; ".join(b["match_sources"]), b["url"]])

    update_md = reports.scan_update(today_s, mode, url, new_bills, changed, new_hearings,
                                    upcoming, len(tracked), settings_changed=settings_changed)
    if first_run:
        update_md += ("\n_This was the first scan, so everything currently tracked is the "
                      "starting baseline. Future updates will list only new and changed items._\n")
    (REPORTS / "updates").mkdir(parents=True, exist_ok=True)
    (REPORTS / "updates" / f"{today_s}.md").write_text(update_md)
    (REPORTS / "latest-update.md").write_text(update_md)

    if cfg.get("create_github_issues", True) and (new_bills or changed or new_hearings or first_run):
        n = len(new_bills) + len(changed) + len(new_hearings)
        title = (f"KS legislation: tracking started ({len(tracked)} items)" if first_run
                 else f"KS legislation: tracking updated for new keywords ({len(new_bills)} added)"
                 if settings_changed else f"KS legislation update {today_s}: {n} new/changed")
        (OUT / "issue_update_title.txt").write_text(title)
        (OUT / "issue_update_body.md").write_text(update_md[:60000])

    state.update(last_scan=now, last_mode=mode, api_requests=api.request_count)
    if monthly_due:
        write_monthly(prev_month.year, prev_month.month, tracked, hearing_list, topic_names, url,
                      state, cfg)
    write_json(DATA / "state.json", state)
    print(f"  done: {len(new_bills)} new, {len(changed)} changed, {len(new_hearings)} new hearings; "
          f"{api.request_count} API requests")
    return 0


def write_monthly(y, m, bills, hearings, topic_names, url, state, cfg):
    md = reports.monthly_report(y, m, bills, hearings, topic_names, url)
    (REPORTS / "monthly").mkdir(parents=True, exist_ok=True)
    (REPORTS / "monthly" / f"{y}-{m:02d}.md").write_text(md)
    done = state.setdefault("monthly_reports", [])
    if f"{y}-{m:02d}" not in done:
        done.append(f"{y}-{m:02d}")
    if cfg.get("create_github_issues", True):
        OUT.mkdir(exist_ok=True)
        (OUT / "issue_monthly_title.txt").write_text(f"KS legislation monthly report — {y}-{m:02d}")
        (OUT / "issue_monthly_body.md").write_text(md[:60000])
    print(f"  wrote monthly report {y}-{m:02d}")


if __name__ == "__main__":
    sys.exit(main())
