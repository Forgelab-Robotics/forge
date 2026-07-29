use std::collections::HashSet;
use std::sync::Arc;

use arrow_array::builder::{
    ArrayBuilder, Float64Builder, ListBuilder, StringBuilder, StructBuilder,
};
use arrow_array::{
    Array, ArrayRef, Float64Array, Int64Array, ListArray, RecordBatch, StringArray, StructArray,
};
use arrow_schema::{DataType, Field, Fields, Schema};

#[derive(Clone, Debug, PartialEq)]
pub struct JointTrajectoryPoint {
    pub positions: Vec<f64>,
    pub velocities: Vec<f64>,
    pub accelerations: Vec<f64>,
    pub effort: Vec<f64>,
    pub time_from_start_ns: i64,
}

#[derive(Clone, Debug, PartialEq)]
pub struct JointTrajectory {
    pub joint_names: Vec<String>,
    pub points: Vec<JointTrajectoryPoint>,
}

#[derive(Clone, Debug, PartialEq)]
pub struct JointTolerance {
    pub joint_name: String,
    pub position: Option<f64>,
    pub velocity: Option<f64>,
    pub acceleration: Option<f64>,
}

impl JointTrajectoryPoint {
    pub fn new(
        positions: Vec<f64>,
        velocities: Vec<f64>,
        accelerations: Vec<f64>,
        effort: Vec<f64>,
        time_from_start_ns: i64,
    ) -> Result<Self, TrajectoryError> {
        let value = Self {
            positions,
            velocities,
            accelerations,
            effort,
            time_from_start_ns,
        };
        value.validate()?;
        Ok(value)
    }

    pub fn validate(&self) -> Result<(), TrajectoryError> {
        if self.positions.is_empty() {
            return invalid("positions must contain at least one value");
        }
        validate_finite_values("positions", &self.positions)?;
        validate_optional_vector("velocities", &self.velocities, self.positions.len())?;
        validate_optional_vector("accelerations", &self.accelerations, self.positions.len())?;
        validate_optional_vector("effort", &self.effort, self.positions.len())?;
        validate_non_negative_i64("time_from_start_ns", self.time_from_start_ns)
    }

    pub fn to_record_batch(&self) -> Result<RecordBatch, TrajectoryError> {
        self.validate()?;
        make_batch(
            point_schema(),
            vec![
                Arc::new(float_list_array(&self.positions)),
                Arc::new(float_list_array(&self.velocities)),
                Arc::new(float_list_array(&self.accelerations)),
                Arc::new(float_list_array(&self.effort)),
                Arc::new(Int64Array::from(vec![self.time_from_start_ns])),
            ],
        )
    }

    pub fn from_record_batch(batch: &RecordBatch) -> Result<Self, TrajectoryError> {
        validate_batch(batch, &point_schema())?;
        Self::new(
            read_float_list_column(batch, 0, "positions")?,
            read_float_list_column(batch, 1, "velocities")?,
            read_float_list_column(batch, 2, "accelerations")?,
            read_float_list_column(batch, 3, "effort")?,
            read_required_i64(batch.column(4), 0, "time_from_start_ns")?,
        )
    }
}

impl JointTrajectory {
    pub fn new(
        joint_names: Vec<String>,
        points: Vec<JointTrajectoryPoint>,
    ) -> Result<Self, TrajectoryError> {
        let value = Self {
            joint_names,
            points,
        };
        value.validate()?;
        Ok(value)
    }

    pub fn validate(&self) -> Result<(), TrajectoryError> {
        validate_joint_names("joint_names", &self.joint_names, false)?;
        if self.points.is_empty() {
            return invalid("points must contain at least one trajectory point");
        }

        let mut previous_time = None;
        for point in &self.points {
            point.validate()?;
            if point.positions.len() != self.joint_names.len() {
                return invalid("point positions must have the same length as joint_names");
            }
            for (name, values) in [
                ("velocities", &point.velocities),
                ("accelerations", &point.accelerations),
                ("effort", &point.effort),
            ] {
                if !values.is_empty() && values.len() != self.joint_names.len() {
                    return invalid(format!(
                        "point {name} must be empty or have the same length as joint_names"
                    ));
                }
            }
            if previous_time.is_some_and(|time| point.time_from_start_ns <= time) {
                return invalid("time_from_start_ns values must be strictly increasing");
            }
            previous_time = Some(point.time_from_start_ns);
        }
        Ok(())
    }

