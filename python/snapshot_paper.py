"""Refresh or check the local PDF/thumbnail linked from the repository README.

This command never commits files or publishes to an external service. Compile
paper/build/main.pdf first. A source digest detects stale checked-in snapshots
without requiring byte-identical PDFs across LaTeX engines or build dates.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PAPER = ROOT / "paper"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_digest() -> str:
    sources = [
        PAPER / "main.tex",
        PAPER / "references.bib",
        *sorted((PAPER / "sections").glob("*.tex")),
        *sorted((PAPER / "generated").glob("*.tex")),
    ]
    checksum = hashlib.sha256()
    for path in sources:
        name = path.relative_to(PAPER).as_posix().encode()
        content = path.read_bytes()
        checksum.update(len(name).to_bytes(8, "little"))
        checksum.update(name)
        checksum.update(len(content).to_bytes(8, "little"))
        checksum.update(content)
    return checksum.hexdigest()


def check_snapshot() -> None:
    manifest = json.loads((PAPER / "snapshot.json").read_text())
    if manifest["source_sha256"] != source_digest():
        raise ValueError(
            "Paper sources changed: run make -C paper preview and commit the refreshed snapshot"
        )
    for name in ["draft.pdf", "preview.jpg"]:
        if digest(PAPER / name) != manifest["files"][name]:
            raise ValueError(f"Snapshot file differs from its manifest: {name}")
    print("Paper snapshot matches its source and artifact hashes")


def refresh_snapshot() -> None:
    pdf = PAPER / "build" / "main.pdf"
    if not pdf.exists():
        raise ValueError("Build the PDF first with make -C paper pdf")
    with tempfile.TemporaryDirectory(dir=PAPER, prefix=".preview-") as directory:
        temporary = Path(directory)
        preview = temporary / "preview.jpg"
        if shutil.which("pdftoppm"):
            subprocess.run(
                [
                    "pdftoppm",
                    "-f",
                    "1",
                    "-singlefile",
                    "-scale-to",
                    "1200",
                    "-jpeg",
                    str(pdf),
                    str(temporary / "preview"),
                ],
                check=True,
            )
        elif shutil.which("sips"):
            subprocess.run(
                [
                    "sips",
                    "-s",
                    "format",
                    "jpeg",
                    "-Z",
                    "1200",
                    str(pdf),
                    "--out",
                    str(preview),
                ],
                check=True,
            )
        else:
            raise RuntimeError(
                "A thumbnail renderer is required: pdftoppm (Poppler) or macOS sips"
            )
        shutil.copyfile(pdf, temporary / "draft.pdf")
        os.replace(temporary / "draft.pdf", PAPER / "draft.pdf")
        os.replace(preview, PAPER / "preview.jpg")
    manifest = dict(
        source_sha256=source_digest(),
        files={name: digest(PAPER / name) for name in ["draft.pdf", "preview.jpg"]},
    )
    (PAPER / "snapshot.json").write_text(json.dumps(manifest, indent=2) + "\n")
    check_snapshot()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check source freshness and artifact hashes",
    )
    args = parser.parse_args()
    if args.check:
        check_snapshot()
    else:
        refresh_snapshot()


if __name__ == "__main__":
    main()
