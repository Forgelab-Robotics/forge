use std::borrow::Cow;
use std::collections::HashSet;
use std::marker::PhantomData;
use std::str::FromStr;
use std::sync::Arc;

use arrow_array::builder::{
    ArrayBuilder, ListBuilder, StringBuilder, StructBuilder, UInt32Builder,
};
use arrow_array::{
    Array, ArrayRef, BooleanArray, LargeBinaryArray, ListArray, RecordBatch, StringArray,
    StructArray, UInt32Array, UInt64Array,
};
use arrow_schema::{DataType, Field, Fields, Schema};
use bytes::Bytes;

/// Byte order used by all multi-byte values in a [`PointCloudBuffer`].
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum ByteOrder {
    LittleEndian,
    BigEndian,
}

impl ByteOrder {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::LittleEndian => "little_endian",
            Self::BigEndian => "big_endian",
        }
    }
}

impl std::fmt::Display for ByteOrder {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(self.as_str())
    }
}

impl FromStr for ByteOrder {
    type Err = PointCloudBufferError;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        match value {
            "little_endian" => Ok(Self::LittleEndian),
            "big_endian" => Ok(Self::BigEndian),
            _ => invalid(format!(
                "byte_order must be 'little_endian' or 'big_endian', got '{value}'"
            )),
        }
    }
}

impl TryFrom<&str> for ByteOrder {
    type Error = PointCloudBufferError;

    fn try_from(value: &str) -> Result<Self, Self::Error> {
        value.parse()
    }
}

/// Closed set of fixed-width numeric point-field datatypes.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum PointFieldDatatype {
    Int8,
    UInt8,
    Int16,
    UInt16,
    Int32,
    UInt32,
    Int64,
    UInt64,
    Float32,
    Float64,
}

impl PointFieldDatatype {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Int8 => "int8",
            Self::UInt8 => "uint8",
            Self::Int16 => "int16",
            Self::UInt16 => "uint16",
            Self::Int32 => "int32",
            Self::UInt32 => "uint32",
            Self::Int64 => "int64",
            Self::UInt64 => "uint64",
            Self::Float32 => "float32",
            Self::Float64 => "float64",
        }
    }

    pub const fn size_bytes(self) -> u32 {
        match self {
            Self::Int8 | Self::UInt8 => 1,
            Self::Int16 | Self::UInt16 => 2,
            Self::Int32 | Self::UInt32 | Self::Float32 => 4,
            Self::Int64 | Self::UInt64 | Self::Float64 => 8,
        }
    }
}

impl std::fmt::Display for PointFieldDatatype {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(self.as_str())
    }
}

impl FromStr for PointFieldDatatype {
    type Err = PointCloudBufferError;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        match value {
            "int8" => Ok(Self::Int8),
            "uint8" => Ok(Self::UInt8),
            "int16" => Ok(Self::Int16),
            "uint16" => Ok(Self::UInt16),
            "int32" => Ok(Self::Int32),
            "uint32" => Ok(Self::UInt32),
            "int64" => Ok(Self::Int64),
            "uint64" => Ok(Self::UInt64),
            "float32" => Ok(Self::Float32),
            "float64" => Ok(Self::Float64),
            _ => invalid(format!("unsupported point field datatype '{value}'")),
        }
    }
}

impl TryFrom<&str> for PointFieldDatatype {
    type Error = PointCloudBufferError;

    fn try_from(value: &str) -> Result<Self, Self::Error> {
        value.parse()
    }
}

/// Description of one fixed-width value or fixed-size numeric array in a point record.
#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub struct PointField {
    pub name: String,
    pub offset: u32,
    pub datatype: PointFieldDatatype,
    pub count: u32,
}

impl PointField {
    pub fn new(
        name: impl Into<String>,
        offset: u32,
        datatype: PointFieldDatatype,
        count: u32,
    ) -> Result<Self, PointCloudBufferError> {
        let value = Self {
            name: name.into(),
            offset,
            datatype,
            count,
        };
        value.validate_basic()?;
        Ok(value)
    }

    pub fn byte_len(&self) -> Result<u64, PointCloudBufferError> {
        u64::from(self.datatype.size_bytes())
            .checked_mul(u64::from(self.count))
            .ok_or_else(|| {
                PointCloudBufferError::Invalid(format!(
                    "field '{}' datatype_size * count overflows uint64",
                    self.name
                ))
            })
    }

    pub fn end_offset(&self) -> Result<u64, PointCloudBufferError> {
        u64::from(self.offset)
            .checked_add(self.byte_len()?)
            .ok_or_else(|| {
                PointCloudBufferError::Invalid(format!(
                    "field '{}' end offset overflows uint64",
                    self.name
                ))
            })
    }

    fn validate_basic(&self) -> Result<(), PointCloudBufferError> {
        if self.name.is_empty() {
            return invalid("point field names must be non-empty");
        }
        if self.count == 0 {
            return invalid(format!(
                "field '{}' count must be greater than 0",
                self.name
            ));
        }
        self.end_offset()?;
        Ok(())
    }
}

/// Layout-preserving buffer of decoded Cartesian point records.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct PointCloudBuffer {
    pub width: u32,
    pub height: u32,
    pub is_dense: bool,
    pub byte_order: ByteOrder,
    pub point_stride: u32,
    pub row_stride: u64,
    pub fields: Vec<PointField>,
    pub data: Bytes,
}

