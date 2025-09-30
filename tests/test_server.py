#!/usr/bin/env python3
"""
Quick test to verify The Catalyst is working properly
Run this after starting the server with: uvicorn backend.app:app --reload
"""

import pytest
import requests
from requests.exceptions import ConnectionError, Timeout

API_URL = "http://localhost:8000"


def test_server():
    """Test if the server is running and healthy"""
    print("🔍 Testing The Catalyst Server...")

    try:
        # Test basic health
        response = requests.get(f"{API_URL}/", timeout=5)
    except ConnectionError:
        pytest.skip("Server is not running on localhost:8000")

    assert response.status_code == 200, f"Unexpected status: {response.status_code}"
    print("✅ Server is running")
    data = response.json()
    print(f"   Version: {data.get('version')}")
    print(f"   Model: {data.get('model')}")

    # Test detailed health
    response = requests.get(f"{API_URL}/health", timeout=5)
    assert response.status_code == 200, (
        f"Health endpoint returned {response.status_code}"
    )
    print("✅ Health check passed")
    data = response.json()
    print(f"   Status: {data.get('status')}")
    print(f"   Goals: {data.get('goals_count', 0)}")
    print(f"   Function calling: {data.get('function_calling')}")

    # Test chat endpoint (simple message)
    try:
        print("\n🤖 Testing chat functionality...")
        test_message = {
            "message": "Hello, I'm testing if you're working properly.",
            "session_type": "general",
        }

        response = requests.post(
            f"{API_URL}/chat",
            headers={"Content-Type": "application/json"},
            json=test_message,
            timeout=30,
        )
    except Timeout:
        pytest.fail("Chat request timed out (possible API key or network issue)")

    assert response.status_code == 200, (
        f"Chat endpoint returned {response.status_code}: {response.text}"
    )
    print("✅ Chat endpoint working")
    data = response.json()
    print(f"   Response length: {len(data.get('response', ''))}")
    print(f"   Memory updated: {data.get('memory_updated', False)}")
    if len(data.get("response", "")) > 0:
        print(f"   Sample response: {data.get('response', '')[:100]}...")

    print("\n🎉 All tests passed! The Catalyst is working properly.")


def test_goals():
    """Test goals endpoint"""
    try:
        response = requests.get(f"{API_URL}/goals", timeout=5)
    except ConnectionError:
        pytest.skip("Server is not running on localhost:8000")

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
    except pytest.SkipTest as skip_exc:
        print(f"\n🔧 Setup needed: {skip_exc}")
        print("   1. Make sure the server is running: python app.py")
        print("   2. Check your .env file has a valid GEMINI_API_KEY")
        print("   3. Verify no firewall is blocking port 8000")
    except AssertionError as failure:
        print("\n🔧 Setup needed:")
        print(f"   {failure}")
        print("   1. Make sure the server is running: python app.py")
        print("   2. Check your .env file has a valid GEMINI_API_KEY")
        print("   3. Verify no firewall is blocking port 8000")
