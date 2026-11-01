"""
BiLSTM Training Engine for GTX 1650 Ti (4GB VRAM) - Optimized
==============================================================
Optimized for low-VRAM training with:
- Dynamic token slicing: 512 tokens (64 head + 448 tail) from cached 1536
- Length-bucketed batching + pack_padded_sequence (skips PAD tokens)
- FP16 with GradScaler (2x VRAM savings)
- Spatial Dropout on embeddings (anti-cheating)
- AdamW + OneCycleLR + gradient clipping
- EarlyStopping(patience=3) on Macro-F1
- num_workers=0 for Windows compatibility
"""

import os
import json
import time
import math
import gc
import random
import numpy as np
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, Dict, List, Tuple, Any, Union

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import Dataset, DataLoader, Sampler, Subset
from torch.amp import autocast, GradScaler
from torch.nn.utils.rnn import pack_padded_sequence, pad_packed_sequence

# Device setup
DEVICE = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
print(f"[BiLSTM Engine] Using device: {DEVICE}")
if DEVICE.type == 'cuda':
    print(f"[BiLSTM Engine] GPU: {torch.cuda.get_device_name(0)}")
    print(f"[BiLSTM Engine] VRAM: {torch.cuda.get_device_properties(0).total_memory / 1e9:.1f} GB")

# Numerical stability settings for FP16 training on GTX 1650 Ti
torch.set_float32_matmul_precision('high')
torch.backends.cudnn.benchmark = True
torch.backends.cudnn.allow_tf32 = True
torch.backends.cuda.matmul.allow_tf32 = True


# ──────────────────────────────────────────────────────────────────────────────
# Dynamic Token Slicing Dataset Wrapper
# ──────────────────────────────────────────────────────────────────────────────

class SlicedLogDataset(Dataset):
    """
    Wraps cached LogDataset and dynamically slices to 512 tokens:
    - 64 head tokens (early log context)
    - 448 tail tokens (terminal error window)
    Total: 512 tokens for GTX 1650 Ti 4GB VRAM.
    Returns: (input_ids, label, length, group_id, depth_pct)
    """

    def __init__(self, base_dataset: Dataset, head_tokens: int = 64,
                 tail_tokens: int = 448, weights: Optional[torch.Tensor] = None,
                 is_train: bool = False, header_dropout_p: float = 0.0,
                 seed: int = 20241201):
        self.base_dataset = base_dataset
        self.head_tokens = head_tokens
        self.tail_tokens = tail_tokens
        self.max_len = head_tokens + tail_tokens
        self.weights = weights
        self.is_train = is_train
        self.header_dropout_p = header_dropout_p
        self.rng = random.Random(seed)

    def __len__(self):
        return len(self.base_dataset)

    def __getitem__(self, idx):
        item = self.base_dataset[idx]

        # Handle both dict (LogDataset) and tuple (legacy) formats
        if isinstance(item, dict):
            # LogDataset format: {'input_ids', 'labels', 'group_id', 'depth_pct'}
            input_ids = item['input_ids']
            label = item['labels']
            orig_length = (input_ids != 0).sum().item()
            group_id = item.get('group_id', -1)
            depth_pct = item.get('depth_pct', 100)
            extra = (group_id, depth_pct)
        else:
            # Tuple format: (input_ids, label, orig_length, *extra)
            input_ids = item[0]
            label = item[1]
            orig_length = item[2]
            extra = item[3:] if len(item) > 3 else (-1, 100)

        # Dynamic slicing: head + tail
        actual_len = min(orig_length, len(input_ids))
        if actual_len <= self.max_len:
            # Already fits, no slicing needed
            sliced = input_ids[:actual_len]
            new_length = actual_len
        else:
            # Take head + tail
            head = input_ids[:self.head_tokens]
            tail = input_ids[actual_len - self.tail_tokens:actual_len]
            sliced = torch.cat([head, tail], dim=0)
            new_length = self.max_len

        # Anti-shortcut regularization: hide the setup header during training.
        if self.is_train and self.header_dropout_p > 0 and self.rng.random() < self.header_dropout_p:
            n_head = min(self.head_tokens, sliced.numel())
            sliced = sliced.clone()
            sliced[:n_head] = 0
            new_length = max(1, new_length)

        if self.weights is not None:
            weight = self.weights[idx]
            if not torch.is_tensor(weight):
                weight = torch.tensor(float(weight), dtype=torch.float32)
            return (sliced, label, new_length, *extra, weight)
        return (sliced, label, new_length, *extra)


# ──────────────────────────────────────────────────────────────────────────────
# Length-Bucketed Sampler
# ──────────────────────────────────────────────────────────────────────────────

