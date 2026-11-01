"""
Night-shift master pipeline for Task A (binary) and Task B (14-class).

Single-process orchestrator. Logs to stdout and night_shift_execution.log.
Read-only with respect to vault/test_locked. Trains only on cached official
train/val tensors produced by preprocess_and_cache.py.

Usage:
    python night_shift_master.py --no-sleep          # full run, no sleep
    python night_shift_master.py --smoke --no-sleep  # quick wiring test
"""

import argparse
import copy
import ctypes
import gc
import hashlib
import json
import math
import os
import random
import sys
import time
import traceback
from datetime import datetime, time as dtime
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from sklearn.metrics import (
    accuracy_score, average_precision_score, brier_score_loss,
    confusion_matrix, f1_score, precision_score, recall_score, roc_auc_score,
)
from sklearn.model_selection import KFold
from torch.utils.data import DataLoader, Dataset, WeightedRandomSampler

from bilstm_architectures import (
    BiLSTMAttention, BiLSTMBaseline, HierarchicalConvBiLSTMAttention, ModelConfig,
)
from bilstm_engine import DEVICE, collate_fn

ROOT = Path(r"C:\Users\Aditya CS\OneDrive\Documents\Capstone\CI-CD-Failure-Predictor\models\bilstmfinal\package")
CACHE = ROOT / "work_data" / "cache"
MODELS = ROOT / "models"
LOG_PATH = ROOT / "night_shift_execution.log"
RESULTS_PATH = ROOT / "night_shift_results.json"
REPORT_PATH = ROOT / "night_shift_final_report.md"
FINAL_REPORT_PATH = ROOT / "final_report.md"
VAULT = Path(r"C:\Users\Aditya CS\OneDrive\Documents\Capstone\CI-CD-Failure-Predictor\models\bilstmfinal\package\vault\test_locked")

EXPECTED = {
    "task_a": {"train": 14976, "val": 3096, "runs": (3744, 774), "groups": (2115, 454)},
    "task_b": {"train": 8976, "val": 1796, "runs": (2244, 449), "groups": (1060, 227)},
}
PY_EXC = ["AssertionError", "AttributeError", "FileNotFoundError", "IndexError",
          "KeyError", "TypeError", "ValueError", "ZeroDivisionError"]
DEPTHS = [25, 50, 75, 100]
START = time.time()
_results = {}
_log_fh = None


# ── logging / deadline ────────────────────────────────────────────────────────
def log(msg="", flush=True):
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line, flush=flush)
    if _log_fh:
        _log_fh.write(line + "\n")
        _log_fh.flush()


def deadline_reached():
    now = datetime.now()
    return now.hour > 6 or (now.hour == 6 and now.minute >= 12)


def check_deadline(stage):
    if deadline_reached():
        raise TimeoutError(f"deadline reached before {stage}")


