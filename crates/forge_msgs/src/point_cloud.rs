use std::sync::Arc;

use arrow_array::{ArrayRef, BooleanArray, RecordBatch, UInt32Array};
use arrow_schema::{DataType, Field, Schema};

use crate::column::{
    f32_list, list_type, read_bool, read_f32_list, read_u8_list, read_u32, u8_list,
};

#[derive(Clone, Debug, PartialEq)]
pub struct PointCloud {
    pub width: u32,
    pub height: u32,
    pub is_dense: bool,
    pub x: Vec<f32>,
    pub y: Vec<f32>,
    pub z: Vec<f32>,
    pub intensity: Vec<f32>,
    pub red: Vec<u8>,
    pub green: Vec<u8>,
    pub blue: Vec<u8>,
}

impl PointCloud {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        width: u32,
        height: u32,
        is_dense: bool,
        x: Vec<f32>,
        y: Vec<f32>,
        z: Vec<f32>,
        intensity: Vec<f32>,
        red: Vec<u8>,
        green: Vec<u8>,
        blue: Vec<u8>,
    ) -> Result<Self, PointCloudError> {
        let value = Self {
            width,
            height,
            is_dense,
            x,
            y,
            z,
            intensity,
            red,
            green,
            blue,
        };
        value.validate()?;
        Ok(value)
    }

    pub fn from_xyz(x: Vec<f32>, y: Vec<f32>, z: Vec<f32>) -> Result<Self, PointCloudError> {
        let width = u32::try_from(x.len()).map_err(|_| {
            PointCloudError::Invalid("point count exceeds the uint32 range".to_string())
        })?;
        let is_dense = x.iter().chain(&y).chain(&z).all(|value| value.is_finite());
        Self::new(
            width,
            1,
            is_dense,
            x,
            y,
            z,
            Vec::new(),
            Vec::new(),
            Vec::new(),
            Vec::new(),
        )
    }

    pub fn to_record_batch(&self) -> Result<RecordBatch, PointCloudError> {
        self.validate()?;
        let schema = Arc::new(Schema::new(vec![
            Field::new("width", DataType::UInt32, false),
            Field::new("height", DataType::UInt32, false),
            Field::new("is_dense", DataType::Boolean, false),
            Field::new("x", list_type(DataType::Float32), false),
            Field::new("y", list_type(DataType::Float32), false),
            Field::new("z", list_type(DataType::Float32), false),
            Field::new("intensity", list_type(DataType::Float32), false),
            Field::new("red", list_type(DataType::UInt8), false),
            Field::new("green", list_type(DataType::UInt8), false),
            Field::new("blue", list_type(DataType::UInt8), false),
        ]));
        let columns: Vec<ArrayRef> = vec![
            Arc::new(UInt32Array::from(vec![self.width])),
            Arc::new(UInt32Array::from(vec![self.height])),
            Arc::new(BooleanArray::from(vec![self.is_dense])),
            Arc::new(f32_list(&self.x)),
            Arc::new(f32_list(&self.y)),
            Arc::new(f32_list(&self.z)),
            Arc::new(f32_list(&self.intensity)),
            Arc::new(u8_list(&self.red)),
            Arc::new(u8_list(&self.green)),
            Arc::new(u8_list(&self.blue)),
        ];
        RecordBatch::try_new(schema, columns)
            .map_err(|error| PointCloudError::Arrow(error.to_string()))
    }

    pub fn from_record_batch(batch: &RecordBatch) -> Result<Self, PointCloudError> {
        if batch.num_rows() != 1 {
            return Err(PointCloudError::Invalid(
                "RecordBatch must contain exactly one row".to_string(),
            ));
        }
        validate_required_fields(batch)?;
        Self::new(
            read_u32(batch, "width").map_err(PointCloudError::Invalid)?,
            read_u32(batch, "height").map_err(PointCloudError::Invalid)?,
            read_bool(batch, "is_dense").map_err(PointCloudError::Invalid)?,
            read_f32_list(batch, "x").map_err(PointCloudError::Invalid)?,
            read_f32_list(batch, "y").map_err(PointCloudError::Invalid)?,
            read_f32_list(batch, "z").map_err(PointCloudError::Invalid)?,
            read_f32_list(batch, "intensity").map_err(PointCloudError::Invalid)?,
            read_u8_list(batch, "red").map_err(PointCloudError::Invalid)?,
            read_u8_list(batch, "green").map_err(PointCloudError::Invalid)?,
            read_u8_list(batch, "blue").map_err(PointCloudError::Invalid)?,
        )
    }

    fn validate(&self) -> Result<(), PointCloudError> {
        let count = self.x.len();
        if self.y.len() != count || self.z.len() != count {
            return Err(PointCloudError::Invalid(
                "x, y, and z must have the same length".to_string(),
            ));
        }
        let expected_count = (self.width as usize)
            .checked_mul(self.height as usize)
            .ok_or_else(|| {
                PointCloudError::Invalid("width * height overflows usize".to_string())
            })?;
        if expected_count != count {
            return Err(PointCloudError::Invalid(
                "width * height must equal the point count".to_string(),
            ));
        }
        validate_optional_len("intensity", self.intensity.len(), count)?;
        validate_optional_len("red", self.red.len(), count)?;
        validate_optional_len("green", self.green.len(), count)?;
        validate_optional_len("blue", self.blue.len(), count)?;
        let populated_rgb = [
            !self.red.is_empty(),
            !self.green.is_empty(),
            !self.blue.is_empty(),
        ];
        if populated_rgb.iter().any(|value| *value) && !populated_rgb.iter().all(|value| *value) {
            return Err(PointCloudError::Invalid(
                "red, green, and blue must all be empty or all be populated".to_string(),
            ));
        }
        if self.is_dense
            && self
                .x
                .iter()
                .chain(&self.y)
                .chain(&self.z)
                .any(|value| !value.is_finite())
        {
            return Err(PointCloudError::Invalid(
                "dense point clouds must contain finite XYZ values".to_string(),
            ));
        }
        Ok(())
    }
}

