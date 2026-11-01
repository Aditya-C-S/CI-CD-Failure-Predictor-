import pandas as pd
from sklearn.metrics import roc_auc_score, average_precision_score
from pathlib import Path
import sys

sys.path.insert(0, ".")
from src.prediction.bilstm_inference import predict_bilstm

samples_dir = Path("data/samples/snapshots")
snapshot_files = list(samples_dir.rglob("*.txt"))

rows = []
for p in sorted(snapshot_files):
    rel = p.relative_to(samples_dir).parts
    family = rel[0]
    outcome = rel[1]
    y_true = 1 if outcome == "failure" else 0
    depth = int(p.stem.split("_pct")[-1])
    text = p.read_text(encoding="utf-8", errors="replace")
    
    res = predict_bilstm(text, visibility=depth)
    rows.append({
        "family": family,
        "outcome": outcome,
        "y_true": y_true,
        "depth": depth,
        "prob": res["failure_probability"],
        "words": len(text.split()),
    })

df = pd.DataFrame(rows)
print(f"Total samples: {len(df)}")

print("\n--- Empirical Performance on Available 112 Samples ---")
for d in [25, 50, 75, 100]:
    sub = df[df["depth"] == d]
    auc = roc_auc_score(sub["y_true"], sub["prob"]) if len(set(sub["y_true"])) > 1 else None
    prauc = average_precision_score(sub["y_true"], sub["prob"]) if len(set(sub["y_true"])) > 1 else None
    print(f"Depth {d}% (N={len(sub)}): ROC-AUC = {auc:.4f}, PR-AUC = {prauc:.4f}")
    print(f"   Success probs: min={sub[sub['y_true']==0]['prob'].min():.4f}, mean={sub[sub['y_true']==0]['prob'].mean():.4f}, max={sub[sub['y_true']==0]['prob'].max():.4f}")
    print(f"   Failure probs: min={sub[sub['y_true']==1]['prob'].min():.4f}, mean={sub[sub['y_true']==1]['prob'].mean():.4f}, max={sub[sub['y_true']==1]['prob'].max():.4f}")

overall_auc = roc_auc_score(df["y_true"], df["prob"])
overall_prauc = average_precision_score(df["y_true"], df["prob"])
print(f"\nOverall (112 samples): ROC-AUC = {overall_auc:.4f}, PR-AUC = {overall_prauc:.4f}")

