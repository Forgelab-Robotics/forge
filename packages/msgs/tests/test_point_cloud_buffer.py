from __future__ import annotations

import gc
import struct

import numpy as np
import pyarrow as pa
import pytest
from pydantic import ValidationError

from forge_msgs import PointCloudBuffer, PointCloudBufferView, PointField


def _ipc_bytes(batch: pa.RecordBatch) -> bytes:
    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, batch.schema) as writer:
        writer.write_batch(batch)
    return sink.getvalue().to_pybytes()


def _replace_column(
    batch: pa.RecordBatch, name: str, column: pa.Array
) -> pa.RecordBatch:
    columns = list(batch.columns)
    columns[batch.schema.get_field_index(name)] = column
    return pa.RecordBatch.from_arrays(columns, names=batch.schema.names)


def _xyz_fields(datatype: str = "float32") -> list[PointField]:
    size = 4 if datatype == "float32" else 8
    return [
        PointField(name="x", offset=0, datatype=datatype, count=1),
        PointField(name="y", offset=size, datatype=datatype, count=1),
        PointField(name="z", offset=2 * size, datatype=datatype, count=1),
    ]


def _organized_cloud() -> PointCloudBuffer:
    width = 2
    height = 2
    point_stride = 28
    row_stride = 60
    data = bytearray([0xA5] * (row_stride * height))
    for row in range(height):
        for column in range(width):
            index = row * width + column
            base = row * row_stride + column * point_stride
            struct.pack_into(
                "<fff3fH",
                data,
                base,
                index + 0.25,
                index + 10.25,
                index + 20.25,
                index + 1.0,
                index + 2.0,
                index + 3.0,
                100 + index,
            )
    return PointCloudBuffer(
        width=width,
        height=height,
        is_dense=True,
        byte_order="little_endian",
        point_stride=point_stride,
        row_stride=row_stride,
        fields=[
            PointField(name="ring", offset=24, datatype="uint16", count=1),
            PointField(name="z", offset=8, datatype="float32", count=1),
            PointField(name="normal", offset=12, datatype="float32", count=3),
            PointField(name="x", offset=0, datatype="float32", count=1),
            PointField(name="y", offset=4, datatype="float32", count=1),
        ],
        data=bytes(data),
    )


def test_point_cloud_buffer_uses_canonical_schema_and_round_trips() -> None:
    point_field_type = pa.struct(
        [
            pa.field("name", pa.string(), nullable=False),
            pa.field("offset", pa.uint32(), nullable=False),
            pa.field("datatype", pa.string(), nullable=False),
            pa.field("count", pa.uint32(), nullable=False),
        ]
    )
    expected_schema = pa.schema(
        [
            pa.field("width", pa.uint32(), nullable=False),
            pa.field("height", pa.uint32(), nullable=False),
            pa.field("is_dense", pa.bool_(), nullable=False),
            pa.field("byte_order", pa.string(), nullable=False),
            pa.field("point_stride", pa.uint32(), nullable=False),
            pa.field("row_stride", pa.uint64(), nullable=False),
            pa.field(
                "fields",
                pa.list_(pa.field("item", point_field_type, nullable=True)),
                nullable=False,
            ),
            pa.field("data", pa.large_binary(), nullable=False),
        ]
    )
    cloud = _organized_cloud()

    batch = cloud.to_arrow()

    assert batch.schema == expected_schema
    assert batch.num_rows == 1
    assert [field["name"] for field in batch["fields"][0].as_py()] == [
        "x",
        "y",
        "z",
        "normal",
        "ring",
    ]
    assert PointCloudBuffer.from_arrow(batch) == cloud
    assert PointCloudBuffer.from_arrow(pa.Table.from_batches([batch])) == cloud
    assert PointCloudBuffer.from_arrow(_ipc_bytes(batch)) == cloud


