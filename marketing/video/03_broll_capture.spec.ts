/**
 * ClaimGPT — Marketing video b-roll capture
 * --------------------------------------------------------------
 * Records short, deterministic 1080p UI clips for cutaway editing.
 *
 * Auth: bypasses SSO by injecting the Next.js dev-mode session
 * (`sessionStorage.dev_user` + `access_token`) before each page
 * navigates. No interactive login required.
 *
 * Run from /Users/azhar/claimgpt/marketing/video:
 *   npm install
 *   npx playwright install chromium
 *   npm run broll                      # all 7 clips
 *   npm run broll:single -- broll-01-  # one clip by name pattern
 *   npm run convert                    # WebM -> MP4 H.264
 */

import { test, expect, type Page } from "@playwright/test";
import * as fs from "fs";
import * as path from "path";

// ────────────────────────────────────────────────────────────────
// CONFIG
// ────────────────────────────────────────────────────────────────
const CONFIG = {
  baseURL: "http://127.0.0.1:3000",
  outputDir: path.resolve(__dirname, "raw/broll"),
  // Sample upload files for the drag-drop beat. Optional — if any are
  // missing, the upload clip is skipped.
  sampleDocs: [
    path.resolve(process.env.HOME || "", "Desktop/ClaimGPT_Demo/Discharge_Summary_Apollo.pdf"),
    path.resolve(process.env.HOME || "", "Desktop/ClaimGPT_Demo/Hospital_Bill_Apollo.pdf"),
    path.resolve(process.env.HOME || "", "Desktop/ClaimGPT_Demo/Lab_Reports_Cardiac_Panel.pdf"),
    path.resolve(process.env.HOME || "", "Desktop/ClaimGPT_Demo/Prescription_Cardiology.pdf"),
  ],
};

const DEV_USER = {
  sub: "dev-approver-001",
  email: "approver@claimgpt.dev",
  name: "Dr. Anya Reddy",
  preferred_username: "approver",
  given_name: "Anya",
  family_name: "Reddy",
  roles: ["APPROVER", "REVIEWER", "VIEWER"],
};

// ────────────────────────────────────────────────────────────────
// Setup
// ────────────────────────────────────────────────────────────────
test.beforeAll(() => {
  fs.mkdirSync(CONFIG.outputDir, { recursive: true });
});

test.beforeEach(async ({ context }, testInfo) => {
  // Tests in the broll-00 group capture the SSO/login experience itself, so
  // we must NOT inject the dev session for them.
  if (testInfo.title.startsWith("broll-00")) return;

  // Inject dev session into sessionStorage before any page script runs.
  // This bypasses the SSO splash and lands us straight on the dashboard.
  await context.addInitScript(({ user }) => {
    try {
      sessionStorage.setItem("dev_user", JSON.stringify(user));
      sessionStorage.setItem("access_token", "dev-token");
    } catch {
      /* ignore — sessionStorage unavailable in some sandbox modes */
    }
  }, { user: DEV_USER });
});

test.afterEach(async ({ page }, testInfo) => {
  // Move the recorded video to raw/broll/<test-title>.webm
  await page.close().catch(() => {});
  const video = page.video();
  if (!video) return;
  try {
    const src = await video.path();
    const dst = path.join(CONFIG.outputDir, `${testInfo.title}.webm`);
    fs.copyFileSync(src, dst);
    // eslint-disable-next-line no-console
    console.log(`  ▸ saved ${path.relative(process.cwd(), dst)}`);
  } catch {
    /* video may not exist for skipped tests */
  }
});

// ────────────────────────────────────────────────────────────────
// Helpers
// ────────────────────────────────────────────────────────────────
async function gotoDashboard(page: Page) {
  await page.goto(`${CONFIG.baseURL}/`, { waitUntil: "domcontentloaded" });
  // Wait until the auth splash is gone (dev session bypasses it instantly,
  // but allow up to 8 s for the React tree to mount).
  await page
    .waitForFunction(() => !document.querySelector(".auth-splash"), { timeout: 8_000 })
    .catch(() => { /* best effort */ });
  await page.waitForLoadState("networkidle").catch(() => {});
}

async function selectFirstClaim(page: Page) {
  const card = page.locator(".claim-card").first();
  await expect(card).toBeVisible({ timeout: 15_000 });
  await card.click();
  await page.waitForTimeout(1_500);
  return card;
}

