import httpx
from services.parser_v2.semantic_backends import _build_semantic_prompt, SemanticRequest

def main():
    api_key = "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"
    url = "https://openrouter.ai/api/v1/chat/completions"
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    text = (
        "Diagnosis: Hyperthyroidism  Grave's Disease (ICD: E05.00) Date Item Qty Unit Gross Net Pay "
        "13-12-2025 General Ward Charges 1 5,432 5,432 5,432 "
        "13-12-2025 Nursing Charges 1 1,134 1,134 1,021 "
        "13-12-2025 Duty Doctor Fees 1 1,656 1,656 1,656 "
        "14-12-2025 General Ward Charges 1 5,227 5,227 5,227 "
        "14-12-2025 Nursing Charges 1 1,258 1,258 1,133 "
        "14-12-2025 Duty Doctor Fees 1 1,646 1,646 1,646 "
        "15-12-2025 General Ward Charges 1 5,477 5,477 5,477 "
        "15-12-2025 Nursing Charges 1 1,153 1,153 1,038 "
        "15-12-2025 Duty Doctor Fees 1 1,687 1,687 1,687 "
        "16-12-2025 General Ward Charges 1 5,347 5,347 5,347 "
        "16-12-2025 Nursing Charges 1 1,076 1,076 969 "
        "16-12-2025 Duty Doctor Fees 1 1,450 1,450 1,450 "
        "13-12-2025 Registration & Admission Fee 1 0 0 0 "
        "13-12-2025 TAB MET XL 25 [PO OD] 10 65 65 65 "
        "15-12-2025 TAB CARBIMAZOLE 10MG [PO TDS 30 187 187 187 "
        "13-12-2025 TAB PAN 40MG [PO OD] 10 130 130 130 "
        "16-12-2025 Serum Electrolytes 1 608 608 608 "
        "14-12-2025 ECG 1 346 346 346 "
        "15-12-2025 Thyroid Profile 1 1,173 1,173 1,173 "
        "16-12-2025 Biomedical Waste Disposal Ch 1 0 0 0"
    )
    
    req = SemanticRequest(
        region_id="af9c0de8-08d3-4276-8bd6-1e9e4877a7eb",
        region_type="expense_table",
        page=1,
        document_id="doc1",
        claim_id="claim1",
        text=text,
        tokens=[]
    )
    
    prompt = _build_semantic_prompt(req)
    
    payload = {
        "model": "openrouter/free",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens": 4096
    }
    
    print("Sending prompt to openrouter/free...")
    try:
        response = httpx.post(url, json=payload, headers=headers, timeout=60)
        print(f"Status code: {response.status_code}")
        if response.status_code == 200:
            print("Response content:")
            print(response.json()["choices"][0]["message"]["content"])
        else:
            print(response.text)
    except Exception as e:
        print(f"Exception: {e}")

if __name__ == "__main__":
    main()