impl PointCloudBuffer {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        width: u32,
        height: u32,
        is_dense: bool,
        byte_order: ByteOrder,
        point_stride: u32,
        row_stride: u64,
        mut fields: Vec<PointField>,
        data: Bytes,
    ) -> Result<Self, PointCloudBufferError> {
        fields.sort_by(|left, right| {
            left.offset
                .cmp(&right.offset)
                .then_with(|| left.name.cmp(&right.name))
        });
        let value = Self {
            width,
            height,
            is_dense,
            byte_order,
            point_stride,
            row_stride,
            fields,
            data,
        };
        value.validate()?;
        Ok(value)
    }

    pub fn validate(&self) -> Result<(), PointCloudBufferError> {
        if self.height == 0 {
            return invalid("height must be greater than 0");
        }
        if self.point_stride == 0 {
            return invalid("point_stride must be greater than 0");
        }
        if self.width == 0 {
            if self.height != 1 {
                return invalid("width=0 requires the canonical empty height=1");
            }
            if self.row_stride != 0 {
                return invalid("width=0 requires the canonical empty row_stride=0");
            }
            if !self.data.is_empty() {
                return invalid("width=0 requires canonical empty data");
            }
        }

        let point_count = u64::from(self.width)
            .checked_mul(u64::from(self.height))
            .ok_or_else(|| {
                PointCloudBufferError::Invalid("width * height overflows uint64".to_string())
            })?;
        let packed_row_size = u64::from(self.width)
            .checked_mul(u64::from(self.point_stride))
            .ok_or_else(|| {
                PointCloudBufferError::Invalid("width * point_stride overflows uint64".to_string())
            })?;
        if self.row_stride < packed_row_size {
            return invalid(format!(
                "row_stride {} must be at least width * point_stride {packed_row_size}",
                self.row_stride
            ));
        }
        let expected_data_len = self
            .row_stride
            .checked_mul(u64::from(self.height))
            .ok_or_else(|| {
                PointCloudBufferError::Invalid("row_stride * height overflows uint64".to_string())
            })?;
        let actual_data_len = u64::try_from(self.data.len()).map_err(|_| {
            PointCloudBufferError::Invalid("data length does not fit in uint64".to_string())
        })?;
        if actual_data_len != expected_data_len {
            return invalid(format!(
                "data length {actual_data_len} must equal row_stride * height {expected_data_len}"
            ));
        }
        if self.fields.is_empty() {
            return invalid("fields must contain at least one descriptor");
        }

        let mut names = HashSet::with_capacity(self.fields.len());
        let mut ranges = Vec::with_capacity(self.fields.len());
        for field in &self.fields {
            field.validate_basic()?;
            if !names.insert(field.name.as_str()) {
                return invalid(format!(
                    "field names must be unique; duplicate '{}'",
                    field.name
                ));
            }
            let end = field.end_offset()?;
            if end > u64::from(self.point_stride) {
                return invalid(format!(
                    "field '{}' end offset {end} exceeds point_stride {}",
                    field.name, self.point_stride
                ));
            }
            ranges.push((u64::from(field.offset), end, field.name.as_str()));
        }
        ranges
            .sort_unstable_by(|left, right| left.0.cmp(&right.0).then_with(|| left.2.cmp(right.2)));
        for pair in ranges.windows(2) {
            let left = pair[0];
            let right = pair[1];
            if right.0 < left.1 {
                return invalid(format!(
                    "fields '{}' and '{}' have overlapping byte ranges",
                    left.2, right.2
                ));
            }
        }

        let x = required_coordinate_field(&self.fields, "x")?;
        let y = required_coordinate_field(&self.fields, "y")?;
        let z = required_coordinate_field(&self.fields, "z")?;
        if y.datatype != x.datatype || z.datatype != x.datatype {
            return invalid("x, y, and z must use the same datatype");
        }

        if self.is_dense {
            validate_dense_coordinates(self, point_count, x, y, z)?;
        }
        Ok(())
    }

    /// Serializes a canonical one-row batch.
    ///
    /// Canonical writers use little-endian point data. A validated big-endian
    /// value is converted element-by-element while preserving point and row
    /// padding.
    pub fn to_record_batch(&self) -> Result<RecordBatch, PointCloudBufferError> {
        self.validate()?;

        let mut fields = self.fields.clone();
        fields.sort_by(|left, right| {
            left.offset
                .cmp(&right.offset)
                .then_with(|| left.name.cmp(&right.name))
        });
        let data = self.canonical_little_endian_data()?;
        let schema = Arc::new(point_cloud_buffer_schema());
        let columns: Vec<ArrayRef> = vec![
            Arc::new(UInt32Array::from(vec![self.width])),
            Arc::new(UInt32Array::from(vec![self.height])),
            Arc::new(BooleanArray::from(vec![self.is_dense])),
            Arc::new(StringArray::from(vec![ByteOrder::LittleEndian.as_str()])),
            Arc::new(UInt32Array::from(vec![self.point_stride])),
            Arc::new(UInt64Array::from(vec![self.row_stride])),
            Arc::new(point_field_list_array(&fields)),
            Arc::new(LargeBinaryArray::from_iter_values(std::iter::once(
                data.as_ref(),
            ))),
        ];
        RecordBatch::try_new(schema, columns)
            .map_err(|error| PointCloudBufferError::Arrow(error.to_string()))
    }

    pub fn from_record_batch(batch: &RecordBatch) -> Result<Self, PointCloudBufferError> {
        if batch.num_rows() != 1 {
            return invalid("RecordBatch must contain exactly one row");
        }

        let expected = point_cloud_buffer_schema();
        let width = read_required_u32(required_column(batch, expected.field(0))?, "width")?;
        let height = read_required_u32(required_column(batch, expected.field(1))?, "height")?;
        let is_dense = read_required_bool(required_column(batch, expected.field(2))?, "is_dense")?;
        let byte_order =
            read_required_string(required_column(batch, expected.field(3))?, "byte_order")?
                .parse()?;
        let point_stride =
            read_required_u32(required_column(batch, expected.field(4))?, "point_stride")?;
        let row_stride =
            read_required_u64(required_column(batch, expected.field(5))?, "row_stride")?;
        let fields = read_point_fields(required_column(batch, expected.field(6))?)?;
        let data = read_required_binary(required_column(batch, expected.field(7))?, "data")?;

        Self::new(
            width,
            height,
            is_dense,
            byte_order,
            point_stride,
            row_stride,
            fields,
            data,
        )
    }

    pub fn view(&self) -> Result<PointCloudBufferView<'_>, PointCloudBufferError> {
        PointCloudBufferView::new(self)
    }

    fn canonical_little_endian_data(&self) -> Result<Cow<'_, [u8]>, PointCloudBufferError> {
        if self.byte_order == ByteOrder::LittleEndian {
            return Ok(Cow::Borrowed(self.data.as_ref()));
        }

        let mut data = self.data.to_vec();
        for row in 0..self.height {
            let row_offset = u64::from(row).checked_mul(self.row_stride).ok_or_else(|| {
                PointCloudBufferError::Invalid("row * row_stride overflows uint64".to_string())
            })?;
            for column in 0..self.width {
                let point_offset = u64::from(column)
                    .checked_mul(u64::from(self.point_stride))
                    .and_then(|offset| row_offset.checked_add(offset))
                    .ok_or_else(|| {
                        PointCloudBufferError::Invalid(
                            "point byte offset overflows uint64".to_string(),
                        )
                    })?;
                for field in &self.fields {
                    let element_size = u64::from(field.datatype.size_bytes());
                    if element_size == 1 {
                        continue;
                    }
                    for element in 0..field.count {
                        let element_offset = u64::from(element)
                            .checked_mul(element_size)
                            .and_then(|offset| offset.checked_add(u64::from(field.offset)))
                            .and_then(|offset| point_offset.checked_add(offset))
                            .ok_or_else(|| {
                                PointCloudBufferError::Invalid(
                                    "field element byte offset overflows uint64".to_string(),
                                )
                            })?;
                        let end = element_offset.checked_add(element_size).ok_or_else(|| {
                            PointCloudBufferError::Invalid(
                                "field element end offset overflows uint64".to_string(),
                            )
                        })?;
                        let start = usize::try_from(element_offset).map_err(|_| {
                            PointCloudBufferError::Invalid(
                                "field element offset does not fit in usize".to_string(),
                            )
                        })?;
                        let end = usize::try_from(end).map_err(|_| {
                            PointCloudBufferError::Invalid(
                                "field element end does not fit in usize".to_string(),
                            )
                        })?;
                        data[start..end].reverse();
                    }
                }
            }
        }
        Ok(Cow::Owned(data))
    }
}

/// A safe borrowed view over a validated [`PointCloudBuffer`].
#[derive(Clone, Copy, Debug)]
pub struct PointCloudBufferView<'a> {
    buffer: &'a PointCloudBuffer,
}

impl<'a> PointCloudBufferView<'a> {
    pub fn new(buffer: &'a PointCloudBuffer) -> Result<Self, PointCloudBufferError> {
        buffer.validate()?;
        Ok(Self { buffer })
    }

