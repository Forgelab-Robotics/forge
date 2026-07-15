use std::sync::Arc;

use arrow_array::{Array, ArrayRef, LargeBinaryArray, RecordBatch, StringArray, UInt32Array};
use arrow_schema::{DataType, Field, Schema};
use bytes::Bytes;

use crate::column::{column_as, read_string, read_u32};

#[derive(Clone, Debug, PartialEq)]
pub struct AudioChunk {
    pub sample_rate: u32,
    pub channels: u32,
    pub sample_format: String,
    pub frame_count: u32,
    pub data: Bytes,
}

impl AudioChunk {
    pub fn new(
        sample_rate: u32,
        channels: u32,
        sample_format: impl Into<String>,
        frame_count: u32,
        data: Bytes,
    ) -> Result<Self, AudioError> {
        let value = Self {
            sample_rate,
            channels,
            sample_format: sample_format.into(),
            frame_count,
            data,
        };
        value.validate()?;
        Ok(value)
    }

    pub fn to_record_batch(&self) -> Result<RecordBatch, AudioError> {
        self.validate()?;
        let schema = Arc::new(Schema::new(vec![
            Field::new("sample_rate", DataType::UInt32, false),
            Field::new("channels", DataType::UInt32, false),
            Field::new("sample_format", DataType::Utf8, false),
            Field::new("frame_count", DataType::UInt32, false),
            Field::new("data", DataType::LargeBinary, false),
        ]));
        let columns: Vec<ArrayRef> = vec![
            Arc::new(UInt32Array::from(vec![self.sample_rate])),
            Arc::new(UInt32Array::from(vec![self.channels])),
            Arc::new(StringArray::from(vec![self.sample_format.as_str()])),
            Arc::new(UInt32Array::from(vec![self.frame_count])),
            Arc::new(LargeBinaryArray::from_iter_values(std::iter::once(
                &self.data,
            ))),
        ];
        RecordBatch::try_new(schema, columns).map_err(|e| AudioError::Arrow(e.to_string()))
    }

    pub fn from_record_batch(batch: &RecordBatch) -> Result<Self, AudioError> {
        if batch.num_rows() == 0 {
            return Err(AudioError::Invalid(
                "RecordBatch must contain one row".to_string(),
            ));
        }
        let value = Self {
            sample_rate: read_u32(batch, "sample_rate").map_err(AudioError::Invalid)?,
            channels: read_u32(batch, "channels").map_err(AudioError::Invalid)?,
            sample_format: read_string(batch, "sample_format").map_err(AudioError::Invalid)?,
            frame_count: read_u32(batch, "frame_count").map_err(AudioError::Invalid)?,
            data: read_binary(batch, "data")?,
        };
        value.validate()?;
        Ok(value)
    }

    fn validate(&self) -> Result<(), AudioError> {
        if self.sample_rate == 0 {
            return Err(AudioError::Invalid(
                "sample_rate must be greater than 0".to_string(),
            ));
        }
        if self.channels == 0 {
            return Err(AudioError::Invalid(
                "channels must be greater than 0".to_string(),
            ));
        }
        let bytes_per_sample = bytes_per_sample(&self.sample_format)?;
        let expected = self.frame_count as usize * self.channels as usize * bytes_per_sample;
        if self.data.len() != expected {
            return Err(AudioError::Invalid(format!(
                "data length {} must equal frame_count * channels * bytes_per_sample {}",
                self.data.len(),
                expected
            )));
        }
        Ok(())
    }
}

fn bytes_per_sample(sample_format: &str) -> Result<usize, AudioError> {
    match sample_format {
        "f32le" => Ok(4),
        "s16le" => Ok(2),
        _ => Err(AudioError::UnsupportedSampleFormat(
            sample_format.to_string(),
        )),
    }
}

fn read_binary(batch: &RecordBatch, name: &str) -> Result<Bytes, AudioError> {
    let array = column_as::<LargeBinaryArray>(batch, name).map_err(AudioError::Invalid)?;
    if array.len() == 0 || array.is_null(0) {
        return Err(AudioError::Invalid(format!(
            "{name} must contain one non-null scalar row"
        )));
    }
    Ok(Bytes::copy_from_slice(array.value(0)))
}

#[derive(Debug)]
pub enum AudioError {
    Arrow(String),
    Invalid(String),
    UnsupportedSampleFormat(String),
}

impl std::fmt::Display for AudioError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            AudioError::Arrow(msg) => write!(f, "arrow error: {msg}"),
            AudioError::Invalid(msg) => write!(f, "invalid audio message: {msg}"),
            AudioError::UnsupportedSampleFormat(msg) => {
                write!(f, "unsupported audio sample format: {msg}")
            }
        }
    }
}

impl std::error::Error for AudioError {}

#[cfg(test)]
mod tests {
    use super::AudioChunk;
    use bytes::Bytes;

    #[test]
    fn f32le_roundtrip_record_batch() {
        let mut data = Vec::new();
        for value in [0.0f32, 0.25, -0.5, 1.0] {
            data.extend_from_slice(&value.to_le_bytes());
        }
        let chunk = AudioChunk::new(16_000, 1, "f32le", 4, Bytes::from(data)).unwrap();

        let batch = chunk.to_record_batch().unwrap();
        let back = AudioChunk::from_record_batch(&batch).unwrap();

        assert_eq!(back, chunk);
    }

    #[test]
    fn s16le_multichannel_roundtrip_record_batch() {
        let mut data = Vec::new();
        for value in [0i16, 100, -200, 300] {
            data.extend_from_slice(&value.to_le_bytes());
        }
        let chunk = AudioChunk::new(48_000, 2, "s16le", 2, Bytes::from(data)).unwrap();

        let batch = chunk.to_record_batch().unwrap();
        let back = AudioChunk::from_record_batch(&batch).unwrap();

        assert_eq!(back, chunk);
    }

    #[test]
    fn rejects_invalid_data_length() {
        let result = AudioChunk::new(16_000, 2, "s16le", 2, Bytes::from_static(b"bad"));

        assert!(result.is_err());
    }

    #[test]
    fn rejects_invalid_sample_format() {
        let result = AudioChunk::new(16_000, 1, "float32", 1, Bytes::from_static(&[0; 4]));

        assert!(result.is_err());
    }
}
