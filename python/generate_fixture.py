import argparse
from pathlib import Path

from write_binary import Frame, Header, write_binary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    initial = (0.5, 0.25, 0.0, -0.5, 1.0, 0.75)
    resumed = (1.0, 2.0, 3.0, 4.0, 5.0, 6.0)
    zero = (0.0,) * 6

    header = Header(
        start_us=0,
        frame_count=12,
        validation_start_us=30_000_000,
        test_start_us=60_000_000,
    )

    frames = [
        Frame(initial, 0x3F, 0x3F, 0),
        Frame(initial, 0x3F, 0x3F, 0),
        *[
            Frame(initial, 0x00, 0x3F, i)
            for i in range(1, 6)
        ],
        Frame(zero, 0x00, 0x00, 6),
        Frame(zero, 0x00, 0x00, 7),
        Frame(resumed, 0x3F, 0x3F, 0),
        Frame(resumed, 0x3F, 0x3F, 0),
        Frame(resumed, 0x3F, 0x3F, 0),
    ]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_binary(args.output, header, frames)

    print(f"Wrote {len(frames)} frames to {args.output}")
    print(f"File size: {args.output.stat().st_size} bytes")


if __name__ == "__main__":
    main()
