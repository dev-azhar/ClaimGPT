import logging
from typing import List
from .models import Token, Region, FormField
from .geometry_utils import group_tokens_into_lines, get_bbox

logger = logging.getLogger("parser-debug")

def extract_fields(region: Region) -> List[FormField]:
    """
    Extracts Key-Value pairs from a form region using pure geometry.
    Rule: Key is usually tokens ending in ':' or left-aligned tokens.
    Value is tokens to the right on the same line.
    """
    fields = []
    lines = group_tokens_into_lines(region.tokens)
    
    for line in lines:
        if not line:
            continue
            
        # Strategy: Find "Anchor" tokens (those ending with ':')
        for i, token in enumerate(line):
            text = token.text.strip()
            if text.endswith(":") and len(text) > 1:
                # Found a key
                key_text = text[:-1].strip()
                key_bbox = [token.x0, token.y0, token.x1, token.y1]
                
                # Search RIGHT for values
                value_tokens = []
                current_x = token.x1
                
                for next_token in line[i+1:]:
                    # Stop if we hit another colon (next key)
                    if next_token.text.strip().endswith(":"):
                        break
                    
                    # Stop if there's a huge gap (potentially unrelated data)
                    if next_token.x0 - current_x > 150.0:
                        break
                        
                    value_tokens.append(next_token)
                    current_x = next_token.x1
                
                if value_tokens:
                    value_text = " ".join(t.text for t in value_tokens).strip()
                    value_bbox = get_bbox(value_tokens)
                    
                    fields.append(FormField(
                        key=key_text,
                        value=value_text,
                        key_bbox=key_bbox,
                        value_bbox=value_bbox,
                        page=region.page
                    ))
                    
    return fields
