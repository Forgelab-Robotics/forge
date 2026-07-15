from __future__ import annotations

import argparse
import struct
import subprocess
import sys
import tempfile
from pathlib import Path


def _to_ipc_file(batch, path: Path) -> None:
    import pyarrow as pa

    with path.open("wb") as file:
        with pa.ipc.new_stream(file, batch.schema) as writer:
            writer.write_batch(batch)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--driver", required=True)
    parser.add_argument("--pythonpath", required=True)
    args = parser.parse_args()

    sys.path.insert(0, args.pythonpath)
    try:
        from forge_msgs import AudioChunk, Text
    except Exception as exc:  # pragma: no cover - exercised by CTest skip
        print(f"skipping Python/C++ interop test: {exc}", file=sys.stderr)
        return 77

    driver = Path(args.driver)
    if not driver.exists():
        print(f"skipping Python/C++ interop test: missing {driver}", file=sys.stderr)
        return 77

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        cpp_text = tmp_path / "cpp_text.arrow"
        subprocess.run([driver, "write-text", cpp_text], check=True)
        assert Text.from_arrow(cpp_text.read_bytes()).text == "cpp hello"

        py_text = tmp_path / "py_text.arrow"
        _to_ipc_file(Text(text="python hello").to_arrow(), py_text)
        out = subprocess.check_output([driver, "read-text", py_text], text=True).strip()
        assert out == "python hello"

        cpp_audio = tmp_path / "cpp_audio.arrow"
        subprocess.run([driver, "write-audio", cpp_audio], check=True)
        chunk = AudioChunk.from_arrow(cpp_audio.read_bytes())
        assert chunk.sample_rate == 16000
        assert chunk.channels == 1
        assert chunk.sample_format == "f32le"
        assert chunk.frame_count == 2

        py_audio = tmp_path / "py_audio.arrow"
        data = struct.pack("<hh", 100, -200)
        _to_ipc_file(
            AudioChunk(
                sample_rate=48000,
                channels=1,
                sample_format="s16le",
                frame_count=2,
                data=data,
            ).to_arrow(),
            py_audio,
        )
        out = subprocess.check_output([driver, "read-audio", py_audio], text=True).strip()
        assert out == "48000 1 s16le 2 4"

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
