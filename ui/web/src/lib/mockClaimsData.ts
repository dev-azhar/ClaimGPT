/**
 * Static mock claims database for ClaimGPT client demonstrations.
 * Contains rich clinical and billing records modeled on Indian healthcare practices.
 */

export interface DocInfo {
  id: string;
  file_name: string;
  file_type: string | null;
  uploaded_at: string;
}

export interface Claim {
  id: string;
  status: string;
  created_at: string;
  policy_id?: string | null;
  patient_id?: string | null;
  documents: DocInfo[];
  patient_name?: string | null;
  hospital_name?: string | null;
  doctor_name?: string | null;
  diagnosis?: string | null;
}

export interface CodeInfo {
  code: string;
  description: string;
  confidence: number;
  is_primary?: boolean;
  estimated_cost?: number | null;
}

export interface ExpenseRow {
  category: string;
  amount: number;
  source_field?: string;
  model_version?: string;
  document_id?: string | null;
  source_page?: number | null;
}

export interface RuleResult {
  rule_id?: string;
  rule_name: string;
  severity: string;
  message: string;
  passed: boolean;
}

export interface PreviewData {
  claim_id: string;
  status: string;
  policy_id: string | null;
  parsed_fields: Record<string, string>;
  summary: {
    patient_name: string;
    policy_number: string;
    age: string;
    gender: string;
    hospital: string;
    doctor: string;
    admission_date: string;
    discharge_date: string;
    diagnosis: string;
    history_of_present_illness?: string;
    past_history?: string;
    disease_history?: string;
    allergies?: string;
    treatment?: string;
    discharge_summary?: string;
    bank_name?: string;
    bank_branch?: string;
    account_holder?: string;
    account_number?: string;
    ifsc_code?: string;
    total_amount: string;
    icd_count?: number;
    cpt_count?: number;
    risk_score?: number | null;
    validation_passed?: number;
    validation_total?: number;
    manual_review_required?: boolean;
  };
  icd_codes: CodeInfo[];
  cpt_codes: CodeInfo[];
  cost_summary: { icd_total: number; cpt_total: number; grand_total: number };
  expenses: ExpenseRow[];
  expense_total: number;
  billed_total: number;
  predictions: Array<{
    rejection_score: number;
    top_reasons: Array<{ reason: string; weight: number; feature?: string }>;
    model_name: string;
  }>;
  validations: RuleResult[];
  ocr_excerpt: string;
  brain_insights: string[];
  reimbursement_brain: {
    documents_analyzed: Array<{
      file_name: string;
      doc_type: string;
      fields_found: Record<string, string>;
      text_length: number;
    }>;
    cross_references: Array<{
      field: string;
      sources: Array<{ doc: string; doc_type: string; value: string }>;
      status: string;
    }>;
    reimbursement_checklist: Array<{
      item: string;
      status: string;
      reason: string;
    }>;
    insights: Array<{
      type: string;
      category: string;
      text: string;
    }>;
    completeness_pct: number;
  };
  scan_analyses?: Array<{
    id: string;
    scan_type: string;
    body_part: string;
    modality: string;
    findings: Array<{ finding: string; severity: string; confidence: number }>;
    impression: string;
    recommendation: string;
    confidence: number;
    is_abnormal: boolean;
    file_name: string;
  }>;
}

export const STATIC_CLAIM_IDS = [
  "00000000-0000-0000-0000-000000000001",
  "00000000-0000-0000-0000-000000000002",
  "00000000-0000-0000-0000-000000000003",
  "00000000-0000-0000-0000-000000000004",
  "00000000-0000-0000-0000-000000000005",
];

export function isStaticClaim(id?: string | null): boolean {
  if (!id) return false;
  return STATIC_CLAIM_IDS.includes(id);
}

// 1. Basic Claim Metadata List (what /claims returns)
export const MOCK_CLAIMS: Claim[] = [
  {
    id: "00000000-0000-0000-0000-000000000001",
    status: "MANUAL_REVIEW_REQUIRED",
    created_at: new Date(Date.now() - 3600000 * 2).toISOString(), // 2 hours ago
    policy_id: "POL-MAX-90812",
    patient_id: "PAT-RK-45",
    patient_name: "Rajesh Kumar",
    hospital_name: "Max Super Speciality Hospital, Saket",
    doctor_name: "Dr. Ashish Chandra (Cardiology)",
    diagnosis: "Coronary Artery Disease (STEMI)",
    documents: [
      { id: "doc-rk-1", file_name: "admission_record.pdf", file_type: "application/pdf", uploaded_at: new Date(Date.now() - 3600000 * 2).toISOString() },
      { id: "doc-rk-2", file_name: "angioplasty_report.pdf", file_type: "application/pdf", uploaded_at: new Date(Date.now() - 3600000 * 2).toISOString() },
      { id: "doc-rk-3", file_name: "discharge_summary.pdf", file_type: "application/pdf", uploaded_at: new Date(Date.now() - 3600000 * 2).toISOString() },
      { id: "doc-rk-4", file_name: "final_invoice.pdf", file_type: "application/pdf", uploaded_at: new Date(Date.now() - 3600000 * 2).toISOString() }
    ]
  },
  {
    id: "00000000-0000-0000-0000-000000000002",
    status: "VALIDATION_FAILED",
    created_at: new Date(Date.now() - 3600000 * 5).toISOString(), // 5 hours ago
    policy_id: "POL-APO-77123",
    patient_id: "PAT-PR-29",
    patient_name: "Priyadarshini Rao",
    hospital_name: "Apollo Cradle Hospital, Bangalore",
    doctor_name: "Dr. Latha Reddy (OB-GYN)",
    diagnosis: "LSCS Delivery (Breech Presentation)",
    documents: [
      { id: "doc-pr-1", file_name: "maternity_case_sheet.pdf", file_type: "application/pdf", uploaded_at: new Date(Date.now() - 3600000 * 5).toISOString() },
      { id: "doc-pr-2", file_name: "lscs_procedure_notes.pdf", file_type: "application/pdf", uploaded_at: new Date(Date.now() - 3600000 * 5).toISOString() },
      { id: "doc-pr-3", file_name: "apollo_bill_itemized.pdf", file_type: "application/pdf", uploaded_at: new Date(Date.now() - 3600000 * 5).toISOString() }
    ]
  },
  {
    id: "00000000-0000-0000-0000-000000000003",
    status: "APPROVED",
    created_at: new Date(Date.now() - 3600000 * 24).toISOString(), // 1 day ago
    policy_id: "POL-TATA-33291",
    patient_id: "PAT-AS-48",
    patient_name: "Amit Shah",
    hospital_name: "Tata Memorial Hospital, Mumbai",
    doctor_name: "Dr. Sanjay Deshmukh (Oncology)",
    diagnosis: "Colon Cancer (Chemotherapy Session 4)",
    documents: [
      { id: "doc-as-1", file_name: "daycare_chemo_admission.pdf", file_type: "application/pdf", uploaded_at: new Date(Date.now() - 3600000 * 24).toISOString() },
      { id: "doc-as-2", file_name: "oncology_treatment_plan.pdf", file_type: "application/pdf", uploaded_at: new Date(Date.now() - 3600000 * 24).toISOString() },
      { id: "doc-as-3", file_name: "pharmacy_invoice_chemo.pdf", file_type: "application/pdf", uploaded_at: new Date(Date.now() - 3600000 * 24).toISOString() }
    ]
  },
  {
    id: "00000000-0000-0000-0000-000000000004",
    status: "MANUAL_REVIEW_REQUIRED",
    created_at: new Date(Date.now() - 3600000 * 30).toISOString(), // 1.2 days ago
    policy_id: "POL-FOR-55610",
    patient_id: "PAT-SD-67",
    patient_name: "Sarla Devi",
    hospital_name: "Fortis Memorial Research Institute, Gurugram",
    doctor_name: "Dr. Vikram Sethi (Orthopedics)",
    diagnosis: "Severe Bilateral Knee Osteoarthritis",
    documents: [
      { id: "doc-sd-1", file_name: "admission_clinical_notes.pdf", file_type: "application/pdf", uploaded_at: new Date(Date.now() - 3600000 * 30).toISOString() },
      { id: "doc-sd-2", file_name: "total_knee_arthroplasty_notes.pdf", file_type: "application/pdf", uploaded_at: new Date(Date.now() - 3600000 * 30).toISOString() },
      { id: "doc-sd-3", file_name: "implant_sticker_dossier.pdf", file_type: "application/pdf", uploaded_at: new Date(Date.now() - 3600000 * 30).toISOString() },
      { id: "doc-sd-4", file_name: "fortis_final_breakdown.pdf", file_type: "application/pdf", uploaded_at: new Date(Date.now() - 3600000 * 30).toISOString() }
    ]
  },
  {
    id: "00000000-0000-0000-0000-000000000005",
    status: "COMPLETED",
    created_at: new Date(Date.now() - 3600000 * 48).toISOString(), // 2 days ago
    policy_id: "POL-KDA-12109",
    patient_id: "PAT-AM-12",
    patient_name: "Aarav Mehta",
    hospital_name: "Kokilaben Dhirubhai Ambani Hospital, Mumbai",
    doctor_name: "Dr. Meera Patel (Pediatrics)",
    diagnosis: "Severe Dengue Hemorrhagic Fever",
    documents: [
      { id: "doc-am-1", file_name: "emergency_admission_sheet.pdf", file_type: "application/pdf", uploaded_at: new Date(Date.now() - 3600000 * 48).toISOString() },
      { id: "doc-am-2", file_name: "daily_lab_reports_platelets.pdf", file_type: "application/pdf", uploaded_at: new Date(Date.now() - 3600000 * 48).toISOString() },
      { id: "doc-am-3", file_name: "hospital_invoice_dengue.pdf", file_type: "application/pdf", uploaded_at: new Date(Date.now() - 3600000 * 48).toISOString() }
    ]
  }
];