def test_point_cloud_buffer_view_is_zero_copy_strided_readonly_and_retains_owner() -> (
    None
):
    batch = _organized_cloud().to_arrow()
    payload_buffer = batch["data"].buffers()[2]
    assert payload_buffer is not None

    view = PointCloudBufferView.from_arrow(batch)
    x = view.field("x")
    normal = view.field("normal")
    ring = view.field("ring")

    assert view.record_batch is batch
    assert (view.width, view.height, view.point_count) == (2, 2, 4)
    assert (view.point_stride, view.row_stride) == (28, 60)
    assert view.field_names == ("x", "y", "z", "normal", "ring")
    assert view.has_field("normal") is True
    assert view.has_field("missing") is False
    assert x.shape == (2, 2)
    assert x.strides == (60, 28)
    assert normal.shape == (2, 2, 3)
    assert normal.strides == (60, 28, 4)
    assert ring.shape == (2, 2)
    np.testing.assert_array_equal(x, [[0.25, 1.25], [2.25, 3.25]])
    np.testing.assert_array_equal(
        normal,
        [
            [[1.0, 2.0, 3.0], [2.0, 3.0, 4.0]],
            [[3.0, 4.0, 5.0], [4.0, 5.0, 6.0]],
        ],
    )
    np.testing.assert_array_equal(ring, [[100, 101], [102, 103]])

    raw_address = np.frombuffer(view.raw_data, dtype=np.uint8).__array_interface__[
        "data"
    ][0]
    assert raw_address == payload_buffer.address
    assert x.__array_interface__["data"][0] == payload_buffer.address
    assert view.raw_data.readonly is True
    assert x.flags.writeable is False
    assert x.flags.c_contiguous is False
    with pytest.raises(ValueError, match="read-only"):
        x[0, 0] = 99.0
    with pytest.raises(ValueError):
        x.setflags(write=True)

    descriptor = view.descriptor("x")
    descriptor.name = "changed"
    assert view.descriptor("x").name == "x"
    assert not hasattr(view, "field_descriptor")
    assert view.to_owned() == _organized_cloud()

    del batch
    gc.collect()
    np.testing.assert_array_equal(view.field("x"), [[0.25, 1.25], [2.25, 3.25]])


def test_point_cloud_buffer_view_preserves_sliced_large_binary_buffer() -> None:
    cloud = _organized_cloud()
    canonical = cloud.to_arrow()
    prefix = b"prefix"
    source = pa.array([prefix, cloud.data], type=pa.large_binary())
    sliced_data = source.slice(1, 1)
    payload = _replace_column(canonical, "data", sliced_data)
    values_buffer = source.buffers()[2]
    assert values_buffer is not None

    view = PointCloudBufferView.from_arrow(payload)
    raw_address = np.frombuffer(view.raw_data, dtype=np.uint8).__array_interface__[
        "data"
    ][0]

    assert raw_address == values_buffer.address + len(prefix)
    assert view.field("x").__array_interface__["data"][0] == raw_address
    del canonical, payload, sliced_data, source
    gc.collect()
    np.testing.assert_array_equal(view.field("x"), [[0.25, 1.25], [2.25, 3.25]])


def test_point_cloud_buffer_view_decodes_big_endian_unaligned_fields_without_copy() -> (
    None
):
    point_stride = 35
    data = bytearray([0xCC] * (2 * point_stride))
    expected = [
        (1.5, 2.5, 3.5, 10.5, 11.5),
        (-4.5, -5.5, -6.5, -10.5, -11.5),
    ]
    for index, values in enumerate(expected):
        base = index * point_stride
        struct.pack_into(">d", data, base + 1, values[0])
        struct.pack_into(">d", data, base + 9, values[1])
        struct.pack_into(">d", data, base + 17, values[2])
        struct.pack_into(">ff", data, base + 25, values[3], values[4])
    cloud = PointCloudBuffer(
        width=2,
        height=1,
        is_dense=True,
        byte_order="big_endian",
        point_stride=point_stride,
        row_stride=2 * point_stride,
        fields=[
            PointField(name="x", offset=1, datatype="float64", count=1),
            PointField(name="y", offset=9, datatype="float64", count=1),
            PointField(name="z", offset=17, datatype="float64", count=1),
            PointField(name="normal", offset=25, datatype="float32", count=2),
        ],
        data=bytes(data),
    )
    canonical = cloud.to_arrow()
    assert canonical["byte_order"][0].as_py() == "little_endian"
    canonical_view = PointCloudBufferView.from_arrow(canonical)
    assert canonical_view.field("x").dtype.str == "<f8"
    np.testing.assert_array_equal(canonical_view.field("x"), [1.5, -4.5])
    np.testing.assert_array_equal(
        canonical_view.field("normal"), [[10.5, 11.5], [-10.5, -11.5]]
    )
    canonical_data = bytes(canonical_view.raw_data)
    assert [canonical_data[index] for index in (0, 33, 34, 35, 68, 69)] == [0xCC] * 6

    big_endian_payload = _replace_column(
        canonical,
        "byte_order",
        pa.array(["big_endian"], type=pa.string()),
    )
    big_endian_payload = _replace_column(
        big_endian_payload,
        "data",
        pa.array([cloud.data], type=pa.large_binary()),
    )
    view = PointCloudBufferView.from_arrow(big_endian_payload)

    x = view.field("x")
    assert x.shape == (2,)
    assert x.strides == (point_stride,)
    assert x.dtype.str == ">f8"
    assert x.flags.aligned is False
    np.testing.assert_array_equal(x, [1.5, -4.5])
    np.testing.assert_array_equal(view.field("y"), [2.5, -5.5])
    np.testing.assert_array_equal(view.field("z"), [3.5, -6.5])
    np.testing.assert_array_equal(view.field("normal"), [[10.5, 11.5], [-10.5, -11.5]])
    assert x.__array_interface__["data"][0] == (
        np.frombuffer(view.raw_data, dtype=np.uint8).__array_interface__["data"][0] + 1
    )
    assert PointCloudBuffer.from_arrow(big_endian_payload) == cloud


