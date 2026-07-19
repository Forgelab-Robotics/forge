mod classification;
mod detection;
mod keypoint;
mod segmentation;

pub use classification::Classification;
pub use detection::{Detection2DSet, Detection3DSet};
pub use keypoint::{Keypoint2DSet, Keypoint3DSet};
pub use segmentation::SegmentationMaskSet;

use arrow_array::RecordBatch;

#[derive(Debug)]
pub enum PerceptionError {
    Arrow(String),
    Invalid(String),
}

impl std::fmt::Display for PerceptionError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Arrow(message) => write!(formatter, "arrow error: {message}"),
            Self::Invalid(message) => write!(formatter, "invalid perception message: {message}"),
        }
    }
}

impl std::error::Error for PerceptionError {}

fn require_single_row(batch: &RecordBatch) -> Result<(), PerceptionError> {
    if batch.num_rows() != 1 {
        return Err(PerceptionError::Invalid(format!(
            "RecordBatch must contain exactly one row, got {}",
            batch.num_rows()
        )));
    }
    Ok(())
}

fn validate_unique(name: &str, values: &[String]) -> Result<(), PerceptionError> {
    let mut sorted = values.to_vec();
    sorted.sort();
    sorted.dedup();
    if sorted.len() != values.len() {
        return Err(PerceptionError::Invalid(format!(
            "{name} items must be unique"
        )));
    }
    Ok(())
}

fn validate_len(name: &str, actual: usize, expected: usize) -> Result<(), PerceptionError> {
    if actual != expected {
        return Err(PerceptionError::Invalid(format!(
            "{name} must have length {expected}, got {actual}"
        )));
    }
    Ok(())
}

fn validate_non_negative(name: &str, values: &[f32]) -> Result<(), PerceptionError> {
    if values
        .iter()
        .any(|value| !value.is_finite() || *value < 0.0)
    {
        return Err(PerceptionError::Invalid(format!(
            "{name} values must be finite and non-negative"
        )));
    }
    Ok(())
}

fn validate_finite(name: &str, values: &[f32]) -> Result<(), PerceptionError> {
    if values.iter().any(|value| !value.is_finite()) {
        return Err(PerceptionError::Invalid(format!(
            "{name} values must be finite"
        )));
    }
    Ok(())
}

fn validate_unit_scores(name: &str, values: &[f32]) -> Result<(), PerceptionError> {
    if values
        .iter()
        .any(|value| !value.is_finite() || !(0.0..=1.0).contains(value))
    {
        return Err(PerceptionError::Invalid(format!(
            "{name} values must be finite and in the range [0, 1]"
        )));
    }
    Ok(())
}

fn validate_hypotheses(
    detection_count: usize,
    offsets: &[u32],
    class_id: &[String],
    score: &[f32],
) -> Result<(), PerceptionError> {
    validate_len("hypothesis_offset", offsets.len(), detection_count + 1)?;
    if offsets.first() != Some(&0) {
        return Err(PerceptionError::Invalid(
            "hypothesis_offset must start at 0".to_string(),
        ));
    }
    if offsets.windows(2).any(|values| values[0] > values[1]) {
        return Err(PerceptionError::Invalid(
            "hypothesis_offset must be monotonically non-decreasing".to_string(),
        ));
    }
    let class_count = u32::try_from(class_id.len()).map_err(|_| {
        PerceptionError::Invalid("class_id length exceeds the uint32 range".to_string())
    })?;
    if offsets.last().copied() != Some(class_count) {
        return Err(PerceptionError::Invalid(
            "hypothesis_offset must end at class_id length".to_string(),
        ));
    }
    validate_len("score", score.len(), class_id.len())?;
    validate_unit_scores("score", score)
}

#[cfg(test)]
mod tests {
    use std::sync::Arc;

    use arrow_array::{ArrayRef, NullArray, RecordBatch};
    use arrow_schema::{DataType, Field, Schema};

    use super::{
        Classification, Detection2DSet, Detection3DSet, Keypoint2DSet, Keypoint3DSet,
        SegmentationMaskSet,
    };

    fn batch_with_rows(row_count: usize) -> RecordBatch {
        RecordBatch::try_new(
            Arc::new(Schema::new(vec![Field::new(
                "irrelevant",
                DataType::Null,
                true,
            )])),
            vec![Arc::new(NullArray::new(row_count)) as ArrayRef],
        )
        .unwrap()
    }

    #[test]
    fn perception_readers_require_exactly_one_row() {
        for row_count in [0, 2] {
            let batch = batch_with_rows(row_count);
            assert!(Classification::from_record_batch(&batch).is_err());
            assert!(Detection2DSet::from_record_batch(&batch).is_err());
            assert!(Detection3DSet::from_record_batch(&batch).is_err());
            assert!(Keypoint2DSet::from_record_batch(&batch).is_err());
            assert!(Keypoint3DSet::from_record_batch(&batch).is_err());
            assert!(SegmentationMaskSet::from_record_batch(&batch).is_err());
        }
    }
}