class LengthBucketedSampler(Sampler[List[int]]):
    """
    Batches samples by sequence length to minimize padding.
    Groups similar lengths together → less PAD → less VRAM wasted → faster LSTM.
    """

    def __init__(
        self,
        dataset: Dataset,
        batch_size: int,
        shuffle: bool = True,
        num_buckets: int = 10,
        drop_last: bool = False
    ):
        self.dataset = dataset
        self.batch_size = batch_size
        self.shuffle = shuffle
        self.num_buckets = num_buckets
        self.drop_last = drop_last

        # Pre-compute lengths (non-PAD token count)
        print("[LengthBucketedSampler] Computing sequence lengths...")
        self.lengths = []
        for i in range(len(dataset)):
            item = dataset[i]
            # LogDataset returns dict with 'input_ids', 'labels', 'group_id', 'depth_pct'
            # SlicedLogDataset returns tuple (input_ids, label, length, group_id, depth_pct)
            if isinstance(item, dict):
                # LogDataset format: need to compute actual length from input_ids
                input_ids = item['input_ids']
                # Count non-PAD tokens (PAD=0)
                length = (input_ids != 0).sum().item()
            else:
                # Tuple format: (input_ids, label, length, *extra) - length is at index 2
                _, _, length = item[:3]
            self.lengths.append(length)
        self.lengths = torch.tensor(self.lengths)

        # Create buckets
        self._create_buckets()

    def _create_buckets(self):
        """Create length buckets using quantiles."""
        sorted_lengths, sorted_indices = torch.sort(self.lengths)
        n = len(sorted_lengths)
        bucket_size = math.ceil(n / self.num_buckets)

        self.buckets = []
        for i in range(self.num_buckets):
            start = i * bucket_size
            end = min((i + 1) * bucket_size, n)
            if start < end:
                self.buckets.append(sorted_indices[start:end].tolist())

        # Remove empty buckets
        self.buckets = [b for b in self.buckets if len(b) > 0]
        print(f"[LengthBucketedSampler] Created {len(self.buckets)} buckets")

    def __iter__(self):
        if self.shuffle:
            # Shuffle within each bucket
            for bucket in self.buckets:
                indices = torch.randperm(len(bucket)).tolist()
                bucket[:] = [bucket[i] for i in indices]

        # Yield batches from each bucket
        for bucket in self.buckets:
            for i in range(0, len(bucket), self.batch_size):
                batch = bucket[i:i + self.batch_size]
                if self.drop_last and len(batch) < self.batch_size:
                    continue
                yield batch

    def __len__(self):
        total = 0
        for bucket in self.buckets:
            n_batches = math.ceil(len(bucket) / self.batch_size) if not self.drop_last else len(bucket) // self.batch_size
            total += n_batches
        return total


# ──────────────────────────────────────────────────────────────────────────────
# Collate Function for Variable-Length Sequences
# ──────────────────────────────────────────────────────────────────────────────

def collate_fn(batch: List[Union[Dict, Tuple]]) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor, ...]:
    """
    Collate function for LogDataset outputs.
    Handles both dict format (LogDataset) and tuple format (SlicedLogDataset).
    Returns: (input_ids, labels, lengths, *extra)
    - input_ids: [B, max_len] padded
    - labels: [B] or [B, num_classes]
    - lengths: [B] actual non-PAD lengths
    - extra: group_id, depth_pct, etc.
    """
    # Unpack - handle both dict and tuple formats
    if isinstance(batch[0], dict):
        # LogDataset format: {'input_ids', 'labels', 'group_id', 'depth_pct'}
        input_ids = [item['input_ids'] for item in batch]
        labels = [item['labels'] for item in batch]
        # Compute actual length (non-PAD tokens)
        lengths = [(item['input_ids'] != 0).sum().item() for item in batch]
        extra = [(item.get('group_id', -1), item.get('depth_pct', 100)) for item in batch]
    else:
        # Tuple format: (input_ids, label, length, *extra)
        input_ids = [item[0] for item in batch]
        labels = [item[1] for item in batch]
        lengths = [item[2] for item in batch]
        extra = [item[3:] for item in batch]

    # Pad sequences to max length in batch
    max_len = max(lengths)
    input_ids_padded = []
    for seq in input_ids:
        if len(seq) < max_len:
            pad_len = max_len - len(seq)
            input_ids_padded.append(F.pad(seq, (0, pad_len), value=0))
        else:
            input_ids_padded.append(seq[:max_len])

    input_ids = torch.stack(input_ids_padded)
    labels = torch.stack(labels) if isinstance(labels[0], torch.Tensor) else torch.tensor(labels)
    lengths = torch.tensor(lengths, dtype=torch.long)

    # Handle extra fields
    if extra and len(extra[0]) > 0:
        extra_tensors = []
        for i in range(len(extra[0])):
            vals = [e[i] for e in extra]
            if isinstance(vals[0], torch.Tensor):
                extra_tensors.append(torch.stack(vals))
            else:
                extra_tensors.append(torch.tensor(vals))
        return (input_ids, labels, lengths, *extra_tensors)

    return input_ids, labels, lengths


