use std::sync::Arc;

use arrow_array::{Array, ArrayRef, Float64Array, RecordBatch};
use arrow_schema::{DataType, Field, Schema};

/// Planar body-frame locomotion velocity command.
///
/// `vx` is forward-positive linear velocity in m/s, `vy` is left-positive
/// lateral velocity in m/s, and `wz` is counter-clockwise-positive angular
/// velocity around the body Z axis in rad/s.
#[derive(Clone, Debug, PartialEq)]
pub struct LocomotionCommand {
    pub vx: f64,
    pub vy: f64,
    pub wz: f64,
}

impl LocomotionCommand {
    pub fn new(vx: f64, vy: f64, wz: f64) -> Result<Self, LocomotionError> {
        validate_finite("vx", vx)?;
        validate_finite("vy", vy)?;
        validate_finite("wz", wz)?;
        Ok(Self { vx, vy, wz })
    }

    pub fn to_record_batch(&self) -> Result<RecordBatch, LocomotionError> {
        validate_finite("vx", self.vx)?;
        validate_finite("vy", self.vy)?;
        validate_finite("wz", self.wz)?;
        let schema = Arc::new(Schema::new(vec![
            Field::new("vx", DataType::Float64, false),
            Field::new("vy", DataType::Float64, false),
            Field::new("wz", DataType::Float64, false),
        ]));
        let columns: Vec<ArrayRef> = vec![
            Arc::new(Float64Array::from(vec![self.vx])),
            Arc::new(Float64Array::from(vec![self.vy])),
            Arc::new(Float64Array::from(vec![self.wz])),
        ];
        RecordBatch::try_new(schema, columns).map_err(|e| LocomotionError::Arrow(e.to_string()))
    }

    pub fn from_record_batch(batch: &RecordBatch) -> Result<Self, LocomotionError> {
        if batch.num_rows() == 0 {
            return Err(LocomotionError::Invalid(
                "RecordBatch must contain one row".to_string(),
            ));
        }
        Self::new(
            read_f64(batch, "vx")?,
            read_f64(batch, "vy")?,
            read_f64(batch, "wz")?,
        )
    }
}

fn read_f64(batch: &RecordBatch, name: &str) -> Result<f64, LocomotionError> {
    let idx = batch
        .schema()
        .index_of(name)
        .map_err(|_| LocomotionError::Invalid(format!("missing {name} column")))?;
    let array = batch
        .column(idx)
        .as_any()
        .downcast_ref::<Float64Array>()
        .ok_or_else(|| LocomotionError::Invalid(format!("{name} column must be float64")))?;
    if array.is_empty() {
        return Err(LocomotionError::Invalid(format!("{name} column is empty")));
    }
    if array.is_null(0) {
        return Err(LocomotionError::Invalid(format!("{name} must not be null")));
    }
    Ok(array.value(0))
}

fn validate_finite(name: &str, value: f64) -> Result<(), LocomotionError> {
    if value.is_finite() {
        return Ok(());
    }
    Err(LocomotionError::Invalid(format!("{name} must be finite")))
}

#[derive(Debug)]
pub enum LocomotionError {
    Arrow(String),
    Invalid(String),
}

impl std::fmt::Display for LocomotionError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            LocomotionError::Arrow(msg) => write!(f, "arrow error: {msg}"),
            LocomotionError::Invalid(msg) => {
                write!(f, "invalid locomotion command: {msg}")
            }
        }
    }
}

impl std::error::Error for LocomotionError {}

#[cfg(test)]
mod tests {
    use std::sync::Arc;

    use arrow_array::{ArrayRef, Float64Array, RecordBatch};
    use arrow_schema::{DataType, Field, Schema};

    use super::LocomotionCommand;

    #[test]
    fn locomotion_command_roundtrip_record_batch() {
        let command = LocomotionCommand::new(0.5, 0.1, 0.2).unwrap();
        let batch = command.to_record_batch().unwrap();
        let back = LocomotionCommand::from_record_batch(&batch).unwrap();
        assert_eq!(back, command);
    }

    #[test]
    fn rejects_non_finite_values() {
        assert!(LocomotionCommand::new(f64::NAN, 0.0, 0.0).is_err());
        assert!(LocomotionCommand::new(0.0, f64::INFINITY, 0.0).is_err());
        assert!(LocomotionCommand::new(0.0, 0.0, f64::NEG_INFINITY).is_err());
    }

    #[test]
    fn rejects_null_arrow_values() {
        let schema = Arc::new(Schema::new(vec![
            Field::new("vx", DataType::Float64, true),
            Field::new("vy", DataType::Float64, false),
            Field::new("wz", DataType::Float64, false),
        ]));
        let columns: Vec<ArrayRef> = vec![
            Arc::new(Float64Array::from(vec![None])),
            Arc::new(Float64Array::from(vec![Some(0.0)])),
            Arc::new(Float64Array::from(vec![Some(0.0)])),
        ];
        let batch = RecordBatch::try_new(schema, columns).unwrap();

        assert!(LocomotionCommand::from_record_batch(&batch).is_err());
    }
}
