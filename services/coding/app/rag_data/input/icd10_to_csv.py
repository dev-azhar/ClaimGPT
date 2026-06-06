"""
icd10_to_csv.py
---------------
Parses an ICD-10 ClaML XML file and generates a CSV with:
  - icd10_code              : category code starting with a letter (e.g. D50.0)
  - code_description        : preferred label for the category
  - code_includes           : pipe-separated inclusion terms for the category
  - code_excludes           : pipe-separated exclusion terms for the category
  - chapter                 : Roman-numeral chapter code (e.g. III)
  - chapter_description     : preferred label of the chapter
  - chapter_includes        : pipe-separated inclusion terms for the chapter
  - chapter_excludes        : pipe-separated exclusion terms for the chapter
  - block_range             : the immediate block the category falls under (e.g. D50-D53)
  - block_description       : preferred label of that block

Handles shared-modifier subdivisions (ModifiedBy / ModifierClass) so that codes
like E10-E14, F10-F19, K25-K28, N00-N07, O03-O06, R83-R89, V01-V06 etc.
are fully expanded into their fourth-character sub-codes (e.g. E10.0, E10.1 …).

Usage:
    python icd10_to_csv.py [input_xml] [output_csv]

Defaults:
    input_xml  = icd102019en.xml
    output_csv = icd10_output.csv
"""

import xml.etree.ElementTree as ET
import csv
import re
import sys
import os


# ── helpers ───────────────────────────────────────────────────────────────────

def get_label_text(label_elem):
    """
    Extract clean text from a <Label> element, handling:
      - plain text nodes
      - <Reference> tags  -> appended in parentheses, e.g.  (Z22.-)
      - <Para> / <Fragment> children
    """
    if label_elem is None:
        return ""

    parts = []

    def collect(node):
        if node.text:
            parts.append(node.text.strip())
        for child in node:
            tag = child.tag
            if tag == "Reference":
                ref_text = (child.text or "").strip()
                if ref_text:
                    parts.append(f"({ref_text})")
                if child.tail:
                    parts.append(child.tail.strip())
            else:
                collect(child)
                if child.tail:
                    parts.append(child.tail.strip())

    collect(label_elem)
    return " ".join(p for p in parts if p)


def get_preferred_label(cls_elem):
    """Return the text of the first <Rubric kind='preferred'> inside a Class."""
    for rubric in cls_elem.findall("Rubric"):
        if rubric.get("kind") == "preferred":
            return get_label_text(rubric.find("Label"))
    return ""


def get_rubric_items(cls_elem, kind):
    """
    Collect all <Rubric kind='{kind}'> entries from a Class element.
    Returns a list of non-empty text strings.
    """
    items = []
    for rubric in cls_elem.findall("Rubric"):
        if rubric.get("kind") != kind:
            continue
        label = rubric.find("Label")
        text = get_label_text(label).strip()
        if text:
            items.append(text)
    return items


def format_items(items):
    """Join a list of strings with ' | ' separator, or return '' if empty."""
    return " | ".join(items) if items else ""


def roman_to_int(s):
    """Convert a Roman numeral string to int (for sorting chapters numerically)."""
    val = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    result, prev = 0, 0
    for ch in reversed(s.upper()):
        v = val.get(ch, 0)
        result += v if v >= prev else -v
        prev = v
    return result


# ── main ──────────────────────────────────────────────────────────────────────

