"""Offline end-to-end test with made-up API responses (no internet needed).

    python tests/run_offline_test.py

Copies the project to a temp folder, runs two scans and a monthly report
against canned data, and checks the results. Sample bills are fictional.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent


def hist(date, chamber, action, code=""):
    return {"action_code": code, "chamber": chamber, "status": action,
            "occurred_datetime": f"{date}T10:00:00", "session_date": date, "journal_page_number": ""}


def bill(no, short, long_, status="introduced", history=None, sponsors=None):
    d = {"BILLNO": no, "NAME": no, "SHORTTITLE": short, "LONGTITLE": long_, "STATUS": status,
         "SPONSOR_NAMES": sponsors or ["Committee on Commerce, Labor and Economic Development"]}
    if history is not None:
        d["HISTORY"] = history
    return d


def fixtures_day1():
    return {
        "bill_status.json": {"count": 6, "next": None, "results": [
            bill("SB101", "Extending the angel investor tax credit",
                 "AN ACT concerning income taxation; relating to credits; extending the angel investor tax credit.",
                 history=[hist("2026-01-14", "Senate", "Introduced", "intro_ibc_157"),
                          hist("2026-01-15", "Senate", "Referred to Committee on Assessment and Taxation", "ref_rbc_308")]),
            bill("HB2201", "Establishing a prescription drug affordability board",
                 "AN ACT concerning health and healthcare; establishing the prescription drug affordability board; setting upper payment limits.",
                 history=[hist("2026-01-20", "House", "Introduced", "intro_ibc_157"),
                          hist("2026-01-21", "House", "Referred to Committee on Health and Human Services", "ref_rbc_308"),
                          hist("2026-01-28", "House", "Hearing: Wednesday, February 4, 2026, 1:30 PM Room 112-N", "misc_he_200")]),
            bill("HB2250", "Protecting 340B contract pharmacy arrangements",
                 "AN ACT concerning pharmacy; relating to 340B drug pricing; prohibiting manufacturers from restricting contract pharmacies.",
                 history=[hist("2026-01-22", "House", "Introduced", "intro_ibc_157")]),
            bill("SB150", "Research and development tax credit modernization",
                 "AN ACT concerning taxation; relating to the research and development activities credit."),  # no history -> detail fetch
            bill("HB2300", "Concerning motor vehicle registration fees",
                 "AN ACT concerning motor vehicles; relating to registration fees."),
            bill("SB120", "Matters of conscience for health care providers",
                 "AN ACT concerning health care; relating to conscience protections."),  # must NOT match "science"
        ]},
        "bill_status__sb150.json": {"content": [bill("SB150", "Research and development tax credit modernization",
            "AN ACT concerning taxation; relating to the research and development activities credit.",
            history=[hist("2026-01-26", "Senate", "Introduced", "intro_ibc_157"),
                     hist("2026-01-27", "Senate", "Referred to Committee on Commerce", "ref_rbc_308")])]},
        "search__q=biomanufacturing.json": {"count": 1, "results": [
            {"bill_no": "HB2300", "title": "HB 2300", "snippet": "…a biomanufacturing facility exemption…", "rank": 0.4}]},
        "hearings.json": {"count": 1, "next": None, "results": [
            {"je_slug": "sen-commerce-2026-02-03", "chamber": "senate", "committee": {"title": "Senate Commerce"},
             "start_time": "2026-02-03T10:30:00", "room": "548-S",
             "description": "Informational briefing: Kansas bioscience and biomanufacturing workforce", "bills": []}]},
        "chamber_status.json": {"house": {"in_session": True}, "senate": {"in_session": True}},
    }


def run(root, *args):
    env = dict(os.environ, TRACKER_ROOT=str(root), SITE_URL="https://example.github.io/ks-leg-tracker/")
    r = subprocess.run([sys.executable, "-m", "tracker.scan", "--fixtures", str(root / "fx"), *args],
                       cwd=root, env=env, capture_output=True, text=True)
    print(r.stdout, r.stderr)
    assert r.returncode == 0, "scan failed"


def write_fx(root, fx):
    d = root / "fx"
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir()
    for name, data in fx.items():
        (d / name).write_text(json.dumps(data))


def main():
    root = Path(tempfile.mkdtemp()) / "proj"
    shutil.copytree(SRC, root, ignore=shutil.ignore_patterns(".git", "out", "__pycache__"))
    for p in (root / "docs" / "data").glob("*"):
        p.unlink() if p.is_file() else shutil.rmtree(p)
    shutil.rmtree(root / "reports", ignore_errors=True)

    # ---- Day 1 (in session)
    fx = fixtures_day1()
    write_fx(root, fx)
    run(root, "--today", "2026-02-02")
    data = json.loads((root / "docs/data/bills.json").read_text())
    nos = {b["bill_no"]: b for b in data["bills"]}
    assert set(nos) == {"SB101", "HB2201", "HB2250", "SB150", "HB2300"}, set(nos)
    assert "SB120" not in nos, "conscience should not match science"
    assert nos["SB101"]["topics"] == ["Angel Investors"], nos["SB101"]["topics"]
    assert "R&D Tax Credits" in nos["SB150"]["topics"] and nos["SB150"]["history"], "detail fetch"
    assert set(nos["HB2201"]["topics"]) >= {"Prescription Drug Pricing", "Prescription Drug Affordability"}
    assert "340B" in nos["HB2250"]["topics"]
    assert nos["HB2300"]["match_sources"] == ["Bill text"]
    assert nos["HB2201"]["stage"] == "Hearing held/scheduled", nos["HB2201"]["stage"]
    hear = json.loads((root / "docs/data/hearings.json").read_text())["hearings"]
    assert any("HB2201" in h["bills"] for h in hear) and any("bioscience" in h["description"] for h in hear)
    assert (root / "out/issue_update_title.txt").exists()

    # ---- Day 2: SB101 passes the Senate, a new bill appears
    shutil.rmtree(root / "out")
    fx["bill_status.json"]["results"][0]["HISTORY"] += [
        hist("2026-02-10", "Senate", "Committee Report recommending bill be passed by Committee on Assessment and Taxation", "cr_rsc_281"),
        hist("2026-02-12", "Senate", "Final Action - Passed; Yea: 38 Nay: 2", "fa_fabc_340")]
    fx["bill_status.json"]["results"].append(bill("HB2410", "Kansas artificial intelligence innovation sandbox",
        "AN ACT concerning technology; establishing an artificial intelligence regulatory sandbox.",
        history=[hist("2026-02-11", "House", "Introduced", "intro_ibc_157")]))
    write_fx(root, fx)
    run(root, "--today", "2026-02-12")
    upd = (root / "reports/updates/2026-02-12.md").read_text()
    assert "HB2410" in upd and "Status changes (1)" in upd and "Passed Senate" in upd, upd
    data = json.loads((root / "docs/data/bills.json").read_text())
    sb101 = next(b for b in data["bills"] if b["bill_no"] == "SB101")
    assert sb101["last_changed"] == "2026-02-12" and sb101["first_seen"] == "2026-02-02"

    # ---- Out of session, not a Monday: nothing happens. Monday: weekly scan.
    shutil.rmtree(root / "out", ignore_errors=True)
    fx["chamber_status.json"] = {"house": {"in_session": False}, "senate": {"in_session": False}}
    write_fx(root, fx)
    run(root, "--today", "2026-08-12")  # Wednesday
    assert not (root / "reports/updates/2026-08-12.md").exists()
    run(root, "--today", "2026-08-10")  # Monday
    assert (root / "reports/updates/2026-08-10.md").exists()

    # ---- Monthly report (Feb 2026), generated on first run of March
    run(root, "--today", "2026-03-02")
    mr = (root / "reports/monthly/2026-02.md").read_text()
    assert "Passed a chamber | 1" in mr and "HB2410" in mr, mr
    assert (root / "out/issue_monthly_title.txt").exists()

    print("\nALL CHECKS PASSED")
    print("Test project folder:", root)


if __name__ == "__main__":
    main()
