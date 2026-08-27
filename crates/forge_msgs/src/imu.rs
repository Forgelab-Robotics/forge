use std::sync::Arc;

use arrow_array::builder::{Float64Builder, ListBuilder};
use arrow_array::{Array, ArrayRef, Float64Array, ListArray, RecordBatch, StructArray};
use arrow_schema::{DataType, Field, Fields, Schema};

/// Quaternion orientation using explicit XYZW component names.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct ImuOrientation {
    pub qx: f64,
    pub qy: f64,
    pub qz: f64,
    pub qw: f64,
}

impl ImuOrientation {
    pub fn new(qx: f64, qy: f64, qz: f64, qw: f64) -> Result<Self, ImuError> {
        let value = Self { qx, qy, qz, qw };
        value.validate()?;
        Ok(value)
    }

    pub fn validate(&self) -> Result<(), ImuError> {
        for (name, value) in [
            ("orientation.qx", self.qx),
            ("orientation.qy", self.qy),
            ("orientation.qz", self.qz),
            ("orientation.qw", self.qw),
        ] {
            validate_finite(name, value)?;
        }
        if self.qx == 0.0 && self.qy == 0.0 && self.qz == 0.0 && self.qw == 0.0 {
            return invalid("orientation quaternion must not be all zero");
        }
        Ok(())
    }
}

/// Three-axis IMU vector value.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct ImuVector3 {
    pub x: f64,
    pub y: f64,
    pub z: f64,
}

impl ImuVector3 {
    pub fn new(x: f64, y: f64, z: f64) -> Result<Self, ImuError> {
        let value = Self { x, y, z };
        value.validate()?;
        Ok(value)
    }

    pub fn validate(&self) -> Result<(), ImuError> {
        self.validate_named("vector")
    }

    fn validate_named(&self, name: &str) -> Result<(), ImuError> {
        validate_finite(&format!("{name}.x"), self.x)?;
        validate_finite(&format!("{name}.y"), self.y)?;
        validate_finite(&format!("{name}.z"), self.z)?;
        Ok(())
    }
}

/// SI-unit inertial measurement sample.
#[derive(Clone, Debug, PartialEq)]
pub struct Imu {
    pub orientation: Option<ImuOrientation>,
    pub angular_velocity: ImuVector3,
    pub linear_acceleration: ImuVector3,
    pub orientation_covariance: Vec<f64>,
    pub angular_velocity_covariance: Vec<f64>,
    pub linear_acceleration_covariance: Vec<f64>,
    pub temperature_celsius: Option<f64>,
}