    pub fn to_record_batch(&self) -> Result<RecordBatch, TrajectoryError> {
        self.validate()?;
        make_batch(
            trajectory_schema(),
            vec![
                Arc::new(string_list_array(&self.joint_names)),
                Arc::new(point_list_array(&self.points)),
            ],
        )
    }

    pub fn from_record_batch(batch: &RecordBatch) -> Result<Self, TrajectoryError> {
        validate_batch(batch, &trajectory_schema())?;
        Self::new(
            read_string_list_column(batch, 0, "joint_names")?,
            read_point_list(batch.column(1), 0, "points")?,
        )
    }
}

impl JointTolerance {
    pub fn new(
        joint_name: impl Into<String>,
        position: Option<f64>,
        velocity: Option<f64>,
        acceleration: Option<f64>,
    ) -> Result<Self, TrajectoryError> {
        let value = Self {
            joint_name: joint_name.into(),
            position,
            velocity,
            acceleration,
        };
        value.validate()?;
        Ok(value)
    }

    pub fn validate(&self) -> Result<(), TrajectoryError> {
        validate_non_empty("joint_name", &self.joint_name)?;
        if self.position.is_none() && self.velocity.is_none() && self.acceleration.is_none() {
            return invalid("at least one tolerance must be specified");
        }
        validate_optional_non_negative_f64("position", self.position)?;
        validate_optional_non_negative_f64("velocity", self.velocity)?;
        validate_optional_non_negative_f64("acceleration", self.acceleration)
    }

    pub fn to_record_batch(&self) -> Result<RecordBatch, TrajectoryError> {
        self.validate()?;
        make_batch(
            tolerance_schema(),
            vec![
                Arc::new(StringArray::from(vec![self.joint_name.as_str()])),
                Arc::new(Float64Array::from(vec![self.position])),
                Arc::new(Float64Array::from(vec![self.velocity])),
                Arc::new(Float64Array::from(vec![self.acceleration])),
            ],
        )
    }

    pub fn from_record_batch(batch: &RecordBatch) -> Result<Self, TrajectoryError> {
        validate_batch(batch, &tolerance_schema())?;
        Self::new(
            read_required_string(batch.column(0), 0, "joint_name")?,
            read_optional_f64(batch.column(1), 0, "position")?,
            read_optional_f64(batch.column(2), 0, "velocity")?,
            read_optional_f64(batch.column(3), 0, "acceleration")?,
        )
    }
}

pub(crate) fn point_fields() -> Fields {
    vec![
        Field::new("positions", float_list_type(), false),
        Field::new("velocities", float_list_type(), false),
        Field::new("accelerations", float_list_type(), false),
        Field::new("effort", float_list_type(), false),
        Field::new("time_from_start_ns", DataType::Int64, false),
    ]
    .into()
}

pub(crate) fn trajectory_fields() -> Fields {
    vec![
        Field::new("joint_names", string_list_type(), false),
        Field::new("points", point_list_type(), false),
    ]
    .into()
}

pub(crate) fn tolerance_fields() -> Fields {
    vec![
        Field::new("joint_name", DataType::Utf8, false),
        Field::new("position", DataType::Float64, true),
        Field::new("velocity", DataType::Float64, true),
        Field::new("acceleration", DataType::Float64, true),
    ]
    .into()
}

fn point_schema() -> Schema {
    Schema::new(point_fields())
}

fn trajectory_schema() -> Schema {
    Schema::new(trajectory_fields())
}

fn tolerance_schema() -> Schema {
    Schema::new(tolerance_fields())
}

pub(crate) fn float_list_type() -> DataType {
    list_type(DataType::Float64)
}

pub(crate) fn string_list_type() -> DataType {
    list_type(DataType::Utf8)
}

