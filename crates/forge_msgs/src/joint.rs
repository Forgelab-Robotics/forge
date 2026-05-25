use std::sync::Arc;

use arrow_array::builder::{Float64Builder, ListBuilder, StringBuilder};
use arrow_array::{Array, ArrayRef, Float64Array, ListArray, RecordBatch, StringArray};
use arrow_schema::{DataType, Field, Schema};

#[derive(Clone, Debug, PartialEq)]
pub struct JointState {
    pub name: Vec<String>,
    pub position: Vec<f64>,
    pub velocity: Vec<f64>,
    pub effort: Vec<f64>,
}

#[derive(Clone, Debug, PartialEq)]
pub struct JointCommand {
    pub name: Vec<String>,
    pub position: Vec<f64>,
    pub velocity: Vec<f64>,
    pub effort: Vec<f64>,
    pub kp: Vec<f64>,
    pub kd: Vec<f64>,
}

impl JointState {
    pub fn new(
        name: Vec<String>,
        position: Vec<f64>,
        velocity: Vec<f64>,
        effort: Vec<f64>,
    ) -> Result<Self, JointError> {
        let value = Self {
            name,
            position,
            velocity,
            effort,
        };
        value.validate_state()?;
        Ok(value)
    }

    pub fn to_record_batch(&self) -> Result<RecordBatch, JointError> {
        self.validate_state()?;
        record_batch(
            vec![
                ("name", Arc::new(string_list_array(&self.name)) as ArrayRef),
                (
                    "position",
                    Arc::new(float_list_array(&self.position)) as ArrayRef,
                ),
                (
                    "velocity",
                    Arc::new(float_list_array(&self.velocity)) as ArrayRef,
                ),
                (
                    "effort",
                    Arc::new(float_list_array(&self.effort)) as ArrayRef,
                ),
            ],
            vec![
                Field::new(
                    "name",
                    DataType::List(Arc::new(Field::new("item", DataType::Utf8, true))),
                    false,
                ),
                Field::new("position", float_list_type(), false),
                Field::new("velocity", float_list_type(), false),
                Field::new("effort", float_list_type(), false),
            ],
        )
    }

    pub fn from_record_batch(batch: &RecordBatch) -> Result<Self, JointError> {
        if batch.num_rows() == 0 {
            return Err(JointError::Invalid(
                "RecordBatch must contain one row".to_string(),
            ));
        }
        let value = Self {
            name: read_string_list(batch, "name")?,
            position: read_float_list(batch, "position")?,
            velocity: read_float_list(batch, "velocity")?,
            effort: read_float_list(batch, "effort")?,
        };
        value.validate_state()?;
        Ok(value)
    }

    fn validate_state(&self) -> Result<(), JointError> {
        validate_names(&self.name)?;
        validate_len("position", &self.position, &self.name)?;
        validate_len("velocity", &self.velocity, &self.name)?;
        validate_len("effort", &self.effort, &self.name)?;
        Ok(())
    }
}

impl JointCommand {
    pub fn new(
        name: Vec<String>,
        position: Vec<f64>,
        velocity: Vec<f64>,
        effort: Vec<f64>,
        kp: Vec<f64>,
        kd: Vec<f64>,
    ) -> Result<Self, JointError> {
        let value = Self {
            name,
            position,
            velocity,
            effort,
            kp,
            kd,
        };
        value.validate_command()?;
        Ok(value)
    }

    pub fn to_record_batch(&self) -> Result<RecordBatch, JointError> {
        self.validate_command()?;
        record_batch(
            vec![
                ("name", Arc::new(string_list_array(&self.name)) as ArrayRef),
                (
                    "position",
                    Arc::new(float_list_array(&self.position)) as ArrayRef,
                ),
                (
                    "velocity",
                    Arc::new(float_list_array(&self.velocity)) as ArrayRef,
                ),
                (
                    "effort",
                    Arc::new(float_list_array(&self.effort)) as ArrayRef,
                ),
                ("kp", Arc::new(float_list_array(&self.kp)) as ArrayRef),
                ("kd", Arc::new(float_list_array(&self.kd)) as ArrayRef),
            ],
            vec![
                Field::new(
                    "name",
                    DataType::List(Arc::new(Field::new("item", DataType::Utf8, true))),
                    false,
                ),
                Field::new("position", float_list_type(), false),
                Field::new("velocity", float_list_type(), false),
                Field::new("effort", float_list_type(), false),
                Field::new("kp", float_list_type(), false),
                Field::new("kd", float_list_type(), false),
            ],
        )
    }

    pub fn from_record_batch(batch: &RecordBatch) -> Result<Self, JointError> {
        if batch.num_rows() == 0 {
            return Err(JointError::Invalid(
                "RecordBatch must contain one row".to_string(),
            ));
        }
        let value = Self {
            name: read_string_list(batch, "name")?,
            position: read_float_list(batch, "position")?,
            velocity: read_float_list(batch, "velocity")?,
            effort: read_float_list(batch, "effort")?,
            kp: read_float_list(batch, "kp")?,
            kd: read_float_list(batch, "kd")?,
        };
        value.validate_command()?;
        Ok(value)
    }

