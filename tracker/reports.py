"""Markdown scan updates and monthly summary reports."""
from __future__ import annotations

import calendar
from collections import Counter, defaultdict


def _bill_line(b: dict) -> str:
    title = b.get("short_title") or b.get("long_title") or ""
    topics = ", ".join(b.get("topics", []))
    return f"- **[{b['name']}]({b['url']})** — {title}  \n  _{b['stage']}_ · Topics: {topics}"


def _hearing_line(h: dict) -> str:
    when = " ".join(x for x in (h.get("date"), h.get("time")) if x)
    where = f", Room {h['room']}" if h.get("room") else ""
    bills = ", ".join(h.get("bills") or [])
    desc = (h.get("description") or "").strip()
    bills = f" — {bills}" if bills else (f" — {desc[:140]}" if desc else "")
    return f"- **{when}** · {h.get('committee') or h.get('chamber') or 'Committee'}{where}{bills}"


def scan_update(today: str, mode: str, site_url: str | None, new_bills: list[dict],
                changed: list[tuple[dict, list[dict]]], new_hearings: list[dict],
                upcoming: list[dict], total: int) -> str:
    lines = [f"# Kansas legislation scan — {today}", "",
             f"Scan type: **{mode}** · Tracked items: **{total}**", ""]
    if site_url:
        lines += [f"Full filterable list: {site_url}", ""]
    if not (new_bills or changed or new_hearings):
        lines += ["No new or changed items since the last scan.", ""]
    if new_bills:
        lines += [f"## New bills & resolutions ({len(new_bills)})", ""]
        lines += [_bill_line(b) for b in new_bills] + [""]
    if changed:
        lines += [f"## Status changes ({len(changed)})", ""]
        for b, acts in changed:
            lines.append(_bill_line(b))
            for a in acts[-5:]:
                lines.append(f"  - {a['date']}: {a['chamber']} — {a['action']}")
        lines.append("")
    if new_hearings:
        lines += [f"## Newly posted hearings ({len(new_hearings)})", ""]
        lines += [_hearing_line(h) for h in new_hearings] + [""]
    if upcoming:
        lines += ["## Upcoming hearings", ""]
        lines += [_hearing_line(h) for h in upcoming] + [""]
    return "\n".join(lines)


def monthly_report(year: int, month: int, bills: list[dict], hearings: list[dict],
                   topics: list[str], site_url: str | None) -> str:
    prefix = f"{year}-{month:02d}"
    label = f"{calendar.month_name[month]} {year}"

    introduced = [b for b in bills if (b.get("intro_date") or "").startswith(prefix)]
    acted = []
    for b in bills:
        acts = [h for h in b["history"] if h["date"].startswith(prefix)]
        if acts:
            acted.append((b, acts))
    month_hearings = sorted([h for h in hearings if (h.get("date") or "").startswith(prefix)],
                            key=lambda h: (h["date"], h.get("time", "")))

    def has(acts, *words):
        return any(any(w in a["action"].lower() for w in words) for a in acts)

    passed = [(b, a) for b, a in acted if has(a, "final action") and has(a, "passed")]
    adopted = [(b, a) for b, a in acted if b["kind"] == "Resolution" and has(a, "adopted")]
    enacted = [(b, a) for b, a in acted if has(a, "approved by governor", "became law without")]
    vetoed = [(b, a) for b, a in acted if has(a, "vetoed")]
    failed = [(b, a) for b, a in acted if has(a, "failed", "died", "stricken")]

    by_topic = defaultdict(list)
    for b, _ in acted:
        for t in b.get("topics", []):
            by_topic[t].append(b)
    stage_counts = Counter(b["stage"] for b in bills)

    L = [f"# Monthly legislative summary — {label}", ""]
    if site_url:
        L += [f"Full filterable list: {site_url}", ""]
    L += ["## At a glance", "",
          f"| Measure | Count |", "|---|---|",
          f"| New tracked bills & resolutions introduced | {len(introduced)} |",
          f"| Tracked measures with any action | {len(acted)} |",
          f"| Hearings on tracked topics | {len(month_hearings)} |",
          f"| Passed a chamber | {len(passed)} |",
          f"| Resolutions adopted | {len(adopted)} |",
          f"| Signed into law | {len(enacted)} |",
          f"| Vetoed | {len(vetoed)} |",
          f"| Failed / died | {len(failed)} |", ""]

    L += ["## Activity by topic", ""]
    any_topic = False
    for t in topics:
        items = by_topic.get(t, [])
        if not items:
            continue
        any_topic = True
        L.append(f"### {t} ({len(items)})")
        for b in items:
            L.append(f"- [{b['name']}]({b['url']}) — {b.get('short_title') or b.get('long_title')} · _{b['stage']}_")
        L.append("")
    if not any_topic:
        L += ["No action on tracked measures this month.", ""]

    def section(title, rows):
        if rows:
            L.extend([f"## {title}", ""])
            for b, a in rows:
                L.append(_bill_line(b))
            L.append("")

    section("Signed into law", enacted)
    section("Vetoed", vetoed)
    section("Passed a chamber", passed)
    section("Resolutions adopted", adopted)
    section("Failed or died", failed)

    if introduced:
        L += ["## Newly introduced", ""] + [_bill_line(b) for b in introduced] + [""]
    if month_hearings:
        L += ["## Hearings", ""] + [_hearing_line(h) for h in month_hearings] + [""]

    L += ["## Where all tracked measures stand now", "", "| Stage | Count |", "|---|---|"]
    L += [f"| {s} | {n} |" for s, n in stage_counts.most_common()] + [""]

    L += ["## Detailed action log", ""]
    for b, acts in sorted(acted, key=lambda x: x[0]["bill_no"]):
        L.append(f"**[{b['name']}]({b['url']})** — {b.get('short_title') or b.get('long_title')}")
        for a in acts:
            L.append(f"- {a['date']} · {a['chamber']} · {a['action']}")
        L.append("")
    return "\n".join(L)