// 2. Full Preview & Report Data for each static ID
export const MOCK_PREVIEW_DATA: Record<string, PreviewData> = {
  // 1. Rajesh Kumar
  "00000000-0000-0000-0000-000000000001": {
    claim_id: "00000000-0000-0000-0000-000000000001",
    status: "MANUAL_REVIEW_REQUIRED",
    policy_id: "POL-MAX-90812",
    billed_total: 385000,
    expense_total: 385000,
    parsed_fields: {
      patient_name: "Rajesh Kumar",
      policy_number: "POL-MAX-90812",
      age: "54",
      gender: "Male",
      hospital_name: "Max Super Speciality Hospital, Saket, New Delhi",
      doctor_name: "Dr. Ashish Chandra (Cardiology)",
      admission_date: "2026-06-05",
      discharge_date: "2026-06-10",
      diagnosis: "Acute Coronary Syndrome (STEMI), Double Vessel Disease",
      history_of_present_illness: "54-year-old male presented with crushing retrosternal chest pain radiating to the left arm for 4 hours, associated with diaphoresis. ECG showed ST elevation in inferior leads II, III, aVF.",
      past_history: "Known hypertensive for 8 years on Tab. Amlodipine 5mg. Non-diabetic.",
      treatment: "Coronary Angiography followed by Percutaneous Transluminal Coronary Angioplasty (PTCA) with placement of 2 Drug Eluting Stents (DES) in RCA and LAD.",
      discharge_summary: "Patient was admitted in cardiac ICU, monitored, initiated on double anti-platelet therapy (Aspirin + Ticagrelor). Angioplasty performed successfully. Discharged in hemodynamically stable condition.",
      bank_name: "State Bank of India",
      bank_branch: "Saket Metro Branch, New Delhi",
      account_holder: "Rajesh Kumar",
      account_number: "20448102391",
      ifsc_code: "SBIN0014292",
      total_amount: "385000"
    },
    summary: {
      patient_name: "Rajesh Kumar",
      policy_number: "POL-MAX-90812",
      age: "54",
      gender: "Male",
      hospital: "Max Super Speciality Hospital, Saket, New Delhi",
      doctor: "Dr. Ashish Chandra (Cardiology)",
      admission_date: "2026-06-05",
      discharge_date: "2026-06-10",
      diagnosis: "Acute Coronary Syndrome (STEMI), Double Vessel Disease",
      history_of_present_illness: "54-year-old male with crushing chest pain radiating to left arm. ST elevation in inferior leads.",
      treatment: "Coronary Angioplasty (PTCA) + 2 DES (LAD, RCA)",
      total_amount: "385000.00",
      icd_count: 2,
      cpt_count: 2,
      risk_score: 0.68,
      validation_passed: 2,
      validation_total: 4,
      manual_review_required: true
    },
    icd_codes: [
      { code: "I21.1", description: "Acute transmural myocardial infarction of inferior wall", confidence: 0.98, is_primary: true, estimated_cost: 280000 },
      { code: "I25.10", description: "Atherosclerotic heart disease of native coronary artery without angina pectoris", confidence: 0.92, is_primary: false, estimated_cost: 105000 }
    ],
    cpt_codes: [
      { code: "92928", description: "Percutaneous transcatheter coronary stent placement, single major coronary artery", confidence: 0.96, estimated_cost: 150000 },
      { code: "92929", description: "Percutaneous transcatheter coronary stent placement, each additional coronary artery", confidence: 0.91, estimated_cost: 120000 }
    ],
    cost_summary: { icd_total: 385000, cpt_total: 270000, grand_total: 385000 },
    expenses: [
      { category: "ICU Room Rent (3 days @ ₹12000)", amount: 36000, source_field: "icu_charges", model_version: "parser-v2" },
      { category: "Cardiology Ward Bed (2 days @ ₹8000)", amount: 16000, source_field: "ward_charges", model_version: "parser-v2" },
      { category: "Coronary Angioplasty Procedure", amount: 150000, source_field: "surgical_charges", model_version: "parser-v2" },
      { category: "Drug Eluting Stents (2 units @ ₹60000)", amount: 120000, source_field: "implant_charges", model_version: "parser-v2" },
      { category: "Pharmacy & Cardiac Consumables", amount: 43000, source_field: "pharmacy_charges", model_version: "parser-v2" },
      { category: "Cardiac Diagnostics (Angio, ECG, Lab)", amount: 20000, source_field: "investigation_charges", model_version: "parser-v2" }
    ],
    predictions: [
      {
        rejection_score: 0.68,
        model_name: "ClaimRejectionNet-v3.1",
        top_reasons: [
          { reason: "ICU room rent (₹12,000/day) exceeds the policy-defined sum-insured cap of 1% (₹5,000/day).", weight: 0.42 },
          { reason: "Drug Eluting Stent unit price (₹60,000) exceeds GIPSA/GCN tariff agreement maximum (₹52,000/stent).", weight: 0.38 }
        ]
      }
    ],
    validations: [
      { rule_id: "sum_insured_check", rule_name: "Sum Insured Verification", severity: "INFO", message: "Claim total (₹3.85 Lakh) is within the policy sum insured of ₹5.00 Lakh.", passed: true },
      { rule_id: "room_rent_limit", rule_name: "ICU Room Rent Ceiling Check", severity: "WARNING", message: "ICU room rent of ₹12,000/day exceeds the GIPSA room rent cap (₹5,000/day for Normal / ₹10,000/day for ICU). Excess ₹6,000 total flagged.", passed: false },
      { rule_id: "tariff_agreement", rule_name: "GIPSA Stent Price Check", severity: "WARNING", message: "DES stent billed at ₹60,000 per unit. Tariff cap is ₹52,000 per unit. Billed total exceeds agreement by ₹16,000.", passed: false },
      { rule_id: "billing_integrity", rule_name: "Billing Column Addition Audit", severity: "INFO", message: "All itemized charges match the final billed invoice subtotal.", passed: true }
    ],
    ocr_excerpt: "MAX SUPER SPECIALITY HOSPITAL, SAKET\nPATIENT NAME: RAJESH KUMAR, AGE: 54, GENDER: M\nIP NO: IP-998821, POLICY ID: POL-MAX-90812\nDIAGNOSIS: ACUTE INFERIOR WALL MI (STEMI)\nPROCEDURE: CORONARY ANGIOPLASTY (PTCA) TO RCA & LAD WITH 2 DRUG ELUTING STENTS\nICU ROOM CHARGES: 3 DAYS @ RS. 12,000 = RS. 36,000\nWARD CHARGES: 2 DAYS @ RS. 8,000 = RS. 16,000\nANGIOPLASTY CHARGES: RS. 1,50,000\nSTENT CHARGES (2 DES): RS. 1,20,000\nPHARMACY: RS. 43,000, INVESTIGATIONS: RS. 20,000\nTOTAL BILLED AMOUNT: RS. 3,85,000\nPAID VIA SBI ACCOUNT: 20448102391, IFSC: SBIN0014292",
    brain_insights: [
      "🚨 **Tariff Restriction**: Billed stents exceed GIPSA limits. Stent unit cost must be reduced from ₹60,000 to ₹52,000. Potential savings: **₹16,000**.",
      "⚠️ **Room Rent Capping**: ICU room rent exceeds sum-insured cap by ₹2,000/day. Deductible amount: **₹6,000**.",
      "💡 **Pre-Auth Match**: Procedure matches Pre-Authorization Ref #PA-MAX-1291 approved for cashless angioplasty on 2026-06-05."
    ],
    reimbursement_brain: {
      documents_analyzed: [
        { file_name: "admission_record.pdf", doc_type: "Admission Request Sheet", fields_found: { patient_name: "Rajesh Kumar", policy_id: "POL-MAX-90812" }, text_length: 820 },
        { file_name: "angioplasty_report.pdf", doc_type: "OT notes", fields_found: { procedure: "PTCA", implants: "2 DES" }, text_length: 1240 },
        { file_name: "final_invoice.pdf", doc_type: "Hospital Bill", fields_found: { total: "385000" }, text_length: 1980 }
      ],
      cross_references: [
        { field: "patient_name", sources: [{ doc: "admission_record.pdf", doc_type: "Admission", value: "Rajesh Kumar" }, { doc: "final_invoice.pdf", doc_type: "Bill", value: "Rajesh Kumar" }], status: "MATCHED" },
        { field: "procedure", sources: [{ doc: "angioplasty_report.pdf", doc_type: "OT notes", value: "PTCA with 2 Stents" }, { doc: "final_invoice.pdf", doc_type: "Bill", value: "2 DES Stents Billed" }], status: "MATCHED" }
      ],
      reimbursement_checklist: [
        { item: "Discharge Summary Signed", status: "YES", reason: "Found signature of Dr. Ashish Chandra on page 3." },
        { item: "Implant Sticker File", status: "YES", reason: "Verified implant invoices contain serial barcode stickers for Zimmer/Abbott stents." },
        { item: "Detailed Pharmacy Bill", status: "YES", reason: "Itemized pharmacy ledger provided." },
        { item: "Valid ID Proof (Aadhaar/PAN)", status: "YES", reason: "Aadhaar card copy found in attachment dossier." }
      ],
      insights: [
        { type: "rejection_risk", category: "Tariff Limit", text: "Stent cost exceeds GIPSA cap. Deduct ₹16,000." },
        { type: "policy_limitation", category: "Room Rent Limit", text: "ICU charges exceed cap. Deduct ₹6,000." }
      ],
      completeness_pct: 100
    },
    scan_analyses: [
      {
        id: "scan-rk-1",
        scan_type: "Coronary Angiogram",
        body_part: "Heart / Coronary Arteries",
        modality: "X-RAY ANGIOGRAPHY",
        findings: [
          { finding: "Severe stenosis in mid Right Coronary Artery (RCA) - 90%", severity: "CRITICAL", confidence: 0.95 },
          { finding: "Significant stenosis in Left Anterior Descending (LAD) - 80%", severity: "HIGH", confidence: 0.92 }
        ],
        impression: "Double Vessel Disease with acute inferior wall infarction successfully treated via dual coronary angioplasty.",
        recommendation: "Dual antiplatelet therapy for 12 months. Strict cardiovascular follow-up.",
        confidence: 0.96,
        is_abnormal: true,
        file_name: "angioplasty_report.pdf"
      }
    ]
  },

  // 2. Priyadarshini Rao
  "00000000-0000-0000-0000-000000000002": {
    claim_id: "00000000-0000-0000-0000-000000000002",
    status: "VALIDATION_FAILED",
    policy_id: "POL-APO-77123",
    billed_total: 145000,
    expense_total: 145000,
    parsed_fields: {
      patient_name: "Priyadarshini Rao",
      policy_number: "POL-APO-77123",
      age: "29",
      gender: "Female",
      hospital_name: "Apollo Cradle Hospital, Bangalore",
      doctor_name: "Dr. Latha Reddy (OB-GYN)",
      admission_date: "2026-06-04",
      discharge_date: "2026-06-07",
      diagnosis: "LSCS Delivery (Caesarean Section) due to Breech Presentation and fetal distress",
      history_of_present_illness: "29-year-old Primigravida at 39 weeks gestation admitted with complaints of abdominal pain and decreased fetal movements. Ultrasound showed breech presentation and mild fetal bradycardia.",
      past_history: "No significant comorbidities. Hypothyroid on Thyronorm 25mcg.",
      treatment: "Lower Segment Caesarean Section (LSCS) performed under spinal anesthesia. Delivered a healthy male infant.",
      discharge_summary: "Post-operative course was uneventful. Pain controlled. Breastfeeding well. Wound healthy. Discharged with advice on wound care.",
      bank_name: "HDFC Bank",
      bank_branch: "Koramangala 4th Block, Bangalore",
      account_holder: "Priyadarshini Rao",
      account_number: "501002349018",
      ifsc_code: "HDFC0000104",
      total_amount: "145000"
    },
    summary: {
      patient_name: "Priyadarshini Rao",
      policy_number: "POL-APO-77123",
      age: "29",
      gender: "Female",
      hospital: "Apollo Cradle Hospital, Bangalore",
      doctor: "Dr. Latha Reddy (OB-GYN)",
      admission_date: "2026-06-04",
      discharge_date: "2026-06-07",
      diagnosis: "LSCS Delivery (Caesarean Section)",
      history_of_present_illness: "Primigravida at 39 weeks with breech presentation and fetal distress.",
      treatment: "LSCS Delivery under spinal anesthesia.",
      total_amount: "145000.00",
      icd_count: 2,
      cpt_count: 1,
      risk_score: 0.15,
      validation_passed: 2,
      validation_total: 3,
      manual_review_required: true
    },
    icd_codes: [
      { code: "O82", description: "Single delivery by cesarean section", confidence: 0.99, is_primary: true, estimated_cost: 110000 },
      { code: "O32.1", description: "Maternal care for breech presentation", confidence: 0.95, is_primary: false, estimated_cost: 35000 }
    ],
    cpt_codes: [
      { code: "59510", description: "Routine obstetric care including antepartum care, cesarean delivery, and postpartum care", confidence: 0.97, estimated_cost: 145000 }
    ],
    cost_summary: { icd_total: 145000, cpt_total: 145000, grand_total: 145000 },
    expenses: [
      { category: "Luxury Room Rent (3 days @ ₹8000)", amount: 24000, source_field: "room_charges", model_version: "parser-v2" },
      { category: "Operation Theatre (OT) & Anesthesia charges", amount: 45000, source_field: "ot_charges", model_version: "parser-v2" },
      { category: "Obstetrician Delivery Fees", amount: 35000, source_field: "professional_fees", model_version: "parser-v2" },
      { category: "Neonatal Care & Pediatrician Fees", amount: 15000, source_field: "pediatric_fees", model_version: "parser-v2" },
      { category: "Maternity Pharmacy & Consumables", amount: 18000, source_field: "pharmacy_charges", model_version: "parser-v2" },
      { category: "Diagnostics & Pre-operative USG", amount: 13000, source_field: "lab_charges", model_version: "parser-v2" }
    ],
    predictions: [
      {
        rejection_score: 0.15,
        model_name: "ClaimRejectionNet-v3.1",
        top_reasons: [
          { reason: "Maternity sub-limit clause cap of ₹50,000 applies. Remainder of ₹95,000 is client liability.", weight: 0.95 }
        ]
      }
    ],
    validations: [
      { rule_id: "maternity_limit_check", rule_name: "Maternity Sub-Limit Caps Check", severity: "CRITICAL", message: "Billed amount (₹1,45,000) exceeds maternity cover sub-limit of ₹50,000 for LSCS. Excess ₹95,000 will be marked non-payable.", passed: false },
      { rule_id: "waiting_period_check", rule_name: "Maternity Coverage Waiting Period", severity: "INFO", message: "Maternity waiting period of 9 months satisfied (Policy active for 22 months).", passed: true },
      { rule_id: "sum_insured_check", rule_name: "Sum Insured Check", severity: "INFO", message: "Claim fits within general sum insured (₹3.00 Lakh).", passed: true }
    ],
    ocr_excerpt: "APOLLO CRADLE HOSPITAL, KORAMANGALA, BANGALORE\nPATIENT: PRIYADARSHINI RAO, AGE: 29, GENDER: F\nOP NO: OP-87612, POLICY ID: POL-APO-77123\nDIAGNOSIS: SINGLE LIVE FETUS at 39 WEEKS, BREECH PRESENTATION\nPROCEDURE: LSCS DELIVERY UNDER SPINAL ANESTHESIA\nROOM RENT (LUXURY SUITE): 3 DAYS @ RS. 8,000 = RS. 24,000\nOT & ANESTHESIA CHARGES: RS. 45,000\nOBSTETRICIAN FEES: RS. 35,000\nNEONATAL/PEDIATRIC VISIT: RS. 15,000\nPHARMACY/CONSUMABLES: RS. 18,000, LABS/USG: RS. 13,000\nTOTAL BILL: RS. 1,45,000\nBANK DETAILS: HDFC BANK, A/C: 501002349018, IFSC: HDFC0000104",
    brain_insights: [
      "📌 **Maternity Cap Limit**: Policy has strict maternity capping. Caesarean section delivery (LSCS) limit is ₹50,000. Deductible amount: **₹95,000** (co-pay and client share).",
      "💡 **Neonatal Coverage**: Neonatal pediatrician charges (₹15,000) are accepted under the mother's maternity sub-limit but still subject to the ₹50,000 overall limit."
    ],
    reimbursement_brain: {
      documents_analyzed: [
        { file_name: "maternity_case_sheet.pdf", doc_type: "Admission Form", fields_found: { patient_name: "Priyadarshini Rao", policy_id: "POL-APO-77123" }, text_length: 710 },
        { file_name: "apollo_bill_itemized.pdf", doc_type: "Hospital Bill", fields_found: { total: "145000" }, text_length: 1540 }
      ],
      cross_references: [
        { field: "patient_name", sources: [{ doc: "maternity_case_sheet.pdf", doc_type: "Admission", value: "Priyadarshini Rao" }, { doc: "apollo_bill_itemized.pdf", doc_type: "Bill", value: "Priyadarshini Rao" }], status: "MATCHED" }
      ],
      reimbursement_checklist: [
        { item: "Discharge Summary Signed", status: "YES", reason: "Signed by Dr. Latha Reddy." },
        { item: "Birth Certificate Copy", status: "YES", reason: "Found in attachment folder." },
        { item: "Maternity Pre-Auth", status: "YES", reason: "Pre-Auth ref #PA-APO-9912 approved." }
      ],
      insights: [
        { type: "rejection_risk", category: "Maternity limit", text: "Caesarean limit is ₹50,000. Balance of ₹95,000 is co-pay/client share." }
      ],
      completeness_pct: 100
    }
  },

  // 3. Amit Shah
  "00000000-0000-0000-0000-000000000003": {
    claim_id: "00000000-0000-0000-0000-000000000003",
    status: "APPROVED",
    policy_id: "POL-TATA-33291",
    billed_total: 92000,
    expense_total: 92000,
    parsed_fields: {
      patient_name: "Amit Shah",
      policy_number: "POL-TATA-33291",
      age: "48",
      gender: "Male",
      hospital_name: "Tata Memorial Hospital, Parel, Mumbai",
      doctor_name: "Dr. Sanjay Deshmukh (Oncology)",
      admission_date: "2026-06-09",
      discharge_date: "2026-06-09",
      diagnosis: "Adenocarcinoma of Colon, Stage III (FOLFOX regimen)",
      history_of_present_illness: "48-year-old male with diagnosed adenocarcinoma of colon, stage III. Admitted for chemotherapy daycare cycle 4 (FOLFOX protocol). Last cycle tolerated well.",
      past_history: "Post left hemicolectomy in January 2026. Non-diabetic, non-hypertensive.",
      treatment: "Intravenous administration of Oxaliplatin, Leucovorin, and 5-Fluorouracil via chemoport under oncologist supervision.",
      discharge_summary: "Daycare chemo session completed uneventfully. Port flushed. No immediate side-effects. Discharged on anti-emetics.",
      bank_name: "ICICI Bank",
      bank_branch: "Parel Branch, Mumbai",
      account_holder: "Amit Shah",
      account_number: "000491823901",
      ifsc_code: "ICIC0000004",
      total_amount: "92000"
    },
    summary: {
      patient_name: "Amit Shah",
      policy_number: "POL-TATA-33291",
      age: "48",
      gender: "Male",
      hospital: "Tata Memorial Hospital, Parel, Mumbai",
      doctor: "Dr. Sanjay Deshmukh (Oncology)",
      admission_date: "2026-06-09",
      discharge_date: "2026-06-09",
      diagnosis: "Adenocarcinoma of Colon (Stage III)",
      history_of_present_illness: "Daycare Chemotherapy Cycle 4 under FOLFOX regimen.",
      treatment: "IV Oxaliplatin, Leucovorin, 5-FU chemo infusion.",
      total_amount: "92000.00",
      icd_count: 2,
      cpt_count: 1,
      risk_score: 0.08,
      validation_passed: 2,
      validation_total: 2,
      manual_review_required: false
    },
    icd_codes: [
      { code: "C18.9", description: "Malignant neoplasm of colon, unspecified", confidence: 0.97, is_primary: true, estimated_cost: 80000 },
      { code: "Z51.11", description: "Encounter for antineoplastic chemotherapy", confidence: 0.99, is_primary: false, estimated_cost: 12000 }
    ],
    cpt_codes: [
      { code: "96413", description: "Chemotherapy administration, intravenous infusion; up to 1 hour, single or initial substance/drug", confidence: 0.95, estimated_cost: 92000 }
    ],
    cost_summary: { icd_total: 92000, cpt_total: 92000, grand_total: 92000 },
    expenses: [
      { category: "Daycare Chemotherapy Bed Rent (1 day)", amount: 3500, source_field: "room_charges", model_version: "parser-v2" },
      { category: "Chemotherapy Drug Infusion (Oxaliplatin, Leucovorin)", amount: 68000, source_field: "pharmacy_charges", model_version: "parser-v2" },
      { category: "Oncologist Consultation Fees", amount: 7500, source_field: "professional_fees", model_version: "parser-v2" },
      { category: "Supportive Care & Anti-emetic Drugs", amount: 8000, source_field: "pharmacy_charges", model_version: "parser-v2" },
      { category: "Pre-chemo Diagnostics (CBC, LFT, CEA)", amount: 5000, source_field: "lab_charges", model_version: "parser-v2" }
    ],
    predictions: [
      {
        rejection_score: 0.08,
        model_name: "ClaimRejectionNet-v3.1",
        top_reasons: []
      }
    ],
    validations: [
      { rule_id: "daycare_procedure_check", rule_name: "Daycare Chemotherapy Coverage Check", severity: "INFO", message: "Chemotherapy daycare procedure is fully covered without 24-hour hospitalization constraint.", passed: true },
      { rule_id: "waiting_period_check", rule_name: "Pre-existing Cancer Waiting Period Check", severity: "INFO", message: "3-year cancer waiting period is satisfied (Policy age is 4 years).", passed: true }
    ],
    ocr_excerpt: "TATA MEMORIAL HOSPITAL, PAREL, MUMBAI\nDAYCARE CHEMOTHERAPY REPORT\nPATIENT: AMIT SHAH, AGE: 48, GENDER: M\nIP NO: TMH-44918, POLICY ID: POL-TATA-33291\nDIAGNOSIS: ADENOCARCINOMA OF COLON, STAGE III\nTREATMENT: FOLFOX CYCLE 4 INFUSION VIA CHEMAPORT\nDAYCARE WARD BED: RS. 3,500\nCHEMOTHERAPY DRUGS: RS. 68,000\nONCOLOGIST VISIT FEES: RS. 7,500\nSUPPORTIVE DRUGS: RS. 8,000\nLABS (CBC/LFT/CEA): RS. 5,000\nTOTAL BILL: RS. 92,000\nPAID VIA ICICI A/C: 000491823901, IFSC: ICIC0000004",
    brain_insights: [
      "✅ **Approved for Cashless**: Daycare oncology procedure conforms exactly to Standard Treatment Guidelines (STG) for FOLFOX.",
      "💡 **Sub-limit Exemption**: Chemotherapy drugs are exempt from generic drug caps. Full reimbursement approved."
    ],
    reimbursement_brain: {
      documents_analyzed: [
        { file_name: "daycare_chemo_admission.pdf", doc_type: "Daycare Sheet", fields_found: { patient_name: "Amit Shah" }, text_length: 540 },
        { file_name: "pharmacy_invoice_chemo.pdf", doc_type: "Drug Bill", fields_found: { total: "68000" }, text_length: 910 }
      ],
      cross_references: [
        { field: "patient_name", sources: [{ doc: "daycare_chemo_admission.pdf", doc_type: "Admission", value: "Amit Shah" }, { doc: "pharmacy_invoice_chemo.pdf", doc_type: "Bill", value: "Amit Shah" }], status: "MATCHED" }
      ],
      reimbursement_checklist: [
        { item: "Chemo Prescription Uploaded", status: "YES", reason: "Found oncology script by Dr. Sanjay Deshmukh." },
        { item: "Hemogram (CBC) Report", status: "YES", reason: "CBC showing WBC 4.8 / Platelets 1.5L before infusion found." }
      ],
      insights: [
        { type: "rejection_risk", category: "Policy coverage", text: "Full daycare coverage approved." }
      ],
      completeness_pct: 100
    }
  },

  // 4. Sarla Devi
  "00000000-0000-0000-0000-000000000004": {
    claim_id: "00000000-0000-0000-0000-000000000004",
    status: "MANUAL_REVIEW_REQUIRED",
    policy_id: "POL-FOR-55610",
    billed_total: 290000,
    expense_total: 290000,
    parsed_fields: {
      patient_name: "Sarla Devi",
      policy_number: "POL-FOR-55610",
      age: "67",
      gender: "Female",
      hospital_name: "Fortis Memorial Research Institute, Gurugram",
      doctor_name: "Dr. Vikram Sethi (Orthopedics)",
      admission_date: "2026-06-01",
      discharge_date: "2026-06-05",
      diagnosis: "Severe Bilateral Osteoarthritis of Knee Joints",
      history_of_present_illness: "67-year-old female complaining of bilateral knee pain (left > right) for 5 years, worsening recently. Severe pain on weight-bearing, walking restriction < 50 meters. X-rays showed complete joint space loss.",
      past_history: "Diabetic for 12 years on Tab. Metformin 500mg. Thyroid on Eltroxin.",
      treatment: "Left Total Knee Arthroplasty (TKA) performed using Zimmer high-flexion total knee implant under spinal anesthesia.",
      discharge_summary: "Post-op recovery satisfactory. Wound clean, dressing dry. In-hospital physiotherapy initiated. Patient mobilizing with walker. Discharged with home physiotherapy guidelines.",
      bank_name: "Punjab National Bank",
      bank_branch: "Sushant Lok, Gurugram",
      account_holder: "Sarla Devi",
      account_number: "087122094812",
      ifsc_code: "PUNB0087100",
      total_amount: "290000"
    },
    summary: {
      patient_name: "Sarla Devi",
      policy_number: "POL-FOR-55610",
      age: "67",
      gender: "Female",
      hospital: "Fortis Memorial Research Institute, Gurugram",
      doctor: "Dr. Vikram Sethi (Orthopedics)",
      admission_date: "2026-06-01",
      discharge_date: "2026-06-05",
      diagnosis: "Bilateral Knee Osteoarthritis",
      history_of_present_illness: "Bilateral knee joint space loss, severe osteophyte formation. Restricting walking.",
      treatment: "Left Total Knee Arthroplasty (TKA) using Zimmer Knee Joint.",
      total_amount: "290000.00",
      icd_count: 1,
      cpt_count: 1,
      risk_score: 0.22,
      validation_passed: 2,
      validation_total: 3,
      manual_review_required: true
    },
    icd_codes: [
      { code: "M17.12", description: "Unilateral primary osteoarthritis, left knee", confidence: 0.96, is_primary: true, estimated_cost: 290000 }
    ],
    cpt_codes: [
      { code: "27447", description: "Arthroplasty, knee, condyle and patella; total knee arthroplasty (TKR)", confidence: 0.98, estimated_cost: 290000 }
    ],
    cost_summary: { icd_total: 290000, cpt_total: 290000, grand_total: 290000 },
    expenses: [
      { category: "Deluxe Single Room Rent (4 days @ ₹6000)", amount: 24000, source_field: "room_charges", model_version: "parser-v2" },
      { category: "Total Knee Replacement (OT Charges)", amount: 65000, source_field: "ot_charges", model_version: "parser-v2" },
      { category: "Orthopedic Surgeon Fees", amount: 55000, source_field: "professional_fees", model_version: "parser-v2" },
      { category: "Zimmer Knee Joint Implant", amount: 95000, source_field: "implant_charges", model_version: "parser-v2" },
      { category: "In-hospital Physiotherapy (3 sessions)", amount: 12000, source_field: "physio_charges", model_version: "parser-v2" },
      { category: "Orthopedic Pharmacy & Consumables", amount: 23000, source_field: "pharmacy_charges", model_version: "parser-v2" },
      { category: "Diagnostics (Bilateral X-Ray, ECG, Labs)", amount: 16000, source_field: "investigation_charges", model_version: "parser-v2" }
    ],
    predictions: [
      {
        rejection_score: 0.22,
        model_name: "ClaimRejectionNet-v3.1",
        top_reasons: [
          { reason: "Implant sticker sheet verification pending. Missing manufacturer invoice barcode sticker.", weight: 0.85 }
        ]
      }
    ],
    validations: [
      { rule_id: "implant_verification", rule_name: "Implant Barcode Sticker Verification", severity: "CRITICAL", message: "Joint implant Zimmer billed at ₹95,000 lacks the original product serial barcode sticker. Required for audit verification.", passed: false },
      { rule_id: "room_rent_limit", rule_name: "Room Rent Eligibility Check", severity: "INFO", message: "Billed room rent ₹6,000/day is within the policy-allowed limit of ₹8,000/day.", passed: true },
      { rule_id: "sum_insured_check", rule_name: "Sum Insured Eligibility Check", severity: "INFO", message: "Billed total (₹2.90 Lakh) is within the policy sum insured of ₹4.00 Lakh.", passed: true }
    ],
    ocr_excerpt: "FORTIS MEMORIAL RESEARCH INSTITUTE, GURUGRAM\nPATIENT: SARLA DEVI, AGE: 67, GENDER: F\nIP NO: F-899120, POLICY ID: POL-FOR-55610\nDIAGNOSIS: BILATERAL OSTEOARTHRITIS OF KNEE JOINTS\nPROCEDURE: LEFT TOTAL KNEE REPLACEMENT\nIMPLANT: ZIMMER CR HIGH FLEX JOINT ASSEMBLY\nROOM CHARGES (DELUXE): 4 DAYS @ RS. 6,000 = RS. 24,000\nOT FEES: RS. 65,000, SURGEON CHARGES: RS. 55,000\nIMPLANT AMOUNT: RS. 95,000\nPHYSIOTHERAPY CHARGES: RS. 12,000\nPHARMACY: RS. 23,000, X-RAYS/LABS: RS. 16,000\nTOTAL BILLED AMOUNT: RS. 2,90,000\nPUNJAB NATIONAL BANK: A/C: 087122094812, IFSC: PUNB0087100",
    brain_insights: [
      "🚨 **Implant Audit**: Zimmer Knee joint billed. Sticker sheet is missing. Please prompt the user/provider to upload the original Zimmer serial sticker sheet.",
      "✅ **Physio Covered**: Post-op inpatient physiotherapy charges (₹12,000) are fully verified and approved as clinical standard."
    ],
    reimbursement_brain: {
      documents_analyzed: [
        { file_name: "total_knee_arthroplasty_notes.pdf", doc_type: "OT notes", fields_found: { procedure: "TKR", implant: "Zimmer" }, text_length: 1100 },
        { file_name: "fortis_final_breakdown.pdf", doc_type: "Hospital Bill", fields_found: { total: "290000" }, text_length: 1680 }
      ],
      cross_references: [
        { field: "patient_name", sources: [{ doc: "fortis_final_breakdown.pdf", doc_type: "Bill", value: "Sarla Devi" }], status: "MATCHED" }
      ],
      reimbursement_checklist: [
        { item: "Implant Sticker Sheet", status: "NO", reason: "Barcode sticker file missing in the scan dossier." },
        { item: "Detailed Bill", status: "YES", reason: "Detailed GIPSA-format bill found." }
      ],
      insights: [
        { type: "rejection_risk", category: "Audit Defect", text: "Implant serial sticker required." }
      ],
      completeness_pct: 85
    }
  },

  // 5. Aarav Mehta
  "00000000-0000-0000-0000-000000000005": {
    claim_id: "00000000-0000-0000-0000-000000000005",
    status: "COMPLETED",
    policy_id: "POL-KDA-12109",
    billed_total: 68000,
    expense_total: 68000,
    parsed_fields: {
      patient_name: "Aarav Mehta",
      policy_number: "POL-KDA-12109",
      age: "12",
      gender: "Male",
      hospital_name: "Kokilaben Dhirubhai Ambani Hospital, Mumbai",
      doctor_name: "Dr. Meera Patel (Pediatrics)",
      admission_date: "2026-06-03",
      discharge_date: "2026-06-07",
      diagnosis: "Severe Dengue Hemorrhagic Fever (DHF) with Thrombocytopenia",
      history_of_present_illness: "12-year-old male child presented with high-grade fever for 5 days, severe headache, body ache, and vomiting. Platelet count at admission was 22,000/μL. Active petechiae noted.",
      past_history: "No previous hospitalizations, normal developmental milestones.",
      treatment: "Admitted to Pediatric ICU for close monitoring. IV fluid therapy, oral paracetamol. Transfused 2 units of Platelet Concentrate on Day 2 due to platelet count drop to 15,000/μL.",
      discharge_summary: "Platelet counts rose progressively to 1.10 Lakh. Patient afebrile for 48 hours, tolerating diet. Discharged with instruction for follow-up CBC.",
      bank_name: "Kotak Mahindra Bank",
      bank_branch: "Andheri West, Mumbai",
      account_holder: "Siddharth Mehta (Father)",
      account_number: "90129841029",
      ifsc_code: "KKBK0000642",
      total_amount: "68000"
    },
    summary: {
      patient_name: "Aarav Mehta",
      policy_number: "POL-KDA-12109",
      age: "12",
      gender: "Male",
      hospital: "Kokilaben Dhirubhai Ambani Hospital, Mumbai",
      doctor: "Dr. Meera Patel (Pediatrics)",
      admission_date: "2026-06-03",
      discharge_date: "2026-06-07",
      diagnosis: "Severe Dengue Hemorrhagic Fever",
      history_of_present_illness: "Pediatric severe dengue, platelet count dropped to 15,000/μL with active bleeding risk.",
      treatment: "ICU monitoring, IV fluids, 2 units platelet concentrate transfusion.",
      total_amount: "68000.00",
      icd_count: 2,
      cpt_count: 1,
      risk_score: 0.35,
      validation_passed: 1,
      validation_total: 2,
      manual_review_required: true
    },
    icd_codes: [
      { code: "A91", description: "Dengue hemorrhagic fever", confidence: 0.98, is_primary: true, estimated_cost: 55000 },
      { code: "D69.59", description: "Other secondary thrombocytopenia", confidence: 0.94, is_primary: false, estimated_cost: 13000 }
    ],
    cpt_codes: [
      { code: "36430", description: "Transfusion, blood or blood components", confidence: 0.91, estimated_cost: 68000 }
    ],
    cost_summary: { icd_total: 68000, cpt_total: 68000, grand_total: 68000 },
    expenses: [
      { category: "Pediatric ICU Room Rent (2 days @ ₹12000)", amount: 24000, source_field: "icu_charges", model_version: "parser-v2" },
      { category: "Pediatric Ward Bed Rent (2 days @ ₹5000)", amount: 10000, source_field: "room_charges", model_version: "parser-v2" },
      { category: "Platelet Concentrate Transfusion charges", amount: 12500, source_field: "blood_transfusion_charges", model_version: "parser-v2" },
      { category: "Pediatrician Daily Care Visits", amount: 8000, source_field: "professional_fees", model_version: "parser-v2" },
      { category: "Diagnostics (Daily Hemograms, Serology)", amount: 9000, source_field: "lab_charges", model_version: "parser-v2" },
      { category: "PPE Kits, Sanitization & Hygiene Chargers (Non-Payable)", amount: 4500, source_field: "non_medical_charges", model_version: "parser-v2" }
    ],
    predictions: [
      {
        rejection_score: 0.35,
        model_name: "ClaimRejectionNet-v3.1",
        top_reasons: [
          { reason: "Billed non-medical consumables (₹4,500) under standard medical lines.", weight: 0.90 }
        ]
      }
    ],
    validations: [
      { rule_id: "non_medical_items_deduction", rule_name: "Non-Medical Items Deduction Check", severity: "WARNING", message: "PPE and administrative hygiene packs billed at ₹4,500 are non-payable under IRDA guidelines. Marked for deduction.", passed: false },
      { rule_id: "clinical_necessity_check", rule_name: "ICU Admission Clinical Justification", severity: "INFO", message: "ICU admission justified by platelet count of 22,000/μL and hemorrhagic symptoms.", passed: true }
    ],
    ocr_excerpt: "KOKILABEN DHIRUBHAI AMBANI HOSPITAL, MUMBAI\nPATIENT: AARAV MEHTA, AGE: 12, GENDER: M\nIP NO: KDA-7718A, POLICY ID: POL-KDA-12109\nDIAGNOSIS: SEVERE DENGUE HEMORRHAGIC FEVER, THROMBOCYTOPENIA\nCLINICAL STATUS: PLATELET COUNT DROP TO 22K (ADM) -> 15K (DAY 2). TRANSFUSED 2 UNITS PLATELETS\nICU ROOM CHARGES: 2 DAYS @ RS. 12,000 = RS. 24,000\nWARD BED CHARGES: 2 DAYS @ RS. 5,000 = RS. 10,000\nPLATELET TRANSFUSION CHARGES: RS. 12,500\nPEDIATRICIAN FEES: RS. 8,000\nLAB DIAGNOSTICS: RS. 9,000\nADMIN FEES & PPE PACK: RS. 4,500\nTOTAL BILL: RS. 68,000\nKOTAK BANK: A/C: 90129841029, IFSC: KKBK0000642",
    brain_insights: [
      "📌 **IRDA Deductibles**: PPE and administrative kits of ₹4,500 are non-payable under IRDA Annexure-I rules. Deductible: **₹4,500**.",
      "✅ **ICU Justification**: Platelet count drop below 50,000 is an approved trigger for ICU admission under severe dengue. No clinical rejection."
    ],
    reimbursement_brain: {
      documents_analyzed: [
        { file_name: "emergency_admission_sheet.pdf", doc_type: "Admission Notes", fields_found: { patient_name: "Aarav Mehta" }, text_length: 620 },
        { file_name: "daily_lab_reports_platelets.pdf", doc_type: "Lab Reports", fields_found: { platelet_count: "15000" }, text_length: 880 }
      ],
      cross_references: [
        { field: "patient_name", sources: [{ doc: "emergency_admission_sheet.pdf", doc_type: "Admission Note", value: "Aarav Mehta" }], status: "MATCHED" }
      ],
      reimbursement_checklist: [
        { item: "Inpatient Lab Reports", status: "YES", reason: "Found serial hemograms showing platelet drop and recovery." },
        { item: "Non-Medical Ledger Separated", status: "YES", reason: "Found non-medical items list of ₹4,500." }
      ],
      insights: [
        { type: "rejection_risk", category: "Non-payable deduction", text: "Deduct ₹4,500 for non-medical items." }
      ],
      completeness_pct: 100
    }
  }
};

