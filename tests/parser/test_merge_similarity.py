import re

# Mock settings
MERGE_DESCRIPTION_SIMILARITY = 0.85
MERGE_AMOUNT_TOLERANCE = 1.0

def _norm_desc(d: str) -> str:
    if not d:
        return ""
    d = d.lower()
    d = re.sub(r"[^a-z0-9\s]", " ", d)
    d = re.sub(r"\s+", " ", d).strip()
    return d

def _parse_amount(a) -> float:
    try:
        if a is None:
            return 0.0
        s = str(a)
        s = s.replace("\u00A0", " ")
        s = s.replace(" ", "")
        s = s.replace("₹", "").replace("rs.", "").replace("rs", "").replace("inr", "")
        s = s.strip()
        if s.startswith("(") and s.endswith(")"):
            s = "-" + s[1:-1]
        s = s.replace(",", "")
        return float(s)
    except:
        return 0.0

def _is_similar(a: dict, b: dict) -> bool:
    a_desc = _norm_desc(a.get("description") or "")
    b_desc = _norm_desc(b.get("description") or "")
    if not a_desc and not b_desc:
        desc_sim = 1.0
        a_set, b_set = set(), set()
    else:
        a_set = set(a_desc.split())
        b_set = set(b_desc.split())
        if not a_set or not b_set:
            desc_sim = 0.0
        else:
            inter = a_set & b_set
            desc_sim = len(inter) / float(len(a_set | b_set))
    a_amt = _parse_amount(a.get("amount"))
    b_amt = _parse_amount(b.get("amount"))
    amt_close = abs(a_amt - b_amt) <= MERGE_AMOUNT_TOLERANCE

    # Merge if they are Jaccard-similar OR one description is a substring/subset of the other
    is_contained = False
    if a_desc and b_desc:
        if (a_desc in b_desc) or (b_desc in a_desc):
            is_contained = True
        elif a_set.issubset(b_set) or b_set.issubset(a_set):
            is_contained = True

    is_desc_similar = (desc_sim >= MERGE_DESCRIPTION_SIMILARITY) or is_contained
    return is_desc_similar and amt_close

def _merge_groups(group: list[dict]) -> dict:
    semantic_items = [g for g in group if g.get("source") == "semantic"]
    heuristic_items = [g for g in group if g.get("source") == "heuristic"]

    chosen = group[0]
    best_semantic = max(semantic_items, key=lambda x: float(x.get("confidence") or 0.0)) if semantic_items else None
    best_heuristic = max(heuristic_items, key=lambda x: float(x.get("confidence") or 0.0)) if heuristic_items else None

    if best_semantic and best_heuristic:
        sem_conf = float(best_semantic.get("confidence") or 0.0)
        heu_conf = float(best_heuristic.get("confidence") or 0.0)
        chosen = best_semantic if sem_conf >= (heu_conf - 0.15) else best_heuristic
    elif best_semantic:
        chosen = best_semantic
    elif best_heuristic:
        chosen = best_heuristic

    sources = sorted({g.get("source") for g in group if g.get("source")})
    max_conf = max([float(g.get("confidence") or 0.0) for g in group]) if group else 0.0
    merged = dict(chosen)
    merged["sources"] = sources
    merged["confidence"] = max_conf

    # Use the longer description when one normalized description contains/is a superset of the other
    chosen_desc_norm = _norm_desc(chosen.get("description") or "")
    longest_desc = chosen.get("description") or ""

    for g in group:
        g_desc = g.get("description") or ""
        g_desc_norm = _norm_desc(g_desc)
        if len(g_desc_norm) > len(chosen_desc_norm):
            g_set = set(g_desc_norm.split())
            chosen_set = set(chosen_desc_norm.split())
            if (chosen_desc_norm in g_desc_norm) or chosen_set.issubset(g_set):
                longest_desc = g_desc
                chosen_desc_norm = g_desc_norm

    merged["description"] = longest_desc
    return merged

def test_merge_truncated_description():
    # Test case from actual claim:
    # Semantic parser got truncated description "Laparoscopic Surgical Consumables (Trocar, 1"
    # Heuristic parser got full description "Laparoscopic Surgical Consumables (Trocar, 1 Endo-clip, Sutures, Catheter)"
    sem_item = {
        "description": "Laparoscopic Surgical Consumables (Trocar, 1",
        "amount": "10839.0",
        "category": "Consumables",
        "source": "semantic",
        "confidence": 0.9,
    }
    heur_item = {
        "description": "Laparoscopic Surgical Consumables (Trocar, 1 Endo-clip, Sutures, Catheter)",
        "amount": "10,839.00",
        "category": "Consumables",
        "source": "heuristic",
        "confidence": 0.5,
    }

    # Verify they are similar and should merge
    assert _is_similar(sem_item, heur_item) is True

    # Verify that merging them picks the longer description
    group = [sem_item, heur_item]
    merged = _merge_groups(group)

    assert merged["description"] == "Laparoscopic Surgical Consumables (Trocar, 1 Endo-clip, Sutures, Catheter)"
    assert merged["amount"] == "10839.0" or merged["amount"] == "10,839.00"
