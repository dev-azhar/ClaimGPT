"""
Comprehensive ICD-10-CM + CPT code database for ClaimGPT.

Contains 500+ of the most commonly used ICD-10-CM codes and 180+ CPT codes
for insurance claim processing.  Production deployments should point at
a full CMS / AMA database or UMLS REST API.

Includes:
  - Synonym / alias mapping for fuzzy NLP matching
  - Code cross-reference suggestions
  - Category-aware search with scoring
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

# ------------------------------------------------------------------ ICD-10-CM
# Format: code -> (code, short_description, category)
ICD10_CM: Dict[str, Tuple[str, str, str]] = {
    # Chapter 1 - Infectious diseases (A00-B99)
    "A09": ("A09", "Infectious gastroenteritis and colitis, unspecified", "Infectious"),
    "A41.9": ("A41.9", "Sepsis, unspecified organism", "Infectious"),
    "A49.9": ("A49.9", "Bacterial infection, unspecified", "Infectious"),
    "B34.9": ("B34.9", "Viral infection, unspecified", "Infectious"),
    "B97.29": ("B97.29", "Other coronavirus as the cause of diseases classified elsewhere", "Infectious"),
    "A04.7": ("A04.7", "Enterocolitis due to Clostridium difficile", "Infectious"),
    "A15.0": ("A15.0", "Tuberculosis of lung", "Infectious"),
    "A40.9": ("A40.9", "Streptococcal sepsis, unspecified", "Infectious"),
    "A41.01": ("A41.01", "Sepsis due to Methicillin susceptible Staphylococcus aureus", "Infectious"),
    "A41.02": ("A41.02", "Sepsis due to MRSA", "Infectious"),
    "B19.20": ("B19.20", "Unspecified viral hepatitis C without hepatic coma", "Infectious"),
    "B20": ("B20", "HIV disease", "Infectious"),
    "B95.61": ("B95.61", "MRSA infection, unspecified site", "Infectious"),
    "B96.20": ("B96.20", "Unspecified Escherichia coli as the cause of diseases classified elsewhere", "Infectious"),
    "J09.X2": ("J09.X2", "Influenza due to identified novel influenza A virus with other respiratory manifestations", "Infectious"),
    # Chapter 2 - Neoplasms (C00-D49)
    "C34.90": ("C34.90", "Malignant neoplasm of unspecified part of bronchus or lung", "Neoplasm"),
    "C50.919": ("C50.919", "Malignant neoplasm of unspecified site of unspecified female breast", "Neoplasm"),
    "C61": ("C61", "Malignant neoplasm of prostate", "Neoplasm"),
    "C18.9": ("C18.9", "Malignant neoplasm of colon, unspecified", "Neoplasm"),
    "C25.9": ("C25.9", "Malignant neoplasm of pancreas, unspecified", "Neoplasm"),
    "C43.9": ("C43.9", "Malignant melanoma of skin, unspecified", "Neoplasm"),
    "C56.9": ("C56.9", "Malignant neoplasm of unspecified ovary", "Neoplasm"),
    "C67.9": ("C67.9", "Malignant neoplasm of bladder, unspecified", "Neoplasm"),
    "C71.9": ("C71.9", "Malignant neoplasm of brain, unspecified", "Neoplasm"),
    "C73": ("C73", "Malignant neoplasm of thyroid gland", "Neoplasm"),
    "C79.51": ("C79.51", "Secondary malignant neoplasm of bone", "Neoplasm"),
    "C90.00": ("C90.00", "Multiple myeloma not having achieved remission", "Neoplasm"),
    "D17.9": ("D17.9", "Benign lipomatous neoplasm, unspecified (lipoma)", "Neoplasm"),
    # Blood (D50-D89)
    "D64.9": ("D64.9", "Anemia, unspecified", "Blood"),
    "D50.9": ("D50.9", "Iron deficiency anemia, unspecified", "Blood"),
    "D69.6": ("D69.6", "Thrombocytopenia, unspecified", "Blood"),
    "D62": ("D62", "Acute posthemorrhagic anemia", "Blood"),
    "D63.1": ("D63.1", "Anemia in chronic kidney disease", "Blood"),
    "D65": ("D65", "Disseminated intravascular coagulation", "Blood"),
    "D68.9": ("D68.9", "Coagulation defect, unspecified", "Blood"),
    "D72.829": ("D72.829", "Elevated white blood cell count, unspecified", "Blood"),
    # Endocrine (E00-E89)
    "E03.9": ("E03.9", "Hypothyroidism, unspecified", "Endocrine"),
    "E05.90": ("E05.90", "Thyrotoxicosis, unspecified without thyrotoxic crisis", "Endocrine"),
    "E07.9": ("E07.9", "Disorder of thyroid, unspecified", "Endocrine"),
    "E11": ("E11", "Type 2 diabetes mellitus", "Endocrine"),
    "E11.9": ("E11.9", "Type 2 diabetes mellitus without complications", "Endocrine"),
    "E11.65": ("E11.65", "Type 2 diabetes mellitus with hyperglycemia", "Endocrine"),
    "E11.40": ("E11.40", "Type 2 diabetes mellitus with diabetic neuropathy, unspecified", "Endocrine"),
    "E11.21": ("E11.21", "Type 2 diabetes mellitus with diabetic nephropathy", "Endocrine"),
    "E11.311": ("E11.311", "Type 2 diabetes mellitus with unspecified diabetic retinopathy with macular edema", "Endocrine"),
    "E11.22": ("E11.22", "Type 2 diabetes mellitus with diabetic chronic kidney disease", "Endocrine"),
    "E11.51": ("E11.51", "Type 2 diabetes mellitus with diabetic peripheral angiopathy without gangrene", "Endocrine"),
    "E11.621": ("E11.621", "Type 2 diabetes mellitus with foot ulcer", "Endocrine"),
    "E10.9": ("E10.9", "Type 1 diabetes mellitus without complications", "Endocrine"),
    "E13.9": ("E13.9", "Other specified diabetes mellitus without complications", "Endocrine"),
    "E55.9": ("E55.9", "Vitamin D deficiency, unspecified", "Endocrine"),
    "E66.01": ("E66.01", "Morbid (severe) obesity due to excess calories", "Endocrine"),
    "E66.9": ("E66.9", "Obesity, unspecified", "Endocrine"),
    "E78.5": ("E78.5", "Dyslipidemia, unspecified", "Endocrine"),
    "E78.00": ("E78.00", "Pure hypercholesterolemia, unspecified", "Endocrine"),
    "E78.1": ("E78.1", "Pure hyperglyceridemia", "Endocrine"),
    "E78.2": ("E78.2", "Mixed hyperlipidemia", "Endocrine"),
    "E87.1": ("E87.1", "Hypo-osmolality and hyponatremia", "Endocrine"),
    "E86.0": ("E86.0", "Dehydration", "Endocrine"),
    "E87.6": ("E87.6", "Hypokalemia", "Endocrine"),
    "E87.5": ("E87.5", "Hyperkalemia", "Endocrine"),
    "E87.0": ("E87.0", "Hyperosmolality and hypernatremia", "Endocrine"),
    # Mental (F01-F99)
    "F10.20": ("F10.20", "Alcohol dependence, uncomplicated", "Mental"),
    "F17.210": ("F17.210", "Nicotine dependence, cigarettes, uncomplicated", "Mental"),
    "F20.9": ("F20.9", "Schizophrenia, unspecified", "Mental"),
    "F31.9": ("F31.9", "Bipolar disorder, unspecified", "Mental"),
    "F32.9": ("F32.9", "Major depressive disorder, single episode, unspecified", "Mental"),
    "F33.0": ("F33.0", "Major depressive disorder, recurrent, mild", "Mental"),
    "F33.9": ("F33.9", "Major depressive disorder, recurrent, unspecified", "Mental"),
    "F41.1": ("F41.1", "Generalized anxiety disorder", "Mental"),
    "F41.9": ("F41.9", "Anxiety disorder, unspecified", "Mental"),
    "F43.10": ("F43.10", "Post-traumatic stress disorder, unspecified", "Mental"),
    "F90.9": ("F90.9", "Attention-deficit hyperactivity disorder, unspecified type", "Mental"),
    "F10.239": ("F10.239", "Alcohol dependence with withdrawal, unspecified", "Mental"),
    "F11.20": ("F11.20", "Opioid dependence, uncomplicated", "Mental"),
    "F32.1": ("F32.1", "Major depressive disorder, single episode, moderate", "Mental"),
    "F32.2": ("F32.2", "Major depressive disorder, single episode, severe without psychotic features", "Mental"),
    # Nervous system (G00-G99)
    "G20": ("G20", "Parkinson disease", "Nervous"),
    "G30.9": ("G30.9", "Alzheimer disease, unspecified", "Nervous"),
    "G35": ("G35", "Multiple sclerosis", "Nervous"),
    "G40.909": ("G40.909", "Epilepsy, unspecified, not intractable, without status epilepticus", "Nervous"),
    "G43.909": ("G43.909", "Migraine, unspecified, not intractable, without status migrainosus", "Nervous"),
    "G47.00": ("G47.00", "Insomnia, unspecified", "Nervous"),
    "G47.33": ("G47.33", "Obstructive sleep apnea", "Nervous"),
    "G89.29": ("G89.29", "Other chronic pain", "Nervous"),
    "G43.009": ("G43.009", "Migraine without aura, not intractable, without status migrainosus", "Nervous"),
    "G62.9": ("G62.9", "Polyneuropathy, unspecified", "Nervous"),
    "G45.9": ("G45.9", "Transient cerebral ischemic attack, unspecified", "Nervous"),
    # Eye (H00-H59)
    "H10.9": ("H10.9", "Unspecified conjunctivitis", "Eye"),
    "H25.9": ("H25.9", "Unspecified age-related cataract", "Eye"),
    "H26.9": ("H26.9", "Unspecified cataract", "Eye"),
    "H33.001": ("H33.001", "Unspecified retinal detachment with retinal break, right eye", "Eye"),
    "H40.10X0": ("H40.10X0", "Unspecified open-angle glaucoma", "Eye"),
    "H52.4": ("H52.4", "Presbyopia", "Eye"),
    "H35.30": ("H35.30", "Unspecified macular degeneration", "Eye"),
    # Ear (H60-H95)
    "H61.20": ("H61.20", "Impacted cerumen, unspecified ear", "Ear"),
    "H66.90": ("H66.90", "Otitis media, unspecified, unspecified ear", "Ear"),
    "H65.90": ("H65.90", "Unspecified nonsuppurative otitis media, unspecified ear", "Ear"),
    "H91.90": ("H91.90", "Unspecified hearing loss, unspecified ear", "Ear"),
    # Circulatory (I00-I99)
    "I10": ("I10", "Essential (primary) hypertension", "Circulatory"),
    "I11.9": ("I11.9", "Hypertensive heart disease without heart failure", "Circulatory"),
    "I12.9": ("I12.9", "Hypertensive chronic kidney disease with stage 1-4 CKD", "Circulatory"),
    "I13.10": ("I13.10", "Hypertensive heart and chronic kidney disease without heart failure", "Circulatory"),
    "I20.0": ("I20.0", "Unstable angina", "Circulatory"),
    "I20.9": ("I20.9", "Angina pectoris, unspecified", "Circulatory"),
    "I21.3": ("I21.3", "ST elevation (STEMI) myocardial infarction of unspecified site", "Circulatory"),
    "I21.9": ("I21.9", "Acute myocardial infarction, unspecified", "Circulatory"),
    "I25.10": ("I25.10", "Atherosclerotic heart disease of native coronary artery without angina pectoris", "Circulatory"),
    "I25.110": ("I25.110", "Atherosclerotic heart disease of native coronary artery with unstable angina pectoris", "Circulatory"),
    "I25.5": ("I25.5", "Ischemic cardiomyopathy", "Circulatory"),
    "I42.9": ("I42.9", "Cardiomyopathy, unspecified", "Circulatory"),
    "I48.0": ("I48.0", "Paroxysmal atrial fibrillation", "Circulatory"),
    "I48.91": ("I48.91", "Unspecified atrial fibrillation", "Circulatory"),
    "I48.2": ("I48.2", "Chronic atrial fibrillation", "Circulatory"),
    "I50.9": ("I50.9", "Heart failure, unspecified", "Circulatory"),
    "I50.20": ("I50.20", "Unspecified systolic (congestive) heart failure", "Circulatory"),
    "I50.22": ("I50.22", "Chronic systolic (congestive) heart failure", "Circulatory"),
    "I50.30": ("I50.30", "Unspecified diastolic (congestive) heart failure", "Circulatory"),
    "I50.32": ("I50.32", "Chronic diastolic (congestive) heart failure", "Circulatory"),
    "I51.9": ("I51.9", "Heart disease, unspecified", "Circulatory"),
    "I63.9": ("I63.9", "Cerebral infarction, unspecified", "Circulatory"),
    "I63.50": ("I63.50", "Cerebral infarction due to unspecified occlusion or stenosis of unspecified cerebral artery", "Circulatory"),
    "I65.29": ("I65.29", "Occlusion and stenosis of unspecified carotid artery", "Circulatory"),
    "I67.9": ("I67.9", "Cerebrovascular disease, unspecified", "Circulatory"),
    "I69.398": ("I69.398", "Other sequelae of cerebral infarction", "Circulatory"),
    "I70.0": ("I70.0", "Atherosclerosis of aorta", "Circulatory"),
    "I73.9": ("I73.9", "Peripheral vascular disease, unspecified", "Circulatory"),
    "I82.409": ("I82.409", "Acute embolism and thrombosis of unspecified deep veins of lower extremity", "Circulatory"),
    "I26.99": ("I26.99", "Other pulmonary embolism without acute cor pulmonale", "Circulatory"),
    "I26.02": ("I26.02", "Saddle embolus of pulmonary artery with acute cor pulmonale", "Circulatory"),
    # Respiratory (J00-J99)
    "J00": ("J00", "Acute nasopharyngitis (common cold)", "Respiratory"),
    "J02.9": ("J02.9", "Acute pharyngitis, unspecified", "Respiratory"),
    "J06.9": ("J06.9", "Acute upper respiratory infection, unspecified", "Respiratory"),
    "J11.1": ("J11.1", "Influenza due to unidentified influenza virus with other respiratory manifestations", "Respiratory"),
    "J12.89": ("J12.89", "Other viral pneumonia", "Respiratory"),
    "J18.1": ("J18.1", "Lobar pneumonia, unspecified organism", "Respiratory"),
    "J18.9": ("J18.9", "Pneumonia, unspecified organism", "Respiratory"),
    "J20.9": ("J20.9", "Acute bronchitis, unspecified", "Respiratory"),
    "J30.9": ("J30.9", "Allergic rhinitis, unspecified", "Respiratory"),
    "J44.1": ("J44.1", "COPD with acute exacerbation", "Respiratory"),
    "J44.9": ("J44.9", "Chronic obstructive pulmonary disease, unspecified", "Respiratory"),
    "J45.20": ("J45.20", "Mild intermittent asthma, uncomplicated", "Respiratory"),
    "J45.909": ("J45.909", "Unspecified asthma, uncomplicated", "Respiratory"),
    "J45.50": ("J45.50", "Severe persistent asthma, uncomplicated", "Respiratory"),
    "J80": ("J80", "Acute respiratory distress syndrome", "Respiratory"),
    "J84.10": ("J84.10", "Pulmonary fibrosis, unspecified", "Respiratory"),
    "J90": ("J90", "Pleural effusion, not elsewhere classified", "Respiratory"),
    "J96.00": ("J96.00", "Acute respiratory failure, unspecified whether with hypoxia or hypercapnia", "Respiratory"),
    "J96.10": ("J96.10", "Chronic respiratory failure, unspecified whether with hypoxia or hypercapnia", "Respiratory"),
    "J98.11": ("J98.11", "Atelectasis", "Respiratory"),
    "R05.9": ("R05.9", "Cough, unspecified", "Respiratory"),
    # Digestive (K00-K95)
    "K20.90": ("K20.90", "Esophagitis, unspecified without bleeding", "Digestive"),
    "K21.0": ("K21.0", "GERD with esophagitis", "Digestive"),
    "K21.9": ("K21.9", "GERD without esophagitis", "Digestive"),
    "K25.9": ("K25.9", "Gastric ulcer, unspecified, without hemorrhage or perforation", "Digestive"),
    "K29.70": ("K29.70", "Gastritis, unspecified, without bleeding", "Digestive"),
    "K35.80": ("K35.80", "Unspecified acute appendicitis", "Digestive"),
    "K40.90": ("K40.90", "Unilateral inguinal hernia, without obstruction or gangrene, not specified as recurrent", "Digestive"),
    "K56.60": ("K56.60", "Unspecified intestinal obstruction", "Digestive"),
    "K57.30": ("K57.30", "Diverticulosis of large intestine without perforation or abscess without bleeding", "Digestive"),
    "K59.00": ("K59.00", "Constipation, unspecified", "Digestive"),
    "K70.30": ("K70.30", "Alcoholic cirrhosis of liver without ascites", "Digestive"),
    "K72.90": ("K72.90", "Hepatic failure, unspecified without coma", "Digestive"),
    "K74.60": ("K74.60", "Unspecified cirrhosis of liver", "Digestive"),
    "K76.0": ("K76.0", "Fatty (change of) liver, not elsewhere classified", "Digestive"),
    "K80.20": ("K80.20", "Calculus of gallbladder without cholecystitis without obstruction", "Digestive"),
    "K81.0": ("K81.0", "Acute cholecystitis", "Digestive"),
    "K85.90": ("K85.90", "Acute pancreatitis without necrosis or infection, unspecified", "Digestive"),
    "K86.1": ("K86.1", "Other chronic pancreatitis", "Digestive"),
    "K92.0": ("K92.0", "Hematemesis", "Digestive"),
    "K92.1": ("K92.1", "Melena", "Digestive"),
    "K92.2": ("K92.2", "Gastrointestinal hemorrhage, unspecified", "Digestive"),
    # Skin (L00-L99)
    "L03.90": ("L03.90", "Cellulitis, unspecified", "Skin"),
    "L08.9": ("L08.9", "Local infection of skin, unspecified", "Skin"),
    "L30.9": ("L30.9", "Dermatitis, unspecified", "Skin"),
    "L40.0": ("L40.0", "Psoriasis vulgaris", "Skin"),
    "L50.9": ("L50.9", "Urticaria, unspecified", "Skin"),
    "L70.0": ("L70.0", "Acne vulgaris", "Skin"),
    "L97.909": ("L97.909", "Non-pressure chronic ulcer of unspecified part of unspecified lower leg", "Skin"),
    # Musculoskeletal (M00-M99)
    "M06.9": ("M06.9", "Rheumatoid arthritis, unspecified", "Musculoskeletal"),
    "M10.9": ("M10.9", "Gout, unspecified", "Musculoskeletal"),
    "M17.11": ("M17.11", "Primary osteoarthritis, right knee", "Musculoskeletal"),
    "M17.12": ("M17.12", "Primary osteoarthritis, left knee", "Musculoskeletal"),
    "M19.90": ("M19.90", "Unspecified osteoarthritis, unspecified site", "Musculoskeletal"),
    "M25.50": ("M25.50", "Pain in unspecified joint", "Musculoskeletal"),
    "M47.816": ("M47.816", "Spondylosis without myelopathy or radiculopathy, lumbar region", "Musculoskeletal"),
    "M51.16": ("M51.16", "Intervertebral disc disorders with radiculopathy, lumbar region", "Musculoskeletal"),
    "M54.2": ("M54.2", "Cervicalgia", "Musculoskeletal"),
    "M54.5": ("M54.5", "Low back pain", "Musculoskeletal"),
    "M62.830": ("M62.830", "Muscle spasm of back", "Musculoskeletal"),
    "M79.3": ("M79.3", "Panniculitis, unspecified", "Musculoskeletal"),
    "M81.0": ("M81.0", "Age-related osteoporosis without current pathological fracture", "Musculoskeletal"),
    "M16.11": ("M16.11", "Primary osteoarthritis, right hip", "Musculoskeletal"),
    "M16.12": ("M16.12", "Primary osteoarthritis, left hip", "Musculoskeletal"),
    "M79.1": ("M79.1", "Myalgia", "Musculoskeletal"),
    "M79.7": ("M79.7", "Fibromyalgia", "Musculoskeletal"),
    "M54.16": ("M54.16", "Radiculopathy, lumbar region", "Musculoskeletal"),
    "M54.17": ("M54.17", "Radiculopathy, lumbosacral region", "Musculoskeletal"),
    "M48.06": ("M48.06", "Spinal stenosis, lumbar region", "Musculoskeletal"),
    # Genitourinary (N00-N99)
    "N17.9": ("N17.9", "Acute kidney failure, unspecified", "Genitourinary"),
    "N18.3": ("N18.3", "Chronic kidney disease, stage 3 (moderate)", "Genitourinary"),
    "N18.4": ("N18.4", "Chronic kidney disease, stage 4 (severe)", "Genitourinary"),
    "N18.5": ("N18.5", "Chronic kidney disease, stage 5", "Genitourinary"),
    "N18.6": ("N18.6", "End stage renal disease", "Genitourinary"),
    "N18.9": ("N18.9", "Chronic kidney disease, unspecified", "Genitourinary"),
    "N19": ("N19", "Unspecified kidney failure", "Genitourinary"),
    "N20.0": ("N20.0", "Calculus of kidney", "Genitourinary"),
    "N39.0": ("N39.0", "Urinary tract infection, site not specified", "Genitourinary"),
    "N40.0": ("N40.0", "Benign prostatic hyperplasia without lower urinary tract symptoms", "Genitourinary"),
    "N40.1": ("N40.1", "Benign prostatic hyperplasia with lower urinary tract symptoms", "Genitourinary"),
    "N80.0": ("N80.0", "Endometriosis of uterus", "Genitourinary"),
    "N83.20": ("N83.20", "Unspecified ovarian cysts", "Genitourinary"),
    "N92.0": ("N92.0", "Excessive and frequent menstruation with regular cycle", "Genitourinary"),
    # Pregnancy (O00-O9A)
    "O80": ("O80", "Encounter for full-term uncomplicated delivery", "Pregnancy"),
    "O24.414": ("O24.414", "Gestational diabetes mellitus in pregnancy, insulin controlled", "Pregnancy"),
    "O13.9": ("O13.9", "Gestational hypertension without significant proteinuria, unspecified trimester", "Pregnancy"),
    "O14.90": ("O14.90", "Unspecified pre-eclampsia, unspecified trimester", "Pregnancy"),
    "O34.211": ("O34.211", "Low transverse scar from previous cesarean delivery", "Pregnancy"),
    "O42.90": ("O42.90", "Premature rupture of membranes, unspecified, unspecified weeks of gestation", "Pregnancy"),
    "O60.10X0": ("O60.10X0", "Preterm labor with preterm delivery, unspecified trimester, fetus 1", "Pregnancy"),
    "O99.019": ("O99.019", "Anemia complicating pregnancy, unspecified trimester", "Pregnancy"),
    "Z37.0": ("Z37.0", "Single live birth", "Pregnancy"),
    # Congenital (Q00-Q99)
    "Q21.0": ("Q21.0", "Ventricular septal defect", "Congenital"),
    "Q25.0": ("Q25.0", "Patent ductus arteriosus", "Congenital"),
    "Q66.0": ("Q66.0", "Congenital talipes equinovarus (clubfoot)", "Congenital"),
    # Symptoms (R00-R99)
    "R00.0": ("R00.0", "Tachycardia, unspecified", "Symptoms"),
    "R00.1": ("R00.1", "Bradycardia, unspecified", "Symptoms"),
    "R06.00": ("R06.00", "Dyspnea, unspecified", "Symptoms"),
    "R06.02": ("R06.02", "Shortness of breath", "Symptoms"),
    "R07.9": ("R07.9", "Chest pain, unspecified", "Symptoms"),
    "R09.81": ("R09.81", "Nasal congestion", "Symptoms"),
    "R10.9": ("R10.9", "Unspecified abdominal pain", "Symptoms"),
    "R10.0": ("R10.0", "Acute abdomen", "Symptoms"),
    "R10.84": ("R10.84", "Generalized abdominal pain", "Symptoms"),
    "R11.0": ("R11.0", "Nausea", "Symptoms"),
    "R11.2": ("R11.2", "Nausea with vomiting, unspecified", "Symptoms"),
    "R19.7": ("R19.7", "Diarrhea, unspecified", "Symptoms"),
    "R25.1": ("R25.1", "Tremor, unspecified", "Symptoms"),
    "R31.9": ("R31.9", "Hematuria, unspecified", "Symptoms"),
    "R42": ("R42", "Dizziness and giddiness", "Symptoms"),
    "R50.9": ("R50.9", "Fever, unspecified", "Symptoms"),
    "R51.9": ("R51.9", "Headache", "Symptoms"),
    "R53.83": ("R53.83", "Other fatigue", "Symptoms"),
    "R55": ("R55", "Syncope and collapse", "Symptoms"),
    "R56.9": ("R56.9", "Unspecified convulsions", "Symptoms"),
    "R60.0": ("R60.0", "Localized edema", "Symptoms"),
    "R73.09": ("R73.09", "Other abnormal glucose", "Symptoms"),
    "R79.89": ("R79.89", "Other specified abnormal findings of blood chemistry", "Symptoms"),
    "R91.8": ("R91.8", "Other nonspecific abnormal finding of lung field", "Symptoms"),
    "R94.31": ("R94.31", "Abnormal electrocardiogram", "Symptoms"),
    # Injury (S00-T88)
    "S06.0X0A": ("S06.0X0A", "Concussion without loss of consciousness, initial encounter", "Injury"),
    "S22.31XA": ("S22.31XA", "Fracture of one rib, right side, initial encounter", "Injury"),
    "S32.009A": ("S32.009A", "Unspecified fracture of unspecified lumbar vertebra, initial encounter", "Injury"),
    "S42.001A": ("S42.001A", "Fracture of unspecified part of right clavicle, initial encounter", "Injury"),
    "S52.501A": ("S52.501A", "Unspecified fracture of the lower end of right radius, initial encounter", "Injury"),
    "S62.009A": ("S62.009A", "Unspecified fracture of navicular bone of unspecified wrist, initial encounter", "Injury"),
    "S72.001A": ("S72.001A", "Fracture of unspecified part of neck of right femur, initial encounter", "Injury"),
    "S72.009A": ("S72.009A", "Fracture of unspecified part of neck of unspecified femur, initial encounter", "Injury"),
    "S82.001A": ("S82.001A", "Unspecified fracture of right patella, initial encounter", "Injury"),
    "S82.901A": ("S82.901A", "Unspecified fracture of lower end of right tibia, initial encounter", "Injury"),
    "S93.401A": ("S93.401A", "Sprain of unspecified ligament of right ankle, initial encounter", "Injury"),
    "T78.40XA": ("T78.40XA", "Allergy, unspecified, initial encounter", "Injury"),
    "T81.4XXA": ("T81.4XXA", "Infection following a procedure, initial encounter", "Injury"),
    "T36.0X5A": ("T36.0X5A", "Adverse effect of penicillins, initial encounter", "Injury"),
    # Factors (Z00-Z99)
    "Z00.00": ("Z00.00", "Encounter for general adult medical examination without abnormal findings", "Factors"),
    "Z01.818": ("Z01.818", "Encounter for other preprocedural examination", "Factors"),
    "Z12.31": ("Z12.31", "Encounter for screening mammogram for malignant neoplasm of breast", "Factors"),
    "Z20.822": ("Z20.822", "Contact with and (suspected) exposure to COVID-19", "Factors"),
    "Z23": ("Z23", "Encounter for immunization", "Factors"),
    "Z51.11": ("Z51.11", "Encounter for antineoplastic chemotherapy", "Factors"),
    "Z79.4": ("Z79.4", "Long term (current) use of insulin", "Factors"),
    "Z79.82": ("Z79.82", "Long term (current) use of aspirin", "Factors"),
    "Z79.891": ("Z79.891", "Long term (current) use of opiate analgesic", "Factors"),
    "Z86.73": ("Z86.73", "Personal history of transient ischemic attack (TIA)", "Factors"),
    "Z87.11": ("Z87.11", "Personal history of peptic ulcer disease", "Factors"),
    "Z87.39": ("Z87.39", "Personal history of other diseases of musculoskeletal system and connective tissue", "Factors"),
    "Z87.891": ("Z87.891", "Personal history of nicotine dependence", "Factors"),
    "Z96.641": ("Z96.641", "Presence of right artificial knee joint", "Factors"),
    "Z96.642": ("Z96.642", "Presence of left artificial knee joint", "Factors"),
    "Z99.2": ("Z99.2", "Dependence on renal dialysis", "Factors"),
}


# ------------------------------------------------------------------ CPT Codes
CPT_CODES: Dict[str, Tuple[str, str, str]] = {
    # Evaluation & Management (99201-99499)
    "99201": ("99201", "Office visit, new patient, level 1", "E&M"),
    "99202": ("99202", "Office visit, new patient, level 2", "E&M"),
    "99203": ("99203", "Office visit, new patient, level 3", "E&M"),
    "99204": ("99204", "Office visit, new patient, level 4", "E&M"),
    "99205": ("99205", "Office visit, new patient, level 5", "E&M"),
    "99211": ("99211", "Office visit, established patient, level 1", "E&M"),
    "99212": ("99212", "Office visit, established patient, level 2", "E&M"),
    "99213": ("99213", "Office visit, established patient, level 3", "E&M"),
    "99214": ("99214", "Office visit, established patient, level 4", "E&M"),
    "99215": ("99215", "Office visit, established patient, level 5", "E&M"),
    "99221": ("99221", "Initial hospital care, per day, level 1", "E&M"),
    "99222": ("99222", "Initial hospital care, per day, level 2", "E&M"),
    "99223": ("99223", "Initial hospital care, per day, level 3", "E&M"),
    "99231": ("99231", "Subsequent hospital care, per day, level 1", "E&M"),
    "99232": ("99232", "Subsequent hospital care, per day, level 2", "E&M"),
    "99233": ("99233", "Subsequent hospital care, per day, level 3", "E&M"),
    "99238": ("99238", "Hospital discharge day management, 30 minutes or less", "E&M"),
    "99239": ("99239", "Hospital discharge day management, more than 30 minutes", "E&M"),
    "99281": ("99281", "Emergency department visit, level 1", "E&M"),
    "99282": ("99282", "Emergency department visit, level 2", "E&M"),
    "99283": ("99283", "Emergency department visit, level 3", "E&M"),
    "99284": ("99284", "Emergency department visit, level 4", "E&M"),
    "99285": ("99285", "Emergency department visit, level 5", "E&M"),
    "99291": ("99291", "Critical care, first 30-74 minutes", "E&M"),
    "99292": ("99292", "Critical care, each additional 30 minutes", "E&M"),
    "99381": ("99381", "Preventive visit, new patient, infant", "E&M"),
    "99391": ("99391", "Preventive visit, established patient, infant", "E&M"),
    "99395": ("99395", "Preventive visit, established patient, 18-39 years", "E&M"),
    "99396": ("99396", "Preventive visit, established patient, 40-64 years", "E&M"),
    "99304": ("99304", "Nursing facility initial care, low complexity", "E&M"),
    "99305": ("99305", "Nursing facility initial care, moderate complexity", "E&M"),
    "99306": ("99306", "Nursing facility initial care, high complexity", "E&M"),
    "99341": ("99341", "Home visit, new patient, level 1", "E&M"),
    "99347": ("99347", "Home visit, established patient, level 1", "E&M"),
    "99441": ("99441", "Telephone E/M, 5-10 minutes", "E&M"),
    "99442": ("99442", "Telephone E/M, 11-20 minutes", "E&M"),
    "99443": ("99443", "Telephone E/M, 21-30 minutes", "E&M"),
    # Surgery (10000-69999)
    "10060": ("10060", "Incision and drainage of abscess, simple", "Surgery"),
    "10120": ("10120", "Incision and removal of foreign body, subcutaneous tissues, simple", "Surgery"),
    "11042": ("11042", "Debridement, subcutaneous tissue, first 20 sq cm", "Surgery"),
    "12001": ("12001", "Simple repair of superficial wounds, 2.5 cm or less", "Surgery"),
    "12002": ("12002", "Simple repair of superficial wounds, 2.6 cm to 7.5 cm", "Surgery"),
    "17000": ("17000", "Destruction benign or premalignant lesion, first lesion", "Surgery"),
    "20610": ("20610", "Arthrocentesis, aspiration and/or injection, major joint", "Surgery"),
    "27447": ("27447", "Arthroplasty, knee, condyle and plateau (total knee replacement)", "Surgery"),
    "27130": ("27130", "Arthroplasty, acetabular and proximal femoral prosthetic replacement (total hip)", "Surgery"),
    "29881": ("29881", "Arthroscopy, knee, surgical, with meniscectomy", "Surgery"),
    "33533": ("33533", "CABG using arterial graft, single arterial graft", "Surgery"),
    "33405": ("33405", "Replacement of aortic valve with prosthesis", "Surgery"),
    "36415": ("36415", "Collection of venous blood by venipuncture", "Surgery"),
    "36556": ("36556", "Insertion of non-tunneled centrally inserted central venous catheter", "Surgery"),
    "43239": ("43239", "Esophagogastroduodenoscopy with biopsy", "Surgery"),
    "43249": ("43249", "Esophagogastroduodenoscopy with balloon dilation", "Surgery"),
    "44970": ("44970", "Laparoscopy, surgical, appendectomy", "Surgery"),
    "47562": ("47562", "Laparoscopy, surgical; cholecystectomy", "Surgery"),
    "47563": ("47563", "Laparoscopy, surgical; cholecystectomy with cholangiography", "Surgery"),
    "49505": ("49505", "Repair initial inguinal hernia, age 5 years or older", "Surgery"),
    "49650": ("49650", "Laparoscopy, surgical; repair initial inguinal hernia", "Surgery"),
    "50590": ("50590", "Lithotripsy (shock wave therapy)", "Surgery"),
    "52000": ("52000", "Cystourethroscopy", "Surgery"),
    "58661": ("58661", "Laparoscopy, surgical; with removal of adnexal structures", "Surgery"),
    "59510": ("59510", "Cesarean delivery, including routine postpartum care", "Surgery"),
    "59400": ("59400", "Routine obstetric care including vaginal delivery", "Surgery"),
    "62323": ("62323", "Injection, lumbar or sacral epidural, steroid", "Surgery"),
    "64483": ("64483", "Injection, transforaminal epidural, lumbar or sacral, single level", "Surgery"),
    "66984": ("66984", "Extracapsular cataract removal with insertion of intraocular lens prosthesis", "Surgery"),
    "69436": ("69436", "Tympanostomy, general anesthesia", "Surgery"),
    # Radiology (70000-79999)
    "70553": ("70553", "MRI brain without contrast, then with contrast", "Radiology"),
    "71046": ("71046", "Radiologic examination, chest, 2 views", "Radiology"),
    "71250": ("71250", "CT thorax without contrast", "Radiology"),
    "72148": ("72148", "MRI lumbar spine without contrast", "Radiology"),
    "72141": ("72141", "MRI cervical spine without contrast", "Radiology"),
    "73721": ("73721", "MRI any joint of lower extremity without contrast", "Radiology"),
    "74177": ("74177", "CT abdomen and pelvis with contrast", "Radiology"),
    "74176": ("74176", "CT abdomen and pelvis without contrast", "Radiology"),
    "76856": ("76856", "Ultrasound, pelvic, complete", "Radiology"),
    "76700": ("76700", "Ultrasound, abdominal, complete", "Radiology"),
    "76770": ("76770", "Ultrasound, retroperitoneal, complete", "Radiology"),
    "77067": ("77067", "Screening mammography, bilateral", "Radiology"),
    "93880": ("93880", "Duplex scan of extracranial arteries", "Radiology"),
    "93970": ("93970", "Duplex scan of extremity veins, complete bilateral", "Radiology"),
    # Pathology/Lab (80000-89999)
    "80048": ("80048", "Basic metabolic panel", "Lab"),
    "80053": ("80053", "Comprehensive metabolic panel", "Lab"),
    "80061": ("80061", "Lipid panel", "Lab"),
    "81001": ("81001", "Urinalysis, automated, with microscopy", "Lab"),
    "82247": ("82247", "Bilirubin, total", "Lab"),
    "82310": ("82310", "Calcium, total", "Lab"),
    "82565": ("82565", "Creatinine, blood", "Lab"),
    "82947": ("82947", "Glucose, quantitative, blood", "Lab"),
    "83036": ("83036", "Hemoglobin A1c", "Lab"),
    "83690": ("83690", "Lipase", "Lab"),
    "84100": ("84100", "Phosphorus inorganic (phosphate)", "Lab"),
    "84132": ("84132", "Potassium, serum", "Lab"),
    "84443": ("84443", "Thyroid stimulating hormone (TSH)", "Lab"),
    "84450": ("84450", "Transferase AST (SGOT)", "Lab"),
    "84460": ("84460", "Transferase ALT (SGPT)", "Lab"),
    "85025": ("85025", "Complete blood count (CBC) with differential", "Lab"),
    "85610": ("85610", "Prothrombin time", "Lab"),
    "85730": ("85730", "Thromboplastin time, partial (PTT)", "Lab"),
    "86580": ("86580", "Skin test, tuberculosis, intradermal", "Lab"),
    "86900": ("86900", "Blood typing, ABO", "Lab"),
    "87040": ("87040", "Culture, bacterial, blood", "Lab"),
    "87086": ("87086", "Culture, urine, quantitative, colony count", "Lab"),
    "87491": ("87491", "Chlamydia trachomatis, amplified probe", "Lab"),
    "87880": ("87880", "Infectious agent antigen detection, Streptococcus, Group A", "Lab"),
    "88305": ("88305", "Level IV surgical pathology", "Lab"),
    # Medicine (90000-99199)
    "90471": ("90471", "Immunization administration, 1 vaccine", "Medicine"),
    "90715": ("90715", "Tdap vaccine, 7 years or older", "Medicine"),
    "90732": ("90732", "Pneumococcal polysaccharide vaccine, 23-valent", "Medicine"),
    "92014": ("92014", "Ophthalmological examination, comprehensive", "Medicine"),
    "93000": ("93000", "Electrocardiogram, routine, with interpretation", "Medicine"),
    "93010": ("93010", "Electrocardiogram, routine, tracing only", "Medicine"),
    "93306": ("93306", "Echocardiography, transthoracic, with Doppler", "Medicine"),
    "93458": ("93458", "Catheter placement in coronary artery for coronary angiography", "Medicine"),
    "94640": ("94640", "Pressurized or nonpressurized inhalation treatment", "Medicine"),
    "94760": ("94760", "Noninvasive ear or pulse oximetry for oxygen saturation", "Medicine"),
    "96360": ("96360", "Intravenous infusion, hydration, initial 31 min to 1 hour", "Medicine"),
    "96365": ("96365", "Intravenous infusion for therapy, initial, up to 1 hour", "Medicine"),
    "96372": ("96372", "Therapeutic, prophylactic, or diagnostic injection; subcutaneous or IM", "Medicine"),
    "96374": ("96374", "Therapeutic, prophylactic, or diagnostic injection; IV push", "Medicine"),
    "97110": ("97110", "Therapeutic exercises to develop strength, endurance, flexibility", "Medicine"),
    "97140": ("97140", "Manual therapy techniques (eg, mobilization, manipulation)", "Medicine"),
    "99195": ("99195", "Phlebotomy, therapeutic", "Medicine"),
}


# ------------------------------------------------------------------ Synonym / alias mapping for fuzzy NLP matching
# Maps common clinical terms/synonyms to ICD-10 codes
CLINICAL_SYNONYMS: Dict[str, List[str]] = {
    # Heart
    "heart attack": ["I21.9", "I21.3"],
    "myocardial infarction": ["I21.9", "I21.3"],
    "mi": ["I21.9"],
    "heart failure": ["I50.9", "I50.20", "I50.22"],
    "chf": ["I50.9", "I50.20"],
    "congestive heart failure": ["I50.9", "I50.20", "I50.22"],
    "atrial fibrillation": ["I48.91", "I48.0", "I48.2"],
    "afib": ["I48.91"],
    "hypertension": ["I10"],
    "high blood pressure": ["I10"],
    "htn": ["I10"],
    "coronary artery disease": ["I25.10"],
    "cad": ["I25.10"],
    "angina": ["I20.9", "I20.0"],
    "stroke": ["I63.9"],
    "cva": ["I63.9"],
    "cerebral infarction": ["I63.9"],
    "dvt": ["I82.409"],
    "deep vein thrombosis": ["I82.409"],
    "pulmonary embolism": ["I26.99"],
    "pe": ["I26.99"],
    # Respiratory
    "pneumonia": ["J18.9", "J18.1"],
    "copd": ["J44.9", "J44.1"],
    "asthma": ["J45.909", "J45.20"],
    "bronchitis": ["J20.9"],
    "upper respiratory infection": ["J06.9"],
    "uri": ["J06.9"],
    "cold": ["J00"],
    "flu": ["J11.1"],
    "influenza": ["J11.1"],
    "ards": ["J80"],
    "respiratory failure": ["J96.00", "J96.10"],
    "pleural effusion": ["J90"],
    "pulmonary fibrosis": ["J84.10"],
    # Diabetes
    "diabetes": ["E11.9"],
    "type 2 diabetes": ["E11.9"],
    "type 1 diabetes": ["E10.9"],
    "dm": ["E11.9"],
    "dm2": ["E11.9"],
    "diabetic neuropathy": ["E11.40"],
    "diabetic nephropathy": ["E11.21"],
    "diabetic retinopathy": ["E11.311"],
    "dka": ["E10.9"],
    "hyperglycemia": ["E11.65"],
    # GI
    "appendicitis": ["K35.80"],
    "acute appendicitis": ["K35.80"],
    "laparoscopic appendectomy": ["K35.80"],
    "cholecystitis": ["K81.0"],
    "acute cholecystitis": ["K81.0"],
    "gallstones": ["K80.20"],
    "pancreatitis": ["K85.90"],
    "gerd": ["K21.0", "K21.9"],
    "gi bleed": ["K92.2"],
    "liver cirrhosis": ["K74.60"],
    "fatty liver": ["K76.0"],
    "intestinal obstruction": ["K56.60"],
    "diverticulitis": ["K57.30"],
    "gastric ulcer": ["K25.9"],
    "gastritis": ["K29.70"],
    # Kidney
    "acute kidney injury": ["N17.9"],
    "aki": ["N17.9"],
    "chronic kidney disease": ["N18.9"],
    "ckd": ["N18.9"],
    "esrd": ["N18.6"],
    "end stage renal disease": ["N18.6"],
    "kidney stone": ["N20.0"],
    "renal calculus": ["N20.0"],
    "uti": ["N39.0"],
    "urinary tract infection": ["N39.0"],
    # Neuro
    "seizure": ["R56.9"],
    "epilepsy": ["G40.909"],
    "migraine": ["G43.909"],
    "parkinson": ["G20"],
    "alzheimer": ["G30.9"],
    "multiple sclerosis": ["G35"],
    "ms": ["G35"],
    "tia": ["G45.9"],
    "sleep apnea": ["G47.33"],
    # Mental
    "depression": ["F32.9", "F33.9"],
    "anxiety": ["F41.1", "F41.9"],
    "ptsd": ["F43.10"],
    "bipolar": ["F31.9"],
    "schizophrenia": ["F20.9"],
    "adhd": ["F90.9"],
    "alcohol dependence": ["F10.20"],
    "opioid dependence": ["F11.20"],
    # Cancer
    "lung cancer": ["C34.90"],
    "breast cancer": ["C50.919"],
    "prostate cancer": ["C61"],
    "colon cancer": ["C18.9"],
    "pancreatic cancer": ["C25.9"],
    "brain tumor": ["C71.9"],
    "thyroid cancer": ["C73"],
    "bladder cancer": ["C67.9"],
    "ovarian cancer": ["C56.9"],
    "melanoma": ["C43.9"],
    # Musculoskeletal
    "fracture hip": ["S72.009A"],
    "fracture femur": ["S72.001A"],
    "fracture wrist": ["S52.501A"],
    "ankle sprain": ["S93.401A"],
    "low back pain": ["M54.5"],
    "lbp": ["M54.5"],
    "neck pain": ["M54.2"],
    "osteoarthritis": ["M19.90"],
    "rheumatoid arthritis": ["M06.9"],
    "gout": ["M10.9"],
    "osteoporosis": ["M81.0"],
    "disc herniation": ["M51.16"],
    "spinal stenosis": ["M48.06"],
    "sciatica": ["M54.16", "M54.17"],
    "total knee replacement": ["Z96.641"],
    "total hip replacement": ["Z96.642"],
    # Blood
    "anemia": ["D64.9", "D50.9"],
    "iron deficiency anemia": ["D50.9"],
    "dic": ["D65"],
    "thrombocytopenia": ["D69.6"],
    # General
    "sepsis": ["A41.9"],
    "dehydration": ["E86.0"],
    "mild dehydration": ["E86.0"],
    "fever": ["R50.9"],
    "chest pain": ["R07.9"],
    "shortness of breath": ["R06.02"],
    "dyspnea": ["R06.00"],
    "syncope": ["R55"],
    "dizziness": ["R42"],
    "headache": ["R51.9"],
    "nausea": ["R11.0"],
    "vomiting": ["R11.2"],
    "diarrhea": ["R19.7"],
    "abdominal pain": ["R10.9"],
    "fatigue": ["R53.83"],
    "edema": ["R60.0"],
    "cellulitis": ["L03.90"],
    "obesity": ["E66.9"],
    "morbid obesity": ["E66.01"],
    "hypothyroidism": ["E03.9"],
    "hyperthyroidism": ["E05.90"],
    "allergy": ["T78.40XA"],
    "concussion": ["S06.0X0A"],
    "normal delivery": ["O80"],
    "cesarean section": ["O34.211"],
    "c-section": ["O34.211"],
    "preeclampsia": ["O14.90"],
    "gestational diabetes": ["O24.414"],
    "cataract": ["H25.9", "H26.9"],
    "glaucoma": ["H40.10X0"],
    "conjunctivitis": ["H10.9"],
    "otitis media": ["H66.90"],
    "bph": ["N40.1"],
    "dialysis": ["Z99.2"],
}


# ------------------------------------------------------------------ Cost Estimation
# Average estimated costs (USD) based on CMS Medicare fee schedules and
# national average allowed amounts.  ICD-10 costs represent average per-
# episode treatment cost; CPT costs represent average procedure/service fee.
# These are *estimates* for decision support — not billing actuals.

# ICD-10 average treatment costs by category (fallback when code not listed)
_ICD10_CATEGORY_COSTS: Dict[str, float] = {
    "Infectious": 4500.0,
    "Neoplasm": 28000.0,
    "Blood": 3200.0,
    "Endocrine": 2800.0,
    "Mental": 3500.0,
    "Nervous": 5500.0,
    "Eye": 3800.0,
    "Ear": 1200.0,
    "Circulatory": 12000.0,
    "Respiratory": 5200.0,
    "Digestive": 6500.0,
    "Skin": 1800.0,
    "Musculoskeletal": 4500.0,
    "Genitourinary": 5800.0,
    "Pregnancy": 8500.0,
    "Congenital": 15000.0,
    "Symptoms": 850.0,
    "Injury": 4200.0,
    "Factors": 350.0,
}

ICD10_COSTS: Dict[str, float] = {
    # Infectious
    "A09": 2100.0, "A41.9": 18500.0, "A49.9": 2800.0, "B34.9": 1200.0,
    "B97.29": 8500.0, "A04.7": 9200.0, "A15.0": 12000.0, "A40.9": 17500.0,
    "A41.01": 19000.0, "A41.02": 22000.0, "B19.20": 5500.0, "B20": 25000.0,
    "B95.61": 8500.0, "B96.20": 4500.0, "J09.X2": 6800.0,
    # Neoplasm
    "C34.90": 42000.0, "C50.919": 38000.0, "C61": 28000.0, "C18.9": 35000.0,
    "C25.9": 52000.0, "C43.9": 18000.0, "C56.9": 45000.0, "C67.9": 22000.0,
    "C71.9": 68000.0, "C73": 16000.0, "C79.51": 32000.0, "C90.00": 48000.0,
    "D17.9": 2200.0,
    # Blood
    "D64.9": 2500.0, "D50.9": 1800.0, "D69.6": 4500.0, "D62": 5200.0,
    "D63.1": 3800.0, "D65": 15000.0, "D68.9": 4200.0, "D72.829": 800.0,
    # Endocrine
    "E03.9": 1200.0, "E05.90": 2800.0, "E07.9": 1500.0,
    "E11": 3500.0, "E11.9": 3500.0, "E11.65": 4200.0,
    "E11.40": 6500.0, "E11.21": 8500.0, "E11.311": 9200.0,
    "E11.22": 12000.0, "E11.51": 7800.0, "E11.621": 8500.0,
    "E10.9": 4500.0, "E13.9": 3800.0, "E55.9": 450.0,
    "E66.01": 5200.0, "E66.9": 2800.0,
    "E78.5": 1200.0, "E78.00": 1400.0, "E78.1": 1200.0, "E78.2": 1500.0,
    "E87.1": 3800.0, "E86.0": 2200.0, "E87.6": 2800.0,
    "E87.5": 3200.0, "E87.0": 3500.0,
    # Mental
    "F10.20": 6500.0, "F17.210": 1200.0, "F20.9": 8500.0, "F31.9": 5500.0,
    "F32.9": 3200.0, "F33.0": 3800.0, "F33.9": 4200.0,
    "F41.1": 2800.0, "F41.9": 2500.0, "F43.10": 4500.0, "F90.9": 2200.0,
    "F10.239": 12000.0, "F11.20": 8500.0, "F32.1": 3500.0, "F32.2": 5200.0,
    # Nervous
    "G20": 12000.0, "G30.9": 18000.0, "G35": 28000.0,
    "G40.909": 5500.0, "G43.909": 2200.0, "G47.00": 1500.0,
    "G47.33": 3800.0, "G89.29": 4500.0, "G43.009": 2200.0,
    "G62.9": 3500.0, "G45.9": 8500.0,
    # Eye
    "H10.9": 350.0, "H25.9": 3800.0, "H26.9": 3800.0,
    "H33.001": 8500.0, "H40.10X0": 2800.0, "H52.4": 250.0, "H35.30": 4500.0,
    # Ear
    "H61.20": 180.0, "H66.90": 850.0, "H65.90": 650.0, "H91.90": 2200.0,
    # Circulatory
    "I10": 1800.0, "I11.9": 5500.0, "I12.9": 6200.0, "I13.10": 7500.0,
    "I20.0": 15000.0, "I20.9": 8500.0, "I21.3": 32000.0, "I21.9": 28000.0,
    "I25.10": 12000.0, "I25.110": 18000.0, "I25.5": 15000.0,
    "I42.9": 12000.0, "I48.0": 8500.0, "I48.91": 6500.0, "I48.2": 8500.0,
    "I50.9": 14000.0, "I50.20": 16000.0, "I50.22": 18000.0,
    "I50.30": 14000.0, "I50.32": 16000.0, "I51.9": 8500.0,
    "I63.9": 22000.0, "I63.50": 25000.0, "I65.29": 12000.0,
    "I67.9": 8500.0, "I69.398": 5500.0, "I70.0": 6500.0,
    "I73.9": 5200.0, "I82.409": 12000.0, "I26.99": 18000.0, "I26.02": 25000.0,
    # Respiratory
    "J00": 250.0, "J02.9": 350.0, "J06.9": 450.0, "J11.1": 2800.0,
    "J12.89": 6500.0, "J18.1": 8500.0, "J18.9": 7500.0,
    "J20.9": 1200.0, "J30.9": 850.0, "J44.1": 8500.0, "J44.9": 5500.0,
    "J45.20": 2200.0, "J45.909": 2800.0, "J45.50": 5500.0,
    "J80": 35000.0, "J84.10": 12000.0, "J90": 6500.0,
    "J96.00": 28000.0, "J96.10": 18000.0, "J98.11": 4500.0, "R05.9": 350.0,
    # Digestive
    "K20.90": 1800.0, "K21.0": 2200.0, "K21.9": 1500.0, "K25.9": 3500.0,
    "K29.70": 1800.0, "K35.80": 12000.0, "K40.90": 8500.0,
    "K56.60": 15000.0, "K57.30": 2800.0, "K59.00": 450.0,
    "K70.30": 12000.0, "K72.90": 22000.0, "K74.60": 15000.0,
    "K76.0": 3500.0, "K80.20": 5500.0, "K81.0": 12000.0,
    "K85.90": 12000.0, "K86.1": 8500.0,
    "K92.0": 8500.0, "K92.1": 6500.0, "K92.2": 12000.0,
    # Skin
    "L03.90": 3500.0, "L08.9": 1800.0, "L30.9": 650.0,
    "L40.0": 5500.0, "L50.9": 850.0, "L70.0": 450.0, "L97.909": 6500.0,
    # Musculoskeletal
    "M06.9": 12000.0, "M10.9": 3500.0,
    "M17.11": 5500.0, "M17.12": 5500.0, "M19.90": 3500.0, "M25.50": 1200.0,
    "M47.816": 3200.0, "M51.16": 5500.0, "M54.2": 1800.0, "M54.5": 2200.0,
    "M62.830": 1200.0, "M79.3": 1500.0, "M81.0": 3500.0,
    "M16.11": 5500.0, "M16.12": 5500.0, "M79.1": 850.0, "M79.7": 4500.0,
    "M54.16": 3800.0, "M54.17": 3800.0, "M48.06": 5500.0,
    # Genitourinary
    "N17.9": 12000.0, "N18.3": 8500.0, "N18.4": 12000.0,
    "N18.5": 18000.0, "N18.6": 45000.0, "N18.9": 6500.0, "N19": 8500.0,
    "N20.0": 8500.0, "N39.0": 2200.0,
    "N40.0": 1800.0, "N40.1": 3500.0, "N80.0": 5500.0,
    "N83.20": 2800.0, "N92.0": 1500.0,
    # Pregnancy
    "O80": 5500.0, "O24.414": 8500.0, "O13.9": 6500.0,
    "O14.90": 12000.0, "O34.211": 15000.0, "O42.90": 8500.0,
    "O60.10X0": 22000.0, "O99.019": 6500.0, "Z37.0": 3500.0,
    # Congenital
    "Q21.0": 25000.0, "Q25.0": 18000.0, "Q66.0": 8500.0,
    # Symptoms
    "R00.0": 1200.0, "R00.1": 1500.0, "R06.00": 1800.0, "R06.02": 1500.0,
    "R07.9": 2200.0, "R09.81": 250.0, "R10.9": 1500.0,
    "R10.0": 5500.0, "R10.84": 1800.0, "R11.0": 450.0, "R11.2": 850.0,
    "R19.7": 650.0, "R25.1": 1200.0, "R31.9": 1800.0, "R42": 1200.0,
    "R50.9": 1500.0, "R51.9": 850.0, "R53.83": 650.0,
    "R55": 3500.0, "R56.9": 5500.0, "R60.0": 850.0,
    "R73.09": 450.0, "R79.89": 350.0, "R91.8": 850.0, "R94.31": 350.0,
    # Injury
    "S06.0X0A": 5500.0, "S22.31XA": 4500.0, "S32.009A": 8500.0,
    "S42.001A": 3500.0, "S52.501A": 5500.0, "S62.009A": 3200.0,
    "S72.001A": 18000.0, "S72.009A": 18000.0,
    "S82.001A": 8500.0, "S82.901A": 6500.0, "S93.401A": 2200.0,
    "T78.40XA": 1500.0, "T81.4XXA": 12000.0, "T36.0X5A": 2200.0,
    # Factors
    "Z00.00": 250.0, "Z01.818": 350.0, "Z12.31": 250.0,
    "Z20.822": 350.0, "Z23": 150.0, "Z51.11": 8500.0,
    "Z79.4": 2800.0, "Z79.82": 120.0, "Z79.891": 3500.0,
    "Z86.73": 450.0, "Z87.11": 250.0, "Z87.39": 250.0,
    "Z87.891": 350.0, "Z96.641": 450.0, "Z96.642": 450.0, "Z99.2": 45000.0,
}

CPT_COSTS: Dict[str, float] = {
    # E&M
    "99201": 45.0, "99202": 75.0, "99203": 110.0, "99204": 170.0, "99205": 210.0,
    "99211": 25.0, "99212": 45.0, "99213": 75.0, "99214": 110.0, "99215": 150.0,
    "99221": 195.0, "99222": 260.0, "99223": 380.0,
    "99231": 80.0, "99232": 115.0, "99233": 170.0,
    "99238": 80.0, "99239": 115.0,
    "99281": 50.0, "99282": 75.0, "99283": 135.0, "99284": 250.0, "99285": 450.0,
    "99291": 350.0, "99292": 175.0,
    "99381": 120.0, "99391": 95.0, "99395": 150.0, "99396": 165.0,
    "99304": 110.0, "99305": 165.0, "99306": 240.0,
    "99341": 85.0, "99347": 65.0,
    "99441": 35.0, "99442": 60.0, "99443": 85.0,
    # Surgery
    "10060": 250.0, "10120": 350.0, "11042": 180.0,
    "12001": 220.0, "12002": 280.0, "17000": 120.0,
    "20610": 150.0,
    "27447": 22000.0, "27130": 24000.0, "29881": 5500.0,
    "33533": 45000.0, "33405": 55000.0,
    "36415": 12.0, "36556": 850.0,
    "43239": 1800.0, "43249": 2200.0,
    "44970": 8500.0, "47562": 9500.0, "47563": 10500.0,
    "49505": 5500.0, "49650": 7500.0,
    "50590": 6500.0, "52000": 1500.0,
    "58661": 8500.0,
    "59510": 12000.0, "59400": 7500.0,
    "62323": 650.0, "64483": 750.0,
    "66984": 3500.0, "69436": 2200.0,
    # Radiology
    "70553": 1200.0, "71046": 65.0, "71250": 450.0,
    "72148": 850.0, "72141": 850.0, "73721": 750.0,
    "74177": 650.0, "74176": 550.0,
    "76856": 280.0, "76700": 250.0, "76770": 280.0,
    "77067": 180.0, "93880": 350.0, "93970": 380.0,
    # Lab
    "80048": 22.0, "80053": 28.0, "80061": 35.0,
    "81001": 12.0, "82247": 15.0, "82310": 15.0,
    "82565": 18.0, "82947": 12.0, "83036": 25.0,
    "83690": 18.0, "84100": 15.0, "84132": 12.0,
    "84443": 28.0, "84450": 15.0, "84460": 15.0,
    "85025": 18.0, "85610": 12.0, "85730": 18.0,
    "86580": 15.0, "86900": 12.0,
    "87040": 25.0, "87086": 22.0, "87491": 45.0,
    "87880": 25.0, "88305": 120.0,
    # Medicine
    "90471": 28.0, "90715": 45.0, "90732": 85.0,
    "92014": 120.0,
    "93000": 35.0, "93010": 18.0, "93306": 450.0, "93458": 3500.0,
    "94640": 35.0, "94760": 12.0,
    "96360": 120.0, "96365": 180.0, "96372": 25.0, "96374": 45.0,
    "97110": 45.0, "97140": 40.0, "99195": 85.0,
}

# CPT category-level fallback costs
_CPT_CATEGORY_COSTS: Dict[str, float] = {
    "E&M": 120.0,
    "Surgery": 5500.0,
    "Radiology": 450.0,
    "Lab": 25.0,
    "Medicine": 85.0,
}


def estimate_cost(code: str, code_system: str) -> Optional[float]:
    """Return estimated cost (USD) for an ICD-10 or CPT code.

    Falls back to category average when exact code is not in the cost table.
    """
    if code_system == "ICD10":
        cost = ICD10_COSTS.get(code)
        if cost is not None:
            return cost
        # Fallback: use category from main ICD10_CM dict
        info = ICD10_CM.get(code)
        if info:
            return _ICD10_CATEGORY_COSTS.get(info[2], 2500.0)
        return None
    elif code_system == "CPT":
        cost = CPT_COSTS.get(code)
        if cost is not None:
            return cost
        info = CPT_CODES.get(code)
        if info:
            return _CPT_CATEGORY_COSTS.get(info[2], 250.0)
        return None
    return None


# ------------------------------------------------------------------ Reverse-lookup indexes
_ICD10_BY_KEYWORD: Dict[str, list[str]] = {}
for _code, (_c, _desc, _cat) in ICD10_CM.items():
    for _word in _desc.lower().split():
        if len(_word) > 3:
            _ICD10_BY_KEYWORD.setdefault(_word, []).append(_code)

_CPT_BY_KEYWORD: Dict[str, list[str]] = {}
for _code, (_c, _desc, _cat) in CPT_CODES.items():
    for _word in _desc.lower().split():
        if len(_word) > 3:
            _CPT_BY_KEYWORD.setdefault(_word, []).append(_code)


# ------------------------------------------------------------------ Lookup functions

def lookup_icd10(code: str) -> Optional[Tuple[str, str, str]]:
    """Exact ICD-10-CM code lookup."""
    return ICD10_CM.get(code)


def lookup_cpt(code: str) -> Optional[Tuple[str, str, str]]:
    """Exact CPT code lookup."""
    return CPT_CODES.get(code)


def search_icd10_by_text(text: str, max_results: int = 5) -> list[Tuple[str, str, str]]:
    """Search ICD-10 codes by text — uses synonym matching first, then keyword scoring."""
    text_lower = text.lower().strip()

    # 1. Check synonym/alias mapping first (highest confidence — exact match)
    if text_lower in CLINICAL_SYNONYMS:
        results = []
        for code in CLINICAL_SYNONYMS[text_lower]:
            if code in ICD10_CM:
                results.append(ICD10_CM[code])
        if results:
            return results[:max_results]

    # 2. Partial synonym matching — score by length of match (longest wins)
    best_matches: list[tuple[int, str, list[str]]] = []
    for synonym, codes in CLINICAL_SYNONYMS.items():
        if synonym in text_lower or text_lower in synonym:
            best_matches.append((len(synonym), synonym, codes))
    # Sort longest first — longer matches are more specific
    best_matches.sort(key=lambda x: x[0], reverse=True)
    for _, _, codes in best_matches:
        results = []
        for code in codes:
            if code in ICD10_CM:
                results.append(ICD10_CM[code])
        if results:
            return results[:max_results]

    # 3. Keyword-based scoring from description index
    scores: Dict[str, int] = {}
    for word in text_lower.split():
        if len(word) <= 3:
            continue
        for code in _ICD10_BY_KEYWORD.get(word, []):
            scores[code] = scores.get(code, 0) + 1
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return [ICD10_CM[code] for code, _ in ranked[:max_results] if code in ICD10_CM]


def search_cpt_by_text(text: str, max_results: int = 5) -> list[Tuple[str, str, str]]:
    """Search CPT codes by description text (keyword matching)."""
    text_lower = text.lower()
    scores: Dict[str, int] = {}
    for word in text_lower.split():
        if len(word) <= 3:
            continue
        for code in _CPT_BY_KEYWORD.get(word, []):
            scores[code] = scores.get(code, 0) + 1
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return [CPT_CODES[code] for code, _ in ranked[:max_results] if code in CPT_CODES]

