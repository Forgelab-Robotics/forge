use std::sync::Arc;

use arrow_array::builder::{Float64Builder, ListBuilder, StringBuilder};
use arrow_array::{Array, ArrayRef, Float64Array, ListArray, RecordBatch, StringArray};
use arrow_schema::{DataType, Field, Schema};

#[derive(Clone, Debug, PartialEq)]
pub struct Pose {
    pub x: f64,
    pub y: f64,
    pub z: f64,
    pub qx: f64,
    pub qy: f64,
    pub qz: f64,
    pub qw: f64,
}

#[derive(Clone, Debug, PartialEq)]
pub struct PoseSet {
    pub name: Vec<String>,
    pub x: Vec<f64>,
    pub y: Vec<f64>,
    pub z: Vec<f64>,
    pub qx: Vec<f64>,
    pub qy: Vec<f64>,
    pub qz: Vec<f64>,
    pub qw: Vec<f64>,
}

impl Pose {
    pub fn new(
        x: f64,
        y: f64,
        z: f64,
        qx: f64,
        qy: f64,
        qz: f64,
        qw: f64,
    ) -> Result<Self, PoseError> {
        validate_quaternion(qx, qy, qz, qw)?;
        Ok(Self {
            x,
            y,
            z,
            qx,
            qy,
            qz,
            qw,
        })
    }

    pub fn identity(x: f64, y: f64, z: f64) -> Self {
        Self {
            x,
            y,
            z,
            qx: 0.0,
            qy: 0.0,
            qz: 0.0,
            qw: 1.0,
        }
    }

    pub fn from_xy_yaw(x: f64, y: f64, yaw: f64, z: f64) -> Self {
        let half = yaw * 0.5;
        Self {
            x,
            y,
            z,
            qx: 0.0,
            qy: 0.0,
            qz: half.sin(),
            qw: half.cos(),
        }
    }

    pub fn to_xy_yaw(&self) -> (f64, f64, f64) {
        let yaw = (2.0 * (self.qw * self.qz + self.qx * self.qy))
            .atan2(1.0 - 2.0 * (self.qy * self.qy + self.qz * self.qz));
        (self.x, self.y, yaw)
    }

    pub fn to_record_batch(&self) -> Result<RecordBatch, PoseError> {
        validate_quaternion(self.qx, self.qy, self.qz, self.qw)?;
        let schema = Arc::new(Schema::new(vec![
            Field::new("x", DataType::Float64, false),
            Field::new("y", DataType::Float64, false),
            Field::new("z", DataType::Float64, false),
            Field::new("qx", DataType::Float64, false),
            Field::new("qy", DataType::Float64, false),
            Field::new("qz", DataType::Float64, false),
            Field::new("qw", DataType::Float64, false),
        ]));
        let columns: Vec<ArrayRef> = vec![
            Arc::new(Float64Array::from(vec![self.x])),
            Arc::new(Float64Array::from(vec![self.y])),
            Arc::new(Float64Array::from(vec![self.z])),
            Arc::new(Float64Array::from(vec![self.qx])),
            Arc::new(Float64Array::from(vec![self.qy])),
            Arc::new(Float64Array::from(vec![self.qz])),
            Arc::new(Float64Array::from(vec![self.qw])),
        ];
        RecordBatch::try_new(schema, columns).map_err(|e| PoseError::Arrow(e.to_string()))
    }

    pub fn from_record_batch(batch: &RecordBatch) -> Result<Self, PoseError> {
        if batch.num_rows() == 0 {
            return Err(PoseError::Invalid(
                "RecordBatch must contain one row".to_string(),
            ));
        }
        Self::new(
            read_f64(batch, "x")?,
            read_f64(batch, "y")?,
            read_f64(batch, "z")?,
            read_f64(batch, "qx")?,
            read_f64(batch, "qy")?,
            read_f64(batch, "qz")?,
            read_f64(batch, "qw")?,
        )
    }
}

