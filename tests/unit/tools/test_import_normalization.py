from __future__ import annotations

from codegraphcontext.tools.indexing.persistence.writer import GraphWriter


def test_python_relative_from_import_is_canonicalized_to_absolute_module_path():
    writer = GraphWriter(driver=None)
    rows = writer._normalize_import_rows(
        [
            {
                "name": "TftAspTraining",
                "full_import_name": ".training.TftAspTraining",
                "line_number": 11,
                "alias": None,
            }
        ],
        lang="python",
        file_path_str="/workspace/Subproject-HMM/hmm_pipeline_v3/modelling/tft/asp/block.py",
        repo_path_str="/workspace/Subproject-HMM",
    )

    assert len(rows) == 1
    row = rows[0]
    assert row["module_name"] == "hmm_pipeline_v3.modelling.tft.asp.training"
    assert row["imported_name"] == "TftAspTraining"
    assert row["full_import_name"] == "hmm_pipeline_v3.modelling.tft.asp.training.TftAspTraining"


def test_python_absolute_import_keeps_module_identity():
    writer = GraphWriter(driver=None)
    rows = writer._normalize_import_rows(
        [
            {
                "name": "numpy",
                "full_import_name": "numpy",
                "line_number": 3,
                "alias": "np",
            }
        ],
        lang="python",
        file_path_str="/workspace/Subproject-HMM/hmm_pipeline_v3/modelling/tft/asp/training.py",
        repo_path_str="/workspace/Subproject-HMM",
    )

    assert len(rows) == 1
    row = rows[0]
    assert row["module_name"] == "numpy"
    assert row["imported_name"] == "numpy"
    assert row["full_import_name"] == "numpy"