async function selectClaimByStatus(page: Page, statusRegex: string) {
  const card = page
    .locator(".claim-card", { hasText: new RegExp(statusRegex, "i") })
    .first();
  if (await card.count()) {
    await card.scrollIntoViewIfNeeded();
    await card.click();
    await page.waitForTimeout(1_500);
    return card;
  }
  return selectFirstClaim(page);
}

// ────────────────────────────────────────────────────────────────// 0 — SSO login screen → "Create an account" signup modal
//     (no dev session injected so the real auth UI is captured)
// ─────────────────────────────────────────────────────────────
test("broll-00-login-signup", async ({ page }) => {
  await page.goto(`${CONFIG.baseURL}/`, { waitUntil: "domcontentloaded" });

  // Wait for the SSO login screen to render.
  const loginPage = page.locator(".sso-login-page").first();
  await expect(loginPage).toBeVisible({ timeout: 12_000 });
  await page.waitForTimeout(1_400);

  // 1) Hover the brand panel → establishes context.
  const brand = page.locator(".sso-brand").first();
  if (await brand.count()) {
    await brand.hover();
    await page.waitForTimeout(800);
  }

  // 2) Type a work email so the email field shows live state.
  const email = page.locator("#sso-email").first();
  await expect(email).toBeVisible({ timeout: 6_000 });
  await email.click();
  await email.type("reviewer@bajajallianz.in", { delay: 80 });
  await page.waitForTimeout(900);

  // 3) Hover each SSO provider tile so the brand-coloured affordances animate.
  const providers = page.locator(".sso-provider-btn");
  const provCount = Math.min(await providers.count(), 4);
  for (let i = 0; i < provCount; i++) {
    await providers.nth(i).hover();
    await page.waitForTimeout(450);
  }

  // 4) Click "Create an account" → signup modal opens.
  const signupLink = page.locator(".sso-link-btn").first();
  if (await signupLink.count()) {
    await signupLink.scrollIntoViewIfNeeded().catch(() => {});
    await signupLink.hover();
    await page.waitForTimeout(500);
    await signupLink.click();
    await page.waitForTimeout(1_400);

    // Hover the SSO signup tiles inside the modal.
    const modalSso = page.locator(".signup-modal-sso-btn");
    const msc = Math.min(await modalSso.count(), 3);
    for (let i = 0; i < msc; i++) {
      await modalSso.nth(i).hover();
      await page.waitForTimeout(380);
    }

    // Fill first name / last name / email so the signup form looks active.
    const fname = page.locator("#su-fname").first();
    if (await fname.count()) {
      await fname.click();
      await fname.type("Anya", { delay: 80 });
    }
    const lname = page.locator("#su-lname").first();
    if (await lname.count()) {
      await lname.click();
      await lname.type("Reddy", { delay: 80 });
    }
    const semail = page.locator("#su-email").first();
    if (await semail.count()) {
      await semail.click();
      await semail.type("anya.reddy@medibuddy.in", { delay: 70 });
    }
    await page.waitForTimeout(2_500);

    // Close the signup modal so the camera lands back on the SSO screen.
    const closeBtn = page.locator(".signup-modal-close").first();
    if (await closeBtn.count()) {
      await closeBtn.click();
      await page.waitForTimeout(900);
    } else {
      await page.keyboard.press("Escape").catch(() => {});
      await page.waitForTimeout(900);
    }
  }

  // 5) Final dwell on the login screen so the cut feels intentional.
  await page.waitForTimeout(1_500);
});