    pub const fn buffer(&self) -> &'a PointCloudBuffer {
        self.buffer
    }

    pub const fn width(&self) -> u32 {
        self.buffer.width
    }

    pub const fn height(&self) -> u32 {
        self.buffer.height
    }

    pub const fn is_dense(&self) -> bool {
        self.buffer.is_dense
    }

    pub const fn byte_order(&self) -> ByteOrder {
        self.buffer.byte_order
    }

    pub const fn point_stride(&self) -> u32 {
        self.buffer.point_stride
    }

    pub const fn row_stride(&self) -> u64 {
        self.buffer.row_stride
    }

    pub fn point_count(&self) -> u64 {
        u64::from(self.buffer.width) * u64::from(self.buffer.height)
    }

    pub const fn fields(&self) -> &'a [PointField] {
        self.buffer.fields.as_slice()
    }

    pub fn field(&self, name: &str) -> Option<&'a PointField> {
        self.buffer.fields.iter().find(|field| field.name == name)
    }

    pub fn has_field(&self, name: &str) -> bool {
        self.field(name).is_some()
    }

    pub fn raw_bytes(&self) -> &'a [u8] {
        self.buffer.data.as_ref()
    }

    pub fn point_bytes(&self, row: u32, column: u32) -> Option<&'a [u8]> {
        let start = self.point_offset(row, column)?;
        let end = start.checked_add(usize::try_from(self.buffer.point_stride).ok()?)?;
        self.buffer.data.get(start..end)
    }

    pub fn point_bytes_at(&self, point_index: usize) -> Option<&'a [u8]> {
        let (row, column) = self.row_column(point_index)?;
        self.point_bytes(row, column)
    }

    pub fn field_bytes(
        &self,
        row: u32,
        column: u32,
        name: &str,
    ) -> Result<&'a [u8], PointCloudBufferError> {
        let point_offset = self.point_offset(row, column).ok_or_else(|| {
            PointCloudBufferError::Invalid(format!(
                "point ({row}, {column}) is outside the {}x{} cloud",
                self.height(),
                self.width()
            ))
        })?;
        let field = self.field(name).ok_or_else(|| {
            PointCloudBufferError::Invalid(format!("unknown point field '{name}'"))
        })?;
        self.field_bytes_from_point_offset(point_offset, field)
    }

    pub fn field_bytes_at(
        &self,
        point_index: usize,
        name: &str,
    ) -> Result<&'a [u8], PointCloudBufferError> {
        let point_offset = self.point_offset_at(point_index).ok_or_else(|| {
            PointCloudBufferError::Invalid(format!(
                "point index {point_index} is outside the cloud"
            ))
        })?;
        let field = self.field(name).ok_or_else(|| {
            PointCloudBufferError::Invalid(format!("unknown point field '{name}'"))
        })?;
        self.field_bytes_from_point_offset(point_offset, field)
    }

    pub fn read_scalar<T: PointFieldScalar>(
        &self,
        row: u32,
        column: u32,
        name: &str,
    ) -> Result<T, PointCloudBufferError> {
        let field = self.scalar_field::<T>(name)?;
        let point_offset = self.point_offset(row, column).ok_or_else(|| {
            PointCloudBufferError::Invalid(format!(
                "point ({row}, {column}) is outside the {}x{} cloud",
                self.height(),
                self.width()
            ))
        })?;
        Ok(self.decode_element(point_offset, field, 0))
    }

    pub fn read_scalar_at<T: PointFieldScalar>(
        &self,
        point_index: usize,
        name: &str,
    ) -> Result<T, PointCloudBufferError> {
        let field = self.scalar_field::<T>(name)?;
        let point_offset = self.point_offset_at(point_index).ok_or_else(|| {
            PointCloudBufferError::Invalid(format!(
                "point index {point_index} is outside the cloud"
            ))
        })?;
        Ok(self.decode_element(point_offset, field, 0))
    }

    pub fn read_element<T: PointFieldScalar>(
        &self,
        row: u32,
        column: u32,
        name: &str,
        element: u32,
    ) -> Result<T, PointCloudBufferError> {
        let field = self.typed_field::<T>(name)?;
        validate_element_index(field, element)?;
        let point_offset = self.point_offset(row, column).ok_or_else(|| {
            PointCloudBufferError::Invalid(format!(
                "point ({row}, {column}) is outside the {}x{} cloud",
                self.height(),
                self.width()
            ))
        })?;
        Ok(self.decode_element(point_offset, field, element))
    }

    pub fn read_element_at<T: PointFieldScalar>(
        &self,
        point_index: usize,
        name: &str,
        element: u32,
    ) -> Result<T, PointCloudBufferError> {
        let field = self.typed_field::<T>(name)?;
        validate_element_index(field, element)?;
        let point_offset = self.point_offset_at(point_index).ok_or_else(|| {
            PointCloudBufferError::Invalid(format!(
                "point index {point_index} is outside the cloud"
            ))
        })?;
        Ok(self.decode_element(point_offset, field, element))
    }

    pub fn iter_scalar<T: PointFieldScalar>(
        &self,
        name: &str,
    ) -> Result<PointFieldIter<'a, T>, PointCloudBufferError> {
        let field = self.scalar_field::<T>(name)?;
        Ok(PointFieldIter {
            view: *self,
            field,
            next: 0,
            total: self.point_count_usize(),
            marker: PhantomData,
        })
    }

    pub fn xyz(&self, row: u32, column: u32) -> Result<[f64; 3], PointCloudBufferError> {
        let point_offset = self.point_offset(row, column).ok_or_else(|| {
            PointCloudBufferError::Invalid(format!(
                "point ({row}, {column}) is outside the {}x{} cloud",
                self.height(),
                self.width()
            ))
        })?;
        Ok(self.decode_xyz(point_offset))
    }

    pub fn xyz_at(&self, point_index: usize) -> Result<[f64; 3], PointCloudBufferError> {
        let point_offset = self.point_offset_at(point_index).ok_or_else(|| {
            PointCloudBufferError::Invalid(format!(
                "point index {point_index} is outside the cloud"
            ))
        })?;
        Ok(self.decode_xyz(point_offset))
    }

    pub fn xyz_iter(&self) -> PointCloudXyzIter<'a> {
        let x = self
            .field("x")
            .expect("validated PointCloudBuffer must contain x");
        let y = self
            .field("y")
            .expect("validated PointCloudBuffer must contain y");
        let z = self
            .field("z")
            .expect("validated PointCloudBuffer must contain z");
        PointCloudXyzIter {
            view: *self,
            x,
            y,
            z,
            next: 0,
            total: self.point_count_usize(),
        }
    }

    fn typed_field<T: PointFieldScalar>(
        &self,
        name: &str,
    ) -> Result<&'a PointField, PointCloudBufferError> {
        let field = self.field(name).ok_or_else(|| {
            PointCloudBufferError::Invalid(format!("unknown point field '{name}'"))
        })?;
        if field.datatype != T::DATATYPE {
            return invalid(format!(
                "field '{name}' has datatype {}, not {}",
                field.datatype,
                T::DATATYPE
            ));
        }
        Ok(field)
    }

    fn scalar_field<T: PointFieldScalar>(
        &self,
        name: &str,
    ) -> Result<&'a PointField, PointCloudBufferError> {
        let field = self.typed_field::<T>(name)?;
        if field.count != 1 {
            return invalid(format!(
                "field '{name}' has count {}; scalar access requires count 1",
                field.count
            ));
        }
        Ok(field)
    }

    fn point_count_usize(&self) -> usize {
        usize::try_from(self.point_count())
            .expect("validated PointCloudBuffer point count must fit in usize")
    }

    fn row_column(&self, point_index: usize) -> Option<(u32, u32)> {
        if point_index >= self.point_count_usize() || self.width() == 0 {
            return None;
        }
        let width = usize::try_from(self.width()).ok()?;
        let row = u32::try_from(point_index / width).ok()?;
        let column = u32::try_from(point_index % width).ok()?;
        Some((row, column))
    }

    fn point_offset_at(&self, point_index: usize) -> Option<usize> {
        let (row, column) = self.row_column(point_index)?;
        self.point_offset(row, column)
    }

    fn point_offset(&self, row: u32, column: u32) -> Option<usize> {
        if row >= self.height() || column >= self.width() {
            return None;
        }
        let row_offset = u64::from(row).checked_mul(self.row_stride())?;
        let column_offset = u64::from(column).checked_mul(u64::from(self.point_stride()))?;
        let offset = row_offset.checked_add(column_offset)?;
        usize::try_from(offset).ok()
    }

    fn field_bytes_from_point_offset(
        &self,
        point_offset: usize,
        field: &PointField,
    ) -> Result<&'a [u8], PointCloudBufferError> {
        let field_offset = usize::try_from(field.offset).map_err(|_| {
            PointCloudBufferError::Invalid(format!(
                "field '{}' offset does not fit in usize",
                field.name
            ))
        })?;
        let byte_len = usize::try_from(field.byte_len()?).map_err(|_| {
            PointCloudBufferError::Invalid(format!(
                "field '{}' byte length does not fit in usize",
                field.name
            ))
        })?;
        let start = point_offset.checked_add(field_offset).ok_or_else(|| {
            PointCloudBufferError::Invalid("field byte offset overflows usize".to_string())
        })?;
        let end = start.checked_add(byte_len).ok_or_else(|| {
            PointCloudBufferError::Invalid("field byte end overflows usize".to_string())
        })?;
        self.buffer.data.get(start..end).ok_or_else(|| {
            PointCloudBufferError::Invalid(format!(
                "field '{}' byte range is outside data",
                field.name
            ))
        })
    }

    fn decode_element<T: PointFieldScalar>(
        &self,
        point_offset: usize,
        field: &PointField,
        element: u32,
    ) -> T {
        let element_size = usize::try_from(field.datatype.size_bytes())
            .expect("point field datatype size must fit in usize");
        let field_offset =
            usize::try_from(field.offset).expect("validated point field offset must fit in usize");
        let element_offset = usize::try_from(element)
            .expect("point field element index must fit in usize")
            .checked_mul(element_size)
            .and_then(|offset| offset.checked_add(field_offset))
            .and_then(|offset| offset.checked_add(point_offset))
            .expect("validated point field element offset must fit in usize");
        let end = element_offset
            .checked_add(element_size)
            .expect("validated point field element end must fit in usize");
        T::decode(
            &self.buffer.data[element_offset..end],
            self.buffer.byte_order,
        )
    }

    fn decode_coordinate(&self, point_offset: usize, field: &PointField) -> f64 {
        match field.datatype {
            PointFieldDatatype::Float32 => {
                self.decode_element::<f32>(point_offset, field, 0) as f64
            }
            PointFieldDatatype::Float64 => self.decode_element::<f64>(point_offset, field, 0),
            _ => unreachable!("validated XYZ fields must be float32 or float64"),
        }
    }

    fn decode_xyz(&self, point_offset: usize) -> [f64; 3] {
        let x = self
            .field("x")
            .expect("validated PointCloudBuffer must contain x");
        let y = self
            .field("y")
            .expect("validated PointCloudBuffer must contain y");
        let z = self
            .field("z")
            .expect("validated PointCloudBuffer must contain z");
        [
            self.decode_coordinate(point_offset, x),
            self.decode_coordinate(point_offset, y),
            self.decode_coordinate(point_offset, z),
        ]
    }
}

