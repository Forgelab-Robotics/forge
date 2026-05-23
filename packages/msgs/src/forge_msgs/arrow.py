from __future__ import annotations

import pyarrow as pa


def ensure_record_batch(
    data: "pa.RecordBatch | pa.Table | pa.Array | bytes",
) -> "pa.RecordBatch":
    """Normalize Dora/Arrow payloads to a RecordBatch."""

    if isinstance(data, pa.RecordBatch):
        return data
    if isinstance(data, bytes):
        reader = pa.ipc.open_stream(data)
        return reader.read_next_batch()
    if isinstance(data, pa.Table):
        batches = data.to_batches()
        if not batches:
            return pa.RecordBatch.from_pydict({})
        return batches[0]
    if isinstance(data, pa.StructArray):
        names = [data.type.field(i).name for i in range(data.type.num_fields)]
        arrays = [data.field(i) for i in range(data.type.num_fields)]
        return pa.RecordBatch.from_arrays(arrays, names=names)
    raise TypeError(
        "from_arrow expects pa.RecordBatch, pa.Table, pa.StructArray, or bytes, "
        f"got: {type(data)}"
    )