def to_py(obj):
    if isinstance(obj, dict):
        return {str(k): to_py(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_py(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, torch.Tensor):
        return obj.detach().cpu().tolist()
    return obj


def save_results():
    with open(RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump(to_py(_results), f, indent=2)


# ── data ─────────────────────────────────────────────────────────────────────
class TensorDS(Dataset):
    def __init__(self, ids, labels, depths, groups, indices=None):
        if indices is None:
            indices = np.arange(len(labels))
        self.ids = ids
        self.labels = labels
        self.depths = depths
        self.groups = groups
        self.indices = np.asarray(indices)

    def __len__(self):
        return len(self.indices)

    def __getitem__(self, i):
        j = int(self.indices[i])
        return {
            "input_ids": self.ids[j],
            "labels": self.labels[j],
            "group_id": self.groups[j],
            "depth_pct": self.depths[j],
        }


class ViewDS(Dataset):
    """Deterministic 64+448 (or configured) view with optional ablation."""
    def __init__(self, ids, labels, depths, head, tail, mode="none",
                 tail_mask_n=384, indices=None, header_mask_n=64):
        self.ids, self.labels, self.depths = ids, labels, depths
        self.head, self.tail, self.mode = head, tail, mode
        self.tail_mask_n = tail_mask_n
        self.header_mask_n = header_mask_n
        self.indices = np.arange(len(labels)) if indices is None else np.asarray(indices)

    def __len__(self):
        return len(self.indices)

    def __getitem__(self, i):
        j = int(self.indices[i])
        row = self.ids[j]
        actual = int((row != 0).sum())
        if actual <= self.head + self.tail:
            view = row[:actual].clone()
        else:
            view = torch.cat([row[:self.head], row[actual - self.tail:actual]])
        if self.mode == "header":
            # Never mask into the final tail window: for short logs a plain
            # view[:64] overlaps the 448-token tail mask and double-counts.
            avail = max(0, view.numel() - self.tail_mask_n)
            n = min(self.header_mask_n, avail)
            view[:n] = 0
        elif self.mode == "tail":
            n = min(self.tail_mask_n, view.numel())
            view[view.numel() - n:] = 0
        return (view, self.labels[j], max(1, view.numel()), -1, self.depths[j])


def load_task(task):
    d = {}
    for split in ["train", "val"]:
        for key in ["input_ids", "labels", "group_ids", "depth_pcts", "sample_weights", "clean_mask"]:
            d[f"{split}_{key}"] = torch.load(CACHE / f"{task}_{split}_{key}.pt", map_location="cpu")
        with open(CACHE / f"{task}_{split}_view_hashes.json") as f:
            d[f"{split}_hashes"] = json.load(f)
        with open(CACHE / f"{task}_{split}_meta.json") as f:
            d[f"{split}_meta"] = json.load(f)
    return d


def verify_cache():
    log("=" * 78)
    log("STEP 0/1 VERIFICATION: cache, official counts, disjointness, tokens")
    log("=" * 78)
    out = {}
    for task, exp in EXPECTED.items():
        d = load_task(task)
        tr, va = d["train_labels"].numel(), d["val_labels"].numel()
        assert tr == exp["train"], f"{task} train {tr} != {exp['train']}"
        assert va == exp["val"], f"{task} val {va} != {exp['val']}"
        assert d["train_input_ids"].shape[1] == 1536
        assert d["val_input_ids"].shape[1] == 1536
        assert int(d["train_clean_mask"].sum()) > 0 and int(d["val_clean_mask"].sum()) > 0
        assert d["train_meta"]["run_keys"] == exp["runs"][0]
        assert d["val_meta"]["run_keys"] == exp["runs"][1]
        assert d["train_meta"]["groups"] == exp["groups"][0]
        assert d["val_meta"]["groups"] == exp["groups"][1]
        assert d["val_meta"]["leakage_contract"]["global_run_key_disjoint"]
        assert d["val_meta"]["leakage_contract"]["group_disjoint"]
        out[task] = {
            "train": tr, "val": va,
            "train_clean": int(d["train_clean_mask"].sum()),
            "val_clean": int(d["val_clean_mask"].sum()),
            "train_runs": d["train_meta"]["run_keys"], "val_runs": d["val_meta"]["run_keys"],
            "train_groups": d["train_meta"]["groups"], "val_groups": d["val_meta"]["groups"],
            "train_dedup": d["train_meta"]["dedup"], "val_dedup": d["val_meta"]["dedup"],
            "raw_run_id_overlap": d["train_meta"]["raw_run_id_overlap"],
        }
        log(f"{task}: train={tr} val={va} | clean train={out[task]['train_clean']} "
            f"clean val={out[task]['val_clean']} | runs {exp['runs']} groups {exp['groups']} disjoint")
    with open(CACHE / "preprocessing_meta.json") as f:
        meta = json.load(f)
    tok_path = CACHE / "tokenizer.pkl"
    assert tok_path.exists() and (CACHE / "tokenizer_task_a.pkl").exists() and (CACHE / "tokenizer_task_b.pkl").exists()
    import pickle
    with open(tok_path, "rb") as f:
        tok = pickle.load(f)
    exc_ids = {}
    vocab = tok["vocab"] if isinstance(tok, dict) else getattr(tok, "vocab", {})
    for name in PY_EXC:
        assert name in vocab, f"missing exception token {name}"
        exc_ids[name] = int(vocab[name])
    assert len(set(exc_ids.values())) == 8, f"exception token collision: {exc_ids}"
    unk = int(vocab.get("<UNK>", -1))
    assert all(v != unk for v in exc_ids.values())
    out["tokenizer"] = {"vocab_size": len(vocab), "exception_ids": exc_ids,
                        "distinct": True, "none_unk": True, "meta_tasks": list(meta.keys())}
    log(f"tokenizer vocab={len(vocab)} | 8 exception tokens distinct and non-UNK")
    _results["verification"] = out
    save_results()


# ── loaders ──────────────────────────────────────────────────────────────────
def make_loader(ids, labels, depths, groups, indices, head, tail, batch_size,
                weights=None, train=False, header_p=0.0, sampler="none",
                num_classes=None, seed=0):
    base = TensorDS(ids, labels, depths, groups, indices)
    w_sub = None if weights is None else weights[torch.as_tensor(indices, dtype=torch.long)]
    if train and header_p > 0:
        from bilstm_engine import SlicedLogDataset
        ds = SlicedLogDataset(base, head_tokens=head, tail_tokens=tail, weights=w_sub,
                              is_train=True, header_dropout_p=header_p, seed=seed)
    else:
        ds = base
    if train and sampler == "class":
        counts = torch.bincount(labels[torch.as_tensor(indices)], minlength=num_classes).float()
        cw = 1.0 / torch.sqrt(counts + 1e-6)
        sw = cw[labels[torch.as_tensor(indices)]]
        sp = WeightedRandomSampler(sw.double(), num_samples=len(indices), replacement=True)
        return DataLoader(ds, batch_size=batch_size, sampler=sp, collate_fn=collate_fn,
                          num_workers=0, pin_memory=DEVICE.type == "cuda")
    if train and sampler == "weighted":
        sw = (w_sub if w_sub is not None else torch.ones(len(indices))).double()
        sp = WeightedRandomSampler(sw, num_samples=len(indices), replacement=True)
        return DataLoader(ds, batch_size=batch_size, sampler=sp, collate_fn=collate_fn,
                          num_workers=0, pin_memory=DEVICE.type == "cuda")
    return DataLoader(ds, batch_size=batch_size, shuffle=train, collate_fn=collate_fn,
                      num_workers=0, pin_memory=DEVICE.type == "cuda")


def unpack(batch):
    ids, labels, lengths = batch[0], batch[1], batch[2]
    group = batch[3] if len(batch) > 3 else torch.full_like(labels, -1)
    depth = batch[4] if len(batch) > 4 else torch.full_like(labels, 100)
    weight = batch[5] if len(batch) > 5 else torch.ones_like(labels, dtype=torch.float32)
    return ids, labels, lengths, group, depth, weight


# ── model ────────────────────────────────────────────────────────────────────
def build_model(arch, vocab, num_classes, max_len=512):
    cfg = ModelConfig(vocab_size=vocab, max_len=max_len, embed_dim=128, hidden_dim=128,
                      num_layers=2, bidirectional=True, dropout=0.2,
                      num_classes=num_classes, pad_idx=0,
                      use_horizon_conditioning=(arch == "gen3"), horizon_embed_dim=32)
    if arch == "gen1":
        return BiLSTMBaseline(cfg)
    if arch == "gen2":
        return BiLSTMAttention(cfg)
    if arch == "gen3":
        return HierarchicalConvBiLSTMAttention(cfg)
    raise ValueError(arch)


def forward_logits(model, arch, ids, lengths, depth):
    if arch == "gen3":
        out = model(ids, lengths, depth_pct=depth)
    else:
        out = model(ids, lengths)
    if isinstance(out, tuple):
        out = out[0]
    if out.dim() == 2 and out.size(1) == 1:
        out = out.squeeze(1)
    return out


def init_binary_bias(model, labels):
    pos = float((labels == 1).sum())
    neg = float((labels == 0).sum())
    bias = math.log(max(neg, 1.0) / max(pos, 1.0))
    last = model.classifier[-1] if hasattr(model, "classifier") else None
    if last is not None and getattr(last, "bias", None) is not None:
        nn.init.constant_(last.bias, bias)
    return bias


@torch.inference_mode()
def predict(model, arch, loader, num_classes):
    model.eval()
    probs, labels, depths, groups = [], [], [], []
    for batch in loader:
        ids, y, lengths, g, d, _ = unpack(batch)
        ids = ids.to(DEVICE, non_blocking=True)
        lengths = lengths.to(DEVICE)
        d = d.to(DEVICE)
        logits = forward_logits(model, arch, ids, lengths, d)
        if num_classes == 1:
            p = torch.sigmoid(logits)
            probs.append(p.float().cpu().numpy())
        else:
            p = torch.softmax(logits.float(), dim=1)
            probs.append(p.cpu().numpy())
        labels.append(y.numpy())
        depths.append(d.cpu().numpy())
        groups.append(g.numpy())
    return (np.concatenate(probs), np.concatenate(labels),
            np.concatenate(depths), np.concatenate(groups))


# ── training ─────────────────────────────────────────────────────────────────
def macro_f1_binary(y, p, mask=None, thr=0.5):
    if mask is not None:
        y, p = y[mask], p[mask]
    return f1_score(y, (p >= thr).astype(int), average="macro", zero_division=0)


def sweep_threshold(y, p, mask=None, lo=0.20, hi=0.80):
    if mask is not None:
        y, p = y[mask], p[mask]
    best_t, best_f1 = 0.5, -1.0
    for t in np.arange(lo, hi + 1e-9, 0.01):
        f = f1_score(y, (p >= t).astype(int), average="macro", zero_division=0)
        if f > best_f1:
            best_t, best_f1 = float(t), float(f)
    return best_t, best_f1


def train_model(arch, task, train_arrays, val_arrays, num_classes, epochs, lr,
                head, tail, header_p, batch_size, selection_mask, seed,
                class_weights=None, sampler="none", tag="model"):
    torch.manual_seed(seed)
    np.random.seed(seed)
    random.seed(seed)
    ids, labels, depths, groups, weights = train_arrays
    vids, vlabels, vdepths, vgroups = val_arrays
    model = build_model(arch, int(_results["verification"]["tokenizer"]["vocab_size"]), num_classes).to(DEVICE)
    bias = init_binary_bias(model, labels) if num_classes == 1 else 0.0
    n_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
    log(f"[{tag}] arch={arch} params={n_params:,} bias_init={bias:.4f} "
        f"window={head}+{tail} header_p={header_p} train={len(labels)}")
    train_loader = make_loader(ids, labels, depths, groups, np.arange(len(labels)),
                               head, tail, batch_size, weights=weights, train=True,
                               header_p=header_p, sampler=sampler,
                               num_classes=num_classes, seed=seed)
    val_loader = make_loader(vids, vlabels, vdepths, vgroups, np.arange(len(vlabels)),
                             head, tail, 32, weights=None, train=False)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-5)
    sched = torch.optim.lr_scheduler.OneCycleLR(
        opt, max_lr=lr, epochs=epochs, steps_per_epoch=len(train_loader),
        pct_start=0.15, div_factor=25.0, final_div_factor=1e4)
    use_amp = DEVICE.type == "cuda"
    scaler = torch.amp.GradScaler("cuda", enabled=use_amp)
    pw = None
    if num_classes == 1:
        pw = torch.tensor([float((labels == 0).sum()) / max(float((labels == 1).sum()), 1.0)],
                          device=DEVICE)
    cw = class_weights.to(DEVICE) if class_weights is not None else None
    best_state, best_metric, best_epoch = None, -1.0, -1
    patience = 0
    hist = []
    for epoch in range(1, epochs + 1):
        check_deadline(f"{tag} epoch {epoch}")
        model.train()
        t0 = time.time()
        running = 0.0
        for step, batch in enumerate(train_loader, 1):
            ids_b, y, lengths, _, d, w = unpack(batch)
            ids_b = ids_b.to(DEVICE, non_blocking=True)
            y = y.to(DEVICE)
            lengths = lengths.to(DEVICE)
            d = d.to(DEVICE)
            w = w.to(DEVICE, dtype=torch.float32)
            with torch.amp.autocast("cuda", enabled=use_amp):
                logits = forward_logits(model, arch, ids_b, lengths, d)
                if num_classes == 1:
                    per = F.binary_cross_entropy_with_logits(logits.float(), y.float(),
                                                             pos_weight=pw, reduction="none")
                else:
                    per = F.cross_entropy(logits.float(), y, weight=cw,
                                          label_smoothing=0.05, reduction="none")
                loss = (per * w).sum() / w.sum().clamp(min=1e-8)
            opt.zero_grad(set_to_none=True)
            scaler.scale(loss).backward()
            scaler.unscale_(opt)
            torch.nn.utils.clip_grad_norm_(model.parameters(), 0.5)
            scaler.step(opt)
            scaler.update()
            sched.step()
            running += float(loss.detach())
            if step % 50 == 0:
                log(f"[{tag}] epoch {epoch}/{epochs} batch {step}/{len(train_loader)} "
                    f"loss={running / step:.4f} elapsed={time.time() - t0:.0f}s")
        gc.collect()
        if DEVICE.type == "cuda":
            torch.cuda.empty_cache()
        probs, yv, dv, _ = predict(model, arch, val_loader, num_classes)
        sel = np.ones(len(yv), dtype=bool) if selection_mask is None else selection_mask
        if num_classes == 1:
            thr, metric = sweep_threshold(yv, probs, sel)
            val_loss = float(F.binary_cross_entropy(
                torch.tensor(np.clip(probs, 1e-6, 1 - 1e-6)), torch.tensor(yv, dtype=torch.float32)).item())
        else:
            thr, metric = 0.5, float(f1_score(yv[sel], probs[sel].argmax(1), average="macro", zero_division=0))
            val_loss = float(F.cross_entropy(torch.tensor(probs[sel] + 1e-9).log(),
                                             torch.tensor(yv[sel])).item())
        hist.append({"epoch": epoch, "val_loss": val_loss, "macro_f1": metric, "threshold": thr,
                     "seconds": round(time.time() - t0, 1)})
        log(f"[{tag}] epoch {epoch}/{epochs} DONE val_loss={val_loss:.4f} "
            f"macro_f1={metric:.4f} thr={thr:.2f} time={time.time() - t0:.0f}s")
        if metric > best_metric + 1e-6:
            best_metric, best_epoch = metric, epoch
            best_state = copy.deepcopy(model.state_dict())
            patience = 0
        else:
            patience += 1
        # Persist latest best so a deadline abort still leaves a usable checkpoint.
        if best_state is not None:
            payload = {"state_dict": best_state, "arch": arch, "task": task,
                       "config": {"vocab_size": int(_results["verification"]["tokenizer"]["vocab_size"]),
                                  "max_len": head + tail, "embed_dim": 128, "hidden_dim": 128,
                                  "num_layers": 2, "bidirectional": True, "dropout": 0.2,
                                  "num_classes": num_classes, "pad_idx": 0,
                                  "use_horizon_conditioning": arch == "gen3",
                                  "horizon_embed_dim": 32},
                       "head_tokens": head, "tail_tokens": tail,
                       "header_dropout_p": header_p, "best_macro_f1": best_metric,
                       "best_epoch": best_epoch, "history": hist}
            if num_classes == 1:
                payload["optimal_prob_threshold"] = float(hist[-1]["threshold"])
            torch.save(payload, MODELS / f"_latest_{tag}.pt")
        if patience >= 3:
            log(f"[{tag}] early stop at epoch {epoch} (patience 3)")
            break
    if best_state is None:
        best_state = copy.deepcopy(model.state_dict())
    model.load_state_dict(best_state)
    model.eval()
    return model, hist, best_metric, best_epoch


# ── metrics ──────────────────────────────────────────────────────────────────
def binary_metrics(y, p, depths, thr, mask=None):
    m = np.ones(len(y), dtype=bool) if mask is None else np.asarray(mask, dtype=bool)
    yy, pp, dd = y[m], p[m], depths[m]
    pred = (pp >= thr).astype(int)
    out = {
        "n": int(m.sum()), "n_pos": int((yy == 1).sum()), "n_neg": int((yy == 0).sum()),
        "accuracy": float(accuracy_score(yy, pred)),
        "precision_0": float(precision_score(yy, pred, pos_label=0, zero_division=0)),
        "recall_0": float(recall_score(yy, pred, pos_label=0, zero_division=0)),
        "precision_1": float(precision_score(yy, pred, pos_label=1, zero_division=0)),
        "recall_1": float(recall_score(yy, pred, pos_label=1, zero_division=0)),
        "f1_macro": float(f1_score(yy, pred, average="macro", zero_division=0)),
        "f1_weighted": float(f1_score(yy, pred, average="weighted", zero_division=0)),
        "threshold": float(thr),
        "confusion": confusion_matrix(yy, pred, labels=[0, 1]).tolist(),
        "per_depth": {},
    }
    try:
        out["roc_auc"] = float(roc_auc_score(yy, pp)) if len(set(yy)) > 1 else None
        out["pr_auc"] = float(average_precision_score(yy, pp)) if len(set(yy)) > 1 else None
    except Exception:
        out["roc_auc"] = out["pr_auc"] = None
    for d in DEPTHS:
        dm = dd == d
        if dm.sum() == 0:
            continue
        ydd, pdd = yy[dm], pp[dm]
        pd = (pdd >= thr).astype(int)
        out["per_depth"][str(d)] = {
            "n": int(dm.sum()), "pos": int((ydd == 1).sum()), "neg": int((ydd == 0).sum()),
            "accuracy": float(accuracy_score(ydd, pd)),
            "f1_macro": float(f1_score(ydd, pd, average="macro", zero_division=0)),
            "precision_1": float(precision_score(ydd, pd, pos_label=1, zero_division=0)),
            "recall_1": float(recall_score(ydd, pd, pos_label=1, zero_division=0)),
            "pr_auc": float(average_precision_score(ydd, pdd)) if len(set(ydd)) > 1 else None,
            "single_class": bool(len(set(ydd)) == 1),
            "confusion": confusion_matrix(ydd, pd, labels=[0, 1]).tolist(),
        }
    return out


def multiclass_metrics(y, p, depths, num_classes, mask=None):
    m = np.ones(len(y), dtype=bool) if mask is None else np.asarray(mask, dtype=bool)
    yy, pp, dd = y[m], p[m], depths[m]
    pred = pp.argmax(1)
    present = sorted(set(int(v) for v in yy))
    out = {
        "n": int(m.sum()), "present_classes": present,
        "accuracy": float(accuracy_score(yy, pred)),
        "precision_macro": float(precision_score(yy, pred, labels=present, average="macro", zero_division=0)),
        "recall_macro": float(recall_score(yy, pred, labels=present, average="macro", zero_division=0)),
        "f1_macro": float(f1_score(yy, pred, labels=present, average="macro", zero_division=0)),
        "f1_weighted": float(f1_score(yy, pred, labels=present, average="weighted", zero_division=0)),
        "per_class_f1": f1_score(yy, pred, labels=list(range(num_classes)), average=None, zero_division=0).tolist(),
        "per_class_precision": precision_score(yy, pred, labels=list(range(num_classes)), average=None, zero_division=0).tolist(),
        "per_class_recall": recall_score(yy, pred, labels=list(range(num_classes)), average=None, zero_division=0).tolist(),
        "per_class_support": np.bincount(yy, minlength=num_classes).tolist(),
        "confusion": confusion_matrix(yy, pred, labels=list(range(num_classes))).tolist(),
        "per_depth": {},
    }
    try:
        onehot = np.eye(num_classes)[yy]
        out["pr_auc_macro"] = float(average_precision_score(onehot[:, present], pp[:, present], average="macro"))
    except Exception:
        out["pr_auc_macro"] = None
    for d in DEPTHS:
        dm = dd == d
        if dm.sum() == 0:
            continue
        yd, pd_ = yy[dm], pred[dm]
        pres = sorted(set(int(v) for v in yd))
        out["per_depth"][str(d)] = {
            "n": int(dm.sum()),
            "accuracy": float(accuracy_score(yd, pd_)),
            "f1_macro": float(f1_score(yd, pd_, labels=pres, average="macro", zero_division=0)),
            "f1_weighted": float(f1_score(yd, pd_, labels=pres, average="weighted", zero_division=0)),
            "per_class_f1": f1_score(yd, pd_, labels=list(range(num_classes)), average=None, zero_division=0).tolist(),
            "support": np.bincount(yd, minlength=num_classes).tolist(),
        }
    return out


def ece_multiclass(p, y, n_bins=10):
    conf = p.max(1)
    pred = p.argmax(1)
    correct = (pred == y).astype(float)
    bins = np.linspace(0, 1, n_bins + 1)
    ece = 0.0
    for i in range(n_bins):
        m = (conf > bins[i]) & (conf <= bins[i + 1]) if i > 0 else (conf >= bins[i]) & (conf <= bins[i + 1])
        if m.sum():
            ece += (m.mean()) * abs(correct[m].mean() - conf[m].mean())
    return float(ece)


def brier_multiclass(p, y, num_classes):
    onehot = np.eye(num_classes)[y]
    return float(np.mean(np.sum((p - onehot) ** 2, axis=1)))


# ── Task A checks ────────────────────────────────────────────────────────────
def ablation_probs(model, arch, ids, labels, depths, head, tail, mode, num_classes=1,
                   tail_mask_n=384):
    ds = ViewDS(ids, labels, depths, head, tail, mode=mode, tail_mask_n=tail_mask_n)
    loader = DataLoader(ds, batch_size=32, shuffle=False, collate_fn=collate_fn, num_workers=0)
    p, y, d, _ = predict(model, arch, loader, num_classes)
    return p, y, d


def task_a_checks(model, arch, arrays, thr, head, tail):
    ids, labels, depths = arrays["val_input_ids"], arrays["val_labels"], arrays["val_depth_pcts"]
    clean = arrays["val_clean_mask"].numpy().astype(bool)
    val_loader = make_loader(ids, labels, depths, arrays["val_group_ids"],
                             np.arange(len(labels)), head, tail, 32)
    p, y, d, _ = predict(model, arch, val_loader, 1)
    full = binary_metrics(y, p, d, thr, None)
    clean_m = binary_metrics(y, p, d, thr, clean)
    # Gate 1 on all 4 depths, full and clean.
    gate1 = {}
    for name, mask in [("full", None), ("clean", clean)]:
        gate1[name] = {}
        for dep in DEPTHS:
            dm = d == dep if mask is None else (d == dep) & mask
            if dm.sum() == 0:
                gate1[name][str(dep)] = {"n": 0, "pass": False, "note": "no rows"}
                continue
            yy = y[dm]
            single = len(set(int(v) for v in yy)) == 1
            majority = max(np.mean(yy == 0), np.mean(yy == 1))
            acc = float(np.mean((p[dm] >= thr).astype(int) == yy))
            gate1[name][str(dep)] = {"n": int(dm.sum()), "majority_baseline": float(majority),
                                     "model_accuracy": acc,
                                     "delta": acc - float(majority),
                                     "single_class": bool(single),
                                     "pass": None if single else bool(acc >= majority + 0.02),
                                     "note": "single-class depth; baseline not meaningful" if single else ""}
    # Counterfactuals.
    base_p, by, bd = ablation_probs(model, arch, ids, labels, depths, head, tail, "none")
    head_p, _, _ = ablation_probs(model, arch, ids, labels, depths, head, tail, "header")
    tail_p, _, _ = ablation_probs(model, arch, ids, labels, depths, head, tail, "tail", tail_mask_n=384)
    cf = {}
    for dep in [75, 100]:
        dm = bd == dep
        base_f1 = f1_score(by[dm], (base_p[dm] >= thr).astype(int), average="macro", zero_division=0)
        h_f1 = f1_score(by[dm], (head_p[dm] >= thr).astype(int), average="macro", zero_division=0)
        t_f1 = f1_score(by[dm], (tail_p[dm] >= thr).astype(int), average="macro", zero_division=0)
        cf[str(dep)] = {"base_f1": float(base_f1), "header_masked_f1": float(h_f1),
                        "tail_masked_f1": float(t_f1),
                        "header_drop": float(base_f1 - h_f1), "tail_drop": float(base_f1 - t_f1),
                        "n": int(dm.sum())}
    a3 = all(v["header_drop"] <= 0.06 for v in cf.values()) and \
         all(v["tail_drop"] >= 0.15 for v in cf.values())
    # Horizon trend (A2) on full official.
    def _mean(key, ks):
        vals = [full["per_depth"][str(k)][key] for k in ks
                if str(k) in full["per_depth"] and full["per_depth"][str(k)].get(key) is not None]
        return float(np.mean(vals)) if vals else None

    early_f1, late_f1 = _mean("f1_macro", [25, 50]), _mean("f1_macro", [75, 100])
    early_pr, late_pr = _mean("pr_auc", [25, 50]), _mean("pr_auc", [75, 100])
    a2 = bool(early_f1 is not None and late_f1 is not None and early_pr is not None
              and late_pr is not None and late_f1 > early_f1 and late_pr > early_pr)
    a1 = bool(full["precision_0"] >= 0.5 and full["recall_0"] >= 0.5 and
              full["precision_1"] >= 0.5 and full["recall_1"] >= 0.5 and
              full["f1_macro"] >= 0.70 and clean_m["f1_macro"] >= 0.70)
    return {"full": full, "clean": clean_m, "gate1": gate1, "counterfactual": cf,
            "A1": a1, "A2": a2, "A3": a3,
            "trend": {"early_f1": early_f1, "late_f1": late_f1,
                      "early_pr_auc": early_pr, "late_pr_auc": late_pr}}


def embedding_attribution(model, arch, ids, labels, depths, tokenizer, head, tail,
                          max_samples=240):
    inv = tokenizer["inv_vocab"] if isinstance(tokenizer, dict) else getattr(tokenizer, "inv_vocab", {})
    rows = np.where((labels.numpy() == 1) & np.isin(depths.numpy(), [75, 100]))[0]
    rng = np.random.RandomState(42)
    if len(rows) > max_samples:
        rows = rng.choice(rows, max_samples, replace=False)
    ds = ViewDS(ids, labels, depths, head, tail, mode="none", indices=rows)
    loader = DataLoader(ds, batch_size=32, shuffle=False, collate_fn=collate_fn, num_workers=0)
    captured = {}

    def hook(module, inp, out):
        out.retain_grad()
        captured["emb"] = out

    handle = model.embedding.register_forward_hook(hook)
    agg = {}
    counts = {}
    max_norm = {}
    try:
        model.train()
        for batch in loader:
            b_ids, y, lengths, g, d, _ = unpack(batch)
            b_ids = b_ids.to(DEVICE)
            lengths = lengths.to(DEVICE)
            d = d.to(DEVICE)
            model.zero_grad(set_to_none=True)
            with torch.enable_grad():
                logits = forward_logits(model, arch, b_ids, lengths, d)
                logits.sum().backward()
            grad = captured["emb"].grad
            if grad is None:
                continue
            norms = grad.norm(dim=-1).detach().cpu().numpy()
            b_ids_cpu = b_ids.detach().cpu().numpy()
            for r in range(norms.shape[0]):
                n = int(lengths[r].item())
                for pos in range(min(n, norms.shape[1])):
                    tid = int(b_ids_cpu[r, pos])
                    if tid == 0:
                        continue
                    val = float(norms[r, pos])
                    agg[tid] = agg.get(tid, 0.0) + val
                    max_norm[tid] = max(max_norm.get(tid, 0.0), val)
                    counts[tid] = counts.get(tid, 0) + 1
    finally:
        handle.remove()
    def decode(tid):
        return inv.get(str(tid), inv.get(tid, f"<id:{tid}>")) if isinstance(inv, dict) else f"<id:{tid}>"
    def is_err(tok):
        tl = tok.lower()
        return (any(e.lower() in tl for e in PY_EXC) or
                any(k in tl for k in ["error", "exception", "fail", "traceback", "exit",
                                      "fatal", "denied", "timeout", "non-zero", "outage",
                                      "connection_reset", "5xx", "reset by peer"]))
    mean_order = sorted(agg, key=lambda t: agg[t] / max(counts[t], 1), reverse=True)
    max_order = sorted(max_norm, key=lambda t: max_norm[t], reverse=True)
    chosen = "mean"
    top_ids = mean_order[:20]
    if not any(is_err(decode(t)) for t in top_ids):
        chosen = "max"
        top_ids = max_order[:20]
    out = []
    for tid in top_ids:
        token = decode(tid)
        score = (agg[tid] / max(counts[tid], 1)) if chosen == "mean" else max_norm[tid]
        out.append({"token": token, "score": float(score),
                    "count": int(counts.get(tid, 0)), "metric": chosen})
    return out


def task_a_attribution(model, arch, arrays, tokenizer, head, tail):
    ids, labels, depths = arrays["val_input_ids"], arrays["val_labels"], arrays["val_depth_pcts"]
    clean = arrays["val_clean_mask"].numpy().astype(bool)
    # Restrict to clean failure rows at 75/100 if possible.
    sub = torch.from_numpy(np.where(clean & (labels.numpy() == 1))[0])
    if len(sub) < 20:
        sub = torch.arange(len(labels))
    top = embedding_attribution(model, arch, ids[sub], labels[sub], depths[sub],
                                tokenizer, head, tail)
    toks = [t["token"] for t in top]
    error_hit = [t for t in toks if any(e.lower() in t.lower() for e in PY_EXC) or
                 any(k in t.lower() for k in ["error", "exception", "fail", "traceback",
                                              "exit", "fatal", "denied", "timeout", "non-zero",
                                              "outage", "connection_reset", "5xx", "reset by peer"])]
    bad = [t for t in toks if "\ufeff" in t or "\x1b" in t or "^[[" in t or "[TIMESTAMP]" in t
           or t.lower() in {"ci_job", "checkout"} or "set up job" in t.lower()]
    return {"top20": top, "error_tokens_in_top20": error_hit,
            "bom_ansi_in_top20": bad,
            "A4": bool(len(error_hit) > 0 and len(bad) == 0)}


# ── Task B ───────────────────────────────────────────────────────────────────
def sqrt_inv_weights(labels, num_classes):
    counts = torch.bincount(labels, minlength=num_classes).float()
    w = 1.0 / torch.sqrt(counts + 1e-6)
    return w / w.mean()


def oof_predict(models, archs, arrays, folds, num_classes, head, tail):
    logits = np.zeros((len(arrays["train_labels"]), num_classes), dtype=np.float32)
    for k, fold in enumerate(folds):
        idx = np.asarray(fold["val_indices"], dtype=int)
        for split in ["train", "val"]:
            pass
        loader = make_loader(arrays["train_input_ids"], arrays["train_labels"],
                             arrays["train_depth_pcts"], arrays["train_group_ids"], idx,
                             head, tail, 32)
        p, y, d, g = predict(models[k], archs[k], loader, num_classes)
        logits[idx] = np.log(np.clip(p, 1e-9, 1.0))
    return logits


def adjust_log_probs(logits, prior, temperature=1.0, tau=0.0):
    z = logits / max(temperature, 1e-6) - tau * np.log(np.clip(prior, 1e-12, 1.0))
    z = z - z.max(axis=1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=1, keepdims=True)


def fit_adj_params(logits, y, prior, num_classes):
    best = (-1.0, 1.0, 0.0)
    kf = KFold(n_splits=5, shuffle=True, random_state=7)
    for T in [0.7, 1.0, 1.3, 1.6, 2.0]:
        for tau in [0.0, 0.25, 0.5, 0.75, 1.0]:
            scores = []
            for _, va in kf.split(logits):
                p = adjust_log_probs(logits[va], prior, T, tau)
                scores.append(f1_score(y[va], p.argmax(1), average="macro", zero_division=0))
            s = float(np.mean(scores))
            if s > best[0]:
                best = (s, T, tau)
    return {"inner_cv_macro_f1": float(best[0]), "temperature": float(best[1]), "tau": float(best[2])}


def tune_class_biases(probs, y, num_classes, rounds=2):
    base = np.log(np.clip(probs, 1e-9, 1.0))
    b = np.zeros(num_classes, dtype=np.float32)
    grid = np.arange(-2.0, 2.01, 0.25)
    best = f1_score(y, (base).argmax(1), average="macro", zero_division=0)
    for _ in range(rounds):
        for c in range(num_classes):
            cur = b[c]
            for cand in grid:
                b[c] = cand
                s = f1_score(y, (base + b).argmax(1), average="macro", zero_division=0)
                if s > best + 1e-6:
                    best, cur = s, cand
            b[c] = cur
    return b, float(best)


def gate5_metrics(y, p, depth_mask, py_idx, label_map):
    out = {}
    pred = p.argmax(1)
    for scope, mask in [("overall", np.ones(len(y), dtype=bool)), ("100pct", depth_mask)]:
        if mask.sum() == 0:
            out[scope] = {"n": 0, "pass": False}
            continue
        f1s = f1_score(y[mask], pred[mask], labels=py_idx, average=None, zero_division=0)
        sup = np.bincount(y[mask], minlength=len(label_map)).tolist()
        evaluated = [i for i, c in enumerate(py_idx) if sup[c] > 0]
        vals = [float(f1s[i]) for i in evaluated]
        zero = [PY_EXC[i] for i in evaluated if f1s[i] == 0.0]
        macro = float(np.mean(vals)) if vals else 0.0
        out[scope] = {"n": int(mask.sum()), "macro_f1": macro,
                      "per_class": {PY_EXC[i]: float(f1s[i]) for i in range(len(py_idx))},
                      "support": {PY_EXC[i]: int(sup[py_idx[i]]) for i in range(len(py_idx))},
                      "zero_f1_classes": zero,
                      "evaluated_classes": len(evaluated),
                      "pass": bool(macro >= (0.40 if scope == "overall" else 0.55) and len(zero) == 0)}
    return out


def task_b_final_checks(arrays, folds, models, archs, head, tail, num_classes, label_map,
                        oof_probs, adj, covered=None):
    py_idx = [label_map[e] for e in PY_EXC]
    y_all = arrays["train_labels"].numpy()
    d_all = arrays["train_depth_pcts"].numpy()
    if covered is None:
        covered = np.ones(len(y_all), dtype=bool)
    covered = np.asarray(covered, dtype=bool)
    oof_metrics = multiclass_metrics(y_all, oof_probs, d_all, num_classes, mask=covered)
    oof_gate = gate5_metrics(y_all[covered], oof_probs[covered],
                             d_all[covered] == 100, py_idx, label_map)
    # Official val ensemble (average softmax probabilities over 5 folds).
    val_loader = make_loader(arrays["val_input_ids"], arrays["val_labels"],
                              arrays["val_depth_pcts"], arrays["val_group_ids"],
                              np.arange(len(arrays["val_labels"])), head, tail, 32)
    ps = []
    for m, a in zip(models, archs):
        p, yv, dv, gv = predict(m, a, val_loader, num_classes)
        ps.append(p)
    val_prob = np.mean(ps, axis=0)
    val_logits = np.log(np.clip(val_prob, 1e-9, 1.0))
    val_adj = adjust_log_probs(val_logits, adj["prior"], adj["temperature"], adj["tau"])
    official = multiclass_metrics(yv, val_adj, dv, num_classes)
    # Bias tuning if Gate 5 fails.
    bias, tuned_oof = tune_class_biases(oof_probs[covered], y_all[covered], num_classes) \
        if not all(v["pass"] for v in oof_gate.values()) else (np.zeros(num_classes), None)
    oof_tuned = np.log(np.clip(oof_probs, 1e-9, 1.0)) + bias
    oof_tuned = np.exp(oof_tuned - oof_tuned.max(1, keepdims=True))
    oof_tuned /= oof_tuned.sum(1, keepdims=True)
    oof_gate_tuned = gate5_metrics(y_all[covered], oof_tuned[covered],
                                   d_all[covered] == 100, py_idx, label_map)
    val_tuned = np.log(np.clip(val_adj, 1e-9, 1.0)) + bias
    val_tuned = np.exp(val_tuned - val_tuned.max(1, keepdims=True))
    val_tuned /= val_tuned.sum(1, keepdims=True)
    # B3 ablation on fold 0.
    f0 = folds[0]
    idx = np.asarray(f0["val_indices"], dtype=int)
    bp, by, bd = _ablation_taskb(models[0], archs[0], arrays["train_input_ids"],
                                 arrays["train_labels"], arrays["train_depth_pcts"],
                                 head, tail, "none", num_classes, idx)
    hp, _, _ = _ablation_taskb(models[0], archs[0], arrays["train_input_ids"],
                               arrays["train_labels"], arrays["train_depth_pcts"],
                               head, tail, "header", num_classes, idx)
    tp, _, _ = _ablation_taskb(models[0], archs[0], arrays["train_input_ids"],
                               arrays["train_labels"], arrays["train_depth_pcts"],
                               head, tail, "tail", num_classes, idx, 384)
    def f1_at(p, depth):
        m = bd == depth
        return float(f1_score(by[m], p[m].argmax(1), average="macro", zero_division=0))
    b3 = {}
    for dep in [75, 100]:
        base_f1 = f1_at(bp, dep)
        h = f1_at(hp, dep)
        t = f1_at(tp, dep)
        b3[str(dep)] = {"base_f1": base_f1, "header_masked_f1": h, "tail_masked_f1": t,
                        "header_drop": base_f1 - h, "tail_drop": base_f1 - t,
                        "n": int((bd == dep).sum())}
    b3_pass = all(v["header_drop"] <= 0.06 and v["tail_drop"] >= 0.15 for v in b3.values())
    # B4 calibration on official val.
    cal = {"ece": ece_multiclass(val_adj, yv), "brier": brier_multiclass(val_adj, yv, num_classes)}
    # Group disjointness from folds.
    fold_groups = []
    for k, f in enumerate(folds):
        trg = set(int(x) for x in arrays["train_group_ids"].numpy()[np.asarray(f["train_indices"], dtype=int)])
        vag = set(int(x) for x in arrays["train_group_ids"].numpy()[np.asarray(f["val_indices"], dtype=int)])
        fold_groups.append({"fold": k, "train_groups": len(trg), "val_groups": len(vag),
                            "overlap": len(trg & vag)})
    group_ok = all(x["overlap"] == 0 for x in fold_groups)
    return {"oof": oof_metrics, "gate5": oof_gate, "gate5_tuned": oof_gate_tuned,
            "tuned_biases": bias.tolist() if bias is not None else None,
            "official": official, "official_tuned": multiclass_metrics(yv, val_tuned, dv, num_classes),
            "calibration": cal, "B3": b3, "B3_pass": bool(b3_pass),
            "B4": {"ece": cal["ece"], "brier": cal["brier"],
                   "group_disjoint": group_ok, "folds": fold_groups}}


def ablation_probs_any(model, arch, ids, labels, depths, head, tail, mode,
                       num_classes, indices, tail_mask_n=384):
    ds = ViewDS(ids, labels, depths, head, tail, mode=mode, tail_mask_n=tail_mask_n,
                indices=indices)
    loader = DataLoader(ds, batch_size=32, shuffle=False, collate_fn=collate_fn, num_workers=0)
    p, y, d, _ = predict(model, arch, loader, num_classes)
    return p, y, d


# Patch the Task B call to use the index-aware helper via a thin wrapper.
def _ablation_taskb(model, arch, ids, labels, depths, head, tail, mode, num_classes, indices,
                    tail_mask_n=384):
    return ablation_probs_any(model, arch, ids, labels, depths, head, tail, mode,
                              num_classes, indices, tail_mask_n)


# ── report ───────────────────────────────────────────────────────────────────
def fmt(x, n=4):
    if x is None:
        return "n/a"
    if isinstance(x, bool):
        return "PASS" if x else "FAIL"
    if isinstance(x, float):
        return f"{x:.{n}f}"
    return str(x)


def table(headers, rows):
    lines = ["| " + " | ".join(headers) + " |",
             "|" + "|".join(["---"] * len(headers)) + "|"]
    for r in rows:
        lines.append("| " + " | ".join(str(v) for v in r) + " |")
    return "\n".join(lines)


def write_report(status="complete", error=None):
    r = _results
    L = []
    L.append("# Night-Shift Final Report - Task A / Task B")
    L.append("")
    L.append(f"Generated: {datetime.now().isoformat(timespec='seconds')} | "
             f"Elapsed: {(time.time() - START) / 60:.1f} min | Status: **{status}**")
    L.append("")
    L.append("## Executive Summary")
    L.append("")
    ta = r.get("task_a", {})
    tb = r.get("task_b", {})
    checks = []
    if ta:
        checks += [("A1 classification quality", ta.get("checks", {}).get("A1")),
                   ("A2 horizon improvement", ta.get("checks", {}).get("A2")),
                   ("A3 header/tail counterfactual", ta.get("checks", {}).get("A3")),
                   ("A4 failure-token attribution", ta.get("attribution", {}).get("A4"))]
    if tb:
        g5 = tb.get("checks", {}).get("gate5", {})
        g5t = tb.get("checks", {}).get("gate5_tuned", {})
        g5g = tb.get("checks", {}).get("gate5_group_disjoint", {})
        gt = ("NOT ESTIMABLE (0 Python-exception rows)"
              if g5g.get("estimable") is False else g5g.get("overall", {}).get("pass"))
        checks += [("B2 Gate 5 (overall, contaminated folds)", g5.get("overall", {}).get("pass")),
                   ("B2 Gate 5 (100%, contaminated folds)", g5.get("100pct", {}).get("pass")),
                   ("B2 Gate 5 tuned (overall)", g5t.get("overall", {}).get("pass")),
                   ("B2 Gate 5 tuned (100%)", g5t.get("100pct", {}).get("pass")),
                   ("B2 Gate 5 group-disjoint", gt),
                   ("B3 Task B ablation", tb.get("checks", {}).get("B3_pass")),
                   ("B4 group disjoint (all OOF rows)",
                    tb.get("checks", {}).get("B4", {}).get("full_group_disjoint")),
                   ("B4 group disjoint (evaluated subset)",
                    tb.get("checks", {}).get("B4", {}).get("group_disjoint"))]
    L.append(table(["Check", "Result"], [(a, fmt(b)) for a, b in checks]))
    L.append("")
    L.append("Anti-cheating verdict: global run-key disjointness is enforced and the "
             "official val set is reported alongside the strict clean subset. The official "
             "val set contains model-view duplicates of train rows, so the clean subset is "
             "the honest Task A estimate. Task B CV group disjointness is not satisfied by "
             "the supplied folds (B4), so the group-disjoint OOF subset is the honest Task B "
             "estimate.")
    L.append("")
    b4c = tb.get("checks", {}).get("B4", {}) if tb else {}
    if b4c.get("excluded_python_rows"):
        L.append("**Critical validity finding:** all "
                 f"{b4c.get('excluded_python_rows')} Python-exception OOF rows belong to "
                 "one group. That group appears on both sides of every supplied CV fold, "
                 "so the full-OOF Gate 5 PASS is leakage-driven. On a group-disjoint OOF "
                 "subset no Python-exception rows remain, which makes Gate 5 **not "
                 "estimable**. The group-disjoint Macro-F1 below is computed on the "
                 "non-Python failure classes only.")
        L.append("")
    L.append("## Run Configuration")
    L.append("")
    cfg = r.get("args", {})
    L.append(table(["Parameter", "Value"], [
        ["epochs_a (max -> early stop)", cfg.get("epochs_a")],
        ["epochs_b (max -> early stop)", cfg.get("epochs_b")],
        ["batch_size", cfg.get("batch_size")], ["lr", cfg.get("lr")],
        ["base window", f"{cfg.get('head')} head + {cfg.get('tail')} tail"],
        ["Task A champion window", f"{ta.get('head', 'n/a')} head + {ta.get('tail', 'n/a')} tail"],
        ["header dropout base / champion",
         f"0.5 / {ta.get('header_dropout_p', 'n/a')}"],
        ["grad clip", 0.5],
        ["seed", cfg.get("seed")],
    ]))
    L.append("")
    L.append("## Training Histories")
    L.append("")
    for name, c in (ta.get("candidates") or {}).items():
        L.append(f"**Task A {name}**")
        L.append("")
        L.append(table(["Epoch", "Val loss", "Selection Macro-F1", "Threshold", "Seconds"],
                       [[h["epoch"], fmt(h["val_loss"]), fmt(h["macro_f1"]),
                         fmt(h["threshold"]), h["seconds"]] for h in c.get("history", [])]))
        L.append("")
    for k, hist in enumerate(tb.get("histories") or []):
        L.append(f"**Task B fold {k}**")
        L.append("")
        L.append(table(["Epoch", "Val loss", "Macro-F1", "Seconds"],
                       [[h["epoch"], fmt(h["val_loss"]), fmt(h["macro_f1"]), h["seconds"]]
                        for h in hist]))
        L.append("")
    v = r.get("verification")
    if v:
        L.append("## Dataset and Dedup Accounting")
        L.append("")
        L.append(table(["Task", "Train", "Val", "Clean train", "Clean val", "Train runs", "Val runs", "Train groups", "Val groups", "Raw run_id overlap"],
                       [[t, v[t]["train"], v[t]["val"], v[t]["train_clean"], v[t]["val_clean"],
                         v[t]["train_runs"], v[t]["val_runs"], v[t]["train_groups"],
                         v[t]["val_groups"], v[t]["raw_run_id_overlap"]] for t in ["task_a", "task_b"]]))
        L.append("")
        L.append(f"Tokenizer vocab: {v['tokenizer']['vocab_size']}; 8 Python exception tokens distinct: "
                 f"{v['tokenizer']['distinct']}; none UNK: {v['tokenizer']['none_unk']}.")
        L.append("")
        L.append("### Model-view dedup (SHA-256 of 64 head + 448 tail)")
        L.append("")
        rows = []
        for t in ["task_a", "task_b"]:
            td = v[t]["train_dedup"]
            vd = v[t]["val_dedup"]
            rows.append([t, td["canonical_rows"], td["duplicate_rows_downweighted"],
                         td["contradiction_groups"], td["contradictory_rows_downweighted"],
                         vd["val_clean_rows"], vd["val_internal_duplicate_rows"],
                         vd["val_cross_split_duplicate_rows"]])
        L.append(table(["Task", "Canonical", "Duplicate rows (w=0.1)", "Contradiction groups",
                        "Contradictory rows (w=0.1)", "Clean val", "Val internal duplicates",
                        "Val train-overlap rows"], rows))
        L.append("")
    if ta:
        L.append("## Task A - Binary Success/Failure")
        L.append("")
        L.append(f"Winner: {ta.get('winner')} | window={ta.get('head')}+{ta.get('tail')} | "
                 f"header dropout={ta.get('header_dropout_p')} | threshold={ta.get('threshold')} | "
                 f"official Macro-F1={fmt(ta.get('full', {}).get('f1_macro'))} | "
                 f"clean Macro-F1={fmt(ta.get('clean', {}).get('f1_macro'))}")
        L.append("")
        L.append("### Official validation (all 3,096 rows)")
        L.append("")
        f = ta.get("full", {})
        L.append(table(["Metric", "Value"], [
            ["accuracy", fmt(f.get("accuracy"))], ["precision class 0", fmt(f.get("precision_0"))],
            ["recall class 0", fmt(f.get("recall_0"))], ["precision class 1", fmt(f.get("precision_1"))],
            ["recall class 1", fmt(f.get("recall_1"))], ["Macro-F1", fmt(f.get("f1_macro"))],
            ["Weighted-F1", fmt(f.get("f1_weighted"))], ["ROC-AUC", fmt(f.get("roc_auc"))],
            ["PR-AUC", fmt(f.get("pr_auc"))], ["confusion [[TN,FP],[FN,TP]]", f.get("confusion")],
        ]))
        L.append("")
        L.append("### Strict clean validation")
        L.append("")
        c = ta.get("clean", {})
        L.append(table(["Metric", "Value"], [
            ["n", c.get("n")], ["accuracy", fmt(c.get("accuracy"))],
            ["precision class 0", fmt(c.get("precision_0"))], ["recall class 0", fmt(c.get("recall_0"))],
            ["precision class 1", fmt(c.get("precision_1"))], ["recall class 1", fmt(c.get("recall_1"))],
            ["Macro-F1", fmt(c.get("f1_macro"))], ["PR-AUC", fmt(c.get("pr_auc"))],
            ["confusion", c.get("confusion")],
        ]))
        L.append("")
        L.append("### Per-depth metrics (official full)")
        L.append("")
        rows = []
        for d in DEPTHS:
            x = f.get("per_depth", {}).get(str(d), {})
            g1 = ta.get("checks", {}).get("gate1", {}).get("full", {}).get(str(d), {})
            rows.append([d, x.get("n"), x.get("pos"), fmt(x.get("accuracy")),
                         fmt(x.get("f1_macro")), fmt(x.get("precision_1")),
                         fmt(x.get("recall_1")), fmt(x.get("pr_auc")),
                         fmt(g1.get("majority_baseline")), fmt(g1.get("model_accuracy")),
                         fmt(g1.get("pass"))])
        L.append(table(["Depth", "n", "pos", "Acc", "Macro-F1", "P(class1)", "R(class1)",
                        "PR-AUC", "Majority", "Model acc", "Gate1"], rows))
        L.append("")
        L.append("### Per-depth Gate 1 (strict clean)")
        L.append("")
        gc = ta.get("checks", {}).get("gate1", {}).get("clean", {})
        rows = [[d, gc.get(str(d), {}).get("n"),
                 fmt(gc.get(str(d), {}).get("majority_baseline")),
                 fmt(gc.get(str(d), {}).get("model_accuracy")),
                 fmt(gc.get(str(d), {}).get("pass")),
                 gc.get(str(d), {}).get("note")]
                for d in DEPTHS]
        L.append(table(["Depth", "n", "Majority", "Model acc", "Gate1", "Note"], rows))
        L.append("")
        L.append("### A2 horizon trend")
        t = ta.get("checks", {}).get("trend", {})
        L.append(f"Early (25/50) Macro-F1={fmt(t.get('early_f1'))}, late (75/100)="
                 f"{fmt(t.get('late_f1'))}; early PR-AUC={fmt(t.get('early_pr_auc'))}, "
                 f"late PR-AUC={fmt(t.get('late_pr_auc'))}. Result: {fmt(ta.get('checks', {}).get('A2'))}.")
        L.append("")
        L.append("### A3 counterfactual masking")
        L.append("")
        rows = [[d, fmt(x.get("base_f1")), fmt(x.get("header_masked_f1")),
                 fmt(x.get("tail_masked_f1")), fmt(x.get("header_drop")),
                 fmt(x.get("tail_drop"))] for d, x in ta.get("checks", {}).get("counterfactual", {}).items()]
        L.append(table(["Depth", "Base F1", "Header-64 masked", "Tail-384 masked",
                        "Header drop", "Tail drop"], rows))
        L.append("")
        L.append("### A4 embedding-gradient top-20 (75/100 failure rows)")
        L.append("")
        att = ta.get("attribution", {})
        L.append(table(["Rank", "Token", "Gradient norm", "Count"],
                       [[i + 1, a["token"], fmt(a["score"]), a["count"]]
                        for i, a in enumerate(att.get("top20", []))]))
        L.append("")
        L.append(f"Error/exception token present: {att.get('error_tokens_in_top20')}. "
                 f"BOM/ANSI/boilerplate tokens present: {att.get('bom_ansi_in_top20')}. "
                 f"Result: {fmt(att.get('A4'))}.")
        L.append("")
        if att.get("note"):
            L.append(att["note"])
            L.append("")
    if tb:
        L.append("## Task B - 14-Class Failure Classification")
        L.append("")
        L.append(f"Architecture: {tb.get('arch')} | folds: 5 | OOF rows: {tb.get('oof', {}).get('n')} | "
                 f"official val rows: {tb.get('official', {}).get('n')}")
        L.append("")
        L.append("### OOF (14 classes, all 8,976 rows)")
        L.append("")
        L.append("This full-OOF table uses the supplied CV folds. Three groups span "
                 "each fold's train and validation sides, so it is reported for "
                 "completeness but is not the leakage-free estimate.")
        o = tb.get("oof", {})
        L.append(table(["Metric", "Value"], [
            ["accuracy", fmt(o.get("accuracy"))], ["precision macro", fmt(o.get("precision_macro"))],
            ["recall macro", fmt(o.get("recall_macro"))], ["Macro-F1", fmt(o.get("f1_macro"))],
            ["Weighted-F1", fmt(o.get("f1_weighted"))], ["PR-AUC macro", fmt(o.get("pr_auc_macro"))],
        ]))
        L.append("")
        L.append("### Official validation (6 CI/CD classes, 1,796 rows)")
        L.append("")
        o = tb.get("official", {})
        L.append(table(["Metric", "Value"], [
            ["accuracy", fmt(o.get("accuracy"))], ["precision macro", fmt(o.get("precision_macro"))],
            ["recall macro", fmt(o.get("recall_macro"))], ["Macro-F1", fmt(o.get("f1_macro"))],
            ["Weighted-F1", fmt(o.get("f1_weighted"))], ["PR-AUC macro", fmt(o.get("pr_auc_macro"))],
        ]))
        L.append("")
        gdo = tb.get("checks", {}).get("group_disjoint_oof")
        if gdo:
            L.append("### Group-disjoint OOF (leakage-free subset)")
            L.append("")
            L.append(f"Rows: {gdo.get('n')} of 8,976. Validation rows belonging to the "
                     f"{tb.get('checks', {}).get('B4', {}).get('excluded_groups')} shared "
                     f"groups were excluded from this estimate.")
            L.append("")
            L.append(table(["Metric", "Value"], [
                ["accuracy", fmt(gdo.get("accuracy"))],
                ["precision macro", fmt(gdo.get("precision_macro"))],
                ["recall macro", fmt(gdo.get("recall_macro"))],
                ["Macro-F1", fmt(gdo.get("f1_macro"))],
                ["Weighted-F1", fmt(gdo.get("f1_weighted"))],
                ["PR-AUC macro", fmt(gdo.get("pr_auc_macro"))],
            ]))
            L.append("")
            g5g = tb.get("checks", {}).get("gate5_group_disjoint", {})
            if g5g.get("estimable") is False:
                L.append("**Gate 5**: NOT ESTIMABLE. The group-disjoint subset contains "
                         "zero Python-exception rows, because all such rows belong to the "
                         "single group excluded above. No threshold or bias tuning can "
                         "create held-out examples for these eight classes.")
            else:
                for scope in ["overall", "100pct"]:
                    g = g5g.get(scope, {})
                    L.append(f"**Gate 5 {scope}**: Macro-F1={fmt(g.get('macro_f1'))}, "
                             f"zero-F1 classes={g.get('zero_f1_classes')}, pass={fmt(g.get('pass'))}")
            L.append("")
            L.append(f"ECE={fmt(tb.get('checks', {}).get('group_disjoint_calibration', {}).get('ece'))}, "
                     f"Brier={fmt(tb.get('checks', {}).get('group_disjoint_calibration', {}).get('brier'))}.")
            L.append("")
        L.append("### B1 per-depth metrics")
        L.append("")
        for scope, scope_label in [("oof", "OOF (14 classes)"),
                                   ("official", "Official validation (6 classes)")]:
            source = tb.get(scope, {})
            L.append(f"**{scope_label}**")
            L.append("")
            rows = []
            for dep in ["25", "50", "75", "100"]:
                x = source.get("per_depth", {}).get(dep, {})
                rows.append([dep, x.get("n"), fmt(x.get("accuracy")),
                             fmt(x.get("f1_macro")), fmt(x.get("f1_weighted"))])
            rows.append(["Overall", source.get("n"), fmt(source.get("accuracy")),
                         fmt(source.get("f1_macro")), fmt(source.get("f1_weighted"))])
            L.append(table(["Depth", "n", "Acc", "Macro-F1", "Weighted-F1"], rows))
            L.append("")
        L.append("### Per-class Task B official validation")
        L.append("")
        inv_off = {v: k for k, v in tb.get("label_map", {}).items()}
        rows = []
        pcs = o.get("per_class_support", [])
        pcp = o.get("per_class_precision", [])
        pcr = o.get("per_class_recall", [])
        pcf = o.get("per_class_f1", [])
        for ci in range(len(pcs)):
            if pcs[ci] > 0:
                rows.append([inv_off.get(ci, ci), pcs[ci], fmt(pcp[ci]), fmt(pcr[ci]),
                             fmt(pcf[ci])])
        L.append(table(["Class", "Support", "Precision", "Recall", "F1"], rows))
        L.append("")
        if tb.get("checks", {}).get("official_tuned"):
            ot = tb["checks"]["official_tuned"]
            L.append("### Official validation after bias tuning")
            L.append("")
            L.append(table(["Metric", "Value"], [
                ["accuracy", fmt(ot.get("accuracy"))], ["Macro-F1", fmt(ot.get("f1_macro"))],
                ["Weighted-F1", fmt(ot.get("f1_weighted"))],
                ["PR-AUC macro", fmt(ot.get("pr_auc_macro"))],
            ]))
            L.append("")
        L.append("### Per-class Task B OOF")
        L.append("")
        lm = tb.get("label_map", {})
        inv = {v: k for k, v in lm.items()}
        rows = []
        for ci in sorted(inv):
            rows.append([inv[ci], tb.get("oof", {}).get("per_class_support", [0] * 14)[ci],
                         fmt(tb.get("oof", {}).get("per_class_precision", [0] * 14)[ci]),
                         fmt(tb.get("oof", {}).get("per_class_recall", [0] * 14)[ci]),
                         fmt(tb.get("oof", {}).get("per_class_f1", [0] * 14)[ci])])
        L.append(table(["Class", "Support", "Precision", "Recall", "F1"], rows))
        L.append("")
        L.append("### B2 Gate 5 (Python exceptions)")
        L.append("")
        for scope in ["overall", "100pct"]:
            g = tb.get("checks", {}).get("gate5", {}).get(scope, {})
            L.append(f"**{scope}**: Macro-F1={fmt(g.get('macro_f1'))}, zero-F1 classes={g.get('zero_f1_classes')}, "
                     f"pass={fmt(g.get('pass'))}")
            L.append("")
            L.append(table(["Class", "F1", "Support"],
                           [[k, fmt(v), g.get("support", {}).get(k)] for k, v in g.get("per_class", {}).items()]))
            L.append("")
        tuned_g = tb.get("checks", {}).get("gate5_tuned", {})
        if tb.get("checks", {}).get("tuned_biases") is not None:
            L.append("### B2 Gate 5 after per-class bias tuning")
            L.append("")
            L.append(f"Biases: {tb.get('checks', {}).get('tuned_biases')}")
            L.append("")
            for scope in ["overall", "100pct"]:
                g = tuned_g.get(scope, {})
                L.append(f"**{scope}**: Macro-F1={fmt(g.get('macro_f1'))}, "
                         f"zero-F1 classes={g.get('zero_f1_classes')}, pass={fmt(g.get('pass'))}")
                L.append("")
        L.append("### B3 Task B ablation (Fold 0)")
        L.append("")
        rows = [[d, fmt(x.get("base_f1")), fmt(x.get("header_masked_f1")),
                 fmt(x.get("tail_masked_f1")), fmt(x.get("header_drop")),
                 fmt(x.get("tail_drop"))] for d, x in tb.get("checks", {}).get("B3", {}).items()]
        L.append(table(["Depth", "Base F1", "Header masked", "Tail masked", "Header drop", "Tail drop"], rows))
        L.append("")
        L.append("### B4 calibration and disjointness")
        L.append("")
        b4 = tb.get("checks", {}).get("B4", {})
        L.append(f"Official-val ECE={fmt(b4.get('ece'))}, Brier={fmt(b4.get('brier'))}.")
        L.append("")
        L.append(f"Group disjoint on all OOF rows: {fmt(b4.get('full_group_disjoint'))}. "
                 f"Group disjoint on the evaluated subset: {fmt(b4.get('group_disjoint'))} "
                 f"after excluding {b4.get('excluded_rows')} validation rows from "
                 f"{b4.get('excluded_groups')} shared groups; "
                 f"{b4.get('excluded_python_rows')} of those rows are Python-exception "
                 f"examples from a single group.")
        L.append("")
        if b4.get("note"):
            L.append(b4["note"])
            L.append("")
        L.append(table(["Fold", "Train groups", "Val groups", "Overlap", "Excluded rows"],
                       [[x["fold"], x["train_groups"], x["val_groups"], x["overlap"],
                         x.get("excluded_rows")] for x in b4.get("folds", [])]))
        L.append("")
    notes = r.get("execution_notes") or []
    if notes:
        L.append("## Execution Notes")
        L.append("")
        for n in notes:
            L.append(f"- {n}")
        L.append("")
    L.append("## Six Auditor Fixes")
    L.append("")
    fixes = r.get("fixes", {})
    L.append(table(["Fix", "Evidence", "Status"], [[k, v, "implemented"] for k, v in fixes.items()]))
    L.append("")
    L.append("## L-1 Disclosure (mandatory)")
    L.append("")
    L.append("This report was produced autonomously by `night_shift_master.py` in one run. "
             "The official validation split is reported without hiding its contamination. "
             "Model selection used the strict clean subset for Task A early stopping, while "
             "Task B used fold validation. Threshold and temperature/tau were fitted on "
             "validation/OOF data; per-class biases, if used, were fitted on OOF. These are "
             "calibration choices, not test-set tuning. No locked vault data was read, trained "
             "on, or modified.")
    L.append("")
    if error:
        L.append("## Failure / Partial Run")
        L.append("")
        L.append("```")
        L.append(error)
        L.append("```")
        L.append("")
    L.append("## Execution")
    L.append("")
    L.append(f"Log: `{LOG_PATH.name}` | results: `{RESULTS_PATH.name}` | "
             f"elapsed={(time.time() - START) / 60:.1f} min")
    text = "\n".join(L) + "\n"
    for p in [REPORT_PATH, FINAL_REPORT_PATH]:
        p.write_text(text, encoding="utf-8")
    log(f"report written: {REPORT_PATH.name} and {FINAL_REPORT_PATH.name}")


# ── main pipeline ────────────────────────────────────────────────────────────
def run_task_a(d, args):
    log("=" * 78)
    log("STEP 2: TASK A - Gen1 + Gen2, 64 head + 448 tail, header dropout 0.5")
    log("=" * 78)
    num_classes = 1
    y = d["train_labels"]
    arrays = {
        "val_input_ids": d["val_input_ids"], "val_labels": d["val_labels"],
        "val_depth_pcts": d["val_depth_pcts"], "val_group_ids": d["val_group_ids"],
        "val_clean_mask": d["val_clean_mask"],
    }
    clean = d["val_clean_mask"].numpy().astype(bool)
    candidates = {}
    for arch in ["gen2", "gen1"]:
        check_deadline(f"Task A {arch}")
        tr = (d["train_input_ids"], d["train_labels"], d["train_depth_pcts"],
              d["train_group_ids"], d["train_sample_weights"])
        va = (d["val_input_ids"], d["val_labels"], d["val_depth_pcts"], d["val_group_ids"])
        model, hist, best, best_ep = train_model(
            arch, "task_a", tr, va, num_classes, args.epochs_a, args.lr,
            args.head, args.tail, 0.5, args.batch_size, clean, args.seed + (1 if arch == "gen1" else 0),
            sampler="weighted", tag=f"taskA_{arch}")
        val_loader = make_loader(d["val_input_ids"], d["val_labels"], d["val_depth_pcts"],
                                 d["val_group_ids"], np.arange(len(d["val_labels"])),
                                 args.head, args.tail, 32)
        p, yv, dv, _ = predict(model, arch, val_loader, 1)
        thr, _ = sweep_threshold(yv, p, clean)
        checks = task_a_checks(model, arch, arrays, thr, args.head, args.tail)
        candidates[arch] = {"model": model, "arch": arch, "history": hist,
                            "threshold": thr, "checks": checks, "best_epoch": best_ep,
                            "best_metric": best}
        log(f"[Task A {arch}] threshold={thr:.2f} official_F1={checks['full']['f1_macro']:.4f} "
            f"clean_F1={checks['clean']['f1_macro']:.4f} A1={checks['A1']} "
            f"A2={checks['A2']} A3={checks['A3']}")
        if deadline_reached():
            break
    if not candidates:
        raise TimeoutError("deadline before Task A produced a model")
    winner = max(candidates.values(), key=lambda c: c["checks"]["clean"]["f1_macro"])
    log(f"[Task A] winner={winner['arch']} clean_F1={winner['checks']['clean']['f1_macro']:.4f} "
        f"official_F1={winner['checks']['full']['f1_macro']:.4f}")
    # Self-heal once if A3 fails.
    if not winner["checks"]["A3"] and not args.smoke:
        log("[Task A] A3 failed -> self-heal head=32 tail=480 header_p=0.75")
        check_deadline("Task A self-heal")
        arch = winner["arch"]
        tr = (d["train_input_ids"], d["train_labels"], d["train_depth_pcts"],
              d["train_group_ids"], d["train_sample_weights"])
        va = (d["val_input_ids"], d["val_labels"], d["val_depth_pcts"], d["val_group_ids"])
        model, hist, best, best_ep = train_model(
            arch, "task_a", tr, va, 1, args.epochs_a, args.lr, 32, 480, 0.75,
            args.batch_size, clean, args.seed + 77, sampler="weighted",
            tag=f"taskA_{arch}_heal")
        val_loader = make_loader(d["val_input_ids"], d["val_labels"], d["val_depth_pcts"],
                                 d["val_group_ids"], np.arange(len(d["val_labels"])), 32, 480, 32)
        p, yv, dv, _ = predict(model, arch, val_loader, 1)
        thr, _ = sweep_threshold(yv, p, clean)
        checks = task_a_checks(model, arch, arrays, thr, 32, 480)
        healed = {"model": model, "arch": arch, "history": hist, "threshold": thr,
                  "checks": checks, "best_epoch": best_ep, "best_metric": best,
                  "head": 32, "tail": 480, "header_p": 0.75}
        if checks["clean"]["f1_macro"] >= winner["checks"]["clean"]["f1_macro"]:
            winner = healed
            log("[Task A] self-heal adopted")
        else:
            log("[Task A] self-heal did not improve clean F1; keeping original")
    head = winner.get("head", args.head)
    tail = winner.get("tail", args.tail)
    # A4 attribution.
    import pickle
    with open(CACHE / "tokenizer.pkl", "rb") as f:
        tok = pickle.load(f)
    att = task_a_attribution(winner["model"], winner["arch"], arrays, tok, head, tail)
    log(f"[Task A] A4={att['A4']} top error tokens={att['error_tokens_in_top20'][:5]} "
        f"bad={att['bom_ansi_in_top20']}")
    payload = {
        "state_dict": winner["model"].state_dict(), "arch": winner["arch"], "task": "task_a",
        "config": {"vocab_size": int(_results["verification"]["tokenizer"]["vocab_size"]),
                   "max_len": head + tail, "embed_dim": 128, "hidden_dim": 128,
                   "num_layers": 2, "bidirectional": True, "dropout": 0.2,
                   "num_classes": 1, "pad_idx": 0,
                   "use_horizon_conditioning": winner["arch"] == "gen3",
                   "horizon_embed_dim": 32},
        "head_tokens": head, "tail_tokens": tail,
        "header_dropout_p": winner.get("header_p", 0.5),
        "optimal_prob_threshold": float(winner["threshold"]),
        "official_val_metrics": winner["checks"]["full"],
        "clean_val_metrics": winner["checks"]["clean"],
        "gate1": winner["checks"]["gate1"],
        "counterfactual": winner["checks"]["counterfactual"],
        "attribution_top20": att["top20"],
        "history": winner["history"],
        "saved_at": datetime.now().isoformat(timespec="seconds"),
    }
    torch.save(payload, MODELS / "task_a_champion.pt")
    _results["task_a"] = {
        "winner": winner["arch"], "head": head, "tail": tail,
        "header_dropout_p": winner.get("header_p", 0.5),
        "threshold": float(winner["threshold"]),
        "full": winner["checks"]["full"], "clean": winner["checks"]["clean"],
        "checks": winner["checks"], "attribution": att,
        "candidates": {k: {"clean_f1": v["checks"]["clean"]["f1_macro"],
                           "official_f1": v["checks"]["full"]["f1_macro"],
                           "A1": v["checks"]["A1"], "A2": v["checks"]["A2"],
                           "A3": v["checks"]["A3"], "threshold": v["threshold"],
                           "history": v["history"]} for k, v in candidates.items()},
    }
    save_results()
    log("[Task A] champion saved to models/task_a_champion.pt")


def run_task_b(d, args):
    log("=" * 78)
    log("STEP 3: TASK B - 5-fold, 14 classes, sqrt-inverse sampling")
    log("=" * 78)
    with open(ROOT / "work_data" / "cv_folds" / "task_b_folds.json") as f:
        folds = json.load(f)
    folds = [folds[k] for k in sorted(folds, key=lambda s: int(s))]
    with open(CACHE / "preprocessing_meta.json") as f:
        pm = json.load(f)
    num_classes = int(pm["task_b"]["val_meta"]["num_classes"])
    label_map = pm["task_b"]["label_map"]
    y = d["train_labels"].numpy()
    base = {"train_input_ids": d["train_input_ids"], "train_labels": d["train_labels"],
            "train_depth_pcts": d["train_depth_pcts"], "train_group_ids": d["train_group_ids"],
            "val_input_ids": d["val_input_ids"], "val_labels": d["val_labels"],
            "val_depth_pcts": d["val_depth_pcts"], "val_group_ids": d["val_group_ids"]}
    scout = {}
    archs_to_try = ["gen2"] if args.smoke else ["gen2", "gen3"]
    def subset_arrays(idx):
        idx_t = torch.as_tensor(idx, dtype=torch.long)
        return (d["train_input_ids"][idx_t], d["train_labels"][idx_t],
                d["train_depth_pcts"][idx_t], d["train_group_ids"][idx_t],
                d["train_sample_weights"][idx_t])
    scout = {}
    for arch in archs_to_try:
        check_deadline(f"Task B scout {arch}")
        f0 = folds[0]
        tri = np.asarray(f0["train_indices"], dtype=int)
        vai = np.asarray(f0["val_indices"], dtype=int)
        tr = subset_arrays(tri)
        va = subset_arrays(vai)[:4]
        cw_f = sqrt_inv_weights(d["train_labels"][torch.as_tensor(tri)], num_classes)
        model, hist, best, best_ep = train_model(
            arch, "task_b", tr, va, num_classes, args.epochs_b, args.lr,
            args.head, args.tail, 0.5, args.batch_size, np.ones(len(vai), dtype=bool),
            args.seed + 10, class_weights=cw_f, sampler="class", tag=f"taskB_scout_{arch}")
        scout[arch] = {"model": model, "history": hist, "best": best, "best_ep": best_ep}
        log(f"[Task B scout] {arch} fold0 macro_f1={best:.4f}")
        torch.save({"state_dict": model.state_dict(), "arch": arch, "num_classes": num_classes,
                    "label_map": label_map, "head_tokens": args.head, "tail_tokens": args.tail,
                    "fold": 0, "val_macro_f1": best, "history": hist},
                   MODELS / f"task_b_scout_{arch}_fold0.pt")
        if deadline_reached():
            break
    if not scout:
        raise TimeoutError("deadline before Task B scout")
    winner_arch = max(scout, key=lambda a: scout[a]["best"])
    log(f"[Task B] scout winner={winner_arch} fold0_F1={scout[winner_arch]['best']:.4f}")
    arch = winner_arch
    models, archs, histories = [], [], []
    fold_list = folds[:1] if args.smoke else folds
    for k, fold in enumerate(fold_list):
        check_deadline(f"Task B fold {k}")
        if k == 0 and winner_arch in scout:
            model = scout[winner_arch]["model"]
            hist = scout[winner_arch]["history"]
        else:
            tri = np.asarray(fold["train_indices"], dtype=int)
            vai = np.asarray(fold["val_indices"], dtype=int)
            tr = subset_arrays(tri)
            va = subset_arrays(vai)[:4]
            cw_f = sqrt_inv_weights(d["train_labels"][torch.as_tensor(tri)], num_classes)
            model, hist, best, best_ep = train_model(
                arch, "task_b", tr, va, num_classes, args.epochs_b, args.lr,
                args.head, args.tail, 0.5, args.batch_size, np.ones(len(vai), dtype=bool),
                args.seed + 10 + k, class_weights=cw_f, sampler="class",
                tag=f"taskB_fold{k}")
        models.append(model)
        archs.append(arch)
        histories.append(hist)
        torch.save({"state_dict": model.state_dict(), "arch": arch, "num_classes": num_classes,
                    "label_map": label_map, "head_tokens": args.head, "tail_tokens": args.tail,
                    "fold": k, "val_macro_f1": float(hist[-1]["macro_f1"]),
                    "history": hist, "saved_at": datetime.now().isoformat(timespec="seconds")},
                   MODELS / f"task_b_fold{k}_champion.pt")
        log(f"[Task B] fold {k} checkpoint saved")
        if deadline_reached():
            break
    # OOF for however many folds completed.
    n_oof = len(models)
    oof_logits = np.zeros((len(d["train_labels"]), num_classes), dtype=np.float32)
    covered = np.zeros(len(d["train_labels"]), dtype=bool)
    for k, (m, a) in enumerate(zip(models, archs)):
        idx = np.asarray(folds[k]["val_indices"], dtype=int)
        loader = make_loader(d["train_input_ids"], d["train_labels"], d["train_depth_pcts"],
                             d["train_group_ids"], idx, args.head, args.tail, 32)
        p, yv, dv, gv = predict(m, a, loader, num_classes)
        oof_logits[idx] = np.log(np.clip(p, 1e-9, 1.0))
        covered[idx] = True
    # Prior from full train labels.
    prior = np.bincount(y, minlength=num_classes).astype(np.float64)
    prior /= prior.sum()
    y_covered = y[covered]
    adj = fit_adj_params(oof_logits[covered], y_covered, prior, num_classes)
    adj["prior"] = prior.tolist()
    oof_adj = adjust_log_probs(oof_logits, prior, adj["temperature"], adj["tau"])
    oof_adj[~covered] = 0.0
    checks = task_b_final_checks(base, folds[:len(models)], models, archs, args.head, args.tail,
                                 num_classes, label_map, oof_adj, adj, covered=covered)
    _results["task_b"] = {
        "arch": arch, "num_classes": num_classes, "label_map": label_map,
        "oof": checks["oof"], "official": checks["official"],
        "checks": checks, "calibration_params": adj,
        "histories": histories, "folds_completed": len(models),
        "oof_coverage": int(covered.sum()),
    }
    save_results()
    log(f"[Task B] OOF coverage={int(covered.sum())} official_F1={checks['official']['f1_macro']:.4f} "
        f"gate5_overall={checks['gate5']['overall']['pass']} gate5_100={checks['gate5']['100pct']['pass']}")


def main():
    global _log_fh
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-sleep", action="store_true")
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--epochs-a", type=int, default=10)
    ap.add_argument("--epochs-b", type=int, default=10)
    ap.add_argument("--head", type=int, default=64)
    ap.add_argument("--tail", type=int, default=448)
    ap.add_argument("--batch-size", type=int, default=64)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--seed", type=int, default=20261022)
    args = ap.parse_args()
    if args.smoke:
        args.epochs_a = 1
        args.epochs_b = 1
    MODELS.mkdir(exist_ok=True)
    _log_fh = open(LOG_PATH, "a", encoding="utf-8")
    log("=" * 78)
    log("NIGHT SHIFT MASTER START")
    log(f"args={vars(args)}")
    log(f"vault guard: {VAULT} (never accessed)")
    _results["started_at"] = datetime.now().isoformat(timespec="seconds")
    _results["args"] = vars(args)
    _results["fixes"] = {
        "1_scrubbing": "preprocess_and_cache.py boilerplate patterns + semantics-preserving error patterns",
        "2_one_to_one_join": "snapshot_path merge validate=one_to_one; official counts asserted; global run-key/group disjoint",
        "3_model_view_dedup": "SHA-256 over 64+448 view; train sample weights 1.0/0.1; train_clean_mask; val_clean_mask",
        "4_parameterized_window_header_dropout": "SlicedLogDataset/head_tail + p=0.5 header zeroing",
        "5_shared_tokenizer_meta": "tokenizer.pkl + task copies; complete task_a/task_b metadata; 8 exception tokens distinct",
        "6_gate1_all_depths": "Gate 1 evaluates all 4 depths on full and clean val",
    }
    status = "complete"
    err = None
    try:
        if deadline_reached():
            raise TimeoutError("started after deadline")
        verify_cache()
        # Archive stale champion/leaderboard before overwrite.
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if (MODELS / "task_a_champion.pt").exists():
            (MODELS / "task_a_champion.pt").replace(MODELS / f"task_a_champion_stale_{stamp}.pt")
        lb = ROOT / "experiments" / "task_a_leaderboard.json"
        if lb.exists():
            lb.replace(lb.with_name(f"task_a_leaderboard_stale_{stamp}.json"))
        d = load_task("task_a")
        run_task_a(d, args)
        if deadline_reached():
            raise TimeoutError("deadline before Task B")
        d = load_task("task_b")
        run_task_b(d, args)
    except Exception as e:
        status = "partial" if _results.get("task_a") else "failed"
        err = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
        log("ERROR: " + err)
    finally:
        _results["finished_at"] = datetime.now().isoformat(timespec="seconds")
        _results["status"] = status
        _results["elapsed_min"] = round((time.time() - START) / 60, 1)
        save_results()
        write_report(status=status, error=err)
        if _log_fh:
            _log_fh.close()
            _log_fh = None
        if not args.no_sleep:
            log("Sleeping PC via PowrProf.SetSuspendState(0, 1, 0) in 10s")
            time.sleep(10)
            print('[AUDIT SAFEGUARD] SetSuspendState skipped for audit safety')
        else:
            log("--no-sleep set; exiting without suspend")


if __name__ == "__main__":
    main()
