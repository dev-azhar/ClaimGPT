import os
import sys
import time
import glob
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

# Target directory containing batch documents
BATCH_DIR = r"C:\Users\Admin\Downloads\Batch1-100 2\Batch1-100"
API_URL = "http://127.0.0.1:8000/ingress/claims"
CONCURRENCY = 8  # Concurrency limit (number of simultaneous uploads to load-test gateways)

def upload_file(file_path):
    file_name = os.path.basename(file_path)
    print(f">> [Start] Uploading: {file_name} ...")
    start_time = time.perf_counter()
    try:
        with open(file_path, "rb") as f:
            files = {"files": (file_name, f, "application/octet-stream")}
            # Send the request to Nginx -> Gateway -> Ingress
            resp = requests.post(API_URL, files=files, timeout=60)
            
        elapsed = time.perf_counter() - start_time
        if resp.status_code in (200, 201, 202, 204):
            print(f"OK [Success] {file_name} uploaded in {elapsed:.2f}s (HTTP {resp.status_code})")
            return True, file_name, elapsed
        else:
            print(f"FAIL [Failed] {file_name} failed in {elapsed:.2f}s (HTTP {resp.status_code}): {resp.text}")
            return False, file_name, resp.status_code
    except Exception as e:
        elapsed = time.perf_counter() - start_time
        print(f"ERR [Error] {file_name} error in {elapsed:.2f}s: {e}")
        return False, file_name, str(e)

def main():
    if not os.path.exists(BATCH_DIR):
        print(f"Error: Directory not found: {BATCH_DIR}")
        sys.exit(1)
        
    # Gather all files in the directory
    # Supporting PDF, JPG, PNG, DOCX, etc.
    extensions = ("*.pdf", "*.jpg", "*.jpeg", "*.png", "*.tiff", "*.tif", "*.webp", "*.docx", "*.doc", "*.xlsx", "*.xls", "*.txt")
    files = []
    for ext in extensions:
        files.extend(glob.glob(os.path.join(BATCH_DIR, ext)))
        
    # Remove duplicates
    files = list(set(files))
    
    total_files = len(files)
    if total_files == 0:
        print(f"No documents found in {BATCH_DIR}")
        return

    print("=" * 60)
    print(f"ClaimGPT Batch Upload Load-Tester")
    print(f"Directory:    {BATCH_DIR}")
    print(f"Total Files:  {total_files}")
    print(f"Concurrency:  {CONCURRENCY} parallel uploads")
    print(f"Target API:   {API_URL}")
    print("=" * 60)
    
    start_time = time.perf_counter()
    success_count = 0
    fail_count = 0
    durations = []
    
    with ThreadPoolExecutor(max_workers=CONCURRENCY) as executor:
        futures = {executor.submit(upload_file, fp): fp for fp in files}
        
        for future in as_completed(futures):
            success, file_name, result = future.result()
            if success:
                success_count += 1
                durations.append(result)
            else:
                fail_count += 1
                
    total_elapsed = time.perf_counter() - start_time
    avg_duration = sum(durations) / len(durations) if durations else 0
    
    print("=" * 60)
    print("Batch Upload Summary")
    print("=" * 60)
    print(f"Total Uploads:     {total_files}")
    print(f"Success Count:     {success_count}")
    print(f"Failure Count:     {fail_count}")
    print(f"Total Time Taken:  {total_elapsed:.2f}s")
    print(f"Average Request:   {avg_duration:.2f}s")
    print(f"Upload Rate:       {success_count / total_elapsed:.2f} claims/second")
    print("=" * 60)
    print("Monitor the worker scaling in Flower: http://localhost:8000/flower/")
    print("=" * 60)

if __name__ == "__main__":
    main()
