from __future__ import annotations

import pyarrow as pa
from pydantic import BaseModel

from forge_msgs.arrow import ensure_record_batch


def _read_text_cell(array: pa.Array, context: str) -> str:
    if len(array) == 0:
        raise ValueError(f"Text {context} must contain one row")
    value = array[0].as_py()
    if value is None:
        raise ValueError("Text text must contain one non-null scalar row")
    return str(value)


class Text(BaseModel):
    """Single UTF-8 text payload for Dora/Arrow transport."""

    text: str

    def to_arrow(self) -> pa.RecordBatch:
        return pa.RecordBatch.from_pydict(
            {
                "text": pa.array([self.text], type=pa.string()),
            }
        )

    @classmethod
    def from_arrow(
        cls,
        data: pa.RecordBatch
        | pa.Table
        | pa.StructArray
        | pa.Array
        | pa.ChunkedArray
        | bytes,
    ) -> "Text":
        if isinstance(data, pa.ChunkedArray):
            data = data.chunk(0)
        if isinstance(data, pa.Array) and not isinstance(data, pa.StructArray):
            return cls(text=_read_text_cell(data, "array"))

        batch = ensure_record_batch(data)
        if batch.num_rows == 0:
            raise ValueError("Text RecordBatch must contain one row")
        return cls(text=_read_text_cell(batch["text"], "RecordBatch"))