pub(crate) fn point_list_type() -> DataType {
    list_type(DataType::Struct(point_fields()))
}

pub(crate) fn tolerance_list_type() -> DataType {
    list_type(DataType::Struct(tolerance_fields()))
}

fn list_type(value_type: DataType) -> DataType {
    DataType::List(Arc::new(Field::new("item", value_type, true)))
}

pub(crate) fn string_list_array(values: &[String]) -> ListArray {
    let mut builder = ListBuilder::new(StringBuilder::new());
    for value in values {
        builder.values().append_value(value);
    }
    builder.append(true);
    builder.finish()
}

pub(crate) fn float_list_array(values: &[f64]) -> ListArray {
    let mut builder = ListBuilder::new(Float64Builder::new());
    for value in values {
        builder.values().append_value(*value);
    }
    builder.append(true);
    builder.finish()
}

pub(crate) fn point_struct_array(value: &JointTrajectoryPoint) -> StructArray {
    StructArray::new(
        point_fields(),
        vec![
            Arc::new(float_list_array(&value.positions)),
            Arc::new(float_list_array(&value.velocities)),
            Arc::new(float_list_array(&value.accelerations)),
            Arc::new(float_list_array(&value.effort)),
            Arc::new(Int64Array::from(vec![value.time_from_start_ns])),
        ],
        None,
    )
}

pub(crate) fn trajectory_struct_array(value: &JointTrajectory) -> StructArray {
    StructArray::new(
        trajectory_fields(),
        vec![
            Arc::new(string_list_array(&value.joint_names)),
            Arc::new(point_list_array(&value.points)),
        ],
        None,
    )
}

fn point_struct_builder() -> StructBuilder {
    StructBuilder::new(
        point_fields(),
        vec![
            Box::new(ListBuilder::new(Float64Builder::new())) as Box<dyn ArrayBuilder>,
            Box::new(ListBuilder::new(Float64Builder::new())),
            Box::new(ListBuilder::new(Float64Builder::new())),
            Box::new(ListBuilder::new(Float64Builder::new())),
            Box::new(arrow_array::builder::Int64Builder::new()),
        ],
    )
}

fn append_float_list(builder: &mut StructBuilder, index: usize, values: &[f64]) {
    let builder = builder
        .field_builder::<ListBuilder<Float64Builder>>(index)
        .expect("point builder field type");
    for value in values {
        builder.values().append_value(*value);
    }
    builder.append(true);
}

fn append_point(builder: &mut StructBuilder, value: &JointTrajectoryPoint) {
    append_float_list(builder, 0, &value.positions);
    append_float_list(builder, 1, &value.velocities);
    append_float_list(builder, 2, &value.accelerations);
    append_float_list(builder, 3, &value.effort);
    builder
        .field_builder::<arrow_array::builder::Int64Builder>(4)
        .expect("point builder field type")
        .append_value(value.time_from_start_ns);
    builder.append(true);
}

pub(crate) fn point_list_array(values: &[JointTrajectoryPoint]) -> ListArray {
    let item_field = Arc::new(Field::new("item", DataType::Struct(point_fields()), true));
    let mut builder = ListBuilder::new(point_struct_builder()).with_field(item_field);
    for value in values {
        append_point(builder.values(), value);
    }
    builder.append(true);
    builder.finish()
}

fn tolerance_struct_builder() -> StructBuilder {
    StructBuilder::new(
        tolerance_fields(),
        vec![
            Box::new(StringBuilder::new()) as Box<dyn ArrayBuilder>,
            Box::new(Float64Builder::new()),
            Box::new(Float64Builder::new()),
            Box::new(Float64Builder::new()),
        ],
    )
}

fn append_tolerance(builder: &mut StructBuilder, value: &JointTolerance) {
    builder
        .field_builder::<StringBuilder>(0)
        .expect("tolerance builder field type")
        .append_value(&value.joint_name);
    builder
        .field_builder::<Float64Builder>(1)
        .expect("tolerance builder field type")
        .append_option(value.position);
    builder
        .field_builder::<Float64Builder>(2)
        .expect("tolerance builder field type")
        .append_option(value.velocity);
    builder
        .field_builder::<Float64Builder>(3)
        .expect("tolerance builder field type")
        .append_option(value.acceleration);
    builder.append(true);
}