// 3. Simulated Client-Side PDF Generation (Minimal standard PDF)
export function generateMockPdf(claimId: string, type: "tpa" | "irda"): Blob {
  const preview = MOCK_PREVIEW_DATA[claimId];
  if (!preview) {
    return new Blob([`%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF`], { type: "application/pdf" });
  }

  const patientName = preview.summary.patient_name;
  const hospital = preview.summary.hospital;
  const diagnosis = preview.summary.diagnosis;
  const billedTotal = preview.summary.total_amount;
  const policyNum = preview.summary.policy_number;

  const title = type === "tpa" ? "ClaimGPT - TPA Audit & Summary Report" : "ClaimGPT - IRDA Standard Form-A Claim Document";

  const streamContent = `BT
/F1 20 Tf
50 740 Td
(${title}) Tj
/F1 12 Tf
0 -40 Td
(Claim ID: ${claimId}) Tj
0 -20 Td
(Patient Name: ${patientName}) Tj
0 -20 Td
(Policy Number: ${policyNum}) Tj
0 -20 Td
(Hospitalization: ${hospital}) Tj
0 -20 Td
(Diagnosis: ${diagnosis}) Tj
0 -20 Td
(Total Billed Amount: INR ${billedTotal}) Tj
0 -40 Td
(AI Audit Assessment:) Tj
0 -20 Td
(Rejection Risk Score: ${Math.round((preview.summary.risk_score || 0) * 100)}%) Tj
0 -20 Td
(Validation Status: ${preview.summary.validation_passed} of ${preview.summary.validation_total} rules passed.) Tj
0 -30 Td
(------------------------------------------------------------------------------------------) Tj
0 -25 Td
(This is an AI-generated report mockup for client-facing product demonstration.) Tj
0 -20 Td
(In live environments, this document contains full GIPSA tariff audits, GCN) Tj
0 -20 Td
(negotiation templates, medical coding, and automated settlement files.) Tj
ET`;

  const pdfBody = `%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>
endobj
4 0 obj
<< /Length ${streamContent.length} >>
stream
${streamContent}
endstream
endobj
5 0 obj
<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>
endobj
xref
0 6
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000115 00000 n 
0000000248 00000 n 
0000000300 00000 n 
trailer
<< /Size 6 /Root 1 0 R >>
startxref
390
%%EOF`;

  return new Blob([pdfBody], { type: "application/pdf" });
}

