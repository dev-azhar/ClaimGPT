"""
IRDA Standard Health Insurance Claim Form (Part A + Part B) PDF generator.

Renders a clean, professional auto-filled rendition of the IRDAI mandatory
reimbursement claim form:
  Part A - To be filled by the Insured (Sections A-H)
  Part B - To be filled by the Hospital  (Sections A-F)

Layout strategy: instead of mimicking printed character-boxes (which look
poor when auto-filled with variable-width text), we use a clean tabular
two-column "label | value" presentation per section. This is the same
approach insurers use for digital intake forms - readable, scan-friendly,
and faithful to the IRDAI section/field structure.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any

from fpdf import FPDF

logger = logging.getLogger("submission.irda_pdf")

# ── palette ───────────────────────────────────────────────────────────────
ACCENT = (3, 105, 161)
ACCENT_LIGHT = (224, 242, 254)
SECTION_BG = (30, 41, 59)
SECTION_FG = (255, 255, 255)
LABEL_BG = (243, 244, 246)
VALUE_BG = (255, 255, 255)
BORDER = (203, 213, 225)
SUB_BORDER = (226, 232, 240)
MUTED = (100, 116, 139)
TEXT = (15, 23, 42)
TICK_ON = (3, 105, 161)
TICK_OFF = (203, 213, 225)

# ── provenance / confidence visual cue ──────────────────────────────
AI_FILLED_BG = (254, 252, 232)   # very light amber: "verify this AI-filled value"
AI_FILLED_RULE = (251, 191, 36)  # amber-400 left rule


# ─────────────────────────────────────────────────────────────────────────
# Field-kind specification - per IRDA Master Circular field formats
#   Each entry maps a label-substring (lower-case) to a kind dict that
#   drives MaxLen, validation regex, PDF-JS format/keystroke action, and
#   the tooltip displayed by AcroForm-aware viewers.
# ─────────────────────────────────────────────────────────────────────────
FIELD_SPEC: tuple[tuple[str, dict[str, Any]], ...] = (
    ("pan", {
        "max_len": 10, "regex": r"^[A-Z]{5}[0-9]{4}[A-Z]$",
        "hint": "PAN format: 5 letters + 4 digits + 1 letter (e.g. ABCDE1234F).",
    }),
    ("ifsc", {
        "max_len": 11, "regex": r"^[A-Z]{4}0[A-Z0-9]{6}$",
        "hint": "IFSC format: 4 letters + '0' + 6 alphanumerics (e.g. HDFC0001234).",
    }),
    ("micr", {
        "max_len": 9, "regex": r"^[0-9]{9}$",
        "hint": "MICR is a 9-digit numeric code printed on cheques.",
    }),
    ("account number", {
        "max_len": 18, "regex": r"^[0-9]{9,18}$",
        "hint": "Bank account number (9-18 digits, numeric only).",
    }),
    ("email", {
        "max_len": 64, "regex": r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
        "hint": "Valid e-mail address (e.g. name@example.com).",
    }),
    ("phone", {
        "max_len": 13, "regex": r"^[+0-9 ()\-]{10,13}$",
        "hint": "Mobile / phone number (10-13 digits incl. country code).",
    }),
    ("pin code", {
        "max_len": 6, "regex": r"^[0-9]{6}$",
        "hint": "6-digit India postal PIN code.",
    }),
    ("pincode", {
        "max_len": 6, "regex": r"^[0-9]{6}$", "hint": "6-digit India postal PIN code.",
    }),
    ("policy no", {
        "max_len": 25,
        "hint": "Policy number as printed on the policy schedule.",
    }),
    ("date", {
        "max_len": 11, "format": "date",
        "hint": "Date in dd-mmm-yyyy format (e.g. 15-Aug-2026).",
    }),
    ("time", {
        "max_len": 5,
        "hint": "24-hour time as HH:MM (e.g. 09:30, 18:45).",
    }),
    ("amount", {"format": "currency", "hint": "Amount in INR (rounded to nearest rupee)."}),
    ("sum insured", {"format": "currency", "hint": "Sum insured in INR."}),
    ("cumulative bonus", {"format": "currency", "hint": "Cumulative bonus in INR."}),
    ("icd-10", {
        "max_len": 10, "regex": r"^[A-TV-Z][0-9][0-9AB](\.[0-9A-TV-Z]{1,4})?$",
        "hint": "ICD-10-CM code (e.g. K35.80, E11.9).",
    }),
    ("sl. no", {"max_len": 20}),
    ("certificate", {"max_len": 20}),
)

# Mandatory fields per IRDA Master Circular on Standardisation of
# Health Insurance Claim Forms (June 2020). Marked Required (Ff bit 2).
MANDATORY_LABELS: frozenset[str] = frozenset({
    "policy no.", "insurer / tpa name", "policyholder name", "patient name",
    "hospital name", "date of admission", "date of discharge",
    "primary diagnosis", "total claimed amount", "total claimed",
    "pan", "account number", "ifsc code", "bank name & branch",
    "treating doctor", "reg. no. (state)",
})


def _infer_kind(label: str) -> dict[str, Any]:
    """Return the field-kind spec for a given label (substring match)."""
    s = (label or "").lower()
    spec: dict[str, Any] = {}
    for needle, meta in FIELD_SPEC:
        if needle in s:
            for k, v in meta.items():
                spec.setdefault(k, v)
    spec["required"] = any(m == s.strip() for m in MANDATORY_LABELS)
    return spec


def _s(text: Any) -> str:
    if text is None:
        return ""
    return str(text).encode("latin-1", "replace").decode("latin-1")


# ── data helpers ──────────────────────────────────────────────────────────
_DATE_PATTERNS = (
    "%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%d/%m/%Y",
    "%d-%b-%Y", "%d %b %Y", "%d %B %Y", "%m/%d/%Y",
    "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S",
)


def _parse_date(value: Any) -> datetime | None:
    if not value:
        return None
    v = str(value).strip()
    if not v:
        return None
    for fmt in _DATE_PATTERNS:
        try:
            return datetime.strptime(v[: len(fmt) + 5], fmt)
        except ValueError:
            continue
    m = re.search(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", v)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    m = re.search(r"(\d{1,2})[-/](\d{1,2})[-/](\d{4})", v)
    if m:
        try:
            return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None
    return None


def _fmt_date(value: Any, fmt: str = "%d-%b-%Y") -> str:
    d = _parse_date(value)
    return d.strftime(fmt) if d else (str(value) if value else "")


def _fmt_time(value: Any) -> str:
    if not value:
        return ""
    m = re.search(r"(\d{1,2})[:\.](\d{2})", str(value))
    if m:
        return f"{int(m.group(1)):02d}:{int(m.group(2)):02d}"
    return str(value)


def _pick(d: dict[str, Any], *keys: str) -> str:
    for k in keys:
        v = d.get(k)
        if v not in (None, "", []):
            return str(v)
    return ""


def _to_float(value: Any) -> float:
    if value in (None, "", []):
        return 0.0
    try:
        if isinstance(value, (int, float)):
            return float(value)
        return float(str(value).replace(",", "").replace("Rs.", "").replace("INR", "").strip() or 0)
    except (ValueError, TypeError):
        return 0.0


def _rupees(value: Any, with_symbol: bool = True) -> str:
    n = _to_float(value)
    if n == 0:
        return ""
    s = f"{int(round(n)):,}"
    return f"Rs. {s}" if with_symbol else s


def _yes_no(value: Any) -> bool | None:
    if value in (None, "", []):
        return None
    s = str(value).strip().lower()
    if s in ("yes", "y", "true", "1"):
        return True
    if s in ("no", "n", "false", "0"):
        return False
    return None


# ── PDF base ──────────────────────────────────────────────────────────────
class IRDAClaimPDF(FPDF):
    PAGE_W = 210.0
    PAGE_H = 297.0
    CONTENT_W = 186.0  # 210 - 12 - 12

    def __init__(self):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.set_auto_page_break(auto=True, margin=15)
        self.set_margins(12, 12, 12)
        self.set_text_color(*TEXT)
        # ── editable form-field tracking ──
        # populated by _track_text / _track_check during layout, then
        # consumed by _inject_acroform() after fpdf2 has produced bytes.
        self.acro_fields: list[dict[str, Any]] = []
        self._field_seq: int = 0
        self._used_names: set[str] = set()
        # ── calculation-order tracking (auto-sum of expense rows) ──
        self.expense_field_names: list[str] = []
        self.total_field_name: str | None = None

    def _next_name(self, label: str) -> str:
        self._field_seq += 1
        slug = re.sub(r"[^a-zA-Z0-9]+", "_", label or "f").strip("_").lower()[:38] or "field"
        name = f"{slug}_{self._field_seq:03d}"
        self._used_names.add(name)
        return name

    def _track_text(self, label: str, value: Any, w: float, h: float,
                    multiline: bool = False, align: str = "L",
                    bold: bool = False, font_size: float = 8.4,
                    readonly: bool = False, kind: dict[str, Any] | None = None) -> str:
        """Record a text-field at the *current* cursor position.

        Returns the generated unique field name so callers can reference
        it from calculation-order (``/CO``) lists and JavaScript actions.
        """
        spec = kind if kind is not None else _infer_kind(label)
        name = self._next_name(label)
        sval = _s(value or "")
        # provenance heuristic: any non-empty value at generation time
        # is treated as AI-filled and gets a light-amber background to
        # cue the user to *verify before signing*. Empty values are
        # plain white (user-fillable).
        ai_filled = bool(sval.strip())
        if ai_filled:
            cur_x, cur_y = self.get_x(), self.get_y()
            self.set_fill_color(*AI_FILLED_BG)
            self.rect(cur_x, cur_y, w, h, "F")
            # subtle 0.4mm amber rule on the left edge of the cell
            self.set_fill_color(*AI_FILLED_RULE)
            self.rect(cur_x, cur_y, 0.4, h, "F")
            self.set_xy(cur_x, cur_y)
        self.acro_fields.append({
            "type": "tx",
            "name": name,
            "label": _s(label),
            "page": max(self.page_no(), 1),
            "x": self.get_x(),
            "y": self.get_y(),
            "w": w,
            "h": h,
            "value": sval,
            "multiline": multiline,
            "align": align,
            "bold": bold,
            "font_size": font_size,
            "readonly": readonly,
            "required": bool(spec.get("required")),
            "max_len": spec.get("max_len"),
            "format": spec.get("format"),
            "regex": spec.get("regex"),
            "tooltip": spec.get("hint") or _s(label),
            "ai_filled": ai_filled,
        })
        return name

    def _track_check(self, label: str, x: float, y: float, size: float,
                     checked: bool, group: str | None = None,
                     export_value: str | None = None) -> None:
        """Record a check-box widget. If group is given, fields share name (radio)."""
        if group:
            name = group
        else:
            name = self._next_name(label)
        self.acro_fields.append({
            "type": "chk",
            "name": name,
            "label": _s(label),
            "page": max(self.page_no(), 1),
            "x": x,
            "y": y,
            "w": size,
            "h": size,
            "checked": bool(checked),
            "export_value": export_value or _s(label) or "On",
        })

    # ---------------- chrome ----------------
    def header(self):
        self.set_fill_color(*ACCENT)
        self.rect(0, 0, self.PAGE_W, 2, "F")

    def footer(self):
        self.set_y(-12)
        self.set_draw_color(*BORDER)
        self.set_line_width(0.2)
        self.line(self.l_margin, self.get_y(), self.PAGE_W - self.r_margin, self.get_y())
        self.set_y(-9)
        self.set_font("Helvetica", "I", 7)
        self.set_text_color(*MUTED)
        self.cell(
            0, 4,
            _s(
                f"IRDA Standard Health Insurance Claim Form  |  Auto-filled by ClaimGPT  |  "
                f"Generated {datetime.now().strftime('%d-%b-%Y %H:%M')}  |  Page {self.page_no()}/{{nb}}"
            ),
            align="C",
        )
        self.set_text_color(*TEXT)

    # ---------------- primitives ----------------
    def title_block(self, kind: str, subtitle: str, who_fills: str):
        self.set_y(8)
        self.set_fill_color(*ACCENT)
        self.set_text_color(*SECTION_FG)
        self.set_font("Helvetica", "B", 14)
        self.cell(self.CONTENT_W, 9, _s(f"  CLAIM FORM - {kind}"),
                  fill=True, new_x="LMARGIN", new_y="NEXT")
        self.set_fill_color(*ACCENT_LIGHT)
        self.set_text_color(*TEXT)
        self.set_font("Helvetica", "B", 8.5)
        self.cell(self.CONTENT_W, 5, _s(f"  {subtitle}"),
                  fill=True, new_x="LMARGIN", new_y="NEXT")
        self.set_font("Helvetica", "I", 7.5)
        self.set_text_color(*MUTED)
        self.cell(self.CONTENT_W, 4, _s(f"  {who_fills}"),
                  new_x="LMARGIN", new_y="NEXT")
        self.set_text_color(*TEXT)
        self.ln(3)

    def section_header(self, letter: str, title: str):
        self.set_fill_color(*SECTION_BG)
        self.set_text_color(*SECTION_FG)
        self.set_font("Helvetica", "B", 9)
        self.cell(8, 6.5, _s(letter), fill=True, align="C")
        self.set_fill_color(71, 85, 105)
        self.cell(self.CONTENT_W - 8, 6.5, _s(f"  {title}"),
                  fill=True, new_x="LMARGIN", new_y="NEXT")
        self.set_text_color(*TEXT)
        self.ln(0.6)

    def kv_row(self, items: list[tuple[str, str]],
               col_widths: list[float] | None = None, row_h: float = 6.0):
        if not items:
            return
        n = len(items)
        if col_widths is None:
            col_widths = [self.CONTENT_W / n] * n
        # widen label column when row has many narrow columns so longer
        # IRDA field labels (e.g. 'Date of Admission') fit without truncation
        label_ratio = 0.42 if n <= 2 else 0.50
        for (label, value), col_w in zip(items, col_widths):
            label_w = col_w * label_ratio
            value_w = col_w - label_w
            self.set_fill_color(*LABEL_BG)
            self.set_text_color(*MUTED)
            self.set_font("Helvetica", "B", 7.2)
            self.cell(label_w, row_h, _s(label), border="LTB", fill=True)
            # Empty value cell (border + fill only). The interactive
            # AcroForm widget overlay will display the editable value.
            self.set_fill_color(*VALUE_BG)
            self._track_text(label, value, value_w, row_h)
            self.cell(value_w, row_h, "", border="TBR", fill=True)
        self.ln(row_h)

    def kv_full(self, label: str, value: str, row_h: float = 6.0,
                label_w: float = 38, bold_value: bool = False,
                multiline: bool = False):
        self.set_fill_color(*LABEL_BG)
        self.set_text_color(*MUTED)
        self.set_font("Helvetica", "B", 7.2)
        self.cell(label_w, row_h, _s(label), border="LTB", fill=True)
        # Editable widget overlays this empty value cell.
        self.set_fill_color(*VALUE_BG)
        value_w = self.CONTENT_W - label_w
        self._track_text(label, value, value_w, row_h,
                         multiline=multiline, bold=bold_value)
        self.cell(value_w, row_h, "", border="TBR", fill=True)
        self.ln(row_h)

    def options_row(self, label: str, options: list[tuple[str, bool]],
                    label_w: float = 75, row_h: float = 6.5,
                    radio_group: str | None = None):
        """Render label + a row of options.

        If ``radio_group`` is given, the options become a single radio-button
        field group (mutually exclusive). Otherwise each option becomes its
        own independent check-box.
        """
        self.set_fill_color(*LABEL_BG)
        self.set_text_color(*MUTED)
        self.set_font("Helvetica", "B", 7.2)
        self.cell(label_w, row_h, _s(label), border="LTB", fill=True)
        x0 = self.get_x()
        y0 = self.get_y()
        value_w = self.CONTENT_W - label_w
        self.set_fill_color(*VALUE_BG)
        self.cell(value_w, row_h, "", border="TBR", fill=True)
        self.set_xy(x0 + 2, y0 + 1)
        self.set_text_color(*TEXT)
        group_name = radio_group if radio_group else None
        for name, checked in options:
            text_w = self.get_string_width(name) + 2.4
            chip_w = text_w + 5
            cx = self.get_x()
            cy = self.get_y()
            # Track an interactive checkbox/radio at the chip position
            self._track_check(
                f"{label} - {name}",
                cx + 0.2, cy + 0.6, 3.0,
                checked,
                group=group_name,
                export_value=name or "On",
            )
            # Print the option label next to the (widget will draw its box).
            self.set_font("Helvetica", "", 7.8)
            self.set_text_color(*MUTED)
            self.set_xy(cx + 4.0, cy)
            self.cell(text_w, 4.5, _s(name))
            self.set_xy(cx + chip_w + 0.6, cy)
        self.set_xy(x0 + value_w, y0)
        self.set_text_color(*TEXT)
        self.ln(row_h)

    def yn_row(self, label: str, value: bool | None,
               label_w: float = 75, row_h: float = 6.5,
               include_na: bool = True):
        """Yes / No (/ Not specified) as a radio-group."""
        if include_na:
            opts = [
                ("Yes", value is True),
                ("No", value is False),
                ("Not specified", value is None),
            ]
        else:
            opts = [("Yes", value is True), ("No", value is False)]
        group = self._next_name(label) + "_grp"
        self.options_row(label, opts, label_w, row_h, radio_group=group)

    def divider(self, gap_before: float = 1.0, gap_after: float = 1.5):
        if gap_before:
            self.ln(gap_before)
        self.set_draw_color(*SUB_BORDER)
        self.set_line_width(0.2)
        y = self.get_y()
        self.line(self.l_margin, y, self.PAGE_W - self.r_margin, y)
        if gap_after:
            self.ln(gap_after)


def _ensure_space(pdf: IRDAClaimPDF, needed: float):
    if pdf.get_y() + needed > pdf.h - pdf.b_margin - 4:
        pdf.add_page()


# ── builders ──────────────────────────────────────────────────────────────
def _build_part_a(pdf: IRDAClaimPDF, ctx: dict[str, Any]) -> None:
    pf = ctx["fields"]

    pdf.add_page()
    pdf.title_block(
        kind="PART A",
        subtitle="HEALTH INSURANCE POLICIES OTHER THAN TRAVEL & PERSONAL ACCIDENT",
        who_fills="To be filled by the INSURED  |  Issue of this Form is not to be taken as an admission of liability",
    )

    # ── visual legend explaining the provenance cue ──
    pdf.set_fill_color(*AI_FILLED_BG)
    pdf.set_draw_color(*AI_FILLED_RULE)
    pdf.set_line_width(0.3)
    pdf.rect(pdf.l_margin, pdf.get_y(), 4, 4, "FD")
    pdf.set_xy(pdf.l_margin + 5, pdf.get_y() - 0.4)
    pdf.set_font("Helvetica", "I", 7)
    pdf.set_text_color(*MUTED)
    pdf.cell(0, 4.8, _s(
        " Amber-tinted cells = AI-extracted values; please verify before signing.  "
        "All cells are editable in any modern PDF reader.  Mandatory fields are marked by the viewer (typically red border)."
    ), new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(*TEXT)
    pdf.ln(2)

    # ── A: Primary Insured ──────────────────────────────────────────
    pdf.section_header("A", "DETAILS OF PRIMARY INSURED")
    claim_type = (_pick(pf, "claim_type", "type_of_claim") or "").lower()
    is_cashless = "cash" in claim_type
    is_reimb = "reimb" in claim_type or not is_cashless
    pdf.options_row("Type of Claim", [
        ("Cashless", is_cashless),
        ("Reimbursement", is_reimb),
    ], radio_group="a_type_of_claim")
    pdf.kv_row([
        ("Policy No.", _pick(pf, "policy_number", "policy_id", "policy_no")),
        ("Sl. No / Cert. No.", _pick(pf, "certificate_no", "sl_no")),
    ])
    pdf.kv_row([
        ("Company / TPA ID", _pick(pf, "tpa_id", "company_id")),
        ("Insurer / TPA Name", _pick(pf, "insurer", "insurance_company", "tpa_name", "payer_name")),
    ])
    pdf.kv_row([
        ("Plan / Type of Policy", _pick(pf, "plan_name", "policy_type")),
        ("Customer ID", _pick(pf, "customer_id", "member_id")),
    ])
    pdf.kv_full("Policyholder Name",
                _pick(pf, "policyholder_name", "primary_insured", "patient_name", "member_name", "insured_name"),
                bold_value=True)
    pdf.kv_full("Address", _pick(pf, "policyholder_address", "address", "patient_address"))
    pdf.kv_row([
        ("City", _pick(pf, "city")),
        ("State", _pick(pf, "state")),
        ("Pin Code", _pick(pf, "pin_code", "pincode", "zip")),
    ])
    pdf.kv_row([
        ("Phone", _pick(pf, "phone", "phone_number", "mobile")),
        ("Email", _pick(pf, "email", "email_id")),
    ])
    pdf.kv_row([
        ("Employee Code", _pick(pf, "employee_code", "member_id")),
        ("Member ID", _pick(pf, "member_id", "patient_id")),
    ])
    pdf.divider()

    # ── B: Insurance History ────────────────────────────────────────
    _ensure_space(pdf, 55)
    pdf.section_header("B", "DETAILS OF INSURANCE HISTORY")
    pdf.yn_row("Currently covered by another Mediclaim/Health Insurance",
               _yes_no(_pick(pf, "other_insurance", "currently_covered_other")))
    pdf.kv_row([
        ("Date of First Insurance", _fmt_date(_pick(pf, "first_insurance_date", "policy_inception_date", "policy_start_date"))),
        ("Sum Insured", _rupees(_pick(pf, "sum_insured"))),
    ])
    pdf.kv_row([
        ("Cumulative Bonus", _rupees(_pick(pf, "cumulative_bonus"))),
        ("Date of Issue of Policy", _fmt_date(_pick(pf, "policy_issue_date"))),
    ])
    pdf.yn_row("Family Floater Policy", _yes_no(_pick(pf, "family_floater")))
    pdf.kv_row([
        ("Other Insurer Name", _pick(pf, "other_insurer_name")),
        ("Other Policy No.", _pick(pf, "other_policy_number")),
    ])
    pdf.yn_row("Hospitalised in last 4 years since policy inception",
               _yes_no(_pick(pf, "hospitalized_last_4_years")))
    pdf.kv_row([
        ("Date of prior hospitalisation", _fmt_date(_pick(pf, "prior_hospitalization_date"))),
        ("Prior diagnosis", _pick(pf, "prior_diagnosis", "primary_diagnosis", "diagnosis")),
    ])
    pdf.yn_row("Previously covered by another Mediclaim/Health Insurance",
               _yes_no(_pick(pf, "previously_covered_other")))
    pdf.kv_full("Previous Insurer Name", _pick(pf, "previous_insurer_name"))
    pdf.divider()

    # ── C: Insured Person Hospitalised ──────────────────────────────
    _ensure_space(pdf, 55)
    pdf.section_header("C", "DETAILS OF INSURED PERSON HOSPITALISED")
    pdf.kv_full("Patient Name",
                _pick(pf, "patient_name", "member_name", "insured_name"),
                bold_value=True)
    g_raw = (_pick(pf, "gender", "sex") or "").lower()
    gender = "Male" if g_raw.startswith("m") else ("Female" if g_raw.startswith("f") else _pick(pf, "gender", "sex"))
    pdf.kv_row([
        ("Gender", gender),
        ("Age", _pick(pf, "age")),
        ("Date of Birth", _fmt_date(_pick(pf, "date_of_birth", "dob"))),
    ])
    rel_raw = (_pick(pf, "relationship", "relationship_to_primary_insured") or "Self").lower()
    rel_display = next((o for o in ("Self", "Spouse", "Child", "Father", "Mother") if rel_raw.startswith(o.lower()[:4])), rel_raw.title() or "Other")
    occ_raw = (_pick(pf, "occupation") or "").lower()
    occ_display = next((o for o in ("Service", "Self Employed", "Home Maker", "Student", "Retired") if occ_raw.startswith(o.lower()[:4])), _pick(pf, "occupation") or "-")
    pdf.kv_row([
        ("Relationship to Primary Insured", rel_display),
        ("Occupation", occ_display),
    ])
    pdf.kv_full("Address (if different)", _pick(pf, "patient_address_alt", "patient_address"))
    pdf.kv_row([
        ("Phone", _pick(pf, "patient_phone", "phone")),
        ("Email", _pick(pf, "patient_email", "email")),
    ])
    pdf.divider()

    # ── D: Hospitalisation ──────────────────────────────────────────
    _ensure_space(pdf, 70)
    pdf.section_header("D", "DETAILS OF HOSPITALISATION")
    pdf.kv_full("Hospital Name", _pick(pf, "hospital_name", "hospital", "provider_name"), bold_value=True)
    room = (_pick(pf, "room_type", "room_category") or "").lower()
    pdf.options_row("Room Category", [
        ("Day care", "day" in room),
        ("Single occupancy", "single" in room or "private" in room),
        ("Twin sharing", "twin" in room or "double" in room or "semi" in room),
        ("3+ beds / room", "ward" in room or "general" in room or "3" in room),
    ])
    cause = (_pick(pf, "hospitalization_due_to", "admission_type") or "").lower()
    is_inj = "inj" in cause or "accident" in cause or "trauma" in cause
    is_mat = "mat" in cause or "delivery" in cause or "preg" in cause
    is_ill = not (is_inj or is_mat)
    pdf.options_row("Hospitalisation due to", [
        ("Injury", is_inj), ("Illness", is_ill), ("Maternity", is_mat),
    ])
    pdf.kv_full("Date of injury / disease detected / delivery",
                _fmt_date(_pick(pf, "date_of_injury", "disease_detected_date", "date_of_delivery")))
    pdf.kv_row([
        ("Date of Admission", _fmt_date(_pick(pf, "admission_date", "date_of_admission", "service_date"))),
        ("Time", _fmt_time(_pick(pf, "admission_time"))),
    ])
    pdf.kv_row([
        ("Date of Discharge", _fmt_date(_pick(pf, "discharge_date", "date_of_discharge"))),
        ("Time", _fmt_time(_pick(pf, "discharge_time"))),
    ])
    inj_cause = (_pick(pf, "injury_cause") or "").lower()
    pdf.options_row("If injury - cause", [
        ("Self-inflicted", "self" in inj_cause),
        ("Road Traffic Accident", "road" in inj_cause or "rta" in inj_cause),
        ("Substance / Alcohol", "subst" in inj_cause or "alc" in inj_cause),
    ])
    pdf.yn_row("Medico-legal", _yes_no(_pick(pf, "medico_legal")))
    pdf.yn_row("Reported to Police", _yes_no(_pick(pf, "reported_to_police")))
    pdf.yn_row("MLC Report & Police FIR attached", _yes_no(_pick(pf, "mlc_attached", "fir_attached")))
    pdf.kv_full("System of Medicine", _pick(pf, "system_of_medicine", "treatment_system") or "Allopathy")
    pdf.divider()

    # ── E: Claim ────────────────────────────────────────────────────
    _ensure_space(pdf, 75)
    pdf.section_header("E", "DETAILS OF CLAIM")

    pre_h = _to_float(_pick(pf, "pre_hospitalization_expenses", "pre_hosp_amount"))
    hosp = _to_float(_pick(pf, "hospitalization_expenses", "hospital_expenses", "total_amount", "billed_amount"))
    post_h = _to_float(_pick(pf, "post_hospitalization_expenses", "post_hosp_amount"))
    health_chk = _to_float(_pick(pf, "health_checkup_cost"))
    amb = _to_float(_pick(pf, "ambulance_charges"))
    others = _to_float(_pick(pf, "other_charges", "misc_charges"))
    grand_total = pre_h + hosp + post_h + health_chk + amb + others or hosp

    pdf.set_font("Helvetica", "B", 8)
    pdf.set_fill_color(*ACCENT_LIGHT)
    pdf.cell(pdf.CONTENT_W * 0.55, 6, _s("  Treatment Expense"), border=1, fill=True)
    pdf.cell(pdf.CONTENT_W * 0.45, 6, _s("Amount"), border=1, fill=True, align="C")
    pdf.ln(6)
    pdf.set_font("Helvetica", "", 8)
    rows = [
        ("i. Pre-hospitalisation expenses", pre_h),
        ("ii. Hospitalisation expenses", hosp),
        ("iii. Post-hospitalisation expenses", post_h),
        ("iv. Health-Check up cost", health_chk),
        ("v. Ambulance charges", amb),
        ("vi. Others", others),
    ]
    pdf.expense_field_names = []
    for label, amt in rows:
        pdf.cell(pdf.CONTENT_W * 0.55, 5.6, _s(f"  {label}"), border=1)
        fname = pdf._track_text(
            f"Amount - {label.lstrip('iv. ')}",
            _rupees(amt) if amt else "",
            pdf.CONTENT_W * 0.45, 5.6, align="R",
            kind={"format": "currency", "hint": "Amount in INR."},
        )
        pdf.expense_field_names.append(fname)
        pdf.cell(pdf.CONTENT_W * 0.45, 5.6, "", border=1)
        pdf.ln(5.6)
    pdf.set_font("Helvetica", "B", 8.5)
    pdf.set_fill_color(*ACCENT)
    pdf.set_text_color(*SECTION_FG)
    pdf.cell(pdf.CONTENT_W * 0.55, 6.4, _s("  TOTAL CLAIMED  (auto-sum)"), border=1, fill=True)
    # Total Claimed: editable but auto-calculated from the 6 expense rows.
    # Marked read-only so the JS calculate handler is the sole source of
    # truth - removes manual data-entry errors that otherwise plague IRDA
    # form submissions.
    pdf.total_field_name = pdf._track_text(
        "Total Claimed", _rupees(grand_total) if grand_total else "",
        pdf.CONTENT_W * 0.45, 6.4, align="R", bold=True, readonly=True,
        kind={"format": "currency",
              "hint": "Auto-calculated as sum of i+ii+iii+iv+v+vi (read-only)."},
    )
    pdf.cell(pdf.CONTENT_W * 0.45, 6.4, "", border=1, fill=True)
    pdf.ln(6.4)
    pdf.set_text_color(*TEXT)
    pdf.ln(1.5)

    pdf.kv_row([
        ("Pre-hosp. period (days)", _pick(pf, "pre_hospitalization_days", "pre_hosp_days") or "0"),
        ("Post-hosp. period (days)", _pick(pf, "post_hospitalization_days", "post_hosp_days") or "0"),
    ])
    pdf.yn_row("Claim for Domiciliary Hospitalisation",
               _yes_no(_pick(pf, "domiciliary_hospitalization")))
    pdf.divider()

    # ── F: Bills Enclosed ───────────────────────────────────────────
    _ensure_space(pdf, 60)
    pdf.section_header("F", "DETAILS OF BILLS ENCLOSED")
    bills = list(ctx.get("bills", []) or [])
    if not bills:
        if hosp > 0:
            bills.append({"bill_no": "", "date": _fmt_date(_pick(pf, "discharge_date")),
                          "issued_by": _pick(pf, "hospital_name"), "towards": "Hospital main bill", "amount": hosp})
        ph = _to_float(_pick(pf, "pharmacy_charges", "pharmacy_charge"))
        if ph > 0:
            bills.append({"bill_no": "", "date": "", "issued_by": "Pharmacy",
                          "towards": "Pharmacy bills", "amount": ph})
        if pre_h > 0:
            bills.append({"bill_no": "", "date": "", "issued_by": "",
                          "towards": "Pre-hospitalisation bills", "amount": pre_h})
        if post_h > 0:
            bills.append({"bill_no": "", "date": "", "issued_by": "",
                          "towards": "Post-hospitalisation bills", "amount": post_h})

    if not bills:
        # always render at least 6 empty rows so the user can fill them in
        bills = [{} for _ in range(6)]
    else:
        while len(bills) < 6:
            bills.append({})

    cols = [("#", 8), ("Bill No.", 22), ("Date", 22), ("Issued By", 50), ("Towards", 50), ("Amount", 34)]
    pdf.set_font("Helvetica", "B", 7.8)
    pdf.set_fill_color(*ACCENT_LIGHT)
    for name, w in cols:
        pdf.cell(w, 6, _s(name), border=1, fill=True, align="C")
    pdf.ln(6)
    pdf.set_font("Helvetica", "", 7.8)
    for i, b in enumerate(bills[:10], start=1):
        # row number is static, the other 5 cells are editable
        pdf.cell(cols[0][1], 5.4, str(i), border=1, align="C")
        pdf._track_text(f"Bill #{i} No", b.get("bill_no", ""), cols[1][1], 5.4)
        pdf.cell(cols[1][1], 5.4, "", border=1)
        pdf._track_text(f"Bill #{i} Date", b.get("date", ""), cols[2][1], 5.4, align="C")
        pdf.cell(cols[2][1], 5.4, "", border=1)
        pdf._track_text(f"Bill #{i} Issued By", b.get("issued_by", ""), cols[3][1], 5.4)
        pdf.cell(cols[3][1], 5.4, "", border=1)
        pdf._track_text(f"Bill #{i} Towards", b.get("towards", ""), cols[4][1], 5.4)
        pdf.cell(cols[4][1], 5.4, "", border=1)
        pdf._track_text(f"Bill #{i} Amount", _rupees(b.get("amount")) or "", cols[5][1], 5.4, align="R")
        pdf.cell(cols[5][1], 5.4, "", border=1)
        pdf.ln(5.4)
    pdf.divider()

    # ── G: Bank Account ─────────────────────────────────────────────
    _ensure_space(pdf, 30)
    pdf.section_header("G", "DETAILS OF PRIMARY INSURED'S BANK ACCOUNT")
    pdf.kv_row([
        ("PAN", _pick(pf, "pan", "pan_number")),
        ("Account Number", _pick(pf, "account_number", "bank_account_number")),
    ])
    acc_type = (_pick(pf, "account_type") or "savings").lower()
    pdf.options_row("Account Type", [
        ("Savings", "sav" in acc_type),
        ("Current", "curr" in acc_type),
        ("NRE/NRO", "nre" in acc_type or "nro" in acc_type),
    ], radio_group="a_acc_type")
    pdf.kv_full("Bank Name & Branch", _pick(pf, "bank_name", "bank_branch"))
    pdf.kv_row([
        ("Cheque/DD Payable to", _pick(pf, "cheque_payable_to", "policyholder_name", "patient_name")),
        ("IFSC Code", _pick(pf, "ifsc", "ifsc_code")),
    ])
    pdf.kv_full("MICR Code", _pick(pf, "micr", "micr_code"))
    pdf.divider()

    # ── H: Declaration ──────────────────────────────────────────────
    _ensure_space(pdf, 45)
    pdf.section_header("H", "DECLARATION BY THE INSURED")
    pdf.set_font("Helvetica", "", 7.4)
    pdf.set_text_color(*TEXT)
    pdf.multi_cell(
        pdf.CONTENT_W,
        3.6,
        _s(
            "I hereby declare that the information furnished in this claim form is true & correct to the best of my "
            "knowledge and belief. If I have made any false or untrue statement, suppression or concealment of any "
            "material fact with respect to questions asked in relation to this claim, my right to claim reimbursement "
            "shall be forfeited. I also consent and authorize the TPA / Insurance Company to seek necessary medical "
            "information / documents from any hospital / Medical Practitioner who has attended the person against "
            "whom this claim is made. I confirm that I have included all bills / receipts for the purpose of this "
            "claim and that I will not be making any supplementary claim except the pre/post-hospitalisation claim, if any."
        ),
    )
    pdf.ln(2)
    pdf.kv_row([
        ("Date", datetime.now().strftime("%d-%b-%Y")),
        ("Place", _pick(pf, "city", "place") or "-"),
    ])
    pdf.kv_full("Signature of the Insured", "(pending physical sign)")


def _build_part_b(pdf: IRDAClaimPDF, ctx: dict[str, Any]) -> None:
    pf = ctx["fields"]
    icd_codes: list[dict[str, Any]] = ctx.get("icd_codes", []) or []
    cpt_codes: list[dict[str, Any]] = ctx.get("cpt_codes", []) or []

    pdf.add_page()
    pdf.title_block(
        kind="PART B",
        subtitle="HOSPITAL DECLARATION & CLINICAL DETAILS",
        who_fills="To be filled by the HOSPITAL  |  Include the original preauthorisation request form in lieu of Part A where applicable",
    )

    # ── A: Hospital ─────────────────────────────────────────────────
    pdf.section_header("A", "DETAILS OF HOSPITAL")
    pdf.kv_full("Hospital Name", _pick(pf, "hospital_name", "hospital", "provider_name"), bold_value=True)
    pdf.kv_full("Hospital ID / Provider ID", _pick(pf, "hospital_id", "provider_id", "npi"))
    type_h = (_pick(pf, "hospital_type", "network_status") or "").lower()
    is_network = "network" in type_h and "non" not in type_h
    pdf.options_row("Type of Hospital", [("Network", is_network), ("Non-Network", not is_network)])
    pdf.kv_full("Treating Doctor",
                _pick(pf, "doctor_name", "treating_doctor", "surgeon", "rendering_provider"),
                bold_value=True)
    pdf.kv_row([
        ("Qualification", _pick(pf, "doctor_qualification", "qualification") or "MBBS"),
        ("Reg. No. (State)", _pick(pf, "doctor_registration_no", "registration_no")),
        ("Phone", _pick(pf, "doctor_phone", "hospital_phone")),
    ])
    pdf.kv_row([
        ("Anaesthetist Name", _pick(pf, "anaesthetist_name")),
        ("Type of Anaesthesia", _pick(pf, "type_of_anaesthesia")),
    ])
    pdf.kv_row([
        ("Date of OT", _fmt_date(_pick(pf, "ot_date", "date_of_ot"))),
        ("OT Time", _fmt_time(_pick(pf, "ot_time"))),
    ])
    pdf.divider()

    # ── B: Patient Admitted ─────────────────────────────────────────
    _ensure_space(pdf, 55)
    pdf.section_header("B", "DETAILS OF THE PATIENT ADMITTED")
    pdf.kv_full("Patient Name", _pick(pf, "patient_name", "member_name"), bold_value=True)
    g_raw = (_pick(pf, "gender", "sex") or "").lower()
    gender = "Male" if g_raw.startswith("m") else ("Female" if g_raw.startswith("f") else _pick(pf, "gender", "sex"))
    pdf.kv_row([
        ("IP Registration No.", _pick(pf, "ip_registration_number", "ip_no", "registration_number")),
        ("Gender", gender),
    ])
    pdf.kv_row([
        ("Age", _pick(pf, "age")),
        ("Date of Birth", _fmt_date(_pick(pf, "date_of_birth", "dob"))),
    ])
    pdf.kv_row([
        ("Date of Admission", _fmt_date(_pick(pf, "admission_date", "date_of_admission", "service_date"))),
        ("Admission Time", _fmt_time(_pick(pf, "admission_time"))),
    ])
    pdf.kv_row([
        ("Date of Discharge", _fmt_date(_pick(pf, "discharge_date", "date_of_discharge"))),
        ("Discharge Time", _fmt_time(_pick(pf, "discharge_time"))),
    ])
    adm_type = (_pick(pf, "admission_type", "type_of_admission") or "").lower()
    pdf.options_row("Type of Admission", [
        ("Emergency", "emerg" in adm_type),
        ("Planned", "plan" in adm_type or "elect" in adm_type),
        ("Day Care", "day" in adm_type),
        ("Maternity", "mat" in adm_type),
    ])
    pdf.kv_row([
        ("If Maternity - Date of Delivery", _fmt_date(_pick(pf, "date_of_delivery"))),
        ("Gravida Status", _pick(pf, "gravida_status", "gravida")),
    ])
    status = (_pick(pf, "discharge_status", "status_at_discharge") or "home").lower()
    pdf.options_row("Status at Discharge", [
        ("Home", "home" in status or "discharge" in status),
        ("Transferred to another hospital", "another" in status or "transfer" in status),
        ("Deceased", "decea" in status or "death" in status or "expir" in status),
    ])
    pdf.kv_full("Total Claimed Amount",
                _rupees(_pick(pf, "total_amount", "billed_amount", "claim_amount")) or "",
                bold_value=True)
    # additional clinical detail rows
    pdf.kv_row([
        ("Date of First Symptom", _fmt_date(_pick(pf, "date_of_first_symptom", "symptom_onset_date"))),
        ("Past History (months)", _pick(pf, "past_history_months", "duration_of_illness")),
    ])
    pdf.yn_row("Pre-existing condition", _yes_no(_pick(pf, "pre_existing", "preexisting")))
    pdf.yn_row("Hereditary disease", _yes_no(_pick(pf, "hereditary")))
    pdf.kv_row([
        ("ICU - days", _pick(pf, "icu_days")),
        ("Class of accommodation", _pick(pf, "class_of_accommodation", "room_type")),
    ])
    pdf.divider()

    # ── C: Diagnoses & Procedures ───────────────────────────────────
    _ensure_space(pdf, 90)
    pdf.section_header("C", "DETAILS OF AILMENT DIAGNOSED & PROCEDURES")

    # Diagnoses
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_fill_color(*ACCENT_LIGHT)
    pdf.cell(pdf.CONTENT_W, 6, _s("  ICD-10 Diagnoses"), border=1, fill=True)
    pdf.ln(6)
    diag_cols = [("Type", 50), ("ICD-10 Code", 30), ("Description", 106)]
    pdf.set_font("Helvetica", "B", 7.8)
    pdf.set_fill_color(*LABEL_BG)
    for name, w in diag_cols:
        pdf.cell(w, 5.6, _s(name), border=1, fill=True, align="C")
    pdf.ln(5.6)
    pdf.set_font("Helvetica", "", 7.8)
    diag_labels = ["Primary Diagnosis", "Additional Diagnosis", "Co-morbidity 1", "Co-morbidity 2"]
    for i in range(4):
        c = icd_codes[i] if i < len(icd_codes) else None
        pdf.cell(diag_cols[0][1], 5.6, _s(diag_labels[i]), border=1)
        code_val = (c or {}).get("code", "")
        pdf._track_text(f"{diag_labels[i]} - ICD-10 Code", code_val, diag_cols[1][1], 5.6, align="C")
        pdf.cell(diag_cols[1][1], 5.6, "", border=1)
        desc = (c or {}).get("description", "") or (i == 0 and _pick(pf, "primary_diagnosis", "diagnosis")) or ""
        pdf._track_text(f"{diag_labels[i]} - Description", desc, diag_cols[2][1], 5.6)
        pdf.cell(diag_cols[2][1], 5.6, "", border=1)
        pdf.ln(5.6)
    pdf.ln(1.5)

    # Procedures
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_fill_color(*ACCENT_LIGHT)
    pdf.cell(pdf.CONTENT_W, 6, _s("  Procedures (ICD-10 PCS / CPT)"), border=1, fill=True)
    pdf.ln(6)
    proc_cols = [("Type", 50), ("Code", 30), ("Description", 106)]
    pdf.set_font("Helvetica", "B", 7.8)
    pdf.set_fill_color(*LABEL_BG)
    for name, w in proc_cols:
        pdf.cell(w, 5.6, _s(name), border=1, fill=True, align="C")
    pdf.ln(5.6)
    pdf.set_font("Helvetica", "", 7.8)
    proc_labels = ["Procedure 1", "Procedure 2", "Procedure 3"]
    for i in range(3):
        c = cpt_codes[i] if i < len(cpt_codes) else None
        pdf.cell(proc_cols[0][1], 5.6, _s(proc_labels[i]), border=1)
        code_val = (c or {}).get("code", "")
        pdf._track_text(f"{proc_labels[i]} - Code", code_val, proc_cols[1][1], 5.6, align="C")
        pdf.cell(proc_cols[1][1], 5.6, "", border=1)
        desc = (c or {}).get("description", "")
        pdf._track_text(f"{proc_labels[i]} - Description", desc, proc_cols[2][1], 5.6)
        pdf.cell(proc_cols[2][1], 5.6, "", border=1)
        pdf.ln(5.6)
    detail = _pick(pf, "procedure", "service_description")
    pdf.set_fill_color(*LABEL_BG)
    pdf.set_font("Helvetica", "B", 7.8)
    pdf.cell(50, 5.6, _s("Details of Procedure"), border=1, fill=True)
    pdf.set_font("Helvetica", "", 7.8)
    pdf.set_fill_color(*VALUE_BG)
    pdf._track_text("Details of Procedure", detail, 136, 5.6)
    pdf.cell(136, 5.6, "", border=1)
    pdf.ln(5.6)
    pdf.ln(1.5)

    preauth_obtained = (_pick(pf, "pre_authorization", "preauth_obtained") or "").lower() in ("yes", "y", "true") or bool(_pick(pf, "preauth_number", "pre_authorization_number"))
    pdf.yn_row("Pre-authorisation obtained", preauth_obtained)
    pdf.kv_row([
        ("Pre-auth Number", _pick(pf, "preauth_number", "pre_authorization_number")),
        ("Reason if not obtained", _pick(pf, "preauth_reason")),
    ])
    inj = (_pick(pf, "injury") or "").lower()
    is_inj = "yes" in inj or "true" in inj
    pdf.yn_row("Hospitalisation due to injury", is_inj if inj else None)
    inj_cause = (_pick(pf, "injury_cause") or "").lower()
    pdf.options_row("If injury - cause", [
        ("Self-inflicted", "self" in inj_cause),
        ("Road Traffic Accident", "road" in inj_cause or "rta" in inj_cause),
        ("Substance / Alcohol", "subst" in inj_cause or "alc" in inj_cause),
    ])
    pdf.yn_row("Medico-legal", _yes_no(_pick(pf, "medico_legal")))
    pdf.yn_row("Reported to Police", _yes_no(_pick(pf, "reported_to_police")))
    pdf.kv_row([
        ("FIR No.", _pick(pf, "fir_no", "fir_number")),
        ("Reason if not reported", _pick(pf, "fir_reason")),
    ])
    pdf.divider()

    # ── D: Documents Checklist ──────────────────────────────────────
    _ensure_space(pdf, 55)
    pdf.section_header("D", "CLAIM DOCUMENTS SUBMITTED - CHECKLIST")
    docs = ctx.get("documents", []) or []
    doc_names = " ".join(str(d.get("file_name", "")).lower() for d in docs)
    checklist = [
        ("Claim Form duly signed", True),
        ("Original Pre-authorisation request", "preauth" in doc_names or preauth_obtained),
        ("Pre-authorisation approval letter", "approval" in doc_names),
        ("Photo ID Card of patient", any(k in doc_names for k in ("id", "aadhaar", "pan"))),
        ("Hospital Discharge Summary", any(k in doc_names for k in ("discharge", "summary"))),
        ("Operation Theatre Notes", "ot " in doc_names or "operation" in doc_names),
        ("Hospital main bill", "bill" in doc_names or _to_float(_pick(pf, "total_amount")) > 0),
        ("Hospital break-up bill", "break" in doc_names or "itemiz" in doc_names),
        ("Investigation reports", any(k in doc_names for k in ("report", "investig", "lab"))),
        ("CT / MR / USG / HPE reports", any(k in doc_names for k in ("ct", "mri", "usg", "hpe", "scan"))),
        ("Doctor's reference slip", "prescription" in doc_names),
        ("ECG", "ecg" in doc_names),
        ("Pharmacy bills", any(k in doc_names for k in ("pharmacy", "medicine"))),
        ("MLC reports & Police FIR", _yes_no(_pick(pf, "reported_to_police")) is True),
        ("Original death summary (if applicable)", "death" in doc_names),
    ]
    pdf.set_font("Helvetica", "", 7.8)
    col_w = pdf.CONTENT_W / 2
    for i in range(0, len(checklist), 2):
        for j in (0, 1):
            if i + j >= len(checklist):
                break
            label, checked = checklist[i + j]
            x = pdf.l_margin + j * col_w
            y = pdf.get_y()
            pdf.set_xy(x, y)
            # Interactive checkbox: 3.2x3.2mm, widget supplies its own glyph
            pdf._track_check(f"Doc: {label}", x + 1, y + 1.3, 3.2, checked)
            pdf.set_text_color(*TEXT)
            pdf.set_font("Helvetica", "", 7.8)
            pdf.set_xy(x + 5.4, y)
            pdf.cell(col_w - 6, 6, _s(label))
        pdf.ln(6)
    pdf.set_text_color(*TEXT)
    pdf.divider()

    # ── E: Non-Network Hospital ─────────────────────────────────────
    _ensure_space(pdf, 35)
    pdf.section_header("E", "ADDITIONAL DETAILS - NON-NETWORK HOSPITAL (if applicable)")
    pdf.kv_full("Address of Hospital", _pick(pf, "hospital_address"))
    pdf.kv_row([
        ("City", _pick(pf, "hospital_city", "city")),
        ("State", _pick(pf, "hospital_state", "state")),
        ("Pin Code", _pick(pf, "hospital_pincode", "pin_code", "pincode")),
    ])
    pdf.kv_row([
        ("Hospital Phone", _pick(pf, "hospital_phone")),
        ("Reg. No.", _pick(pf, "hospital_registration_no")),
        ("Hospital PAN", _pick(pf, "hospital_pan")),
    ])
    pdf.kv_row([
        ("Inpatient beds", _pick(pf, "inpatient_beds", "bed_count")),
        ("OT facility", "Yes" if (_pick(pf, "has_ot") or "yes").lower() in ("yes", "y", "true") else "No"),
        ("ICU facility", "Yes" if (_pick(pf, "has_icu") or "yes").lower() in ("yes", "y", "true") else "No"),
    ])
    pdf.divider()

    # ── F: Declaration ──────────────────────────────────────────────
    _ensure_space(pdf, 35)
    pdf.section_header("F", "DECLARATION BY THE HOSPITAL")
    pdf.set_font("Helvetica", "", 7.4)
    pdf.multi_cell(
        pdf.CONTENT_W,
        3.6,
        _s(
            "We hereby declare that the information furnished in this Claim Form is true & correct to the best of "
            "our knowledge and belief. If we have made any false or untrue statement, suppression or concealment of "
            "any material fact, our right to claim under this claim shall be forfeited."
        ),
    )
    pdf.ln(2)
    pdf.kv_row([
        ("Date", datetime.now().strftime("%d-%b-%Y")),
        ("Place", _pick(pf, "hospital_city", "city") or "-"),
    ])
    pdf.kv_full("Signature & Hospital Seal", "(pending physical sign & seal)")


# ── editable-form post-processor (AcroForm widget injection) ──────────────
_MM2PT = 72.0 / 25.4


def _inject_acroform(pdf_bytes: bytes, fields: list[dict[str, Any]],
                     page_h_mm: float = 297.0,
                     expense_field_names: list[str] | None = None,
                     total_field_name: str | None = None,
                     metadata: dict[str, str] | None = None) -> bytes:
    """Overlay AcroForm widget annotations on top of the rendered PDF.

    Each entry in ``fields`` is either a text-field (``type='tx'``) or a
    check-box / radio (``type='chk'``). Coordinates are converted from
    fpdf2's top-left mm system to PDF native bottom-left points.

    When ``expense_field_names`` and ``total_field_name`` are supplied,
    the AcroForm calculation-order array ``/CO`` is populated and the
    total-field receives a ``/AA /C`` JavaScript handler that sums them
    automatically every time any expense row changes.
    """
    try:
        from pypdf import PdfReader, PdfWriter
        from pypdf.generic import (
            ArrayObject, BooleanObject, ByteStringObject, DictionaryObject,
            FloatObject, NameObject, NumberObject, TextStringObject,
        )
    except ImportError:  # pragma: no cover
        logger.warning("pypdf not installed; returning non-editable PDF")
        return pdf_bytes

    import io as _io
    reader = PdfReader(_io.BytesIO(pdf_bytes))
    writer = PdfWriter()
    writer.append_pages_from_reader(reader)

    page_h_pt = page_h_mm * _MM2PT

    def _rect(x_mm: float, y_mm: float, w_mm: float, h_mm: float) -> ArrayObject:
        llx = x_mm * _MM2PT
        urx = (x_mm + w_mm) * _MM2PT
        ury = (page_h_mm - y_mm) * _MM2PT
        lly = (page_h_mm - y_mm - h_mm) * _MM2PT
        return ArrayObject([FloatObject(round(llx, 3)), FloatObject(round(lly, 3)),
                            FloatObject(round(urx, 3)), FloatObject(round(ury, 3))])

    field_refs: list[Any] = []
    radio_groups: dict[str, dict[str, Any]] = {}
    name_to_ref: dict[str, Any] = {}

    # ── PDF JavaScript helpers ──────────────────────────────────────────
    def _js_action(script: str) -> DictionaryObject:
        return DictionaryObject({
            NameObject("/S"): NameObject("/JavaScript"),
            NameObject("/JS"): TextStringObject(script),
        })

    def _validators_for(f: dict[str, Any]) -> tuple[DictionaryObject | None,
                                                     DictionaryObject | None,
                                                     DictionaryObject | None]:
        """Return (format-action /F, keystroke-action /K, validate /V)."""
        fmt = f.get("format")
        format_act: DictionaryObject | None = None
        keystr_act: DictionaryObject | None = None
        val_act: DictionaryObject | None = None
        if fmt == "currency":
            # AFNumber_* are Acrobat built-ins for currency formatting
            format_act = _js_action(
                'AFNumber_Format(0, 0, 0, 0, "\\u20b9 ", true);'
            )
            keystr_act = _js_action(
                'AFNumber_Keystroke(0, 0, 0, 0, "", true);'
            )
        elif fmt == "date":
            format_act = _js_action('AFDate_FormatEx("dd-mmm-yyyy");')
            keystr_act = _js_action('AFDate_KeystrokeEx("dd-mmm-yyyy");')
        regex = f.get("regex")
        if regex:
            # JavaScript-friendly regex (already JS-compatible)
            hint = (f.get("tooltip") or f.get("label") or "").replace('"', "'")
            val_act = _js_action(
                f'if (event.value && !/{regex}/.test(event.value)) '
                f'{{ app.alert({{cMsg: "Invalid format for ' + (f.get('label') or '').replace('"', "'") + f'.\\n\\n{hint}", cTitle: "IRDA Form Validation"}}); event.rc = false; }}'
            )
        return format_act, keystr_act, val_act

    def _aa_dict(f: dict[str, Any]) -> DictionaryObject | None:
        format_act, keystr_act, val_act = _validators_for(f)
        if not (format_act or keystr_act or val_act):
            return None
        d = DictionaryObject()
        if format_act:
            d[NameObject("/F")] = format_act
        if keystr_act:
            d[NameObject("/K")] = keystr_act
        if val_act:
            d[NameObject("/V")] = val_act
        return d

    for f in fields:
        page_idx = max(0, min(len(writer.pages) - 1, f["page"] - 1))
        page = writer.pages[page_idx]

        if f["type"] == "tx":
            # ── text widget ──
            ff_flags = 0
            if f.get("multiline"):
                ff_flags |= 1 << 12  # bit 13 - Multiline
            if f.get("readonly"):
                ff_flags |= 1 << 0   # bit 1  - ReadOnly
            if f.get("required"):
                ff_flags |= 1 << 1   # bit 2  - Required
            q = {"L": 0, "C": 1, "R": 2}.get(f.get("align", "L"), 0)
            font_pt = max(6.0, float(f.get("font_size", 8.4)))
            da = f"/Helv {font_pt} Tf 0.06 0.09 0.16 rg"
            widget = DictionaryObject({
                NameObject("/Type"): NameObject("/Annot"),
                NameObject("/Subtype"): NameObject("/Widget"),
                NameObject("/FT"): NameObject("/Tx"),
                NameObject("/Rect"): _rect(f["x"], f["y"], f["w"], f["h"]),
                NameObject("/T"): TextStringObject(f["name"]),
                NameObject("/TU"): TextStringObject(f.get("tooltip") or f.get("label") or f["name"]),
                NameObject("/V"): TextStringObject(f.get("value", "") or ""),
                NameObject("/DV"): TextStringObject(f.get("value", "") or ""),
                NameObject("/DA"): TextStringObject(da),
                NameObject("/Q"): NumberObject(q),
                NameObject("/Ff"): NumberObject(ff_flags),
                NameObject("/F"): NumberObject(4),  # printable
                NameObject("/BS"): DictionaryObject({
                    NameObject("/W"): NumberObject(0),
                    NameObject("/S"): NameObject("/S"),
                }),
            })
            if f.get("max_len"):
                widget[NameObject("/MaxLen")] = NumberObject(int(f["max_len"]))
            aa = _aa_dict(f)
            if aa is not None:
                widget[NameObject("/AA")] = aa
            # mark AI-filled fields with an amber widget border for accessibility
            if f.get("ai_filled"):
                widget[NameObject("/MK")] = DictionaryObject({
                    NameObject("/BC"): ArrayObject([
                        FloatObject(0.984), FloatObject(0.749), FloatObject(0.141),
                    ]),
                })
            ref = writer._add_object(widget)
            widget[NameObject("/P")] = page.indirect_reference
            field_refs.append(ref)
            name_to_ref[f["name"]] = ref
            page_annots = page.get("/Annots")
            if page_annots is None:
                page[NameObject("/Annots")] = ArrayObject([ref])
            else:
                page_annots.append(ref)

        elif f["type"] == "chk":
            export = f.get("export_value") or "On"
            # sanitise name to a PDF-safe token (no spaces, no slashes)
            export_pdf = re.sub(r"[^A-Za-z0-9_]", "_", export) or "On"
            checked = bool(f.get("checked"))
            grp = radio_groups.get(f["name"]) if f["name"] in radio_groups else None
            is_radio = grp is not None or any(
                ff["type"] == "chk" and ff["name"] == f["name"] and ff is not f
                for ff in fields
            )
            widget = DictionaryObject({
                NameObject("/Type"): NameObject("/Annot"),
                NameObject("/Subtype"): NameObject("/Widget"),
                NameObject("/FT"): NameObject("/Btn"),
                NameObject("/Rect"): _rect(f["x"], f["y"], f["w"], f["h"]),
                NameObject("/AS"): NameObject(f"/{export_pdf}" if checked else "/Off"),
                NameObject("/F"): NumberObject(4),
                NameObject("/MK"): DictionaryObject({
                    NameObject("/CA"): TextStringObject("4"),  # Zapf "4" = check mark
                    NameObject("/BC"): ArrayObject([FloatObject(0.4), FloatObject(0.5), FloatObject(0.6)]),
                }),
                NameObject("/BS"): DictionaryObject({
                    NameObject("/W"): NumberObject(0.6),
                    NameObject("/S"): NameObject("/S"),
                }),
            })

            if is_radio:
                # share the same parent field; widgets are children (kids)
                if f["name"] not in radio_groups:
                    parent = DictionaryObject({
                        NameObject("/FT"): NameObject("/Btn"),
                        NameObject("/Ff"): NumberObject((1 << 15) | (1 << 14)),  # Radio + NoToggleToOff
                        NameObject("/T"): TextStringObject(f["name"]),
                        NameObject("/V"): NameObject("/Off"),
                        NameObject("/Kids"): ArrayObject([]),
                    })
                    parent_ref = writer._add_object(parent)
                    radio_groups[f["name"]] = {"ref": parent_ref, "obj": parent}
                    field_refs.append(parent_ref)
                grp = radio_groups[f["name"]]
                widget[NameObject("/Parent")] = grp["ref"]
                grp["obj"]["/Kids"].append(writer._add_object(widget))
                if checked:
                    grp["obj"][NameObject("/V")] = NameObject(f"/{export_pdf}")
                ref = grp["obj"]["/Kids"][-1]
            else:
                widget[NameObject("/T")] = TextStringObject(f["name"])
                widget[NameObject("/TU")] = TextStringObject(f.get("label") or f["name"])
                widget[NameObject("/V")] = NameObject(f"/{export_pdf}" if checked else "/Off")
                widget[NameObject("/DV")] = NameObject(f"/{export_pdf}" if checked else "/Off")
                ref = writer._add_object(widget)
                field_refs.append(ref)

            widget[NameObject("/P")] = page.indirect_reference
            page_annots = page.get("/Annots")
            if page_annots is None:
                page[NameObject("/Annots")] = ArrayObject([ref])
            else:
                page_annots.append(ref)

    # ── AcroForm root entry ──
    helv = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
        NameObject("/Encoding"): NameObject("/WinAnsiEncoding"),
    })
    zapf = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/ZapfDingbats"),
    })
    helv_ref = writer._add_object(helv)
    zapf_ref = writer._add_object(zapf)
    dr = DictionaryObject({
        NameObject("/Font"): DictionaryObject({
            NameObject("/Helv"): helv_ref,
            NameObject("/ZaDb"): zapf_ref,
        }),
    })
    acro = DictionaryObject({
        NameObject("/Fields"): ArrayObject(field_refs),
        NameObject("/NeedAppearances"): BooleanObject(True),
        NameObject("/DA"): TextStringObject("/Helv 0 Tf 0 0 0 rg"),
        NameObject("/DR"): dr,
    })

    # ── calculation order: auto-sum total claimed ──────────────────────────
    if total_field_name and expense_field_names and total_field_name in name_to_ref:
        # AFSimple_Calculate accepts an array of source field names; the
        # value goes into event.value automatically.
        names_js = ", ".join(f'"{n}"' for n in expense_field_names)
        calc_js = (
            f'AFSimple_Calculate("SUM", new Array({names_js})); '
            'event.target.readonly = true;'
        )
        total_widget = name_to_ref[total_field_name].get_object()
        total_aa = total_widget.get(NameObject("/AA")) or DictionaryObject()
        total_aa[NameObject("/C")] = _js_action(calc_js)
        total_widget[NameObject("/AA")] = total_aa
        co_refs = [name_to_ref[n] for n in expense_field_names if n in name_to_ref]
        co_refs.append(name_to_ref[total_field_name])
        acro[NameObject("/CO")] = ArrayObject(co_refs)

    writer._root_object[NameObject("/AcroForm")] = acro

    # ── accessibility & metadata ────────────────────────────────────────────
    writer._root_object[NameObject("/Lang")] = TextStringObject("en-IN")
    # row-order tab navigation per page (accessibility / keyboard fillers)
    for page in writer.pages:
        page[NameObject("/Tabs")] = NameObject("/R")

    md = {
        "/Title": "IRDA Standard Health Insurance Claim Form",
        "/Subject": "IRDAI Master Circular - Standardisation of Health Insurance Claim Forms",
        "/Author": "ClaimGPT - Auto-filled by AI (verify before signing)",
        "/Keywords": "IRDA, IRDAI, Health Insurance, Claim Form, Reimbursement, Cashless",
        "/Creator": "ClaimGPT submission service",
        "/Producer": "fpdf2 + pypdf (AcroForm overlay)",
    }
    if metadata:
        for k, v in metadata.items():
            md[k if k.startswith("/") else f"/{k}"] = str(v)
    writer.add_metadata(md)

    buf = _io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


# ── public entry-point ────────────────────────────────────────────────────
def generate_irda_pdf(claim_data: dict[str, Any], blank: bool = False) -> bytes:
    """Generate the IRDA Standard Health Insurance Claim Form (Part A + Part B).

    The returned PDF is **interactive** - every value cell, table cell,
    Yes/No option and document-checklist box becomes an editable AcroForm
    widget that any modern PDF reader (Acrobat, Preview, browser viewer)
    can fill in, save and print.

    Set ``blank=True`` to produce a fully empty template with the same
    layout - useful when the user wants a printable IRDA form to fill by
    hand with only the policy / patient names auto-populated.
    """
    fields = dict(claim_data.get("parsed_fields", {}) or {})
    icd = claim_data.get("icd_codes", []) or []
    cpt = claim_data.get("cpt_codes", []) or []
    docs = claim_data.get("documents", []) or []
    bills = claim_data.get("bills", []) or []

    icd_norm = [c if isinstance(c, dict) else {"code": str(c), "description": ""} for c in icd]
    cpt_norm = [c if isinstance(c, dict) else {"code": str(c), "description": ""} for c in cpt]

    if blank:
        fields = {k: "" for k in fields}
        icd_norm = []
        cpt_norm = []
        bills = []

    ctx = {
        "fields": fields,
        "icd_codes": icd_norm,
        "cpt_codes": cpt_norm,
        "documents": docs,
        "bills": list(bills),
    }

    pdf = IRDAClaimPDF()
    pdf.alias_nb_pages()
    try:
        _build_part_a(pdf, ctx)
        _build_part_b(pdf, ctx)
    except Exception as exc:  # pragma: no cover
        logger.exception("IRDA PDF render error: %s", exc)
        if pdf.page_no() == 0:
            pdf.add_page()
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 8, _s("IRDA Claim Form - render error"), new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 9)
        pdf.multi_cell(0, 5, _s(str(exc)))

    raw = pdf.output(dest="S")
    raw_bytes = bytes(raw) if not isinstance(raw, (bytes, bytearray)) else bytes(raw)
    try:
        meta_extra = {
            "/IRDA.PolicyNo": str(fields.get("policy_number", "")),
            "/IRDA.ClaimType": str(fields.get("claim_type", "")),
            "/IRDA.PatientName": str(fields.get("patient_name", "")),
            "/IRDA.GeneratedAt": datetime.now().isoformat(timespec="seconds"),
            "/IRDA.Provenance": "ai_filled" if not blank else "blank_template",
        }
        return _inject_acroform(
            raw_bytes,
            pdf.acro_fields,
            expense_field_names=getattr(pdf, "expense_field_names", None),
            total_field_name=getattr(pdf, "total_field_name", None),
            metadata=meta_extra,
        )
    except Exception as exc:  # pragma: no cover
        logger.exception("AcroForm injection failed, returning static PDF: %s", exc)
        return raw_bytes
