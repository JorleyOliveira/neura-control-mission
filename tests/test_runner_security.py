from pathlib import Path

import pytest
from fastapi import HTTPException

from neura_marketplace.runner_app import _resolve_user_path


def test_path_traversal_rejected(tmp_path: Path):
    with pytest.raises(HTTPException):
        _resolve_user_path(tmp_path, '../secret')


def test_path_inside_workspace_allowed(tmp_path: Path):
    p = _resolve_user_path(tmp_path, 'a/b.txt')
    assert p == (tmp_path / 'a/b.txt').resolve()
