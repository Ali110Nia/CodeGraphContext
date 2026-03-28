import os
import shutil
import pytest
from pathlib import Path
from typer.testing import CliRunner
from codegraphcontext.cli.main import app

runner = CliRunner()

@pytest.fixture
def temp_repo(tmp_path):
    repo_dir = tmp_path / "test_incremental_repo"
    repo_dir.mkdir()

    # Create initial files
    (repo_dir / "main.py").write_text("def hello():\n    pass")
    (repo_dir / "utils.py").write_text("def helper():\n    pass")

    yield repo_dir

    # Cleanup
    shutil.rmtree(repo_dir, ignore_errors=True)

@pytest.mark.asyncio
def test_incremental_indexing(temp_repo):
    import os
    os.environ['CGC_RUNTIME_DB_TYPE'] = 'falkordb'
    from codegraphcontext.cli.cli_helpers import _initialize_services
    db_manager, _, _ = _initialize_services()

    try:
        # 1. Initial Index
        result = runner.invoke(app, ["index", str(temp_repo)])
        assert result.exit_code == 0

        with db_manager.get_driver().session() as session:
            res = session.run("MATCH (f:Function) WHERE f.path STARTS WITH $path RETURN f.name AS name", path=str(temp_repo))
            functions = {record["name"] for record in res}
            assert "hello" in functions
            assert "helper" in functions

        # 2. Modify files
        # Modify main.py
        (temp_repo / "main.py").write_text("def hello_world():\n    pass")
        # Delete utils.py
        (temp_repo / "utils.py").unlink()
        # Add new file
        (temp_repo / "new_file.py").write_text("def new_func():\n    pass")

        # 3. Incremental Index (no --force)
        result = runner.invoke(app, ["index", str(temp_repo)])
        assert result.exit_code == 0
        assert "Performing incremental index" in result.output

        with db_manager.get_driver().session() as session:
            res = session.run("MATCH (f:Function) WHERE f.path STARTS WITH $path RETURN f.name AS name", path=str(temp_repo))
            functions = {record["name"] for record in res}

            # check updates
            assert "hello_world" in functions # modified
            assert "hello" not in functions   # old function should be gone
            assert "new_func" in functions    # added
            assert "helper" not in functions  # deleted file's function should be gone

            # verify files count
            res = session.run("MATCH (f:File) WHERE f.path STARTS WITH $path RETURN count(f) as count", path=str(temp_repo))
            assert res.single()["count"] == 3 # main.py, new_file.py, and auto-generated .cgcignore

        # 4. Force Reindex
        result = runner.invoke(app, ["index", str(temp_repo), "--force"])
        assert result.exit_code == 0
        assert "Force re-indexing" in result.output
    finally:
        # Cleanup graph
        with db_manager.get_driver().session() as session:
            session.run("MATCH (r:Repository {path: $path}) DETACH DELETE r", path=str(temp_repo))
            session.run("MATCH (f:File) WHERE f.path STARTS WITH $path DETACH DELETE f", path=str(temp_repo))
        db_manager.close_driver()
