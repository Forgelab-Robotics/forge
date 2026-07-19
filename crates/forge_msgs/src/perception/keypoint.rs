use std::collections::HashSet;
use std::sync::Arc;

use arrow_array::{ArrayRef, RecordBatch};
use arrow_schema::{DataType, Field, Schema};

use crate::column::{
    f32_list, list_type, read_f32_list, read_string_list, read_u32_list, string_list, u32_list,
};

use super::{
    PerceptionError, require_single_row as require_row, validate_finite, validate_len,
    validate_unique, validate_unit_scores,
};

#[derive(Clone, Debug, PartialEq)]
pub struct Keypoint2DSet {
    pub instance_id: Vec<String>,
    pub detection_id: Vec<String>,
    pub track_id: Vec<String>,
    pub keypoint_offset: Vec<u32>,
    pub keypoint_id: Vec<String>,
    pub x: Vec<f32>,
    pub y: Vec<f32>,
    pub score: Vec<f32>,
}

#[derive(Clone, Debug, PartialEq)]
pub struct Keypoint3DSet {
    pub instance_id: Vec<String>,
    pub detection_id: Vec<String>,
    pub track_id: Vec<String>,
    pub keypoint_offset: Vec<u32>,
    pub keypoint_id: Vec<String>,
    pub x: Vec<f32>,
    pub y: Vec<f32>,
    pub z: Vec<f32>,
    pub score: Vec<f32>,
}

impl Keypoint2DSet {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        instance_id: Vec<String>,
        detection_id: Vec<String>,
        track_id: Vec<String>,
        keypoint_offset: Vec<u32>,
        keypoint_id: Vec<String>,
        x: Vec<f32>,
        y: Vec<f32>,
        score: Vec<f32>,
    ) -> Result<Self, PerceptionError> {
        let count = instance_id.len();
        let value = Self {
            instance_id,
            detection_id: default_association(detection_id, count),
            track_id: default_association(track_id, count),
            keypoint_offset: default_offsets(keypoint_offset),
            keypoint_id,
            x,
            y,
            score,
        };
        value.validate()?;
        Ok(value)
    }

    pub fn empty() -> Self {
        Self {
            instance_id: Vec::new(),
            detection_id: Vec::new(),
            track_id: Vec::new(),
            keypoint_offset: vec![0],
            keypoint_id: Vec::new(),
            x: Vec::new(),
            y: Vec::new(),
            score: Vec::new(),
        }
    }

    pub fn to_record_batch(&self) -> Result<RecordBatch, PerceptionError> {
        self.validate()?;
        let schema = Arc::new(Schema::new(vec![
            Field::new("instance_id", list_type(DataType::Utf8), false),
            Field::new("detection_id", list_type(DataType::Utf8), false),
            Field::new("track_id", list_type(DataType::Utf8), false),
            Field::new("keypoint_offset", list_type(DataType::UInt32), false),
            Field::new("keypoint_id", list_type(DataType::Utf8), false),
            Field::new("x", list_type(DataType::Float32), false),
            Field::new("y", list_type(DataType::Float32), false),
            Field::new("score", list_type(DataType::Float32), false),
        ]));
        let columns: Vec<ArrayRef> = vec![
            Arc::new(string_list(&self.instance_id)),
            Arc::new(string_list(&self.detection_id)),
            Arc::new(string_list(&self.track_id)),
            Arc::new(u32_list(&self.keypoint_offset)),
            Arc::new(string_list(&self.keypoint_id)),
            Arc::new(f32_list(&self.x)),
            Arc::new(f32_list(&self.y)),
            Arc::new(f32_list(&self.score)),
        ];
        RecordBatch::try_new(schema, columns)
            .map_err(|error| PerceptionError::Arrow(error.to_string()))
    }

    pub fn from_record_batch(batch: &RecordBatch) -> Result<Self, PerceptionError> {
        require_row(batch)?;
        Self::new(
            read_string_list(batch, "instance_id").map_err(PerceptionError::Invalid)?,
            read_string_list(batch, "detection_id").map_err(PerceptionError::Invalid)?,
            read_string_list(batch, "track_id").map_err(PerceptionError::Invalid)?,
            read_u32_list(batch, "keypoint_offset").map_err(PerceptionError::Invalid)?,
            read_string_list(batch, "keypoint_id").map_err(PerceptionError::Invalid)?,
            read_f32_list(batch, "x").map_err(PerceptionError::Invalid)?,
            read_f32_list(batch, "y").map_err(PerceptionError::Invalid)?,
            read_f32_list(batch, "score").map_err(PerceptionError::Invalid)?,
        )
    }

    fn validate(&self) -> Result<(), PerceptionError> {
        validate_keypoints(
            &self.instance_id,
            &self.detection_id,
            &self.track_id,
            &self.keypoint_offset,
            &self.keypoint_id,
            &self.score,
        )?;
        let count = self.keypoint_id.len();
        validate_len("x", self.x.len(), count)?;
        validate_len("y", self.y.len(), count)?;
        validate_finite("x", &self.x)?;
        validate_finite("y", &self.y)
    }
}

