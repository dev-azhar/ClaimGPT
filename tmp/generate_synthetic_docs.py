"""
Generate realistic synthetic Indian hospital documents for testing.
Creates diverse bill layouts, medical scenarios, and expense structures.
"""

import os
import random
from datetime import datetime, timedelta
from pathlib import Path
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER
from PIL import Image, ImageDraw, ImageFont
import io

# Indian names
FIRST_NAMES = [
    "Rajesh", "Priya", "Amit", "Deepika", "Arjun", "Meera", "Vikram", "Neha",
    "Suresh", "Anjali", "Ashok", "Ritika", "Karan", "Pooja", "Sanjay", "Divya"
]

LAST_NAMES = [
    "Sharma", "Patel", "Singh", "Kumar", "Gupta", "Iyer", "Desai", "Verma",
    "Nair", "Rao", "Khan", "Reddy", "Menon", "Bhat", "Dutta", "Sinha"
]

# Indian hospitals
HOSPITAL_NAMES = [
    "Apollo Hospitals, New Delhi",
    "Aniket Netaralay And Maternity Home, Nanded",
    "Fortis Healthcare, Mumbai",
    "Max Super Speciality Hospital, Bangalore",
    "Medanta The Medicity, Gurgaon",
    "Narayana Health, Bangalore",
    "Lilavati Hospital, Mumbai",
    "Sir Ganga Ram Hospital, Delhi",
    "Kokilaben Dhirubhai Ambani Hospital, Mumbai",
    "Jaslok Hospital, Mumbai",
]

# Medical scenarios
SCENARIOS = [
    {
        "name": "Normal Delivery",
        "procedure": "Normal Vaginal Delivery with Maternal & Neonatal Care",
        "expenses": {
            "Room Charges": (5000, 15000),
            "Labour Room Charges": (2000, 8000),
            "Delivery Charges": (10000, 25000),
            "Nursing Charges": (500, 2000),
            "Oxygen Charges": (500, 1500),
            "Medication & Consumables": (3000, 10000),
            "Doctor Consultation": (2000, 5000),
        }
    },
    {
        "name": "Cesarean Delivery",
        "procedure": "Emergency Cesarean Section with Anesthesia",
        "expenses": {
            "Room Charges": (8000, 20000),
            "Operation Theatre Charges": (15000, 40000),
            "Surgical Procedure": (20000, 50000),
            "Anaesthesia Charges": (5000, 15000),
            "Nursing Support": (1000, 3000),
            "Implants & Consumables": (5000, 15000),
            "Blood Products": (2000, 8000),
            "Doctor/Surgeon Fees": (10000, 25000),
        }
    },
    {
        "name": "Medical Investigation",
        "procedure": "Advanced Diagnostic & Investigation",
        "expenses": {
            "Consultation": (1000, 3000),
            "Laboratory Tests": (5000, 15000),
            "Radiology & Imaging": (3000, 10000),
            "CT/MRI Scans": (8000, 20000),
            "Pathology": (2000, 8000),
            "Ultrasound": (1500, 5000),
        }
    },
    {
        "name": "Orthopedic Surgery",
        "procedure": "Orthopedic Surgical Intervention with Implants",
        "expenses": {
            "Pre-op Evaluation": (2000, 5000),
            "Operation Theatre": (20000, 50000),
            "Surgical Implants": (25000, 100000),
            "Anesthesia": (8000, 15000),
            "Post-op Care": (5000, 15000),
            "Physiotherapy": (3000, 10000),
            "Medications": (5000, 15000),
            "Nursing": (2000, 8000),
        }
    },
    {
        "name": "Emergency Care",
        "procedure": "Emergency Department Treatment & Stabilization",
        "expenses": {
            "ED Triage & Assessment": (500, 2000),
            "Diagnostic Tests": (3000, 10000),
            "Imaging": (2000, 8000),
            "Medications": (2000, 8000),
            "Procedures": (5000, 20000),
            "Monitoring": (1000, 5000),
            "Ambulance": (500, 2000),
        }
    },
]

