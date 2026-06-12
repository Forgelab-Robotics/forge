use std::sync::Arc;

use arrow_array::{ArrayRef, LargeBinaryArray, RecordBatch, StringArray, UInt32Array};
use arrow_schema::{DataType, Field, Schema};
use bytes::Bytes;

use crate::column::{
    bool_list, f32_list, i32_list, list_type, read_binary, read_bool_list, read_f32_list,
    read_i32_list, read_string, read_u32, read_u32_list, u32_list,
};

use super::{PerceptionError, validate_finite, validate_len, validate_non_negative};

#[derive(Clone, Debug, PartialEq)]
pub struct Keypoint2DSet {
    pub keypoint_id: Vec<u32>,
    pub x: Vec<f32>,
    pub y: Vec<f32>,
    pub size: Vec<f32>,
    pub angle: Vec<f32>,
    pub response: Vec<f32>,
    pub octave: Vec<i32>,
    pub descriptor_type: String,
    pub descriptor_size: u32,
    pub descriptor_data: Bytes,
}

#[derive(Clone, Debug, PartialEq)]
pub struct KeypointMatchSet {
    pub query_source: String,
    pub train_source: String,
    pub query_id: Vec<u32>,
    pub train_id: Vec<u32>,
    pub distance: Vec<f32>,
    pub inlier: Vec<bool>,
}

impl Keypoint2DSet {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        keypoint_id: Vec<u32>,
        x: Vec<f32>,
        y: Vec<f32>,
        size: Vec<f32>,
        angle: Vec<f32>,
        response: Vec<f32>,
        octave: Vec<i32>,
        descriptor_type: impl Into<String>,
        descriptor_size: u32,
        descriptor_data: Bytes,
    ) -> Result<Self, PerceptionError> {
        let value = Self {
            keypoint_id,
            x,
            y,
            size,
            angle,
            response,
            octave,
            descriptor_type: descriptor_type.into(),
            descriptor_size,
            descriptor_data,
        };
        value.validate()?;
        Ok(value)
    }

    pub fn to_record_batch(&self) -> Result<RecordBatch, PerceptionError> {
        self.validate()?;
        let schema = Arc::new(Schema::new(vec![
            Field::new("keypoint_id", list_type(DataType::UInt32), false),
            Field::new("x", list_type(DataType::Float32), false),
            Field::new("y", list_type(DataType::Float32), false),
            Field::new("size", list_type(DataType::Float32), false),
            Field::new("angle", list_type(DataType::Float32), false),
            Field::new("response", list_type(DataType::Float32), false),
            Field::new("octave", list_type(DataType::Int32), false),
            Field::new("descriptor_type", DataType::Utf8, false),
            Field::new("descriptor_size", DataType::UInt32, false),
            Field::new("descriptor_data", DataType::LargeBinary, false),
        ]));
        let columns: Vec<ArrayRef> = vec![
            Arc::new(u32_list(&self.keypoint_id)),
            Arc::new(f32_list(&self.x)),
            Arc::new(f32_list(&self.y)),
            Arc::new(f32_list(&self.size)),
            Arc::new(f32_list(&self.angle)),
            Arc::new(f32_list(&self.response)),
            Arc::new(i32_list(&self.octave)),
            Arc::new(StringArray::from(vec![self.descriptor_type.as_str()])),
            Arc::new(UInt32Array::from(vec![self.descriptor_size])),
            Arc::new(LargeBinaryArray::from_iter_values(std::iter::once(
                &self.descriptor_data,
            ))),
        ];
        RecordBatch::try_new(schema, columns)
            .map_err(|error| PerceptionError::Arrow(error.to_string()))
    }

    pub fn from_record_batch(batch: &RecordBatch) -> Result<Self, PerceptionError> {
        require_row(batch)?;
        Self::new(
            read_u32_list(batch, "keypoint_id").map_err(PerceptionError::Invalid)?,
            read_f32_list(batch, "x").map_err(PerceptionError::Invalid)?,
            read_f32_list(batch, "y").map_err(PerceptionError::Invalid)?,
            read_f32_list(batch, "size").map_err(PerceptionError::Invalid)?,
            read_f32_list(batch, "angle").map_err(PerceptionError::Invalid)?,
            read_f32_list(batch, "response").map_err(PerceptionError::Invalid)?,
            read_i32_list(batch, "octave").map_err(PerceptionError::Invalid)?,
            read_string(batch, "descriptor_type").map_err(PerceptionError::Invalid)?,
            read_u32(batch, "descriptor_size").map_err(PerceptionError::Invalid)?,
            read_binary(batch, "descriptor_data").map_err(PerceptionError::Invalid)?,
        )
    }

    fn validate(&self) -> Result<(), PerceptionError> {
        let mut ids = self.keypoint_id.clone();
        ids.sort();
        ids.dedup();
        if ids.len() != self.keypoint_id.len() {
            return Err(PerceptionError::Invalid(
                "keypoint_id items must be unique".to_string(),
            ));
        }
        let count = self.keypoint_id.len();
        for (name, actual) in [
            ("x", self.x.len()),
            ("y", self.y.len()),
            ("size", self.size.len()),
            ("angle", self.angle.len()),
            ("response", self.response.len()),
            ("octave", self.octave.len()),
        ] {
            validate_len(name, actual, count)?;
        }
        validate_non_negative("size", &self.size)?;
        for (name, values) in [
            ("x", self.x.as_slice()),
            ("y", self.y.as_slice()),
            ("angle", self.angle.as_slice()),
            ("response", self.response.as_slice()),
        ] {
            validate_finite(name, values)?;
        }
        let scalar_size = match self.descriptor_type.as_str() {
            "none" => {
                if self.descriptor_size != 0 || !self.descriptor_data.is_empty() {
                    return Err(PerceptionError::Invalid(
                        "none descriptors require size 0 and empty data".to_string(),
                    ));
                }
                return Ok(());
            }
            "uint8" => 1,
            "float32" => 4,
            _ => {
                return Err(PerceptionError::Invalid(
                    "descriptor_type must be none, uint8, or float32".to_string(),
                ));
            }
        };
        let expected = count
            .checked_mul(self.descriptor_size as usize)
            .and_then(|value| value.checked_mul(scalar_size))
            .ok_or_else(|| {
                PerceptionError::Invalid("descriptor dimensions overflow usize".to_string())
            })?;
        if self.descriptor_data.len() != expected {
            return Err(PerceptionError::Invalid(
                "descriptor_data has an invalid length".to_string(),
            ));
        }
        Ok(())
    }
}

