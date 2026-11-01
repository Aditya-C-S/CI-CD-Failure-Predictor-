# ModernBERT Model Directory

**Status:** Awaiting weights and checkpoint ZIP package from teammate (**Aadarsh Koushik**).

## Expected Artifact Format
When teammate weights arrive, extract or copy the following files directly into this directory:
- `modernbert_depth025.pt` (or HuggingFace formatted directory with `config.json`, `tokenizer.json`, `model.safetensors`)
- `modernbert_depth050.pt`
- `modernbert_depth075.pt`
- `modernbert_depth100.pt`

## Reported Performance (Claims from Teammate Review Packet)
*Note: Evaluated strictly as reported claims; not independently reproduced at artifact level.*
- **Task A (Binary Early Failure Prediction):**
  - Depth 25%: Reported F1 ~ 0.88 - 0.92
  - Depth 100%: Reported F1 ~ 0.96 - 0.98
- **Inference Requirements:** PyTorch >= 2.2, Transformers >= 4.40, GPU recommended for low latency.

Once files are placed here, the predictor adapter in `src/prediction/predictor.py` will automatically load them.