# ──────────────────────────────────────────────────────────────────────────────
# Training Configuration
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class TrainingConfig:
    """Training hyperparameters optimized for GTX 1650 Ti (4GB VRAM)."""
    # Model
    vocab_size: int = 21105
    max_len: int = 512          # Dynamic sliced length (64 head + 448 tail)
    embed_dim: int = 128
    hidden_dim: int = 128
    num_layers: int = 2
    bidirectional: bool = True
    dropout: float = 0.2
    num_classes: int = 2
    pad_idx: int = 0

    # Training
    batch_size: int = 64        # Train batch size (eval uses 128)
    epochs: int = 10            # OneCycleLR total epochs (reduced from 12)
    lr: float = 1e-3            # AdamW lr
    weight_decay: float = 1e-5
    max_grad_norm: float = 1.0
    patience: int = 3           # EarlyStopping patience on Macro-F1

    # FP16
    use_fp16: bool = True

    # Length bucketing
    num_buckets: int = 10

    # Loss
    loss_type: str = "bce"  # "bce", "focal", "ce", "class_balanced_focal"
    focal_gamma: float = 2.0
    focal_alpha: Optional[float] = None
    class_weights: Optional[torch.Tensor] = None

    # Task B specific
    use_class_balanced_sampler: bool = False
    beta: float = 0.9999  # For class-balanced loss

    # OneCycleLR
    onecycle_pct_start: float = 0.3
    onecycle_div_factor: float = 25.0
    onecycle_final_div_factor: float = 1e4


# ──────────────────────────────────────────────────────────────────────────────
# Loss Functions
# ──────────────────────────────────────────────────────────────────────────────

class FocalLoss(nn.Module):
    """Focal Loss for imbalanced classification."""

    def __init__(self, gamma: float = 2.0, alpha: Optional[float] = None, reduction: str = 'mean'):
        super().__init__()
        self.gamma = gamma
        self.alpha = alpha
        self.reduction = reduction

    def forward(self, inputs: torch.Tensor, targets: torch.Tensor) -> torch.Tensor:
        if inputs.dim() == 1 or inputs.size(1) == 1:
            # Binary case
            inputs = inputs.squeeze(-1)
            p = torch.sigmoid(inputs)
            pt = p * targets + (1 - p) * (1 - targets)
            ce = F.binary_cross_entropy_with_logits(inputs, targets.float(), reduction='none')
        else:
            # Multi-class case
            ce = F.cross_entropy(inputs, targets, reduction='none')
            pt = torch.exp(-ce)

        loss = (1 - pt) ** self.gamma * ce

        if self.alpha is not None:
            if inputs.dim() == 1 or inputs.size(1) == 1:
                alpha_t = self.alpha * targets + (1 - self.alpha) * (1 - targets)
            else:
                alpha_t = self.alpha
            loss = alpha_t * loss

        if self.reduction == 'mean':
            return loss.mean()
        elif self.reduction == 'sum':
            return loss.sum()
        return loss


class ClassBalancedFocalLoss(nn.Module):
    """Class-Balanced Focal Loss: FL = -α(1-p)^γ log(p) with α = (1-β)/(1-β^n)"""

    def __init__(self, samples_per_class: List[int], gamma: float = 2.0, beta: float = 0.9999):
        super().__init__()
        self.gamma = gamma
        self.beta = beta

        # Compute class-balanced weights: α = (1-β)/(1-β^n)
        samples_per_class = torch.tensor(samples_per_class, dtype=torch.float)
        effective_num = 1.0 - torch.pow(beta, samples_per_class)
        weights = (1.0 - beta) / effective_num
        weights = weights / weights.sum() * len(samples_per_class)  # Normalize
        self.register_buffer('class_weights', weights)

    def forward(self, inputs: torch.Tensor, targets: torch.Tensor) -> torch.Tensor:
        ce = F.cross_entropy(inputs, targets, reduction='none')
        pt = torch.exp(-ce)
        alpha = self.class_weights[targets]
        loss = alpha * (1 - pt) ** self.gamma * ce
        return loss.mean()


def get_loss_fn(config: TrainingConfig, samples_per_class: Optional[List[int]] = None) -> nn.Module:
    """Factory for loss functions."""
    if config.loss_type == "bce":
        pos_weight = config.class_weights
        if pos_weight is not None and pos_weight.dim() == 1 and pos_weight.size(0) == 1:
            pos_weight = pos_weight[0]
        return nn.BCEWithLogitsLoss(pos_weight=pos_weight)

    elif config.loss_type == "focal":
        return FocalLoss(gamma=config.focal_gamma, alpha=config.focal_alpha)

    elif config.loss_type == "ce":
        return nn.CrossEntropyLoss(weight=config.class_weights)

    elif config.loss_type == "class_balanced_focal":
        if samples_per_class is None:
            raise ValueError("samples_per_class required for class_balanced_focal")
        return ClassBalancedFocalLoss(samples_per_class, gamma=config.focal_gamma, beta=config.beta)

    else:
        raise ValueError(f"Unknown loss_type: {config.loss_type}")


