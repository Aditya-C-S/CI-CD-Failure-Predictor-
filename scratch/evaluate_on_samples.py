"""
scratch/evaluate_on_samples.py - Offline evaluation of bilstm and bilstm2 on available snapshot samples
"""
import sys
import time
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score, precision_score, recall_score, f1_score,
    roc_auc_score, average_precision_score, confusion_matrix, brier_score_loss
)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.prediction.bilstm_inference import predict_bilstm
from src.prediction.bilstm2_inference import predict_bilstm2

samples_dir = Path("data/samples/snapshots")
snapshot_files = list(samples_dir.rglob("*.txt"))
print(f"Found {len(snapshot_files)} snapshot sample files.")

records = []
for p in sorted(snapshot_files):
    # Path format: data/samples/snapshots/<family>/<outcome>/<run_id>_pct<depth>.txt
    rel_parts = p.relative_to(samples_dir).parts
    family = rel_parts[0]
    outcome = rel_parts[1] # 'failure' or 'success'
    y_true = 1 if outcome == "failure" else 0

    # Extract depth from filename e.g. run_0001_pct025.txt -> 25
    depth_str = p.stem.split("_pct")[-1]
    depth = int(depth_str)

    text = p.read_text(encoding="utf-8", errors="replace")
    word_count = len(text.split())

    # Predict with BiLSTM 1
    t0 = time.perf_counter()
    res1 = predict_bilstm(text, visibility=depth)
    lat1 = (time.perf_counter() - t0) * 1000

    # Predict with BiLSTM 2
    t0 = time.perf_counter()
    res2 = predict_bilstm2(text, visibility=depth)
    lat2 = (time.perf_counter() - t0) * 1000

    records.append({
        "path": str(p),
        "family": family,
        "depth": depth,
        "outcome": outcome,
        "y_true": y_true,
        "word_count": word_count,
        "prob1": res1["failure_probability"],
        "pred1": res1["predicted_outcome"],
        "class1": res1["predicted_error_class"],
        "pad_pct1": res1["token_diagnostics"]["pad_pct"],
        "unk_pct1": res1["token_diagnostics"]["unk_pct"],
        "lat1": lat1,
        "prob2": res2["failure_probability"],
        "pred2": res2["predicted_outcome"],
        "class2": res2["predicted_error_class"],
        "pad_pct2": res2["token_diagnostics"]["pad_pct"],
        "unk_pct2": res2["token_diagnostics"]["unk_pct"],
        "lat2": lat2,
    })

df = pd.DataFrame(records)
print(f"Total evaluated records: {len(df)}")
print(f"Outcome balance: {df['outcome'].value_counts().to_dict()}")
print(f"Depth counts: {df['depth'].value_counts().to_dict()}")

def compute_metrics(y_true, probs, threshold=0.270):
    preds = (probs >= threshold).astype(int)
    cm = confusion_matrix(y_true, preds, labels=[0, 1])
    tn, fp, fn, tp = cm.ravel()
    fpr = fp / (fp + tn) if (fp + tn) > 0 else 0.0
    return {
        "accuracy": round(accuracy_score(y_true, preds), 4),
        "precision": round(precision_score(y_true, preds, zero_division=0), 4),
        "recall": round(recall_score(y_true, preds, zero_division=0), 4),
        "f1": round(f1_score(y_true, preds, zero_division=0), 4),
        "roc_auc": round(roc_auc_score(y_true, probs), 4) if len(set(y_true)) > 1 else None,
        "pr_auc": round(average_precision_score(y_true, probs), 4) if len(set(y_true)) > 1 else None,
        "brier": round(brier_score_loss(y_true, probs), 4),
        "fpr": round(fpr, 4),
        "tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp),
    }

print("\n=== Overall Metrics @ Operational Threshold 0.270 ===")
m1_op = compute_metrics(df["y_true"], df["prob1"], threshold=0.270)
m2_op = compute_metrics(df["y_true"], df["prob2"], threshold=0.270)
print("BiLSTM 1:", m1_op)
print("BiLSTM 2:", m2_op)

print("\n=== Overall Metrics @ Standard Threshold 0.500 ===")
m1_50 = compute_metrics(df["y_true"], df["prob1"], threshold=0.500)
m2_50 = compute_metrics(df["y_true"], df["prob2"], threshold=0.500)
print("BiLSTM 1:", m1_50)
print("BiLSTM 2:", m2_50)

print("\n=== Metrics by Depth Checkpoint @ Threshold 0.270 ===")
for d in [25, 50, 75, 100]:
    sub = df[df["depth"] == d]
    m1_d = compute_metrics(sub["y_true"], sub["prob1"], threshold=0.270)
    m2_d = compute_metrics(sub["y_true"], sub["prob2"], threshold=0.270)
    print(f"Depth {d}% (N={len(sub)}):")
    print(f"   BiLSTM 1: F1={m1_d['f1']}, Acc={m1_d['accuracy']}, Rec={m1_d['recall']}, Prec={m1_d['precision']}, FPR={m1_d['fpr']}, CM=[TN:{m1_d['tn']}, FP:{m1_d['fp']}, FN:{m1_d['fn']}, TP:{m1_d['tp']}]")
    print(f"   BiLSTM 2: F1={m2_d['f1']}, Acc={m2_d['accuracy']}, Rec={m2_d['recall']}, Prec={m2_d['precision']}, FPR={m2_d['fpr']}, CM=[TN:{m2_d['tn']}, FP:{m2_d['fp']}, FN:{m2_d['fn']}, TP:{m2_d['tp']}]")

print(f"\nAverage Latency: BiLSTM 1={df['lat1'].mean():.2f} ms, BiLSTM 2={df['lat2'].mean():.2f} ms")

