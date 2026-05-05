import json
import pdfkit
from jinja2 import Template
import os

# 1. SETUP: Ensure this path matches your installation
path_to_wkhtmltopdf = r'C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe'
config = pdfkit.configuration(wkhtmltopdf=path_to_wkhtmltopdf)

def generate_full_bill(json_path, output_pdf):
    if not os.path.exists(json_path):
        print(f"Error: File not found at {json_path}")
        return

    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    bill_info = {
        "bill_id": data.get('id', 'N/A')[:8].upper(),
        "patient": {"name": "Valued Patient", "address": "Not Provided", "dob": "N/A", "gender": "N/A"},
        "hospital": {"name": "SYNTHEA GENERAL HOSPITAL", "address": "100 Medical Way, Boston, MA"},
        "items": [],
        "total_cost": 0.0
    }

    entries = data.get('entry', [])
    print(f"Scanning {len(entries)} entries...")

    for entry in entries:
        res = entry.get('resource', {})
        res_type = res.get('resourceType')
        
        # Capture Patient Data
        if res_type == 'Patient':
            name_list = res.get('name', [{}])[0]
            first = " ".join(name_list.get('given', []))
            last = name_list.get('family', '')
            bill_info['patient']['name'] = f"{first} {last}"
            bill_info['patient']['dob'] = res.get('birthDate', 'N/A')
            bill_info['patient']['gender'] = res.get('gender', 'N/A')
            print(f"Found Patient: {bill_info['patient']['name']}")

        # Capture Claim Data (Financials)[cite: 1, 2]
        if res_type == 'Claim':
            # Extract Amount
            amount = float(res.get('total', {}).get('value', 0))
            bill_info['total_cost'] += amount
            
            # Extract Description from item or type[cite: 1]
            item_data = res.get('item', [{}])[0].get('productOrService', {}).get('coding', [{}])[0]
            if not item_data.get('display'):
                item_data = res.get('type', {}).get('coding', [{}])[0]
            
            bill_info['items'].append({
                "date": res.get('billablePeriod', {}).get('start', 'N/A')[:10],
                "desc": item_data.get('display', 'Medical Service'),
                "code": item_data.get('code', 'N/A'),
                "price": f"{amount:.2f}"
            })

    print(f"Extracted {len(bill_info['items'])} line items.")
    print(f"Total Amount: ${bill_info['total_cost']:.2f}")

    # 2. HTML TEMPLATE (Fixed Variable Definition)
    html_template = """
    <html>
    <head>
        <style>
            body { font-family: 'Segoe UI', Arial; margin: 40px; color: #333; }
            .header { border-bottom: 3px solid #2c3e50; padding-bottom: 10px; margin-bottom: 20px; }
            .info-section { display: flex; justify-content: space-between; margin-bottom: 30px; }
            table { width: 100%; border-collapse: collapse; }
            th { background-color: #2c3e50; color: white; padding: 12px; text-align: left; }
            td { padding: 12px; border-bottom: 1px solid #ddd; }
            .total-box { text-align: right; margin-top: 30px; font-size: 1.5em; font-weight: bold; border-top: 2px solid #2c3e50; padding-top: 10px; }
        </style>
    </head>
    <body>
        <div class="header">
            <h1>{{ hospital.name }}</h1>
            <p>{{ hospital.address }} | <strong>Invoice #: {{ bill_id }}</strong></p>
        </div>
        <div class="info-section">
            <div><strong>BILL TO:</strong><br>{{ patient.name }}</div>
            <div style="text-align: right;"><strong>DETAILS:</strong><br>DOB: {{ patient.dob }}<br>Gender: {{ patient.gender }}</div>
        </div>
        <table>
            <thead>
                <tr><th>Date</th><th>Description</th><th>Code</th><th>Amount</th></tr>
            </thead>
            <tbody>
                {% for item in items %}
                <tr><td>{{ item.date }}</td><td>{{ item.desc }}</td><td>{{ item.code }}</td><td>${{ item.price }}</td></tr>
                {% endfor %}
            </tbody>
        </table>
        <div class="total-box">TOTAL AMOUNT DUE: ${{ "{:,.2f}".format(total_cost) }}</div>
    </body>
    </html>
    """

    template = Template(html_template)
    html_out = template.render(**bill_info)
    
    # 3. CONVERSION
    try:
        pdfkit.from_string(html_out, output_pdf, configuration=config)
        print(f"Success! PDF generated at: {os.path.abspath(output_pdf)}")
    except Exception as e:
        print(f"Error during PDF generation: {e}")

# IMPORTANT: Ensure this path is correct
input_path = r'C:\Users\Admin\Downloads\output\fhir\hospitalInformation1777959833019.json'
generate_full_bill(input_path, 'Actual_Hospital_Bill.pdf')