# Indian states and cities
STATES_CITIES = {
    "Maharashtra": ["Mumbai", "Pune", "Nanded", "Nagpur"],
    "Delhi": ["New Delhi", "Delhi"],
    "Karnataka": ["Bangalore", "Bengaluru"],
    "Haryana": ["Gurgaon", "Noida", "Faridabad"],
    "Tamil Nadu": ["Chennai", "Coimbatore"],
}


def generate_patient_data():
    """Generate realistic patient data."""
    age = random.randint(18, 75)
    gender = random.choice(["Male", "Female"])
    
    return {
        "name": f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}",
        "age": age,
        "gender": gender,
        "patient_id": f"IPD{random.randint(100000, 999999)}",
        "registration_number": f"{random.randint(1, 50)}-{random.randint(2020, 2026)}/2026",
        "address": f"{random.randint(1, 500)} {random.choice(['Main Road', 'Market Lane', 'Hospital Road', 'City Center'])}",
    }


def generate_admission_dates():
    """Generate admission and discharge dates."""
    admission = datetime.now() - timedelta(days=random.randint(1, 30))
    discharge = admission + timedelta(days=random.randint(1, 14))
    return {
        "admission_date": admission.strftime("%d-%m-%Y"),
        "discharge_date": discharge.strftime("%d-%m-%Y"),
        "admission_time": f"{random.randint(8, 22)}:30",
        "discharge_time": f"{random.randint(8, 22)}:30",
    }


def generate_expense_breakdown(scenario):
    """Generate realistic expense breakdown."""
    expenses = []
    total = 0
    for category, (min_amt, max_amt) in scenario["expenses"].items():
        amount = random.randint(min_amt, max_amt)
        total += amount
        expenses.append({
            "category": category,
            "amount": amount,
        })
    return expenses, total


