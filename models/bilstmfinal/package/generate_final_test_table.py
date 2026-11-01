"""Score the saved Task A and Task B champions on the locked test set.

The script reads the locked manifest, labels, checkpoints, tokenizer, and
snapshot files. Its only output file is final_test_results.csv.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import pickle
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import torch
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)

ROOT = Path(r"C:\Users\Aditya CS\OneDrive\Documents\Capstone\CI-CD-Failure-Predictor\models\bilstmfinal\package")
VAULT = ROOT / "vault" / "test_locked"
SNAPSHOT_ROOT = ROOT / "data_v2" / "ready_to_train_v2"
CACHE = ROOT / "work_data" / "cache"
MODELS = ROOT / "models"
OUTPUT = ROOT / "final_test_results.csv"
VISIBILITIES = (25, 50, 75, 100)
MODEL_WINDOW = 512
BATCH_SIZE = 32
TABLE_COLUMNS = (
    "task",
    "visibility_pct",
    "accuracy",
    "precision",
    "recall",
    "f1",
    "macro_f1",
    "pr_auc",
    "roc_auc",
    "inference_ms_per_snapshot",
    "test_rows",
)


class RestrictedUnpickler(pickle.Unpickler):
    def find_class(self, module: str, name: str) -> Any:
        raise pickle.UnpicklingError(
            f"Global object {module}.{name} is not allowed in tokenizer data"
        )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_locked_vault() -> None:
    manifest_path = VAULT / "test_manifest_sha256.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not manifest:
        raise RuntimeError("The locked-test manifest is empty")

    for name, expected in manifest.items():
        path = (VAULT / name).resolve()
        if not path.is_relative_to(VAULT.resolve()):
            raise RuntimeError(f"Manifest path escapes the locked vault: {name}")
        if not path.is_file():
            raise FileNotFoundError(f"Locked-test asset is missing: {path}")
        if path.stat().st_size != expected["size_bytes"]:
            raise RuntimeError(f"Locked-test asset size mismatch: {name}")
        if sha256_file(path) != expected["sha256"]:
            raise RuntimeError(f"Locked-test asset SHA-256 mismatch: {name}")


def load_test_rows(filename: str) -> pd.DataFrame:
    path = VAULT / filename
    frame = pd.read_csv(path)
    if frame.empty:
        raise RuntimeError(f"Locked test table has no rows: {filename}")
    if set(frame["split"].astype(str)) != {"test"}:
        raise RuntimeError(f"{filename} includes a non-test split")
    if frame["snapshot_path"].isna().any() or frame["snapshot_path"].duplicated().any():
        raise RuntimeError(f"{filename} has missing or duplicate snapshot paths")
    if set(frame["snapshot_depth_pct"].astype(int)) != set(VISIBILITIES):
        raise RuntimeError(f"{filename} does not contain all requested visibilities")
    return frame


def build_snapshot_metadata(index: pd.DataFrame) -> dict[str, dict[str, Any]]:
    path_columns = {
        "snapshot_pct025": 25,
        "snapshot_pct050": 50,
        "snapshot_pct075": 75,
        "snapshot_pct100": 100,
    }
    required = {
        "run_id",
        "family",
        "outcome",
        "failure_type",
        "group_id",
        "split",
        *path_columns,
    }
    missing = required - set(index.columns)
    if missing:
        raise RuntimeError(f"Test index is missing columns: {sorted(missing)}")
    if set(index["split"].astype(str)) != {"test"}:
        raise RuntimeError("Test index includes a non-test split")

    metadata: dict[str, dict[str, Any]] = {}
    for row in index.to_dict(orient="records"):
        for column, depth in path_columns.items():
            snapshot_path = row[column]
            if not isinstance(snapshot_path, str) or not snapshot_path:
                raise RuntimeError(f"Missing {column} in test index")
            if snapshot_path in metadata:
                raise RuntimeError(f"Duplicate snapshot path in test index: {snapshot_path}")
            metadata[snapshot_path] = {
                "run_id": str(row["run_id"]),
                "family": str(row["family"]),
                "split": str(row["split"]),
                "depth": depth,
                "group_id": str(row["group_id"]),
                "outcome": str(row["outcome"]),
                "failure_type": str(row["failure_type"]),
            }
    return metadata


def validate_rows(
    frame: pd.DataFrame, metadata: dict[str, dict[str, Any]], task: str
) -> None:
    required_label = "label_outcome" if task == "binary" else "label_failure_type"
    for column in ("run_id", "family", "snapshot_depth_pct", required_label):
        if column not in frame.columns:
            raise RuntimeError(f"{task} test table is missing {column}")

    for row in frame.itertuples(index=False):
        snapshot = str(row.snapshot_path)
        details = metadata.get(snapshot)
        if details is None:
            raise RuntimeError(f"Snapshot is absent from locked test index: {snapshot}")
        if (
            str(row.run_id) != details["run_id"]
            or str(row.family) != details["family"]
            or str(row.split) != details["split"]
            or int(row.snapshot_depth_pct) != details["depth"]
        ):
            raise RuntimeError(f"Test table/index mismatch for {snapshot}")
        row_label = str(getattr(row, required_label))
        expected = details["outcome"] if task == "binary" else details["failure_type"]
        if row_label != expected:
            raise RuntimeError(f"Test label/index mismatch for {snapshot}")


def resolve_snapshot(relative_path: str) -> Path:
    path = (SNAPSHOT_ROOT / relative_path).resolve()
    if not path.is_relative_to(SNAPSHOT_ROOT.resolve()):
        raise RuntimeError(f"Snapshot path escapes the source data root: {relative_path}")
    if not path.is_file():
        raise FileNotFoundError(f"Snapshot file is missing: {path}")
    return path


def load_tokenizer() -> tuple[Any, dict[str, int]]:
    tokenizer_path = CACHE / "tokenizer.pkl"
    with tokenizer_path.open("rb") as stream:
        data = RestrictedUnpickler(stream).load()
    if not isinstance(data, dict) or not isinstance(data.get("vocab"), dict):
        raise RuntimeError("Tokenizer file does not contain the expected vocabulary")
    if data.get("fitted") is not True:
        raise RuntimeError("Saved tokenizer is not fitted")
    vocab = data["vocab"]
    if vocab.get("<PAD>") != 0 or "<UNK>" not in vocab:
        raise RuntimeError("Saved tokenizer is missing required special tokens")

    # Reuse the project's established normalizer rather than reimplementing
    # its canonicalization rules.
    from preprocess_and_cache import LogNormalizer, TrainOnlyTokenizer

    tokenizer = TrainOnlyTokenizer(vocab_size=int(data["vocab_size"]))
    tokenizer.vocab = vocab
    tokenizer.inv_vocab = {int(key): value for key, value in data["inv_vocab"].items()}
    tokenizer.fitted = True
    return LogNormalizer(), tokenizer


def tokenize_snapshot(path: Path, normalizer: Any, tokenizer: Any) -> list[int]:
    text = path.read_text(encoding="utf-8")
    normalized = normalizer.normalize(text)
    return tokenizer.encode(normalized)


def model_view(token_ids: list[int], head: int, tail: int) -> list[int]:
    actual = next((i for i, token in enumerate(token_ids) if token == 0), len(token_ids))
    if actual <= head + tail:
        return token_ids[:actual]
    return token_ids[:head] + token_ids[actual - tail : actual]


def load_checkpoint(path: Path) -> dict[str, Any]:
    checkpoint = torch.load(path, map_location="cpu", weights_only=True)
    if not isinstance(checkpoint, dict) or not isinstance(checkpoint.get("state_dict"), dict):
        raise RuntimeError(f"Checkpoint has no state_dict: {path}")
    return checkpoint


def build_model(checkpoint: dict[str, Any], num_classes: int) -> torch.nn.Module:
    from bilstm_architectures import ModelConfig, create_model

    arch = checkpoint.get("arch")
    generation = {"gen1": 1, "gen2": 2, "gen3": 3}.get(arch)
    if generation is None:
        raise RuntimeError(f"Unsupported model architecture: {arch}")

    if num_classes == 1:
        saved = checkpoint.get("config")
        if not isinstance(saved, dict):
            raise RuntimeError("Task A checkpoint is missing its model config")
        config = ModelConfig(**saved)
    else:
        config = ModelConfig(
            vocab_size=21041,
            max_len=MODEL_WINDOW,
            embed_dim=128,
            hidden_dim=128,
            num_layers=2,
            bidirectional=True,
            dropout=0.2,
            num_classes=num_classes,
            pad_idx=0,
            use_horizon_conditioning=(arch == "gen3"),
            horizon_embed_dim=32,
        )

    model = create_model(generation, config)
    model.load_state_dict(checkpoint["state_dict"], strict=True)
    return model


def forward(model: torch.nn.Module, arch: str, ids: torch.Tensor, lengths: torch.Tensor,
            depths: torch.Tensor) -> torch.Tensor:
    if arch == "gen3":
        output = model(ids, lengths, depth_pct=depths)
    else:
        output = model(ids, lengths)
    if isinstance(output, tuple):
        output = output[0]
    return output


def collate_batch(rows: list[dict[str, Any]], device: torch.device) -> tuple[
    torch.Tensor, torch.Tensor, torch.Tensor
]:
    lengths = torch.tensor([max(1, len(row["ids"])) for row in rows], dtype=torch.long)
    width = int(lengths.max().item())
    ids = torch.zeros((len(rows), width), dtype=torch.long)
    for i, row in enumerate(rows):
        if row["ids"]:
            ids[i, : len(row["ids"])] = torch.tensor(row["ids"], dtype=torch.long)
    depths = torch.tensor([row["depth"] for row in rows], dtype=torch.long)
    return ids.to(device), lengths.to(device), depths.to(device)


def predict_visibility(
    rows: list[dict[str, Any]],
    models: list[tuple[torch.nn.Module, str, int]],
    device: torch.device,
) -> tuple[np.ndarray, float]:
    if not rows:
        raise RuntimeError("No test rows found for a visibility")

    first_batch = rows[: min(BATCH_SIZE, len(rows))]
    warm_ids, warm_lengths, warm_depths = collate_batch(first_batch, device)
    with torch.inference_mode():
        for model, arch, _ in models:
            forward(model, arch, warm_ids, warm_lengths, warm_depths)
    if device.type == "cuda":
        torch.cuda.synchronize(device)

    outputs: list[np.ndarray] = []
    start = time.perf_counter()
    with torch.inference_mode():
        for offset in range(0, len(rows), BATCH_SIZE):
            batch = rows[offset : offset + BATCH_SIZE]
            ids, lengths, depths = collate_batch(batch, device)
            ensemble_probabilities = None
            for model, arch, num_classes in models:
                logits = forward(model, arch, ids, lengths, depths).float()
                probabilities = (
                    torch.sigmoid(logits).reshape(-1)
                    if num_classes == 1
                    else torch.softmax(logits, dim=1)
                )
                ensemble_probabilities = (
                    probabilities
                    if ensemble_probabilities is None
                    else ensemble_probabilities + probabilities
                )
            ensemble_probabilities = ensemble_probabilities / len(models)
            outputs.append(ensemble_probabilities.detach().cpu().numpy())
    if device.type == "cuda":
        torch.cuda.synchronize(device)
    elapsed = time.perf_counter() - start
    return np.concatenate(outputs, axis=0), elapsed * 1000.0 / len(rows)


def calculate_metrics(
    task: str,
    labels: np.ndarray,
    probabilities: np.ndarray,
    threshold: float | None,
    inference_ms_per_snapshot: float,
) -> dict[str, Any]:
    if task == "binary":
        class_labels = np.array([0, 1])
        predictions = (probabilities >= threshold).astype(int)
        pr_auc = average_precision_score(labels, probabilities)
        roc_auc = roc_auc_score(labels, probabilities) if np.unique(labels).size == 2 else np.nan
    else:
        class_labels = np.arange(probabilities.shape[1])
        predictions = probabilities.argmax(axis=1)
        one_hot = np.eye(len(class_labels), dtype=np.int8)[labels]
        pr_auc = average_precision_score(one_hot, probabilities, average="macro")
        roc_auc = np.nan

    return {
        "accuracy": accuracy_score(labels, predictions),
        "precision": precision_score(
            labels, predictions, labels=class_labels, average="macro", zero_division=0
        ),
        "recall": recall_score(
            labels, predictions, labels=class_labels, average="macro", zero_division=0
        ),
        "f1": f1_score(
            labels, predictions, labels=class_labels, average="weighted", zero_division=0
        ),
        "macro_f1": f1_score(
            labels, predictions, labels=class_labels, average="macro", zero_division=0
        ),
        "pr_auc": pr_auc,
        "roc_auc": roc_auc,
        "inference_ms_per_snapshot": inference_ms_per_snapshot,
        "test_rows": int(len(labels)),
    }


def evaluate_task(
    task: str,
    frame: pd.DataFrame,
    normalizer: Any,
    tokenizer: Any,
    device: torch.device,
) -> list[dict[str, Any]]:
    if task == "binary":
        checkpoint_paths = [MODELS / "task_a_champion.pt"]
        num_classes = 1
    else:
        checkpoint_paths = [
            MODELS / f"task_b_fold{fold}_champion.pt" for fold in range(5)
        ]
        num_classes = 14

    checkpoints = [load_checkpoint(path) for path in checkpoint_paths]
    if task == "binary":
        checkpoint = checkpoints[0]
        threshold = checkpoint.get("optimal_prob_threshold")
        if not isinstance(threshold, (int, float)) or not 0.0 <= threshold <= 1.0:
            raise RuntimeError("Task A checkpoint has no valid probability threshold")
        if not math.isclose(float(threshold), 0.20, abs_tol=1e-8) and not math.isclose(
            float(threshold), 0.525, abs_tol=1e-8
        ):
            raise RuntimeError(f"Unexpected Task A probability threshold: {threshold}")
        checkpoint_labels = {"success": 0, "failure": 1}
    else:
        threshold = None
        checkpoint_labels = checkpoints[0].get("label_map")
        if not isinstance(checkpoint_labels, dict) or len(checkpoint_labels) != num_classes:
            raise RuntimeError("Task B checkpoints have an invalid class label map")
        for fold, checkpoint in enumerate(checkpoints):
            if checkpoint.get("label_map") != checkpoint_labels:
                raise RuntimeError(f"Task B fold {fold} has a different label map")
            if checkpoint.get("arch") != checkpoints[0].get("arch"):
                raise RuntimeError(f"Task B fold {fold} has a different architecture")

    label_names = frame["label_outcome"] if task == "binary" else frame["label_failure_type"]
    try:
        labels = np.asarray([checkpoint_labels[str(label)] for label in label_names], dtype=int)
    except KeyError as error:
        raise RuntimeError(f"Unknown {task} test label: {error.args[0]}") from error

    head = int(checkpoints[0].get("head_tokens", 64))
    tail = int(checkpoints[0].get("tail_tokens", 448))
    if head <= 0 or tail <= 0:
        raise RuntimeError(f"Invalid saved model window for {task}")
    for checkpoint in checkpoints:
        if int(checkpoint.get("head_tokens", head)) != head or int(
            checkpoint.get("tail_tokens", tail)
        ) != tail:
            raise RuntimeError(f"Checkpoint model windows do not match for {task}")

    encoded_rows: list[dict[str, Any]] = []
    for row in frame.itertuples(index=False):
        tokens = tokenize_snapshot(resolve_snapshot(str(row.snapshot_path)), normalizer, tokenizer)
        encoded_rows.append(
            {
                "ids": model_view(tokens, head, tail),
                "depth": int(row.snapshot_depth_pct),
            }
        )

    models = []
    for checkpoint in checkpoints:
        model = build_model(checkpoint, num_classes).to(device)
        model.eval()
        models.append((model, str(checkpoint["arch"]), num_classes))

    results = []
    depths = frame["snapshot_depth_pct"].to_numpy(dtype=int)
    for visibility in VISIBILITIES:
        indices = np.flatnonzero(depths == visibility)
        if not len(indices):
            raise RuntimeError(f"No {task} test rows at {visibility}% visibility")
        subset = [encoded_rows[int(index)] for index in indices]
        probabilities, latency = predict_visibility(subset, models, device)
        metrics = calculate_metrics(
            task,
            labels[indices],
            probabilities,
            None if threshold is None else float(threshold),
            latency,
        )
        results.append(
            {
                "task": task,
                "visibility_pct": visibility,
                **metrics,
            }
        )
    return results


def format_cell(value: Any) -> str:
    if isinstance(value, (float, np.floating)):
        if math.isnan(float(value)):
            return "NaN"
        return f"{float(value):.4f}"
    return str(value)


def print_ascii_table(rows: list[dict[str, Any]]) -> None:
    rendered = [
        [format_cell(row[column]) for column in TABLE_COLUMNS] for row in rows
    ]
    widths = [
        max(len(column), *(len(row[index]) for row in rendered))
        for index, column in enumerate(TABLE_COLUMNS)
    ]

    def line(values: list[str]) -> str:
        return " | ".join(value.ljust(widths[i]) for i, value in enumerate(values))

    print(line(list(TABLE_COLUMNS)))
    print("-+-".join("-" * width for width in widths))
    for row in rendered:
        print(line(row))


def main() -> None:
    if not VAULT.is_dir() or not CACHE.is_dir() or not SNAPSHOT_ROOT.is_dir():
        raise FileNotFoundError("Required locked-test, cache, or source-data directory is missing")
    verify_locked_vault()

    binary = load_test_rows("binary_classification_test.csv")
    multiclass = load_test_rows("failure_classification_test.csv")
    index = pd.read_csv(VAULT / "dataset_index_test.csv")
    metadata = build_snapshot_metadata(index)
    validate_rows(binary, metadata, "binary")
    validate_rows(multiclass, metadata, "multiclass")

    normalizer, tokenizer = load_tokenizer()
    if len(tokenizer.vocab) != 21041:
        raise RuntimeError(f"Unexpected tokenizer vocabulary size: {len(tokenizer.vocab)}")

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    results = evaluate_task("binary", binary, normalizer, tokenizer, device)
    results.extend(evaluate_task("multiclass", multiclass, normalizer, tokenizer, device))

    output_frame = pd.DataFrame(results, columns=TABLE_COLUMNS)
    output_frame.to_csv(OUTPUT, index=False, quoting=csv.QUOTE_MINIMAL, na_rep="NaN")
    print_ascii_table(results)


if __name__ == "__main__":
    main()