# ──────────────────────────────────────────────────────────────────────────────
# BiLSTM Trainer with OneCycleLR + EarlyStopping
# ──────────────────────────────────────────────────────────────────────────────

class BiLSTMTrainer:
    """
    High-performance BiLSTM trainer for GTX 1650 Ti.
    Handles FP16, length-bucketed batching, pack_padded_sequence, gradient clipping.
    Uses OneCycleLR with EarlyStopping(patience=3) on Macro-F1.
    """

    def __init__(
        self,
        model: nn.Module,
        train_loader: DataLoader,
        val_loader: DataLoader,
        config: TrainingConfig,
        samples_per_class: Optional[List[int]] = None,
        fold: int = 0,
        task_name: str = "task_a",
        checkpoint_dir: Optional[Path] = None
    ):
        self.model = model.to(DEVICE)
        self.train_loader = train_loader
        self.val_loader = val_loader
        self.config = config
        self.samples_per_class = samples_per_class
        self.fold = fold
        self.task_name = task_name
        self.checkpoint_dir = checkpoint_dir or Path("models")
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

        # Loss
        self.criterion = get_loss_fn(config, samples_per_class)

        # Optimizer
        self.optimizer = torch.optim.AdamW(
            model.parameters(),
            lr=config.lr,
            weight_decay=config.weight_decay
        )

        # OneCycleLR Scheduler
        steps_per_epoch = len(train_loader)
        self.scheduler = torch.optim.lr_scheduler.OneCycleLR(
            self.optimizer,
            max_lr=config.lr,
            epochs=config.epochs,
            steps_per_epoch=steps_per_epoch,
            pct_start=config.onecycle_pct_start,
            div_factor=config.onecycle_div_factor,
            final_div_factor=config.onecycle_final_div_factor,
            anneal_strategy='cos'
        )

        # FP16
        self.scaler = GradScaler('cuda', enabled=config.use_fp16 and DEVICE.type == 'cuda')

        # State
        self.best_val_metric = -1.0
        self.best_epoch = 0
        self.epochs_no_improve = 0
        self.history = {
            'train_loss': [],
            'val_loss': [],
            'val_macro_f1': [],
            'val_metrics': []
        }

    def train_epoch(self) -> float:
        """Train one epoch with FP16 and pack_padded_sequence. Includes strong NaN protection."""
        self.model.train()
        total_loss = 0.0
        num_batches = 0
        skipped_batches = 0

        for batch_idx, batch in enumerate(self.train_loader, 1):
            # Unpack batch (input_ids, labels, lengths, ...)
            input_ids = batch[0].to(DEVICE, non_blocking=True)
            labels = batch[1].to(DEVICE, non_blocking=True)
            lengths = batch[2].to(DEVICE, non_blocking=True)

            # Reshape labels for BCE loss: [B] -> [B, 1] and convert to float
            if self.config.loss_type == "bce" and labels.dim() == 1:
                labels = labels.unsqueeze(-1).float()

            self.optimizer.zero_grad(set_to_none=True)

            # Forward with FP16 - compute loss in FP32 for stability
            with autocast('cuda', enabled=self.config.use_fp16 and DEVICE.type == 'cuda'):
                logits = self.model(input_ids, lengths)

            # Check logits for NaN/Inf before loss computation
            if torch.isnan(logits).any() or torch.isinf(logits).any():
                skipped_batches += 1
                if skipped_batches <= 3:
                    print(f"  [WARN] skipped non-finite batch {batch_idx}", flush=True)
                continue

            # Compute loss in FP32 for numerical stability
            if self.config.use_fp16 and DEVICE.type == 'cuda':
                logits_fp32 = logits.float()
                if self.config.loss_type == "bce" and labels.dim() == 2 and labels.size(1) == 1:
                    labels_fp32 = labels.float()
                else:
                    labels_fp32 = labels
                loss = self.criterion(logits_fp32, labels_fp32)
            else:
                loss = self.criterion(logits, labels)

            # Check for NaN loss - skip batch if detected
            if torch.isnan(loss) or torch.isinf(loss):
                skipped_batches += 1
                if skipped_batches <= 3:
                    print(f"  [WARN] skipped non-finite batch {batch_idx}", flush=True)
                continue

            # Backward with GradScaler - CORRECT ORDER: step -> update -> scheduler.step
            self.scaler.scale(loss).backward()
            self.scaler.unscale_(self.optimizer)
            torch.nn.utils.clip_grad_norm_(self.model.parameters(), self.config.max_grad_norm)
            self.scaler.step(self.optimizer)
            self.scaler.update()
            # Step scheduler per batch (OneCycleLR) - AFTER scaler.update()
            self.scheduler.step()

            # Check for NaN in parameters after step
            for p in self.model.parameters():
                if torch.isnan(p).any() or torch.isinf(p).any():
                    print(f"  [ERROR] NaN/Inf in model parameters after optimizer step! Restoring from best checkpoint...", flush=True)
                    return float('nan')

            total_loss += loss.item()
            num_batches += 1
            if batch_idx % 50 == 0:
                print(f"  batch {batch_idx}/{len(self.train_loader)} loss={loss.item():.4f} "
                      f"lr={self.optimizer.param_groups[0]['lr']:.2e}", flush=True)

        if skipped_batches > 0:
            print(f"  [INFO] Skipped {skipped_batches} batches due to NaN/Inf loss")

        return total_loss / max(num_batches, 1)

    @torch.inference_mode()
    def evaluate(
        self,
        loader: DataLoader,
        depths: List[int] = [25, 50, 75, 100],
        return_predictions: bool = False
    ) -> Dict[str, Any]:
        """
        Evaluate model on loader.
        Returns per-depth metrics + overall.
        Uses torch.inference_mode() for memory efficiency and immediate numpy conversion.
        """
        self.model.eval()

        all_logits_list = []
        all_labels_list = []
        all_depth_pcts_list = []

        total_loss = 0.0
        num_batches = 0

        for batch_idx, batch in enumerate(loader, 1):
            input_ids = batch[0].to(DEVICE, non_blocking=True)
            labels = batch[1].to(DEVICE, non_blocking=True)
            lengths = batch[2].to(DEVICE, non_blocking=True)

            # Get depth_pct if available (index 3 in extra)
            depth_pcts = batch[3].to(DEVICE, non_blocking=True) if len(batch) > 3 else None

            # Reshape labels for BCE loss: [B] -> [B, 1] and convert to float
            if self.config.loss_type == "bce" and labels.dim() == 1:
                labels = labels.unsqueeze(-1).float()

            with autocast('cuda', enabled=self.config.use_fp16 and DEVICE.type == 'cuda'):
                logits = self.model(input_ids, lengths)
                loss = self.criterion(logits, labels)

            total_loss += loss.item()
            num_batches += 1
            if batch_idx % 50 == 0:
                print(f"  eval batch {batch_idx}/{len(loader)}", flush=True)

            # IMMEDIATE conversion to numpy - detach and move to CPU
            all_logits_list.append(logits.float().detach().cpu().numpy())
            all_labels_list.append(labels.detach().cpu().numpy())
            if depth_pcts is not None:
                all_depth_pcts_list.append(depth_pcts.detach().cpu().numpy())

            # Clear GPU tensors immediately
            del input_ids, labels, lengths, logits, loss
            if depth_pcts is not None:
                del depth_pcts

        if num_batches == 0:
            return {'loss': 0.0}

        # Concatenate numpy arrays (no GPU memory)
        all_logits_np = np.concatenate(all_logits_list, axis=0)
        all_labels_np = np.concatenate(all_labels_list, axis=0)
        if all_depth_pcts_list:
            all_depth_pcts_np = np.concatenate(all_depth_pcts_list, axis=0)
        else:
            all_depth_pcts_np = None

        # Clear lists to free memory (but keep concatenated arrays for metrics)
        del all_logits_list, all_labels_list, all_depth_pcts_list
        gc.collect()
        if DEVICE.type == 'cuda':
            torch.cuda.empty_cache()

        # Compute metrics per depth
        metrics = {'loss': total_loss / num_batches}

        if self.config.num_classes == 2:
            metrics.update(self._compute_binary_metrics(
                all_logits_np, all_labels_np, all_depth_pcts_np, depths, return_predictions
            ))
        else:
            metrics.update(self._compute_multiclass_metrics(
                all_logits_np, all_labels_np, all_depth_pcts_np, depths, return_predictions
            ))

        return metrics

    def _compute_binary_metrics(
        self,
        logits_np: np.ndarray,
        labels_np: np.ndarray,
        depth_pcts_np: Optional[np.ndarray],
        depths: List[int],
        return_predictions: bool
    ) -> Dict[str, Any]:
        """Compute binary classification metrics per depth. All inputs are numpy arrays."""
        from sklearn.metrics import (
            accuracy_score, precision_score, recall_score, f1_score,
            roc_auc_score, average_precision_score, confusion_matrix
        )

        probs = 1.0 / (1.0 + np.exp(-logits_np))  # sigmoid
        preds = (probs > 0.5).astype(int)

        metrics = {}

        # Overall
        metrics['overall'] = {
            'accuracy': accuracy_score(labels_np, preds),
            'precision': precision_score(labels_np, preds, zero_division=0),
            'recall': recall_score(labels_np, preds, zero_division=0),
            'f1_binary': f1_score(labels_np, preds, zero_division=0),
            'f1_macro': f1_score(labels_np, preds, average='macro', zero_division=0),
            'f1_weighted': f1_score(labels_np, preds, average='weighted', zero_division=0),
            'roc_auc': roc_auc_score(labels_np, probs) if len(set(labels_np)) > 1 else 0.0,
            'pr_auc': average_precision_score(labels_np, probs) if len(set(labels_np)) > 1 else 0.0,
            'confusion_matrix': confusion_matrix(labels_np, preds).tolist()
        }

        # Per depth
        if depth_pcts_np is not None:
            for depth in depths:
                mask = depth_pcts_np == depth
                if mask.sum() == 0:
                    continue
                d_labels = labels_np[mask]
                d_preds = preds[mask]
                d_probs = probs[mask]

                metrics[f'depth_{depth}'] = {
                    'accuracy': accuracy_score(d_labels, d_preds),
                    'precision': precision_score(d_labels, d_preds, zero_division=0),
                    'recall': recall_score(d_labels, d_preds, zero_division=0),
                    'f1_binary': f1_score(d_labels, d_preds, zero_division=0),
                    'f1_macro': f1_score(d_labels, d_preds, average='macro', zero_division=0),
                    'f1_weighted': f1_score(d_labels, d_preds, average='weighted', zero_division=0),
                    'roc_auc': roc_auc_score(d_labels, d_probs) if len(set(d_labels)) > 1 else 0.0,
                    'pr_auc': average_precision_score(d_labels, d_probs) if len(set(d_labels)) > 1 else 0.0,
                    'confusion_matrix': confusion_matrix(d_labels, d_preds).tolist(),
                    'n_samples': int(mask.sum())
                }

        if return_predictions:
            metrics['predictions'] = probs.tolist()
            metrics['labels'] = labels_np.tolist()

        return metrics

    def _compute_multiclass_metrics(
        self,
        logits_np: np.ndarray,
        labels_np: np.ndarray,
        depth_pcts_np: Optional[np.ndarray],
        depths: List[int],
        return_predictions: bool
    ) -> Dict[str, Any]:
        """Compute multi-class classification metrics per depth. All inputs are numpy arrays."""
        from sklearn.metrics import (
            accuracy_score, precision_score, recall_score, f1_score,
            confusion_matrix
        )

        # Softmax
        exp_logits = np.exp(logits_np - logits_np.max(axis=1, keepdims=True))
        probs = exp_logits / exp_logits.sum(axis=1, keepdims=True)
        preds = probs.argmax(axis=1)

        metrics = {}

        # Overall
        metrics['overall'] = {
            'accuracy': accuracy_score(labels_np, preds),
            'precision_macro': precision_score(labels_np, preds, average='macro', zero_division=0),
            'recall_macro': recall_score(labels_np, preds, average='macro', zero_division=0),
            'f1_macro': f1_score(labels_np, preds, average='macro', zero_division=0),
            'f1_weighted': f1_score(labels_np, preds, average='weighted', zero_division=0),
            'per_class_f1': f1_score(labels_np, preds, average=None, zero_division=0).tolist(),
            'confusion_matrix': confusion_matrix(labels_np, preds).tolist()
        }

        # Per depth
        if depth_pcts_np is not None:
            for depth in depths:
                mask = depth_pcts_np == depth
                if mask.sum() == 0:
                    continue
                d_labels = labels_np[mask]
                d_preds = preds[mask]

                metrics[f'depth_{depth}'] = {
                    'accuracy': accuracy_score(d_labels, d_preds),
                    'precision_macro': precision_score(d_labels, d_preds, average='macro', zero_division=0),
                    'recall_macro': recall_score(d_labels, d_preds, average='macro', zero_division=0),
                    'f1_macro': f1_score(d_labels, d_preds, average='macro', zero_division=0),
                    'f1_weighted': f1_score(d_labels, d_preds, average='weighted', zero_division=0),
                    'per_class_f1': f1_score(d_labels, d_preds, average=None, zero_division=0).tolist(),
                    'confusion_matrix': confusion_matrix(d_labels, d_preds).tolist(),
                    'n_samples': int(mask.sum())
                }

        if return_predictions:
            metrics['predictions'] = probs.tolist()
            metrics['labels'] = labels_np.tolist()

        return metrics

    def train(self) -> Dict[str, Any]:
        """Full training loop with EarlyStopping(patience=3) on Macro-F1. Includes NaN recovery."""
        print(f"\n[Fold {self.fold}] Starting training for {self.config.epochs} epochs (OneCycleLR)...")
        print(f"  Model: {sum(p.numel() for p in self.model.parameters()):,} parameters")
        print(f"  Train batches: {len(self.train_loader)}, Val batches: {len(self.val_loader)}")
        print(f"  FP16: {self.config.use_fp16 and DEVICE.type == 'cuda'}")
        print(f"  Loss: {self.config.loss_type}")
        print(f"  EarlyStopping: patience={self.config.patience} on Macro-F1")

        start_time = time.time()

        for epoch in range(self.config.epochs):
            epoch_start = time.time()

            # Train
            train_loss = self.train_epoch()

            # Check if training produced NaN (train_epoch returns NaN on parameter corruption)
            if math.isnan(train_loss) if isinstance(train_loss, float) else torch.isnan(torch.tensor(train_loss)):
                print(f"  [ERROR] NaN detected in training at epoch {epoch+1}. Restoring from best checkpoint...")
                best_ckpt = self.checkpoint_dir / f"{self.task_name}_fold{self.fold}_best.pt"
                if best_ckpt.exists():
                    self.load_checkpoint(best_ckpt)
                    # Reduce learning rate by half for recovery
                    for param_group in self.optimizer.param_groups:
                        param_group['lr'] *= 0.5
                    print(f"  [RECOVERY] Reduced LR to {self.optimizer.param_groups[0]['lr']:.2e}")
                else:
                    print(f"  [ERROR] No checkpoint to restore from. Stopping training.")
                    break
                # Skip validation for this epoch, continue to next
                train_loss = float('nan')
                val_metrics = {'loss': float('nan')}
                val_metric = 0.0
                # Count as no improvement
                self.epochs_no_improve += 1
            else:
                # Validate
                val_metrics = self.evaluate(self.val_loader)
                val_loss = val_metrics['loss']

                # Primary metric: macro F1
                if self.config.num_classes == 2:
                    val_metric = val_metrics.get('overall', {}).get('f1_macro', 0.0)
                else:
                    val_metric = val_metrics.get('overall', {}).get('f1_macro', 0.0)

                # Check if validation produced NaN (model parameters corrupted)
                if math.isnan(val_loss) if isinstance(val_loss, float) else torch.isnan(torch.tensor(val_loss)):
                    print(f"  [ERROR] NaN detected in validation at epoch {epoch+1}. Restoring from best checkpoint...")
                    best_ckpt = self.checkpoint_dir / f"{self.task_name}_fold{self.fold}_best.pt"
                    if best_ckpt.exists():
                        self.load_checkpoint(best_ckpt)
                        # Reduce learning rate by half for recovery
                        for param_group in self.optimizer.param_groups:
                            param_group['lr'] *= 0.5
                        print(f"  [RECOVERY] Reduced LR to {self.optimizer.param_groups[0]['lr']:.2e}")
                    else:
                        print(f"  [ERROR] No checkpoint to restore from. Stopping training.")
                        break
                    # Don't update metrics for this epoch, count as no improvement
                    val_metric = 0.0
                    self.epochs_no_improve += 1

            self.history['train_loss'].append(train_loss)
            self.history['val_loss'].append(val_metrics['loss'])
            self.history['val_macro_f1'].append(val_metric)
            self.history['val_metrics'].append(val_metrics)

            epoch_time = time.time() - epoch_start
            current_lr = self.optimizer.param_groups[0]['lr']

            print(f"  Epoch {epoch+1:2d}/{self.config.epochs} | "
                  f"Train Loss: {train_loss:.4f} | Val Loss: {val_metrics['loss']:.4f} | "
                  f"Val Macro-F1: {val_metric:.4f} | Time: {epoch_time:.1f}s | "
                  f"LR: {current_lr:.2e}")

            # Early stopping / checkpoint (only if validation was valid)
            if val_metric > self.best_val_metric and val_metric > 0:
                self.best_val_metric = val_metric
                self.best_epoch = epoch
                self.epochs_no_improve = 0

                # Save best checkpoint
                ckpt_path = self.checkpoint_dir / f"{self.task_name}_fold{self.fold}_best.pt"
                self.save_checkpoint(ckpt_path, epoch, val_metric)
                print(f"    [OK] New best model saved to {ckpt_path}")
            else:
                self.epochs_no_improve += 1
                if self.epochs_no_improve >= self.config.patience:
                    print(f"  Early stopping at epoch {epoch+1} (no improvement for {self.config.patience} epochs)")
                    break

        total_time = time.time() - start_time
        print(f"\n[Fold {self.fold}] Training complete in {total_time:.1f}s")
        print(f"  Best epoch: {self.best_epoch+1}, Best Macro-F1: {self.best_val_metric:.4f}")

        # Load best model for final evaluation
        best_ckpt = self.checkpoint_dir / f"{self.task_name}_fold{self.fold}_best.pt"
        if best_ckpt.exists():
            self.load_checkpoint(best_ckpt)

        final_metrics = self.evaluate(self.val_loader, return_predictions=True)
        final_metrics['history'] = self.history
        final_metrics['best_epoch'] = self.best_epoch
        final_metrics['best_val_macro_f1'] = self.best_val_metric
        final_metrics['total_time'] = total_time

        return final_metrics

    def save_checkpoint(self, path: Path, epoch: int, val_metric: float):
        """Save model checkpoint."""
        torch.save({
            'epoch': epoch,
            'model_state_dict': self.model.state_dict(),
            'optimizer_state_dict': self.optimizer.state_dict(),
            'scheduler_state_dict': self.scheduler.state_dict(),
            'scaler_state_dict': self.scaler.state_dict(),
            'val_metric': val_metric,
            'config': self.config.__dict__,
            'history': self.history
        }, path)

    def load_checkpoint(self, path: Path):
        """Load model checkpoint."""
        ckpt = torch.load(path, map_location=DEVICE, weights_only=False)
        self.model.load_state_dict(ckpt['model_state_dict'])
        self.optimizer.load_state_dict(ckpt['optimizer_state_dict'])
        self.scheduler.load_state_dict(ckpt['scheduler_state_dict'])
        self.scaler.load_state_dict(ckpt['scaler_state_dict'])
        self.best_val_metric = ckpt['val_metric']
        self.history = ckpt.get('history', self.history)
        print(f"  Loaded checkpoint from epoch {ckpt['epoch']+1}, val_metric={ckpt['val_metric']:.4f}")