/// Iterator over one scalar point field in row-major order.
#[derive(Clone, Debug)]
pub struct PointFieldIter<'a, T> {
    view: PointCloudBufferView<'a>,
    field: &'a PointField,
    next: usize,
    total: usize,
    marker: PhantomData<T>,
}

impl<T: PointFieldScalar> Iterator for PointFieldIter<'_, T> {
    type Item = T;

    fn next(&mut self) -> Option<Self::Item> {
        if self.next == self.total {
            return None;
        }
        let point_offset = self
            .view
            .point_offset_at(self.next)
            .expect("validated point iterator index must be in bounds");
        self.next += 1;
        Some(self.view.decode_element(point_offset, self.field, 0))
    }

    fn size_hint(&self) -> (usize, Option<usize>) {
        let remaining = self.total - self.next;
        (remaining, Some(remaining))
    }
}

impl<T: PointFieldScalar> ExactSizeIterator for PointFieldIter<'_, T> {}
impl<T: PointFieldScalar> std::iter::FusedIterator for PointFieldIter<'_, T> {}

/// Iterator over XYZ coordinates in row-major order.
#[derive(Clone, Debug)]
pub struct PointCloudXyzIter<'a> {
    view: PointCloudBufferView<'a>,
    x: &'a PointField,
    y: &'a PointField,
    z: &'a PointField,
    next: usize,
    total: usize,
}

impl Iterator for PointCloudXyzIter<'_> {
    type Item = [f64; 3];

    fn next(&mut self) -> Option<Self::Item> {
        if self.next == self.total {
            return None;
        }
        let point_offset = self
            .view
            .point_offset_at(self.next)
            .expect("validated XYZ iterator index must be in bounds");
        self.next += 1;
        Some([
            self.view.decode_coordinate(point_offset, self.x),
            self.view.decode_coordinate(point_offset, self.y),
            self.view.decode_coordinate(point_offset, self.z),
        ])
    }

    fn size_hint(&self) -> (usize, Option<usize>) {
        let remaining = self.total - self.next;
        (remaining, Some(remaining))
    }
}

impl ExactSizeIterator for PointCloudXyzIter<'_> {}
impl std::iter::FusedIterator for PointCloudXyzIter<'_> {}

mod private {
    pub trait Sealed {}
}

/// Numeric scalar that can be decoded from a point field without alignment assumptions.
pub trait PointFieldScalar: private::Sealed + Copy {
    const DATATYPE: PointFieldDatatype;

    #[doc(hidden)]
    fn decode(bytes: &[u8], byte_order: ByteOrder) -> Self;
}

macro_rules! impl_point_field_scalar {
    ($rust_type:ty, $datatype:ident, $size:expr) => {
        impl private::Sealed for $rust_type {}

        impl PointFieldScalar for $rust_type {
            const DATATYPE: PointFieldDatatype = PointFieldDatatype::$datatype;

            fn decode(bytes: &[u8], byte_order: ByteOrder) -> Self {
                let bytes: [u8; $size] = bytes
                    .try_into()
                    .expect("validated point field slice must have the datatype size");
                match byte_order {
                    ByteOrder::LittleEndian => <$rust_type>::from_le_bytes(bytes),
                    ByteOrder::BigEndian => <$rust_type>::from_be_bytes(bytes),
                }
            }
        }
    };
}

impl_point_field_scalar!(i8, Int8, 1);
impl_point_field_scalar!(u8, UInt8, 1);
impl_point_field_scalar!(i16, Int16, 2);
impl_point_field_scalar!(u16, UInt16, 2);
impl_point_field_scalar!(i32, Int32, 4);
impl_point_field_scalar!(u32, UInt32, 4);
impl_point_field_scalar!(i64, Int64, 8);
impl_point_field_scalar!(u64, UInt64, 8);
impl_point_field_scalar!(f32, Float32, 4);
impl_point_field_scalar!(f64, Float64, 8);

