import hashlib
from pathlib import Path

def get_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()

fresh_dir = Path("scratch/audit_fresh_extract")
orig_dir = Path("models/bilstm/artifacts")
bilstm2_art = Path("models/bilstm2/artifacts")

files = [
    "models/task_a_champion.pt",
    "models/task_b_fold0_champion.pt",
    "models/task_b_fold1_champion.pt",
    "models/task_b_fold2_champion.pt",
    "models/task_b_fold3_champion.pt",
    "models/task_b_fold4_champion.pt",
    "work_data/cache/tokenizer.pkl",
    "final_test_results.csv",
    "test_per_class_breakdown.csv",
    "capstone_final_defense_report.md",
    "day_shift_complete_pipeline.py",
]

print(f"{'Relative File':<35} {'SHA-256 (Fresh Extracted)':<66} {'Matches Orig?':<16} {'Matches bilstm2/art?'}")
print("-" * 140)
for rel in files:
    fresh_p = fresh_dir / rel
    orig_p = orig_dir / rel
    b2_p = bilstm2_art / rel
    
    sha_fresh = get_sha256(fresh_p) if fresh_p.exists() else "MISSING"
    sha_orig = get_sha256(orig_p) if orig_p.exists() else "NOT_IN_ORIG"
    sha_b2 = get_sha256(b2_p) if b2_p.exists() else "NOT_IN_B2"
    
    match_orig = (sha_fresh == sha_orig) if sha_orig != "NOT_IN_ORIG" else "N/A (New)"
    match_b2 = (sha_fresh == sha_b2)
    print(f"{rel:<35} {sha_fresh:<66} {str(match_orig):<16} {match_b2}")