impl Imu {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        orientation: Option<ImuOrientation>,
        angular_velocity: ImuVector3,
        linear_acceleration: ImuVector3,
        orientation_covariance: Vec<f64>,
        angular_velocity_covariance: Vec<f64>,
        linear_acceleration_covariance: Vec<f64>,
        temperature_celsius: Option<f64>,
    ) -> Result<Self, ImuError> {
        let value = Self {
            orientation,
            angular_velocity,
            linear_acceleration,
            orientation_covariance,
            angular_velocity_covariance,
            linear_acceleration_covariance,
            temperature_celsius,
        };
        value.validate()?;
        Ok(value)
    }

    pub fn validate(&self) -> Result<(), ImuError> {
        if let Some(orientation) = self.orientation {
            orientation.validate()?;
        } else if !self.orientation_covariance.is_empty() {
            return invalid("orientation_covariance must be empty when orientation is absent");
        }
        self.angular_velocity.validate_named("angular_velocity")?;
        self.linear_acceleration
            .validate_named("linear_acceleration")?;
        validate_covariance("orientation_covariance", &self.orientation_covariance)?;
        validate_covariance(
            "angular_velocity_covariance",
            &self.angular_velocity_covariance,
        )?;
        validate_covariance(
            "linear_acceleration_covariance",
            &self.linear_acceleration_covariance,
        )?;
        if let Some(temperature) = self.temperature_celsius {
            validate_finite("temperature_celsius", temperature)?;
        }
        Ok(())
    }

    pub fn to_record_batch(&self) -> Result<RecordBatch, ImuError> {
        self.validate()?;
        let schema = Arc::new(imu_schema());
        let columns: Vec<ArrayRef> = vec![
            Arc::new(optional_orientation_array(self.orientation)),
            Arc::new(vector_array(self.angular_velocity)),
            Arc::new(vector_array(self.linear_acceleration)),
            Arc::new(covariance_array(&self.orientation_covariance)),
            Arc::new(covariance_array(&self.angular_velocity_covariance)),
            Arc::new(covariance_array(&self.linear_acceleration_covariance)),
            Arc::new(Float64Array::from(vec![self.temperature_celsius])),
        ];
        RecordBatch::try_new(schema, columns).map_err(|error| ImuError::Arrow(error.to_string()))
    }

    pub fn from_record_batch(batch: &RecordBatch) -> Result<Self, ImuError> {
        if batch.num_rows() != 1 {
            return invalid("RecordBatch must contain exactly one row");
        }
        let expected = imu_schema();
        let orientation = read_orientation(
            required_column(batch, expected.field(0))?,
            "orientation",
            true,
        )?;
        let angular_velocity = read_vector(
            required_column(batch, expected.field(1))?,
            "angular_velocity",
        )?;
        let linear_acceleration = read_vector(
            required_column(batch, expected.field(2))?,
            "linear_acceleration",
        )?;
        let orientation_covariance = read_covariance(
            required_column(batch, expected.field(3))?,
            "orientation_covariance",
        )?;
        let angular_velocity_covariance = read_covariance(
            required_column(batch, expected.field(4))?,
            "angular_velocity_covariance",
        )?;
        let linear_acceleration_covariance = read_covariance(
            required_column(batch, expected.field(5))?,
            "linear_acceleration_covariance",
        )?;
        let temperature_celsius = read_optional_f64(
            required_column(batch, expected.field(6))?,
            "temperature_celsius",
        )?;
        Self::new(
            orientation,
            angular_velocity,
            linear_acceleration,
            orientation_covariance,
            angular_velocity_covariance,
            linear_acceleration_covariance,
            temperature_celsius,
        )
    }
}

fn validate_finite(name: &str, value: f64) -> Result<(), ImuError> {
    if !value.is_finite() {
        return invalid(format!("{name} must be finite"));
    }
    Ok(())
}

fn validate_covariance(name: &str, values: &[f64]) -> Result<(), ImuError> {
    if !values.is_empty() && values.len() != 9 {
        return invalid(format!("{name} must be empty or contain exactly 9 values"));
    }
    if values.iter().any(|value| !value.is_finite()) {
        return invalid(format!("{name} values must be finite"));
    }
    if values.len() == 9 && [0usize, 4, 8].iter().any(|index| values[*index] < 0.0) {
        return invalid(format!("{name} diagonal values must be non-negative"));
    }
    Ok(())
}

fn orientation_fields() -> Fields {
    vec![
        Field::new("qx", DataType::Float64, false),
        Field::new("qy", DataType::Float64, false),
        Field::new("qz", DataType::Float64, false),
        Field::new("qw", DataType::Float64, false),
    ]
    .into()
}

fn vector_fields() -> Fields {
    vec![
        Field::new("x", DataType::Float64, false),
        Field::new("y", DataType::Float64, false),
        Field::new("z", DataType::Float64, false),
    ]
    .into()
}

fn covariance_type() -> DataType {
    DataType::List(Arc::new(Field::new("item", DataType::Float64, true)))
}

