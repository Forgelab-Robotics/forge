from __future__ import annotations

import gc
import struct
import warnings
import weakref

import numpy as np
import pyarrow as pa
import pytest

from forge_msgs import PointCloud, PointCloudBatch, PointCloudView


def _readonly(value: np.ndarray) -> np.ndarray:
    current: object | None = value
    while isinstance(current, np.ndarray):
        current.setflags(write=False)
        current = current.base
    return value


def _to_ipc_bytes(batch: pa.RecordBatch) -> bytes:
    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, batch.schema) as writer:
        writer.write_batch(batch)
    return sink.getvalue().to_pybytes()


def _value_buffer_address(batch: pa.RecordBatch, name: str) -> int:
    buffer = batch[name][0].values.buffers()[1]
    assert buffer is not None
    return buffer.address


def _replace_column(
    batch: pa.RecordBatch, name: str, column: pa.Array
) -> pa.RecordBatch:
    columns = list(batch.columns)
    columns[batch.schema.get_field_index(name)] = column
    return pa.RecordBatch.from_arrays(columns, names=batch.schema.names)


def test_point_cloud_batch_never_borrows_readonly_soa_buffers() -> None:
    x = _readonly(np.arange(6, dtype=np.float32).reshape(2, 3))
    y = _readonly((np.arange(6, dtype=np.float32) + 10).reshape(2, 3))
    z = _readonly((np.arange(6, dtype=np.float32) + 20).reshape(2, 3))
    intensity = _readonly(np.arange(6, dtype=np.float32).reshape(2, 3))
    red = _readonly(np.arange(6, dtype=np.uint8).reshape(2, 3))
    green = _readonly((np.arange(6, dtype=np.uint8) + 10).reshape(2, 3))
    blue = _readonly((np.arange(6, dtype=np.uint8) + 20).reshape(2, 3))

    cloud = PointCloudBatch.from_numpy(
        x=x,
        y=y,
        z=z,
        intensity=intensity,
        rgb=(red, green, blue),
        copy="never",
    )
    batch = cloud.to_arrow()

    assert batch.schema == PointCloud(
        width=3,
        height=2,
        is_dense=True,
        x=x.reshape(-1).tolist(),
        y=y.reshape(-1).tolist(),
        z=z.reshape(-1).tolist(),
        intensity=intensity.reshape(-1).tolist(),
        red=red.reshape(-1).tolist(),
        green=green.reshape(-1).tolist(),
        blue=blue.reshape(-1).tolist(),
    ).to_arrow().schema
    assert _value_buffer_address(batch, "x") == x.__array_interface__["data"][0]
    assert _value_buffer_address(batch, "y") == y.__array_interface__["data"][0]
    assert _value_buffer_address(batch, "z") == z.__array_interface__["data"][0]
    assert _value_buffer_address(batch, "intensity") == intensity.__array_interface__["data"][0]
    assert _value_buffer_address(batch, "red") == red.__array_interface__["data"][0]
    assert _value_buffer_address(batch, "green") == green.__array_interface__["data"][0]
    assert _value_buffer_address(batch, "blue") == blue.__array_interface__["data"][0]

    view = cloud.view()
    assert (view.width, view.height, view.point_count) == (3, 2, 6)
    assert view.has_intensity is True
    assert view.has_rgb is True
    assert view.x.flags.writeable is False
    assert view.x.__array_interface__["data"][0] == x.__array_interface__["data"][0]
    np.testing.assert_array_equal(view.blue, blue.reshape(-1))


def test_point_cloud_batch_always_copies_and_snapshots_sources() -> None:
    x = np.array([1.0, 2.0], dtype=np.float32)
    y = np.array([3.0, 4.0], dtype=np.float32)
    z = np.array([5.0, 6.0], dtype=np.float32)

    batch = PointCloudBatch.from_numpy(x=x, y=y, z=z).to_arrow()

    assert _value_buffer_address(batch, "x") != x.__array_interface__["data"][0]
    x[0] = 99.0
    assert batch["x"][0].values[0].as_py() == 1.0


def test_point_cloud_batch_normalizes_ndarray_subclasses() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", PendingDeprecationWarning)
        x = np.matrix([[1.0, 2.0, 3.0]], dtype=np.float32)
        y = np.matrix([[4.0, 5.0, 6.0]], dtype=np.float32)
        z = np.matrix([[7.0, 8.0, 9.0]], dtype=np.float32)

    view = PointCloudBatch.from_numpy(x=x, y=y, z=z).view()

    assert (view.width, view.height, view.point_count) == (3, 1, 3)
    assert type(view.x) is np.ndarray
    np.testing.assert_array_equal(view.x, [1.0, 2.0, 3.0])
    np.testing.assert_array_equal(view.y, [4.0, 5.0, 6.0])
    np.testing.assert_array_equal(view.z, [7.0, 8.0, 9.0])