impl KeypointMatchSet {
    pub fn new(
        query_source: impl Into<String>,
        train_source: impl Into<String>,
        query_id: Vec<u32>,
        train_id: Vec<u32>,
        distance: Vec<f32>,
        inlier: Vec<bool>,
    ) -> Result<Self, PerceptionError> {
        let value = Self {
            query_source: query_source.into(),
            train_source: train_source.into(),
            query_id,
            train_id,
            distance,
            inlier,
        };
        value.validate()?;
        Ok(value)
    }

    pub fn to_record_batch(&self) -> Result<RecordBatch, PerceptionError> {
        self.validate()?;
        let schema = Arc::new(Schema::new(vec![
            Field::new("query_source", DataType::Utf8, false),
            Field::new("train_source", DataType::Utf8, false),
            Field::new("query_id", list_type(DataType::UInt32), false),
            Field::new("train_id", list_type(DataType::UInt32), false),
            Field::new("distance", list_type(DataType::Float32), false),
            Field::new("inlier", list_type(DataType::Boolean), false),
        ]));
        let columns: Vec<ArrayRef> = vec![
            Arc::new(StringArray::from(vec![self.query_source.as_str()])),
            Arc::new(StringArray::from(vec![self.train_source.as_str()])),
            Arc::new(u32_list(&self.query_id)),
            Arc::new(u32_list(&self.train_id)),
            Arc::new(f32_list(&self.distance)),
            Arc::new(bool_list(&self.inlier)),
        ];
        RecordBatch::try_new(schema, columns)
            .map_err(|error| PerceptionError::Arrow(error.to_string()))
    }

    pub fn from_record_batch(batch: &RecordBatch) -> Result<Self, PerceptionError> {
        require_row(batch)?;
        Self::new(
            read_string(batch, "query_source").map_err(PerceptionError::Invalid)?,
            read_string(batch, "train_source").map_err(PerceptionError::Invalid)?,
            read_u32_list(batch, "query_id").map_err(PerceptionError::Invalid)?,
            read_u32_list(batch, "train_id").map_err(PerceptionError::Invalid)?,
            read_f32_list(batch, "distance").map_err(PerceptionError::Invalid)?,
            read_bool_list(batch, "inlier").map_err(PerceptionError::Invalid)?,
        )
    }

    fn validate(&self) -> Result<(), PerceptionError> {
        if self.query_source.is_empty() || self.train_source.is_empty() {
            return Err(PerceptionError::Invalid(
                "query_source and train_source must be non-empty".to_string(),
            ));
        }
        let count = self.query_id.len();
        validate_len("train_id", self.train_id.len(), count)?;
        validate_len("distance", self.distance.len(), count)?;
        validate_len("inlier", self.inlier.len(), count)?;
        validate_non_negative("distance", &self.distance)
    }
}

fn require_row(batch: &RecordBatch) -> Result<(), PerceptionError> {
    if batch.num_rows() == 0 {
        return Err(PerceptionError::Invalid(
            "RecordBatch must contain one row".to_string(),
        ));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use bytes::Bytes;

    use super::{Keypoint2DSet, KeypointMatchSet};

    #[test]
    fn keypoint_and_match_roundtrip() {
        let keypoints = Keypoint2DSet::new(
            vec![0, 1],
            vec![10.0, 20.0],
            vec![11.0, 21.0],
            vec![8.0, 8.0],
            vec![-1.0, 0.5],
            vec![0.9, 0.8],
            vec![0, 1],
            "uint8",
            2,
            Bytes::from_static(&[1, 2, 3, 4]),
        )
        .unwrap();
        let batch = keypoints.to_record_batch().unwrap();
        assert_eq!(Keypoint2DSet::from_record_batch(&batch).unwrap(), keypoints);

        let matches = KeypointMatchSet::new(
            "previous",
            "current",
            vec![0],
            vec![1],
            vec![0.25],
            vec![true],
        )
        .unwrap();
        let batch = matches.to_record_batch().unwrap();
        assert_eq!(
            KeypointMatchSet::from_record_batch(&batch).unwrap(),
            matches
        );
    }

    #[test]
    fn rejects_invalid_descriptor_length() {
        let result = Keypoint2DSet::new(
            vec![0],
            vec![1.0],
            vec![2.0],
            vec![3.0],
            vec![-1.0],
            vec![0.5],
            vec![0],
            "float32",
            2,
            Bytes::from_static(&[0; 4]),
        );
        assert!(result.is_err());
    }
}