# ──────────────────────────────────────────────────────────────────────────────
# Factory Functions
# ──────────────────────────────────────────────────────────────────────────────

def create_dataloaders(
    train_dataset: Dataset,
    val_dataset: Dataset,
    config: TrainingConfig,
    task_name: str = "task_a",
    head_tokens: int = 64,
    tail_tokens: int = 448,
    train_header_dropout_p: float = 0.0,
    train_weights: Optional[torch.Tensor] = None,
    val_weights: Optional[torch.Tensor] = None,
    train_sampler: Optional[Sampler] = None,
    use_length_buckets: bool = True,
) -> Tuple[DataLoader, DataLoader]:
    """Create train/val dataloaders with task-specific window and sampling."""

    train_dataset = SlicedLogDataset(
        train_dataset, head_tokens=head_tokens, tail_tokens=tail_tokens,
        weights=train_weights, is_train=True,
        header_dropout_p=train_header_dropout_p,
    )
    val_dataset = SlicedLogDataset(
        val_dataset, head_tokens=head_tokens, tail_tokens=tail_tokens,
        weights=val_weights, is_train=False, header_dropout_p=0.0,
    )

    if train_sampler is not None:
        train_loader = DataLoader(
            train_dataset,
            batch_size=config.batch_size,
            sampler=train_sampler,
            collate_fn=collate_fn,
            num_workers=0,
            pin_memory=DEVICE.type == 'cuda'
        )
    elif use_length_buckets:
        batch_sampler = LengthBucketedSampler(
            train_dataset,
            batch_size=config.batch_size,
            shuffle=True,
            num_buckets=config.num_buckets
        )
        train_loader = DataLoader(
            train_dataset,
            batch_sampler=batch_sampler,
            collate_fn=collate_fn,
            num_workers=0,
            pin_memory=DEVICE.type == 'cuda'
        )
    else:
        train_loader = DataLoader(
            train_dataset,
            batch_size=config.batch_size,
            shuffle=True,
            collate_fn=collate_fn,
            num_workers=0,
            pin_memory=DEVICE.type == 'cuda'
        )

    # Val: regular sequential with larger batch size for eval (128)
    eval_batch_size = 128 if config.batch_size == 64 else config.batch_size * 2
    val_loader = DataLoader(
        val_dataset,
        batch_size=eval_batch_size,
        shuffle=False,
        collate_fn=collate_fn,
        num_workers=0,
        pin_memory=DEVICE.type == 'cuda'
    )

    return train_loader, val_loader


def compute_class_weights(labels: torch.Tensor, num_classes: int) -> torch.Tensor:
    """Compute inverse frequency class weights."""
    class_counts = torch.bincount(labels, minlength=num_classes).float()
    weights = 1.0 / (class_counts + 1e-6)
    weights = weights / weights.sum() * num_classes
    return weights.to(DEVICE)


def compute_sqrt_inv_class_weights(labels: torch.Tensor, num_classes: int) -> torch.Tensor:
    """Compute sqrt-inverse class weights: 1/sqrt(n)."""
    class_counts = torch.bincount(labels, minlength=num_classes).float()
    weights = 1.0 / torch.sqrt(class_counts + 1e-6)
    weights = weights / weights.sum() * num_classes
    return weights.to(DEVICE)