impl Keypoint3DSet {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        instance_id: Vec<String>,
        detection_id: Vec<String>,
        track_id: Vec<String>,
        keypoint_offset: Vec<u32>,
        keypoint_id: Vec<String>,
        x: Vec<f32>,
        y: Vec<f32>,
        z: Vec<f32>,
        score: Vec<f32>,
    ) -> Result<Self, PerceptionError> {
        let count = instance_id.len();
        let value = Self {
            instance_id,
            detection_id: default_association(detection_id, count),
            track_id: default_association(track_id, count),
            keypoint_offset: default_offsets(keypoint_offset),
            keypoint_id,
            x,
            y,
            z,
            score,
        };
        value.validate()?;
        Ok(value)
    }

    pub fn empty() -> Self {
        Self {
            instance_id: Vec::new(),
            detection_id: Vec::new(),
            track_id: Vec::new(),
            keypoint_offset: vec![0],
            keypoint_id: Vec::new(),
            x: Vec::new(),
            y: Vec::new(),
            z: Vec::new(),
            score: Vec::new(),
        }
    }

    pub fn to_record_batch(&self) -> Result<RecordBatch, PerceptionError> {
        self.validate()?;
        let schema = Arc::new(Schema::new(vec![
            Field::new("instance_id", list_type(DataType::Utf8), false),
            Field::new("detection_id", list_type(DataType::Utf8), false),
            Field::new("track_id", list_type(DataType::Utf8), false),
            Field::new("keypoint_offset", list_type(DataType::UInt32), false),
            Field::new("keypoint_id", list_type(DataType::Utf8), false),
            Field::new("x", list_type(DataType::Float32), false),
            Field::new("y", list_type(DataType::Float32), false),
            Field::new("z", list_type(DataType::Float32), false),
            Field::new("score", list_type(DataType::Float32), false),
        ]));
        let columns: Vec<ArrayRef> = vec![
            Arc::new(string_list(&self.instance_id)),
            Arc::new(string_list(&self.detection_id)),
            Arc::new(string_list(&self.track_id)),
            Arc::new(u32_list(&self.keypoint_offset)),
            Arc::new(string_list(&self.keypoint_id)),
            Arc::new(f32_list(&self.x)),
            Arc::new(f32_list(&self.y)),
            Arc::new(f32_list(&self.z)),
            Arc::new(f32_list(&self.score)),
        ];
        RecordBatch::try_new(schema, columns)
            .map_err(|error| PerceptionError::Arrow(error.to_string()))
    }

    pub fn from_record_batch(batch: &RecordBatch) -> Result<Self, PerceptionError> {
        require_row(batch)?;
        Self::new(
            read_string_list(batch, "instance_id").map_err(PerceptionError::Invalid)?,
            read_string_list(batch, "detection_id").map_err(PerceptionError::Invalid)?,
            read_string_list(batch, "track_id").map_err(PerceptionError::Invalid)?,
            read_u32_list(batch, "keypoint_offset").map_err(PerceptionError::Invalid)?,
            read_string_list(batch, "keypoint_id").map_err(PerceptionError::Invalid)?,
            read_f32_list(batch, "x").map_err(PerceptionError::Invalid)?,
            read_f32_list(batch, "y").map_err(PerceptionError::Invalid)?,
            read_f32_list(batch, "z").map_err(PerceptionError::Invalid)?,
            read_f32_list(batch, "score").map_err(PerceptionError::Invalid)?,
        )
    }

    fn validate(&self) -> Result<(), PerceptionError> {
        validate_keypoints(
            &self.instance_id,
            &self.detection_id,
            &self.track_id,
            &self.keypoint_offset,
            &self.keypoint_id,
            &self.score,
        )?;
        let count = self.keypoint_id.len();
        for (name, values) in [
            ("x", self.x.as_slice()),
            ("y", self.y.as_slice()),
            ("z", self.z.as_slice()),
        ] {
            validate_len(name, values.len(), count)?;
            validate_finite(name, values)?;
        }
        Ok(())
    }
}

fn default_association(values: Vec<String>, count: usize) -> Vec<String> {
    if values.is_empty() && count > 0 {
        vec![String::new(); count]
    } else {
        values
    }
}

fn default_offsets(offsets: Vec<u32>) -> Vec<u32> {
    if offsets.is_empty() { vec![0] } else { offsets }
}

