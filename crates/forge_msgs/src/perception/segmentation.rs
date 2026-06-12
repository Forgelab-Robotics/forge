use std::sync::Arc;

use arrow_array::{ArrayRef, RecordBatch, StringArray};
use arrow_schema::{DataType, Field, Schema};
use bytes::Bytes;

use crate::column::{
    binary_list, list_type, read_binary_list, read_string, read_string_list, read_u32_list,
    string_list, u32_list,
};

use super::{PerceptionError, validate_len, validate_unique};

#[derive(Clone, Debug, PartialEq)]
pub struct SegmentationMaskSet {
    pub mask_id: Vec<String>,
    pub detection_id: Vec<String>,
    pub track_id: Vec<String>,
    pub x_offset: Vec<u32>,
    pub y_offset: Vec<u32>,
    pub width: Vec<u32>,
    pub height: Vec<u32>,
    pub encoding: String,
    pub data: Vec<Bytes>,
}

impl SegmentationMaskSet {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        mask_id: Vec<String>,
        detection_id: Vec<String>,
        track_id: Vec<String>,
        x_offset: Vec<u32>,
        y_offset: Vec<u32>,
        width: Vec<u32>,
        height: Vec<u32>,
        encoding: impl Into<String>,
        data: Vec<Bytes>,
    ) -> Result<Self, PerceptionError> {
        let value = Self {
            mask_id,
            detection_id,
            track_id,
            x_offset,
            y_offset,
            width,
            height,
            encoding: encoding.into(),
            data,
        };
        value.validate()?;
        Ok(value)
    }

    pub fn to_record_batch(&self) -> Result<RecordBatch, PerceptionError> {
        self.validate()?;
        let schema = Arc::new(Schema::new(vec![
            Field::new("mask_id", list_type(DataType::Utf8), false),
            Field::new("detection_id", list_type(DataType::Utf8), false),
            Field::new("track_id", list_type(DataType::Utf8), false),
            Field::new("x_offset", list_type(DataType::UInt32), false),
            Field::new("y_offset", list_type(DataType::UInt32), false),
            Field::new("width", list_type(DataType::UInt32), false),
            Field::new("height", list_type(DataType::UInt32), false),
            Field::new("encoding", DataType::Utf8, false),
            Field::new("data", list_type(DataType::LargeBinary), false),
        ]));
        let columns: Vec<ArrayRef> = vec![
            Arc::new(string_list(&self.mask_id)),
            Arc::new(string_list(&self.detection_id)),
            Arc::new(string_list(&self.track_id)),
            Arc::new(u32_list(&self.x_offset)),
            Arc::new(u32_list(&self.y_offset)),
            Arc::new(u32_list(&self.width)),
            Arc::new(u32_list(&self.height)),
            Arc::new(StringArray::from(vec![self.encoding.as_str()])),
            Arc::new(binary_list(&self.data)),
        ];
        RecordBatch::try_new(schema, columns)
            .map_err(|error| PerceptionError::Arrow(error.to_string()))
    }

    pub fn from_record_batch(batch: &RecordBatch) -> Result<Self, PerceptionError> {
        if batch.num_rows() == 0 {
            return Err(PerceptionError::Invalid(
                "RecordBatch must contain one row".to_string(),
            ));
        }
        Self::new(
            read_string_list(batch, "mask_id").map_err(PerceptionError::Invalid)?,
            read_string_list(batch, "detection_id").map_err(PerceptionError::Invalid)?,
            read_string_list(batch, "track_id").map_err(PerceptionError::Invalid)?,
            read_u32_list(batch, "x_offset").map_err(PerceptionError::Invalid)?,
            read_u32_list(batch, "y_offset").map_err(PerceptionError::Invalid)?,
            read_u32_list(batch, "width").map_err(PerceptionError::Invalid)?,
            read_u32_list(batch, "height").map_err(PerceptionError::Invalid)?,
            read_string(batch, "encoding").map_err(PerceptionError::Invalid)?,
            read_binary_list(batch, "data").map_err(PerceptionError::Invalid)?,
        )
    }

    fn validate(&self) -> Result<(), PerceptionError> {
        if self.encoding != "mono8" {
            return Err(PerceptionError::Invalid(
                "encoding must be mono8".to_string(),
            ));
        }
        validate_unique("mask_id", &self.mask_id)?;
        let count = self.mask_id.len();
        for (name, actual) in [
            ("detection_id", self.detection_id.len()),
            ("track_id", self.track_id.len()),
            ("x_offset", self.x_offset.len()),
            ("y_offset", self.y_offset.len()),
            ("width", self.width.len()),
            ("height", self.height.len()),
            ("data", self.data.len()),
        ] {
            validate_len(name, actual, count)?;
        }
        for index in 0..count {
            let expected = (self.width[index] as usize)
                .checked_mul(self.height[index] as usize)
                .ok_or_else(|| {
                    PerceptionError::Invalid(format!(
                        "mask dimensions overflow usize at index {index}"
                    ))
                })?;
            if self.data[index].len() != expected {
                return Err(PerceptionError::Invalid(format!(
                    "data[{index}] length must equal width * height"
                )));
            }
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use bytes::Bytes;

    use super::SegmentationMaskSet;

    #[test]
    fn segmentation_mask_roundtrip() {
        let masks = SegmentationMaskSet::new(
            vec!["m0".into()],
            vec!["d0".into()],
            vec![String::new()],
            vec![4],
            vec![5],
            vec![2],
            vec![2],
            "mono8",
            vec![Bytes::from_static(&[0, 255, 255, 0])],
        )
        .unwrap();
        let batch = masks.to_record_batch().unwrap();
        assert_eq!(
            SegmentationMaskSet::from_record_batch(&batch).unwrap(),
            masks
        );
    }

    #[test]
    fn rejects_invalid_mask_length() {
        let result = SegmentationMaskSet::new(
            vec!["m0".into()],
            vec![String::new()],
            vec![String::new()],
            vec![0],
            vec![0],
            vec![2],
            vec![2],
            "mono8",
            vec![Bytes::from_static(&[0])],
        );
        assert!(result.is_err());
    }
}
