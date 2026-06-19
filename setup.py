#!/usr/bin/env python3
"""
Setup script for The Catalyst - helps with initial configuration
"""

from pathlib import Path


def create_env_file():
    """Create .env file if it doesn't exist"""
    env_path = Path(".env")
    env_example_path = Path(".env.example")

    if not env_path.exists():
        if env_example_path.exists():
            with open(env_example_path, "r") as f:
                content = f.read()

            with open(env_path, "w") as f:
                f.write(content)

            print("✅ Created .env file from .env.example")
            print("⚠️  Please edit .env and add your CLOD_API_KEY")
            return False
        else:
            content = """# The Catalyst Environment Configuration
CLOD_API_KEY=
GEMINI_API_KEY=
MODEL_NAME=GPT OSS 120B
ALT_MODEL_NAME=gemini-2.5-flash
SHOW_THINKING=false
DATABASE_URL=
"""
            with open(env_path, "w") as f:
                f.write(content)

            print("✅ Created basic .env file")
            print("⚠️  Please edit .env and add your CLOD_API_KEY")
            return False
    else:
        with open(env_path, "r") as f:
            content = f.read()

        for line in content.splitlines():
            if line.startswith("CLOD_API_KEY=") and not line.split("=", 1)[1].strip():
                print("⚠️  Please edit .env and add your real CLOD_API_KEY")
                return False

        print("✅ .env file exists and appears configured")
        return True


def create_data_directory():
    """Create data directory if it doesn't exist"""
    data_path = Path("data")
    data_path.mkdir(exist_ok=True)
    print("✅ Data directory created/verified")


def check_dependencies():
    """Check if required packages are installed"""
    required_packages = [
        "fastapi",
        "uvicorn",
        "python-dotenv",
        "litellm",
        "pydantic",
        "sqlalchemy",
    ]

    missing_packages = []

    for package in required_packages:
        try:
            __import__(package.replace("-", "_"))
        except ImportError:
            missing_packages.append(package)

    if missing_packages:
        print(f"❌ Missing packages: {', '.join(missing_packages)}")
        print("   Run: pip install -r requirements.txt")
        return False
    else:
        print("✅ All required packages are installed")
        return True


def main():
    """Main setup function"""
    print("🔥 The Catalyst Setup Script\n")

    print("📦 Checking dependencies...")
    deps_ok = check_dependencies()
    print()

    print("📁 Setting up directories...")
    create_data_directory()
    print()

    print("⚙️  Setting up configuration...")
    env_ok = create_env_file()
    print()

    if deps_ok and env_ok:
        print("🎉 Setup complete! You can now run:")
        print("   uvicorn backend.app:app --reload")
        print("\nThen open frontend/index.html in your browser")
    else:
        print("⚠️  Setup incomplete. Please address the issues above.")
        if not deps_ok:
            print("   - Install dependencies: pip install -r requirements.txt")
        if not env_ok:
            print("   - Configure your .env file with a valid CLOD_API_KEY")

    print("\n🔗 Useful commands:")
    print("   python scripts/demo_retry_logic.py")
    print("   python -m pytest tests/ --ignore=tests/test_rate_limiter.py")
    print("   uvicorn backend.app:app --reload")
    print("   python app.py")


if __name__ == "__main__":
    main()
