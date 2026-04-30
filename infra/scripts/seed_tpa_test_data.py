"""
Seed 50 diverse test claims for TPA dashboard testing.
Each claim has patient info, hospital, diagnosis, documents, predictions, validations,
bank details, discharge summary — all mandatory fields populated.
Categories: Cardiac, Orthopedic, Oncology, Gastro, Neuro, OB-GYN, Nephro, Pulmo,
            Infectious, Pediatrics, ENT, Ophthalmology, Cosmetic, Urology, Endocrine
"""
import uuid, json, random
from datetime import date, timedelta
from sqlalchemy import create_engine, text

DB_URL = "postgresql://postgres:postgres@localhost:5432/claimgpt"
engine = create_engine(DB_URL)

random.seed(42)  # reproducible data

# ───────────────────── Reference Pools ─────────────────────

MALE_NAMES = [
    "Rajesh Kumar", "Amit Patel", "Mohammed Farhan", "Vikram Joshi", "Arjun Singh",
    "Suresh Reddy", "Rahul Verma", "Anil Sharma", "Karthik Nair", "Devendra Yadav",
    "Sanjay Gupta", "Ravi Pillai", "Ashok Mishra", "Gaurav Tiwari", "Nitin Deshmukh",
    "Rohan Mehta", "Varun Saxena", "Manoj Pandey", "Harish Chauhan", "Ajay Dubey",
    "Naveen Prasad", "Sachin Kulkarni", "Deepak Agarwal", "Vivek Kapoor", "Rajan Menon",
]

FEMALE_NAMES = [
    "Priya Sharma", "Sunita Devi", "Ananya Reddy", "Lakshmi Iyer", "Deepa Menon",
    "Kavita Banerjee", "Pooja Agarwal", "Nandini Rao", "Meera Pillai", "Shalini Jain",
    "Ritu Malhotra", "Anjali Chopra", "Sneha Das", "Divya Kaur", "Swati Bhatia",
    "Rekha Nair", "Padma Sundaram", "Gayatri Hegde", "Bhavana Shetty", "Neha Pandey",
    "Sapna Tripathi", "Geeta Thakur", "Asha Mohan", "Veena Rajan", "Lata Gowda",
]

HOSPITALS = [
    ("Apollo Hospital", "Chennai"), ("Fortis Hospital", "Mumbai"), ("Max Super Speciality", "Delhi"),
    ("Medanta Hospital", "Gurugram"), ("AIIMS", "New Delhi"), ("Manipal Hospital", "Bangalore"),
    ("Narayana Health", "Bangalore"), ("Kokilaben Hospital", "Mumbai"),
    ("Rainbow Children's Hospital", "Hyderabad"), ("Aster CMI Hospital", "Bangalore"),
    ("Lilavati Hospital", "Mumbai"), ("Sir Ganga Ram Hospital", "Delhi"),
    ("Tata Memorial Hospital", "Mumbai"), ("CMC Vellore", "Vellore"),
    ("KIMS Hospital", "Hyderabad"), ("Wockhardt Hospital", "Mumbai"),
    ("BLK Super Speciality Hospital", "Delhi"), ("Jaslok Hospital", "Mumbai"),
    ("Columbia Asia Hospital", "Bangalore"), ("Yashoda Hospital", "Hyderabad"),
    ("Sanjay Gandhi PGIMS", "Lucknow"), ("Amrita Hospital", "Kochi"),
    ("Ruby Hall Clinic", "Pune"), ("Care Hospital", "Hyderabad"),
    ("Artemis Hospital", "Gurugram"),
]

BANKS = [
    ("State Bank of India", "SBIN"), ("HDFC Bank", "HDFC"), ("ICICI Bank", "ICIC"),
    ("Axis Bank", "UTIB"), ("Punjab National Bank", "PUNB"), ("Canara Bank", "CNRB"),
    ("Kotak Mahindra Bank", "KKBK"), ("Bank of Baroda", "BARB"), ("Union Bank of India", "UBIN"),
    ("Indian Bank", "IDIB"), ("Bank of India", "BKID"), ("Central Bank of India", "CBIN"),
    ("Indian Overseas Bank", "IOBA"), ("YES Bank", "YESB"), ("Federal Bank", "FDRL"),
]

BANK_BRANCHES = [
    "Anna Nagar", "Bandra West", "Connaught Place", "Sector 44", "Lajpat Nagar",
    "Indiranagar", "Jayanagar", "Andheri East", "Jubilee Hills", "HSR Layout",
    "MG Road", "T Nagar", "Koramangala", "Malad West", "Rajouri Garden",
    "Salt Lake", "Park Street", "Aundh", "Viman Nagar", "Adyar",
]

