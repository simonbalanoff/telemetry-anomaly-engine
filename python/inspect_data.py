import argparse
import io
import zipfile
from pathlib import Path

import pandas as pd


def show_dir(root: Path) -> None:
    print("== Top level ==")
    for p in sorted(root.iterdir()):
        size = p.stat().st_size if p.is_file() else "-"
        print(f"  {p.name:30} {size}")


def show_csv(path: Path, name: str) -> None:
    print(f"\n== {name} ==")
    if not path.exists():
        print("  (not found)")
        return
    df = pd.read_csv(path)
    print(f"  rows: {len(df)}")
    print(f"  columns: {df.columns.tolist()}")
    print(df.head(5).to_string())


def show_channel_file(path: Path) -> None:
    print(f"\n== Sample channel file: {path.name} ==")
    if path.suffix == ".zip":
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            print(f"  zip members: {names}")
            member = names[0]
            raw = z.read(member)
            print(f"  first member: {member}, {len(raw)} bytes")
            print(f"  first 200 bytes: {raw[:200]!r}")
            if member.endswith(".csv"):
                df = pd.read_csv(io.BytesIO(raw))
                print(df.head(5).to_string())
                print(df.dtypes)
    else:
        print(f"  not a zip (suffix {path.suffix!r}); inspect it by hand")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("root", type=Path)
    root = ap.parse_args().root

    show_dir(root)
    for name in ("labels.csv", "anomaly_types.csv", "channels.csv"):
        show_csv(root / name, name)

    channels = root / "channels"
    if channels.is_dir():
        files = sorted(channels.iterdir())
        print(f"\n== channels/ has {len(files)} entries; first 5: {[f.name for f in files[:5]]}")
        if files:
            show_channel_file(files[0])


if __name__ == "__main__":
    main()