// 3.5. Dynamic PDF document generator for original uploaded files (Admission, OT notes, Bills, etc.)
export function generateMockDocumentPdf(claimId: string, fileName: string): Blob {
  const preview = MOCK_PREVIEW_DATA[claimId];
  if (!preview) {
    return new Blob([`%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF`], { type: "application/pdf" });
  }

  const patientName = preview.summary.patient_name;
  const hospital = preview.summary.hospital;
  const diagnosis = preview.summary.diagnosis;
  const billedTotal = preview.summary.total_amount;
  const policyNum = preview.summary.policy_number;

  let title = "Document Preview";
  let contentLines: string[] = [];

  const lowerName = fileName.toLowerCase();

  if (lowerName.includes("admission") || lowerName.includes("case_sheet")) {
    title = `${hospital} - Admission Form`;
    contentLines = [
      `Patient Name: ${patientName}    Age / Gender: ${preview.parsed_fields.age || "—"} / ${preview.parsed_fields.gender || "—"}`,
      `Policy Number: ${policyNum}`,
      `Admitting Doctor: ${preview.parsed_fields.doctor_name || "Dr. Duty Medical Officer"}`,
      `Admission Date: ${preview.parsed_fields.admission_date || "—"}`,
      `Chief Complaints: Admitted with clinical symptoms under reference code ${claimId.substring(0, 4).toUpperCase()}.`,
      `Provisional Diagnosis: ${diagnosis}`,
      `Vitals at Admission: BP: 120/80 mmHg, Pulse: 82 bpm, Temp: 98.6 F`,
      `Management Plan: Monitor vitals, initiate IV fluids, schedule standard diagnostic checks.`,
      `Admitting Officer Signature: [Signed Digitally]`
    ];
  } else if (
    lowerName.includes("report") ||
    lowerName.includes("notes") ||
    lowerName.includes("procedure") ||
    lowerName.includes("chemo") ||
    lowerName.includes("angioplasty") ||
    lowerName.includes("arthroplasty")
  ) {
    title = `${hospital} - Clinical & OT Notes`;
    contentLines = [
      `Patient Name: ${patientName}    Policy Number: ${policyNum}`,
      `Date of Procedure: ${preview.parsed_fields.admission_date || "—"}`,
      `Procedure Performed: ${preview.summary.treatment || "Medical Management"}`,
      `Attending Surgeon / Consultant: ${preview.parsed_fields.doctor_name}`,
      `Pre-operative Diagnosis: ${diagnosis}`,
      `Intervention Summary: Patient tolerated the procedure well. Shifted to recovery.`,
      `Implants / Specialized Drugs: Zimmer Joint / Drug Eluting Stents / FOLFOX Chemo as per billing invoice.`,
      `Post-operative Instructions: Check vitals every 2 hours, monitor drainage and output.`,
      `Consultant Surgeon Signature: [Verified Signature]`
    ];
  } else if (lowerName.includes("discharge")) {
    title = `${hospital} - Discharge Summary`;
    contentLines = [
      `Patient Name: ${patientName}    Age: ${preview.parsed_fields.age || "—"}`,
      `Date of Admission: ${preview.parsed_fields.admission_date || "—"}    Date of Discharge: ${preview.parsed_fields.discharge_date || "—"}`,
      `Final Diagnosis: ${diagnosis}`,
      `Clinical Course: Satisfactory recovery. Vitals stable at discharge. Wound clean and dry.`,
      `Condition at Discharge: Active, alert, hemodynamically stable.`,
      `Advice at Discharge & Medications:`,
      `1. Continue primary prescription medications as advised.`,
      `2. Strict follow-up in the outpatient department in 7 days.`,
      `3. Seek emergency care immediately if fever or severe pain develops.`,
      `Attending Doctor: ${preview.parsed_fields.doctor_name}`
    ];
  } else if (lowerName.includes("invoice") || lowerName.includes("bill") || lowerName.includes("breakdown")) {
    title = `${hospital} - Detailed Final Invoice`;
    contentLines = [
      `Invoice ID: INV-2026-${claimId.substring(0, 4).toUpperCase()}    Billing Date: ${preview.parsed_fields.discharge_date || "—"}`,
      `Patient Name: ${patientName}    Policy Number: ${policyNum}`,
      `------------------------------------------------------------------------------------------`,
      `Itemized Bill Breakdown:`,
      ...preview.expenses.map((e) => ` - ${e.category}: INR ${e.amount.toLocaleString("en-IN")}.00`),
      `------------------------------------------------------------------------------------------`,
      `Final Invoice Total Billed: INR ${parseFloat(billedTotal).toLocaleString("en-IN")}.00`,
      `Settlement Route: Paid via Bank account ending in ${preview.parsed_fields.account_number?.substring(Math.max(0, (preview.parsed_fields.account_number?.length || 0) - 4)) || "—"}`,
      `Finance Executive Signature: [Digitally Approved]`
    ];
  } else if (lowerName.includes("sticker")) {
    title = `${hospital} - Zimmer Joint Sticker Dossier`;
    contentLines = [
      `Claim ID: ${claimId}`,
      `Patient Name: ${patientName}`,
      `------------------------------------------------------------------------------------------`,
      `[TPA AUDIT WARNING]`,
      `THIS STICKER PAGE IS BLANK. MANUFACTURER INVOICE BARCODE WAS NOT FOUND IN DOSSIER.`,
      `Under GIPSA/IRDA compliance rules, the physical sticker from the knee joint replacement packaging`,
      `must be scanned and attached here to authorize the joint replacement implant payout of INR 95,000.`,
      `Please contact the Fortis orthopedics department to retrieve the physical serial sticker sheet.`,
      `------------------------------------------------------------------------------------------`
    ];
  } else {
    title = `${hospital} - Medical Document Record`;
    contentLines = [
      `File Name: ${fileName}`,
      `Patient Name: ${patientName}`,
      `Policy Number: ${policyNum}`,
      `Diagnosis: ${diagnosis}`,
      `Document ID: ${claimId.substring(0, 8)}`,
      `This document contains original scanned medical paperwork retrieved from the hospital EHR.`
    ];
  }

  // PDF syntax requires escaping parentheses: ( ) -> \( \)
  const escapePdfText = (t: string) => t.replace(/\(/g, "\\(").replace(/\)/g, "\\)");

  const streamContent = `BT
/F1 18 Tf
50 740 Td
(${escapePdfText(title)}) Tj
/F1 11 Tf
0 -40 Td
(------------------------------------------------------------------------------------------) Tj
${contentLines.map((line) => `0 -22 Td\n(${escapePdfText(line)}) Tj`).join("\n")}
0 -35 Td
(------------------------------------------------------------------------------------------) Tj
0 -20 Td
(This is an offline mock document generated dynamically in the ClaimGPT frontend) Tj
0 -18 Td
(for demonstrating the click-through validation/auditing features.) Tj
ET`;

  const pdfBody = `%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>
endobj
4 0 obj
<< /Length ${streamContent.length} >>
stream
${streamContent}
endstream
endobj
5 0 obj
<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>
endobj
xref
0 6
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000115 00000 n 
0000000248 00000 n 
0000000300 00000 n 
trailer
<< /Size 6 /Root 1 0 R >>
startxref
390
%%EOF`;

  return new Blob([pdfBody], { type: "application/pdf" });
}

