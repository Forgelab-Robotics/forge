mod detection;
mod segmentation;

pub use detection::{Detection2DSet, Detection3DSet};
pub use segmentation::SegmentationMaskSet;

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
    if score
        .iter()
        .any(|value| !value.is_finite() || !(0.0..=1.0).contains(value))
    {
        return Err(PerceptionError::Invalid(
            "score values must be finite and in the range [0, 1]".to_string(),
        ));
    }
    Ok(())
}