impl PoseSet {
    pub fn new(
        name: Vec<String>,
        x: Vec<f64>,
        y: Vec<f64>,
        z: Vec<f64>,
        qx: Vec<f64>,
        qy: Vec<f64>,
        qz: Vec<f64>,
        qw: Vec<f64>,
    ) -> Result<Self, PoseError> {
        let value = Self {
            name,
            x,
            y,
            z,
            qx,
            qy,
            qz,
            qw,
        };
        value.validate()?;
        Ok(value)
    }

    pub fn to_record_batch(&self) -> Result<RecordBatch, PoseError> {
        self.validate()?;
        let schema = Arc::new(Schema::new(vec![
            Field::new(
                "name",
                DataType::List(Arc::new(Field::new("item", DataType::Utf8, true))),
                false,
            ),
            Field::new("x", float_list_type(), false),
            Field::new("y", float_list_type(), false),
            Field::new("z", float_list_type(), false),
            Field::new("qx", float_list_type(), false),
            Field::new("qy", float_list_type(), false),
            Field::new("qz", float_list_type(), false),
            Field::new("qw", float_list_type(), false),
        ]));
        let columns: Vec<ArrayRef> = vec![
            Arc::new(string_list_array(&self.name)),
            Arc::new(float_list_array(&self.x)),
            Arc::new(float_list_array(&self.y)),
            Arc::new(float_list_array(&self.z)),
            Arc::new(float_list_array(&self.qx)),
            Arc::new(float_list_array(&self.qy)),
            Arc::new(float_list_array(&self.qz)),
            Arc::new(float_list_array(&self.qw)),
        ];
        RecordBatch::try_new(schema, columns).map_err(|e| PoseError::Arrow(e.to_string()))
    }

    pub fn from_record_batch(batch: &RecordBatch) -> Result<Self, PoseError> {
        if batch.num_rows() == 0 {
            return Err(PoseError::Invalid(
                "RecordBatch must contain one row".to_string(),
            ));
        }
        Self::new(
            read_string_list(batch, "name")?,
            read_float_list(batch, "x")?,
            read_float_list(batch, "y")?,
            read_float_list(batch, "z")?,
            read_float_list(batch, "qx")?,
            read_float_list(batch, "qy")?,
            read_float_list(batch, "qz")?,
            read_float_list(batch, "qw")?,
        )
    }

