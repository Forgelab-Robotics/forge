use std::sync::Arc;

use arrow_array::{ArrayRef, RecordBatch};
use arrow_schema::{DataType, Field, Schema};

use crate::column::{
    f32_list, list_type, read_f32_list, read_string_list, read_u32_list, string_list, u32_list,
};

use super::{
    PerceptionError, require_single_row as require_row, validate_finite, validate_hypotheses,
    validate_len, validate_non_negative, validate_unique,
};

#[derive(Clone, Debug, PartialEq)]
pub struct Detection2DSet {
    pub detection_id: Vec<String>,
    pub track_id: Vec<String>,
    pub center_x: Vec<f32>,
    pub center_y: Vec<f32>,
    pub size_x: Vec<f32>,
    pub size_y: Vec<f32>,
    pub rotation: Vec<f32>,
    pub hypothesis_offset: Vec<u32>,
    pub class_id: Vec<String>,
    pub score: Vec<f32>,
}

#[derive(Clone, Debug, PartialEq)]
pub struct Detection3DSet {
    pub detection_id: Vec<String>,
    pub track_id: Vec<String>,
    pub center_x: Vec<f32>,
    pub center_y: Vec<f32>,
    pub center_z: Vec<f32>,
    pub qx: Vec<f32>,
    pub qy: Vec<f32>,
    pub qz: Vec<f32>,
    pub qw: Vec<f32>,
    pub size_x: Vec<f32>,
    pub size_y: Vec<f32>,
    pub size_z: Vec<f32>,
    pub hypothesis_offset: Vec<u32>,
    pub class_id: Vec<String>,
    pub score: Vec<f32>,
}

impl Detection2DSet {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        detection_id: Vec<String>,
        track_id: Vec<String>,
        center_x: Vec<f32>,
        center_y: Vec<f32>,
        size_x: Vec<f32>,
        size_y: Vec<f32>,
        rotation: Vec<f32>,
        hypothesis_offset: Vec<u32>,
        class_id: Vec<String>,
        score: Vec<f32>,
    ) -> Result<Self, PerceptionError> {
        let rotation = if rotation.is_empty() && !detection_id.is_empty() {
            vec![0.0; detection_id.len()]
        } else {
            rotation
        };
        let value = Self {
            detection_id,
            track_id,
            center_x,
            center_y,
            size_x,
            size_y,
            rotation,
            hypothesis_offset,
            class_id,
            score,
        };
        value.validate()?;
        Ok(value)
    }

    pub fn empty() -> Self {
        Self {
            detection_id: Vec::new(),
            track_id: Vec::new(),
            center_x: Vec::new(),
            center_y: Vec::new(),
            size_x: Vec::new(),
            size_y: Vec::new(),
            rotation: Vec::new(),
            hypothesis_offset: vec![0],
            class_id: Vec::new(),
            score: Vec::new(),
        }
    }

    pub fn to_record_batch(&self) -> Result<RecordBatch, PerceptionError> {
        self.validate()?;
        let schema = Arc::new(Schema::new(vec![
            Field::new("detection_id", list_type(DataType::Utf8), false),
            Field::new("track_id", list_type(DataType::Utf8), false),
            Field::new("center_x", list_type(DataType::Float32), false),
            Field::new("center_y", list_type(DataType::Float32), false),
            Field::new("size_x", list_type(DataType::Float32), false),
            Field::new("size_y", list_type(DataType::Float32), false),
            Field::new("rotation", list_type(DataType::Float32), false),
            Field::new("hypothesis_offset", list_type(DataType::UInt32), false),
            Field::new("class_id", list_type(DataType::Utf8), false),
            Field::new("score", list_type(DataType::Float32), false),
        ]));
        let columns: Vec<ArrayRef> = vec![
            Arc::new(string_list(&self.detection_id)),
            Arc::new(string_list(&self.track_id)),
            Arc::new(f32_list(&self.center_x)),
            Arc::new(f32_list(&self.center_y)),
            Arc::new(f32_list(&self.size_x)),
            Arc::new(f32_list(&self.size_y)),
            Arc::new(f32_list(&self.rotation)),
            Arc::new(u32_list(&self.hypothesis_offset)),
            Arc::new(string_list(&self.class_id)),
            Arc::new(f32_list(&self.score)),
        ];
        RecordBatch::try_new(schema, columns)
            .map_err(|error| PerceptionError::Arrow(error.to_string()))
    }

    pub fn from_record_batch(batch: &RecordBatch) -> Result<Self, PerceptionError> {
        require_row(batch)?;
        Self::new(
            read_string_list(batch, "detection_id").map_err(PerceptionError::Invalid)?,
            read_string_list(batch, "track_id").map_err(PerceptionError::Invalid)?,
            read_f32_list(batch, "center_x").map_err(PerceptionError::Invalid)?,
            read_f32_list(batch, "center_y").map_err(PerceptionError::Invalid)?,
            read_f32_list(batch, "size_x").map_err(PerceptionError::Invalid)?,
            read_f32_list(batch, "size_y").map_err(PerceptionError::Invalid)?,
            read_f32_list(batch, "rotation").map_err(PerceptionError::Invalid)?,
            read_u32_list(batch, "hypothesis_offset").map_err(PerceptionError::Invalid)?,
            read_string_list(batch, "class_id").map_err(PerceptionError::Invalid)?,
            read_f32_list(batch, "score").map_err(PerceptionError::Invalid)?,
        )
    }

    fn validate(&self) -> Result<(), PerceptionError> {
        validate_unique("detection_id", &self.detection_id)?;
        let count = self.detection_id.len();
        validate_len("track_id", self.track_id.len(), count)?;
        validate_len("center_x", self.center_x.len(), count)?;
        validate_len("center_y", self.center_y.len(), count)?;
        validate_len("size_x", self.size_x.len(), count)?;
        validate_len("size_y", self.size_y.len(), count)?;
        validate_len("rotation", self.rotation.len(), count)?;
        validate_non_negative("size_x", &self.size_x)?;
        validate_non_negative("size_y", &self.size_y)?;
        validate_finite("center_x", &self.center_x)?;
        validate_finite("center_y", &self.center_y)?;
        validate_finite("rotation", &self.rotation)?;
        validate_hypotheses(count, &self.hypothesis_offset, &self.class_id, &self.score)
    }
}