def generate_pdf_bill(output_path, scenario_name="Random"):
    """Generate a realistic hospital bill as PDF."""
    if scenario_name == "Random":
        scenario = random.choice(SCENARIOS)
    else:
        scenario = next(s for s in SCENARIOS if s["name"] == scenario_name)
    
    patient = generate_patient_data()
    dates = generate_admission_dates()
    hospital = random.choice(HOSPITAL_NAMES)
    expenses, total = generate_expense_breakdown(scenario)
    
    # Create PDF
    doc = SimpleDocTemplate(output_path, pagesize=A4, topMargin=0.5*inch, bottomMargin=0.5*inch)
    story = []
    styles = getSampleStyleSheet()
    
    # Header
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=14,
        textColor=colors.HexColor('#1a1a1a'),
        alignment=TA_CENTER,
        spaceAfter=6,
        fontName='Helvetica-Bold',
    )
    
    subtitle_style = ParagraphStyle(
        'Subtitle',
        parent=styles['Normal'],
        fontSize=9,
        textColor=colors.HexColor('#333333'),
        alignment=TA_CENTER,
        spaceAfter=3,
    )
    
    normal_style = ParagraphStyle(
        'CustomNormal',
        parent=styles['Normal'],
        fontSize=9,
        textColor=colors.HexColor('#000000'),
        spaceAfter=2,
    )
    
    # Hospital Header
    story.append(Paragraph(hospital.upper(), title_style))
    story.append(Paragraph("Registered & Accredited Healthcare Facility", subtitle_style))
    story.append(Spacer(1, 0.1*inch))
    
    # Document Title
    story.append(Paragraph("ITEMIZED INPATIENT HOSPITAL BILL", ParagraphStyle(
        'DocTitle', parent=styles['Heading2'], fontSize=11, alignment=TA_CENTER, fontName='Helvetica-Bold'
    )))
    story.append(Spacer(1, 0.15*inch))
    
    # Patient & Bill Info
    info_data = [
        ["BILL NO.", f"{random.randint(1, 100)}", "REGISTRATION NO.", patient["registration_number"]],
        ["PATIENT NAME", patient["name"], "AGE / GENDER", f"{patient['age']} / {patient['gender']}"],
        ["IPD REG NO.", patient["patient_id"], "ADDRESS", patient["address"]],
        ["DATE OF ADMISSION", dates["admission_date"], "DATE OF DISCHARGE", dates["discharge_date"]],
    ]
    
    info_table = Table(info_data, colWidths=[1.5*inch, 1.8*inch, 1.5*inch, 1.7*inch])
    info_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f5f5f5')),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('GRID', (0, 0), (-1, -1), 1, colors.grey),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 0.15*inch))
    
    # Diagnosis & Procedure
    story.append(Paragraph(f"<b>Diagnosis/Procedure:</b> {scenario['procedure']}", normal_style))
    story.append(Paragraph(f"<b>Treating Doctor:</b> Dr. {random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}", normal_style))
    story.append(Spacer(1, 0.1*inch))
    
    # Expense Table
    story.append(Paragraph("BILL SUMMARY - ITEMIZED CHARGES", ParagraphStyle(
        'TableTitle', parent=styles['Heading3'], fontSize=10, fontName='Helvetica-Bold'
    )))
    story.append(Spacer(1, 0.05*inch))
    
    expense_data = [["S.No", "Description of Charges", "Quantity", "Rate", "Amount (Rs.)"]]
    for idx, expense in enumerate(expenses, 1):
        qty = random.randint(1, 5)
        rate = expense["amount"] // qty
        expense_data.append([
            str(idx),
            expense["category"],
            str(qty),
            f"{rate:,.2f}",
            f"{expense['amount']:,.2f}"
        ])
    
    expense_table = Table(expense_data, colWidths=[0.4*inch, 3.2*inch, 0.6*inch, 0.9*inch, 1.0*inch])
    expense_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a1a1a')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('ALIGN', (0, 1), (-1, -1), 'RIGHT'),
        ('ALIGN', (1, 1), (1, -1), 'LEFT'),
        ('FONTSIZE', (0, 1), (-1, -1), 8),
        ('TOPPADDING', (0, 1), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 3),
    ]))
    story.append(expense_table)
    story.append(Spacer(1, 0.1*inch))
    
    # Totals
    totals_data = [
        ["TOTAL GROSS AMOUNT", f"Rs. {total:,.2f}"],
        ["DISCOUNT / ADJUSTMENT", f"Rs. {random.randint(0, int(total*0.1)):,.2f}"],
        ["NET AMOUNT DUE", f"Rs. {total - random.randint(0, int(total*0.1)):,.2f}"],
    ]
    
    totals_table = Table(totals_data, colWidths=[4*inch, 1.5*inch])
    totals_table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (0, -1), 'RIGHT'),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#ffeb99')),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('GRID', (0, -1), (-1, -1), 1, colors.black),
    ]))
    story.append(totals_table)
    story.append(Spacer(1, 0.2*inch))
    
    # Footer
    story.append(Paragraph("This is a computer generated bill. No signature required.", ParagraphStyle(
        'Footer', parent=styles['Normal'], fontSize=7, alignment=TA_CENTER, textColor=colors.grey
    )))
    
    # Build PDF
    doc.build(story)
    return True


def generate_test_suite():
    """Generate a diverse set of test documents."""
    output_dir = Path("tmp/synthetic_docs")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    scenarios = ["Normal Delivery", "Cesarean Delivery", "Medical Investigation", "Orthopedic Surgery", "Emergency Care"]
    docs_created = []
    
    print("📋 Generating synthetic hospital documents...\n")
    
    # Create 3 variations of each scenario
    for scenario in scenarios:
        for variation in range(3):
            filename = f"{scenario.lower().replace(' ', '_')}_v{variation+1}.pdf"
            filepath = output_dir / filename
            
            try:
                generate_pdf_bill(str(filepath), scenario)
                size_kb = filepath.stat().st_size / 1024
                print(f"✅ {filename:50s} ({size_kb:.1f} KB)")
                docs_created.append((scenario, str(filepath)))
            except Exception as e:
                print(f"❌ {filename:50s} ERROR: {str(e)}")
    
    print(f"\n✨ Generated {len(docs_created)} synthetic documents in: {output_dir}")
    return output_dir, docs_created


if __name__ == "__main__":
    output_dir, docs = generate_test_suite()
    
    print("\n" + "="*70)
    print("NEXT STEPS:")
    print("="*70)
    print(f"1. Upload documents from: {output_dir}")
    print(f"2. Test OCR extraction on diverse bill layouts")
    print(f"3. Verify parser handles different expense categories")
    print(f"4. Check submission aggregation with various amounts")
    print("="*70)
