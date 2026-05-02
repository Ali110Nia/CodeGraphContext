import sys
from unittest.mock import patch, MagicMock
import pytest

sys.modules['neo4j'] = MagicMock()

from codegraphcontext.core.bundle_registry import BundleRegistry

class TestBundleRegistry:

    @patch('requests.get')
    def test_fetch_available_bundles_exceptions(self, mock_get):
        # Setup mock to raise exception for both requests
        mock_get.side_effect = Exception("Network error")

        # Run the function
        result = BundleRegistry.fetch_available_bundles()

        # Assertions
        assert result == []
        # Verify requests.get was called twice (once for manifest, once for API)
        assert mock_get.call_count == 2

    @patch('requests.get')
    def test_fetch_available_bundles_partial_failure(self, mock_get):
        # Setup mock to fail on first request but succeed on second
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                "tag_name": "bundles-20230101",
                "assets": [
                    {
                        "name": "test-1.0-abc.cgc",
                        "size": 1048576,
                        "browser_download_url": "http://example.com/download",
                        "updated_at": "2023-01-01T00:00:00Z"
                    }
                ]
            }
        ]

        # First call raises Exception, second returns mock response
        mock_get.side_effect = [Exception("Manifest network error"), mock_response]

        # Run the function
        result = BundleRegistry.fetch_available_bundles()

        # Assertions
        assert len(result) == 1
        assert result[0]['name'] == 'test'
        assert result[0]['source'] == 'weekly'
        assert mock_get.call_count == 2

    @patch('requests.get')
    def test_download_file_exceptions(self, mock_get):
        # Setup mock to raise exception
        mock_get.side_effect = Exception("Download error")

        from pathlib import Path
        output_path = Path("test_download.cgc")

        # Run the function
        with pytest.raises(Exception) as excinfo:
            BundleRegistry.download_file("http://example.com/file", output_path)

        assert str(excinfo.value) == "Download error"

    @patch('requests.get')
    def test_fetch_available_bundles_second_request_failure(self, mock_get):
        # Setup mock to succeed on first request but fail on second
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "bundles": [
                {
                    "bundle_name": "manifest-test.cgc",
                    "description": "A test bundle from manifest"
                }
            ]
        }

        # First call returns mock response, second raises Exception
        mock_get.side_effect = [mock_response, Exception("API network error")]

        # Run the function
        result = BundleRegistry.fetch_available_bundles()

        # Assertions
        assert len(result) == 1
        assert result[0]['name'] == 'manifest'
        assert result[0]['source'] == 'on-demand'
        assert mock_get.call_count == 2

    @patch('requests.get')
    def test_download_file_success(self, mock_get):
        # Setup mock to return a successful response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.iter_content.return_value = [b"chunk1", b"chunk2"]
        mock_get.return_value = mock_response

        from pathlib import Path
        output_path = Path("test_download.cgc")

        # We need to mock open to avoid actually writing to the filesystem
        with patch('builtins.open', MagicMock()) as mock_open:
            mock_progress = MagicMock()
            result = BundleRegistry.download_file("http://example.com/file", output_path, mock_progress)

            assert result is True
            assert mock_progress.call_count == 2
            mock_progress.assert_any_call(6)  # len("chunk1") == 6
            mock_progress.assert_any_call(6)  # len("chunk2") == 6

    @patch('codegraphcontext.core.bundle_registry.BundleRegistry.fetch_available_bundles')
    def test_find_bundle_download_info(self, mock_fetch):
        # Setup mock bundles
        mock_fetch.return_value = [
            {
                "name": "test",
                "full_name": "test-1.0-abc",
                "download_url": "http://example.com/test-1.0-abc.cgc",
                "generated_at": "2023-01-01T00:00:00Z"
            },
            {
                "name": "test",
                "full_name": "test-1.1-def",
                "download_url": "http://example.com/test-1.1-def.cgc",
                "generated_at": "2023-02-01T00:00:00Z"
            },
            {
                "name": "other",
                "full_name": "other-1.0-abc",
                "download_url": None,
                "generated_at": "2023-01-01T00:00:00Z"
            }
        ]

        # Test exact match on full_name
        url, bundle, err = BundleRegistry.find_bundle_download_info("test-1.0-abc")
        assert url == "http://example.com/test-1.0-abc.cgc"
        assert bundle['full_name'] == "test-1.0-abc"
        assert err == ""

        # Test base name match (returns newest)
        url, bundle, err = BundleRegistry.find_bundle_download_info("test")
        assert url == "http://example.com/test-1.1-def.cgc"
        assert bundle['full_name'] == "test-1.1-def"
        assert err == ""

        # Test no download URL found
        url, bundle, err = BundleRegistry.find_bundle_download_info("other-1.0-abc")
        assert url is None
        assert bundle['full_name'] == "other-1.0-abc"
        assert "No download URL found" in err

        # Test base name with no download URL
        url, bundle, err = BundleRegistry.find_bundle_download_info("other")
        assert url is None
        assert bundle['full_name'] == "other-1.0-abc"
        assert "No download URL found" in err

        # Test missing bundle
        url, bundle, err = BundleRegistry.find_bundle_download_info("missing")
        assert url is None
        assert bundle is None
        assert "not found" in err

    @patch('codegraphcontext.core.bundle_registry.BundleRegistry.fetch_available_bundles')
    def test_find_bundle_download_info_empty(self, mock_fetch):
        # Setup mock to return empty list
        mock_fetch.return_value = []

        url, bundle, err = BundleRegistry.find_bundle_download_info("test")
        assert url is None
        assert bundle is None
        assert "Could not fetch bundle registry" in err

    @patch('requests.get')
    def test_fetch_available_bundles_missing_fields(self, mock_get):
        # Setup mock to return a response with missing fields
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "bundles": [
                {
                    "repo": "org/my-repo"
                },
                {
                    "bundle_name": "unknown-1.0.cgc"
                }
            ]
        }

        # First call returns mock response, second raises Exception
        mock_get.side_effect = [mock_response, Exception("API network error")]

        # Run the function
        result = BundleRegistry.fetch_available_bundles()

        # Assertions
        assert len(result) == 2
        assert result[0]['name'] == 'my-repo'
        assert result[1]['name'] == 'unknown'
        assert result[1]['full_name'] == 'unknown-1.0'

    @patch('requests.get')
    def test_download_file_exceptions_cleanup(self, mock_get):
        # Setup mock to raise exception during streaming
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.iter_content.side_effect = Exception("Download error")
        mock_get.return_value = mock_response

        from pathlib import Path
        output_path = MagicMock(spec=Path)
        output_path.exists.return_value = True

        # We need to mock open to avoid actually writing to the filesystem
        with patch('builtins.open', MagicMock()):
            # Run the function
            with pytest.raises(Exception) as excinfo:
                BundleRegistry.download_file("http://example.com/file", output_path)

        assert str(excinfo.value) == "Download error"
        output_path.unlink.assert_called_once()
