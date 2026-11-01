# Complete BiLSTM Log Predictor Environment

Reproducible package for the Task A (binary) and Task B (14-class) BiLSTM models,
the locked test vault, the preprocessing source, and the reported metrics.

---

## 1. Clarification: the Oct 23 weights ARE the final retrained weights

There is no newer checkpoint set. The files in `models/` here are the output of the
post-anonymization `day_shift_complete_pipeline.py` run that finished on
**2026-10-23 at 03:49**, and they supersede every earlier generation in the project
tree. Timestamps to verify against:

| File | Mtime |
|---|---|
| `models/task_a_champion.pt` | 2026-10-23 03:47 |
| `models/task_b_fold0_champion.pt` | 2026-10-23 02:53 |
| `models/task_b_fold1_champion.pt` | 2026-10-23 03:03 |
| `models/task_b_fold2_champion.pt` | 2026-10-23 03:14 |
| `models/task_b_fold3_champion.pt` | 2026-10-23 03:26 |
| `models/task_b_fold4_champion.pt` | 2026-10-23 03:38 |
| `work_data/cache/tokenizer.pkl` | 2026-10-23 01:15 |

Do not substitute files named `task_a_champion_stale_*`, `*_ablation_*`, `*_scout_*`,
`*_gen1_*`, or anything from `archive_leaky/`. Those are retired generations that
were kept for audit purposes; scoring against them will not reproduce the numbers.

## 2. Configuration

| Parameter | Value |
|---|---|
| Model input sequence length | **768 tokens** |
| Composition | 192 head tokens + 576 tail tokens |
| Tokenizer encode ceiling (pre-slice) | 1536 tokens |
| Vocabulary size | 19,083 |
| Task A classes | 2 (success / failure) |
| Task B classes | 14 (rolled up to F1-F7) |
| Depth buckets | 25 / 50 / 75 / 100 percent |

The 768-token value is `MODEL_VIEW_LEN` in `preprocess_and_cache.py`; the pipeline
splits it as `HEAD = 192`, `TAIL = 576`. Snapshots shorter than 768 tokens are seen
in full; longer ones keep 192 true head tokens and the last 576 tokens.

## 3. Critical warning: raw logs CANNOT be fed directly into the model

**This is the cause of a local evaluation collapsing to roughly 0.3764 ROC-AUC on
un-normalized logs.** Raw log text must pass through `LogNormalizer` before
tokenization. Skipping it does not merely lose accuracy - it feeds the model a
different distribution from the one it was trained on.

```python
from preprocess_and_cache import LogNormalizer

for rel_path in snapshot_paths:
    raw  = (DATA_DIR / rel_path).read_text(encoding="utf-8")
    text = LogNormalizer().normalize(raw)          # REQUIRED
    ids  = tokenizer.encode(text, max_len=1536, head_tokens=192)
```

`LogNormalizer` (defined in `preprocess_and_cache.py`) performs:

- **Synthetic-leakage scrub** - removes the scenario identifiers the model must not
  key on (`dependency-error-repo`, `buildx`, `test_valid_configuration`,
  `test_tls_handshake_failure`, `test_value_error`, and the wider
  `test_*` / runner-image family), replacing them with canonical placeholders.
- **Mojibake scrub** - strips the UTF-8 BOM (`\ufeff`) and its latin-1/cp1252
  double-decoded form (`i>>?`) that corrupted snapshots accumulate.
- **Boilerplate scrub** - removes ANSI colour escapes, `[TIMESTAMP]` /
  `<TIMESTAMP>` placeholders, and runner/job-step prefixes.
- **Canonical ID replacement** - timestamps, commit SHAs, IPs and ports are
  normalized on non-error lines. Lines containing `error`, `exception`,
  `traceback`, `assert`, `failed` or `failure` are *protected* from this pass so
  error semantics survive.

The normalizer is not optional or cosmetic. Treat it as part of the model.

## 4. Setup

```bash
python -m pip install -r requirements.txt
```

`requirements.txt` was not tracked in the original project; it was generated from
the run host. On a CPU-only machine use `torch==2.6.0` without the `+cu124` suffix.
The scripts select CUDA automatically when available and fall back to CPU.

**Hardcoded paths.** Every script pins the project root to
`F:\Capstone\Log Model`. After extracting the archive, rewrite that to wherever
you put it:

```bash
# Linux / macOS
grep -rl 'F:\\Capstone\\Log Model' --include=*.py . | xargs sed -i "s|F:\\\\Capstone\\\\Log Model|$(pwd -W 2>/dev/null || pwd)|g"
```

```powershell
# Windows
Get-ChildItem -Recurse -Filter *.py | ForEach-Object {
  (Get-Content $_.FullName) -replace [regex]::Escape('F:\Capstone\Log Model'), $PWD | Set-Content $_.FullName
}
```

## 5. Execution

Re-score the locked test vault using only the shipped checkpoints (no retraining):

```bash
python day_shift_complete_pipeline.py --stages test --skip-fix --no-sleep
```

- `--stages test` runs Step 4 only, reading `vault/test_locked/` and the snapshots
  under `data_v2/ready_to_train_v2/snapshots/`.
- `--skip-fix` is required: it reuses `work_data/dataset_remediation/dataset_integrity_proof.json`
  (shipped, `passed: true`) instead of re-running the dataset gate, which needs the
  full train/val corpus you do not have.
- `--no-sleep` is **required**. Without it the pipeline calls
  `SetSuspendState` and suspends your PC when every gate passes.

The test stage needs `day_shift_results.json` (shipped) for the Task B ensemble
calibration, and the five fold checkpoints for the ensemble.

Expected output - `final_test_results.csv` is regenerated with these values:

| Task | 25% | 50% | 75% | 100% |
|---|---|---|---|---|
| binary macro-F1 | 0.8910 | 0.8002 | 0.9988 | 1.0000 |
| binary ROC-AUC | 0.9834 | 0.8717 | 1.0000 | 1.0000 |
| multiclass macro-F1 | 0.3509 | 0.4214 | 1.0000 | 1.0000 |
| multiclass F1-F7 macro-F1 | 0.8095 | 0.8095 | 1.0000 | 1.0000 |

Test row counts: 4,288 Task A / 3,188 Task B (1,072 and 797 per depth bucket).

To also re-run the leakage and saliency audit:

```bash
python independent_model_audit.py
```

It reuses the same vault and checkpoints and exits 0 when all checks pass.

## 6. Locked test vault

`vault/test_locked/` ships all eight manifest-covered files plus
`test_manifest_sha256.json`. The evaluation scripts call `verify_locked_vault()`,
which refuses to proceed on any size or SHA-256 mismatch - so if it runs at all,
your test data is byte-identical to the run that produced the reported metrics.

The 4,288 referenced snapshot `.txt` files are under
`data_v2/ready_to_train_v2/snapshots/`. They are part of the test set and must not
be edited; the vault manifest does not cover them individually, but the run IDs in
the vault CSVs index into them.

## 7. Known stale script

`generate_final_test_table.py` is included for completeness but **will not run** on
this tokenizer. It asserts a 21,041-token vocabulary at line 495, which predates the
anonymization pass; the shipped tokenizer has 19,083 tokens. Use
`day_shift_complete_pipeline.py --stages test` instead. The assertion is left in
place deliberately rather than being edited, so the staleness stays visible.
