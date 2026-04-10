$ErrorActionPreference = 'Stop'
$outPath = 'c:\Project\ClaimGPT\tmp\ollama_eval_output.json'

$path = 'c:\Project\ClaimGPT\tmp\parser_debug\4c0cec0f-7870-4abe-bd2b-68a17096c7b5_9cc5c17c-f96e-4469-80d4-4f002999265b.json'
$d = Get-Content $path -Raw | ConvertFrom-Json
$pages = $d.ocr_pages | Sort-Object page_number
$chunks = @()
foreach ($p in $pages) {
  if ($p.text) {
    $chunks += "[PAGE $($p.page_number)]`n$($p.text)"
  }
}
$rawText = ($chunks -join "`n`n")
if ($rawText.Length -gt 8000) {
  $rawText = $rawText.Substring(0, 8000)
}

$prompt = @"
You are extracting data from hospital claim documents.
Return ONLY valid JSON for the provided schema.
Hard rules:
1) Do not guess. If a value is not explicitly present, return null.
2) primary_diagnosis must be the reason for admission or principal diagnosis.
3) Extract bill_line_items row-wise from billing tables/statements.
4) Use numeric values for amounts, quantity, and unit_price.
5) confidence must be one of HIGH, MEDIUM, LOW.
6) No markdown, no commentary, no extra keys.

Document OCR text:
$rawText
"@

$schema = @{
  type = 'object'
  properties = @{
    patient_name = @{ type = @('string', 'null') }
    member_id = @{ type = @('string', 'null') }
    policy_number = @{ type = @('string', 'null') }
    age = @{ type = @('integer', 'null') }
    hospital_name = @{ type = @('string', 'null') }
    admission_date = @{ type = @('string', 'null') }
    discharge_date = @{ type = @('string', 'null') }
    primary_diagnosis = @{ type = @('string', 'null') }
    secondary_diagnosis = @{ type = @('string', 'null') }
    procedures = @{ type = 'array'; items = @{ type = 'string' } }
    treating_doctor = @{ type = @('string', 'null') }
    claimed_total = @{ type = @('number', 'null') }
    bill_line_items = @{
      type = 'array'
      items = @{
        type = 'object'
        properties = @{
          description = @{ type = 'string' }
          category = @{ type = @('string', 'null') }
          quantity = @{ type = @('number', 'null') }
          unit_price = @{ type = @('number', 'null') }
          amount = @{ type = @('number', 'null') }
        }
        required = @('description', 'category', 'quantity', 'unit_price', 'amount')
      }
    }
    notes = @{ type = @('string', 'null') }
    confidence = @{ type = 'string'; enum = @('HIGH', 'MEDIUM', 'LOW') }
  }
  required = @(
    'patient_name', 'member_id', 'policy_number', 'age', 'hospital_name',
    'admission_date', 'discharge_date', 'primary_diagnosis', 'secondary_diagnosis',
    'procedures', 'treating_doctor', 'claimed_total', 'bill_line_items', 'notes', 'confidence'
  )
}

$payload = @{
  model = 'llama3.2'
  prompt = $prompt
  stream = $false
  format = $schema
  options = @{ temperature = 0 }
} | ConvertTo-Json -Depth 30

try {
  $resp = Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:11434/api/generate' -ContentType 'application/json' -Body $payload -TimeoutSec 180
  $obj = $resp.response | ConvertFrom-Json

  $summary = [ordered]@{
    patient_name = $obj.patient_name
    member_id = $obj.member_id
    policy_number = $obj.policy_number
    age = $obj.age
    hospital_name = $obj.hospital_name
    admission_date = $obj.admission_date
    discharge_date = $obj.discharge_date
    primary_diagnosis = $obj.primary_diagnosis
    secondary_diagnosis = $obj.secondary_diagnosis
    treating_doctor = $obj.treating_doctor
    claimed_total = $obj.claimed_total
    confidence = $obj.confidence
    bill_line_items_count = @($obj.bill_line_items).Count
  }

  $expected = [ordered]@{
    patient_name = 'Mr. Ravi Kumar Sharma'
    member_id = 'MEM-20210044711'
    policy_number = 'NSHP-HYD-2021-004471'
    age = 47
    primary_diagnosis = 'ST-Elevation Myocardial Infarction (STEMI) – Inferior Wall'
  }

  $correct = 0
  if ($summary.patient_name -eq $expected.patient_name) { $correct++ }
  if ($summary.member_id -eq $expected.member_id) { $correct++ }
  if ($summary.policy_number -eq $expected.policy_number) { $correct++ }
  if ($summary.age -eq $expected.age) { $correct++ }
  if ($summary.primary_diagnosis -and $summary.primary_diagnosis -like '*STEMI*') { $correct++ }
  $accuracy = [math]::Round(($correct / 5.0) * 100.0, 2)

  $result = [ordered]@{
    status = 'ok'
    prompt_chars = $rawText.Length
    summary = $summary
    quick_accuracy_percent = $accuracy
  } | ConvertTo-Json -Depth 8
  Set-Content -Path $outPath -Value $result -Encoding UTF8
}
catch {
  $result = [ordered]@{
    status = 'error'
    message = $_.Exception.Message
  } | ConvertTo-Json -Depth 5
  Set-Content -Path $outPath -Value $result -Encoding UTF8
}
