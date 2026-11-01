"""
BiLSTM Architectures - 3 Generations
=====================================
Gen 1: BiLSTMBaseline - Simple but strong
Gen 2: BiLSTMAttention - Adds masked self-attention pooling
Gen 3: HierarchicalConvBiLSTMAttention - Adds multi-scale conv stem + optional horizon conditioning
"""

import torch
import torch.nn as nn
import torch.nn.functional as F
from dataclasses import dataclass
from typing import Optional, Tuple, List


@dataclass
class ModelConfig:
    """Shared model configuration."""
    vocab_size: int = 21105
    max_len: int = 1536
    embed_dim: int = 192
    hidden_dim: int = 192
    num_layers: int = 2
    bidirectional: bool = True
    dropout: float = 0.3
    num_classes: int = 2
    pad_idx: int = 0

    # Gen 3 specific
    use_horizon_conditioning: bool = False
    horizon_embed_dim: int = 16

    def __post_init__(self):
        self.lstm_hidden = self.hidden_dim * 2 if self.bidirectional else self.hidden_dim


# ──────────────────────────────────────────────────────────────────────────────
# Utility Functions
# ──────────────────────────────────────────────────────────────────────────────

def masked_mean_pool(x: torch.Tensor, lengths: torch.Tensor) -> torch.Tensor:
    """
    Mean pooling over non-PAD tokens.
    x: [B, L, H], lengths: [B]
    Returns: [B, H]
    """
    mask = torch.arange(x.size(1), device=x.device).expand(x.size(0), -1) < lengths.unsqueeze(1)
    mask = mask.unsqueeze(-1).float()  # [B, L, 1]
    summed = (x * mask).sum(dim=1)
    counts = lengths.unsqueeze(1).float().clamp(min=1)
    return summed / counts


def masked_max_pool(x: torch.Tensor, lengths: torch.Tensor) -> torch.Tensor:
    """
    Max pooling over non-PAD tokens.
    x: [B, L, H], lengths: [B]
    Returns: [B, H]
    """
    mask = torch.arange(x.size(1), device=x.device).expand(x.size(0), -1) < lengths.unsqueeze(1)
    mask = mask.unsqueeze(-1).float()  # [B, L, 1]
    # Set PAD positions to -inf for max pooling
    x_masked = x.masked_fill(~mask.bool(), float('-inf'))
    return x_masked.max(dim=1)[0]


def create_padding_mask(lengths: torch.Tensor, max_len: int) -> torch.Tensor:
    """Create boolean mask: True for valid positions, False for PAD."""
    return torch.arange(max_len, device=lengths.device).expand(lengths.size(0), -1) < lengths.unsqueeze(1)


# ──────────────────────────────────────────────────────────────────────────────
# Gen 1: BiLSTMBaseline
# ──────────────────────────────────────────────────────────────────────────────

