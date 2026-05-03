import sys
from unittest.mock import MagicMock

# Mock fastapi and uvicorn before importing server
sys.modules['fastapi'] = MagicMock()
sys.modules['fastapi.staticfiles'] = MagicMock()
sys.modules['fastapi.middleware.cors'] = MagicMock()
sys.modules['fastapi.responses'] = MagicMock()
sys.modules['uvicorn'] = MagicMock()
sys.modules['neo4j'] = MagicMock()

from codegraphcontext.viz import server

def test_set_db_manager():
    """Test that set_db_manager correctly updates the global db_manager."""
    # Reset db_manager to None before test
    server.db_manager = None

    mock_manager = MagicMock()
    server.set_db_manager(mock_manager)

    assert server.db_manager == mock_manager

def test_set_db_manager_overwrite():
    """Test that set_db_manager overwrites an existing db_manager."""
    old_manager = MagicMock()
    server.db_manager = old_manager

    new_manager = MagicMock()
    server.set_db_manager(new_manager)

    assert server.db_manager == new_manager
    assert server.db_manager != old_manager
