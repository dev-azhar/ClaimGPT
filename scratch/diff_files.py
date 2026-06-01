import sys
import difflib
from pathlib import Path

file_pairs = [
    ("services/parser_v2/pipeline.py", "services/parser_v2/pipeline.py"),
    ("services/parser_v2/semantic_backends.py", "services/parser_v2/semantic_backends.py"),
    ("services/parser_v2/semantic_extractor.py", "services/parser_v2/semantic_extractor.py"),
    ("services/parser_v2/document_processor.py", "services/parser_v2/document_processor.py"),
    ("services/parser/app/main.py", "services/parser/app/main.py"),
    ("services/parser/app/engine.py", "services/parser/app/engine.py"),
    ("services/parser/app/layout_analyzer.py", "services/parser/app/layout_analyzer.py"),
    ("services/ocr/app/engine.py", "services/ocr/app/engine.py"),
    ("services/ocr/app/main.py", "services/ocr/app/main.py"),
    ("services/shared_tasks.py", "services/shared_tasks.py"),
]

def print_diff(file_path):
    f1 = Path("C:/Project/ClaimGPT") / file_path
    f2 = Path("C:/Project/ClaimGPT-feature") / file_path
    
    if not f1.exists() or not f2.exists():
        print(f"Skipping {file_path} (does not exist in both)")
        return
        
    with open(f1, "r", encoding="utf-8", errors="ignore") as file1, open(f2, "r", encoding="utf-8", errors="ignore") as file2:
        diff = list(difflib.unified_diff(
            file2.readlines(),
            file1.readlines(),
            fromfile=f"parser-coding-updates:{file_path}",
            tofile=f"docker-branch:{file_path}",
            n=2
        ))
        
    if diff:
        print(f"\n=========================================")
        print(f"DIFF FOR {file_path} (Lines count: {len(diff)})")
        print(f"=========================================")
        # Print up to 100 lines of diff
        for line in diff[:100]:
            print(line, end="")
        if len(diff) > 100:
            print(f"\n... Diff truncated ({len(diff) - 100} more lines)")
    else:
        print(f"No difference in {file_path}")

def main():
    for f in file_pairs:
        print_diff(f[0])

if __name__ == "__main__":
    main()