class BiLSTMBaseline(nn.Module):
    """
    Gen 1: Standard BiLSTM with masked mean+max pooling.

    Architecture:
    - Embedding(vocab_size, embed_dim, padding_idx=pad_idx) → SpatialDropout1d(dropout)
    - 2-Layer BiLSTM(embed_dim, hidden_dim, bidirectional=True) → lstm_hidden
    - Masked Mean Pooling + Masked Max Pooling → concat 2*lstm_hidden
    - LayerNorm(2*lstm_hidden) → MLP Classifier (2*lstm_hidden → 256 → num_classes)
    """

    def __init__(self, config: ModelConfig):
        super().__init__()
        self.config = config
        lstm_hidden = config.lstm_hidden

        # Embedding + Spatial Dropout
        self.embedding = nn.Embedding(config.vocab_size, config.embed_dim, padding_idx=config.pad_idx)
        self.spatial_dropout = nn.Dropout2d(config.dropout)  # SpatialDropout1d = Dropout2d on (B, 1, L, D)

        # BiLSTM
        self.lstm = nn.LSTM(
            input_size=config.embed_dim,
            hidden_size=config.hidden_dim,
            num_layers=config.num_layers,
            bidirectional=config.bidirectional,
            batch_first=True,
            dropout=config.dropout if config.num_layers > 1 else 0
        )

        # Pooling + Classifier
        self.pool_norm = nn.LayerNorm(2 * lstm_hidden)
        self.classifier = nn.Sequential(
            nn.Linear(2 * lstm_hidden, 256),
            nn.ReLU(),
            nn.Dropout(config.dropout),
            nn.Linear(256, config.num_classes)
        )

        self._init_weights()

    def _init_weights(self):
        """Initialize weights."""
        nn.init.xavier_uniform_(self.embedding.weight)
        nn.init.constant_(self.embedding.weight[self.config.pad_idx], 0)

        for name, param in self.lstm.named_parameters():
            if 'weight_ih' in name:
                nn.init.xavier_uniform_(param)
            elif 'weight_hh' in name:
                nn.init.orthogonal_(param)
            elif 'bias' in name:
                nn.init.constant_(param, 0)
                # Forget gate bias = 1
                n = param.size(0)
                param.data[n//4:n//2].fill_(1.0)

        for m in self.classifier.modules():
            if isinstance(m, nn.Linear):
                nn.init.xavier_uniform_(m.weight)
                nn.init.constant_(m.bias, 0)

    def forward(self, input_ids: torch.Tensor, lengths: torch.Tensor) -> torch.Tensor:
        """
        input_ids: [B, L] (padded)
        lengths: [B] actual non-PAD lengths
        Returns: logits [B, num_classes]
        """
        B, L = input_ids.shape

        # Embedding: [B, L, D]
        x = self.embedding(input_ids)

        # Spatial Dropout: reshape to [B, 1, L, D] → Dropout2d → [B, L, D]
        x = x.unsqueeze(1)  # [B, 1, L, D]
        x = self.spatial_dropout(x)
        x = x.squeeze(1)    # [B, L, D]

        # Pack for LSTM (skip PAD tokens)
        packed = nn.utils.rnn.pack_padded_sequence(
            x, lengths.cpu(), batch_first=True, enforce_sorted=False
        )

        # LSTM forward
        packed_out, _ = self.lstm(packed)

        # Unpack: [B, L, lstm_hidden]
        out, _ = nn.utils.rnn.pad_packed_sequence(packed_out, batch_first=True, total_length=L)

        # Masked pooling
        mean_pooled = masked_mean_pool(out, lengths)   # [B, lstm_hidden]
        max_pooled = masked_max_pool(out, lengths)     # [B, lstm_hidden]

        # Concat + classify
        pooled = torch.cat([mean_pooled, max_pooled], dim=-1)  # [B, 2*lstm_hidden]
        pooled = self.pool_norm(pooled)
        logits = self.classifier(pooled)

        return logits


# ──────────────────────────────────────────────────────────────────────────────
# Gen 2: BiLSTMAttention
# ──────────────────────────────────────────────────────────────────────────────

class MaskedMultiHeadAttentionPooling(nn.Module):
    """
    Multi-head self-attention pooling with PAD masking.
    Attention weights: softmax(QK^T/sqrt(d)) with -inf on PAD positions.
    """

    def __init__(self, embed_dim: int, num_heads: int = 4, dropout: float = 0.1):
        super().__init__()
        assert embed_dim % num_heads == 0
        self.embed_dim = embed_dim
        self.num_heads = num_heads
        self.head_dim = embed_dim // num_heads

        self.qkv = nn.Linear(embed_dim, 3 * embed_dim)
        self.out_proj = nn.Linear(embed_dim, embed_dim)
        self.dropout = nn.Dropout(dropout)

        nn.init.xavier_uniform_(self.qkv.weight)
        nn.init.constant_(self.qkv.bias, 0)
        nn.init.xavier_uniform_(self.out_proj.weight)
        nn.init.constant_(self.out_proj.bias, 0)

    def forward(self, x: torch.Tensor, lengths: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        """
        x: [B, L, D], lengths: [B]
        Returns: (pooled [B, D], attention_weights [B, num_heads, L])
        """
        B, L, D = x.shape

        # Create padding mask: True for valid, False for PAD
        mask = create_padding_mask(lengths, L)  # [B, L]
        attn_mask = mask.unsqueeze(1).unsqueeze(2)  # [B, 1, 1, L] for broadcast

        # QKV projection
        qkv = self.qkv(x)  # [B, L, 3*D]
        qkv = qkv.reshape(B, L, 3, self.num_heads, self.head_dim).permute(2, 0, 3, 1, 4)
        q, k, v = qkv[0], qkv[1], qkv[2]  # Each: [B, H, L, d]

        # Attention scores
        scores = torch.matmul(q, k.transpose(-2, -1)) / (self.head_dim ** 0.5)  # [B, H, L, L]

        # Mask PAD positions with -inf before softmax
        scores = scores.masked_fill(~attn_mask, float('-inf'))

        attn_weights = F.softmax(scores, dim=-1)  # [B, H, L, L]
        attn_weights = self.dropout(attn_weights)

        # Apply attention to values
        out = torch.matmul(attn_weights, v)  # [B, H, L, d]
        out = out.transpose(1, 2).reshape(B, L, D)  # [B, L, D]
        out = self.out_proj(out)  # [B, L, D]

        # Pool: weighted sum using mean attention across heads
        mean_attn = attn_weights.mean(dim=1)  # [B, L, L]
        # Use diagonal (self-attention weights) or mean across query positions
        pooled = (out * mean_attn.mean(dim=-1, keepdim=True)).sum(dim=1)  # [B, D]

        # Return attention weights for inspection (mean across heads, mean across queries)
        attn_for_inspection = mean_attn.mean(dim=1)  # [B, L]

        return pooled, attn_for_inspection


class BiLSTMAttention(nn.Module):
    """
    Gen 2: BiLSTM + Masked Multi-Head Self-Attention Pooling.

    Architecture:
    - Same backbone as Gen 1
    - BiLSTM output → Masked Multi-Head Self-Attention Pooling
    - Concat: Attention Pooled (lstm_hidden) + Mean Pooled (lstm_hidden) + Max Pooled (lstm_hidden) = 3*lstm_hidden
    - Residual LayerNorm → MLP Classifier
    """

    def __init__(self, config: ModelConfig):
        super().__init__()
        self.config = config
        lstm_hidden = config.lstm_hidden

        # Embedding + Spatial Dropout
        self.embedding = nn.Embedding(config.vocab_size, config.embed_dim, padding_idx=config.pad_idx)
        self.spatial_dropout = nn.Dropout2d(config.dropout)

        # BiLSTM
        self.lstm = nn.LSTM(
            input_size=config.embed_dim,
            hidden_size=config.hidden_dim,
            num_layers=config.num_layers,
            bidirectional=config.bidirectional,
            batch_first=True,
            dropout=config.dropout if config.num_layers > 1 else 0
        )

        # Attention pooling
        self.attention_pool = MaskedMultiHeadAttentionPooling(
            embed_dim=lstm_hidden,
            num_heads=4,
            dropout=config.dropout
        )

        # Classifier: 3 * lstm_hidden → num_classes
        self.pool_norm = nn.LayerNorm(3 * lstm_hidden)
        self.classifier = nn.Sequential(
            nn.Linear(3 * lstm_hidden, 256),
            nn.ReLU(),
            nn.Dropout(config.dropout),
            nn.Linear(256, config.num_classes)
        )

        self._init_weights()

    def _init_weights(self):
        nn.init.xavier_uniform_(self.embedding.weight)
        nn.init.constant_(self.embedding.weight[self.config.pad_idx], 0)

        for name, param in self.lstm.named_parameters():
            if 'weight_ih' in name:
                nn.init.xavier_uniform_(param)
            elif 'weight_hh' in name:
                nn.init.orthogonal_(param)
            elif 'bias' in name:
                nn.init.constant_(param, 0)
                n = param.size(0)
                param.data[n//4:n//2].fill_(1.0)

        for m in self.classifier.modules():
            if isinstance(m, nn.Linear):
                nn.init.xavier_uniform_(m.weight)
                nn.init.constant_(m.bias, 0)

    def forward(self, input_ids: torch.Tensor, lengths: torch.Tensor,
                return_attention: bool = False) -> Tuple[torch.Tensor, Optional[torch.Tensor]]:
        """
        Returns: (logits [B, num_classes], attention_weights [B, L] or None)
        """
        B, L = input_ids.shape

        # Embedding
        x = self.embedding(input_ids)
        x = x.unsqueeze(1)
        x = self.spatial_dropout(x)
        x = x.squeeze(1)

        # Pack + LSTM
        packed = nn.utils.rnn.pack_padded_sequence(
            x, lengths.cpu(), batch_first=True, enforce_sorted=False
        )
        packed_out, _ = self.lstm(packed)
        out, _ = nn.utils.rnn.pad_packed_sequence(packed_out, batch_first=True, total_length=L)

        # Three pooling strategies
        mean_pooled = masked_mean_pool(out, lengths)   # [B, lstm_hidden]
        max_pooled = masked_max_pool(out, lengths)     # [B, lstm_hidden]
        attn_pooled, attn_weights = self.attention_pool(out, lengths)  # [B, lstm_hidden], [B, L]

        # Concat all three
        pooled = torch.cat([attn_pooled, mean_pooled, max_pooled], dim=-1)  # [B, 3*lstm_hidden]
        pooled = self.pool_norm(pooled)
        logits = self.classifier(pooled)

        if return_attention:
            return logits, attn_weights
        return logits


# ──────────────────────────────────────────────────────────────────────────────
# Gen 3: HierarchicalConvBiLSTMAttention
# ──────────────────────────────────────────────────────────────────────────────

class DepthwiseSeparableConv1d(nn.Module):
    """Depthwise separable 1D convolution."""

    def __init__(self, in_channels: int, out_channels: int, kernel_size: int, padding: int = 0):
        super().__init__()
        self.depthwise = nn.Conv1d(
            in_channels, in_channels, kernel_size,
            padding=padding, groups=in_channels, bias=False
        )
        self.pointwise = nn.Conv1d(in_channels, out_channels, 1, bias=False)
        self.bn = nn.BatchNorm1d(out_channels)
        self.act = nn.GELU()

        nn.init.kaiming_normal_(self.depthwise.weight)
        nn.init.kaiming_normal_(self.pointwise.weight)
        nn.init.constant_(self.bn.weight, 1)
        nn.init.constant_(self.bn.bias, 0)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: [B, C, L]
        x = self.depthwise(x)
        x = self.pointwise(x)
        x = self.bn(x)
        x = self.act(x)
        return x


class MultiScaleConvStem(nn.Module):
    """
    Multi-scale 1D depthwise/separable convolution stem.
    Captures local n-gram patterns (AssertionError, KeyError, HTTP 502, etc.)
    """

    def __init__(self, embed_dim: int, kernel_sizes: List[int] = [3, 5, 7], dropout: float = 0.1):
        super().__init__()
        self.convs = nn.ModuleList([
            DepthwiseSeparableConv1d(embed_dim, embed_dim, k, padding=k//2)
            for k in kernel_sizes
        ])
        self.fusion = nn.Conv1d(embed_dim * len(kernel_sizes), embed_dim, 1, bias=False)
        self.norm = nn.LayerNorm(embed_dim)
        self.dropout = nn.Dropout(dropout)

        nn.init.kaiming_normal_(self.fusion.weight)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        x: [B, L, D] (embeddings)
        Returns: [B, L, D]
        """
        # Transpose for Conv1d: [B, D, L]
        x = x.transpose(1, 2)

        # Multi-scale convolutions
        conv_outs = [conv(x) for conv in self.convs]  # Each: [B, D, L]
        x = torch.cat(conv_outs, dim=1)  # [B, D*len(kernels), L]

        # Fusion
        x = self.fusion(x)  # [B, D, L]
        x = x.transpose(1, 2)  # [B, L, D]
        x = self.norm(x)
        x = self.dropout(x)

        return x


class HorizonConditioner(nn.Module):
    """
    Optional horizon conditioning for Gen 3.
    Projects normalized depth_pct (0.25, 0.50, 0.75, 1.00) to embed_dim and adds to embeddings.
    Only enabled if it improves calibration without breaking Gate 2 monotonicity.
    """

    def __init__(self, embed_dim: int, horizon_embed_dim: int = 16):
        super().__init__()
        self.horizon_proj = nn.Sequential(
            nn.Linear(1, horizon_embed_dim),
            nn.GELU(),
            nn.Linear(horizon_embed_dim, embed_dim)
        )
        nn.init.xavier_uniform_(self.horizon_proj[0].weight)
        nn.init.constant_(self.horizon_proj[0].bias, 0)
        nn.init.xavier_uniform_(self.horizon_proj[2].weight)
        nn.init.constant_(self.horizon_proj[2].bias, 0)

    def forward(self, x: torch.Tensor, depth_pct: torch.Tensor) -> torch.Tensor:
        """
        x: [B, L, D], depth_pct: [B] (values: 25, 50, 75, 100)
        Returns: [B, L, D] with horizon conditioning added
        """
        # Normalize to [0, 1]
        h = depth_pct.float() / 100.0  # [B]
        h = h.unsqueeze(1).unsqueeze(1)  # [B, 1, 1]
        h_embed = self.horizon_proj(h)  # [B, 1, D]

        # Add to all positions (broadcast)
        return x + h_embed


class HierarchicalConvBiLSTMAttention(nn.Module):
    """
    Gen 3: Multi-scale Conv Stem + BiLSTM + Attention Pooling + Optional Horizon Conditioning.

    Architecture:
    - Embedding → SpatialDropout
    - MultiScaleConvStem (kernels 3, 5, 7) → captures local error n-grams
    - Optional: HorizonConditioner (adds depth_pct info to embeddings)
    - BiLSTM (same as Gen 2)
    - Attention Pooling (same as Gen 2)
    - Classifier (same as Gen 2)
    """

    def __init__(self, config: ModelConfig):
        super().__init__()
        self.config = config
        lstm_hidden = config.lstm_hidden

        # Embedding + Spatial Dropout
        self.embedding = nn.Embedding(config.vocab_size, config.embed_dim, padding_idx=config.pad_idx)
        self.spatial_dropout = nn.Dropout2d(config.dropout)

        # Multi-scale Conv Stem
        self.conv_stem = MultiScaleConvStem(config.embed_dim, kernel_sizes=[3, 5, 7], dropout=config.dropout)

        # Optional horizon conditioning
        self.use_horizon = config.use_horizon_conditioning
        if self.use_horizon:
            self.horizon_conditioner = HorizonConditioner(config.embed_dim, config.horizon_embed_dim)

        # BiLSTM
        self.lstm = nn.LSTM(
            input_size=config.embed_dim,
            hidden_size=config.hidden_dim,
            num_layers=config.num_layers,
            bidirectional=config.bidirectional,
            batch_first=True,
            dropout=config.dropout if config.num_layers > 1 else 0
        )

        # Attention pooling
        self.attention_pool = MaskedMultiHeadAttentionPooling(
            embed_dim=lstm_hidden,
            num_heads=4,
            dropout=config.dropout
        )

        # Classifier
        self.pool_norm = nn.LayerNorm(3 * lstm_hidden)
        self.classifier = nn.Sequential(
            nn.Linear(3 * lstm_hidden, 256),
            nn.ReLU(),
            nn.Dropout(config.dropout),
            nn.Linear(256, config.num_classes)
        )

        self._init_weights()

    def _init_weights(self):
        nn.init.xavier_uniform_(self.embedding.weight)
        nn.init.constant_(self.embedding.weight[self.config.pad_idx], 0)

        for name, param in self.lstm.named_parameters():
            if 'weight_ih' in name:
                nn.init.xavier_uniform_(param)
            elif 'weight_hh' in name:
                nn.init.orthogonal_(param)
            elif 'bias' in name:
                nn.init.constant_(param, 0)
                n = param.size(0)
                param.data[n//4:n//2].fill_(1.0)

        for m in self.classifier.modules():
            if isinstance(m, nn.Linear):
                nn.init.xavier_uniform_(m.weight)
                nn.init.constant_(m.bias, 0)

    def forward(self, input_ids: torch.Tensor, lengths: torch.Tensor,
                depth_pct: Optional[torch.Tensor] = None,
                return_attention: bool = False) -> Tuple[torch.Tensor, Optional[torch.Tensor]]:
        """
        input_ids: [B, L], lengths: [B], depth_pct: [B] (optional, for horizon conditioning)
        Returns: (logits [B, num_classes], attention_weights [B, L] or None)
        """
        B, L = input_ids.shape

        # Embedding
        x = self.embedding(input_ids)
        x = x.unsqueeze(1)
        x = self.spatial_dropout(x)
        x = x.squeeze(1)  # [B, L, D]

        # Conv Stem
        x = self.conv_stem(x)  # [B, L, D]

        # Horizon conditioning (optional)
        if self.use_horizon and depth_pct is not None:
            x = self.horizon_conditioner(x, depth_pct)

        # Pack + LSTM
        packed = nn.utils.rnn.pack_padded_sequence(
            x, lengths.cpu(), batch_first=True, enforce_sorted=False
        )
        packed_out, _ = self.lstm(packed)
        out, _ = nn.utils.rnn.pad_packed_sequence(packed_out, batch_first=True, total_length=L)

        # Three pooling strategies
        mean_pooled = masked_mean_pool(out, lengths)
        max_pooled = masked_max_pool(out, lengths)
        attn_pooled, attn_weights = self.attention_pool(out, lengths)

        # Concat all three
        pooled = torch.cat([attn_pooled, mean_pooled, max_pooled], dim=-1)
        pooled = self.pool_norm(pooled)
        logits = self.classifier(pooled)

        if return_attention:
            return logits, attn_weights
        return logits


# ──────────────────────────────────────────────────────────────────────────────
# Factory
# ──────────────────────────────────────────────────────────────────────────────

def create_model(gen: int, config: ModelConfig) -> nn.Module:
    """Factory function to create model by generation."""
    if gen == 1:
        return BiLSTMBaseline(config)
    elif gen == 2:
        return BiLSTMAttention(config)
    elif gen == 3:
        return HierarchicalConvBiLSTMAttention(config)
    else:
        raise ValueError(f"Unknown generation: {gen}. Must be 1, 2, or 3.")


def count_parameters(model: nn.Module) -> int:
    """Count trainable parameters."""
    return sum(p.numel() for p in model.parameters() if p.requires_grad)


# ──────────────────────────────────────────────────────────────────────────────
# Test / Demo
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Quick test
    config = ModelConfig(vocab_size=21105, num_classes=14)

    for gen in [1, 2, 3]:
        model = create_model(gen, config)
        params = count_parameters(model)
        print(f"Gen {gen}: {params:,} parameters")

        # Dummy forward
        B, L = 2, 100
        input_ids = torch.randint(0, 21105, (B, L))
        lengths = torch.tensor([80, 90])
        depth_pct = torch.tensor([100, 75]) if gen == 3 else None

        logits, attn = model(input_ids, lengths, depth_pct=depth_pct, return_attention=True)
        print(f"  Output shape: {logits.shape}")
        if attn is not None:
            print(f"  Attention shape: {attn.shape}")