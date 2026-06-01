import os
import filecmp
from pathlib import Path

path1 = Path("C:/Project/ClaimGPT/services")
path2 = Path("C:/Project/ClaimGPT-feature/services")

def compare_dirs(dir1, dir2, rel_path=""):
    d1 = dir1 / rel_path
    d2 = dir2 / rel_path
    
    if not d1.exists() or not d2.exists():
        print(f"Directory missing: {rel_path}")
        return
        
    cmp = filecmp.dircmp(d1, d2)
    
    if cmp.left_only:
        print(f"[{rel_path}] Only in current (docker) branch: {cmp.left_only}")
    if cmp.right_only:
        print(f"[{rel_path}] Only in feature (parser-coding-updates) branch: {cmp.right_only}")
    if cmp.diff_files:
        print(f"[{rel_path}] Files differ: {cmp.diff_files}")
        
    for sub in cmp.common_dirs:
        sub_rel = f"{rel_path}/{sub}" if rel_path else sub
        compare_dirs(dir1, dir2, sub_rel)

def main():
    print("Comparing services directories...")
    compare_dirs(path1, path2)

if __name__ == "__main__":
    main()