fn validate_element_index(field: &PointField, element: u32) -> Result<(), PointCloudBufferError> {
    if element >= field.count {
        return invalid(format!(
            "field '{}' element index {element} is outside count {}",
            field.name, field.count
        ));
    }
    Ok(())
}

fn required_coordinate_field<'a>(
    fields: &'a [PointField],
    name: &str,
) -> Result<&'a PointField, PointCloudBufferError> {
    let field = fields
        .iter()
        .find(|field| field.name == name)
        .ok_or_else(|| {
            PointCloudBufferError::Invalid(format!(
                "missing required scalar coordinate field '{name}'"
            ))
        })?;
    if field.count != 1 {
        return invalid(format!("coordinate field '{name}' must have count 1"));
    }
    if !matches!(
        field.datatype,
        PointFieldDatatype::Float32 | PointFieldDatatype::Float64
    ) {
        return invalid(format!(
            "coordinate field '{name}' must use float32 or float64"
        ));
    }
    Ok(field)
}

fn validate_dense_coordinates(
    value: &PointCloudBuffer,
    point_count: u64,
    x: &PointField,
    y: &PointField,
    z: &PointField,
) -> Result<(), PointCloudBufferError> {
    let view = PointCloudBufferView { buffer: value };
    let point_count = usize::try_from(point_count).map_err(|_| {
        PointCloudBufferError::Invalid("point count does not fit in usize".to_string())
    })?;
    for point_index in 0..point_count {
        let point_offset = view.point_offset_at(point_index).ok_or_else(|| {
            PointCloudBufferError::Invalid(format!(
                "point index {point_index} cannot be mapped to data"
            ))
        })?;
        for field in [x, y, z] {
            if !view.decode_coordinate(point_offset, field).is_finite() {
                return invalid("dense point clouds must contain finite XYZ values");
            }
        }
    }
    Ok(())
}

fn point_field_fields() -> Fields {
    vec![
        Field::new("name", DataType::Utf8, false),
        Field::new("offset", DataType::UInt32, false),
        Field::new("datatype", DataType::Utf8, false),
        Field::new("count", DataType::UInt32, false),
    ]
    .into()
}

fn point_field_list_type() -> DataType {
    DataType::List(Arc::new(Field::new(
        "item",
        DataType::Struct(point_field_fields()),
        true,
    )))
}

fn point_cloud_buffer_schema() -> Schema {
    Schema::new(vec![
        Field::new("width", DataType::UInt32, false),
        Field::new("height", DataType::UInt32, false),
        Field::new("is_dense", DataType::Boolean, false),
        Field::new("byte_order", DataType::Utf8, false),
        Field::new("point_stride", DataType::UInt32, false),
        Field::new("row_stride", DataType::UInt64, false),
        Field::new("fields", point_field_list_type(), false),
        Field::new("data", DataType::LargeBinary, false),
    ])
}

fn point_field_struct_builder() -> StructBuilder {
    StructBuilder::new(
        point_field_fields(),
        vec![
            Box::new(StringBuilder::new()) as Box<dyn ArrayBuilder>,
            Box::new(UInt32Builder::new()),
            Box::new(StringBuilder::new()),
            Box::new(UInt32Builder::new()),
        ],
    )
}

fn point_field_list_array(fields: &[PointField]) -> ListArray {
    let item_field = Arc::new(Field::new(
        "item",
        DataType::Struct(point_field_fields()),
        true,
    ));
    let mut builder = ListBuilder::new(point_field_struct_builder()).with_field(item_field);
    for field in fields {
        let values = builder.values();
        values
            .field_builder::<StringBuilder>(0)
            .expect("name builder type")
            .append_value(&field.name);
        values
            .field_builder::<UInt32Builder>(1)
            .expect("offset builder type")
            .append_value(field.offset);
        values
            .field_builder::<StringBuilder>(2)
            .expect("datatype builder type")
            .append_value(field.datatype.as_str());
        values
            .field_builder::<UInt32Builder>(3)
            .expect("count builder type")
            .append_value(field.count);
        values.append(true);
    }
    builder.append(true);
    builder.finish()
}

fn required_column<'a>(
    batch: &'a RecordBatch,
    expected: &Field,
) -> Result<&'a ArrayRef, PointCloudBufferError> {
    let schema = batch.schema();
    let matches = schema
        .fields()
        .iter()
        .enumerate()
        .filter(|(_, field)| field.name() == expected.name())
        .collect::<Vec<_>>();
    match matches.as_slice() {
        [] => invalid(format!("missing required field '{}'", expected.name())),
        [(index, actual)] => {
            if !physical_type_matches(actual.data_type(), expected.data_type()) {
                return invalid(format!(
                    "field '{}' must have Arrow type {}, got {}",
                    expected.name(),
                    expected.data_type(),
                    actual.data_type()
                ));
            }
            Ok(batch.column(*index))
        }
        _ => invalid(format!(
            "duplicate required field '{}' (found {} occurrences)",
            expected.name(),
            matches.len()
        )),
    }
}

fn physical_type_matches(actual: &DataType, expected: &DataType) -> bool {
    match (actual, expected) {
        (DataType::List(actual), DataType::List(expected)) => {
            physical_type_matches(actual.data_type(), expected.data_type())
        }
        (DataType::Struct(actual), DataType::Struct(expected)) => {
            actual.len() == expected.len()
                && actual.iter().zip(expected).all(|(actual, expected)| {
                    actual.name() == expected.name()
                        && physical_type_matches(actual.data_type(), expected.data_type())
                })
        }
        _ => actual == expected,
    }
}

fn read_required_u32(array: &ArrayRef, name: &str) -> Result<u32, PointCloudBufferError> {
    let values = array
        .as_any()
        .downcast_ref::<UInt32Array>()
        .ok_or_else(|| PointCloudBufferError::Invalid(format!("{name} must be uint32")))?;
    require_non_null(values, name)?;
    Ok(values.value(0))
}

fn read_required_u64(array: &ArrayRef, name: &str) -> Result<u64, PointCloudBufferError> {
    let values = array
        .as_any()
        .downcast_ref::<UInt64Array>()
        .ok_or_else(|| PointCloudBufferError::Invalid(format!("{name} must be uint64")))?;
    require_non_null(values, name)?;
    Ok(values.value(0))
}

fn read_required_bool(array: &ArrayRef, name: &str) -> Result<bool, PointCloudBufferError> {
    let values = array
        .as_any()
        .downcast_ref::<BooleanArray>()
        .ok_or_else(|| PointCloudBufferError::Invalid(format!("{name} must be bool")))?;
    require_non_null(values, name)?;
    Ok(values.value(0))
}

fn read_required_string(array: &ArrayRef, name: &str) -> Result<String, PointCloudBufferError> {
    let values = array
        .as_any()
        .downcast_ref::<StringArray>()
        .ok_or_else(|| PointCloudBufferError::Invalid(format!("{name} must be utf8")))?;
    require_non_null(values, name)?;
    Ok(values.value(0).to_string())
}

fn read_required_binary(array: &ArrayRef, name: &str) -> Result<Bytes, PointCloudBufferError> {
    let values = array
        .as_any()
        .downcast_ref::<LargeBinaryArray>()
        .ok_or_else(|| PointCloudBufferError::Invalid(format!("{name} must be large_binary")))?;
    require_non_null(values, name)?;
    Ok(Bytes::copy_from_slice(values.value(0)))
}

