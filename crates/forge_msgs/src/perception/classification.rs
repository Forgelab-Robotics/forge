use std::sync::Arc;

use arrow_array::{ArrayRef, RecordBatch};
use arrow_schema::{DataType, Field, Schema};

use crate::column::{f32_list, list_type, read_f32_list, read_string_list, string_list};

use super::{
    PerceptionError, require_single_row, validate_len, validate_unique, validate_unit_scores,
};

#[derive(Clone, Debug, PartialEq)]
pub struct Classification {
    pub class_id: Vec<String>,
    pub score: Vec<f32>,
}

impl Classification {
    pub fn new(class_id: Vec<String>, score: Vec<f32>) -> Result<Self, PerceptionError> {
        let value = Self { class_id, score };
        value.validate()?;
        Ok(value)
    }

    pub fn empty() -> Self {
        Self {
            class_id: Vec::new(),
            score: Vec::new(),
        }
    }

    pub fn to_record_batch(&self) -> Result<RecordBatch, PerceptionError> {
        self.validate()?;
        let schema = Arc::new(Schema::new(vec![
            Field::new("class_id", list_type(DataType::Utf8), false),
            Field::new("score", list_type(DataType::Float32), false),
        ]));
        let columns: Vec<ArrayRef> = vec![
            Arc::new(string_list(&self.class_id)),
            Arc::new(f32_list(&self.score)),
        ];
        RecordBatch::try_new(schema, columns)
            .map_err(|error| PerceptionError::Arrow(error.to_string()))
    }

    pub fn from_record_batch(batch: &RecordBatch) -> Result<Self, PerceptionError> {
        require_single_row(batch)?;
        Self::new(
            read_string_list(batch, "class_id").map_err(PerceptionError::Invalid)?,
            read_f32_list(batch, "score").map_err(PerceptionError::Invalid)?,
        )
    }

    fn validate(&self) -> Result<(), PerceptionError> {
        validate_unique("class_id", &self.class_id)?;
        validate_len("score", self.score.len(), self.class_id.len())?;
        validate_unit_scores("score", &self.score)
    }
}

#[cfg(test)]
mod tests {
    use super::Classification;

    #[test]
    fn classification_roundtrip_and_empty_result() {
        let classification =
            Classification::new(vec!["person".into(), "worker".into()], vec![0.9, 0.1]).unwrap();
        let batch = classification.to_record_batch().unwrap();
        let fields: Vec<_> = batch
            .schema()
            .fields()
            .iter()
            .map(|field| field.name().clone())
            .collect();
        assert_eq!(fields, ["class_id", "score"]);
        assert_eq!(
            Classification::from_record_batch(&batch).unwrap(),
            classification
        );

        let empty = Classification::empty();
        assert_eq!(
            Classification::from_record_batch(&empty.to_record_batch().unwrap()).unwrap(),
            empty
        );
    }

    #[test]
    fn classification_rejects_invalid_values() {
        assert!(
            Classification::new(vec!["person".into(), "person".into()], vec![0.5, 0.5]).is_err()
        );
        assert!(Classification::new(vec!["person".into()], Vec::new()).is_err());
        assert!(Classification::new(vec!["person".into()], vec![f32::NAN]).is_err());
        assert!(Classification::new(vec!["person".into()], vec![1.1]).is_err());
    }
}