    fn validate(&self) -> Result<(), PoseError> {
        if self.name.is_empty() {
            return Err(PoseError::Invalid(
                "name must contain at least one pose".to_string(),
            ));
        }
        let mut sorted = self.name.clone();
        sorted.sort();
        sorted.dedup();
        if sorted.len() != self.name.len() {
            return Err(PoseError::Invalid("name items must be unique".to_string()));
        }
        validate_len("x", &self.x, &self.name)?;
        validate_len("y", &self.y, &self.name)?;
        validate_len("z", &self.z, &self.name)?;
        validate_len("qx", &self.qx, &self.name)?;
        validate_len("qy", &self.qy, &self.name)?;
        validate_len("qz", &self.qz, &self.name)?;
        validate_len("qw", &self.qw, &self.name)?;
        for i in 0..self.name.len() {
            validate_quaternion(self.qx[i], self.qy[i], self.qz[i], self.qw[i])?;
        }
        Ok(())
    }
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

fn read_f64(batch: &RecordBatch, name: &str) -> Result<f64, PoseError> {
    let idx = batch
        .schema()
        .index_of(name)
        .map_err(|_| PoseError::Invalid(format!("missing {name} column")))?;
    let array = batch
        .column(idx)
        .as_any()
        .downcast_ref::<Float64Array>()
        .ok_or_else(|| PoseError::Invalid(format!("{name} column must be float64")))?;
    Ok(array.value(0))
}

fn read_string_list(batch: &RecordBatch, name: &str) -> Result<Vec<String>, PoseError> {
    let values = read_list(batch, name)?;
    let array = values
        .as_any()
        .downcast_ref::<StringArray>()
        .ok_or_else(|| PoseError::Invalid(format!("{name} values must be utf8")))?;
    Ok((0..array.len())
        .map(|i| array.value(i).to_string())
        .collect())
}

fn read_float_list(batch: &RecordBatch, name: &str) -> Result<Vec<f64>, PoseError> {
    let values = read_list(batch, name)?;
    let array = values
        .as_any()
        .downcast_ref::<Float64Array>()
        .ok_or_else(|| PoseError::Invalid(format!("{name} values must be float64")))?;
    Ok((0..array.len()).map(|i| array.value(i)).collect())
}

fn read_list(batch: &RecordBatch, name: &str) -> Result<ArrayRef, PoseError> {
    let idx = batch
        .schema()
        .index_of(name)
        .map_err(|_| PoseError::Invalid(format!("missing {name} column")))?;
    let array = batch
        .column(idx)
        .as_any()
        .downcast_ref::<ListArray>()
        .ok_or_else(|| PoseError::Invalid(format!("{name} column must be list")))?;
    if array.is_empty() {
        return Err(PoseError::Invalid(format!("{name} column is empty")));
    }
    Ok(array.value(0))
}

fn validate_len(field: &str, values: &[f64], names: &[String]) -> Result<(), PoseError> {
    if values.len() != names.len() {
        return Err(PoseError::Invalid(format!(
            "{field} must have the same length as name"
        )));
    }
    Ok(())
}

fn validate_quaternion(qx: f64, qy: f64, qz: f64, qw: f64) -> Result<(), PoseError> {
    if qx == 0.0 && qy == 0.0 && qz == 0.0 && qw == 0.0 {
        return Err(PoseError::Invalid(
            "quaternion must not be all zero".to_string(),
        ));
    }
    Ok(())
}

#[derive(Debug)]
pub enum PoseError {
    Arrow(String),
    Invalid(String),
}

impl std::fmt::Display for PoseError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            PoseError::Arrow(msg) => write!(f, "arrow error: {msg}"),
            PoseError::Invalid(msg) => write!(f, "invalid pose message: {msg}"),
        }
    }
}

impl std::error::Error for PoseError {}

#[cfg(test)]
mod tests {
    use super::{Pose, PoseSet};

    #[test]
    fn pose_roundtrip_record_batch() {
        let pose = Pose::new(1.0, 2.0, 3.0, 0.0, 0.0, 0.0, 1.0).unwrap();
        let batch = pose.to_record_batch().unwrap();
        let back = Pose::from_record_batch(&batch).unwrap();
        assert_eq!(back, pose);
    }

    #[test]
    fn pose_xy_yaw_helper() {
        let pose = Pose::from_xy_yaw(1.0, 2.0, std::f64::consts::FRAC_PI_2, 0.0);
        let (x, y, yaw) = pose.to_xy_yaw();
        assert_eq!(x, 1.0);
        assert_eq!(y, 2.0);
        assert!((yaw - std::f64::consts::FRAC_PI_2).abs() < 1e-12);
    }

    #[test]
    fn pose_set_roundtrip_record_batch() {
        let set = PoseSet::new(
            vec!["a".to_string(), "b".to_string()],
            vec![1.0, 2.0],
            vec![2.0, 3.0],
            vec![0.0, 0.0],
            vec![0.0, 0.0],
            vec![0.0, 0.0],
            vec![0.0, 0.0],
            vec![1.0, 1.0],
        )
        .unwrap();
        let batch = set.to_record_batch().unwrap();
        let back = PoseSet::from_record_batch(&batch).unwrap();
        assert_eq!(back, set);
    }

    #[test]
    fn rejects_invalid_quaternion() {
        let pose = Pose::new(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0);
        assert!(pose.is_err());
    }

    #[test]
    fn rejects_invalid_pose_set_lengths() {
        let set = PoseSet::new(
            vec!["a".to_string(), "b".to_string()],
            vec![1.0],
            vec![2.0, 3.0],
            vec![0.0, 0.0],
            vec![0.0, 0.0],
            vec![0.0, 0.0],
            vec![0.0, 0.0],
            vec![1.0, 1.0],
        );
        assert!(set.is_err());
    }
}