fn require_non_null(array: &dyn Array, name: &str) -> Result<(), PointCloudBufferError> {
    if array.is_empty() || array.is_null(0) {
        return invalid(format!("{name} must contain one non-null value"));
    }
    Ok(())
}

fn read_point_fields(array: &ArrayRef) -> Result<Vec<PointField>, PointCloudBufferError> {
    let list = array
        .as_any()
        .downcast_ref::<ListArray>()
        .ok_or_else(|| PointCloudBufferError::Invalid("fields must be list".to_string()))?;
    require_non_null(list, "fields")?;
    let values = list.value(0);
    let structs = values
        .as_any()
        .downcast_ref::<StructArray>()
        .ok_or_else(|| {
            PointCloudBufferError::Invalid("fields list values must be struct".to_string())
        })?;
    if structs.null_count() != 0 {
        return invalid("fields struct values must not contain nulls");
    }

    let names = structs
        .column(0)
        .as_any()
        .downcast_ref::<StringArray>()
        .ok_or_else(|| PointCloudBufferError::Invalid("fields.name must be utf8".to_string()))?;
    let offsets = structs
        .column(1)
        .as_any()
        .downcast_ref::<UInt32Array>()
        .ok_or_else(|| {
            PointCloudBufferError::Invalid("fields.offset must be uint32".to_string())
        })?;
    let datatypes = structs
        .column(2)
        .as_any()
        .downcast_ref::<StringArray>()
        .ok_or_else(|| {
            PointCloudBufferError::Invalid("fields.datatype must be utf8".to_string())
        })?;
    let counts = structs
        .column(3)
        .as_any()
        .downcast_ref::<UInt32Array>()
        .ok_or_else(|| PointCloudBufferError::Invalid("fields.count must be uint32".to_string()))?;
    for (name, child) in [
        ("fields.name", names as &dyn Array),
        ("fields.offset", offsets as &dyn Array),
        ("fields.datatype", datatypes as &dyn Array),
        ("fields.count", counts as &dyn Array),
    ] {
        if child.null_count() != 0 {
            return invalid(format!("{name} values must not contain nulls"));
        }
    }

    (0..structs.len())
        .map(|index| {
            PointField::new(
                names.value(index),
                offsets.value(index),
                datatypes.value(index).parse()?,
                counts.value(index),
            )
        })
        .collect()
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum PointCloudBufferError {
    Arrow(String),
    Invalid(String),
}

impl std::fmt::Display for PointCloudBufferError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Arrow(message) => write!(formatter, "arrow error: {message}"),
            Self::Invalid(message) => write!(formatter, "invalid point cloud buffer: {message}"),
        }
    }
}

impl std::error::Error for PointCloudBufferError {}

fn invalid<T>(message: impl Into<String>) -> Result<T, PointCloudBufferError> {
    Err(PointCloudBufferError::Invalid(message.into()))
}

#[cfg(test)]
mod tests {
    use std::sync::Arc;

    use arrow_array::builder::{
        ArrayBuilder, ListBuilder, StringBuilder, StructBuilder, UInt32Builder,
    };
    use arrow_array::{
        Array, ArrayRef, Float64Array, Int32Array, RecordBatch, StringArray, UInt32Array,
    };
    use arrow_schema::{DataType, Field, Schema};
    use bytes::Bytes;

    use super::{
        ByteOrder, PointCloudBuffer, PointField, PointFieldDatatype, point_field_list_type,
    };

    fn xyz_fields(datatype: PointFieldDatatype) -> Vec<PointField> {
        let size = datatype.size_bytes();
        vec![
            PointField::new("z", 1 + size * 2, datatype, 1).unwrap(),
            PointField::new("x", 1, datatype, 1).unwrap(),
            PointField::new("y", 1 + size, datatype, 1).unwrap(),
        ]
    }

    fn encode_f32(order: ByteOrder, value: f32) -> [u8; 4] {
        match order {
            ByteOrder::LittleEndian => value.to_le_bytes(),
            ByteOrder::BigEndian => value.to_be_bytes(),
        }
    }

    fn cloud_with_f32_points(
        order: ByteOrder,
        width: u32,
        height: u32,
        row_stride: u64,
        points: &[[f32; 3]],
    ) -> PointCloudBuffer {
        let point_stride = 14u32;
        let data_len = usize::try_from(row_stride * u64::from(height)).unwrap();
        let mut data = vec![0xa5; data_len];
        for (index, point) in points.iter().enumerate() {
            let width_usize = usize::try_from(width).unwrap();
            let row = index / width_usize;
            let column = index % width_usize;
            let base = row * usize::try_from(row_stride).unwrap()
                + column * usize::try_from(point_stride).unwrap();
            for (coordinate, offset) in point.iter().zip([1usize, 5, 9]) {
                data[base + offset..base + offset + 4]
                    .copy_from_slice(&encode_f32(order, *coordinate));
            }
        }
        PointCloudBuffer::new(
            width,
            height,
            true,
            order,
            point_stride,
            row_stride,
            xyz_fields(PointFieldDatatype::Float32),
            Bytes::from(data),
        )
        .unwrap()
    }

    fn canonical_cloud() -> PointCloudBuffer {
        cloud_with_f32_points(
            ByteOrder::LittleEndian,
            2,
            1,
            28,
            &[[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]],
        )
    }

    fn replace_column(
        batch: &RecordBatch,
        name: &str,
        field: Field,
        column: ArrayRef,
    ) -> RecordBatch {
        let index = batch.schema().index_of(name).unwrap();
        let mut fields = batch.schema().fields().to_vec();
        fields[index] = Arc::new(field);
        let mut columns = batch.columns().to_vec();
        columns[index] = column;
        RecordBatch::try_new(Arc::new(Schema::new(fields)), columns).unwrap()
    }

    #[test]
    fn writer_schema_and_descriptor_order_are_canonical() {
        let batch = canonical_cloud().to_record_batch().unwrap();
        assert_eq!(batch.num_rows(), 1);
        let expected = [
            ("width", DataType::UInt32),
            ("height", DataType::UInt32),
            ("is_dense", DataType::Boolean),
            ("byte_order", DataType::Utf8),
            ("point_stride", DataType::UInt32),
            ("row_stride", DataType::UInt64),
            ("fields", point_field_list_type()),
            ("data", DataType::LargeBinary),
        ];
        for (actual, (name, datatype)) in batch.schema().fields().iter().zip(expected) {
            assert_eq!(actual.name(), name);
            assert_eq!(actual.data_type(), &datatype);
            assert!(!actual.is_nullable(), "{name} must be non-nullable");
        }

        let schema = batch.schema();
        let DataType::List(item) = schema.field(6).data_type() else {
            panic!("fields must be a list")
        };
        assert!(item.is_nullable());
        let DataType::Struct(children) = item.data_type() else {
            panic!("fields items must be structs")
        };
        assert_eq!(
            children
                .iter()
                .map(|field| (
                    field.name().as_str(),
                    field.data_type(),
                    field.is_nullable()
                ))
                .collect::<Vec<_>>(),
            vec![
                ("name", &DataType::Utf8, false),
                ("offset", &DataType::UInt32, false),
                ("datatype", &DataType::Utf8, false),
                ("count", &DataType::UInt32, false),
            ]
        );

        let list = batch
            .column(6)
            .as_any()
            .downcast_ref::<arrow_array::ListArray>()
            .unwrap();
        assert!(!list.is_null(0));
        let values = list.value(0);
        let structs = values
            .as_any()
            .downcast_ref::<arrow_array::StructArray>()
            .unwrap();
        assert_eq!(structs.null_count(), 0);
        let names = structs
            .column(0)
            .as_any()
            .downcast_ref::<StringArray>()
            .unwrap();
        assert_eq!(
            (0..names.len())
                .map(|index| names.value(index))
                .collect::<Vec<_>>(),
            vec!["x", "y", "z"]
        );
    }

