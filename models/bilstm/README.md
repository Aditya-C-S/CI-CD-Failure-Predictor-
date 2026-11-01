# BiLSTM Model Directory

**Status:** Awaiting weights and checkpoint ZIP package from teammate (**Aayush Jha**).

## Expected Artifact Format
When teammate weights arrive, extract or copy the following files directly into this directory:
- `bilstm_depth025.pt` (or PyTorch state dict / H5 weight bundle)
- `bilstm_depth050.pt`
- `bilstm_depth075.pt`
- `bilstm_depth100.pt`
- `vocab.json` / `tokenizer_config.json`

## Reported Performance (Claims from Teammate Review Packet)
*Note: Evaluated strictly as reported claims; not independently reproduced at artifact level.*
- **Task A (Binary Early Failure Prediction):**
  - Architecture: 768-token embedding + BiLSTM bidirectional recurrent layers.
  - Reported F1 across depths: ~ 0.85 - 0.90.
- **Inference Requirements:** PyTorch >= 2.2.

Once files are placed here, the predictor adapter in `src/prediction/predictor.py` will automatically load them.
