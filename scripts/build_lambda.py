"""Builds build/lambda.zip, the package Terraform uploads to AWS Lambda.

Run from the repository root:  python scripts/build_lambda.py

The zip holds the dependencies from requirements-lambda.txt, the src package and
db/schema.sql. The dependencies are downloaded as Linux wheels for the Lambda
runtime, whatever operating system this runs on. Compiled packages such as
psycopg2 would not work on Lambda if installed normally on Windows.

The zip is byte-for-byte the same when nothing changed, so Terraform only
redeploys the function when its code or dependencies really changed.
"""
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build"
PACKAGE = BUILD / "package"
ZIP_PATH = BUILD / "lambda.zip"

PYTHON_VERSION = "3.13"  # must match the runtime in infra/lambda.tf
PLATFORM = "manylinux2014_x86_64"  # must match the architecture in infra/lambda.tf


def install_dependencies() -> None:
    subprocess.run(
        [
            sys.executable, "-m", "pip", "install",
            "--requirement", str(ROOT / "requirements-lambda.txt"),
            "--target", str(PACKAGE),
            "--platform", PLATFORM,
            "--python-version", PYTHON_VERSION,
            "--implementation", "cp",
            "--only-binary", ":all:",
            "--no-compile",
            "--disable-pip-version-check",
        ],
        check=True,
    )


def copy_code() -> None:
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
    shutil.copytree(ROOT / "src", PACKAGE / "src", ignore=ignore)
    (PACKAGE / "db").mkdir()
    shutil.copy2(ROOT / "db" / "schema.sql", PACKAGE / "db" / "schema.sql")


def write_zip() -> int:
    """Zip the package folder with fixed timestamps and permissions; returns the file count."""
    files = sorted(p for p in PACKAGE.rglob("*") if p.is_file() and "__pycache__" not in p.parts)
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            entry = zipfile.ZipInfo(path.relative_to(PACKAGE).as_posix(), date_time=(1980, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o644 << 16  # readable by everyone; Lambda must be able to read every file
            archive.writestr(entry, path.read_bytes())
    return len(files)


def main() -> None:
    if BUILD.exists():
        shutil.rmtree(BUILD)
    PACKAGE.mkdir(parents=True)

    install_dependencies()
    copy_code()
    count = write_zip()

    size_mb = ZIP_PATH.stat().st_size / 1_000_000
    print(f"Built {ZIP_PATH.relative_to(ROOT)}: {count} files, {size_mb:.1f} MB (Lambda allows 50 MB)")


if __name__ == "__main__":
    main()