DOCTORS = [
    "Dr. S. Venkatesh", "Dr. A. Mehta", "Dr. R. Gupta", "Dr. K. Singh", "Dr. P. Rao",
    "Dr. L. Nair", "Dr. B. Hegde", "Dr. D. Kulkarni", "Dr. M. Rao", "Dr. V. Krishnan",
    "Dr. N. Sharma", "Dr. T. Reddy", "Dr. J. Patel", "Dr. G. Menon", "Dr. H. Srinivasan",
    "Dr. F. Ahmed", "Dr. C. Iyer", "Dr. U. Banerjee", "Dr. W. Das", "Dr. Y. Kaur",
]

STATUSES = [
    "SUBMITTED", "SUBMITTED", "SUBMITTED",
    "APPROVED", "APPROVED",
    "MANUAL_REVIEW_REQUIRED", "MANUAL_REVIEW_REQUIRED",
    "REJECTED",
    "PROCESSING", "PROCESSING",
    "DOCUMENTS_REQUESTED",
    "MODIFICATION_REQUESTED",
    "SETTLED",
]

# ── Categories with diagnosis, ICD, CPT, treatment, discharge summary templates ──
CATEGORIES = [
    {
        "category": "Cardiac",
        "diagnoses": [
            {"name": "Acute Myocardial Infarction", "icd": ("I21.9", "Acute myocardial infarction, unspecified"),
             "cpt": ("92928", "Percutaneous coronary stent placement"),
             "treatment": "Coronary angioplasty with stent placement",
             "history": "Chest pain and shortness of breath for 2 days",
             "discharge": "Successful coronary angioplasty with drug-eluting stent in LAD. Post-op recovery uneventful. Dual antiplatelet therapy initiated.",
             "amount_range": (200000, 800000)},
            {"name": "Mitral Valve Replacement", "icd": ("I05.1", "Rheumatic mitral insufficiency"),
             "cpt": ("33430", "Mitral valve replacement"),
             "treatment": "Open heart mitral valve replacement with mechanical prosthesis",
             "history": "Progressive dyspnea on exertion, orthopnea for 3 months",
             "discharge": "MVR done under CPB. Mechanical valve placed. INR target 2.5-3.5. On warfarin and diuretics. Follow-up echo in 6 weeks.",
             "amount_range": (500000, 1200000)},
            {"name": "Atrial Fibrillation Ablation", "icd": ("I48.91", "Unspecified atrial fibrillation"),
             "cpt": ("93656", "Catheter ablation of atrial fibrillation"),
             "treatment": "Radiofrequency catheter ablation for persistent AF",
             "history": "Palpitations and irregular heartbeat for 1 year, refractory to medication",
             "discharge": "Pulmonary vein isolation performed. Sinus rhythm restored. Continue anticoagulation for 3 months.",
             "amount_range": (300000, 600000)},
        ],
    },
    {
        "category": "Orthopedic",
        "diagnoses": [
            {"name": "Bilateral Knee Replacement", "icd": ("M17.0", "Primary osteoarthritis, bilateral knees"),
             "cpt": ("27447", "Total knee arthroplasty"),
             "treatment": "Total bilateral knee arthroplasty",
             "history": "Severe osteoarthritis, wheelchair-bound for 1 year",
             "discharge": "Bilateral TKR under spinal anaesthesia. Physiotherapy Day 1. Ambulating with walker. Pain management protocol started.",
             "amount_range": (400000, 900000)},
            {"name": "Hip Fracture Repair", "icd": ("S72.001A", "Fracture of unspecified part of neck of femur"),
             "cpt": ("27236", "Open reduction internal fixation, femoral neck"),
             "treatment": "ORIF with dynamic hip screw",
             "history": "Fall from height, unable to bear weight on right leg",
             "discharge": "ORIF with DHS completed. Non-weight bearing for 6 weeks. DVT prophylaxis given. Physiotherapy plan initiated.",
             "amount_range": (200000, 500000)},
            {"name": "Lumbar Disc Herniation", "icd": ("M51.16", "Lumbar disc herniation with radiculopathy"),
             "cpt": ("63030", "Lumbar microdiscectomy"),
             "treatment": "Lumbar microdiscectomy",
             "history": "Chronic lower back pain with left leg radiculopathy",
             "discharge": "L4-L5 microdiscectomy performed. Post-op neuro exam normal. Pain significantly reduced. Bed rest 2 weeks, then physiotherapy.",
             "amount_range": (200000, 450000)},
            {"name": "ACL Reconstruction", "icd": ("S83.511A", "Sprain of anterior cruciate ligament"),
             "cpt": ("29888", "Arthroscopic ACL reconstruction"),
             "treatment": "Arthroscopic ACL reconstruction with hamstring autograft",
             "history": "Sports injury during cricket match, knee instability and swelling",
             "discharge": "ACL reconstruction done arthroscopically. Graft fixation secure. Knee brace applied. Weight bearing as tolerated. Rehab protocol started.",
             "amount_range": (150000, 350000)},
        ],
    },
    {
        "category": "Oncology",
        "diagnoses": [
            {"name": "Breast Cancer Stage IIA", "icd": ("C50.919", "Malignant neoplasm of breast"),
             "cpt": ("19307", "Modified radical mastectomy"),
             "treatment": "Modified radical mastectomy + chemotherapy cycle 1",
             "history": "Lump detected during screening, biopsy confirmed malignancy",
             "discharge": "MRM with axillary clearance. IDC Grade II, ER+/PR+/HER2-. First AC chemo tolerated well. Port-a-cath in situ.",
             "amount_range": (500000, 1500000)},
            {"name": "Colon Cancer — Hemicolectomy", "icd": ("C18.9", "Malignant neoplasm of colon, unspecified"),
             "cpt": ("44204", "Laparoscopic partial colectomy"),
             "treatment": "Laparoscopic right hemicolectomy",
             "history": "Altered bowel habits, weight loss, colonoscopy showing cecal mass",
             "discharge": "Lap right hemicolectomy done. Histopath: adenocarcinoma T3N1. Stoma not required. Tolerating diet. Oncology follow-up for adjuvant chemo.",
             "amount_range": (400000, 900000)},
            {"name": "Lung Cancer — Lobectomy", "icd": ("C34.90", "Malignant neoplasm of lung, unspecified"),
             "cpt": ("32663", "Thoracoscopic lobectomy"),
             "treatment": "VATS right upper lobectomy",
             "history": "Persistent cough, hemoptysis, CT showing right upper lobe mass",
             "discharge": "VATS RUL lobectomy completed. Chest drain removed Day 3. Histopath: squamous cell carcinoma Stage IIB. Referred for adjuvant RT.",
             "amount_range": (600000, 1200000)},
        ],
    },
    {
        "category": "Gastroenterology",
        "diagnoses": [
            {"name": "Laparoscopic Cholecystectomy", "icd": ("K80.20", "Calculus of gallbladder without obstruction"),
             "cpt": ("47562", "Laparoscopic cholecystectomy"),
             "treatment": "Laparoscopic removal of gallbladder",
             "history": "Recurrent right upper quadrant pain for 6 months",
             "discharge": "Uneventful lap cholecystectomy. Chronic cholecystitis on histopath. Oral diet tolerated. Wound clean.",
             "amount_range": (100000, 250000)},
            {"name": "Acute Pancreatitis", "icd": ("K85.90", "Acute pancreatitis, unspecified"),
             "cpt": ("48000", "Drainage of pancreatic cyst"),
             "treatment": "Conservative management with IV fluids, analgesics, and NPO",
             "history": "Severe epigastric pain radiating to back after alcohol binge",
             "discharge": "Acute pancreatitis managed conservatively. Amylase/lipase normalized. Tolerating low-fat diet. Alcohol abstinence counselled.",
             "amount_range": (80000, 200000)},
            {"name": "GERD — Fundoplication", "icd": ("K21.0", "Gastro-esophageal reflux with esophagitis"),
             "cpt": ("43280", "Laparoscopic fundoplication"),
             "treatment": "Laparoscopic Nissen fundoplication",
             "history": "Refractory GERD despite PPI therapy for 2 years, Barrett's changes on endoscopy",
             "discharge": "Lap Nissen fundoplication done. Soft diet for 4 weeks. Symptom free at discharge. Follow-up endoscopy in 3 months.",
             "amount_range": (150000, 350000)},
        ],
    },
    {
        "category": "Neurology",
        "diagnoses": [
            {"name": "Cerebral Stroke — Thrombolysis", "icd": ("I63.9", "Cerebral infarction, unspecified"),
             "cpt": ("37195", "Thrombolysis, cerebral"),
             "treatment": "IV thrombolysis with alteplase, neuro-ICU monitoring",
             "history": "Sudden onset right-sided weakness and slurred speech",
             "discharge": "IV tPA administered within window. MRS score improved from 4 to 2. Swallowing assessment cleared. Anticoagulation and rehab initiated.",
             "amount_range": (300000, 800000)},
            {"name": "Brain Tumor — Craniotomy", "icd": ("D33.0", "Benign neoplasm of brain, supratentorial"),
             "cpt": ("61510", "Craniotomy for excision of brain tumor"),
             "treatment": "Right fronto-parietal craniotomy and tumor excision",
             "history": "Progressive headaches, seizures, MRI showing 4cm right frontal meningioma",
             "discharge": "Gross total excision of meningioma achieved. No post-op neuro deficits. Anti-epileptic therapy continued. MRI at 3 months.",
             "amount_range": (500000, 1000000)},
            {"name": "Epilepsy Management", "icd": ("G40.909", "Epilepsy, unspecified, not intractable"),
             "cpt": ("95816", "EEG with sleep"),
             "treatment": "Anti-epileptic drug optimization, video EEG monitoring",
             "history": "Recurrent generalized tonic-clonic seizures despite medication",
             "discharge": "Video EEG confirmed generalized epilepsy. Levetiracetam dose optimized. Seizure-free 72 hours at discharge. Driving restriction advised.",
             "amount_range": (60000, 180000)},
        ],
    },
    {
        "category": "Obstetrics & Gynecology",
        "diagnoses": [
            {"name": "Cesarean Section Delivery", "icd": ("O82", "Encounter for cesarean delivery"),
             "cpt": ("59510", "Cesarean delivery"),
             "treatment": "Emergency cesarean section",
             "history": "Full-term pregnancy, fetal distress detected during labor",
             "discharge": "Emergency LSCS for fetal distress. Healthy baby delivered. Mother and baby stable. Breastfeeding initiated.",
             "amount_range": (120000, 300000)},
            {"name": "Hysterectomy — Fibroid Uterus", "icd": ("D25.9", "Leiomyoma of uterus, unspecified"),
             "cpt": ("58571", "Laparoscopic total hysterectomy"),
             "treatment": "Laparoscopic total hysterectomy",
             "history": "Heavy menstrual bleeding, large uterine fibroids on ultrasound",
             "discharge": "Lap TLH completed. Multiple leiomyomas, largest 8cm. Minimal blood loss. Ambulating well. Follow-up in 2 weeks.",
             "amount_range": (200000, 400000)},
            {"name": "Ectopic Pregnancy", "icd": ("O00.10", "Tubal pregnancy"),
             "cpt": ("59151", "Laparoscopic salpingectomy for ectopic"),
             "treatment": "Laparoscopic salpingectomy",
             "history": "Missed period, acute abdominal pain, positive pregnancy test, ultrasound showing adnexal mass",
             "discharge": "Lap left salpingectomy for ruptured ectopic. 500ml hemoperitoneum drained. Hemodynamically stable post-op. Beta-hCG trending down.",
             "amount_range": (100000, 250000)},
        ],
    },
    {
        "category": "Nephrology",
        "diagnoses": [
            {"name": "Diabetic Nephropathy — Dialysis", "icd": ("E11.22", "Type 2 diabetes with nephropathy"),
             "cpt": ("90935", "Hemodialysis procedure"),
             "treatment": "Dialysis sessions and insulin therapy optimization",
             "history": "Uncontrolled diabetes for 15 years, rising creatinine levels",
             "discharge": "3 sessions of hemodialysis completed. Creatinine reduced from 8.2 to 4.1. Insulin regimen optimized. AV fistula planning referred.",
             "amount_range": (150000, 500000)},
            {"name": "Kidney Stone — Lithotripsy", "icd": ("N20.0", "Calculus of kidney"),
             "cpt": ("50590", "Lithotripsy, extracorporeal shock wave"),
             "treatment": "ESWL for right renal calculus",
             "history": "Severe right flank pain with hematuria, CT KUB showing 12mm right renal stone",
             "discharge": "ESWL administered — stone fragmented. DJ stent placed. Adequate hydration advised. Stent removal in 4 weeks.",
             "amount_range": (60000, 180000)},
        ],
    },
    {
        "category": "Pulmonology",
        "diagnoses": [
            {"name": "Pneumonia — Severe", "icd": ("J18.9", "Pneumonia, unspecified organism"),
             "cpt": ("94003", "Ventilator management"),
             "treatment": "IV antibiotics, oxygen therapy, respiratory support",
             "history": "High-grade fever with productive cough and breathlessness for 5 days",
             "discharge": "CAP managed with IV piperacillin-tazobactam. Oxygen weaned off Day 4. CXR improving. Switched to oral antibiotics.",
             "amount_range": (80000, 250000)},
            {"name": "Asthma Exacerbation", "icd": ("J45.41", "Moderate persistent asthma with acute exacerbation"),
             "cpt": ("94640", "Nebulizer treatment"),
             "treatment": "Nebulization, IV steroids, oxygen therapy",
             "history": "Known asthmatic, severe wheezing and respiratory distress after dust exposure",
             "discharge": "Acute exacerbation managed with nebulized bronchodilators and IV methylprednisolone. Peak flow improved to 80%. Step-up therapy initiated.",
             "amount_range": (40000, 120000)},
            {"name": "COPD Exacerbation", "icd": ("J44.1", "COPD with acute exacerbation"),
             "cpt": ("94660", "CPAP ventilation"),
             "treatment": "BiPAP, IV steroids, antibiotics, bronchodilators",
             "history": "Long-standing smoker with progressive dyspnea, acute worsening with purulent sputum",
             "discharge": "COPD exacerbation managed with NIV, steroids and antibiotics. ABG normalized. Smoking cessation counselled. Pulmonary rehab referral.",
             "amount_range": (80000, 200000)},
        ],
    },
    {
        "category": "Infectious Disease",
        "diagnoses": [
            {"name": "Dengue Hemorrhagic Fever", "icd": ("A91", "Dengue hemorrhagic fever"),
             "cpt": ("36430", "Transfusion of blood components"),
             "treatment": "IV fluids, platelet transfusion, monitoring",
             "history": "High fever, body ache, low platelet count for 4 days",
             "discharge": "Dengue with thrombocytopenia managed with IV fluids and platelet transfusion. Platelet count recovered to 1.2L. Afebrile 48 hours.",
             "amount_range": (50000, 150000)},
            {"name": "Typhoid Fever", "icd": ("A01.00", "Typhoid fever, unspecified"),
             "cpt": ("87040", "Blood culture"),
             "treatment": "IV ceftriaxone, supportive care",
             "history": "Step-ladder fever for 10 days, positive Widal test",
             "discharge": "Enteric fever confirmed on blood culture. IV ceftriaxone 14 days completed. Afebrile, tolerating diet. Stool culture negative.",
             "amount_range": (30000, 90000)},
            {"name": "Malaria — Complicated", "icd": ("B50.9", "Plasmodium falciparum malaria, unspecified"),
             "cpt": ("87207", "Smear for parasites"),
             "treatment": "IV artesunate, supportive care, monitoring for complications",
             "history": "High-grade fever with chills and rigors, travel to endemic area",
             "discharge": "Severe falciparum malaria treated with IV artesunate. Parasitemia cleared. No organ dysfunction. Switched to oral ACT.",
             "amount_range": (40000, 130000)},
        ],
    },
    {
        "category": "Pediatrics",
        "diagnoses": [
            {"name": "Acute Appendicitis", "icd": ("K35.80", "Acute appendicitis, unspecified"),
             "cpt": ("44970", "Laparoscopic appendectomy"),
             "treatment": "Laparoscopic appendectomy",
             "history": "Sudden severe abdominal pain, vomiting, fever",
             "discharge": "Emergency lap appendectomy. Histopath: acute suppurative appendicitis. Recovery smooth. Tolerating feeds.",
             "amount_range": (80000, 200000)},
            {"name": "Kawasaki Disease", "icd": ("M30.3", "Mucocutaneous lymph node syndrome"),
             "cpt": ("93306", "Echocardiography"),
             "treatment": "IVIG infusion and high-dose aspirin",
             "history": "Persistent fever >5 days, rash, conjunctivitis, strawberry tongue in child",
             "discharge": "Kawasaki disease treated with IVIG — fever resolved 24 hours. Echo: no coronary aneurysm. Low-dose aspirin for 6 weeks.",
             "amount_range": (100000, 300000)},
        ],
    },
    {
        "category": "ENT",
        "diagnoses": [
            {"name": "Tonsillectomy", "icd": ("J35.01", "Chronic tonsillitis"),
             "cpt": ("42826", "Tonsillectomy"),
             "treatment": "Bilateral tonsillectomy under general anesthesia",
             "history": "Recurrent tonsillitis 6+ episodes/year, obstructive symptoms",
             "discharge": "Bilateral tonsillectomy done. Hemostasis achieved. Soft diet 2 weeks. Analgesics prescribed. Follow-up in 10 days.",
             "amount_range": (40000, 100000)},
            {"name": "Septoplasty", "icd": ("J34.2", "Deviated nasal septum"),
             "cpt": ("30520", "Septoplasty"),
             "treatment": "Septoplasty for deviated nasal septum",
             "history": "Chronic nasal obstruction and recurrent sinusitis for 2 years",
             "discharge": "Septoplasty performed. Nasal packing removed after 48 hours. Breathing improved. Nasal douching advised. Review in 1 week.",
             "amount_range": (50000, 150000)},
        ],
    },
    {
        "category": "Ophthalmology",
        "diagnoses": [
            {"name": "Cataract Surgery — Phaco", "icd": ("H25.9", "Senile cataract, unspecified"),
             "cpt": ("66984", "Phacoemulsification with IOL"),
             "treatment": "Phacoemulsification with posterior chamber IOL implantation",
             "history": "Progressive bilateral visual deterioration over 2 years",
             "discharge": "Uneventful phaco + PCIOL right eye. VA improved to 6/9. Topical steroids and antibiotics prescribed. Left eye in 6 weeks.",
             "amount_range": (30000, 80000)},
            {"name": "Retinal Detachment Repair", "icd": ("H33.001", "Retinal detachment with retinal break"),
             "cpt": ("67108", "Vitrectomy for retinal detachment"),
             "treatment": "Pars plana vitrectomy with silicone oil tamponade",
             "history": "Sudden floaters and curtain-like vision loss in left eye",
             "discharge": "PPV with silicone oil done for RRD. Retina attached on table. Prone positioning 2 weeks. Oil removal in 3 months.",
             "amount_range": (100000, 300000)},
        ],
    },
    {
        "category": "Cosmetic / Excluded",
        "diagnoses": [
            {"name": "Cosmetic Rhinoplasty", "icd": ("Z41.1", "Encounter for cosmetic surgery"),
             "cpt": ("30400", "Rhinoplasty, primary"),
             "treatment": "Rhinoplasty (nose reshaping)",
             "history": "Elective cosmetic surgery request",
             "discharge": "Elective rhinoplasty under GA. No complications. Nasal packing removed. Cosmetic procedure — not medically indicated.",
             "amount_range": (150000, 400000)},
            {"name": "Liposuction — Cosmetic", "icd": ("Z41.1", "Encounter for cosmetic surgery"),
             "cpt": ("15877", "Suction assisted lipectomy"),
             "treatment": "Liposuction of abdomen and flanks",
             "history": "Elective body contouring request, no medical indication",
             "discharge": "Liposuction of abdomen and flanks performed. Compression garment applied. Cosmetic procedure — no medical necessity.",
             "amount_range": (200000, 500000)},
        ],
    },
    {
        "category": "Urology",
        "diagnoses": [
            {"name": "TURP — Benign Prostatic Hyperplasia", "icd": ("N40.1", "BPH with lower urinary tract symptoms"),
             "cpt": ("52601", "TURP"),
             "treatment": "Transurethral resection of prostate",
             "history": "Progressive difficulty in urination, nocturia, poor stream for 1 year",
             "discharge": "TURP performed. Catheter removed Day 3. Voiding well with good stream. Histopath: BPH, no malignancy.",
             "amount_range": (100000, 250000)},
        ],
    },
    {
        "category": "Endocrinology",
        "diagnoses": [
            {"name": "Diabetic Ketoacidosis", "icd": ("E11.10", "Type 2 diabetes with ketoacidosis"),
             "cpt": ("99291", "Critical care, first hour"),
             "treatment": "Insulin infusion, IV fluids, electrolyte correction",
             "history": "Known diabetic with vomiting, altered sensorium, blood sugar >500 mg/dL",
             "discharge": "DKA resolved with insulin drip and IV fluids. Anion gap closed. Transitioned to SC insulin. Diabetes education provided.",
             "amount_range": (60000, 180000)},
            {"name": "Thyroidectomy — Goiter", "icd": ("E04.9", "Nontoxic goiter, unspecified"),
             "cpt": ("60240", "Thyroidectomy"),
             "treatment": "Total thyroidectomy for multinodular goiter",
             "history": "Visible neck swelling 2 years, compressive symptoms, FNAC suggestive of follicular neoplasm",
             "discharge": "Total thyroidectomy done. No RLN palsy, calcium stable. Histopath: multinodular goiter with follicular adenoma. Thyroxine started.",
             "amount_range": (150000, 350000)},
        ],
    },
]