pub(crate) fn tolerance_list_array(values: &[JointTolerance]) -> ListArray {
    let item_field = Arc::new(Field::new(
        "item",
        DataType::Struct(tolerance_fields()),
        true,
    ));
    let mut builder = ListBuilder::new(tolerance_struct_builder()).with_field(item_field);
    for value in values {
        append_tolerance(builder.values(), value);
    }
    builder.append(true);
    builder.finish()
}

pub(crate) fn read_point_struct(
    array: &StructArray,
    index: usize,
    name: &str,
) -> Result<JointTrajectoryPoint, TrajectoryError> {
    ensure_struct_value(array, index, name)?;
    JointTrajectoryPoint::new(
        read_float_list(array.column(0), index, &format!("{name}.positions"))?,
        read_float_list(array.column(1), index, &format!("{name}.velocities"))?,
        read_float_list(array.column(2), index, &format!("{name}.accelerations"))?,
        read_float_list(array.column(3), index, &format!("{name}.effort"))?,
        read_required_i64(
            array.column(4),
            index,
            &format!("{name}.time_from_start_ns"),
        )?,
    )
}

pub(crate) fn read_trajectory_struct(
    array: &StructArray,
    index: usize,
    name: &str,
) -> Result<JointTrajectory, TrajectoryError> {
    ensure_struct_value(array, index, name)?;
    JointTrajectory::new(
        read_string_list(array.column(0), index, &format!("{name}.joint_names"))?,
        read_point_list(array.column(1), index, &format!("{name}.points"))?,
    )
}

fn read_tolerance_struct(
    array: &StructArray,
    index: usize,
    name: &str,
) -> Result<JointTolerance, TrajectoryError> {
    ensure_struct_value(array, index, name)?;
    JointTolerance::new(
        read_required_string(array.column(0), index, &format!("{name}.joint_name"))?,
        read_optional_f64(array.column(1), index, &format!("{name}.position"))?,
        read_optional_f64(array.column(2), index, &format!("{name}.velocity"))?,
        read_optional_f64(array.column(3), index, &format!("{name}.acceleration"))?,
    )
}

pub(crate) fn read_tolerance_list(
    array: &ArrayRef,
    index: usize,
    name: &str,
) -> Result<Vec<JointTolerance>, TrajectoryError> {
    let values = read_list_values(array, index, name)?;
    let structs = values
        .as_any()
        .downcast_ref::<StructArray>()
        .ok_or_else(|| TrajectoryError::Invalid(format!("{name} values must be struct")))?;
    (0..structs.len())
        .map(|item| read_tolerance_struct(structs, item, &format!("{name}[{item}]")))
        .collect()
}

fn read_point_list(
    array: &ArrayRef,
    index: usize,
    name: &str,
) -> Result<Vec<JointTrajectoryPoint>, TrajectoryError> {
    let values = read_list_values(array, index, name)?;
    let structs = values
        .as_any()
        .downcast_ref::<StructArray>()
        .ok_or_else(|| TrajectoryError::Invalid(format!("{name} values must be struct")))?;
    (0..structs.len())
        .map(|item| read_point_struct(structs, item, &format!("{name}[{item}]")))
        .collect()
}

pub(crate) fn read_string_list(
    array: &ArrayRef,
    index: usize,
    name: &str,
) -> Result<Vec<String>, TrajectoryError> {
    let values = read_list_values(array, index, name)?;
    let strings = values
        .as_any()
        .downcast_ref::<StringArray>()
        .ok_or_else(|| TrajectoryError::Invalid(format!("{name} values must be utf8")))?;
    if strings.null_count() != 0 {
        return invalid(format!("{name} values must not contain nulls"));
    }
    Ok((0..strings.len())
        .map(|item| strings.value(item).to_string())
        .collect())
}

