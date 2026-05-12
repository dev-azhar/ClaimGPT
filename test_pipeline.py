import sys
import os

# Add project root to sys.path so services module is found
sys.path.append(os.path.dirname(__file__))

from services.parser_v2.pipeline import process_file

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_pipeline.py <path_to_json>")
        sys.exit(1)
        
    json_path = sys.argv[1]
    debug_dir = os.path.join(os.path.dirname(json_path), "debug")
    
    print(f"Processing: {json_path}")
    doc_data = process_file(json_path, debug_dir=debug_dir)
    print(f"Regions detected: {len(doc_data.regions)}")
    print(f"Tables reconstructed: {len(doc_data.tables)}")
    print(f"Output saved to: {debug_dir}")
