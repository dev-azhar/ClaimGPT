ClaimGPT under-the-hood note

Date: 2026-04-09
Source debug file: tmp/parser_debug/d6847c3a-bcd8-4879-b49c-83307512aac2_c5907440-5bd1-4d90-ac88-95a1ee13e186.json

1. What the current flow actually does

- OCR first produces raw text per page.
- Parser then tries structured extraction first when PARSER_structured_extraction_enabled is on.
- If the structured LLM endpoint is unavailable, returns invalid JSON, or fails schema validation, the parser falls back to model-based LayoutLMv3 if available.
- If that also fails or is not available, it falls back to heuristic-v2 regex extraction.
- In the current debug file, the parser output shows used_fallback=true and model_version=heuristic-v2, so the document did not complete through the structured LLM path.

2. Why the last document still shows the fields in debug but they can disappear later

The important distinction is between raw OCR text and the canonical parsed fields used by the submission preview/report.

- The debug file keeps OCR pages, detected tables, and extracted fields together, so you can see text like Surgery Charges, Laboratory, and Consumables in the source material.
- The preview/report layer does not render raw OCR text directly. It builds a normalized expense view from parsed_fields and, if a hospital-bill subtotal block is found, it replaces the generic parsed expense list with a smaller anchored expense list.
- That anchored list only keeps these canonical categories:
  - room_charges
  - investigation_charges
  - surgery_charges
  - consultation_charges
  - pharmacy_charges

So consumables can be parsed and still be dropped from the final expense section if the hospital-bill subtotal branch is used, because consumables is not in that anchored canonical list.

3. Exact hard-coded mappings that matter here

Parser document types considered:
- DISCHARGE_SUMMARY
- LAB_REPORT
- PHARMACY_INVOICE
- HOSPITAL_BILL
- UNKNOWN

Parser expense categories hard-coded in the heuristic extractor:
- surgery_charges
- surgeon_fees
- anaesthesia_charges
- ot_charges
- consumables
- investigation_charges
- room_charges
- nursing_charges
- pharmacy_charges
- consultation_charges
- icu_charges
- ambulance_charges
- misc_charges

Important detail for laboratory:
- The parser does not use a literal laboratory_charges field.
- It normalizes lab-like items into investigation_charges.
- The keyword map includes lab, but not a full laboratory keyword in the category map, so a row labeled Laboratory can be missed unless another pattern catches it.

Important detail for consumables:
- consumables is recognized by the parser and included in HOSPITAL_BILL allowlists.
- But submission preview canonicalizes the billed expense breakdown to a smaller list that excludes consumables, so it can vanish from the report even when the parser found it.

4. Why you saw OCR-debug values but the report still looked incomplete

For this specific claim, the debug OCR contains rows like:
- Surgery Charges
- Laboratory
- Consumables

The parser debug also shows extracted fields such as:
- surgery_charges
- investigation_charges
- consumables

So the loss is not at OCR time. The loss is in normalization and downstream selection:
- Laboratory is not a direct final field name; it has to become investigation_charges.
- Consumables is recognized by the parser, but the preview/report anchored-expense branch can discard it.
- Surgery charges should survive if the page is routed into the hospital-bill expense path or if the canonical subtotal extraction sees Sub Total C / procedure-surgical charges.

5. What the predictor actually uses

The predictor does not score raw line items like surgery, laboratory, or consumables directly.
It uses this 13-value feature vector:
- has_patient_name
- has_policy_number
- has_diagnosis
- has_service_date
- has_total_amount
- has_provider
- num_parsed_fields
- num_entities
- num_icd_codes
- num_cpt_codes
- has_primary_icd
- num_diagnosis_types
- total_amount_log

So the predictor only sees whether the parser produced enough structured signals, not the detailed bill breakdown itself.

6. Short answer to your main question

Yes, the parser is currently falling back to heuristic-v2 for this document.
No, the missing charges are not because those words are completely unknown to the system.
The root cause is a combination of normalization and downstream filtering:
- Laboratory is not a final expense field name; it must map into investigation_charges.
- Consumables is recognized, but the preview/report anchored expense list can drop it.
- The report/preview layer prefers hard-coded canonical categories and does not render every parsed line item.

7. Practical reading of the current behavior

- OCR: sees the text.
- Parser: may extract the values.
- Submission preview: only shows what survives canonical mapping and hospital-bill anchoring.
- Predictor: uses aggregated completeness features, not detailed expense categories.

If you want, the next useful step is to inspect the persisted ParsedField rows for this claim and compare them against the preview payload; that will show exactly which field was lost between parser persistence and report assembly.