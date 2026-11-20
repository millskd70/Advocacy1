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
            bill("SB175", "Creating workforce development grants for advanced manufacturing and biology programs",
                 "AN ACT concerning economic development; relating to workforce training.",
                 history=[hist("2026-01-29", "Senate", "Introduced", "intro_ibc_157")]),
            bill("SB120", "Matters of conscience for health care providers",
                 "AN ACT concerning health care; relating to conscience protections."),  # must NOT match "science"
        ]},
        "bill_status__sb150.json": {"content": [bill("SB150", "Research and development tax credit modernization",
            "AN ACT concerning taxation; relating to the research and development activities credit.",
            history=[hist("2026-01-26", "Senate", "Introduced", "intro_ibc_157"),
                     hist("2026-01-27", "Senate", "Referred to Committee on Commerce", "ref_rbc_308")])]},
        # Live shapes (checked against the API in Nov 2026)
        "search__q=biomanufacturing.json": {"q": "biomanufacturing", "biennium": "b2025_26", "bills": {"count": 1, "results": [
            {"number": "HB2300", "type": "bill", "chamber": "House", "shorttitle": "Concerning motor vehicle registration fees",
             "url": "/bills/HB2300/", "rank": 0.4, "match_snippet": "Concerning motor vehicle"}]}},
        "hearings.json": {"count": 3, "next_offset": None, "previous_offset": None, "results": [
            {"committee_kpid": "ctte_h_hhs_1", "committee_title": "Health and Human Services", "chamber": "House",
             "hearing_date": "2026-02-04", "hearing_time": "1:30 PM", "hearing_datetime": "2026-02-04T13:30:00Z",
             "room": "112-N", "status": "scheduled", "hearing_type": "Hearing on:", "bill_numbers": ["HB2201"],
             "is_past": True, "streaming": "http://example.invalid/room112N"},
            {"committee_kpid": "ctte_jt_it_1", "committee_title": "Joint Committee on Information Technology", "chamber": "Joint",
             "hearing_date": "2026-02-05", "hearing_time": "9:00 AM", "hearing_datetime": "2026-02-05T09:00:00Z",
             "room": "142-S", "status": "scheduled", "hearing_type": "Hearing on:", "bill_numbers": ["HB2300"],
             "is_past": True, "streaming": ""},
            {"committee_kpid": "ctte_h_tax_1", "committee_title": "Taxation", "chamber": "House",
             "hearing_date": "2026-02-06", "hearing_time": "3:30 PM", "hearing_datetime": "2026-02-06T15:30:00Z",
             "room": "346-S", "status": "scheduled", "hearing_type": "Hearing on:", "bill_numbers": ["HB2999"],
             "is_past": True, "streaming": ""}]},
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
    assert set(nos) == {"SB101", "HB2201", "HB2250", "SB150", "HB2300", "SB175"}, set(nos)
    assert "SB120" not in nos, "conscience should not match science"
    assert nos["SB101"]["topics"] == ["Angel Investors"], nos["SB101"]["topics"]
    assert "R&D Tax Credits" in nos["SB150"]["topics"] and nos["SB150"]["history"], "detail fetch"
    assert set(nos["HB2201"]["topics"]) >= {"Prescription Drug Pricing", "Prescription Drug Affordability"}
    assert "340B" in nos["HB2250"]["topics"]
    assert nos["HB2300"]["match_sources"] == ["Bill text"]
    assert nos["HB2201"]["stage"] == "Hearing held/scheduled", nos["HB2201"]["stage"]
    hear = json.loads((root / "docs/data/hearings.json").read_text())["hearings"]
    h2201 = [h for h in hear if "HB2201" in h["bills"]]
    assert len(h2201) == 1 and h2201[0]["source"] == "Hearing schedule" and h2201[0]["room"] == "112-N", h2201
    assert h2201[0]["bill_details"][0]["title"].startswith("Establishing a prescription drug"), h2201
    assert h2201[0]["committee"] == "House Health and Human Services"
    it = [h for h in hear if "Information Technology" in h["committee"]]
    assert it and "Technology" in it[0]["topics"], it
    assert not any("HB2999" in h["bills"] for h in hear), "untracked bill in non-matching committee"
    assert nos["SB175"]["topics"] == ["Science", "Workforce Development", "Advanced Manufacturing"], nos["SB175"]["topics"]
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

    # ---- Keyword change: new matches are labeled as such, not as new bills
    shutil.rmtree(root / "out", ignore_errors=True)
    cfgp = root / "config.yml"
    cfgp.write_text(cfgp.read_text().replace("    - quantum\n", "    - quantum\n    - registration fees\n"))
    fx["bill_status.json"]["results"].append(bill("HB2420", "Changing motor vehicle registration fees",
        "AN ACT concerning motor vehicles.", history=[hist("2026-02-12", "House", "Introduced", "intro_ibc_157")]))
    write_fx(root, fx)
    run(root, "--today", "2026-02-13")
    upd = (root / "reports/updates/2026-02-13.md").read_text()
    assert "Now tracked because your keywords" in upd and "HB2420" in upd, upd
    assert "keywords" in (root / "out/issue_update_title.txt").read_text()

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