pub(crate) fn read_float_list(
    array: &ArrayRef,
    index: usize,
    name: &str,
) -> Result<Vec<f64>, TrajectoryError> {
    let values = read_list_values(array, index, name)?;
    let floats = values
        .as_any()
        .downcast_ref::<Float64Array>()
        .ok_or_else(|| TrajectoryError::Invalid(format!("{name} values must be float64")))?;
    if floats.null_count() != 0 {
        return invalid(format!("{name} values must not contain nulls"));
    }
    Ok((0..floats.len()).map(|item| floats.value(item)).collect())
}

fn read_list_values(
    array: &ArrayRef,
    index: usize,
    name: &str,
) -> Result<ArrayRef, TrajectoryError> {
    let list = array
        .as_any()
        .downcast_ref::<ListArray>()
        .ok_or_else(|| TrajectoryError::Invalid(format!("{name} must be list")))?;
    if index >= list.len() || list.is_null(index) {
        return invalid(format!("{name} must be non-null"));
    }
    Ok(list.value(index))
}

fn read_float_list_column(
    batch: &RecordBatch,
    index: usize,
    name: &str,
) -> Result<Vec<f64>, TrajectoryError> {
    read_float_list(batch.column(index), 0, name)
}

fn read_string_list_column(
    batch: &RecordBatch,
    index: usize,
    name: &str,
) -> Result<Vec<String>, TrajectoryError> {
    read_string_list(batch.column(index), 0, name)
}

pub(crate) fn read_required_string(
    array: &ArrayRef,
    index: usize,
    name: &str,
) -> Result<String, TrajectoryError> {
    let strings = array
        .as_any()
        .downcast_ref::<StringArray>()
        .ok_or_else(|| TrajectoryError::Invalid(format!("{name} must be utf8")))?;
    if index >= strings.len() || strings.is_null(index) {
        return invalid(format!("{name} must be non-null"));
    }
    Ok(strings.value(index).to_string())
}

pub(crate) fn read_required_i64(
    array: &ArrayRef,
    index: usize,
    name: &str,
) -> Result<i64, TrajectoryError> {
    let values = array
        .as_any()
        .downcast_ref::<Int64Array>()
        .ok_or_else(|| TrajectoryError::Invalid(format!("{name} must be int64")))?;
    if index >= values.len() || values.is_null(index) {
        return invalid(format!("{name} must be non-null"));
    }
    Ok(values.value(index))
}

pub(crate) fn read_optional_f64(
    array: &ArrayRef,
    index: usize,
    name: &str,
) -> Result<Option<f64>, TrajectoryError> {
    let values = array
        .as_any()
        .downcast_ref::<Float64Array>()
        .ok_or_else(|| TrajectoryError::Invalid(format!("{name} must be float64")))?;
    if index >= values.len() {
        return invalid(format!("{name} is missing row {index}"));
    }
    Ok((!values.is_null(index)).then(|| values.value(index)))
}

fn ensure_struct_value(
    array: &StructArray,
    index: usize,
    name: &str,
) -> Result<(), TrajectoryError> {
    if index >= array.len() || array.is_null(index) {
        return invalid(format!("{name} must be non-null"));
    }
    Ok(())
}

pub(crate) fn validate_joint_names(
    name: &str,
    values: &[String],
    empty_allowed: bool,
) -> Result<(), TrajectoryError> {
    if !empty_allowed && values.is_empty() {
        return invalid(format!("{name} must contain at least one joint name"));
    }
    if values.iter().any(|value| value.is_empty()) {
        return invalid(format!("{name} must contain only non-empty names"));
    }
    let unique = values.iter().collect::<HashSet<_>>();
    if unique.len() != values.len() {
        return invalid(format!("{name} items must be unique"));
    }
    Ok(())
}

pub(crate) fn validate_non_empty(name: &str, value: &str) -> Result<(), TrajectoryError> {
    if value.is_empty() {
        return invalid(format!("{name} must be non-empty"));
    }
    Ok(())
}

pub(crate) fn validate_non_negative_i64(name: &str, value: i64) -> Result<(), TrajectoryError> {
    if value < 0 {
        return invalid(format!("{name} must be non-negative"));
    }
    Ok(())
}