    #[test]
    fn canonical_empty_shape_roundtrips_with_layout_descriptors() {
        let cloud = PointCloudBuffer::new(
            0,
            1,
            true,
            ByteOrder::LittleEndian,
            14,
            0,
            xyz_fields(PointFieldDatatype::Float32),
            Bytes::new(),
        )
        .unwrap();

        let view = cloud.view().unwrap();
        assert_eq!(view.point_count(), 0);
        assert!(view.raw_bytes().is_empty());
        assert_eq!(view.fields().len(), 3);
        assert_eq!(view.iter_scalar::<f32>("x").unwrap().next(), None);

        let batch = cloud.to_record_batch().unwrap();
        assert_eq!(PointCloudBuffer::from_record_batch(&batch).unwrap(), cloud);
    }

    #[test]
    fn rejects_noncanonical_empty_shapes_and_missing_layout() {
        let fields = xyz_fields(PointFieldDatatype::Float32);
        let make_empty =
            |height, point_stride, row_stride, fields: Vec<PointField>, data: Bytes| {
                PointCloudBuffer::new(
                    0,
                    height,
                    true,
                    ByteOrder::LittleEndian,
                    point_stride,
                    row_stride,
                    fields,
                    data,
                )
            };

        assert!(make_empty(2, 14, 0, fields.clone(), Bytes::new()).is_err());
        assert!(make_empty(1, 14, 1, fields.clone(), Bytes::from_static(&[0])).is_err());
        assert!(make_empty(1, 14, 0, fields.clone(), Bytes::from_static(&[0])).is_err());
        assert!(make_empty(1, 0, 0, fields, Bytes::new()).is_err());
        assert!(make_empty(1, 14, 0, Vec::new(), Bytes::new()).is_err());
    }

    #[test]
    fn little_endian_roundtrip_and_typed_access() {
        let cloud = canonical_cloud();
        let batch = cloud.to_record_batch().unwrap();
        let decoded = PointCloudBuffer::from_record_batch(&batch).unwrap();
        assert_eq!(decoded, cloud);

        let view = decoded.view().unwrap();
        assert_eq!(view.field("x").unwrap().offset, 1);
        assert_eq!(view.raw_bytes(), decoded.data.as_ref());
        assert_eq!(view.read_scalar::<f32>(0, 1, "y").unwrap(), 5.0);
        assert_eq!(view.read_scalar_at::<f32>(1, "z").unwrap(), 6.0);
        assert!(view.read_scalar::<f64>(0, 0, "x").is_err());
        assert_eq!(view.xyz_at(0).unwrap(), [1.0, 2.0, 3.0]);
        assert_eq!(
            view.iter_scalar::<f32>("x").unwrap().collect::<Vec<_>>(),
            vec![1.0, 4.0]
        );
    }

    #[test]
    fn big_endian_unaligned_reads_and_canonical_serialization() {
        let cloud = cloud_with_f32_points(
            ByteOrder::BigEndian,
            2,
            1,
            28,
            &[[1.25, -2.5, 3.75], [4.5, 5.25, -6.0]],
        );
        let view = cloud.view().unwrap();
        assert_eq!(view.xyz_at(0).unwrap(), [1.25, -2.5, 3.75]);
        assert_eq!(view.read_scalar::<f32>(0, 1, "z").unwrap(), -6.0);

        let batch = cloud.to_record_batch().unwrap();
        let decoded = PointCloudBuffer::from_record_batch(&batch).unwrap();
        assert_eq!(decoded.byte_order, ByteOrder::LittleEndian);
        assert_eq!(
            decoded.view().unwrap().xyz_iter().collect::<Vec<_>>(),
            view.xyz_iter().collect::<Vec<_>>()
        );
    }

    #[test]
    fn organized_view_honors_row_padding() {
        let cloud = cloud_with_f32_points(
            ByteOrder::LittleEndian,
            2,
            2,
            36,
            &[
                [1.0, 2.0, 3.0],
                [4.0, 5.0, 6.0],
                [7.0, 8.0, 9.0],
                [10.0, 11.0, 12.0],
            ],
        );
        let view = cloud.view().unwrap();
        assert_eq!(view.point_count(), 4);
        assert_eq!(view.xyz(1, 0).unwrap(), [7.0, 8.0, 9.0]);
        assert_eq!(view.xyz_at(3).unwrap(), [10.0, 11.0, 12.0]);
        assert_eq!(view.point_bytes_at(2).unwrap(), &cloud.data[36..50]);
        assert_eq!(
            view.xyz_iter().collect::<Vec<_>>(),
            vec![
                [1.0, 2.0, 3.0],
                [4.0, 5.0, 6.0],
                [7.0, 8.0, 9.0],
                [10.0, 11.0, 12.0],
            ]
        );
    }

    #[test]
    fn scalar_array_elements_are_endian_safe() {
        let mut fields = xyz_fields(PointFieldDatatype::Float32);
        fields.push(PointField::new("normal", 13, PointFieldDatatype::Int16, 3).unwrap());
        let mut data = vec![0u8; 20];
        for (value, offset) in [1.0f32, 2.0, 3.0].iter().zip([1usize, 5, 9]) {
            data[offset..offset + 4].copy_from_slice(&value.to_be_bytes());
        }
        for (value, offset) in [-4i16, 5, 6].iter().zip([13usize, 15, 17]) {
            data[offset..offset + 2].copy_from_slice(&value.to_be_bytes());
        }
        let cloud = PointCloudBuffer::new(
            1,
            1,
            true,
            ByteOrder::BigEndian,
            20,
            20,
            fields,
            Bytes::from(data),
        )
        .unwrap();
        let view = cloud.view().unwrap();
        assert_eq!(view.read_element::<i16>(0, 0, "normal", 0).unwrap(), -4);
        assert_eq!(view.read_element_at::<i16>(0, "normal", 2).unwrap(), 6);
        assert!(view.read_scalar::<i16>(0, 0, "normal").is_err());
    }

    #[test]
    fn rejects_bad_strides_field_ranges_types_and_data() {
        let fields = xyz_fields(PointFieldDatatype::Float32);
        assert!(
            PointCloudBuffer::new(
                1,
                0,
                true,
                ByteOrder::LittleEndian,
                14,
                14,
                fields.clone(),
                Bytes::new(),
            )
            .is_err()
        );
        assert!(
            PointCloudBuffer::new(
                1,
                1,
                true,
                ByteOrder::LittleEndian,
                0,
                0,
                fields.clone(),
                Bytes::new(),
            )
            .is_err()
        );
        assert!(
            PointCloudBuffer::new(
                2,
                1,
                true,
                ByteOrder::LittleEndian,
                14,
                27,
                fields.clone(),
                Bytes::from(vec![0; 27]),
            )
            .is_err()
        );
        assert!(
            PointCloudBuffer::new(
                1,
                1,
                true,
                ByteOrder::LittleEndian,
                14,
                14,
                fields.clone(),
                Bytes::from(vec![0; 13]),
            )
            .is_err()
        );

        let mut overlap = fields.clone();
        overlap.push(PointField::new("intensity", 3, PointFieldDatatype::UInt16, 1).unwrap());
        assert!(
            PointCloudBuffer::new(
                1,
                1,
                true,
                ByteOrder::LittleEndian,
                14,
                14,
                overlap,
                Bytes::from(vec![0; 14]),
            )
            .is_err()
        );

        let mut past_stride = fields.clone();
        past_stride.push(PointField::new("ring", 13, PointFieldDatatype::UInt16, 1).unwrap());
        assert!(
            PointCloudBuffer::new(
                1,
                1,
                true,
                ByteOrder::LittleEndian,
                14,
                14,
                past_stride,
                Bytes::from(vec![0; 14]),
            )
            .is_err()
        );

        let mut mismatched_xyz = fields;
        mismatched_xyz
            .iter_mut()
            .find(|field| field.name == "z")
            .unwrap()
            .datatype = PointFieldDatatype::UInt32;
        assert!(
            PointCloudBuffer::new(
                1,
                1,
                true,
                ByteOrder::LittleEndian,
                14,
                14,
                mismatched_xyz,
                Bytes::from(vec![0; 14]),
            )
            .is_err()
        );
    }

