#!/usr/bin/env python3
"""Fix corrupted sections in services/parser/app/main.py"""

with open('services/parser/app/main.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Fix the corrupted section
bad_block = '''                table_data.append(item)

                db.commit()
                return
) -> dict[str, Any]:
    return {'''

good_block = '''                table_data.append(item)

    return build_canonical_schema(form_data, table_data)


def _build_renderer_input(
    output: ParseOutput,
    ocr_pages: List[Dict[str, Any]],
    layout: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {'''

if bad_block in content:
    content = content.replace(bad_block, good_block)
    print("✓ Fixed corruption")
    with open('services/parser/app/main.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print("✓ Wrote corrected file")
else:
    print("✗ Could not find exact bad block")
    print("Trying alternative approach...")
    # Find and fix the orphaned db.commit() and return after table_data.append
    import re
    pattern = r'(\s+table_data\.append\(item\))\n+\s+(db\.commit\(\))\n+\s+(return)\n+\) -> dict\[str, Any\]:'
    replacement = r'\1\n\n    return build_canonical_schema(form_data, table_data)\n\n\ndef _build_renderer_input(\n    output: ParseOutput,\n    ocr_pages: List[Dict[str, Any]],\n    layout: dict[str, Any] | None = None,\n) -> dict[str, Any]:'
    
    content = re.sub(pattern, replacement, content)
    with open('services/parser/app/main.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print("✓ Applied regex fix")