def test_point_cloud_buffer_view_eagerly_validates_dense_values() -> None:
    data = bytearray(12)
    struct.pack_into("<fff", data, 0, float("nan"), 1.0, 2.0)
    sparse = PointCloudBuffer(
        width=1,
        height=1,
        is_dense=False,
        byte_order="little_endian",
        point_stride=12,
        row_stride=12,
        fields=_xyz_fields(),
        data=bytes(data),
    ).to_arrow()
    sparse_view = PointCloudBufferView.from_arrow(sparse)
    assert sparse_view.is_dense is False
    sparse_view.validate_values()

    claimed_dense = _replace_column(
        sparse, "is_dense", pa.array([True], type=pa.bool_())
    )
    with pytest.raises(ValueError, match="finite XYZ"):
        PointCloudBufferView.from_arrow(claimed_dense)
    with pytest.raises(ValueError, match="finite XYZ"):
        PointCloudBuffer.from_arrow(claimed_dense)


def test_point_cloud_buffer_empty_shape_has_empty_strided_views() -> None:
    cloud = PointCloudBuffer(
        width=0,
        height=1,
        is_dense=True,
        byte_order="little_endian",
        point_stride=12,
        row_stride=0,
        fields=_xyz_fields(),
        data=b"",
    )

    view = PointCloudBufferView.from_arrow(cloud.to_arrow())

    assert view.point_count == 0
    assert view.raw_data.nbytes == 0
    assert view.field("x").shape == (0,)
    assert view.field("x").strides == (12,)
    view.validate_values()


@pytest.mark.parametrize(
    ("updates", "match"),
    [
        ({"height": 0, "row_stride": 0, "data": b""}, "height"),
        ({"point_stride": 0, "row_stride": 0, "data": b""}, "point_stride"),
        ({"row_stride": 11, "data": bytes(11)}, "row_stride"),
        ({"data": bytes(11)}, "data length"),
        (
            {"width": 0, "height": 2, "row_stride": 0, "data": b""},
            "zero-width shape must use height=1",
        ),
        (
            {"width": 0, "height": 1, "row_stride": 1, "data": bytes(1)},
            "zero-width shape must use row_stride=0",
        ),
        (
            {"width": 0, "height": 1, "row_stride": 0, "data": b"x"},
            "data length",
        ),
        ({"fields": []}, "fields must not be empty"),
        (
            {
                "fields": [
                    PointField(name="x", offset=0, datatype="float32", count=1),
                    PointField(name="x", offset=4, datatype="float32", count=1),
                    PointField(name="z", offset=8, datatype="float32", count=1),
                ]
            },
            "unique",
        ),
        (
            {
                "fields": [
                    PointField(name="x", offset=0, datatype="float32", count=1),
                    PointField(name="y", offset=2, datatype="float32", count=1),
                    PointField(name="z", offset=8, datatype="float32", count=1),
                ]
            },
            "overlap",
        ),
        (
            {
                "fields": [
                    PointField(name="x", offset=0, datatype="float32", count=1),
                    PointField(name="y", offset=4, datatype="float32", count=1),
                    PointField(name="z", offset=10, datatype="float32", count=1),
                ]
            },
            "exceeds point_stride",
        ),
        ({"fields": _xyz_fields()[:2]}, "missing z"),
        (
            {
                "point_stride": 16,
                "row_stride": 16,
                "data": bytes(16),
                "fields": [
                    PointField(name="x", offset=0, datatype="float32", count=2),
                    PointField(name="y", offset=8, datatype="float32", count=1),
                    PointField(name="z", offset=12, datatype="float32", count=1),
                ],
            },
            "must be scalar",
        ),
        (
            {
                "point_stride": 16,
                "row_stride": 16,
                "data": bytes(16),
                "fields": [
                    PointField(name="x", offset=0, datatype="float32", count=1),
                    PointField(name="y", offset=4, datatype="float64", count=1),
                    PointField(name="z", offset=12, datatype="float32", count=1),
                ],
            },
            "same float32 or float64",
        ),
        (
            {
                "height": 2,
                "row_stride": 2**64 - 1,
                "data": b"",
            },
            r"row_stride \* height",
        ),
    ],
)
def test_point_cloud_buffer_rejects_malformed_layouts(
    updates: dict[str, object], match: str
) -> None:
    values: dict[str, object] = {
        "width": 1,
        "height": 1,
        "is_dense": False,
        "byte_order": "little_endian",
        "point_stride": 12,
        "row_stride": 12,
        "fields": _xyz_fields(),
        "data": bytes(12),
    }
    values.update(updates)

    with pytest.raises((ValueError, ValidationError), match=match):
        PointCloudBuffer.model_validate(values)


