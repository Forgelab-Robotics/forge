from __future__ import annotations

import pyarrow as pa

from forge_msgs.arrow import ensure_record_batch

ArrowInput = pa.RecordBatch | pa.Table | pa.StructArray | bytes


def normalize_single_row(data: ArrowInput, model_name: str) -> pa.RecordBatch:
    """Normalize a supported Arrow payload without combining its value buffers."""

    if isinstance(data, bytes):
        source = pa.BufferReader(data)
        reader = pa.ipc.open_stream(source)
        try:
            batch = reader.read_next_batch()
        except StopIteration:
            raise ValueError(
                f"{model_name} IPC stream must contain exactly one RecordBatch"
            ) from None
        try:
            reader.read_next_batch()
        except StopIteration:
            pass
        else:
            raise ValueError(
                f"{model_name} IPC stream must contain exactly one RecordBatch"
            )
        if source.tell() != len(data):
            raise ValueError(f"{model_name} IPC stream must not contain trailing bytes")
    elif isinstance(data, pa.Table):
        if data.num_rows != 1:
            raise ValueError(
                f"{model_name} RecordBatch must contain exactly one row, "
                f"got {data.num_rows}"
            )
        arrays: list[pa.Array] = []
        for column in data.columns:
            non_empty = [chunk for chunk in column.chunks if len(chunk)]
            if len(non_empty) != 1:
                raise ValueError(
                    f"{model_name} single-row Table columns must contain one value"
                )
            arrays.append(non_empty[0])
        batch = pa.RecordBatch.from_arrays(arrays, schema=data.schema)
    else:
        batch = ensure_record_batch(data)

    if batch.num_rows != 1:
        raise ValueError(
            f"{model_name} RecordBatch must contain exactly one row, "
            f"got {batch.num_rows}"
        )
    if isinstance(data, pa.StructArray) and data.null_count:
        raise ValueError(f"{model_name} StructArray row must not be null")
    return batch


def physical_types_match(actual: pa.DataType, expected: pa.DataType) -> bool:
    """Compare Arrow storage types while ignoring child nullability metadata."""

    if pa.types.is_list(expected):
        return pa.types.is_list(actual) and physical_types_match(
            actual.value_type, expected.value_type
        )
    if pa.types.is_struct(expected):
        if not pa.types.is_struct(actual) or actual.num_fields != expected.num_fields:
            return False
        return all(
            actual_field.name == expected_field.name
            and physical_types_match(actual_field.type, expected_field.type)
            for actual_field, expected_field in zip(actual, expected, strict=True)
        )
    return actual == expected


def required_field_indices(
    batch: pa.RecordBatch, schema: pa.Schema, model_name: str
) -> dict[str, int]:
    """Resolve canonical columns by name and reject missing or duplicate columns."""

    missing = [field.name for field in schema if field.name not in batch.schema.names]
    if missing:
        raise ValueError(
            f"{model_name} RecordBatch is missing required fields: "
            + ", ".join(missing)
        )

    indices: dict[str, int] = {}
    for expected_field in schema:
        matching_indices = [
            index
            for index, name in enumerate(batch.schema.names)
            if name == expected_field.name
        ]
        if len(matching_indices) != 1:
            raise ValueError(
                f"{model_name} RecordBatch field {expected_field.name} must appear "
                f"exactly once, got {len(matching_indices)}"
            )
        index = matching_indices[0]
        actual_type = batch.schema.field(index).type
        if not physical_types_match(actual_type, expected_field.type):
            raise TypeError(
                f"{model_name} Arrow field {expected_field.name} must have type "
                f"{expected_field.type}, got {actual_type}"
            )
        indices[expected_field.name] = index
    return indices
