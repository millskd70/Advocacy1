# Kansas Legislation Tracker

Automatically tracks Kansas bills, resolutions and committee hearings on the topics you choose. It runs free on GitHub:

- **Daily scans during the legislative session** (from the second Monday in January through May 31, plus any special session it detects)
- **Weekly scans out of session** (Mondays)
- **A running list of every matching bill and resolution**, with its current stage and full action history
- **A monthly summary report** for each month the Legislature is in session
- **A web page with filters**: topic checkboxes, Excel-style column filters, keyword search, sorting and CSV export
- **Email alerts** through GitHub Issues whenever something is new or changes

Data comes from the Kansas Legislature's official public API (kslegislature.gov).

Tracked topics: Science, Technology, Angel Investors, R&D Tax Credits, Biotechnology, Bioscience, Biomanufacturing, Prescription Drug Pricing, 340B, and Prescription Drug Affordability.

---

## Setup (about 10 minutes, done once)

The files are already in this repository (`millskd70/Advocacy1`). These steps are easiest on a computer.

### 1. Allow the workflow to save results
**Settings → Actions → General → Workflow permissions** → choose **Read and write permissions** → **Save**.

### 2. Turn on the web page
**Settings → Pages** → under *Build and deployment*, set **Source: Deploy from a branch**, **Branch: main**, folder **/docs** → **Save**.
Your page will be at https://millskd70.github.io/Advocacy1/ (it can take a few minutes to appear the first time).

### 3. Run the first scan
**Actions** tab → if asked, click **I understand my workflows, go ahead and enable them** → click **Kansas legislation scan** on the left → **Run workflow** → **Run workflow**.
The first run takes about 5 minutes. When it finishes with a green check, your page fills in and you get a "tracking started" Issue listing everything found.

### 4. Get email alerts
At the top of the repository, click **Watch → Custom → check Issues → Apply**. GitHub will email you each scan update and monthly report. You can also turn on GitHub mobile app notifications.

### 5. (Optional, recommended) Free API key
Without a key the scanner works but runs slowly (the Legislature limits anonymous use to 30 requests per minute). With a free key it's about 10 times faster.
1. Request a key from the Legislature's API page: https://www.kslegislature.gov/klois/Pages/RESTianAPI.html
2. In your repository: **Settings → Secrets and variables → Actions → New repository secret**. Name: `KS_LEG_API_KEY`, Secret: your key.

---

## Using it

| What you want | Where |
|---|---|
| Browse and filter tracked bills | Your GitHub Pages web page |
| See what changed today | The latest Issue, or `reports/latest-update.md` |
| Monthly report | An Issue on the 1st of each month after an in-session month; also `reports/monthly/` |
| Spreadsheet of everything | **Export CSV** on the web page (exports your current filtered view), or `docs/data/tracked_bills.csv` |
| Run a scan right now | **Actions → Kansas legislation scan → Run workflow** |
| Rebuild a monthly report | **Run workflow** and enter a month like `2027-02` |

**On the web page:**
- **Topics ▼, Stage ▼, Chamber ▼** and the other filter buttons work like Excel's AutoFilter. Uncheck *(Select all)*, check what you want, then tap **OK**. Counts show how many items match each value.
- The **search box** filters by any word in the bill number, titles, sponsors, committees or actions.
- **Changed in last 7 days** shows only recent activity.
- **Found in: Bill text** marks bills that matched only somewhere in their text, not their title. Filter these out if they're noise.
- Tap any row to see its full title, sponsors, why it's tracked, and its complete history.
- Your filters are remembered on each device.

---

## Changing what's tracked

Open `config.yml` in GitHub, click the pencil icon, edit, and commit. Changes apply on the next scan.

- **Add a keyword:** add a line under the topic, like `    - quantum computing`.
- **Add a topic:** add a new name with its own keyword list. It appears as a new checkbox on the page.
- **Too many irrelevant results?** Add phrases to `exclude_keywords`, make keywords more specific (e.g., replace `technology` with `technology innovation`), or set `full_text_search: false` to match titles only.
- **Change the out-of-session scan day:** `weekly_scan_day` (0 = Monday … 6 = Sunday).
- **Change the scan time:** edit the `cron` line in `.github/workflows/scan.yml`. Times are in UTC; `17 11 * * *` is 5:17 AM Central (6:17 AM during daylight time).

---

## Privacy
GitHub Pages on a free account requires a **public** repository, so anyone with the link could see your page and your topic list. The data itself is public legislative information. If you want the page private, you'd need a paid GitHub plan (Pages from private repositories), or you can skip Pages and use the CSV and Issue emails only.

## Good to know
- **New biennium:** in January of odd years (e.g., 2027) the tracker automatically starts a fresh list for the new two-year session and archives the old one in `docs/data/archive/`.
- **Scheduled times are approximate.** GitHub can delay scheduled runs by up to an hour or so when it's busy.
- **Hearings** come from the Legislature's hearing schedule plus hearing notices in each tracked bill's history. Informational briefings on your topics are included when their description matches a keyword.
- **Stages** ("Passed House", "In committee", etc.) are inferred from the official action history. Always confirm important details on the official bill page linked from each row.

## Troubleshooting
- **Red X on a workflow run:** open the run and click the failed step to see the message. The most common cause is step 1 (permissions) not being set.
- **Page shows "No data yet":** the first scan hasn't finished, or Pages isn't set to `main` and `/docs`.
- **No emails:** check the *Watch* setting (step 4) and your GitHub notification settings.

## Files
```
config.yml                     ← your topics and settings
.github/workflows/scan.yml     ← the schedule
tracker/                       ← the scanner (Python)
docs/index.html                ← the web page
docs/data/                     ← data the page reads (updated by each scan)
reports/updates/               ← one Markdown update per scan
reports/monthly/               ← monthly summary reports
tests/run_offline_test.py      ← offline test with sample data
```