impl Detection3DSet {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        detection_id: Vec<String>,
        track_id: Vec<String>,
        center_x: Vec<f32>,
        center_y: Vec<f32>,
        center_z: Vec<f32>,
        qx: Vec<f32>,
        qy: Vec<f32>,
        qz: Vec<f32>,
        qw: Vec<f32>,
        size_x: Vec<f32>,
        size_y: Vec<f32>,
        size_z: Vec<f32>,
        hypothesis_offset: Vec<u32>,
        class_id: Vec<String>,
        score: Vec<f32>,
    ) -> Result<Self, PerceptionError> {
        let count = detection_id.len();
        let (qx, qy, qz, qw) =
            if count > 0 && qx.is_empty() && qy.is_empty() && qz.is_empty() && qw.is_empty() {
                (
                    vec![0.0; count],
                    vec![0.0; count],
                    vec![0.0; count],
                    vec![1.0; count],
                )
            } else {
                (qx, qy, qz, qw)
            };
        let value = Self {
            detection_id,
            track_id,
            center_x,
            center_y,
            center_z,
            qx,
            qy,
            qz,
            qw,
            size_x,
            size_y,
            size_z,
            hypothesis_offset,
            class_id,
            score,
        };
        value.validate()?;
        Ok(value)
    }

    pub fn to_record_batch(&self) -> Result<RecordBatch, PerceptionError> {
        self.validate()?;
        let string_type = list_type(DataType::Utf8);
        let float_type = list_type(DataType::Float32);
        let schema = Arc::new(Schema::new(vec![
            Field::new("detection_id", string_type.clone(), false),
            Field::new("track_id", string_type.clone(), false),
            Field::new("center_x", float_type.clone(), false),
            Field::new("center_y", float_type.clone(), false),
            Field::new("center_z", float_type.clone(), false),
            Field::new("qx", float_type.clone(), false),
            Field::new("qy", float_type.clone(), false),
            Field::new("qz", float_type.clone(), false),
            Field::new("qw", float_type.clone(), false),
            Field::new("size_x", float_type.clone(), false),
            Field::new("size_y", float_type.clone(), false),
            Field::new("size_z", float_type, false),
            Field::new("hypothesis_offset", list_type(DataType::UInt32), false),
            Field::new("class_id", string_type, false),
            Field::new("score", list_type(DataType::Float32), false),
        ]));
        let columns: Vec<ArrayRef> = vec![
            Arc::new(string_list(&self.detection_id)),
            Arc::new(string_list(&self.track_id)),
            Arc::new(f32_list(&self.center_x)),
            Arc::new(f32_list(&self.center_y)),
            Arc::new(f32_list(&self.center_z)),
            Arc::new(f32_list(&self.qx)),
            Arc::new(f32_list(&self.qy)),
            Arc::new(f32_list(&self.qz)),
            Arc::new(f32_list(&self.qw)),
            Arc::new(f32_list(&self.size_x)),
            Arc::new(f32_list(&self.size_y)),
            Arc::new(f32_list(&self.size_z)),
            Arc::new(u32_list(&self.hypothesis_offset)),
            Arc::new(string_list(&self.class_id)),
            Arc::new(f32_list(&self.score)),
        ];
        RecordBatch::try_new(schema, columns)
            .map_err(|error| PerceptionError::Arrow(error.to_string()))
    }

    pub fn from_record_batch(batch: &RecordBatch) -> Result<Self, PerceptionError> {
        require_row(batch)?;
        Self::new(
            read_string_list(batch, "detection_id").map_err(PerceptionError::Invalid)?,
            read_string_list(batch, "track_id").map_err(PerceptionError::Invalid)?,
            read_f32_list(batch, "center_x").map_err(PerceptionError::Invalid)?,
            read_f32_list(batch, "center_y").map_err(PerceptionError::Invalid)?,
            read_f32_list(batch, "center_z").map_err(PerceptionError::Invalid)?,
            read_f32_list(batch, "qx").map_err(PerceptionError::Invalid)?,
            read_f32_list(batch, "qy").map_err(PerceptionError::Invalid)?,
            read_f32_list(batch, "qz").map_err(PerceptionError::Invalid)?,
            read_f32_list(batch, "qw").map_err(PerceptionError::Invalid)?,
            read_f32_list(batch, "size_x").map_err(PerceptionError::Invalid)?,
            read_f32_list(batch, "size_y").map_err(PerceptionError::Invalid)?,
            read_f32_list(batch, "size_z").map_err(PerceptionError::Invalid)?,
            read_u32_list(batch, "hypothesis_offset").map_err(PerceptionError::Invalid)?,
            read_string_list(batch, "class_id").map_err(PerceptionError::Invalid)?,
            read_f32_list(batch, "score").map_err(PerceptionError::Invalid)?,
        )
    }

    fn validate(&self) -> Result<(), PerceptionError> {
        validate_unique("detection_id", &self.detection_id)?;
        let count = self.detection_id.len();
        for (name, actual) in [
            ("track_id", self.track_id.len()),
            ("center_x", self.center_x.len()),
            ("center_y", self.center_y.len()),
            ("center_z", self.center_z.len()),
            ("qx", self.qx.len()),
            ("qy", self.qy.len()),
            ("qz", self.qz.len()),
            ("qw", self.qw.len()),
            ("size_x", self.size_x.len()),
            ("size_y", self.size_y.len()),
            ("size_z", self.size_z.len()),
        ] {
            validate_len(name, actual, count)?;
        }
        for index in 0..count {
            if self.qx[index] == 0.0
                && self.qy[index] == 0.0
                && self.qz[index] == 0.0
                && self.qw[index] == 0.0
            {
                return Err(PerceptionError::Invalid(
                    "quaternion must not be all zero".to_string(),
                ));
            }
        }
        for (name, values) in [
            ("center_x", self.center_x.as_slice()),
            ("center_y", self.center_y.as_slice()),
            ("center_z", self.center_z.as_slice()),
            ("qx", self.qx.as_slice()),
            ("qy", self.qy.as_slice()),
            ("qz", self.qz.as_slice()),
            ("qw", self.qw.as_slice()),
        ] {
            validate_finite(name, values)?;
        }
        validate_non_negative("size_x", &self.size_x)?;
        validate_non_negative("size_y", &self.size_y)?;
        validate_non_negative("size_z", &self.size_z)?;
        validate_hypotheses(count, &self.hypothesis_offset, &self.class_id, &self.score)
    }
}