@pytest.mark.parametrize(
    ("values", "match"),
    [
        ({"name": "", "offset": 0, "datatype": "float32", "count": 1}, "name"),
        ({"name": "x", "offset": -1, "datatype": "float32", "count": 1}, "offset"),
        ({"name": "x", "offset": 0, "datatype": "float32", "count": 0}, "count"),
        ({"name": "x", "offset": 0, "datatype": "float16", "count": 1}, "datatype"),
    ],
)
def test_point_field_rejects_invalid_descriptors(
    values: dict[str, object], match: str
) -> None:
    with pytest.raises((ValueError, ValidationError), match=match):
        PointField.model_validate(values)


def test_point_field_rejects_name_that_is_not_valid_utf8_at_construction() -> None:
    with pytest.raises((ValueError, ValidationError), match="valid UTF-8"):
        PointField(name="\ud800", offset=0, datatype="float32", count=1)


def test_point_cloud_buffer_reader_accepts_reorder_and_extras_but_rejects_bad_columns() -> (
    None
):
    cloud = _organized_cloud()
    canonical = cloud.to_arrow()
    reversed_names = list(reversed(canonical.schema.names))
    reordered = pa.RecordBatch.from_arrays(
        [pa.array(["ignored"])] + [canonical[name] for name in reversed_names],
        names=["extra"] + reversed_names,
    )
    assert PointCloudBuffer.from_arrow(reordered) == cloud

    missing = canonical.select(
        [name for name in canonical.schema.names if name != "row_stride"]
    )
    with pytest.raises(ValueError, match="missing required fields: row_stride"):
        PointCloudBufferView.from_arrow(missing)

    duplicate = pa.RecordBatch.from_arrays(
        [*canonical.columns, canonical["width"]],
        names=[*canonical.schema.names, "width"],
    )
    with pytest.raises(ValueError, match="width must appear exactly once"):
        PointCloudBufferView.from_arrow(duplicate)

    wrong_type = _replace_column(
        canonical, "row_stride", pa.array([120], type=pa.int64())
    )
    with pytest.raises(TypeError, match="row_stride must have type uint64"):
        PointCloudBufferView.from_arrow(wrong_type)

    null_data = _replace_column(
        canonical, "data", pa.array([None], type=pa.large_binary())
    )
    with pytest.raises(ValueError, match="data cell must not be null"):
        PointCloudBufferView.from_arrow(null_data)


def test_point_cloud_buffer_reader_rejects_null_descriptor_children() -> None:
    canonical = _organized_cloud().to_arrow()
    nullable_struct = pa.struct(
        [
            pa.field("name", pa.string()),
            pa.field("offset", pa.uint32()),
            pa.field("datatype", pa.string()),
            pa.field("count", pa.uint32()),
        ]
    )
    null_child = pa.array(
        [[{"name": None, "offset": 0, "datatype": "float32", "count": 1}]],
        type=pa.list_(nullable_struct),
    )
    with pytest.raises(ValueError, match="struct child name must not be null"):
        PointCloudBufferView.from_arrow(
            _replace_column(canonical, "fields", null_child)
        )

    null_struct = pa.array([[None]], type=pa.list_(nullable_struct))
    with pytest.raises(ValueError, match="struct items must not be null"):
        PointCloudBufferView.from_arrow(
            _replace_column(canonical, "fields", null_struct)
        )


def test_point_cloud_buffer_reader_enforces_row_and_ipc_framing() -> None:
    canonical = _organized_cloud().to_arrow()
    with pytest.raises(ValueError, match="exactly one row, got 0"):
        PointCloudBufferView.from_arrow(canonical.slice(0, 0))

    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, canonical.schema) as writer:
        writer.write_batch(canonical)
        writer.write_batch(canonical)
    with pytest.raises(ValueError, match="exactly one RecordBatch"):
        PointCloudBuffer.from_arrow(sink.getvalue().to_pybytes())

    payload = _ipc_bytes(canonical)
    with pytest.raises(ValueError, match="trailing bytes"):
        PointCloudBufferView.from_arrow(payload + b"JUNK")