// ─────────────────────────────────────────────────────────────// 1 — Drag-and-drop upload (beat 3)
// ────────────────────────────────────────────────────────────────
test("broll-01-upload-dragdrop", async ({ page }) => {
  const presentDocs = CONFIG.sampleDocs.filter((p) => fs.existsSync(p));

  await gotoDashboard(page);

  // Pick a claim first so the right-hand workspace shows real content
  // — prevents an empty white panel behind the drop zone.
  await selectClaimByStatus(page, "APPROVED|MANUAL_REVIEW|SETTLED|PROCESSING");
  await page.waitForTimeout(1_200);

  // Scroll the queue back to the top so the drop zone is fully visible.
  await page.evaluate(() => window.scrollTo({ top: 0, behavior: "smooth" }));
  await page.waitForTimeout(800);

  const dropZone = page.locator(".drop-zone").first();
  await expect(dropZone).toBeVisible({ timeout: 10_000 });
  await dropZone.scrollIntoViewIfNeeded().catch(() => {});

  // Cinematic hover so the drop zone glow + dashed border animate.
  for (let i = 0; i < 3; i++) {
    await dropZone.hover();
    await page.waitForTimeout(800);
    await page.mouse.move(50, 50);
    await page.waitForTimeout(500);
  }
  await dropZone.hover();
  await page.waitForTimeout(1_500);

  // Optionally trigger a real upload — but only if backend writes succeed.
  // The visible toast on failure ruins the shot, so we wrap & dismiss it.
  if (presentDocs.length) {
    const fileInput = page.locator('input[type="file"]').first();
    if (await fileInput.count()) {
      await fileInput.setInputFiles(presentDocs).catch(() => {});
      await page.waitForTimeout(2_500);
      // Hide any error toasts so the camera doesn't catch them.
      await page.evaluate(() => {
        document.querySelectorAll(
          '.toast-error, [class*="toast"][class*="error"], [class*="failed"]'
        ).forEach((el) => ((el as HTMLElement).style.display = "none"));
      });
      await page.waitForTimeout(1_500);
    }
  }
});

// ────────────────────────────────────────────────────────────────
// 2 — Pipeline status pill / processing view (beat 4)
// ────────────────────────────────────────────────────────────────
test("broll-02-pipeline-status-transitions", async ({ page }) => {
  await gotoDashboard(page);
  await selectClaimByStatus(page, "PROCESSING|SUBMITTED");

  const panel = page
    .locator(".chat-panel, .right-panel, .claim-dashboard, .claim-dashboard-stub")
    .first();
  if (await panel.count()) {
    await panel.scrollIntoViewIfNeeded();
    await panel.hover();
  }
  await page.waitForTimeout(5_000);

  await page.mouse.wheel(0, 220);
  await page.waitForTimeout(1_200);
  await page.mouse.wheel(0, 220);
  await page.waitForTimeout(1_500);
});

// ────────────────────────────────────────────────────────────────
// 3 — Reimbursement Brain right-panel scroll (beat 5)
// ────────────────────────────────────────────────────────────────
test("broll-03-brain-report-scroll", async ({ page }) => {
  await gotoDashboard(page);
  await selectClaimByStatus(page, "APPROVED|SETTLED|MANUAL_REVIEW");

  const rightPanel = page.locator(".chat-panel").first();
  await expect(rightPanel).toBeVisible({ timeout: 10_000 });
  await rightPanel.hover();

  for (let i = 0; i < 6; i++) {
    await page.mouse.wheel(0, 220);
    await page.waitForTimeout(750);
  }
  await page.waitForTimeout(1_000);
  await rightPanel.evaluate((el) => el.scrollTo({ top: 0, behavior: "smooth" }));
  await page.waitForTimeout(2_000);
});

// ────────────────────────────────────────────────────────────────
// 4 — Risk meter close-up on a high-risk / manual-review claim (beat 5 inset)
// ────────────────────────────────────────────────────────────────
test("broll-04-risk-meter-high-risk", async ({ page }) => {
  await gotoDashboard(page);
  await selectClaimByStatus(page, "MANUAL_REVIEW|REJECTED");

  const meter = page
    .locator('.cd-risk-card, .risk-meter, [data-testid="risk-meter"]')
    .first();
  if (await meter.count()) {
    await meter.scrollIntoViewIfNeeded();
    await meter.hover();
  }
  await page.waitForTimeout(4_000);
});

