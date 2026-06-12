use std::sync::Arc;

use arrow_array::builder::{
    BooleanBuilder, Float32Builder, Int32Builder, LargeBinaryBuilder, ListBuilder, StringBuilder,
    UInt8Builder, UInt32Builder,
};
use arrow_array::{
    Array, ArrayRef, BooleanArray, Float32Array, Int32Array, LargeBinaryArray, ListArray,
    RecordBatch, StringArray, UInt8Array, UInt32Array,
};
use arrow_schema::{DataType, Field};
use bytes::Bytes;

pub(crate) fn list_type(value_type: DataType) -> DataType {
    DataType::List(Arc::new(Field::new("item", value_type, true)))
}

pub(crate) fn string_list(values: &[String]) -> ListArray {
    let mut builder = ListBuilder::new(StringBuilder::new());
    for value in values {
        builder.values().append_value(value);
    }
    builder.append(true);
    builder.finish()
}

pub(crate) fn f32_list(values: &[f32]) -> ListArray {
    let mut builder = ListBuilder::new(Float32Builder::new());
    for value in values {
        builder.values().append_value(*value);
    }
    builder.append(true);
    builder.finish()
}

pub(crate) fn u32_list(values: &[u32]) -> ListArray {
    let mut builder = ListBuilder::new(UInt32Builder::new());
    for value in values {
        builder.values().append_value(*value);
    }
    builder.append(true);
    builder.finish()
}

pub(crate) fn i32_list(values: &[i32]) -> ListArray {
    let mut builder = ListBuilder::new(Int32Builder::new());
    for value in values {
        builder.values().append_value(*value);
    }
    builder.append(true);
    builder.finish()
}

pub(crate) fn u8_list(values: &[u8]) -> ListArray {
    let mut builder = ListBuilder::new(UInt8Builder::new());
    for value in values {
        builder.values().append_value(*value);
    }
    builder.append(true);
    builder.finish()
}

pub(crate) fn bool_list(values: &[bool]) -> ListArray {
    let mut builder = ListBuilder::new(BooleanBuilder::new());
    for value in values {
        builder.values().append_value(*value);
    }
    builder.append(true);
    builder.finish()
}

pub(crate) fn binary_list(values: &[Bytes]) -> ListArray {
    let mut builder = ListBuilder::new(LargeBinaryBuilder::new());
    for value in values {
        builder.values().append_value(value);
    }
    builder.append(true);
    builder.finish()
}

pub(crate) fn read_string_list(batch: &RecordBatch, name: &str) -> Result<Vec<String>, String> {
    let values = read_list(batch, name)?;
    let array = values
        .as_any()
        .downcast_ref::<StringArray>()
        .ok_or_else(|| format!("{name} values must be utf8"))?;
    reject_nulls(array, name)?;
    Ok((0..array.len())
        .map(|index| array.value(index).to_string())
        .collect())
}

pub(crate) fn read_f32_list(batch: &RecordBatch, name: &str) -> Result<Vec<f32>, String> {
    let values = read_list(batch, name)?;
    let array = values
        .as_any()
        .downcast_ref::<Float32Array>()
        .ok_or_else(|| format!("{name} values must be float32"))?;
    reject_nulls(array, name)?;
    Ok((0..array.len()).map(|index| array.value(index)).collect())
}

pub(crate) fn read_u32_list(batch: &RecordBatch, name: &str) -> Result<Vec<u32>, String> {
    let values = read_list(batch, name)?;
    let array = values
        .as_any()
        .downcast_ref::<UInt32Array>()
        .ok_or_else(|| format!("{name} values must be uint32"))?;
    reject_nulls(array, name)?;
    Ok((0..array.len()).map(|index| array.value(index)).collect())
}

pub(crate) fn read_i32_list(batch: &RecordBatch, name: &str) -> Result<Vec<i32>, String> {
    let values = read_list(batch, name)?;
    let array = values
        .as_any()
        .downcast_ref::<Int32Array>()
        .ok_or_else(|| format!("{name} values must be int32"))?;
    reject_nulls(array, name)?;
    Ok((0..array.len()).map(|index| array.value(index)).collect())
}