def parse_icd10_claml(xml_path: str, csv_path: str):
    print(f"Parsing {xml_path} ...")
    tree = ET.parse(xml_path)
    root = tree.getroot()

    # ── 1. Index all Class elements by code ──────────────────────────────────
    chapters   = {}   # code -> element
    blocks     = {}   # code -> element
    categories = {}   # code -> element

    for cls in root.iter("Class"):
        kind = cls.get("kind", "")
        code = cls.get("code", "")
        if kind == "chapter":
            chapters[code] = cls
        elif kind == "block":
            blocks[code] = cls
        elif kind == "category":
            categories[code] = cls

    print(f"  Found {len(chapters)} chapters, {len(blocks)} blocks, "
          f"{len(categories)} categories.")

    # ── 2. Parse Modifier definitions (shared subdivisions) ──────────────────
    # modifier_code -> list of ModifierClass elements
    modifier_classes = {}
    for mc in root.iter("ModifierClass"):
        mod_code = mc.get("modifier", "")
        if mod_code not in modifier_classes:
            modifier_classes[mod_code] = []
        modifier_classes[mod_code].append(mc)

    print(f"  Found {len(modifier_classes)} modifiers with "
          f"{sum(len(v) for v in modifier_classes.values())} modifier sub-classes.")

    # ── 3. Build parent map for blocks (block -> its SuperClass code) ─────────
    block_parent = {}
    for bcode, belem in blocks.items():
        sc = belem.find("SuperClass")
        if sc is not None:
            block_parent[bcode] = sc.get("code", "")

    def find_chapter_for_block(block_code):
        visited = set()
        current = block_code
        while current and current not in visited:
            visited.add(current)
            if current in chapters:
                return current
            parent = block_parent.get(current)
            if parent is None:
                break
            current = parent
        return None

    # ── 4. For each category, find its immediate block and chapter ────────────
    def find_block_and_chapter(cat_code):
        visited = set()
        current = cat_code
        while current and current not in visited:
            visited.add(current)
            c_elem = categories.get(current)
            elem = c_elem if c_elem is not None else blocks.get(current)
            if elem is None:
                break
            sc = elem.find("SuperClass")
            if sc is None:
                break
            parent_code = sc.get("code", "")

            if parent_code in blocks:
                chapter_code = find_chapter_for_block(parent_code)
                return parent_code, chapter_code or ""
            elif parent_code in chapters:
                return "", parent_code
            current = parent_code

        return "", ""

    # ── 5. Filter: only codes that start with a letter (A-Z / a-z) ───────────
    letter_re = re.compile(r'^[A-Za-z]')

    rows = []

    for cat_code, cat_elem in categories.items():
        if not letter_re.match(cat_code):
            continue

        code_desc = get_preferred_label(cat_elem)
        code_incl = format_items(get_rubric_items(cat_elem, "inclusion"))
        code_excl = format_items(get_rubric_items(cat_elem, "exclusion"))

        block_code, chap_code = find_block_and_chapter(cat_code)

        block_elem  = blocks.get(block_code)
        block_desc  = get_preferred_label(block_elem) if block_elem is not None else ""

        chap_elem   = chapters.get(chap_code)
        chap_desc   = get_preferred_label(chap_elem)  if chap_elem  is not None else ""
        chap_incl   = format_items(get_rubric_items(chap_elem, "inclusion")) if chap_elem is not None else ""
        chap_excl   = format_items(get_rubric_items(chap_elem, "exclusion")) if chap_elem is not None else ""

        # Check whether this category uses shared modifier subdivisions
        modified_by = cat_elem.find("ModifiedBy")

        if modified_by is not None:
            mod_code = modified_by.get("code", "")
            mc_list  = modifier_classes.get(mod_code, [])

            if mc_list:
                # Expand into one row per ModifierClass sub-code
                for mc in mc_list:
                    suffix = mc.get("code", "")   # e.g. ".0", ".1"

                    # Build the expanded code: base + suffix
                    # suffix already contains the dot for fourth-char sub-codes
                    expanded_code = cat_code + suffix

                    sub_desc = get_preferred_label(mc)
                    sub_incl = format_items(get_rubric_items(mc, "inclusion"))
                    sub_excl = format_items(get_rubric_items(mc, "exclusion"))

                    rows.append({
                        "icd10_code":           expanded_code,
                        "code_description":     sub_desc,
                        "code_includes":        sub_incl,
                        "code_excludes":        sub_excl,
                        "chapter":              chap_code,
                        "chapter_description":  chap_desc,
                        "chapter_includes":     chap_incl,
                        "chapter_excludes":     chap_excl,
                        "block_range":          block_code,
                        "block_description":    block_desc,
                    })

                # Also keep a row for the parent code itself (description only,
                # no sub-code suffix) so the 3-char code is still in the output
                rows.append({
                    "icd10_code":           cat_code,
                    "code_description":     code_desc,
                    "code_includes":        code_incl,
                    "code_excludes":        code_excl,
                    "chapter":              chap_code,
                    "chapter_description":  chap_desc,
                    "chapter_includes":     chap_incl,
                    "chapter_excludes":     chap_excl,
                    "block_range":          block_code,
                    "block_description":    block_desc,
                })
                continue   # already added rows, skip the plain append below

        # Normal category (no shared modifier) ─ single row
        rows.append({
            "icd10_code":           cat_code,
            "code_description":     code_desc,
            "code_includes":        code_incl,
            "code_excludes":        code_excl,
            "chapter":              chap_code,
            "chapter_description":  chap_desc,
            "chapter_includes":     chap_incl,
            "chapter_excludes":     chap_excl,
            "block_range":          block_code,
            "block_description":    block_desc,
        })

    # ── 6. Sort by chapter (numerically) then by ICD code ────────────────────
    rows.sort(key=lambda r: (
        roman_to_int(r["chapter"]) if r["chapter"] else 999,
        r["icd10_code"]
    ))

    # ── 7. Write CSV ──────────────────────────────────────────────────────────
    fieldnames = [
        "icd10_code",   "code_description",   "code_includes",   "code_excludes",
        "chapter",      "chapter_description", "chapter_includes", "chapter_excludes",
        "block_range",  "block_description",
    ]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"  Written {len(rows):,} rows -> {csv_path}")


if __name__ == "__main__":
    xml_path = sys.argv[1] if len(sys.argv) > 1 else "icd102019en.xml"
    csv_path = sys.argv[2] if len(sys.argv) > 2 else "icd10.csv"

    if not os.path.exists(xml_path):
        print(f"ERROR: File not found: {xml_path}")
        sys.exit(1)

    parse_icd10_claml(xml_path, csv_path)
    print("Done.")