    fn validate_command(&self) -> Result<(), JointError> {
        validate_names(&self.name)?;
        validate_len("position", &self.position, &self.name)?;
        validate_len("velocity", &self.velocity, &self.name)?;
        validate_len("effort", &self.effort, &self.name)?;
        validate_len("kp", &self.kp, &self.name)?;
        validate_len("kd", &self.kd, &self.name)?;
        Ok(())
    }
}

fn record_batch(
    columns: Vec<(&'static str, ArrayRef)>,
    fields: Vec<Field>,
) -> Result<RecordBatch, JointError> {
    let schema = Arc::new(Schema::new(fields));
    let arrays = columns.into_iter().map(|(_, array)| array).collect();
    RecordBatch::try_new(schema, arrays).map_err(|e| JointError::Arrow(e.to_string()))
}

fn float_list_type() -> DataType {
    DataType::List(Arc::new(Field::new("item", DataType::Float64, true)))
}

fn string_list_array(values: &[String]) -> ListArray {
    let mut builder = ListBuilder::new(StringBuilder::new());
    for value in values {
        builder.values().append_value(value);
    }
    builder.append(true);
    builder.finish()
}

fn float_list_array(values: &[f64]) -> ListArray {
    let mut builder = ListBuilder::new(Float64Builder::new());
    for value in values {
        builder.values().append_value(*value);
    }
    builder.append(true);
    builder.finish()
}

fn read_string_list(batch: &RecordBatch, name: &str) -> Result<Vec<String>, JointError> {
    let values = read_list(batch, name)?;
    let array = values
        .as_any()
        .downcast_ref::<StringArray>()
        .ok_or_else(|| JointError::Invalid(format!("{name} values must be utf8")))?;
    Ok((0..array.len())
        .map(|i| array.value(i).to_string())
        .collect())
}

fn read_float_list(batch: &RecordBatch, name: &str) -> Result<Vec<f64>, JointError> {
    let values = read_list(batch, name)?;
    let array = values
        .as_any()
        .downcast_ref::<Float64Array>()
        .ok_or_else(|| JointError::Invalid(format!("{name} values must be float64")))?;
    Ok((0..array.len()).map(|i| array.value(i)).collect())
}

fn read_list(batch: &RecordBatch, name: &str) -> Result<ArrayRef, JointError> {
    let idx = batch
        .schema()
        .index_of(name)
        .map_err(|_| JointError::Invalid(format!("missing {name} column")))?;
    let array = batch
        .column(idx)
        .as_any()
        .downcast_ref::<ListArray>()
        .ok_or_else(|| JointError::Invalid(format!("{name} column must be list")))?;
    if array.is_empty() {
        return Err(JointError::Invalid(format!("{name} column is empty")));
    }
    Ok(array.value(0))
}

fn validate_names(names: &[String]) -> Result<(), JointError> {
    if names.is_empty() {
        return Err(JointError::Invalid(
            "name must contain at least one joint".to_string(),
        ));
    }
    let mut sorted = names.to_vec();
    sorted.sort();
    sorted.dedup();
    if sorted.len() != names.len() {
        return Err(JointError::Invalid("name items must be unique".to_string()));
    }
    Ok(())
}

fn validate_len(field: &str, values: &[f64], names: &[String]) -> Result<(), JointError> {
    if !values.is_empty() && values.len() != names.len() {
        return Err(JointError::Invalid(format!(
            "{field} must be empty or have the same length as name"
        )));
    }
    Ok(())
}

#[derive(Debug)]
pub enum JointError {
    Arrow(String),
    Invalid(String),
}

impl std::fmt::Display for JointError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            JointError::Arrow(msg) => write!(f, "arrow error: {msg}"),
            JointError::Invalid(msg) => write!(f, "invalid joint message: {msg}"),
        }
    }
}

impl std::error::Error for JointError {}

#[cfg(test)]
mod tests {
    use super::{JointCommand, JointState};

    #[test]
    fn joint_state_roundtrip_record_batch() {
        let state = JointState::new(
            vec!["j1".to_string(), "j2".to_string()],
            vec![1.0, 2.0],
            vec![0.1, 0.2],
            vec![],
        )
        .unwrap();
        let batch = state.to_record_batch().unwrap();
        let back = JointState::from_record_batch(&batch).unwrap();
        assert_eq!(back, state);
    }

    #[test]
    fn joint_command_roundtrip_record_batch() {
        let command = JointCommand::new(
            vec!["j1".to_string()],
            vec![1.0],
            vec![0.0],
            vec![0.5],
            vec![20.0],
            vec![1.0],
        )
        .unwrap();
        let batch = command.to_record_batch().unwrap();
        let back = JointCommand::from_record_batch(&batch).unwrap();
        assert_eq!(back, command);
    }

    #[test]
    fn rejects_invalid_lengths() {
        let err = JointState::new(
            vec!["j1".to_string(), "j2".to_string()],
            vec![1.0],
            vec![],
            vec![],
        );
        assert!(err.is_err());
    }
}