pub(crate) fn read_u8_list(batch: &RecordBatch, name: &str) -> Result<Vec<u8>, String> {
    let values = read_list(batch, name)?;
    let array = values
        .as_any()
        .downcast_ref::<UInt8Array>()
        .ok_or_else(|| format!("{name} values must be uint8"))?;
    reject_nulls(array, name)?;
    Ok((0..array.len()).map(|index| array.value(index)).collect())
}

pub(crate) fn read_bool_list(batch: &RecordBatch, name: &str) -> Result<Vec<bool>, String> {
    let values = read_list(batch, name)?;
    let array = values
        .as_any()
        .downcast_ref::<BooleanArray>()
        .ok_or_else(|| format!("{name} values must be bool"))?;
    reject_nulls(array, name)?;
    Ok((0..array.len()).map(|index| array.value(index)).collect())
}

pub(crate) fn read_binary_list(batch: &RecordBatch, name: &str) -> Result<Vec<Bytes>, String> {
    let values = read_list(batch, name)?;
    let array = values
        .as_any()
        .downcast_ref::<LargeBinaryArray>()
        .ok_or_else(|| format!("{name} values must be large_binary"))?;
    reject_nulls(array, name)?;
    Ok((0..array.len())
        .map(|index| Bytes::copy_from_slice(array.value(index)))
        .collect())
}

pub(crate) fn column_as<'a, T: 'static + Array>(
    batch: &'a RecordBatch,
    name: &str,
) -> Result<&'a T, String> {
    let index = batch
        .schema()
        .index_of(name)
        .map_err(|_| format!("missing {name} column"))?;
    batch
        .column(index)
        .as_any()
        .downcast_ref::<T>()
        .ok_or_else(|| format!("{name} column has unexpected type"))
}

pub(crate) fn read_string(batch: &RecordBatch, name: &str) -> Result<String, String> {
    let array = scalar_column::<StringArray>(batch, name)?;
    Ok(array.value(0).to_string())
}

pub(crate) fn read_u32(batch: &RecordBatch, name: &str) -> Result<u32, String> {
    let array = scalar_column::<UInt32Array>(batch, name)?;
    Ok(array.value(0))
}

pub(crate) fn read_bool(batch: &RecordBatch, name: &str) -> Result<bool, String> {
    let array = scalar_column::<BooleanArray>(batch, name)?;
    Ok(array.value(0))
}

pub(crate) fn read_binary(batch: &RecordBatch, name: &str) -> Result<Bytes, String> {
    let array = scalar_column::<LargeBinaryArray>(batch, name)?;
    Ok(Bytes::copy_from_slice(array.value(0)))
}

fn read_list(batch: &RecordBatch, name: &str) -> Result<ArrayRef, String> {
    let list = column_as::<ListArray>(batch, name)?;
    if list.len() == 0 || list.is_null(0) {
        return Err(format!("{name} must contain one non-null list row"));
    }
    Ok(list.value(0))
}

fn scalar_column<'a, T: 'static + Array>(
    batch: &'a RecordBatch,
    name: &str,
) -> Result<&'a T, String> {
    let array = column_as::<T>(batch, name)?;
    if array.len() == 0 || array.is_null(0) {
        return Err(format!("{name} must contain one non-null scalar row"));
    }
    Ok(array)
}

fn reject_nulls(array: &dyn Array, name: &str) -> Result<(), String> {
    if array.null_count() != 0 {
        return Err(format!("{name} values must not contain nulls"));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use std::sync::Arc;

    use arrow_array::{ArrayRef, RecordBatch, UInt32Array};
    use arrow_schema::{DataType, Field, Schema};

    use super::read_u32;

    #[test]
    fn scalar_reader_rejects_null() {
        let schema = Arc::new(Schema::new(vec![Field::new(
            "value",
            DataType::UInt32,
            true,
        )]));
        let columns: Vec<ArrayRef> = vec![Arc::new(UInt32Array::from(vec![None]))];
        let batch = RecordBatch::try_new(schema, columns).unwrap();

        assert!(read_u32(&batch, "value").is_err());
    }
}