#[cfg(test)]
mod tests {
    use super::{Detection2DSet, Detection3DSet};

    #[test]
    fn detection_2d_roundtrip_and_empty_result() {
        let detections = Detection2DSet::new(
            vec!["d0".into(), "d1".into()],
            vec!["track-7".into(), String::new()],
            vec![10.5, 20.0],
            vec![11.0, 21.0],
            vec![4.0, 8.0],
            vec![5.0, 9.0],
            vec![0.0, 0.25],
            vec![0, 2, 3],
            vec!["person".into(), "worker".into(), "cup".into()],
            vec![0.9, 0.1, 0.8],
        )
        .unwrap();
        let batch = detections.to_record_batch().unwrap();
        assert_eq!(
            Detection2DSet::from_record_batch(&batch).unwrap(),
            detections
        );

        let empty = Detection2DSet::empty();
        let batch = empty.to_record_batch().unwrap();
        assert_eq!(Detection2DSet::from_record_batch(&batch).unwrap(), empty);

        let axis_aligned = Detection2DSet::new(
            vec!["d0".into()],
            vec![String::new()],
            vec![10.5],
            vec![11.0],
            vec![4.0],
            vec![5.0],
            Vec::new(),
            vec![0, 1],
            vec!["person".into()],
            vec![0.9],
        )
        .unwrap();
        assert_eq!(axis_aligned.rotation, vec![0.0]);
    }

