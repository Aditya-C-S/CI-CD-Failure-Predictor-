"""
scratch/test_models_comparison.py - Run validation and live scenario comparison
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.prediction.bilstm_inference import get_bilstm_engine, predict_bilstm
from src.prediction.bilstm2_inference import get_bilstm2_engine, predict_bilstm2
from src.prediction.predictor import get_predictor

print('--- Testing Model Loading ---')
e1 = get_bilstm_engine()
e1.load_artifacts()
print('BiLSTM 1 loaded. Vocab size:', len(e1.vocab), 'Threshold:', e1.task_a_threshold)

e2 = get_bilstm2_engine()
e2.load_artifacts()
print('BiLSTM 2 loaded. Vocab size:', len(e2.vocab), 'Threshold:', e2.task_a_threshold)

p1_count = sum(p.numel() for p in e1.task_a_model.parameters())
p2_count = sum(p.numel() for p in e2.task_a_model.parameters())
print(f'Task A Param counts: BiLSTM1={p1_count}, BiLSTM2={p2_count}')

p1_b_count = sum(p.numel() for p in e1.task_b_models[0].parameters())
p2_b_count = sum(p.numel() for p in e2.task_b_models[0].parameters())
print(f'Task B Fold 0 Param counts: BiLSTM1={p1_b_count}, BiLSTM2={p2_b_count}')

# Test empty input
print('\n--- 1. Empty Input ---')
r1_empty = predict_bilstm('', 100)
r2_empty = predict_bilstm2('', 100)
print('bilstm1 empty:', r1_empty['failure_probability'], r1_empty['predicted_outcome'], r1_empty['predicted_error_class'])
print('bilstm2 empty:', r2_empty['failure_probability'], r2_empty['predicted_outcome'], r2_empty['predicted_error_class'])

# Test short log
print('\n--- 2. Short Log ---')
short_log = 'Setting up runner\nProcess completed with exit code 0\n'
r1_short = predict_bilstm(short_log, 100)
r2_short = predict_bilstm2(short_log, 100)
print('bilstm1 short:', r1_short['failure_probability'], r1_short['predicted_outcome'])
print('bilstm2 short:', r2_short['failure_probability'], r2_short['predicted_outcome'])

# Test normal successful log
print('\n--- 3. Normal Success Log ---')
succ_log = (
    'ci_job\tCheckout\tChecking out main branch\n'
    'ci_job\tBuild\tBuilding project packages\n'
    'pytest tests/test_core.py\n'
    '3 passed in 0.45s\n'
    'Process completed with exit code 0\n'
)
r1_succ = predict_bilstm(succ_log, 100)
r2_succ = predict_bilstm2(succ_log, 100)
print('bilstm1 succ:', r1_succ['failure_probability'], r1_succ['predicted_outcome'])
print('bilstm2 succ:', r2_succ['failure_probability'], r2_succ['predicted_outcome'])

# Test dependency error
print('\n--- 4. Dependency Error Log ---')
dep_log = (
    'ci_job\tBuild\tInstalling requirements\n'
    'pip install -r requirements.txt\n'
    'ERROR: Could not find a version that satisfies the requirement missing_pkg==9.9.9\n'
    'ERROR: No matching distribution found for missing_pkg==9.9.9\n'
    'Process completed with exit code 1\n'
)
r1_dep = predict_bilstm(dep_log, 100)
r2_dep = predict_bilstm2(dep_log, 100)
print('bilstm1 dep:', r1_dep['failure_probability'], r1_dep['predicted_outcome'], r1_dep['predicted_error_class'])
print('bilstm2 dep:', r2_dep['failure_probability'], r2_dep['predicted_outcome'], r2_dep['predicted_error_class'])

# Test syntax error
print('\n--- 5. Syntax Error Log ---')
syntax_log = (
    'ci_job\tBuild\tRunning flake8 and build\n'
    'python src/app.py\n'
    'File "src/app.py", line 12\n'
    'def foo(\n'
    'SyntaxError: unexpected EOF while parsing\n'
    'Process completed with exit code 1\n'
)
r1_syn = predict_bilstm(syntax_log, 100)
r2_syn = predict_bilstm2(syntax_log, 100)
print('bilstm1 syn:', r1_syn['failure_probability'], r1_syn['predicted_outcome'], r1_syn['predicted_error_class'])
print('bilstm2 syn:', r2_syn['failure_probability'], r2_syn['predicted_outcome'], r2_syn['predicted_error_class'])

# Test assertion failure
print('\n--- 6. Pytest Assertion Failure Log ---')
test_fail_log = (
    'ci_job\tTest\tRunning pytest test suite\n'
    'pytest tests/\n'
    'FAILURES\n'
    'test_addition\n'
    'assert 2 + 2 == 5\n'
    'AssertionError: assert 4 == 5\n'
    'tests/test_math.py:8: AssertionError\n'
    '1 failed in 0.12s\n'
    'Process completed with exit code 1\n'
)
r1_test = predict_bilstm(test_fail_log, 100)
r2_test = predict_bilstm2(test_fail_log, 100)
print('bilstm1 test_fail:', r1_test['failure_probability'], r1_test['predicted_outcome'], r1_test['predicted_error_class'])
print('bilstm2 test_fail:', r2_test['failure_probability'], r2_test['predicted_outcome'], r2_test['predicted_error_class'])

# Test log growth across checkpoints 25%, 50%, 75%, 100%
print('\n--- 7. Checkpoint Progression on Growing Dependency Failure ---')
log_parts = [
    '2026-10-28T09:00:00Z Setting up runner\nci_job\tCheckout\tgit checkout main\n',
    '2026-10-28T09:00:05Z Setting up python 3.10\npython -m venv venv\n',
    '2026-10-28T09:00:10Z pip install -r requirements.txt\nCollecting missing_pkg==9.9.9\n',
    '2026-10-28T09:00:15Z ERROR: Could not find a version that satisfies the requirement missing_pkg==9.9.9\nProcess completed with exit code 1\n',
]

accum = ''
for i, depth in enumerate([25, 50, 75, 100]):
    accum += log_parts[i]
    r1 = predict_bilstm(accum, depth)
    r2 = predict_bilstm2(accum, depth)
    print(f'Depth {depth}%: len={len(accum.split())} words')
    print(f'   bilstm1: prob={r1["failure_probability"]:.4f}, outcome={r1["predicted_outcome"]}, class={r1["predicted_error_class"]}, latency={r1["metadata"]["inference_latency_ms"]}ms')
    print(f'   bilstm2: prob={r2["failure_probability"]:.4f}, outcome={r2["predicted_outcome"]}, class={r2["predicted_error_class"]}, latency={r2["metadata"]["inference_latency_ms"]}ms')