pub(crate) fn validate_optional_non_negative_i64(
    name: &str,
    value: Option<i64>,
) -> Result<(), TrajectoryError> {
    if value.is_some_and(|value| value < 0) {
        return invalid(format!("{name} must be non-negative when specified"));
    }
    Ok(())
}

pub(crate) fn validate_optional_non_negative_f64(
    name: &str,
    value: Option<f64>,
) -> Result<(), TrajectoryError> {
    if value.is_some_and(|value| !value.is_finite() || value < 0.0) {
        return invalid(format!(
            "{name} must be finite and non-negative when specified"
        ));
    }
    Ok(())
}

fn validate_finite_values(name: &str, values: &[f64]) -> Result<(), TrajectoryError> {
    if values.iter().any(|value| !value.is_finite()) {
        return invalid(format!("{name} values must be finite"));
    }
    Ok(())
}

fn validate_optional_vector(
    name: &str,
    values: &[f64],
    positions_len: usize,
) -> Result<(), TrajectoryError> {
    if !values.is_empty() && values.len() != positions_len {
        return invalid(format!(
            "{name} must be empty or have the same length as positions"
        ));
    }
    validate_finite_values(name, values)
}

pub(crate) fn validate_batch(
    batch: &RecordBatch,
    expected: &Schema,
) -> Result<(), TrajectoryError> {
    if batch.num_rows() != 1 {
        return invalid("RecordBatch must contain exactly one row");
    }
    if batch.schema().as_ref() != expected {
        return invalid("RecordBatch schema does not match the message schema");
    }
    Ok(())
}

fn make_batch(schema: Schema, columns: Vec<ArrayRef>) -> Result<RecordBatch, TrajectoryError> {
    RecordBatch::try_new(Arc::new(schema), columns)
        .map_err(|error| TrajectoryError::Arrow(error.to_string()))
}

fn invalid<T>(message: impl Into<String>) -> Result<T, TrajectoryError> {
    Err(TrajectoryError::Invalid(message.into()))
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum TrajectoryError {
    Arrow(String),
    Invalid(String),
}

impl std::fmt::Display for TrajectoryError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Arrow(message) => write!(formatter, "arrow error: {message}"),
            Self::Invalid(message) => write!(formatter, "invalid trajectory message: {message}"),
        }
    }
}

impl std::error::Error for TrajectoryError {}

#[cfg(test)]
mod tests {
    use std::sync::Arc;

    use arrow_array::{Array, ArrayRef, Float64Array, RecordBatch};
    use arrow_schema::{DataType, Field, Schema};

    use super::{JointTolerance, JointTrajectory, JointTrajectoryPoint};

    fn point(time_from_start_ns: i64) -> JointTrajectoryPoint {
        JointTrajectoryPoint::new(
            vec![1.0, 2.0],
            vec![0.1, 0.2],
            vec![],
            vec![],
            time_from_start_ns,
        )
        .unwrap()
    }

    #[test]
    fn all_trajectory_messages_roundtrip() {
        let trajectory =
            JointTrajectory::new(vec!["j1".into(), "j2".into()], vec![point(0), point(10)])
                .unwrap();
        let tolerance = JointTolerance::new("j1", Some(0.1), None, Some(0.0)).unwrap();

        let point_value = point(5);
        assert_eq!(
            JointTrajectoryPoint::from_record_batch(&point_value.to_record_batch().unwrap())
                .unwrap(),
            point_value
        );
        assert_eq!(
            JointTrajectory::from_record_batch(&trajectory.to_record_batch().unwrap()).unwrap(),
            trajectory
        );
        assert_eq!(
            JointTolerance::from_record_batch(&tolerance.to_record_batch().unwrap()).unwrap(),
            tolerance
        );
    }

