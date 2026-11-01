#!/usr/bin/env python3
"""
Step 3: Train-Only Log Normalizer + Tokenizer with Disk Caching
================================================================
- Canonical token replacement for high-cardinality shortcuts (SHA, HEX, UUID, IP, etc.)
- Vocab built ONLY on train split (25k max, special tokens)
- Head+Tail windowing: 64 head + 1472 tail = 1536-token cache
- Model view: 64 head + 448 tail = 512 tokens, hashed for dedup masks
- PyTorch tensor caches saved to work_data/cache/
"""

import os
import sys
import re
import json
import hashlib
import pickle
from pathlib import Path
from collections import Counter
from dataclasses import dataclass, asdict
from typing import List, Dict, Tuple, Optional

import pandas as pd
import numpy as np
import torch
from torch.utils.data import Dataset

# ─── Configuration ────────────────────────────────────────────────────────────
WORK_DIR = Path(r"C:\Users\Aditya CS\OneDrive\Documents\Capstone\CI-CD-Failure-Predictor\models\bilstmfinal\package\work_data")
DATA_DIR = Path(r"C:\Users\Aditya CS\OneDrive\Documents\Capstone\CI-CD-Failure-Predictor\models\bilstmfinal\package\data_v2\ready_to_train_v2")
CACHE_DIR = WORK_DIR / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
VAULT_DIR = Path(r"C:\Users\Aditya CS\OneDrive\Documents\Capstone\CI-CD-Failure-Predictor\models\bilstmfinal\package\vault\test_locked")

# Random seed for reproducibility
RANDOM_STATE = 20241201

# Official split sizes in data_v2/ready_to_train_v2.
EXPECTED_TRAIN_ROWS = 14976
EXPECTED_VAL_ROWS = 3096
EXPECTED_B_TRAIN_ROWS = 8976
EXPECTED_B_VAL_ROWS = 1796
MODEL_VIEW_LEN = 768
MODEL_HEAD_TOKENS = 192
MODEL_TAIL_TOKENS = 576
PYTHON_EXCEPTIONS = [
    'AssertionError', 'AttributeError', 'FileNotFoundError', 'IndexError',
    'KeyError', 'TypeError', 'ValueError', 'ZeroDivisionError',
]

# Tokenizer config
VOCAB_SIZE = 25000
MAX_LEN = 1536
HEAD_TOKENS = 64
TAIL_TOKENS = MAX_LEN - HEAD_TOKENS  # 1472

# Special tokens
PAD_TOKEN = "<PAD>"
UNK_TOKEN = "<UNK>"
CLS_TOKEN = "<CLS>"
SEP_TOKEN = "<SEP>"
MASK_TOKEN = "<MASK>"
SPECIAL_TOKENS = [PAD_TOKEN, UNK_TOKEN, CLS_TOKEN, SEP_TOKEN, MASK_TOKEN]