DOC_TEMPLATES = [
    [("discharge_summary.pdf", "application/pdf"), ("blood_test_results.pdf", "application/pdf")],
    [("admission_form.pdf", "application/pdf"), ("surgical_report.pdf", "application/pdf")],
    [("pre_authorization.pdf", "application/pdf"), ("xray_reports.pdf", "application/pdf"), ("mri_scan.pdf", "application/pdf")],
    [("claim_form.pdf", "application/pdf"), ("doctor_referral.pdf", "application/pdf")],
    [("blood_reports.pdf", "application/pdf"), ("discharge_summary.pdf", "application/pdf"), ("pharmacy_bills.pdf", "application/pdf")],
    [("lab_reports.pdf", "application/pdf"), ("consultation_notes.pdf", "application/pdf"), ("hospital_bills.pdf", "application/pdf")],
    [("operative_notes.pdf", "application/pdf"), ("pathology_report.pdf", "application/pdf")],
    [("insurance_claim_form.pdf", "application/pdf"), ("investigation_reports.pdf", "application/pdf"), ("prescription.pdf", "application/pdf")],
    [("ecg_report.pdf", "application/pdf"), ("echo_report.pdf", "application/pdf"), ("angiography_cd.pdf", "application/pdf"), ("discharge_summary.pdf", "application/pdf")],
    [("ct_scan_report.pdf", "application/pdf"), ("biopsy_report.pdf", "application/pdf"), ("pet_scan_report.pdf", "application/pdf"), ("chemo_protocol.pdf", "application/pdf"), ("insurance_pre_auth.pdf", "application/pdf")],
]


