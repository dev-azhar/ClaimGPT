# ClaimGPT — Marketing Video Bundle

Everything you need to ship the **60-second hero product video** plus three audience-specific re-cuts (TPA · Hospital RCM · Investor).

## Files in this folder

| File                                               | Purpose                                                                                            |
| -------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| `01_script_voiceover.md`                           | Master 60 s VO script + 3 audience re-cuts + ElevenLabs pronunciation notes + soundtrack guidance. |
| `02_demo_prep_checklist.md`                        | Run this end-to-end **before recording** — seed data, demo user, app polish, OBS settings.         |
| `03_broll_capture.spec.ts`                         | Playwright script that captures 7 deterministic 1080p b-roll clips for cutaways.                   |
| `playwright.config.ts` · `package.json` · `.gitignore` | Playwright project scaffolding.                                                                    |

## Workflow at a glance

1. **Pre-prod.** Read `01_script_voiceover.md`. Generate VO in ElevenLabs (~$5 of credits). License music (Artlist ~$10/mo).
2. **Demo prep.** Walk through `02_demo_prep_checklist.md` — seed the database, pick three hero claims, polish the app, set up OBS.
3. **Hero takes.** Record beats 3, 4, 5, 6 manually with OBS following the storyboard in `01_script_voiceover.md`. Multiple takes per beat.
4. **B-roll.** Run the Playwright capture for crisp, deterministic cutaways:

   ```sh
   cd marketing/video
   npm install
   npx playwright install chromium
   # First time only — sign in as Dr. Anya Reddy and save auth state
   npm run auth
   # Capture all 7 b-roll clips
   npm run broll
   # Convert WebM → MP4 H.264 for Descript / Premiere / Final Cut
   npm run convert
   ```

5. **Edit.** Drop OBS clips and Playwright b-roll into Descript. Align with the VO transcript paragraph by paragraph. Apply Studio Sound to the VO.
6. **Motion graphics.** Build the 5 s intro, 10 s outro, and the three stat-card animations in Canva or Runway.
7. **Polish.** Burn in captions, color pass, normalize to −14 LUFS, export 1080p60 H.264.
8. **Re-cuts.** Derive the TPA (25 s 9:16), Hospital RCM (20 s 9:16), and Investor (15 s 16:9) cuts from the same source footage.
9. **Distribute.** YouTube (unlisted → public), homepage embed, three staggered LinkedIn posts, investor deck slide.

## Verified-stat reference

For the stat-card overlay in beat 7, only use these claims — they have been verified against the codebase:

| Claim                                | Source                                                     | Notes                                                                                                          |
| ------------------------------------ | ---------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| **~120 ms medical coding (avg)**     | [docs/benchmark_and_change_summary.md](../../docs/benchmark_and_change_summary.md) | 10-claim sample, 50-claim full validation pending. Honest framing: "around 120 ms." Avoid "sub-100" — overclaim. |
| **10 deterministic validation rules** | [services/validator/app/rules.py](../../services/validator/app/rules.py) | R001–R010 registered in `RULES`.                                                                               |
| **40+ editable IRDAI AcroForm fields** | [services/submission/app/irda_pdf_modern.py](../../services/submission/app/irda_pdf_modern.py) | 46 named text fields verified across Sections A/B/C/D/F + H. Original "70" claim included radios + checkboxes + signatures across both Parts and was not strictly verified.    |

Do **not** put numbers on screen unless they are in this table.

## Budget recap

| Item             | Cost                            |
| ---------------- | ------------------------------- |
| ElevenLabs VO    | ~$5 (one-time credits)          |
| Descript Pro     | $24 / month (cancel after ship) |
| Canva Pro or Runway | $12–15 / month                  |
| Artlist / Epidemic music | $10–15 / month            |
| **Total** | **≤ $60** for one production cycle |

Reference quote for an agency-produced 60s product video: $3,000–$10,000+. The DIY toolchain replaces it without sacrificing quality.