fn validate_required_fields(batch: &RecordBatch) -> Result<(), PointCloudError> {
    const REQUIRED_FIELDS: [&str; 10] = [
        "width",
        "height",
        "is_dense",
        "x",
        "y",
        "z",
        "intensity",
        "red",
        "green",
        "blue",
    ];

    let schema = batch.schema();
    for name in REQUIRED_FIELDS {
        let count = schema
            .fields()
            .iter()
            .filter(|field| field.name() == name)
            .count();
        match count {
            0 => {
                return Err(PointCloudError::Invalid(format!(
                    "missing required field '{name}'"
                )));
            }
            1 => {}
            count => {
                return Err(PointCloudError::Invalid(format!(
                    "duplicate required field '{name}' (found {count} occurrences)"
                )));
            }
        }
    }
    Ok(())
}

fn validate_optional_len(
    name: &str,
    actual: usize,
    expected: usize,
) -> Result<(), PointCloudError> {
    if actual != 0 && actual != expected {
        return Err(PointCloudError::Invalid(format!(
            "{name} must be empty or have the same length as x"
        )));
    }
    Ok(())
}

#[derive(Debug)]
pub enum PointCloudError {
    Arrow(String),
    Invalid(String),
}

impl std::fmt::Display for PointCloudError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Arrow(message) => write!(formatter, "arrow error: {message}"),
            Self::Invalid(message) => write!(formatter, "invalid point cloud: {message}"),
        }
    }
}

impl std::error::Error for PointCloudError {}

#[cfg(test)]
mod tests {
    use std::sync::Arc;

    use arrow_array::builder::{Float32Builder, ListBuilder, UInt8Builder};
    use arrow_array::{Array, ArrayRef, ListArray, RecordBatch, UInt32Array};
    use arrow_schema::{DataType, Field, Schema};

    use super::PointCloud;