# ── Generate 50 claims ──
def generate_claims(n=50):
    claims = []
    all_diagnoses = []
    for cat in CATEGORIES:
        for dx in cat["diagnoses"]:
            all_diagnoses.append({**dx, "category": cat["category"]})

    for i in range(1, n + 1):
        gender = random.choice(["Male", "Female"])
        name = random.choice(MALE_NAMES) if gender == "Male" else random.choice(FEMALE_NAMES)
        age = str(random.randint(3, 78))
        hospital_name, hospital_city = random.choice(HOSPITALS)
        hospital = f"{hospital_name}, {hospital_city}"
        bank_name, bank_prefix = random.choice(BANKS)
        branch = f"{random.choice(BANK_BRANCHES)}, {hospital_city}"
        doctor = random.choice(DOCTORS)
        status = random.choice(STATUSES)
        dx = random.choice(all_diagnoses)

        # Pediatrics → young age
        if dx["category"] == "Pediatrics":
            age = str(random.randint(2, 14))
        # OB-GYN → female only
        if dx["category"] == "Obstetrics & Gynecology":
            gender = "Female"
            name = random.choice(FEMALE_NAMES)
            age = str(random.randint(22, 40))

        # Date ranges
        adm_offset = random.randint(10, 90)
        los = random.randint(1, 21)
        adm_date = date(2026, 4, 28) - timedelta(days=adm_offset)
        dis_date = adm_date + timedelta(days=los)

        amount = random.randint(dx["amount_range"][0] // 1000, dx["amount_range"][1] // 1000) * 1000
        rejection_score = round(random.uniform(0.03, 0.95), 2)
        # cosmetic always high rejection
        if dx["category"] == "Cosmetic / Excluded":
            rejection_score = round(random.uniform(0.80, 0.98), 2)
            status = random.choice(["REJECTED", "MANUAL_REVIEW_REQUIRED"])

        acct_num = "".join([str(random.randint(0, 9)) for _ in range(10)])
        ifsc = f"{bank_prefix}0{random.randint(100000, 999999)}"

        top_reasons = []
        if rejection_score > 0.5:
            top_reasons = [
                {"reason": "High claim amount exceeds threshold", "weight": round(random.uniform(0.2, 0.5), 2)},
                {"reason": "Pre-existing condition flagged", "weight": round(random.uniform(0.1, 0.3), 2)},
            ]
        elif rejection_score > 0.3:
            top_reasons = [
                {"reason": "Documentation incomplete", "weight": round(random.uniform(0.2, 0.4), 2)},
            ]
        else:
            top_reasons = [
                {"reason": "Standard procedure, well-documented", "weight": round(random.uniform(0.4, 0.6), 2)},
            ]

        claims.append({
            "id": f"d{i:07d}-aaaa-4000-b000-{uuid.uuid4().hex[:12]}",
            "policy_id": f"POL-IN-{random.randint(10000, 99999)}",
            "patient_id": f"PAT-{i:03d}",
            "status": status,
            "patient_name": name,
            "age": age,
            "gender": gender,
            "hospital": hospital,
            "diagnosis": dx["name"],
            "category": dx["category"],
            "doctor": doctor,
            "admission_date": adm_date.isoformat(),
            "discharge_date": dis_date.isoformat(),
            "treatment": dx["treatment"],
            "history": dx["history"],
            "discharge_summary": dx["discharge"],
            "bank_name": bank_name,
            "bank_branch": branch,
            "account_holder": name,
            "account_number": acct_num,
            "ifsc_code": ifsc,
            "amount": amount,
            "rejection_score": rejection_score,
            "top_reasons": top_reasons,
            "icd": [dx["icd"]],
            "cpt": [dx["cpt"]],
            "docs": random.choice(DOC_TEMPLATES),
        })
    return claims


CLAIMS = generate_claims(100)


def seed():
    with engine.begin() as conn:
        for c in CLAIMS:
            cid = c["id"]

            # 1) Upsert claim
            conn.execute(
                text("""
                    INSERT INTO claims (id, policy_id, patient_id, status, source)
                    VALUES (:id, :policy_id, :patient_id, :status, 'PATIENT')
                    ON CONFLICT (id) DO UPDATE SET
                        status = EXCLUDED.status,
                        policy_id = EXCLUDED.policy_id,
                        patient_id = EXCLUDED.patient_id
                """),
                {"id": cid, "policy_id": c["policy_id"], "patient_id": c["patient_id"], "status": c["status"]},
            )

            # 2) Documents
            for i, (fname, ftype) in enumerate(c["docs"]):
                did = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{cid}-doc-{i}"))
                conn.execute(
                    text("""
                        INSERT INTO documents (id, claim_id, file_name, file_type, minio_path)
                        VALUES (:id, :claim_id, :file_name, :file_type, :minio_path)
                        ON CONFLICT (id) DO NOTHING
                    """),
                    {
                        "id": did,
                        "claim_id": cid,
                        "file_name": fname,
                        "file_type": ftype,
                        "minio_path": f"/storage/raw/{cid}/{fname}",
                    },
                )

            # 3) Parsed fields — ALL mandatory fields populated
            fields = {
                "patient_name": c["patient_name"],
                "age": c["age"],
                "gender": c["gender"],
                "hospital": c["hospital"],
                "hospital_name": c["hospital"],
                "diagnosis": c["diagnosis"],
                "category": c["category"],
                "doctor": c["doctor"],
                "doctor_name": c["doctor"],
                "admission_date": c["admission_date"],
                "discharge_date": c["discharge_date"],
                "treatment": c["treatment"],
                "history_of_present_illness": c["history"],
                "discharge_summary": c["discharge_summary"],
                "total_amount": str(c["amount"]),
                "policy_number": c["policy_id"],
                "bank_name": c["bank_name"],
                "bank_branch": c["bank_branch"],
                "account_holder": c["account_holder"],
                "account_number": c["account_number"],
                "ifsc_code": c["ifsc_code"],
                "ifsc": c["ifsc_code"],
            }
            conn.execute(text("DELETE FROM parsed_fields WHERE claim_id = :cid"), {"cid": cid})
            for fname, fval in fields.items():
                conn.execute(
                    text("""
                        INSERT INTO parsed_fields (claim_id, field_name, field_value)
                        VALUES (:claim_id, :field_name, :field_value)
                    """),
                    {"claim_id": cid, "field_name": fname, "field_value": fval},
                )

            # 4) Prediction
            conn.execute(text("DELETE FROM predictions WHERE claim_id = :cid"), {"cid": cid})
            conn.execute(
                text("""
                    INSERT INTO predictions (claim_id, rejection_score, top_reasons, model_name, model_version)
                    VALUES (:claim_id, :rejection_score, :top_reasons, 'xgb_rejection', 'v2.1')
                """),
                {
                    "claim_id": cid,
                    "rejection_score": c["rejection_score"],
                    "top_reasons": json.dumps(c["top_reasons"]),
                },
            )

            # 5) Medical codes
            conn.execute(text("DELETE FROM medical_codes WHERE claim_id = :cid"), {"cid": cid})
            for code, desc in c["icd"]:
                conn.execute(
                    text("""
                        INSERT INTO medical_codes (claim_id, code, code_system, description, confidence, is_primary)
                        VALUES (:claim_id, :code, 'ICD10', :description, 0.92, true)
                    """),
                    {"claim_id": cid, "code": code, "description": desc},
                )
            for code, desc in c["cpt"]:
                conn.execute(
                    text("""
                        INSERT INTO medical_codes (claim_id, code, code_system, description, confidence, is_primary)
                        VALUES (:claim_id, :code, 'CPT', :description, 0.88, false)
                    """),
                    {"claim_id": cid, "code": code, "description": desc},
                )

            # 6) Validations
            conn.execute(text("DELETE FROM validations WHERE claim_id = :cid"), {"cid": cid})
            validations = [
                ("policy_active", "Policy Active Check", "INFO", "Policy is active and within coverage period", True),
                ("doc_completeness", "Document Completeness", "WARN" if len(c["docs"]) < 3 else "INFO",
                 f"{len(c['docs'])} document(s) attached" + (" - consider uploading more" if len(c["docs"]) < 3 else " - sufficient"),
                 len(c["docs"]) >= 2),
                ("amount_threshold", "Amount Threshold Check", "ERROR" if c["amount"] > 500000 else "INFO",
                 f"Claim amount ₹{c['amount']:,}" + (" exceeds auto-approval threshold" if c["amount"] > 500000 else " within normal range"),
                 c["amount"] <= 500000),
                ("bank_details", "Bank Details Verification", "INFO",
                 f"Bank: {c['bank_name']}, IFSC: {c['ifsc_code']}", True),
                ("discharge_summary", "Discharge Summary Check", "INFO",
                 "Discharge summary provided", True),
                ("hospital_verification", "Hospital Verification", "INFO",
                 f"Hospital: {c['hospital']} — NABH accredited", True),
            ]
            for rule_id, rule_name, severity, message, passed in validations:
                conn.execute(
                    text("""
                        INSERT INTO validations (claim_id, rule_id, rule_name, severity, message, passed)
                        VALUES (:claim_id, :rule_id, :rule_name, :severity, :message, :passed)
                    """),
                    {"claim_id": cid, "rule_id": rule_id, "rule_name": rule_name,
                     "severity": severity, "message": message, "passed": passed},
                )

            cat_label = f"[{c['category']:22s}]"
            print(f"  ✓ {c['patient_name']:20s} | {c['status']:25s} | ₹{c['amount']:>10,} | {len(c['docs'])} docs | {cat_label} {c['hospital']}")

    # Summary
    from collections import Counter
    cats = Counter(c["category"] for c in CLAIMS)
    statuses = Counter(c["status"] for c in CLAIMS)
    print(f"\n✅ Seeded {len(CLAIMS)} claims with documents, parsed fields, predictions, codes & validations.")
    print(f"\n📊 By Category:")
    for cat, count in sorted(cats.items(), key=lambda x: -x[1]):
        print(f"   {cat:24s} → {count}")
    print(f"\n📊 By Status:")
    for s, count in sorted(statuses.items(), key=lambda x: -x[1]):
        print(f"   {s:25s} → {count}")


if __name__ == "__main__":
    print("Seeding 100 TPA test claims...\n")
    seed()
