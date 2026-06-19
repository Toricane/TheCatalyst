#!/usr/bin/env python3
"""
Live-server integration checks (hits localhost:8000, not the in-memory test DB).

Run manually after starting the server: python app.py
Or via pytest when the server is already running (skipped otherwise).

Chat tests use a dedicated conversation_id and delete it afterward so real
conversation history is not polluted.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
import requests
from requests.exceptions import ConnectionError, Timeout

API_URL = "http://localhost:8000"


def _server_reachable() -> bool:
    try:
        requests.get(f"{API_URL}/", timeout=5)
        return True
    except ConnectionError:
        return False


def _delete_conversation(conversation_id: str | None) -> None:
    if not conversation_id:
        return
    try:
        requests.delete(
            f"{API_URL}/conversations/{conversation_id}",
            timeout=5,
        )
    except ConnectionError:
        pass


def test_server():
    """Test if the server is running and healthy."""
    print("🔍 Testing The Catalyst Server...")

    if not _server_reachable():
        pytest.skip("Server is not running on localhost:8000")

    response = requests.get(f"{API_URL}/", timeout=5)
    assert response.status_code == 200, f"Unexpected status: {response.status_code}"
    print("✅ Server is running")
    data = response.json()
    print(f"   Version: {data.get('version')}")
    print(f"   Model: {data.get('model')}")

    response = requests.get(f"{API_URL}/health", timeout=5)
    assert response.status_code == 200, (
        f"Health endpoint returned {response.status_code}"
    )
    print("✅ Health check passed")
    data = response.json()
    print(f"   Status: {data.get('status')}")
    print(f"   Goals: {data.get('goals_count', 0)}")
    print(f"   Function calling: {data.get('function_calling')}")

    conversation_id = str(uuid4())
    print(f"\n🤖 Testing chat functionality (isolated conversation {conversation_id})...")
    try:
        try:
            response = requests.post(
                f"{API_URL}/chat",
                headers={"Content-Type": "application/json"},
                json={
                    "message": "pytest isolated server health check",
                    "session_type": "general",
                    "conversation_id": conversation_id,
                },
                timeout=30,
            )
        except Timeout:
            pytest.fail("Chat request timed out (possible API key or network issue)")

        assert response.status_code == 200, (
            f"Chat endpoint returned {response.status_code}: {response.text}"
        )
        print("✅ Chat endpoint working")
        data = response.json()
        conversation_id = data.get("conversation_id") or conversation_id
        print(f"   Response length: {len(data.get('response', ''))}")
        print(f"   Memory updated: {data.get('memory_updated', False)}")
        if len(data.get("response", "")) > 0:
            print(f"   Sample response: {data.get('response', '')[:100]}...")
    finally:
        _delete_conversation(conversation_id)
        print(f"🧹 Cleaned up isolated test conversation {conversation_id}")

    print("\n🎉 All tests passed! The Catalyst is working properly.")


def test_goals():
    """Test goals endpoint."""
    if not _server_reachable():
        pytest.skip("Server is not running on localhost:8000")

    response = requests.get(f"{API_URL}/goals", timeout=5)
    assert response.status_code == 200, (
        f"Goals endpoint returned {response.status_code}"
    )
    data = response.json()
    print(f"✅ Goals endpoint working (found {data.get('total', 0)} goals)")


if __name__ == "__main__":
    print("🔥 The Catalyst - System Test\n")

    try:
        test_server()
        print("\n📊 Testing additional endpoints...")
        test_goals()

        print("\n✨ The Catalyst is ready for use!")
        print("\n🚀 Next steps:")
        print("   1. Open frontend/index.html in your browser")
        print("   2. Set your North Star goal")
        print("   3. Start your first conversation")
        print("\n💡 Tip: Try morning and evening session types for the full experience")
    except Exception as exc:
        if exc.__class__.__name__ in {"Skipped", "SkipException"}:
            print(f"\n🔧 Setup needed: {exc}")
            print("   1. Make sure the server is running: python app.py")
            print("   2. Check your .env file has a valid CLOD_API_KEY")
            print("   3. Verify no firewall is blocking port 8000")
        elif isinstance(exc, AssertionError):
            print("\n🔧 Setup needed:")
            print(f"   {exc}")
            print("   1. Make sure the server is running: python app.py")
            print("   2. Check your .env file has a valid CLOD_API_KEY")
            print("   3. Verify no firewall is blocking port 8000")
        else:
            raise
