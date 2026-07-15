use std::sync::Arc;

use arrow_array::{ArrayRef, RecordBatch, StringArray};
use arrow_schema::{DataType, Field, Schema};

use crate::column::read_string;

#[derive(Clone, Debug, PartialEq)]
pub struct Text {
    pub text: String,
}

impl Text {
    pub fn new(text: impl Into<String>) -> Self {
        Self { text: text.into() }
    }

    pub fn to_record_batch(&self) -> Result<RecordBatch, TextError> {
        let schema = Arc::new(Schema::new(vec![Field::new("text", DataType::Utf8, false)]));
        let columns: Vec<ArrayRef> = vec![Arc::new(StringArray::from(vec![self.text.as_str()]))];
        RecordBatch::try_new(schema, columns).map_err(|e| TextError::Arrow(e.to_string()))
    }

    pub fn from_record_batch(batch: &RecordBatch) -> Result<Self, TextError> {
        if batch.num_rows() == 0 {
            return Err(TextError::Invalid(
                "RecordBatch must contain one row".to_string(),
            ));
        }
        Ok(Self::new(
            read_string(batch, "text").map_err(TextError::Invalid)?,
        ))
    }
}

#[derive(Debug)]
pub enum TextError {
    Arrow(String),
    Invalid(String),
}

impl std::fmt::Display for TextError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            TextError::Arrow(msg) => write!(f, "arrow error: {msg}"),
            TextError::Invalid(msg) => write!(f, "invalid text message: {msg}"),
        }
    }
}

impl std::error::Error for TextError {}

#[cfg(test)]
mod tests {
    use super::Text;

    #[test]
    fn roundtrip_record_batch() {
        let text = Text::new("前进");

        let batch = text.to_record_batch().unwrap();
        let back = Text::from_record_batch(&batch).unwrap();

        assert_eq!(back, text);
    }

    #[test]
    fn allows_empty_string() {
        let text = Text::new("");

        let batch = text.to_record_batch().unwrap();
        let back = Text::from_record_batch(&batch).unwrap();

        assert_eq!(back, text);
    }
}