// ────────────────────────────────────────────────────────────────
// 5 — IRDAI form preview reveal (beat 6)
// ────────────────────────────────────────────────────────────────
test("broll-05-irdai-form-preview", async ({ page }) => {
  await gotoDashboard(page);
  await selectClaimByStatus(page, "APPROVED|SETTLED|MANUAL_REVIEW");
  await page.waitForTimeout(1_500);

  // Open the Brain Preview modal — that's where the prominent green
  // "IRDA Claim Form · 70 fields · Editable" button lives. Chromium
  // headless can't render the actual PDF inside the iframe, so we focus
  // the camera on the action button itself instead.
  const previewBtn = page
    .locator('.cd-btn-preview, button.preview-btn, button:has-text("Preview")')
    .first();
  await expect(previewBtn).toBeVisible({ timeout: 10_000 });
  await previewBtn.scrollIntoViewIfNeeded().catch(() => {});
  await previewBtn.hover();
  await page.waitForTimeout(700);
  await previewBtn.click();
  await page.waitForTimeout(2_500);

  // Scroll the modal so the camera lands on the IRDA action card.
  const modal = page.locator('.modal-overlay, [role="dialog"]').first();
  if (await modal.count()) {
    await modal.hover();
    for (let i = 0; i < 5; i++) {
      await page.mouse.wheel(0, 240);
      await page.waitForTimeout(550);
    }
  }

  // Find the IRDA Claim Form action button inside the modal and hover it
  // so the gradient + "70 fields" badge animate.
  const irdaCard = page
    .locator('button:has-text("IRDA Claim Form"), .btn-irda')
    .first();
  if (await irdaCard.count()) {
    await irdaCard.scrollIntoViewIfNeeded().catch(() => {});
    for (let i = 0; i < 3; i++) {
      await irdaCard.hover();
      await page.waitForTimeout(700);
      await page.mouse.move(50, 50);
      await page.waitForTimeout(350);
    }
    await irdaCard.hover();
    await page.waitForTimeout(2_000);
  }

  // Final cinematic dwell.
  await page.waitForTimeout(2_500);
});

// ────────────────────────────────────────────────────────────────
// 6 — Send-to-TPA modal (beat 6 outro)
// ────────────────────────────────────────────────────────────────
test("broll-06-send-to-tpa-modal", async ({ page }) => {
  await gotoDashboard(page);
  await selectClaimByStatus(page, "APPROVED|SETTLED|MANUAL_REVIEW");

  await page.keyboard.press("Escape").catch(() => {});

  const sendBtn = page
    .locator('button.cd-btn-send, button:has-text("Send to TPA")')
    .first();
  if (await sendBtn.count()) {
    await sendBtn.scrollIntoViewIfNeeded();
    await sendBtn.click();
  }
  await page.waitForTimeout(2_000);

  const modal = page.locator('.tpa-modal, [role="dialog"]').first();
  if (await modal.count()) {
    await expect(modal).toBeVisible({ timeout: 5_000 });
  }
  const search = page
    .locator(
      '.tpa-modal input, [role="dialog"] input[type="search"], [role="dialog"] input[placeholder*="TPA" i]'
    )
    .first();
  if (await search.count()) {
    await search.click();
    await search.type("MediAssist", { delay: 90 });
  }
  await page.waitForTimeout(3_000);
});

// ────────────────────────────────────────────────────────────────
// 8 — Chat icon (FAB) → ask claim → bot reply (chat feature beat)
// ────────────────────────────────────────────────────────────────
test("broll-08-chat-icon-feature", async ({ page }) => {
  await gotoDashboard(page);
  await selectClaimByStatus(page, "APPROVED|MANUAL_REVIEW|SETTLED|PROCESSING");

  // Briefly hover the floating chat icon so the pulse animation is visible.
  const fab = page.locator(".chat-fab").first();
  await expect(fab).toBeVisible({ timeout: 8_000 });
  await fab.scrollIntoViewIfNeeded().catch(() => {});
  await fab.hover();
  await page.waitForTimeout(1_400);

  // Open the dock.
  await fab.click();
  await page.waitForTimeout(1_200);

  // Type into the chat input and send — gives the camera a clear, on-brand
  // demonstration of the chat feature with a typed question + reply.
  const input = page.locator(
    '.chat-input-bar input[type="text"], .chat-input-bar input:not([type])'
  ).first();
  await expect(input).toBeVisible({ timeout: 6_000 });
  await input.click();
  await input.type("What is the patient's diagnosis on this claim?", { delay: 60 });
  await page.waitForTimeout(800);
  await page.keyboard.press("Enter");

  // Wait for the bot reply to render (best-effort, then idle for cinematic dwell).
  await page.waitForTimeout(6_500);

  // Scroll the conversation a little to show the streaming reply.
  const dock = page.locator(".floating-chat-dock").first();
  if (await dock.count()) {
    await dock.hover();
    await page.mouse.wheel(0, 160);
    await page.waitForTimeout(1_200);
  }
});