fn imu_schema() -> Schema {
    Schema::new(vec![
        Field::new("orientation", DataType::Struct(orientation_fields()), true),
        Field::new("angular_velocity", DataType::Struct(vector_fields()), false),
        Field::new(
            "linear_acceleration",
            DataType::Struct(vector_fields()),
            false,
        ),
        Field::new("orientation_covariance", covariance_type(), false),
        Field::new("angular_velocity_covariance", covariance_type(), false),
        Field::new("linear_acceleration_covariance", covariance_type(), false),
        Field::new("temperature_celsius", DataType::Float64, true),
    ])
}

fn orientation_array(value: ImuOrientation) -> StructArray {
    StructArray::new(
        orientation_fields(),
        vec![
            Arc::new(Float64Array::from(vec![value.qx])),
            Arc::new(Float64Array::from(vec![value.qy])),
            Arc::new(Float64Array::from(vec![value.qz])),
            Arc::new(Float64Array::from(vec![value.qw])),
        ],
        None,
    )
}

fn optional_orientation_array(value: Option<ImuOrientation>) -> StructArray {
    value.map_or_else(
        || StructArray::new_null(orientation_fields(), 1),
        orientation_array,
    )
}

fn vector_array(value: ImuVector3) -> StructArray {
    StructArray::new(
        vector_fields(),
        vec![
            Arc::new(Float64Array::from(vec![value.x])),
            Arc::new(Float64Array::from(vec![value.y])),
            Arc::new(Float64Array::from(vec![value.z])),
        ],
        None,
    )
}

fn covariance_array(values: &[f64]) -> ListArray {
    let mut builder = ListBuilder::new(Float64Builder::new()).with_field(Arc::new(Field::new(
        "item",
        DataType::Float64,
        true,
    )));
    for value in values {
        builder.values().append_value(*value);
    }
    builder.append(true);
    builder.finish()
}

fn required_column<'a>(batch: &'a RecordBatch, expected: &Field) -> Result<&'a ArrayRef, ImuError> {
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

fn read_orientation(
    array: &ArrayRef,
    name: &str,
    nullable: bool,
) -> Result<Option<ImuOrientation>, ImuError> {
    let values = array
        .as_any()
        .downcast_ref::<StructArray>()
        .ok_or_else(|| ImuError::Invalid(format!("{name} must be struct")))?;
    if values.is_empty() {
        return invalid(format!("{name} is missing row 0"));
    }
    if values.is_null(0) {
        if nullable {
            return Ok(None);
        }
        return invalid(format!("{name} must be non-null"));
    }
    ImuOrientation::new(
        read_required_f64(values.column(0), 0, &format!("{name}.qx"))?,
        read_required_f64(values.column(1), 0, &format!("{name}.qy"))?,
        read_required_f64(values.column(2), 0, &format!("{name}.qz"))?,
        read_required_f64(values.column(3), 0, &format!("{name}.qw"))?,
    )
    .map(Some)
}

fn read_vector(array: &ArrayRef, name: &str) -> Result<ImuVector3, ImuError> {
    let values = array
        .as_any()
        .downcast_ref::<StructArray>()
        .ok_or_else(|| ImuError::Invalid(format!("{name} must be struct")))?;
    if values.is_empty() || values.is_null(0) {
        return invalid(format!("{name} must contain one non-null struct value"));
    }
    Ok(ImuVector3 {
        x: read_required_f64(values.column(0), 0, &format!("{name}.x"))?,
        y: read_required_f64(values.column(1), 0, &format!("{name}.y"))?,
        z: read_required_f64(values.column(2), 0, &format!("{name}.z"))?,
    })
}

fn read_covariance(array: &ArrayRef, name: &str) -> Result<Vec<f64>, ImuError> {
    let list = array
        .as_any()
        .downcast_ref::<ListArray>()
        .ok_or_else(|| ImuError::Invalid(format!("{name} must be list<float64>")))?;
    if list.is_empty() || list.is_null(0) {
        return invalid(format!("{name} must contain one non-null list value"));
    }
    let values = list.value(0);
    let values = values
        .as_any()
        .downcast_ref::<Float64Array>()
        .ok_or_else(|| ImuError::Invalid(format!("{name} values must be float64")))?;
    if values.null_count() != 0 {
        return invalid(format!("{name} values must not contain nulls"));
    }
    Ok((0..values.len()).map(|index| values.value(index)).collect())
}

