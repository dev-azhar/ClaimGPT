import psycopg2

conn = psycopg2.connect('postgresql://claimgpt:claimgpt@localhost:5432/claimgpt')
cur = conn.cursor()

cur.execute('SELECT id FROM claims ORDER BY created_at DESC LIMIT 1')
claim_id = cur.fetchone()[0]
print(f"Claim ID: {claim_id}")

cur.execute('SELECT field_name, field_value, model_version FROM parsed_fields WHERE claim_id = %s', (claim_id,))
print("--- PARSED FIELDS ---")
for row in cur.fetchall():
    print(row)

cur.execute('SELECT text FROM ocr_results WHERE claim_id = %s', (claim_id,))
print("\n--- OCR TEXT ---")
for row in cur.fetchall():
    print(row[0][:1500])