    #[test]
    fn detection_3d_roundtrip() {
        let detection = Detection3DSet::new(
            vec!["d0".into()],
            vec![String::new()],
            vec![1.0],
            vec![2.0],
            vec![3.0],
            vec![0.0],
            vec![0.0],
            vec![0.0],
            vec![1.0],
            vec![0.5],
            vec![0.6],
            vec![0.7],
            vec![0, 1],
            vec!["box".into()],
            vec![0.95],
        )
        .unwrap();
        let batch = detection.to_record_batch().unwrap();
        assert_eq!(
            Detection3DSet::from_record_batch(&batch).unwrap(),
            detection
        );

        let axis_aligned = Detection3DSet::new(
            vec!["d0".into()],
            vec![String::new()],
            vec![1.0],
            vec![2.0],
            vec![3.0],
            Vec::new(),
            Vec::new(),
            Vec::new(),
            Vec::new(),
            vec![0.5],
            vec![0.6],
            vec![0.7],
            vec![0, 1],
            vec!["box".into()],
            vec![0.95],
        )
        .unwrap();
        assert_eq!(axis_aligned.qx, vec![0.0]);
        assert_eq!(axis_aligned.qy, vec![0.0]);
        assert_eq!(axis_aligned.qz, vec![0.0]);
        assert_eq!(axis_aligned.qw, vec![1.0]);
    }

    #[test]
    fn rejects_invalid_hypothesis_offsets() {
        let result = Detection2DSet::new(
            vec!["d0".into()],
            vec![String::new()],
            vec![0.0],
            vec![0.0],
            vec![1.0],
            vec![1.0],
            vec![0.0],
            vec![0, 0],
            vec!["person".into()],
            vec![0.9],
        );
        assert!(result.is_err());
    }
}
