from typing import List, Dict, Any, Optional
import re

ANCHORS = {
    "patient_name": ["patient name", "name", "name of the patient", "insured name"],
    "age": ["age", "age/sex", "age(yrs)"],
    "sex": ["sex", "gender", "m/f"],
    "address": ["address", "residence"],
    "admission_date": ["admission date", "doa", "date of admission", "admitted on", "adm date"],
    "discharge_date": ["discharge date", "dod", "date of discharge", "discharged on", "discharge date", "disch date"],
    "hospital_name": ["hospital name", "name of hospital"],
    "occupation": ["occupation", "profession", "job"],
}

def extract_form_fields(tokens: List[Dict[str, Any]]) -> Dict[str, str]:
    if not tokens:
        return {}
        
    # Pre-process tokens to split merged anchor-value tokens like "Sex- FEMALE"
    split_tokens = []
    all_anchor_phrases = [phrase for phrases in ANCHORS.values() for phrase in phrases]
    for t in tokens:
        text = t.get("text", "")
        # Look for colon or dash splitting a word and another word
        match = re.match(r"^([A-Za-z\s]+)([:\-])(.+)$", text)
        if match:
            k_part = match.group(1).strip()
            k_clean = re.sub(r'[^a-z0-9\s]', '', k_part.lower()).strip()
            if k_clean in all_anchor_phrases:
                # Split into two tokens
                t1 = t.copy()
                t1["text"] = k_part + match.group(2)
                t2 = t.copy()
                t2["text"] = match.group(3).strip()
                # Guess x-coordinates
                mid_x = t["x0"] + (t["x1"] - t["x0"]) * (len(k_part) / len(text))
                t1["x1"] = mid_x
                t2["x0"] = mid_x
                split_tokens.extend([t1, t2])
                continue
        split_tokens.append(t)
        
    # Group tokens by row (simple Y proximity)
    rows = _cluster_rows(split_tokens)
    extracted = {}
    
    # Flatten anchor list for quick lookup to know when to stop
    all_anchor_phrases = [phrase for phrases in ANCHORS.values() for phrase in phrases]
    
    for row in rows:
        # Sort tokens in row left-to-right
        row = sorted(row, key=lambda t: t["x0"])
        
        i = 0
        while i < len(row):
            token_text = row[i].get("text", "").strip()
            if not token_text:
                i += 1
                continue
                
            matched_key = None
            matched_phrase = None
            
            # Look ahead up to 3 tokens for a multi-word anchor
            for lookahead in range(3, 0, -1):
                if i + lookahead <= len(row):
                    phrase = " ".join(t.get("text", "") for t in row[i:i+lookahead]).lower()
                    phrase_clean = re.sub(r'[^a-z0-9\s]', '', phrase).strip()
                    
                    for key, anchor_phrases in ANCHORS.items():
                        if phrase_clean in anchor_phrases or phrase.endswith(":") and phrase[:-1].strip().lower() in anchor_phrases:
                            matched_key = key
                            matched_phrase = phrase
                            break
                    if matched_key:
                        i += lookahead - 1
                        break
            
            if matched_key and matched_key not in extracted:
                # We found an anchor. Now scan RIGHT on the SAME ROW to collect the value.
                value_tokens = []
                i += 1
                while i < len(row):
                    # Look ahead for stop anchors
                    stop_found = False
                    for lookahead in range(3, 0, -1):
                        if i + lookahead <= len(row):
                            phrase = " ".join(t.get("text", "") for t in row[i:i+lookahead]).lower()
                            phrase_clean = re.sub(r'[^a-z0-9\s]', '', phrase).strip()
                            if phrase_clean in all_anchor_phrases or (phrase.endswith(":") and phrase[:-1].strip().lower() in all_anchor_phrases):
                                stop_found = True
                                break
                    if stop_found:
                        break
                        
                    # Stop if there's a large horizontal gap (e.g. > 50px)
                    if value_tokens:
                        gap = row[i]["x0"] - value_tokens[-1]["x1"]
                        if gap > 50:
                            break
                    else:
                        gap = row[i]["x0"] - row[i-1]["x1"]
                        if gap > 100: # gap between anchor and first value token
                            break
                            
                    value_text = row[i].get("text", "").strip()
                    # Skip separators right after anchor
                    if value_text in [":", "-", "="] and not value_tokens:
                        pass
                    else:
                        # Clean prefix separators
                        if not value_tokens and len(value_text) > 1 and value_text[0] in [":", "-", "="]:
                            value_text = value_text[1:].strip()
                        if value_text:
                            value_tokens.append(row[i])
                    i += 1
                
                if value_tokens:
                    extracted[matched_key] = " ".join(t.get("text", "").strip() for t in value_tokens).strip()
                    continue # i is already advanced
            i += 1
            
    return extracted

def _cluster_rows(tokens: List[Dict[str, Any]], y_tolerance: float = 6.0) -> List[List[Dict[str, Any]]]:
    sorted_tokens = sorted(tokens, key=lambda t: (t["y0"] + t["y1"]) / 2.0)
    rows = []
    for token in sorted_tokens:
        token_y = (token["y0"] + token["y1"]) / 2.0
        if not rows:
            rows.append([token])
            continue
        current_row = rows[-1]
        avg_row_y = sum((t["y0"] + t["y1"]) / 2.0 for t in current_row) / len(current_row)
        if abs(token_y - avg_row_y) <= y_tolerance:
            current_row.append(token)
        else:
            rows.append([token])
    return rows