// 4. Simulated Interactive Chatbot Responses
export function getMockChatResponse(claimId: string, query: string): string {
  const preview = MOCK_PREVIEW_DATA[claimId];
  if (!preview) return "I could not find the records for this claim. Please verify the claim ID.";

  const q = query.toLowerCase();
  const name = preview.summary.patient_name;
  const hospital = preview.summary.hospital;
  const diagnosis = preview.summary.diagnosis;
  const total = preview.summary.total_amount;

  if (claimId === "00000000-0000-0000-0000-000000000001") {
    // Rajesh Kumar
    if (q.includes("stent") || q.includes("tariff") || q.includes("gipsa") || q.includes("price")) {
      return `For **${name}**'s claim, the hospital billed **INR 1,20,000** for 2 Drug Eluting Stents (₹60,000 each). Under GIPSA/GCN tariff agreement guidelines, the maximum allowable price per stent is capped at **INR 52,000**. \n\nTherefore, we flag **INR 16,000** as a non-payable overcharge, reducing the approved stent amount to **INR 1,04,000**.`;
    }
    if (q.includes("room") || q.includes("rent") || q.includes("icu") || q.includes("cap")) {
      return `The ICU room rent billed is **INR 12,000 per day** for 3 days. Under this policy's terms, the ICU cap is restricted to 2% of the sum insured (Sum Insured is ₹5.00 Lakh, making the cap **INR 10,000 per day**).\n\nThe daily ICU excess is ₹2,000/day. For 3 days, this results in a deduction of **INR 6,000** from the room rent payable.`;
    }
    if (q.includes("why") && q.includes("manual")) {
      return `This claim is flagged for **Manual Review** due to two validation rule failures:\n1. **ICU Room Rent Ceiling Check**: ICU charges exceed the policy cap by ₹2,000/day (Deduction: ₹6,000).\n2. **GIPSA Stent Price Check**: Stent unit cost exceeds tariff agreement limits by ₹8,000 per stent (Deduction: ₹16,000).\n\nI recommend approving **INR 3,63,000** (₹3,85,000 minus ₹22,000 deductions) subject to medical auditor sign-off.`;
    }
  }

  if (claimId === "00000000-0000-0000-0000-000000000002") {
    // Priyadarshini Rao
    if (q.includes("limit") || q.includes("maternity") || q.includes("cap") || q.includes("maximum")) {
      return `For **${name}**, the Caesarean delivery (LSCS) was billed at **INR 1,45,000** at Apollo Cradle. However, the patient's policy schedule defines a strict **maternity sub-limit of INR 50,000** for Caesarean sections.\n\nThe TPA liability is capped at **INR 50,000**, and the balance of **INR 95,000** is non-payable and must be settled by the patient directly.`;
    }
    if (q.includes("copay") || q.includes("co-pay")) {
      return `A **10% co-payment** applies to all eligible maternity claims. Since the eligible limit is capped at ₹50,000, the co-payment calculation is 10% of ₹50,000 = **INR 5,000**. The final net insurance liability will be **INR 45,000**.`;
    }
    if (q.includes("waiting") || q.includes("period")) {
      return `The maternity waiting period rule is **PASSED**. The policy requires a 9-month waiting period for maternity benefits, and this policy has been active for 22 months, satisfying the condition.`;
    }
  }

  if (claimId === "00000000-0000-0000-0000-000000000003") {
    // Amit Shah
    if (q.includes("daycare") || q.includes("24") || q.includes("hospitalization")) {
      return `Yes, **${name}**'s chemotherapy session (FOLFOX protocol) was done in the daycare ward. Daycare chemotherapy is explicitly covered under Section 2.14 of the policy, exempting it from the standard 24-hour hospitalization rule.`;
    }
    if (q.includes("co-pay") || q.includes("deductible")) {
      return `There are **no co-pays or deductibles** applicable for this claim. The patient is under a corporate policy with zero co-pay, and the cancer treatment waiting period is fully satisfied. Billed amount **INR 92,000** is approved in full.`;
    }
  }

  if (claimId === "00000000-0000-0000-0000-000000000004") {
    // Sarla Devi
    if (q.includes("implant") || q.includes("sticker") || q.includes("barcode")) {
      return `For **${name}**'s knee replacement, the Fortis hospital bill lists a Zimmer Knee Joint implant for **INR 95,000**. However, the clinical dossier is **missing the Zimmer implant barcode sticker sheet**.\n\nTPA audit guidelines require the physical sticker sheet with the implant's serial number to prevent duplicate billing. The claim status is 'Manual Review' until the hospital uploads the barcode sheet.`;
    }
    if (q.includes("room") || q.includes("rent") || q.includes("deluxe")) {
      return `The Deluxe Room Rent billed is **INR 6,000 per day** for 4 days (Total ₹24,000). The policy allows a room rent limit up to **INR 8,000 per day** for this sum-insured bracket, so the room rent is approved in full without deductions.`;
    }
  }

  if (claimId === "00000000-0000-0000-0000-000000000005") {
    // Aarav Mehta
    if (q.includes("non-medical") || q.includes("ppe") || q.includes("hygiene") || q.includes("deduct")) {
      return `For **${name}**'s claim, the invoice lists **INR 4,500** for PPE kits, sanitization packs, and admission admin kits. Under IRDA Guidelines Annexure-I, these non-medical items are classified as non-payable consumables.\n\nWe recommend deducting **INR 4,500** from the final payout.`;
    }
    if (q.includes("icu") || q.includes("necessity") || q.includes("platelet")) {
      return `The ICU admission clinical necessity is **PASSED**. Aarav's lab reports show his platelet count dropped from **22,000/μL** at admission to **15,000/μL** on Day 2, causing active bleeding risk (petechiae). This fully justifies emergency pediatric ICU monitoring.`;
    }
  }

  // General fallback
  return `This claim is for **${name}** at **${hospital}** for **${diagnosis}**. The total billed amount is **INR ${parseFloat(total).toLocaleString()}**. Let me know if you would like details on tariff checks, room rent limits, clinical justifications, or non-payable items.`;
}

export function getMockChatSuggestions(claimId: string): string[] {
  if (claimId === "00000000-0000-0000-0000-000000000001") {
    return ["Tell me about GIPSA stent cap check", "Check room rent limits", "Why is it under manual review?"];
  }
  if (claimId === "00000000-0000-0000-0000-000000000002") {
    return ["What is the maternity sub-limit?", "Calculate co-payment", "Verify waiting period"];
  }
  if (claimId === "00000000-0000-0000-0000-000000000003") {
    return ["Is daycare chemotherapy covered?", "Are there any deductions?"];
  }
  if (claimId === "00000000-0000-0000-0000-000000000004") {
    return ["Why is implant barcode required?", "Verify room rent charges"];
  }
  if (claimId === "00000000-0000-0000-0000-000000000005") {
    return ["What are the non-payable deductions?", "Was ICU admission justified?"];
  }
  return ["Explain the audit results", "What is the policy limit?", "Analyze expense items"];
}