fn read_optional_f64(array: &ArrayRef, name: &str) -> Result<Option<f64>, ImuError> {
    let values = array
        .as_any()
        .downcast_ref::<Float64Array>()
        .ok_or_else(|| ImuError::Invalid(format!("{name} must be float64")))?;
    if values.is_empty() {
        return invalid(format!("{name} is missing row 0"));
    }
    Ok((!values.is_null(0)).then(|| values.value(0)))
}

fn read_required_f64(array: &ArrayRef, index: usize, name: &str) -> Result<f64, ImuError> {
    let values = array
        .as_any()
        .downcast_ref::<Float64Array>()
        .ok_or_else(|| ImuError::Invalid(format!("{name} must be float64")))?;
    if index >= values.len() || values.is_null(index) {
        return invalid(format!("{name} must be non-null"));
    }
    Ok(values.value(index))
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ImuError {
    Arrow(String),
    Invalid(String),
}

impl std::fmt::Display for ImuError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Arrow(message) => write!(formatter, "arrow error: {message}"),
            Self::Invalid(message) => write!(formatter, "invalid imu message: {message}"),
        }
    }
}

impl std::error::Error for ImuError {}

fn invalid<T>(message: impl Into<String>) -> Result<T, ImuError> {
    Err(ImuError::Invalid(message.into()))
}

#[cfg(test)]
mod tests {
    use std::sync::Arc;

    use arrow_array::builder::{Float64Builder, ListBuilder};
    use arrow_array::{
        Array, ArrayRef, Float32Array, Float64Array, Int32Array, RecordBatch, StructArray,
    };
    use arrow_schema::{DataType, Field, Schema};

    use super::{
        Imu, ImuOrientation, ImuVector3, covariance_type, imu_schema, orientation_fields,
        vector_fields,
    };

    fn covariance(diagonal: [f64; 3]) -> Vec<f64> {
        vec![
            diagonal[0],
            0.0,
            0.0,
            0.0,
            diagonal[1],
            0.0,
            0.0,
            0.0,
            diagonal[2],
        ]
    }