def test_point_cloud_batch_rejects_masked_arrays() -> None:
    masked_xyz = np.ma.array(
        [1.0, 2.0], dtype=np.float32, mask=[False, True]
    )
    xyz = np.zeros(2, dtype=np.float32)
    with pytest.raises(TypeError, match="MaskedArray"):
        PointCloudBatch.from_numpy(x=masked_xyz, y=xyz, z=xyz)

    masked_rgb = np.ma.array(
        [[1, 2, 3], [4, 5, 6]], dtype=np.uint8, mask=False
    )
    with pytest.raises(TypeError, match="MaskedArray"):
        PointCloudBatch.from_numpy(x=xyz, y=xyz, z=xyz, rgb=masked_rgb)


def test_point_cloud_batch_if_needed_borrows_readonly_and_copies_writable() -> None:
    readonly = _readonly(np.array([1.0, 2.0], dtype=np.float32))
    writable = np.array([3.0, 4.0], dtype=np.float32)
    z = _readonly(np.array([5.0, 6.0], dtype=np.float32))

    batch = PointCloudBatch.from_numpy(
        x=readonly,
        y=writable,
        z=z,
        copy="if_needed",
    ).to_arrow()

    assert _value_buffer_address(batch, "x") == readonly.__array_interface__["data"][0]
    assert _value_buffer_address(batch, "y") != writable.__array_interface__["data"][0]
    assert _value_buffer_address(batch, "z") == z.__array_interface__["data"][0]


def test_point_cloud_batch_never_rejects_non_borrowable_inputs() -> None:
    writable = np.array([1.0, 2.0], dtype=np.float32)
    readonly = _readonly(writable.copy())
    with pytest.raises(ValueError, match="read-only"):
        PointCloudBatch.from_numpy(
            x=writable,
            y=readonly,
            z=readonly,
            copy="never",
        )

    strided = _readonly(np.arange(4, dtype=np.float32)[::2])
    with pytest.raises(ValueError, match="C-contiguous"):
        PointCloudBatch.from_numpy(
            x=strided,
            y=readonly,
            z=readonly,
            copy="never",
        )

    float64 = _readonly(np.array([1.0, 2.0], dtype=np.float64))
    with pytest.raises(ValueError, match="dtype float32"):
        PointCloudBatch.from_numpy(
            x=float64,
            y=float64,
            z=float64,
            copy="never",
            casting="same_kind",
        )


def test_point_cloud_batch_if_needed_rejects_or_copies_writable_backing_storage() -> None:
    base = np.array([1.0, 2.0], dtype=np.float32)
    readonly_alias = base.view()
    readonly_alias.setflags(write=False)
    stable = _readonly(np.array([3.0, 4.0], dtype=np.float32))

    batch = PointCloudBatch.from_numpy(
        x=readonly_alias,
        y=stable,
        z=stable,
        copy="if_needed",
    ).to_arrow()
    assert _value_buffer_address(batch, "x") != readonly_alias.__array_interface__["data"][0]

    with pytest.raises(ValueError, match="backing storage must be read-only"):
        PointCloudBatch.from_numpy(
            x=readonly_alias,
            y=stable,
            z=stable,
            copy="never",
        )


def test_point_cloud_batch_fails_closed_for_readonly_view_of_writable_buffer() -> None:
    backing = bytearray(np.array([1.0, 2.0], dtype=np.float32).tobytes())
    readonly_alias = np.frombuffer(memoryview(backing).toreadonly(), dtype=np.float32)
    stable = _readonly(np.array([3.0, 4.0], dtype=np.float32))

    batch = PointCloudBatch.from_numpy(
        x=readonly_alias,
        y=stable,
        z=stable,
        copy="if_needed",
    ).to_arrow()
    assert _value_buffer_address(batch, "x") != readonly_alias.__array_interface__["data"][0]
    struct.pack_into("<f", backing, 0, 99.0)
    assert batch["x"][0].values[0].as_py() == 1.0

    with pytest.raises(ValueError, match="backing storage must be read-only"):
        PointCloudBatch.from_numpy(
            x=readonly_alias,
            y=stable,
            z=stable,
            copy="never",
        )


def test_point_cloud_batch_casting_is_explicit_and_checks_float32_range() -> None:
    values = np.array([1.0, 2.0], dtype=np.float64)
    with pytest.raises(TypeError, match="casting='no'"):
        PointCloudBatch.from_numpy(x=values, y=values, z=values)
    with pytest.raises(TypeError, match="casting='safe'"):
        PointCloudBatch.from_numpy(
            x=values,
            y=values,
            z=values,
            casting="safe",
        )

    batch = PointCloudBatch.from_numpy(
        x=values,
        y=values,
        z=values,
        casting="same_kind",
    ).to_arrow()
    assert batch["x"][0].values.type == pa.float32()

    overflow = np.array([float.fromhex("0x1p+128")], dtype=np.float64)
    with pytest.raises(ValueError, match="outside the float32 range"):
        PointCloudBatch.from_numpy(
            x=overflow,
            y=overflow,
            z=overflow,
            casting="same_kind",
        )


