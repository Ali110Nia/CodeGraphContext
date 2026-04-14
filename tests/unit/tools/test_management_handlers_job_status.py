from codegraphcontext.core.jobs import JobManager
from codegraphcontext.tools.handlers.management_handlers import check_job_status


def test_check_job_status_returns_failure_for_missing_job():
    manager = JobManager()

    result = check_job_status(manager, job_id="missing-job-id")

    assert result["success"] is False
    assert result["status"] == "not_found"
    assert result["error_code"] == "JOB_NOT_FOUND"
    assert "not found" in result["message"].lower()
