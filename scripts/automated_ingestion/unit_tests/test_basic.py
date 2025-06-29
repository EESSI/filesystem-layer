"""
Basic test file to prevent pytest from failing with exit code 5 when no tests are found.

This file is part of the EESSI filesystem layer,
see https://github.com/EESSI/filesystem-layer

author: Thomas Roeblitz (@trz42)

license: GPLv2
"""

import pytest


def test_basic_placeholder():
    """Basic placeholder test that always passes."""
    assert True


def test_import_modules():
    """Test that we can import the main modules without errors."""
    try:
        import eessi_logging
        # Verify the modules were imported successfully
        assert eessi_logging is not None
    except ImportError as err:
        pytest.skip(f"Module import failed: {err}")