fn validate_keypoints(
    instance_id: &[String],
    detection_id: &[String],
    track_id: &[String],
    offsets: &[u32],
    keypoint_id: &[String],
    score: &[f32],
) -> Result<(), PerceptionError> {
    validate_unique("instance_id", instance_id)?;
    let instance_count = instance_id.len();
    validate_len("detection_id", detection_id.len(), instance_count)?;
    validate_len("track_id", track_id.len(), instance_count)?;
    validate_len("keypoint_offset", offsets.len(), instance_count + 1)?;
    if offsets.first() != Some(&0) {
        return Err(PerceptionError::Invalid(
            "keypoint_offset must start at 0".to_string(),
        ));
    }
    if offsets.windows(2).any(|values| values[0] > values[1]) {
        return Err(PerceptionError::Invalid(
            "keypoint_offset must be monotonically non-decreasing".to_string(),
        ));
    }
    let keypoint_count = u32::try_from(keypoint_id.len()).map_err(|_| {
        PerceptionError::Invalid("keypoint_id length exceeds the uint32 range".to_string())
    })?;
    if offsets.last().copied() != Some(keypoint_count) {
        return Err(PerceptionError::Invalid(
            "keypoint_offset must end at keypoint_id length".to_string(),
        ));
    }
    validate_len("score", score.len(), keypoint_id.len())?;
    validate_unit_scores("score", score)?;

    for (index, range) in offsets.windows(2).enumerate() {
        let start = range[0] as usize;
        let end = range[1] as usize;
        let mut unique = HashSet::with_capacity(end - start);
        if keypoint_id[start..end]
            .iter()
            .any(|id| !unique.insert(id.as_str()))
        {
            return Err(PerceptionError::Invalid(format!(
                "keypoint_id items must be unique within instance {index}"
            )));
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::{Keypoint2DSet, Keypoint3DSet};

    #[test]
    fn keypoint_2d_roundtrip_defaults_and_canonical_order() {
        let keypoints = Keypoint2DSet::new(
            vec!["pose-0".into(), "pose-1".into()],
            Vec::new(),
            Vec::new(),
            vec![0, 2, 3],
            vec!["left".into(), "right".into(), "left".into()],
            vec![1.0, 2.0, 3.0],
            vec![4.0, 5.0, 6.0],
            vec![0.9, 0.8, 0.7],
        )
        .unwrap();
        assert_eq!(keypoints.detection_id, vec![String::new(); 2]);
        assert_eq!(keypoints.track_id, vec![String::new(); 2]);

        let batch = keypoints.to_record_batch().unwrap();
        let fields: Vec<_> = batch
            .schema()
            .fields()
            .iter()
            .map(|field| field.name().clone())
            .collect();
        assert_eq!(
            fields,
            [
                "instance_id",
                "detection_id",
                "track_id",
                "keypoint_offset",
                "keypoint_id",
                "x",
                "y",
                "score",
            ]
        );
        assert_eq!(Keypoint2DSet::from_record_batch(&batch).unwrap(), keypoints);

        let empty = Keypoint2DSet::new(
            Vec::new(),
            Vec::new(),
            Vec::new(),
            Vec::new(),
            Vec::new(),
            Vec::new(),
            Vec::new(),
            Vec::new(),
        )
        .unwrap();
        assert_eq!(empty, Keypoint2DSet::empty());
    }

    #[test]
    fn keypoint_3d_roundtrip() {
        let keypoints = Keypoint3DSet::new(
            vec!["pose-0".into()],
            vec!["d0".into()],
            vec!["t0".into()],
            vec![0, 1],
            vec!["nose".into()],
            vec![1.0],
            vec![2.0],
            vec![3.0],
            vec![1.0],
        )
        .unwrap();
        let batch = keypoints.to_record_batch().unwrap();
        assert_eq!(Keypoint3DSet::from_record_batch(&batch).unwrap(), keypoints);
    }

    #[test]
    fn rejects_invalid_keypoints() {
        assert!(
            Keypoint2DSet::new(
                vec!["pose-0".into(), "pose-0".into()],
                Vec::new(),
                Vec::new(),
                vec![0, 0, 0],
                Vec::new(),
                Vec::new(),
                Vec::new(),
                Vec::new(),
            )
            .is_err()
        );
        assert!(
            Keypoint2DSet::new(
                vec!["pose-0".into()],
                Vec::new(),
                Vec::new(),
                vec![0, 2],
                vec!["nose".into(), "nose".into()],
                vec![1.0, 2.0],
                vec![1.0, 2.0],
                vec![0.9, 0.8],
            )
            .is_err()
        );
        assert!(
            Keypoint2DSet::new(
                vec!["pose-0".into()],
                Vec::new(),
                Vec::new(),
                vec![1, 1],
                vec!["nose".into()],
                vec![1.0],
                vec![2.0],
                vec![0.9],
            )
            .is_err()
        );
        assert!(
            Keypoint3DSet::new(
                vec!["pose-0".into()],
                Vec::new(),
                Vec::new(),
                vec![0, 1],
                vec!["nose".into()],
                vec![1.0],
                vec![2.0],
                vec![f32::INFINITY],
                vec![0.9],
            )
            .is_err()
        );
        assert!(
            Keypoint2DSet::new(
                vec!["pose-0".into()],
                Vec::new(),
                Vec::new(),
                vec![0, 1],
                vec!["nose".into()],
                vec![1.0],
                vec![2.0],
                vec![-0.1],
            )
            .is_err()
        );
    }
}
