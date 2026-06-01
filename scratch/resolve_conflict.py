filepath = r"c:\Project\ClaimGPT\services\submission\app\main.py"
with open(filepath, "r", encoding="utf-8") as f:
    content = f.read()

# We can simply split the file by the markers.
# <<<<<<< HEAD is at the start
# ======= is in the middle
# >>>>>>> parser-coding-updates is at the end

start_marker = "<<<<<<< HEAD\n"
mid_marker = "\n=======\n"
end_marker = "\n>>>>>>> parser-coding-updates"

if start_marker in content and mid_marker in content and end_marker in content:
    # Find the indices
    start_idx = content.find(start_marker)
    mid_idx = content.find(mid_marker)
    end_idx = content.find(end_marker)
    
    # We want to replace the entire block from start_idx to end_idx + len(end_marker)
    # with the content in between mid_idx + len(mid_marker) and end_idx.
    part2 = content[mid_idx + len(mid_marker):end_idx]
    
    new_content = content[:start_idx] + part2 + content[end_idx + len(end_marker):]
    
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(new_content)
    print("Conflict successfully resolved using the parser-coding-updates version via string slice!")
else:
    print("Conflict markers not found or did not match string structure.")
