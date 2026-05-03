# ClaimGPT — Demo Prep Checklist for the Marketing Video

Run through this list **before you hit Record** in OBS. The goal is zero "demo embarrassment" moments on camera.

---

## 1 · Backend & data

- [ ] PostgreSQL up (`docker compose ps` or whatever your local setup uses).
- [ ] All FastAPI services healthy. Quick check:
  ```sh
  curl -s http://127.0.0.1:8000/health | jq
  ```
- [ ] **Run the seed.** Populates 50 realistic Indian-context claims:
  ```sh
  source .venv/bin/activate
  python infra/scripts/seed_tpa_test_data.py
  ```
- [ ] **Pick the three hero claims** and note their UUIDs (you will paste them into the URL during recording):

  | Hero | Specialty   | Hospital               | Status                 | Risk     | Used in beat |
  | ---- | ----------- | ---------------------- | ---------------------- | -------- | ------------ |
  | A    | Cardiac     | Apollo Chennai         | UPLOADED → COMPLETED   | MODERATE | 3, 4, 5      |
  | B    | Orthopedic  | Fortis Mumbai          | COMPLETED              | LOW      | 6            |
  | C    | Oncology    | Medanta Gurugram       | MANUAL_REVIEW_REQUIRED | HIGH     | 5 (close-up) |

  > Pick by category from the seed output and capture each UUID in this file under "Hero claim IDs" below.

  **Hero claim IDs (fill in after seeding):**
  - Hero A — `__________________________________`
  - Hero B — `__________________________________`
  - Hero C — `__________________________________`

- [ ] **Stage 4 sample upload files** in `~/Desktop/ClaimGPT_Demo/`. Names matter — they appear on screen:
  - `Discharge_Summary_Apollo.pdf`
  - `Hospital_Bill_Apollo.pdf`
  - `Lab_Reports_Cardiac_Panel.pdf`
  - `Prescription_Cardiology.pdf`

  > Copy these from any existing real-world test PDFs you have. Strip any actual PII first.

## 2 · Demo user

- [ ] Create a clean demo user via the signup modal: **"Dr. Anya Reddy"**, role *TPA Reviewer*, avatar set (use any neutral professional headshot).
- [ ] Sign in as Dr. Reddy, then **clear all notification badges** (open and dismiss the bell, settle any toasts).
- [ ] Confirm the topbar greeting reads **"Welcome, Dr. Reddy"** — not "demo" / "test" / "azhar".

## 3 · App polish (one-time)

- [ ] **Light mode on.** Glass effect reads cleaner than dark on camera. Toggle via the theme switcher and refresh.
- [ ] Hard-refresh both pages (`Cmd + Shift + R`) so the v6/v7/v8 right-panel + the new TPA liquid-glass CSS render fully:
  ```sh
  curl -s -o /dev/null -w "main %{http_code}\n" http://127.0.0.1:3000/
  curl -s -o /dev/null -w "tpa  %{http_code}\n" http://127.0.0.1:3000/tpa
  ```
- [ ] No console errors. Open DevTools, refresh, confirm the Console tab is clean (warnings ok, errors not). Close DevTools before recording.
- [ ] No half-loaded states: brain-report buttons all visible, no spinners stuck, all KPI cards have numbers.
- [ ] No `localhost:3000` visible in the URL bar during recording. Two options:
  1. **Hide the URL bar entirely** with Chrome → View → Always Show Toolbar (off) + F11 fullscreen.
  2. **Mask via /etc/hosts** to make the URL read prettier:
     ```sh
     # Append to /etc/hosts (requires sudo)
     127.0.0.1   app.claimgpt.local
     ```
     Then visit `http://app.claimgpt.local:3000`. Add a `next.config.js` allowedDevOrigins entry if Next complains.

## 4 · Recording environment (macOS)

- [ ] **Resolution.** Set your display to a 1920×1080 mode for the recording. (System Settings → Displays → Scaled → "More Space" / "Default" — pick the one that gives you 1920×1080 effective.)
- [ ] **Browser.** Chrome in **Incognito** with all extensions disabled, bookmarks bar hidden (`Cmd + Shift + B`), zoom 100%.
- [ ] **System.**
  - [ ] **Do Not Disturb** on (Focus → Do Not Disturb).
  - [ ] **Dock auto-hide** on (`Cmd + Option + D`).
  - [ ] **Menu bar auto-hide** on (System Settings → Control Center → Automatically hide menu bar → Always).
  - [ ] **Cursor highlighter** on. Recommend the free macOS app *Cursor Pro* or *Mouseposé* — adds a subtle halo around the cursor so viewers can follow clicks.
  - [ ] **Click highlighter** on. Same apps usually offer click-radial animation.
- [ ] **OBS Studio settings.**
  - [ ] Output → Recording → 1080p60, MP4 container, hardware H.264 encoder.
  - [ ] Audio → Sample rate 48 kHz.
  - [ ] Scenes → one scene per beat (Beat-2-BRoll, Beat-3-Upload, Beat-4-Pipeline, Beat-5-Brain, Beat-6-IRDAI, Beat-7-Stats). Makes the Descript edit faster.
  - [ ] Hotkeys → bind a Stop hotkey somewhere out of the way (`F10`).

## 5 · Per-take dry-run

For each beat (3, 4, 5, 6), do **one full take with no edits**, watch it back, and confirm:

- [ ] Cursor moves smoothly — no jitter, no overshoot.
- [ ] Scrolls are smooth (use trackpad two-finger glide, not mouse wheel).
- [ ] No accidental hover-tooltip popups in the frame.
- [ ] No real PII visible (check seed data once more — names should look realistic but not match real patients).
- [ ] Demo data reads as believable: amounts in ₹, hospital names recognizable, dates within the last few months.

## 6 · Pre-flight checklist (10 min before recording)

- [ ] DND on, all chat apps quit (Slack, Teams, Discord — they will steal focus and ping the screen).
- [ ] Phone in another room.
- [ ] Water nearby; you may need to do voiceover takes too.
- [ ] OBS scene set to first beat, recording paused, audio gain checked.
- [ ] Three hero claim UUIDs in a sticky note ready to paste.
- [ ] Sample documents folder open in Finder, ready to drag.

---

## Hand-off

Once recording is done, drop the OBS clips into `marketing/video/raw/` and Descript-import for editing. The next file to follow is `02_shot_list_and_storyboard.md` (mapping of OBS scene → final beat) — generate it on demand if needed.