# Canonical replacement patterns (ordered by specificity)
CANONICAL_PATTERNS = [
    # SHA hashes (40+ hex chars, git shas, etc.)
    (re.compile(r'\b[0-9a-f]{40,}\b'), "<SHA>"),
    # SHA256 (64 hex chars)
    (re.compile(r'\b[0-9a-f]{64}\b'), "<SHA256>"),
    # MD5 (32 hex chars)
    (re.compile(r'\b[0-9a-f]{32}\b'), "<MD5>"),
    # UUIDs
    (re.compile(r'\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b', re.IGNORECASE), "<UUID>"),
    # IPv4 addresses
    (re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b'), "<IP>"),
    # IPv6 addresses (simplified)
    (re.compile(r'\b(?:[0-9a-f]{1,4}:){7}[0-9a-f]{1,4}\b', re.IGNORECASE), "<IPv6>"),
    # MAC addresses
    (re.compile(r'\b(?:[0-9a-f]{2}:){5}[0-9a-f]{2}\b', re.IGNORECASE), "<MAC>"),
    # Hex numbers (0x prefix, 8+ hex chars)
    (re.compile(r'\b0x[0-9a-f]{8,}\b', re.IGNORECASE), "<HEX>"),
    # Hex numbers (bare, 8+ hex chars, not part of word)
    (re.compile(r'(?<![0-9a-f])[0-9a-f]{8,}(?![0-9a-f])', re.IGNORECASE), "<HEX>"),
    # Docker image digests (sha256:...)
    (re.compile(r'sha256:[0-9a-f]{64}'), "sha256:<SHA256>"),
    # File paths (Unix-style, 3+ segments)
    (re.compile(r'(?:/[^/\s]+){3,}'), "<PATH>"),
    # File paths (Windows-style)
    (re.compile(r'(?:[A-Za-z]:(?:\\[^\\\s]+){2,})|(?:\\\\[^\\\s]+(?:\\[^\\\s]+){2,})'), "<WINPATH>"),
    # URLs
    (re.compile(r'https?://[^\s]+'), "<URL>"),
    # Email addresses
    (re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'), "<EMAIL>"),
    # Version numbers (semver-like)
    (re.compile(r'\b\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?\b'), "<VERSION>"),
    # Timestamps (ISO-like)
    (re.compile(r'\b\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?\b'), "<TIMESTAMP>"),
    # Long numbers (10+ digits, likely IDs/timestamps)
    (re.compile(r'\b\d{10,}\b'), "<LONGNUM>"),
    # Kubernetes resource names (namespace/name)
    (re.compile(r'\b[a-z0-9-]+/[a-z0-9-]+\b'), "<K8S_RES>"),
]

# Boilerplate stripped before tokenization so the model cannot memorize template
# prefixes (runner label, job step, timestamp placeholder, ANSI color codes).
ANSI_ESCAPE = re.compile(r'\x1b\[[0-9;?]*[A-Za-z]')
CARET_ESCAPE = re.compile(r'\^\[\[[0-9;]*m')
BOILERPLATE_PATTERNS = [
    # The runner prefix is "ci_job\t<step name>\t". Step names are written by
    # the scenario generator ("Execute F6 Scenario", "Build Container Image")
    # and leak the family, so the whole prefix is removed first.
    re.compile(r'^\s*ci_job\t[^\t]*\t', re.MULTILINE),
    ANSI_ESCAPE,
    CARET_ESCAPE,
    re.compile(r'\[TIMESTAMP\]', re.IGNORECASE),
    re.compile(r'<TIMESTAMP>', re.IGNORECASE),
    re.compile(r'\bci_job\b', re.IGNORECASE),
    re.compile(r'\bCheckout\b', re.IGNORECASE),
    re.compile(r'Set up job', re.IGNORECASE),
    re.compile(r'\[command\]', re.IGNORECASE),
    re.compile(r'^\s*##\[(?:section|group|endgroup|command)\].*$', re.MULTILINE | re.IGNORECASE),
    re.compile(r'^\s*(?:Current runner version|Runner Image|Image Release|Included Software|'
               r'Operating System|Runner\.Worker|Prepare all required actions|'
               r'Download action repository).*$', re.MULTILINE | re.IGNORECASE),
    re.compile(r'^\s*(?:Starting|Finishing):\s.*$', re.MULTILINE | re.IGNORECASE),
    # GitHub Actions git checkout/post-job dumps. These lines are identical in
    # every family and were the top gradient-attribution tokens (A4 failure).
    re.compile(r'^.*/usr/bin/git\b.*$', re.MULTILINE),
    re.compile(r'^.*\bgit version \d+\.\d+.*$', re.MULTILINE),
    re.compile(r'^.*\bSyncing repository:.*$', re.MULTILINE),
    re.compile(r'^.*\bTemporarily overriding HOME=.*$', re.MULTILINE),
    re.compile(r'^.*Adding repository directory to the temporary git global config.*$',
               re.MULTILINE),
    re.compile(r'^.*\bPost job cleanup\..*$', re.MULTILINE),
    re.compile(r'^.*Cleaning up orphan processes.*$', re.MULTILINE),
    re.compile(r'^.*\bNode (?:20|24) is being deprecated\b.*$', re.MULTILINE),
    re.compile(r'^.*##\[warning\]Node\.js 20 is deprecated\b.*$', re.MULTILINE),
    # The Docker Buildx setup step exists only in the docker-build family.
    # Substring match: buildx is often glued to a container name
    # (buildx_buildkit_builder-...), where \b never matches.
    re.compile(r'^.*buildx.*$', re.MULTILINE | re.IGNORECASE),
    re.compile(r'\.pytest_cache\b'),
    # ##[group] markers appear after the runner prefix, so anchor anywhere.
    re.compile(r'^.*##\[(?:section|group|endgroup|command)\].*$', re.MULTILINE),
    re.compile('﻿'),  # UTF-8 BOM
    re.compile('ï»¿'),  # UTF-8 BOM bytes decoded as latin-1/cp1252
]

# Scenario-identifying identifiers (label leakage documented in
# work_data/leakage_evidence.json). Values are anonymous placeholders so the
# model keeps a constant token instead of a family-correlated name.
SCENARIO_PATTERNS = [
    # Repository / image names.
    (re.compile(r'\b[\w\-]*error[\w\-]*repo\b', re.IGNORECASE), '<REPO>'),
    (re.compile(r'\blog[-_]generation\b', re.IGNORECASE), '<REPO>'),
    (re.compile(r'\bsynthetic[-_][\w\-]+', re.IGNORECASE), '<REPO>'),
    (re.compile(r'\bscenario[-_][\w\-]+', re.IGNORECASE), '<REPO>'),
    (re.compile(r'\brunner-images\b', re.IGNORECASE), '<REPO>'),
    (re.compile(r'\bDhruvHegde\b', re.IGNORECASE), '<USER>'),
    # Branch names carry the scenario ("feature/f3-test-failures") and, for
    # green runs, the outcome ("feature/success").
    (re.compile(r'\bfeature/[\w./\-]+'), '<BRANCH>'),
    # Family IDs and scenario variables (F6, F6_REQUIRED_TOKEN, SCENARIO_ID).
    (re.compile(r'\b[fF][1-7][_\-][A-Za-z0-9_\-]+'), '<SCENARIO_VAR>'),
    (re.compile(r'\bF[1-7]\b'), '<SCENARIO>'),
    (re.compile(r'(?<![A-Za-z0-9])scenarios?(?![A-Za-z0-9])', re.IGNORECASE),
     '<SCENARIO>'),
    # Pytest files and functions. Applied longest-first so ".py" is consumed
    # by the file rule, and never matches the Python exception class names.
    (re.compile(r'\b[A-Za-z0-9_]*test_[A-Za-z0-9_]+\.py\b'), '<TEST_FILE>'),
    (re.compile(r'\btest_[A-Za-z0-9_]+\b'), '<TEST_FUNC>'),
]

# Error-preserving patterns (DO NOT canonicalize - these carry failure signal)
ERROR_PATTERNS = [
    r'error', r'failed', r'failure', r'exception', r'traceback',
    r'assertionerror', r'attributeerror', r'filenotfounderror', r'indexerror',
    r'keyerror', r'typeerror', r'valueerror', r'zerodivisionerror',
    r'syntaxerror', r'importError', r'modulenotfounderror',
    r'permission denied', r'connection refused', r'timeout',
    r'out of memory', r'oom', r'killed', r'segfault',
    r'no space left', r'disk full', r'network.*unreachable',
    r'exit code', r'returned non-zero', r'command failed', r'fatal:',
    r'\bhttp[/ ]?\d?\.?\d?\s*[45]\d{2}\b', r'status code\s*[45]\d{2}',
    r'npm err!', r'could not resolve', r'permission denied',
]


@dataclass
class NormalizedSnapshot:
    """Container for normalized log snapshot with metadata."""
    snapshot_path: str
    group_id: str
    run_id: str
    run_key: str
    family: str
    depth_pct: int
    label_outcome: str
    label_failure_type: Optional[str]
    tokens: List[int]
    original_length: int
    normalized_length: int


class LogNormalizer:
    """Applies canonical token replacement while preserving error semantics."""

    def __init__(self):
        self.patterns = CANONICAL_PATTERNS
        self.error_keywords = [re.compile(p, re.IGNORECASE) for p in ERROR_PATTERNS]

    def normalize(self, text: str) -> str:
        """Apply boilerplate scrubbing and canonical replacements to log text."""
        # Scrub template markers on every line, including error lines, so the
        # model cannot key on the runner prefix or color codes.
        for pattern in BOILERPLATE_PATTERNS:
            text = pattern.sub(' ', text)

        # Anonymize scenario identifiers on every line, including error lines.
        for pattern, replacement in SCENARIO_PATTERNS:
            text = pattern.sub(replacement, text)

        # Protect error-bearing lines from high-cardinality ID replacement.
        lines = text.split('\n')
        protected_lines = set()

        for i, line in enumerate(lines):
            for pattern in self.error_keywords:
                if pattern.search(line):
                    protected_lines.add(i)
                    break

        # Apply canonical replacements to non-protected lines
        normalized_lines = []
        for i, line in enumerate(lines):
            if i in protected_lines:
                normalized_lines.append(line)
            else:
                normalized_line = line
                for pattern, replacement in self.patterns:
                    normalized_line = pattern.sub(replacement, normalized_line)
                normalized_lines.append(normalized_line)

        return '\n'.join(normalized_lines)

    def normalize_batch(self, texts: List[str]) -> List[str]:
        """Normalize a batch of texts."""
        return [self.normalize(t) for t in texts]


class TrainOnlyTokenizer:
    """Tokenizer built exclusively on train split data."""

    def __init__(self, vocab_size: int = VOCAB_SIZE):
        self.vocab_size = vocab_size
        self.vocab: Dict[str, int] = {}
        self.inv_vocab: Dict[int, str] = {}
        self.fitted = False

        # Reserve special token IDs
        for i, token in enumerate(SPECIAL_TOKENS):
            self.vocab[token] = i
            self.inv_vocab[i] = token

    def fit(self, texts: List[str]) -> 'TrainOnlyTokenizer':
        """Build vocabulary from train texts only."""
        print(f"  Building vocabulary from {len(texts)} train texts...")

        # Tokenize all texts (simple whitespace + punctuation splitting)
        all_tokens = []
        for text in texts:
            tokens = self._basic_tokenize(text)
            all_tokens.extend(tokens)

        # Count frequencies
        freq = Counter(all_tokens)
        print(f"  Unique tokens before vocab cap: {len(freq)}")

        # Select top (vocab_size - special_tokens) most frequent
        max_regular = self.vocab_size - len(SPECIAL_TOKENS)
        most_common = freq.most_common(max_regular)

        # Assign IDs
        for token, count in most_common:
            if token not in self.vocab:
                idx = len(self.vocab)
                self.vocab[token] = idx
                self.inv_vocab[idx] = token

        self.fitted = True
        print(f"  Final vocab size: {len(self.vocab)} (target: {self.vocab_size})")
        print(f"  Coverage: {sum(c for _, c in most_common) / len(all_tokens) * 100:.1f}%")

        return self

    def _basic_tokenize(self, text: str) -> List[str]:
        """Basic tokenization: split on whitespace, keep punctuation attached."""
        # Split on whitespace, keep newlines as tokens
        text = text.replace('\n', ' \n ')
        tokens = text.split()
        return tokens

    def encode(self, text: str, max_len: int = MAX_LEN, head_tokens: int = HEAD_TOKENS) -> List[int]:
        """Encode text with head+tail windowing."""
        if not self.fitted:
            raise RuntimeError("Tokenizer not fitted. Call fit() first.")

        tokens = self._basic_tokenize(text)
        token_ids = [self.vocab.get(t, self.vocab[UNK_TOKEN]) for t in tokens]

        if len(token_ids) <= max_len:
            # Pad if needed
            return token_ids + [self.vocab[PAD_TOKEN]] * (max_len - len(token_ids))

        # Head+Tail windowing
        head = token_ids[:head_tokens]
        tail = token_ids[-(max_len - head_tokens):]
        return head + tail

    def encode_batch(self, texts: List[str], max_len: int = MAX_LEN, head_tokens: int = HEAD_TOKENS) -> List[List[int]]:
        """Encode a batch of texts."""
        return [self.encode(t, max_len, head_tokens) for t in texts]

    def decode(self, token_ids: List[int]) -> str:
        """Decode token IDs back to text (approximate)."""
        tokens = [self.inv_vocab.get(i, UNK_TOKEN) for i in token_ids if i != self.vocab[PAD_TOKEN]]
        return ' '.join(tokens)

    def ensure_tokens(self, tokens: List[str]) -> List[str]:
        """Add required train-derived tokens that fell outside the frequency cap."""
        added = []
        for token in tokens:
            if token not in self.vocab:
                idx = len(self.vocab)
                self.vocab[token] = idx
                self.inv_vocab[idx] = token
                added.append(token)
        if added:
            print(f"  Added {len(added)} required tokens: {added}", flush=True)
        return added

    def save(self, path: Path):
        """Save tokenizer to disk."""
        data = {
            'vocab': self.vocab,
            'inv_vocab': {str(k): v for k, v in self.inv_vocab.items()},
            'vocab_size': self.vocab_size,
            'fitted': self.fitted
        }
        with open(path, 'wb') as f:
            pickle.dump(data, f)
        print(f"  Tokenizer saved to: {path}")

    @classmethod
    def load(cls, path: Path) -> 'TrainOnlyTokenizer':
        """Load tokenizer from disk."""
        with open(path, 'rb') as f:
            data = pickle.load(f)

        tokenizer = cls(vocab_size=data['vocab_size'])
        tokenizer.vocab = data['vocab']
        tokenizer.inv_vocab = {int(k): v for k, v in data['inv_vocab'].items()}
        tokenizer.fitted = data['fitted']
        print(f"  Tokenizer loaded from: {path} (vocab: {len(tokenizer.vocab)})")
        return tokenizer


class LogDataset(Dataset):
    """PyTorch Dataset for cached log tensors."""

    def __init__(self, cache_dir: Path, split: str, task: str):
        """
        Args:
            cache_dir: Directory containing cached tensors
            split: 'train' or 'val'
            task: 'task_a' (binary) or 'task_b' (failure)
        """
        self.cache_dir = cache_dir
        self.split = split
        self.task = task

        # Load metadata
        meta_path = cache_dir / f"{task}_{split}_meta.json"
        with open(meta_path, 'r') as f:
            self.meta = json.load(f)

        # Load tensors (memory-mapped for large datasets)
        self.input_ids = torch.load(cache_dir / f"{task}_{split}_input_ids.pt", map_location='cpu')
        self.labels = torch.load(cache_dir / f"{task}_{split}_labels.pt", map_location='cpu')
        self.group_ids = torch.load(cache_dir / f"{task}_{split}_group_ids.pt", map_location='cpu')
        self.depth_pcts = torch.load(cache_dir / f"{task}_{split}_depth_pcts.pt", map_location='cpu')

        print(f"  Loaded {task} {split}: {len(self.input_ids)} samples, "
              f"input_ids shape: {self.input_ids.shape}")

    def __len__(self):
        return len(self.input_ids)

    def __getitem__(self, idx):
        return {
            'input_ids': self.input_ids[idx],
            'labels': self.labels[idx],
            'group_id': self.group_ids[idx],
            'depth_pct': self.depth_pcts[idx]
        }


def load_and_normalize_snapshots(
    df: pd.DataFrame,
    index_df: pd.DataFrame,
    normalizer: LogNormalizer,
    snapshot_root: Path,
    task: str = 'task_a'  # 'task_a' or 'task_b'
) -> List[NormalizedSnapshot]:
    """Load snapshot files, normalize, and return structured data."""
    print(f"  Loading and normalizing {len(df)} snapshots...")

    # Join metadata through the unique snapshot path. The old (run_id, family)
    # merge was many-to-many: run_id is only unique within a family, so one
    # snapshot received several group_ids and the split grew by 5,072 rows.
    path_cols = [c for c in ('snapshot_pct025', 'snapshot_pct050',
                             'snapshot_pct075', 'snapshot_pct100')
                 if c in index_df.columns]
    meta = index_df[['run_id', 'family', 'outcome', 'group_id', 'split',
                     'original_log_path'] + path_cols].copy()
    meta = meta.melt(id_vars=['run_id', 'family', 'outcome', 'group_id', 'split',
                              'original_log_path'],
                     value_vars=path_cols, var_name='depth_col',
                     value_name='snapshot_path')
    meta['index_depth'] = meta['depth_col'].str.extract(r'(\d+)').astype(int)
    meta = meta.rename(columns={'split': 'index_split',
                                'original_log_path': 'run_key'})
    if meta['snapshot_path'].duplicated().any():
        raise RuntimeError("snapshot_path is not unique in index metadata")

    df = df.merge(
        meta[['snapshot_path', 'group_id', 'run_key', 'index_split', 'index_depth']],
        on='snapshot_path', how='left', validate='one_to_one'
    )
    if df['group_id'].isna().any():
        missing = int(df['group_id'].isna().sum())
        raise RuntimeError(f"{missing} snapshots have no index metadata")
    if not (df['split'].astype(str) == df['index_split'].astype(str)).all():
        raise RuntimeError("binary split and index split disagree")
    if not (df['snapshot_depth_pct'].astype(int) == df['index_depth'].astype(int)).all():
        raise RuntimeError("snapshot depth and index depth disagree")
    if df['snapshot_path'].duplicated().any():
        raise RuntimeError("join produced duplicate snapshot rows")
    print(f"  Metadata join: {len(df)} rows, 0 fanout, "
          f"{df['group_id'].nunique()} groups")

    snapshots = []
    for _, row in df.iterrows():
        snapshot_path = snapshot_root / row['snapshot_path']
        if not snapshot_path.exists():
            print(f"  WARNING: Missing snapshot: {snapshot_path}")
            continue

        text = snapshot_path.read_text(encoding='utf-8')
        original_len = len(text)

        normalized_text = normalizer.normalize(text)
        normalized_len = len(normalized_text)

        # Task A has label_outcome, Task B has label_failure_type
        label_outcome = row.get('label_outcome', None) if task == 'task_a' else None
        label_failure_type = row.get('label_failure_type', None)

        snapshots.append(NormalizedSnapshot(
            snapshot_path=row['snapshot_path'],
            group_id=row['group_id'],
            run_id=row['run_id'],
            run_key=row['run_key'],
            family=row['family'],
            depth_pct=row['snapshot_depth_pct'],
            label_outcome=label_outcome,
            label_failure_type=label_failure_type,
            tokens=[],  # Will be filled after tokenization
            original_length=original_len,
            normalized_length=normalized_len
        ))

    print(f"  Successfully loaded {len(snapshots)} snapshots")
    return snapshots


def model_view_tokens(tokens: List[int]) -> List[int]:
    """Return the exact 512-token view the model consumes."""
    actual = len(tokens)
    for i, tok in enumerate(tokens):
        if tok == 0:  # PAD
            actual = i
            break
    if actual <= MODEL_VIEW_LEN:
        return tokens[:actual]
    return tokens[:MODEL_HEAD_TOKENS] + tokens[actual - MODEL_TAIL_TOKENS:actual]


def view_hash(tokens: List[int]) -> str:
    """Hash the model-visible token slice, including its length."""
    view = np.asarray(model_view_tokens(tokens), dtype=np.int32)
    h = hashlib.sha256()
    h.update(len(view).to_bytes(4, 'little'))
    h.update(view.tobytes())
    return h.hexdigest()


def build_train_weights(
    hashes: List[str],
    labels: List[int],
    depths: List[int],
) -> Tuple[np.ndarray, np.ndarray, Dict]:
    """Keep one canonical row per (view hash, label); downweight the rest."""
    groups: Dict[str, List[int]] = {}
    for i, h in enumerate(hashes):
        groups.setdefault(h, []).append(i)

    weights = np.ones(len(hashes), dtype=np.float32)
    clean = np.ones(len(hashes), dtype=bool)
    contradiction_groups = 0
    duplicate_rows = 0
    contradictory_rows = 0

    for idxs in groups.values():
        label_counts = Counter(labels[i] for i in idxs)
        if len(label_counts) > 1:
            contradiction_groups += 1
            contradictory_rows += len(idxs)
            max_count = max(label_counts.values())
            candidates = [lab for lab, count in label_counts.items() if count == max_count]
            if len(candidates) > 1:
                deepest = max(depths[i] for i in idxs)
                candidates = sorted({labels[i] for i in idxs if depths[i] == deepest})
            canonical_label = candidates[0]
        else:
            canonical_label = next(iter(label_counts))

        same_label = [i for i in idxs if labels[i] == canonical_label]
        deepest = max(depths[i] for i in same_label)
        canonical = min(i for i in same_label if depths[i] == deepest)

        for i in idxs:
            if i == canonical:
                weights[i] = 1.0
            else:
                weights[i] = 0.1
                clean[i] = False
                duplicate_rows += 1

    stats = {
        'unique_model_view_hashes': len(groups),
        'duplicate_rows_downweighted': int(duplicate_rows),
        'contradiction_groups': int(contradiction_groups),
        'contradictory_rows_downweighted': int(contradictory_rows),
        'canonical_rows': int(clean.sum()),
    }
    return weights, clean, stats


def build_val_mask(val_hashes: List[str], train_hashes: List[str]) -> Tuple[np.ndarray, Dict]:
    """Mark val rows unique in model-view space and absent from train."""
    counts = Counter(val_hashes)
    train_set = set(train_hashes)
    mask = np.asarray(
        [counts[h] == 1 and h not in train_set for h in val_hashes],
        dtype=bool,
    )
    stats = {
        'val_rows': len(val_hashes),
        'val_clean_rows': int(mask.sum()),
        'val_internal_duplicate_rows': int(sum(c - 1 for c in counts.values() if c > 1)),
        'val_cross_split_duplicate_rows': int(sum(1 for h in val_hashes if h in train_set)),
    }
    return mask, stats


def prepare_task_a_data(
    binary_train_val: pd.DataFrame,
    index_train_val: pd.DataFrame,
    normalizer: LogNormalizer,
    tokenizer: TrainOnlyTokenizer,
    snapshot_root: Path,
    cv_folds_dir: Path
) -> Dict:
    """Prepare Task A with official counts, model-view dedup masks, and weights."""
    print("\n[Task A] Preparing binary classification data...", flush=True)

    with open(cv_folds_dir / "task_a_folds.json", "r") as f:
        json.load(f)

    train_df = binary_train_val[binary_train_val["split"] == "train"].copy()
    val_df = binary_train_val[binary_train_val["split"] == "val"].copy()
    print(f"  Official rows: train={len(train_df)} val={len(val_df)}", flush=True)
    if len(train_df) != EXPECTED_TRAIN_ROWS or len(val_df) != EXPECTED_VAL_ROWS:
        raise RuntimeError(
            f"official split size mismatch: {len(train_df)}/{len(val_df)} "
            f"(expected {EXPECTED_TRAIN_ROWS}/{EXPECTED_VAL_ROWS})"
        )

    train_snapshots = load_and_normalize_snapshots(
        train_df, index_train_val, normalizer, snapshot_root, task="task_a"
    )
    val_snapshots = load_and_normalize_snapshots(
        val_df, index_train_val, normalizer, snapshot_root, task="task_a"
    )
    if len(train_snapshots) != EXPECTED_TRAIN_ROWS or len(val_snapshots) != EXPECTED_VAL_ROWS:
        raise RuntimeError(f"snapshot load mismatch: {len(train_snapshots)}/{len(val_snapshots)}")

    train_run_keys = {s.run_key for s in train_snapshots}
    val_run_keys = {s.run_key for s in val_snapshots}
    train_groups = {s.group_id for s in train_snapshots}
    val_groups = {s.group_id for s in val_snapshots}
    raw_train_ids = {s.run_id for s in train_snapshots}
    raw_val_ids = {s.run_id for s in val_snapshots}
    raw_id_overlap = len(raw_train_ids & raw_val_ids)
    if not train_run_keys.isdisjoint(val_run_keys):
        raise RuntimeError(f"global run-key leakage: {len(train_run_keys & val_run_keys)}")
    if not train_groups.isdisjoint(val_groups):
        raise RuntimeError(f"group leakage: {len(train_groups & val_groups)}")
    vault_prefix = str(VAULT_DIR.resolve()).lower()
    for s in train_snapshots + val_snapshots:
        full = str((snapshot_root / s.snapshot_path).resolve()).lower()
        if full.startswith(vault_prefix):
            raise RuntimeError(f"vault path entered cache: {full}")
    print(f"  Disjointness: global runs {len(train_run_keys)}/{len(val_run_keys)} overlap 0 | "
          f"groups {len(train_groups)}/{len(val_groups)} overlap 0", flush=True)
    print(f"  Raw family-local run_id overlap: {raw_id_overlap} (not used as run identity)", flush=True)

    train_texts = []
    for s in train_snapshots:
        text = (snapshot_root / s.snapshot_path).read_text(encoding="utf-8")
        train_texts.append(normalizer.normalize(text))
    tokenizer.fit(train_texts)
    tokenizer.ensure_tokens(PYTHON_EXCEPTIONS)

    print("  Encoding train snapshots...", flush=True)
    for s in train_snapshots:
        text = (snapshot_root / s.snapshot_path).read_text(encoding="utf-8")
        s.tokens = tokenizer.encode(normalizer.normalize(text))
    print("  Encoding val snapshots...", flush=True)
    for s in val_snapshots:
        text = (snapshot_root / s.snapshot_path).read_text(encoding="utf-8")
        s.tokens = tokenizer.encode(normalizer.normalize(text))

    label_map = {"success": 0, "failure": 1}
    train_labels = [label_map[s.label_outcome] for s in train_snapshots]
    val_labels = [label_map[s.label_outcome] for s in val_snapshots]
    train_depths = [int(s.depth_pct) for s in train_snapshots]
    val_depths = [int(s.depth_pct) for s in val_snapshots]
    train_hashes = [view_hash(s.tokens) for s in train_snapshots]
    val_hashes = [view_hash(s.tokens) for s in val_snapshots]

    train_weights, train_clean, train_stats = build_train_weights(
        train_hashes, train_labels, train_depths
    )
    val_clean, val_stats = build_val_mask(val_hashes, train_hashes)
    clean_val_run_keys = {s.run_key for s, keep in zip(val_snapshots, val_clean) if keep}
    clean_val_groups = {s.group_id for s, keep in zip(val_snapshots, val_clean) if keep}
    print(f"  Model-view dedup: {train_stats}", flush=True)
    print(f"  Val model-view: {val_stats}", flush=True)
    print(f"  Clean val: {len(clean_val_run_keys)} runs, {len(clean_val_groups)} groups", flush=True)

    def save_split(split, snapshots, labels, depths, weights, clean, hashes):
        ids = torch.tensor([s.tokens for s in snapshots], dtype=torch.long)
        label_t = torch.tensor(labels, dtype=torch.long)
        group_t = torch.tensor(
            [int(hashlib.sha256(s.group_id.encode()).hexdigest()[:12], 16) % (2**31)
             for s in snapshots], dtype=torch.long
        )
        depth_t = torch.tensor(depths, dtype=torch.long)
        torch.save(ids, CACHE_DIR / f"task_a_{split}_input_ids.pt")
        torch.save(label_t, CACHE_DIR / f"task_a_{split}_labels.pt")
        torch.save(group_t, CACHE_DIR / f"task_a_{split}_group_ids.pt")
        torch.save(depth_t, CACHE_DIR / f"task_a_{split}_depth_pcts.pt")
        torch.save(torch.tensor(weights, dtype=torch.float32), CACHE_DIR / f"task_a_{split}_sample_weights.pt")
        torch.save(torch.tensor(clean, dtype=torch.bool), CACHE_DIR / f"task_a_{split}_clean_mask.pt")
        with open(CACHE_DIR / f"task_a_{split}_view_hashes.json", "w") as f:
            json.dump(hashes, f)
        return ids

    train_ids = save_split("train", train_snapshots, train_labels, train_depths,
                           train_weights, train_clean, train_hashes)
    val_ids = save_split("val", val_snapshots, val_labels, val_depths,
                         np.ones(len(val_snapshots), dtype=np.float32), val_clean, val_hashes)

    train_meta = {
        "num_samples": len(train_snapshots),
        "num_samples_official": EXPECTED_TRAIN_ROWS,
        "max_len": MAX_LEN,
        "model_view_len": MODEL_VIEW_LEN,
        "head_tokens": HEAD_TOKENS,
        "tail_tokens": TAIL_TOKENS,
        "model_head_tokens": MODEL_HEAD_TOKENS,
        "model_tail_tokens": MODEL_TAIL_TOKENS,
        "vocab_size": len(tokenizer.vocab),
        "label_map": label_map,
        "depth_distribution": dict(Counter(train_depths)),
        "run_keys": len(train_run_keys),
        "groups": len(train_groups),
        "raw_run_id_overlap": raw_id_overlap,
        "dedup": train_stats,
    }
    val_meta = {
        "num_samples": len(val_snapshots),
        "num_samples_official": EXPECTED_VAL_ROWS,
        "max_len": MAX_LEN,
        "model_view_len": MODEL_VIEW_LEN,
        "head_tokens": HEAD_TOKENS,
        "tail_tokens": TAIL_TOKENS,
        "model_head_tokens": MODEL_HEAD_TOKENS,
        "model_tail_tokens": MODEL_TAIL_TOKENS,
        "vocab_size": len(tokenizer.vocab),
        "label_map": label_map,
        "depth_distribution": dict(Counter(val_depths)),
        "run_keys": len(val_run_keys),
        "groups": len(val_groups),
        "raw_run_id_overlap": raw_id_overlap,
        "dedup": val_stats,
        "clean_run_keys": len(clean_val_run_keys),
        "clean_groups": len(clean_val_groups),
        "leakage_contract": {
            "global_run_key_disjoint": True,
            "group_disjoint": True,
            "model_view_train_overlap_rows": val_stats["val_cross_split_duplicate_rows"],
            "clean_mask_excludes_train_overlap": True,
        },
    }
    with open(CACHE_DIR / "task_a_train_meta.json", "w") as f:
        json.dump(train_meta, f, indent=2)
    with open(CACHE_DIR / "task_a_val_meta.json", "w") as f:
        json.dump(val_meta, f, indent=2)
    print(f"  Task A train tensors: {tuple(train_ids.shape)} | val tensors: {tuple(val_ids.shape)}", flush=True)
    return {"train_meta": train_meta, "val_meta": val_meta}


def prepare_task_b_data(
    failure_train_val: pd.DataFrame,
    index_train_val: pd.DataFrame,
    normalizer: LogNormalizer,
    tokenizer: TrainOnlyTokenizer,
    snapshot_root: Path,
    cv_folds_dir: Path
) -> Dict:
    """Prepare Task B with official counts, model-view dedup masks, and weights."""
    print("\n[Task B] Preparing 14-class failure data...", flush=True)

    with open(cv_folds_dir / "task_b_folds.json", "r") as f:
        json.load(f)

    train_df = failure_train_val[failure_train_val["split"] == "train"].copy()
    val_df = failure_train_val[failure_train_val["split"] == "val"].copy()
    print(f"  Official rows: train={len(train_df)} val={len(val_df)}", flush=True)
    if len(train_df) != EXPECTED_B_TRAIN_ROWS or len(val_df) != EXPECTED_B_VAL_ROWS:
        raise RuntimeError(
            f"official Task B split mismatch: {len(train_df)}/{len(val_df)} "
            f"(expected {EXPECTED_B_TRAIN_ROWS}/{EXPECTED_B_VAL_ROWS})"
        )

    train_snapshots = load_and_normalize_snapshots(
        train_df, index_train_val, normalizer, snapshot_root, task="task_b"
    )
    val_snapshots = load_and_normalize_snapshots(
        val_df, index_train_val, normalizer, snapshot_root, task="task_b"
    )
    if len(train_snapshots) != EXPECTED_B_TRAIN_ROWS or len(val_snapshots) != EXPECTED_B_VAL_ROWS:
        raise RuntimeError(f"snapshot load mismatch: {len(train_snapshots)}/{len(val_snapshots)}")

    train_run_keys = {s.run_key for s in train_snapshots}
    val_run_keys = {s.run_key for s in val_snapshots}
    train_groups = {s.group_id for s in train_snapshots}
    val_groups = {s.group_id for s in val_snapshots}
    raw_train_ids = {s.run_id for s in train_snapshots}
    raw_val_ids = {s.run_id for s in val_snapshots}
    raw_id_overlap = len(raw_train_ids & raw_val_ids)
    if not train_run_keys.isdisjoint(val_run_keys):
        raise RuntimeError(f"global run-key leakage: {len(train_run_keys & val_run_keys)}")
    if not train_groups.isdisjoint(val_groups):
        raise RuntimeError(f"group leakage: {len(train_groups & val_groups)}")
    vault_prefix = str(VAULT_DIR.resolve()).lower()
    for s in train_snapshots + val_snapshots:
        full = str((snapshot_root / s.snapshot_path).resolve()).lower()
        if full.startswith(vault_prefix):
            raise RuntimeError(f"vault path entered cache: {full}")
    print(f"  Disjointness: global runs {len(train_run_keys)}/{len(val_run_keys)} overlap 0 | "
          f"groups {len(train_groups)}/{len(val_groups)} overlap 0", flush=True)
    print(f"  Raw family-local run_id overlap: {raw_id_overlap} (not used as run identity)", flush=True)

    print("  Encoding train snapshots...", flush=True)
    for s in train_snapshots:
        text = (snapshot_root / s.snapshot_path).read_text(encoding="utf-8")
        s.tokens = tokenizer.encode(normalizer.normalize(text))
    print("  Encoding val snapshots...", flush=True)
    for s in val_snapshots:
        text = (snapshot_root / s.snapshot_path).read_text(encoding="utf-8")
        s.tokens = tokenizer.encode(normalizer.normalize(text))

    failure_classes = sorted(train_df["label_failure_type"].unique())
    label_map = {cls: i for i, cls in enumerate(failure_classes)}
    unknown_val = sorted(set(val_df["label_failure_type"].unique()) - set(label_map))
    if unknown_val:
        raise RuntimeError(f"validation classes absent from train label map: {unknown_val}")
    print(f"  Failure classes ({len(failure_classes)}): {failure_classes}", flush=True)

    train_labels = [label_map[s.label_failure_type] for s in train_snapshots]
    val_labels = [label_map[s.label_failure_type] for s in val_snapshots]
    train_depths = [int(s.depth_pct) for s in train_snapshots]
    val_depths = [int(s.depth_pct) for s in val_snapshots]
    train_hashes = [view_hash(s.tokens) for s in train_snapshots]
    val_hashes = [view_hash(s.tokens) for s in val_snapshots]

    train_weights, train_clean, train_stats = build_train_weights(
        train_hashes, train_labels, train_depths
    )
    val_clean, val_stats = build_val_mask(val_hashes, train_hashes)
    clean_val_run_keys = {s.run_key for s, keep in zip(val_snapshots, val_clean) if keep}
    clean_val_groups = {s.group_id for s, keep in zip(val_snapshots, val_clean) if keep}
    print(f"  Model-view dedup: {train_stats}", flush=True)
    print(f"  Val model-view: {val_stats}", flush=True)

    def save_split(split, snapshots, labels, depths, weights, clean, hashes):
        ids = torch.tensor([s.tokens for s in snapshots], dtype=torch.long)
        label_t = torch.tensor(labels, dtype=torch.long)
        group_t = torch.tensor(
            [int(hashlib.sha256(s.group_id.encode()).hexdigest()[:12], 16) % (2**31)
             for s in snapshots], dtype=torch.long
        )
        depth_t = torch.tensor(depths, dtype=torch.long)
        torch.save(ids, CACHE_DIR / f"task_b_{split}_input_ids.pt")
        torch.save(label_t, CACHE_DIR / f"task_b_{split}_labels.pt")
        torch.save(group_t, CACHE_DIR / f"task_b_{split}_group_ids.pt")
        torch.save(depth_t, CACHE_DIR / f"task_b_{split}_depth_pcts.pt")
        torch.save(torch.tensor(weights, dtype=torch.float32), CACHE_DIR / f"task_b_{split}_sample_weights.pt")
        torch.save(torch.tensor(clean, dtype=torch.bool), CACHE_DIR / f"task_b_{split}_clean_mask.pt")
        with open(CACHE_DIR / f"task_b_{split}_view_hashes.json", "w") as f:
            json.dump(hashes, f)
        return ids

    train_ids = save_split("train", train_snapshots, train_labels, train_depths,
                           train_weights, train_clean, train_hashes)
    val_ids = save_split("val", val_snapshots, val_labels, val_depths,
                         np.ones(len(val_snapshots), dtype=np.float32), val_clean, val_hashes)

    common_meta = {
        "max_len": MAX_LEN,
        "model_view_len": MODEL_VIEW_LEN,
        "head_tokens": HEAD_TOKENS,
        "tail_tokens": TAIL_TOKENS,
        "model_head_tokens": MODEL_HEAD_TOKENS,
        "model_tail_tokens": MODEL_TAIL_TOKENS,
        "vocab_size": len(tokenizer.vocab),
        "label_map": label_map,
        "num_classes": len(failure_classes),
        "python_exceptions": PYTHON_EXCEPTIONS,
        "raw_run_id_overlap": raw_id_overlap,
    }
    train_meta = {
        **common_meta,
        "num_samples": len(train_snapshots),
        "num_samples_official": EXPECTED_B_TRAIN_ROWS,
        "depth_distribution": dict(Counter(train_depths)),
        "run_keys": len(train_run_keys),
        "groups": len(train_groups),
        "dedup": train_stats,
    }
    val_meta = {
        **common_meta,
        "num_samples": len(val_snapshots),
        "num_samples_official": EXPECTED_B_VAL_ROWS,
        "depth_distribution": dict(Counter(val_depths)),
        "run_keys": len(val_run_keys),
        "groups": len(val_groups),
        "dedup": val_stats,
        "clean_run_keys": len(clean_val_run_keys),
        "clean_groups": len(clean_val_groups),
        "leakage_contract": {
            "global_run_key_disjoint": True,
            "group_disjoint": True,
            "model_view_train_overlap_rows": val_stats["val_cross_split_duplicate_rows"],
            "clean_mask_excludes_train_overlap": True,
        },
    }
    with open(CACHE_DIR / "task_b_train_meta.json", "w") as f:
        json.dump(train_meta, f, indent=2)
    with open(CACHE_DIR / "task_b_val_meta.json", "w") as f:
        json.dump(val_meta, f, indent=2)
    print(f"  Task B train tensors: {tuple(train_ids.shape)} | val tensors: {tuple(val_ids.shape)}", flush=True)
    return {"train_meta": train_meta, "val_meta": val_meta, "label_map": label_map}


def main():
    task_a_only = '--task-a-only' in sys.argv
    print("=" * 60)
    print("STEP 3: TRAIN-ONLY LOG NORMALIZER + TOKENIZER + CACHING")
    if task_a_only:
        print("MODE: Task A only (Task B cache is left untouched)")
    print("=" * 60)

    # 1. Load data
    print("\n[1/6] Loading train/val tables...")
    binary_train_val = pd.read_csv(WORK_DIR / "binary_train_val.csv")
    failure_train_val = pd.read_csv(WORK_DIR / "failure_train_val.csv")
    index_train_val = pd.read_csv(WORK_DIR / "index_train_val.csv")

    print(f"  binary_train_val: {len(binary_train_val)} rows")
    print(f"  failure_train_val: {len(failure_train_val)} rows")
    print(f"  index_train_val: {len(index_train_val)} rows")

    snapshot_root = DATA_DIR  # CSV paths already include "snapshots/" prefix

    # 2. Initialize normalizer
    print("\n[2/6] Initializing LogNormalizer...")
    normalizer = LogNormalizer()

    # 3. Initialize tokenizer
    print("\n[3/6] Initializing TrainOnlyTokenizer...")
    tokenizer = TrainOnlyTokenizer(vocab_size=VOCAB_SIZE)

    # 4. Prepare Task A data (this fits the tokenizer)
    print("\n[4/6] Processing Task A (Binary)...")
    task_a_meta = prepare_task_a_data(
        binary_train_val, index_train_val, normalizer, tokenizer,
        snapshot_root, WORK_DIR / "cv_folds"
    )

    # 5. Prepare Task B data (uses already-fitted tokenizer)
    if task_a_only:
        print("\n[5/6] Processing Task B (Failure)... SKIPPED (--task-a-only)")
        task_b_meta = None
    else:
        print("\n[5/6] Processing Task B (Failure)...")
        task_b_meta = prepare_task_b_data(
            failure_train_val, index_train_val, normalizer, tokenizer,
            snapshot_root, WORK_DIR / "cv_folds"
        )

    # 6. Save tokenizer copies and complete metadata
    print("\n[6/6] Saving tokenizer and metadata...")
    tokenizer.save(CACHE_DIR / "tokenizer.pkl")
    tokenizer.save(CACHE_DIR / "tokenizer_task_a.pkl")
    tokenizer.save(CACHE_DIR / "tokenizer_task_b.pkl")
    missing_exceptions = [t for t in PYTHON_EXCEPTIONS if tokenizer.vocab.get(t) in (None, tokenizer.vocab[UNK_TOKEN])]
    if missing_exceptions:
        raise RuntimeError(f"exception tokens missing from vocabulary: {missing_exceptions}")
    exception_ids = {t: tokenizer.vocab[t] for t in PYTHON_EXCEPTIONS}
    if len(set(exception_ids.values())) != len(PYTHON_EXCEPTIONS):
        raise RuntimeError("exception tokens do not have distinct token IDs")
    print(f"  Exception token IDs: {exception_ids}", flush=True)

    combined_meta = {
        'vocab_size': len(tokenizer.vocab),
        'max_len': MAX_LEN,
        'model_view_len': MODEL_VIEW_LEN,
        'head_tokens': HEAD_TOKENS,
        'tail_tokens': TAIL_TOKENS,
        'model_head_tokens': MODEL_HEAD_TOKENS,
        'model_tail_tokens': MODEL_TAIL_TOKENS,
        'special_tokens': SPECIAL_TOKENS,
        'python_exception_token_ids': exception_ids,
        'task_a': task_a_meta,
        'task_b': task_b_meta,
        'task_a_only': task_a_only,
        'canonical_patterns': [str(p.pattern) for p, _ in CANONICAL_PATTERNS],
        'boilerplate_patterns': [str(p.pattern) for p in BOILERPLATE_PATTERNS],
        'random_state': RANDOM_STATE
    }

    with open(CACHE_DIR / "preprocessing_meta.json", 'w') as f:
        json.dump(combined_meta, f, indent=2)

    print(f"  Metadata saved to: {CACHE_DIR / 'preprocessing_meta.json'}")

    # Verify cache integrity
    print("\n[VERIFY] Cache integrity check...")
    tasks = ['task_a'] if task_a_only else ['task_a', 'task_b']
    for task in tasks:
        for split in ['train', 'val']:
            ids = torch.load(CACHE_DIR / f"{task}_{split}_input_ids.pt")
            labels = torch.load(CACHE_DIR / f"{task}_{split}_labels.pt")
            assert len(ids) == len(labels), f"{task} {split}: length mismatch"
            assert ids.shape[1] == MAX_LEN, f"{task} {split}: wrong seq len {ids.shape[1]}"
            print(f"  {task} {split}: {ids.shape} [OK]")

    print("\n" + "=" * 60)
    print("PREPROCESSING & CACHING COMPLETE")
    print("=" * 60)
    print(f"[OK] Cache directory: {CACHE_DIR}")
    print(f"[OK] Tokenizer: {CACHE_DIR / 'tokenizer.pkl'} (vocab: {len(tokenizer.vocab)})")
    print("[OK] Task A train/val tensors cached")
    if not task_a_only:
        print("[OK] Task B train/val tensors cached")
    print(f"[OK] Cache window: {HEAD_TOKENS} + {TAIL_TOKENS} = {MAX_LEN}")
    print(f"[OK] Model view: {MODEL_HEAD_TOKENS} + {MODEL_TAIL_TOKENS} = {MODEL_VIEW_LEN}")
    print("[OK] Train-only vocabulary (no val/test leakage)")

    return 0


if __name__ == "__main__":
    sys.exit(main())