    fn one_point_batch() -> RecordBatch {
        PointCloud::from_xyz(vec![1.0], vec![2.0], vec![3.0])
            .unwrap()
            .to_record_batch()
            .unwrap()
    }

    fn replace_x_column(batch: &RecordBatch, x: ListArray, nullable: bool) -> RecordBatch {
        let x: ArrayRef = Arc::new(x);
        let mut fields = batch.schema().fields().to_vec();
        fields[3] = Arc::new(Field::new("x", x.data_type().clone(), nullable));
        let mut columns = batch.columns().to_vec();
        columns[3] = x;
        RecordBatch::try_new(Arc::new(Schema::new(fields)), columns).unwrap()
    }

    fn duplicate_column(batch: &RecordBatch, name: &str) -> RecordBatch {
        let schema = batch.schema();
        let index = schema.index_of(name).unwrap();
        let mut fields = schema.fields().to_vec();
        fields.push(Arc::clone(&fields[index]));
        let mut columns = batch.columns().to_vec();
        columns.push(Arc::clone(batch.column(index)));
        RecordBatch::try_new(Arc::new(Schema::new(fields)), columns).unwrap()
    }

    fn remove_column(batch: &RecordBatch, name: &str) -> RecordBatch {
        let schema = batch.schema();
        let index = schema.index_of(name).unwrap();
        let mut fields = schema.fields().to_vec();
        fields.remove(index);
        let mut columns = batch.columns().to_vec();
        columns.remove(index);
        RecordBatch::try_new(Arc::new(Schema::new(fields)), columns).unwrap()
    }

    #[test]
    fn point_cloud_roundtrip() {
        let cloud = PointCloud::new(
            2,
            1,
            true,
            vec![1.0, 2.0],
            vec![3.0, 4.0],
            vec![5.0, 6.0],
            Vec::new(),
            vec![255, 0],
            vec![0, 255],
            vec![0, 0],
        )
        .unwrap();
        let batch = cloud.to_record_batch().unwrap();
        assert_eq!(PointCloud::from_record_batch(&batch).unwrap(), cloud);

        let unorganized =
            PointCloud::from_xyz(vec![1.0, 2.0], vec![3.0, 4.0], vec![5.0, 6.0]).unwrap();
        assert_eq!(unorganized.width, 2);
        assert_eq!(unorganized.height, 1);
        assert!(unorganized.is_dense);

        let sparse = PointCloud::from_xyz(vec![f32::NAN], vec![0.0], vec![0.0]).unwrap();
        assert_eq!(sparse.width, 1);
        assert_eq!(sparse.height, 1);
        assert!(!sparse.is_dense);
    }

    #[test]
    fn writer_schema_has_contract_order_types_and_non_nullability() {
        let batch = one_point_batch();
        let schema = batch.schema();
        let fields = schema.fields();
        let expected = [
            ("width", DataType::UInt32),
            ("height", DataType::UInt32),
            ("is_dense", DataType::Boolean),
            (
                "x",
                DataType::List(Arc::new(Field::new("item", DataType::Float32, true))),
            ),
            (
                "y",
                DataType::List(Arc::new(Field::new("item", DataType::Float32, true))),
            ),
            (
                "z",
                DataType::List(Arc::new(Field::new("item", DataType::Float32, true))),
            ),
            (
                "intensity",
                DataType::List(Arc::new(Field::new("item", DataType::Float32, true))),
            ),
            (
                "red",
                DataType::List(Arc::new(Field::new("item", DataType::UInt8, true))),
            ),
            (
                "green",
                DataType::List(Arc::new(Field::new("item", DataType::UInt8, true))),
            ),
            (
                "blue",
                DataType::List(Arc::new(Field::new("item", DataType::UInt8, true))),
            ),
        ];

        assert_eq!(fields.len(), expected.len());
        for (field, (name, data_type)) in fields.iter().zip(expected) {
            assert_eq!(field.name(), name);
            assert_eq!(field.data_type(), &data_type, "unexpected type for {name}");
            assert!(!field.is_nullable(), "{name} must be non-nullable");
        }
    }