    fn sample() -> Imu {
        Imu::new(
            Some(ImuOrientation::new(0.1, 0.2, 0.3, 2.0).unwrap()),
            ImuVector3::new(1.0, 2.0, 3.0).unwrap(),
            ImuVector3::new(4.0, 5.0, 6.0).unwrap(),
            covariance([0.1, 0.2, 0.3]),
            covariance([0.4, 0.5, 0.6]),
            covariance([0.7, 0.8, 0.9]),
            Some(24.5),
        )
        .unwrap()
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
    fn writer_schema_has_exact_order_types_and_nullability() {
        let batch = sample().to_record_batch().unwrap();
        assert_eq!(batch.num_rows(), 1);
        let expected = imu_schema();
        assert_eq!(batch.schema().fields(), expected.fields());
        assert_eq!(
            batch
                .schema()
                .fields()
                .iter()
                .map(|field| (field.name().as_str(), field.is_nullable()))
                .collect::<Vec<_>>(),
            vec![
                ("orientation", true),
                ("angular_velocity", false),
                ("linear_acceleration", false),
                ("orientation_covariance", false),
                ("angular_velocity_covariance", false),
                ("linear_acceleration_covariance", false),
                ("temperature_celsius", true),
            ]
        );
        assert_eq!(
            batch.schema().field(0).data_type(),
            &DataType::Struct(orientation_fields())
        );
        assert_eq!(
            batch.schema().field(1).data_type(),
            &DataType::Struct(vector_fields())
        );
        assert_eq!(batch.schema().field(3).data_type(), &covariance_type());

        let schema = batch.schema();
        for index in [0usize, 1, 2] {
            let DataType::Struct(children) = schema.field(index).data_type() else {
                panic!("IMU vector fields must be structs")
            };
            assert!(children.iter().all(|field| !field.is_nullable()));
        }
        let DataType::List(item) = schema.field(3).data_type() else {
            panic!("covariance must be list")
        };
        assert!(item.is_nullable());
    }

    #[test]
    fn roundtrip_preserves_non_normalized_orientation() {
        let value = sample();
        let batch = value.to_record_batch().unwrap();
        let decoded = Imu::from_record_batch(&batch).unwrap();
        assert_eq!(decoded, value);
        assert_eq!(decoded.orientation.unwrap().qw, 2.0);
    }

    #[test]
    fn null_orientation_temperature_and_empty_covariances_roundtrip() {
        let value = Imu::new(
            None,
            ImuVector3::new(0.0, 0.0, 0.0).unwrap(),
            ImuVector3::new(0.0, 0.0, 9.81).unwrap(),
            Vec::new(),
            Vec::new(),
            Vec::new(),
            None,
        )
        .unwrap();
        let batch = value.to_record_batch().unwrap();
        assert!(batch.column(0).is_null(0));
        assert!(batch.column(6).is_null(0));
        for index in 3..=5 {
            let list = batch
                .column(index)
                .as_any()
                .downcast_ref::<arrow_array::ListArray>()
                .unwrap();
            assert!(!list.is_null(0));
            assert!(list.value(0).is_empty());
        }
        assert_eq!(Imu::from_record_batch(&batch).unwrap(), value);
    }

    #[test]
    fn validates_orientation_vectors_temperature_and_covariances() {
        assert!(ImuOrientation::new(0.0, 0.0, 0.0, 0.0).is_err());
        assert!(ImuOrientation::new(f64::NAN, 0.0, 0.0, 1.0).is_err());
        assert!(ImuVector3::new(0.0, f64::INFINITY, 0.0).is_err());

        let vector = ImuVector3::new(0.0, 0.0, 0.0).unwrap();
        assert!(Imu::new(None, vector, vector, vec![0.0; 9], vec![], vec![], None).is_err());
        assert!(
            Imu::new(
                Some(ImuOrientation::new(0.0, 0.0, 0.0, 1.0).unwrap()),
                vector,
                vector,
                vec![0.0; 8],
                vec![],
                vec![],
                None,
            )
            .is_err()
        );

        let mut negative_diagonal = vec![0.0; 9];
        negative_diagonal[4] = -0.1;
        assert!(
            Imu::new(
                Some(ImuOrientation::new(0.0, 0.0, 0.0, 1.0).unwrap()),
                vector,
                vector,
                vec![],
                negative_diagonal,
                vec![],
                None,
            )
            .is_err()
        );

        let mut nonfinite = vec![0.0; 9];
        nonfinite[1] = f64::NAN;
        assert!(
            Imu::new(
                Some(ImuOrientation::new(0.0, 0.0, 0.0, 1.0).unwrap()),
                vector,
                vector,
                vec![],
                vec![],
                nonfinite,
                Some(f64::INFINITY),
            )
            .is_err()
        );
    }

    #[test]
    fn reader_resolves_reordered_fields_and_ignores_extras() {
        let batch = sample().to_record_batch().unwrap();
        let mut fields = batch.schema().fields().to_vec();
        let mut columns = batch.columns().to_vec();
        fields.reverse();
        columns.reverse();
        fields.push(Arc::new(Field::new("extra", DataType::Int32, false)));
        columns.push(Arc::new(Int32Array::from(vec![7])));
        let batch = RecordBatch::try_new(Arc::new(Schema::new(fields)), columns).unwrap();
        assert_eq!(Imu::from_record_batch(&batch).unwrap(), sample());
    }

    #[test]
    fn reader_rejects_missing_duplicate_wrong_type_and_required_nulls() {
        let batch = sample().to_record_batch().unwrap();

        let mut fields = batch.schema().fields().to_vec();
        let mut columns = batch.columns().to_vec();
        fields.remove(1);
        columns.remove(1);
        let missing = RecordBatch::try_new(Arc::new(Schema::new(fields)), columns).unwrap();
        assert!(Imu::from_record_batch(&missing).is_err());

        let mut fields = batch.schema().fields().to_vec();
        let mut columns = batch.columns().to_vec();
        fields.push(Arc::clone(&fields[1]));
        columns.push(Arc::clone(&columns[1]));
        let duplicate = RecordBatch::try_new(Arc::new(Schema::new(fields)), columns).unwrap();
        assert!(Imu::from_record_batch(&duplicate).is_err());

        let wrong_type = replace_column(
            &batch,
            "temperature_celsius",
            Field::new("temperature_celsius", DataType::Float32, true),
            Arc::new(Float32Array::from(vec![24.5])),
        );
        assert!(Imu::from_record_batch(&wrong_type).is_err());

        let null_vector = replace_column(
            &batch,
            "angular_velocity",
            Field::new("angular_velocity", DataType::Struct(vector_fields()), true),
            Arc::new(StructArray::new_null(vector_fields(), 1)),
        );
        assert!(Imu::from_record_batch(&null_vector).is_err());
    }

    #[test]
    fn reader_rejects_null_covariance_cell_and_item() {
        let batch = sample().to_record_batch().unwrap();
        let null_cell = {
            let mut builder = ListBuilder::new(Float64Builder::new())
                .with_field(Arc::new(Field::new("item", DataType::Float64, true)));
            builder.append(false);
            replace_column(
                &batch,
                "orientation_covariance",
                Field::new("orientation_covariance", covariance_type(), true),
                Arc::new(builder.finish()),
            )
        };
        assert!(Imu::from_record_batch(&null_cell).is_err());

        let null_item = {
            let mut builder = ListBuilder::new(Float64Builder::new());
            for index in 0..9 {
                if index == 1 {
                    builder.values().append_null();
                } else {
                    builder.values().append_value(0.0);
                }
            }
            builder.append(true);
            let array = builder.finish();
            replace_column(
                &batch,
                "orientation_covariance",
                Field::new(
                    "orientation_covariance",
                    DataType::List(Arc::new(Field::new("item", DataType::Float64, true))),
                    false,
                ),
                Arc::new(array),
            )
        };
        assert!(Imu::from_record_batch(&null_item).is_err());
    }

    #[test]
    fn reader_accepts_nonnullable_nested_field_metadata_but_not_null_values() {
        let batch = sample().to_record_batch().unwrap();
        let mut builder = ListBuilder::new(Float64Builder::new()).with_field(Arc::new(Field::new(
            "item",
            DataType::Float64,
            false,
        )));
        for value in &sample().orientation_covariance {
            builder.values().append_value(*value);
        }
        builder.append(true);
        let nonnullable_items = builder.finish();
        let batch = replace_column(
            &batch,
            "orientation_covariance",
            Field::new(
                "orientation_covariance",
                DataType::List(Arc::new(Field::new("item", DataType::Float64, false))),
                false,
            ),
            Arc::new(nonnullable_items),
        );
        assert_eq!(Imu::from_record_batch(&batch).unwrap(), sample());
    }

    #[test]
    fn reader_requires_exactly_one_row() {
        let schema = Arc::new(imu_schema());
        assert!(Imu::from_record_batch(&RecordBatch::new_empty(schema)).is_err());

        let two_rows = RecordBatch::try_new(
            Arc::new(Schema::new(vec![Field::new(
                "temperature_celsius",
                DataType::Float64,
                true,
            )])),
            vec![Arc::new(Float64Array::from(vec![None, None]))],
        )
        .unwrap();
        assert!(Imu::from_record_batch(&two_rows).is_err());
    }
}