def test_point_cloud_batch_safe_casts_float16_without_overflow_warning() -> None:
    values = np.array([1.0, 2.0], dtype=np.float16)

    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        with np.errstate(over="raise"):
            view = PointCloudBatch.from_numpy(
                x=values,
                y=values,
                z=values,
                casting="safe",
            ).view()

    assert view.x.dtype == np.dtype(np.float32)
    np.testing.assert_array_equal(view.x, [1.0, 2.0])


@pytest.mark.parametrize("interleaved", [False, True])
def test_point_cloud_batch_rejects_rgb_narrowing_overflow(interleaved: bool) -> None:
    xyz = np.zeros(3, dtype=np.float32)
    red = np.array([0, 256, 65535], dtype=np.uint16)
    green = np.zeros(3, dtype=np.uint16)
    blue = np.ones(3, dtype=np.uint16)
    rgb = np.stack((red, green, blue), axis=-1) if interleaved else (red, green, blue)

    with pytest.raises(ValueError, match=r"red values.*\[0, 255\]"):
        PointCloudBatch.from_numpy(
            x=xyz,
            y=xyz,
            z=xyz,
            rgb=rgb,
            casting="same_kind",
        )


def test_point_cloud_batch_deinterleaves_rgb_when_copying() -> None:
    x = np.arange(4, dtype=np.float32).reshape(2, 2)
    y = x + 10
    z = x + 20
    rgb = np.array(
        [
            [[1, 2, 3], [4, 5, 6]],
            [[7, 8, 9], [10, 11, 12]],
        ],
        dtype=np.uint8,
    )

    cloud = PointCloudBatch.from_numpy(x=x, y=y, z=z, rgb=rgb)
    view = cloud.view()

    assert (view.width, view.height) == (2, 2)
    np.testing.assert_array_equal(view.red, [1, 4, 7, 10])
    np.testing.assert_array_equal(view.green, [2, 5, 8, 11])
    np.testing.assert_array_equal(view.blue, [3, 6, 9, 12])

    for value in (x, y, z, rgb):
        _readonly(value)
    with pytest.raises(ValueError, match="requires deinterleaving"):
        PointCloudBatch.from_numpy(
            x=x,
            y=y,
            z=z,
            rgb=rgb,
            copy="never",
        )


def test_point_cloud_batch_validates_shapes_dimensions_and_density() -> None:
    xyz = np.zeros((2, 3), dtype=np.float32)
    with pytest.raises(ValueError, match="same shape"):
        PointCloudBatch.from_numpy(x=xyz, y=xyz[:, :2], z=xyz)
    with pytest.raises(ValueError, match="provided together"):
        PointCloudBatch.from_numpy(x=xyz, y=xyz, z=xyz, width=3)
    with pytest.raises(ValueError, match="must match height and width"):
        PointCloudBatch.from_numpy(
            x=xyz,
            y=xyz,
            z=xyz,
            width=2,
            height=3,
        )
    with pytest.raises(TypeError, match="intensity must be a numpy.ndarray"):
        PointCloudBatch.from_numpy(
            x=xyz,
            y=xyz,
            z=xyz,
            intensity=[0.0] * 6,  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError, match="intensity shape"):
        PointCloudBatch.from_numpy(
            x=xyz,
            y=xyz,
            z=xyz,
            intensity=np.zeros(5, dtype=np.float32),
        )

    z_with_nan = xyz.copy()
    z_with_nan[0, 0] = np.nan
    sparse = PointCloudBatch.from_numpy(x=xyz, y=xyz, z=z_with_nan).view()
    assert sparse.is_dense is False
    with pytest.raises(ValueError, match="finite XYZ"):
        PointCloudBatch.from_numpy(
            x=xyz,
            y=xyz,
            z=z_with_nan,
            is_dense=True,
        )