    #[test]
    fn from_record_batch_requires_exactly_one_row() {
        let valid = one_point_batch();
        let empty = RecordBatch::new_empty(valid.schema());
        let empty_error = PointCloud::from_record_batch(&empty).unwrap_err();
        assert_eq!(
            empty_error.to_string(),
            "invalid point cloud: RecordBatch must contain exactly one row"
        );

        let two_rows = RecordBatch::try_new(
            Arc::new(Schema::new(vec![Field::new(
                "width",
                DataType::UInt32,
                false,
            )])),
            vec![Arc::new(UInt32Array::from(vec![1, 1]))],
        )
        .unwrap();
        let two_row_error = PointCloud::from_record_batch(&two_rows).unwrap_err();
        assert_eq!(
            two_row_error.to_string(),
            "invalid point cloud: RecordBatch must contain exactly one row"
        );
    }

    #[test]
    fn from_record_batch_rejects_duplicate_required_fields() {
        for name in [
            "width",
            "height",
            "is_dense",
            "x",
            "y",
            "z",
            "intensity",
            "red",
            "green",
            "blue",
        ] {
            let batch = duplicate_column(&one_point_batch(), name);
            let error = PointCloud::from_record_batch(&batch).unwrap_err();
            assert_eq!(
                error.to_string(),
                format!(
                    "invalid point cloud: duplicate required field '{name}' (found 2 occurrences)"
                )
            );
        }
    }

    #[test]
    fn from_record_batch_rejects_missing_required_fields() {
        for name in [
            "width",
            "height",
            "is_dense",
            "x",
            "y",
            "z",
            "intensity",
            "red",
            "green",
            "blue",
        ] {
            let batch = remove_column(&one_point_batch(), name);
            let error = PointCloud::from_record_batch(&batch).unwrap_err();
            assert_eq!(
                error.to_string(),
                format!("invalid point cloud: missing required field '{name}'")
            );
        }
    }

    #[test]
    fn from_record_batch_rejects_wrong_list_primitive() {
        let mut x = ListBuilder::new(UInt8Builder::new());
        x.values().append_value(1);
        x.append(true);
        let batch = replace_x_column(&one_point_batch(), x.finish(), false);

        let error = PointCloud::from_record_batch(&batch).unwrap_err();
        assert_eq!(
            error.to_string(),
            "invalid point cloud: x values must be float32"
        );
    }

    #[test]
    fn from_record_batch_rejects_null_list_cell() {
        let mut x = ListBuilder::new(Float32Builder::new());
        x.append(false);
        let batch = replace_x_column(&one_point_batch(), x.finish(), true);

        let error = PointCloud::from_record_batch(&batch).unwrap_err();
        assert_eq!(
            error.to_string(),
            "invalid point cloud: x must contain one non-null list row"
        );
    }

    #[test]
    fn from_record_batch_rejects_null_child_value() {
        let mut x = ListBuilder::new(Float32Builder::new());
        x.values().append_null();
        x.append(true);
        let batch = replace_x_column(&one_point_batch(), x.finish(), false);

        let error = PointCloud::from_record_batch(&batch).unwrap_err();
        assert_eq!(
            error.to_string(),
            "invalid point cloud: x values must not contain nulls"
        );
    }

    #[test]
    fn rejects_dense_non_finite_point() {
        let result = PointCloud::new(
            1,
            1,
            true,
            vec![f32::NAN],
            vec![0.0],
            vec![0.0],
            Vec::new(),
            Vec::new(),
            Vec::new(),
            Vec::new(),
        );
        assert!(result.is_err());
    }

    #[test]
    fn rejects_partial_rgb_columns() {
        let result = PointCloud::new(
            1,
            1,
            true,
            vec![0.0],
            vec![0.0],
            vec![0.0],
            Vec::new(),
            vec![255],
            Vec::new(),
            Vec::new(),
        );
        assert!(result.is_err());
    }
}