    #[test]
    fn trajectory_schema_has_contract_order_types_and_nullability() {
        let batch = JointTrajectory::new(vec!["j1".into(), "j2".into()], vec![point(0)])
            .unwrap()
            .to_record_batch()
            .unwrap();
        let fields = batch.schema().fields().clone();
        assert_eq!(fields[0].name(), "joint_names");
        assert!(!fields[0].is_nullable());
        assert_eq!(fields[1].name(), "points");
        assert!(!fields[1].is_nullable());
        let DataType::List(point_item) = fields[1].data_type() else {
            panic!("points must be a list")
        };
        let DataType::Struct(point_fields) = point_item.data_type() else {
            panic!("points items must be structs")
        };
        assert_eq!(
            point_fields
                .iter()
                .map(|field| field.name())
                .collect::<Vec<_>>(),
            vec![
                "positions",
                "velocities",
                "accelerations",
                "effort",
                "time_from_start_ns"
            ]
        );
        assert!(point_fields.iter().all(|field| !field.is_nullable()));
    }

    #[test]
    fn tolerance_preserves_null_and_zero_distinction() {
        let tolerance = JointTolerance::new("j1", Some(0.0), None, Some(0.2)).unwrap();
        let batch = tolerance.to_record_batch().unwrap();
        assert!(!batch.column(1).is_null(0));
        assert!(batch.column(2).is_null(0));
        assert_eq!(
            JointTolerance::from_record_batch(&batch).unwrap(),
            tolerance
        );
    }

    #[test]
    fn rejects_invalid_points_and_trajectory_order() {
        assert!(JointTrajectoryPoint::new(vec![], vec![], vec![], vec![], 0).is_err());
        assert!(JointTrajectoryPoint::new(vec![f64::NAN], vec![], vec![], vec![], 0).is_err());
        assert!(JointTrajectoryPoint::new(vec![1.0], vec![0.0, 1.0], vec![], vec![], 0).is_err());
        assert!(JointTrajectoryPoint::new(vec![1.0], vec![], vec![], vec![], -1).is_err());
        assert!(JointTrajectory::new(vec!["j1".into(), "j1".into()], vec![point(0)]).is_err());
        assert!(
            JointTrajectory::new(vec!["j1".into(), "j2".into()], vec![point(10), point(10)])
                .is_err()
        );
    }

    #[test]
    fn rejects_invalid_tolerances() {
        assert!(JointTolerance::new("", Some(0.1), None, None).is_err());
        assert!(JointTolerance::new("j1", None, None, None).is_err());
        assert!(JointTolerance::new("j1", Some(-0.1), None, None).is_err());
        assert!(JointTolerance::new("j1", Some(f64::NAN), None, None).is_err());
    }

    #[test]
    fn from_record_batch_requires_exactly_one_row_and_exact_schema() {
        let empty = RecordBatch::new_empty(Arc::new(Schema::new(vec![Field::new(
            "positions",
            DataType::List(Arc::new(Field::new("item", DataType::Float64, true))),
            false,
        )])));
        assert!(JointTrajectoryPoint::from_record_batch(&empty).is_err());

        let schema = Arc::new(Schema::new(vec![
            Field::new(
                "positions",
                DataType::List(Arc::new(Field::new("item", DataType::Float64, true))),
                true,
            ),
            Field::new("velocities", super::float_list_type(), false),
            Field::new("accelerations", super::float_list_type(), false),
            Field::new("effort", super::float_list_type(), false),
            Field::new("time_from_start_ns", DataType::Int64, false),
        ]));
        let columns: Vec<ArrayRef> = vec![
            Arc::new(super::float_list_array(&[1.0])),
            Arc::new(super::float_list_array(&[])),
            Arc::new(super::float_list_array(&[])),
            Arc::new(super::float_list_array(&[])),
            Arc::new(arrow_array::Int64Array::from(vec![0])),
        ];
        let wrong_nullability = RecordBatch::try_new(schema, columns).unwrap();
        assert!(JointTrajectoryPoint::from_record_batch(&wrong_nullability).is_err());

        let two_rows = RecordBatch::try_new(
            Arc::new(Schema::new(vec![Field::new(
                "value",
                DataType::Float64,
                false,
            )])),
            vec![Arc::new(Float64Array::from(vec![1.0, 2.0]))],
        )
        .unwrap();
        assert!(JointTrajectoryPoint::from_record_batch(&two_rows).is_err());
    }
}