// ────────────────────────────────────────────────────────────────
// 7 — TPA portal: search ICICI → row hover → View claim → Bank info card
// ────────────────────────────────────────────────────────────────
test("broll-07-tpa-dashboard", async ({ page }) => {
  await page.goto(`${CONFIG.baseURL}/tpa`, { waitUntil: "domcontentloaded" });
  await page
    .waitForFunction(() => !document.querySelector(".auth-splash"), { timeout: 8_000 })
    .catch(() => {});
  await page.waitForLoadState("networkidle").catch(() => {});

  // 1) Type ICICI in the header search so the table filters live on camera.
  const search = page
    .locator(
      '.tpa-hsearch-input, input[placeholder*="Search" i], input[placeholder*="patient" i]'
    )
    .first();
  if (await search.count()) {
    await search.click();
    await search.type("ICICI", { delay: 110 });
    await page.waitForTimeout(2_400);
    // Clear so all rows are visible again for the next beats.
    await search.fill("");
    await page.waitForTimeout(900);
  }

  // 2) Glide along the first few rows so the liquid-glass hover state pops.
  const rows = page.locator("table tbody tr, .tpa-table tbody tr");
  const total = Math.min(await rows.count(), 4);
  for (let i = 0; i < total; i++) {
    await rows.nth(i).hover();
    await page.waitForTimeout(550);
  }

  // 3) Click the Bank Info button on the first row — reveals the floating card
  //    with bank name / account / IFSC / settlement amount. Stays on the
  //    dashboard so the camera can dwell on the details.
  const bankBtn = page.locator(".tpa-bank-btn").first();
  if (await bankBtn.count()) {
    await bankBtn.scrollIntoViewIfNeeded().catch(() => {});
    await bankBtn.hover();
    await page.waitForTimeout(600);
    await bankBtn.click();
    await page.waitForTimeout(4_500);
    // Dismiss the bank card by clicking the table header.
    await page.mouse.click(50, 50).catch(() => {});
    await page.waitForTimeout(600);
  }

  // 4) Click the View button on the first row — opens the claim summary view.
  //    Done last because it navigates away from the dashboard.
  const viewBtn = page.locator(".tpa-view-btn").first();
  if (await viewBtn.count()) {
    await viewBtn.scrollIntoViewIfNeeded().catch(() => {});
    await viewBtn.hover();
    await page.waitForTimeout(700);
    await viewBtn.click();
    await page.waitForTimeout(4_000);
  }
});

// ────────────────────────────────────────────────────────────────
// 9 — Dashboard "Preview" click → Reimbursement Brain modal scroll
// ────────────────────────────────────────────────────────────────
test("broll-09-dashboard-preview-click", async ({ page }) => {
  await gotoDashboard(page);
  await selectClaimByStatus(page, "APPROVED|MANUAL_REVIEW|SETTLED|PROCESSING");

  // Hover the row's eye icon first to surface the liquid affordance.
  const rowPreview = page.locator(".preview-btn").first();
  if (await rowPreview.count()) {
    await rowPreview.scrollIntoViewIfNeeded().catch(() => {});
    await rowPreview.hover();
    await page.waitForTimeout(900);
  }

  // Click the dashboard "Preview" CTA in the right-panel action bar.
  const previewBtn = page
    .locator('.cd-btn-preview, button.preview-btn, button:has-text("Preview")')
    .first();
  await expect(previewBtn).toBeVisible({ timeout: 8_000 });
  await previewBtn.scrollIntoViewIfNeeded().catch(() => {});
  await previewBtn.hover();
  await page.waitForTimeout(700);
  await previewBtn.click();
  await page.waitForTimeout(2_800);

  // Pan through the Brain modal so the camera lingers on KPIs + parsed fields.
  const modal = page.locator('.modal-overlay, [role="dialog"]').first();
  if (await modal.count()) {
    await modal.hover();
    for (let i = 0; i < 5; i++) {
      await page.mouse.wheel(0, 220);
      await page.waitForTimeout(700);
    }
  }
  await page.waitForTimeout(1_500);
});
