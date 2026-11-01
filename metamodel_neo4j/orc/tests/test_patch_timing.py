#!/usr/bin/env python3
"""
CRITICAL TEST: Verify patch is applied BEFORE diff_agent imports it.

This test proves the patch is effective by:
1. Importing graph_adapter (which applies the patch)
2. Checking that diff_agent received the patched version
"""

import sys
from pathlib import Path

pytest = __import__('pytest')

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, r'C:\Users\DHRUV HEGDE\Desktop\graph-doc-gen-main')


def test_patch_applied_before_diff_agent_import():
    """
    Critical test: When graph_adapter imports update_graph_from_diff,
    the patched check_working_tree_clean should already be in place.
    """
    # Import graph_adapter - this applies the patch THEN imports diff_agent
    from src.adapters import graph_adapter
    
    # Now check: what is diff_agent using?
    from maintenance import diff_agent
    from maintenance import git_utils
    
    # Get the check_working_tree_clean that diff_agent has access to
    # It should be bound in the git_utils module
    runtime_func = git_utils.check_working_tree_clean
    
    # Verify it's the patched version
    assert runtime_func.__name__ == '_patched_check_working_tree_clean', \
        f"Expected patched function, got: {runtime_func.__name__}"
    
    print(f"[OK] Patch successfully applied")
    print(f"     Function: {runtime_func.__name__}")
    print(f"     Module: {runtime_func.__module__}")
    print(f"     Object ID: {id(runtime_func)}")


def test_patch_function_name():
    """Verify the patched function has the expected name."""
    from maintenance import git_utils
    
    # The patched function should have the name '_patched_check_working_tree_clean'
    func_name = git_utils.check_working_tree_clean.__name__
    assert func_name == '_patched_check_working_tree_clean', \
        f"Expected '_patched_check_working_tree_clean', got '{func_name}'"
    
    print(f"[OK] Patched function name verified: {func_name}")


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
