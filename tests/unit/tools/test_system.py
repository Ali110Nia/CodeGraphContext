import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from datetime import datetime, timedelta
from codegraphcontext.tools.system import SystemTools
from codegraphcontext.core.jobs import JobInfo, JobStatus

class TestSystemTools:
    @pytest.fixture
    def mock_db_manager(self):
        return MagicMock()

    @pytest.fixture
    def mock_job_manager(self):
        return MagicMock()

    @pytest.fixture
    def system_tools(self, mock_db_manager, mock_job_manager):
        return SystemTools(mock_db_manager, mock_job_manager)

    def test_check_job_status_running(self, system_tools, mock_job_manager):
        # Setup
        job_id = "test-job-id"
        start_time = datetime.now() - timedelta(minutes=5)
        job = JobInfo(
            job_id=job_id,
            status=JobStatus.RUNNING,
            start_time=start_time,
            total_files=100,
            processed_files=50
        )
        # Mock estimated_time_remaining to return 300 seconds (5 minutes)
        with patch.object(JobInfo, 'estimated_time_remaining', new_callable=PropertyMock) as mock_remaining:
            mock_remaining.return_value = 300.0
            mock_job_manager.get_job.return_value = job

            # Execute
            result = system_tools.check_job_status_tool(job_id)

            # Verify
            assert result["success"] is True
            assert result["job"]["status"] == "running"
            assert result["job"]["estimated_time_remaining_human"] == "5m 0s"
            assert "elapsed_time_human" in result["job"]

    def test_check_job_status_completed(self, system_tools, mock_job_manager):
        # Setup
        job_id = "test-job-id"
        start_time = datetime.now() - timedelta(minutes=10)
        end_time = start_time + timedelta(minutes=5)
        job = JobInfo(
            job_id=job_id,
            status=JobStatus.COMPLETED,
            start_time=start_time,
            end_time=end_time
        )
        mock_job_manager.get_job.return_value = job

        # Execute
        result = system_tools.check_job_status_tool(job_id)

        # Verify
        assert result["success"] is True
        assert result["job"]["status"] == "completed"
        assert result["job"]["actual_duration_human"] == "5m 0s"

    def test_check_job_status_not_found(self, system_tools, mock_job_manager):
        # Setup
        job_id = "non-existent-id"
        mock_job_manager.get_job.return_value = None

        # Execute
        result = system_tools.check_job_status_tool(job_id)

        # Verify
        assert "error" in result
        assert "not found" in result["error"]

    def test_check_job_status_exception(self, system_tools, mock_job_manager):
        # Setup
        job_id = "test-job-id"
        mock_job_manager.get_job.side_effect = Exception("Database error")

        # Execute
        result = system_tools.check_job_status_tool(job_id)

        # Verify
        assert "error" in result
        assert "Failed to check job status: Database error" in result["error"]
