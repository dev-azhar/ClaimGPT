import os

# When True, semantic (LLM) expense rows are merged with geometry-backed
# normalized table/region rows so rows missed by the model are preserved.
MERGE_SEMANTIC_AND_HEURISTIC = False

# Similarity threshold for fuzzy description matching when merging (0-1).
MERGE_DESCRIPTION_SIMILARITY = float(os.getenv("PARSER_V2_MERGE_DESCRIPTION_SIMILARITY", "0.85"))

# Amount tolerance (absolute) when considering two amounts equal during merge.
MERGE_AMOUNT_TOLERANCE = float(os.getenv("PARSER_V2_MERGE_AMOUNT_TOLERANCE", "1.0"))