def test_point_cloud_view_is_zero_copy_readonly_and_metadata_isolated() -> None:
    owned = PointCloud(
        width=2,
        height=1,
        is_dense=True,
        x=[1.0, 2.0],
        y=[3.0, 4.0],
        z=[5.0, 6.0],
        red=[10, 20],
        green=[30, 40],
        blue=[50, 60],
    )
    batch = owned.to_arrow()
    view = PointCloudView.from_arrow(batch)

    assert view.record_batch is batch
    assert view.point_count == 2
    assert view.has_intensity is False
    assert view.has_rgb is True
    assert view.x.__array_interface__["data"][0] == _value_buffer_address(batch, "x")
    with pytest.raises(ValueError, match="read-only"):
        view.x[0] = 9.0

    reshaped = view.x
    reshaped.shape = (1, 2)
    assert view.x.shape == (2,)
    with pytest.raises(AttributeError):
        view.width = 1  # type: ignore[misc]
    with pytest.raises(AttributeError):
        view.height = 2  # type: ignore[misc]
    with pytest.raises(AttributeError):
        view.is_dense = False  # type: ignore[misc]
    assert view.to_owned() == owned


def test_point_cloud_bytes_reject_trailing_data_and_second_stream() -> None:
    payload = _to_ipc_bytes(
        PointCloud(x=[1.0], y=[2.0], z=[3.0]).to_arrow()
    )
    assert PointCloudView.from_arrow(payload).point_count == 1

    for malformed in (payload + b"JUNK", payload + payload):
        with pytest.raises(ValueError, match="trailing bytes"):
            PointCloud.from_arrow(malformed)
        with pytest.raises(ValueError, match="trailing bytes"):
            PointCloudView.from_arrow(malformed)


def test_point_cloud_view_preserves_table_and_sliced_value_buffers() -> None:
    owned = PointCloud(x=[1.0, 2.0], y=[3.0, 4.0], z=[5.0, 6.0])
    batch = owned.to_arrow()
    table = pa.Table.from_arrays(
        [pa.chunked_array([column.slice(0, 0), column]) for column in batch.columns],
        schema=batch.schema,
    )

    table_view = PointCloudView.from_arrow(table)
    assert table_view.x.__array_interface__["data"][0] == _value_buffer_address(batch, "x")

    source_values = pa.array([99.0, 1.0, 2.0], type=pa.float32()).slice(1, 2)
    sliced_x = pa.ListArray.from_arrays(pa.array([0, 2], type=pa.int32()), source_values)
    sliced_batch = _replace_column(batch, "x", sliced_x)
    sliced_view = PointCloudView.from_arrow(sliced_batch)
    source_buffer = source_values.buffers()[1]
    assert source_buffer is not None
    assert sliced_view.x.__array_interface__["data"][0] == (
        source_buffer.address + source_values.offset * source_values.type.bit_width // 8
    )
    np.testing.assert_array_equal(sliced_view.x, [1.0, 2.0])


def test_point_cloud_view_validates_semantic_invariants_without_materializing() -> None:
    canonical = PointCloud(x=[1.0], y=[2.0], z=[3.0]).to_arrow()
    bad_width = _replace_column(canonical, "width", pa.array([2], type=pa.uint32()))
    with pytest.raises(ValueError, match=r"width \* height"):
        PointCloudView.from_arrow(bad_width)

    bad_intensity = _replace_column(
        canonical,
        "intensity",
        pa.array([[1.0, 2.0]], type=pa.list_(pa.float32())),
    )
    with pytest.raises(ValueError, match="intensity"):
        PointCloudView.from_arrow(bad_intensity)

    partial_rgb = _replace_column(
        canonical,
        "red",
        pa.array([[255]], type=pa.list_(pa.uint8())),
    )
    with pytest.raises(ValueError, match="all be empty or all be populated"):
        PointCloudView.from_arrow(partial_rgb)

    sparse = PointCloud(x=[np.nan], y=[0.0], z=[0.0]).to_arrow()
    false_dense = _replace_column(
        sparse,
        "is_dense",
        pa.array([True], type=pa.bool_()),
    )
    with pytest.raises(ValueError, match="finite XYZ"):
        PointCloudView.from_arrow(false_dense)


def test_arrow_record_batch_retains_borrowed_numpy_owner() -> None:
    x = _readonly(np.array([1.0, 2.0], dtype=np.float32))
    y = _readonly(np.array([3.0, 4.0], dtype=np.float32))
    z = _readonly(np.array([5.0, 6.0], dtype=np.float32))
    x_ref = weakref.ref(x)

    cloud = PointCloudBatch.from_numpy(x=x, y=y, z=z, copy="never")
    record_batch = cloud.to_arrow()
    del cloud, x, y, z
    gc.collect()

    assert x_ref() is not None
    np.testing.assert_array_equal(PointCloudView.from_arrow(record_batch).x, [1.0, 2.0])


def test_empty_point_cloud_batch_uses_canonical_unorganized_shape() -> None:
    empty = _readonly(np.empty(0, dtype=np.float32))
    view = PointCloudBatch.from_numpy(
        x=empty,
        y=empty,
        z=empty,
        copy="never",
    ).view()

    assert (view.width, view.height, view.point_count) == (0, 1, 0)
    assert view.is_dense is True
    assert view.has_intensity is False
    assert view.has_rgb is False