    #[test]
    fn rejects_invalid_descriptors_and_dense_nonfinite_xyz() {
        assert!(PointField::new("", 0, PointFieldDatatype::Float32, 1).is_err());
        assert!(PointField::new("x", 0, PointFieldDatatype::Float32, 0).is_err());

        let mut duplicate = xyz_fields(PointFieldDatatype::Float32);
        duplicate.push(PointField::new("x", 13, PointFieldDatatype::UInt8, 1).unwrap());
        assert!(
            PointCloudBuffer::new(
                1,
                1,
                false,
                ByteOrder::LittleEndian,
                14,
                14,
                duplicate,
                Bytes::from(vec![0; 14]),
            )
            .is_err()
        );

        let mut data = vec![0u8; 14];
        data[1..5].copy_from_slice(&f32::NAN.to_le_bytes());
        assert!(
            PointCloudBuffer::new(
                1,
                1,
                true,
                ByteOrder::LittleEndian,
                14,
                14,
                xyz_fields(PointFieldDatatype::Float32),
                Bytes::from(data.clone()),
            )
            .is_err()
        );
        assert!(
            PointCloudBuffer::new(
                1,
                1,
                false,
                ByteOrder::LittleEndian,
                14,
                14,
                xyz_fields(PointFieldDatatype::Float32),
                Bytes::from(data),
            )
            .is_ok()
        );
    }

    #[test]
    fn reader_resolves_reordered_fields_and_ignores_extras() {
        let batch = canonical_cloud().to_record_batch().unwrap();
        let mut fields = batch.schema().fields().to_vec();
        let mut columns = batch.columns().to_vec();
        fields.reverse();
        columns.reverse();
        fields.push(Arc::new(Field::new("extra", DataType::Int32, true)));
        columns.push(Arc::new(Int32Array::from(vec![Some(7)])));
        let reordered = RecordBatch::try_new(Arc::new(Schema::new(fields)), columns).unwrap();
        assert_eq!(
            PointCloudBuffer::from_record_batch(&reordered).unwrap(),
            canonical_cloud()
        );
    }

    #[test]
    fn reader_rejects_missing_duplicate_wrong_type_and_null() {
        let batch = canonical_cloud().to_record_batch().unwrap();

        let mut fields = batch.schema().fields().to_vec();
        let mut columns = batch.columns().to_vec();
        fields.remove(0);
        columns.remove(0);
        let missing = RecordBatch::try_new(Arc::new(Schema::new(fields)), columns).unwrap();
        assert!(PointCloudBuffer::from_record_batch(&missing).is_err());

        let mut fields = batch.schema().fields().to_vec();
        let mut columns = batch.columns().to_vec();
        fields.push(Arc::clone(&fields[0]));
        columns.push(Arc::clone(&columns[0]));
        let duplicate = RecordBatch::try_new(Arc::new(Schema::new(fields)), columns).unwrap();
        assert!(PointCloudBuffer::from_record_batch(&duplicate).is_err());

        let wrong_type = replace_column(
            &batch,
            "width",
            Field::new("width", DataType::Float64, false),
            Arc::new(Float64Array::from(vec![1.0])),
        );
        assert!(PointCloudBuffer::from_record_batch(&wrong_type).is_err());

        let null_width = replace_column(
            &batch,
            "width",
            Field::new("width", DataType::UInt32, true),
            Arc::new(UInt32Array::from(vec![None])),
        );
        assert!(PointCloudBuffer::from_record_batch(&null_width).is_err());
    }

    #[test]
    fn reader_rejects_null_descriptor_list_structs_and_children() {
        let batch = canonical_cloud().to_record_batch().unwrap();
        let descriptor_fields = || -> arrow_schema::Fields {
            vec![
                Field::new("name", DataType::Utf8, true),
                Field::new("offset", DataType::UInt32, true),
                Field::new("datatype", DataType::Utf8, true),
                Field::new("count", DataType::UInt32, true),
            ]
            .into()
        };
        let item_field = || {
            Arc::new(Field::new(
                "item",
                DataType::Struct(descriptor_fields()),
                true,
            ))
        };
        let descriptor_builder = || {
            StructBuilder::new(
                descriptor_fields(),
                vec![
                    Box::new(StringBuilder::new()) as Box<dyn ArrayBuilder>,
                    Box::new(UInt32Builder::new()),
                    Box::new(StringBuilder::new()),
                    Box::new(UInt32Builder::new()),
                ],
            )
        };
        let malformed_list_type = || DataType::List(item_field());

        let null_list = {
            let mut builder = ListBuilder::new(descriptor_builder()).with_field(item_field());
            builder.append(false);
            replace_column(
                &batch,
                "fields",
                Field::new("fields", malformed_list_type(), true),
                Arc::new(builder.finish()),
            )
        };
        assert!(PointCloudBuffer::from_record_batch(&null_list).is_err());

        let malformed_list = |null_struct: bool, null_name: bool| {
            let mut builder = ListBuilder::new(descriptor_builder()).with_field(item_field());
            let values = builder.values();
            if null_name {
                values
                    .field_builder::<StringBuilder>(0)
                    .unwrap()
                    .append_null();
            } else {
                values
                    .field_builder::<StringBuilder>(0)
                    .unwrap()
                    .append_value("x");
            }
            values
                .field_builder::<UInt32Builder>(1)
                .unwrap()
                .append_value(0);
            values
                .field_builder::<StringBuilder>(2)
                .unwrap()
                .append_value("float32");
            values
                .field_builder::<UInt32Builder>(3)
                .unwrap()
                .append_value(1);
            values.append(!null_struct);
            builder.append(true);
            builder.finish()
        };

        let null_struct = replace_column(
            &batch,
            "fields",
            Field::new("fields", malformed_list_type(), false),
            Arc::new(malformed_list(true, false)),
        );
        assert!(PointCloudBuffer::from_record_batch(&null_struct).is_err());

        let null_child = replace_column(
            &batch,
            "fields",
            Field::new("fields", malformed_list_type(), false),
            Arc::new(malformed_list(false, true)),
        );
        assert!(PointCloudBuffer::from_record_batch(&null_child).is_err());
    }

    #[test]
    fn closed_wire_enums_reject_unknown_strings() {
        assert!("middle_endian".parse::<ByteOrder>().is_err());
        assert!("float16".parse::<PointFieldDatatype>().is_err());
    }
}
