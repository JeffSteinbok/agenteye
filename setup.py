"""Setup script for Agent Eye."""

from pathlib import Path

from setuptools import find_packages, setup

# Read requirements from requirements.txt
requirements_file = Path(__file__).parent / "requirements.txt"
with open(requirements_file, encoding="utf-8") as f:
    requirements = [line.strip() for line in f if line.strip() and not line.startswith("#")]

# Read version from src/__version__.py
version_file = Path(__file__).parent / "src" / "__version__.py"
version = {}
with open(version_file, encoding="utf-8") as f:
    exec(f.read(), version)

# Read long description from README
readme_file = Path(__file__).parent / "README.md"
with open(readme_file, encoding="utf-8") as f:
    long_description = f.read()

setup(
    name="agenteye",
    version=version["__version__"],
    description="Agent Eye dashboard for monitoring GitHub Copilot CLI sessions in real-time",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Jeff Steinbok",
    url="https://github.com/JeffSteinbok/agenteye",
    license="MIT",
    packages=find_packages(exclude=["tests", "tests.*"]),
    include_package_data=True,
    install_requires=requirements + [
        'pywin32; sys_platform == "win32"',
        'pywinauto; sys_platform == "win32"',
    ],
    python_requires=">=3.11",
    entry_points={
        "console_scripts": [
            "agenteye=src.session_dashboard:main",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
        "Topic :: Software Development :: Quality Assurance",
        "Topic :: Utilities",
    ],
    keywords="agenteye github cli dashboard session monitor",
)
