from fastapi.testclient import TestClient
from main import app
import unittest
from unittest.mock import patch, AsyncMock, MagicMock
import pytest
import json

client = TestClient(app)

class TestAuthPKCE(unittest.TestCase):
    @patch("auth.httpx.AsyncClient.post", new_callable=AsyncMock)
    @patch("auth.httpx.AsyncClient.get", new_callable=AsyncMock)
    @patch("auth.sync_user_to_db", new_callable=AsyncMock)
    def test_github_exchange_with_pkce(self, mock_sync, mock_get, mock_post):
        # Mock GitHub token response
        mock_post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={"access_token": "gh_token"})
        )
        # Mock GitHub user response
        mock_get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={"id": 123, "login": "testuser"})
        )
        # Mock DB sync
        mock_sync.return_value = {"id": "user-uuid", "role": "analyst", "is_active": True}

        payload = {
            "code": "test_code",
            "code_verifier": "test_verifier",
            "redirect_uri": "http://localhost:8080/callback"
        }
        
        response = client.post("/auth/github/exchange", json=payload)
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertIn("access_token", data)
        self.assertIn("refresh_token", data)
        
        # Verify the call to GitHub
        args, kwargs = mock_post.call_args
        github_payload = kwargs.get("data") or kwargs.get("json")
        # In our implementation it's sent as data=payload in auth.py
        sent_payload = kwargs.get("data")
        self.assertEqual(sent_payload["code_verifier"], "test_verifier")
        self.assertEqual(sent_payload["redirect_uri"], "http://localhost:8080/callback")
        print("Backend correctly passed code_verifier and redirect_uri to GitHub API.")

if __name__ == "__main__":
    unittest.main()
