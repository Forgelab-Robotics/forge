use std::sync::Arc;

use arrow_array::{Array, ArrayRef, LargeBinaryArray, RecordBatch, StringArray, UInt32Array};
use arrow_schema::{DataType, Field, Schema};
use bytes::Bytes;
use image as image_crate;
use ndarray::{Array2, Array3, ArrayView2, ArrayView3};

#[derive(Clone, Debug, PartialEq)]
pub struct Image {
    pub height: u32,
    pub width: u32,
    pub encoding: String,
    pub step: u32,
    pub data: Bytes,
}

#[derive(Clone, Debug, PartialEq)]
pub struct CompressedImage {
    pub format: String,
    pub data: Bytes,
}

impl Image {
    pub fn new(
        height: u32,
        width: u32,
        encoding: impl Into<String>,
        step: u32,
        data: Bytes,
    ) -> Result<Self, ImageError> {
        let value = Self {
            height,
            width,
            encoding: encoding.into(),
            step,
            data,
        };
        value.validate()?;
        Ok(value)
    }

    pub fn to_record_batch(&self) -> Result<RecordBatch, ImageError> {
        self.validate()?;
        let schema = Arc::new(Schema::new(vec![
            Field::new("height", DataType::UInt32, false),
            Field::new("width", DataType::UInt32, false),
            Field::new("encoding", DataType::Utf8, false),
            Field::new("step", DataType::UInt32, false),
            Field::new("data", DataType::LargeBinary, false),
        ]));
        let columns: Vec<ArrayRef> = vec![
            Arc::new(UInt32Array::from(vec![self.height])),
            Arc::new(UInt32Array::from(vec![self.width])),
            Arc::new(StringArray::from(vec![self.encoding.as_str()])),
            Arc::new(UInt32Array::from(vec![self.step])),
            Arc::new(LargeBinaryArray::from_iter_values(std::iter::once(
                &self.data,
            ))),
        ];
        RecordBatch::try_new(schema, columns).map_err(|e| ImageError::Arrow(e.to_string()))
    }

    pub fn from_record_batch(batch: &RecordBatch) -> Result<Self, ImageError> {
        if batch.num_rows() == 0 {
            return Err(ImageError::Invalid(
                "RecordBatch must contain one row".to_string(),
            ));
        }
        let value = Self {
            height: read_u32(batch, "height")?,
            width: read_u32(batch, "width")?,
            encoding: read_string(batch, "encoding")?,
            step: read_u32(batch, "step")?,
            data: read_binary(batch, "data")?,
        };
        value.validate()?;
        Ok(value)
    }

    pub fn from_rgb8_ndarray(frame: ArrayView3<u8>) -> Result<Self, ImageError> {
        let (height, width, channels) = frame.dim();
        if channels != 3 {
            return Err(ImageError::Invalid("rgb8 expects 3 channels".to_string()));
        }
        let (data, _offset) = frame.to_owned().into_raw_vec_and_offset();
        Self::new(
            height as u32,
            width as u32,
            "rgb8",
            (width * 3) as u32,
            Bytes::from(data),
        )
    }

    pub fn to_rgb8_ndarray(&self) -> Result<Array3<u8>, ImageError> {
        if self.encoding != "rgb8" {
            return Err(ImageError::UnsupportedEncoding(
                "to_rgb8_ndarray requires rgb8".to_string(),
            ));
        }
        let expected_step = self.width as usize * 3;
        if self.step as usize != expected_step {
            return Err(ImageError::Invalid(
                "to_rgb8_ndarray requires tightly packed rows".to_string(),
            ));
        }
        Array3::from_shape_vec(
            (self.height as usize, self.width as usize, 3),
            self.data.to_vec(),
        )
        .map_err(|e| ImageError::Invalid(e.to_string()))
    }

    pub fn from_16uc1_ndarray(frame: ArrayView2<u16>) -> Result<Self, ImageError> {
        let (height, width) = frame.dim();
        let mut data = Vec::with_capacity(height * width * 2);
        for &value in frame.iter() {
            data.extend_from_slice(&value.to_le_bytes());
        }
        Self::new(
            height as u32,
            width as u32,
            "16UC1",
            (width * 2) as u32,
            Bytes::from(data),
        )
    }

    pub fn to_16uc1_ndarray(&self) -> Result<Array2<u16>, ImageError> {
        if self.encoding != "16UC1" {
            return Err(ImageError::UnsupportedEncoding(
                "to_16uc1_ndarray requires 16UC1".to_string(),
            ));
        }
        let expected_step = self.width as usize * 2;
        if self.step as usize != expected_step {
            return Err(ImageError::Invalid(
                "to_16uc1_ndarray requires tightly packed rows".to_string(),
            ));
        }
        let mut values = Vec::with_capacity(self.height as usize * self.width as usize);
        for chunk in self.data.chunks_exact(2) {
            values.push(u16::from_le_bytes([chunk[0], chunk[1]]));
        }
        Array2::from_shape_vec((self.height as usize, self.width as usize), values)
            .map_err(|e| ImageError::Invalid(e.to_string()))
    }

    fn validate(&self) -> Result<(), ImageError> {
        let bytes_per_pixel = bytes_per_pixel(&self.encoding)?;
        let minimum_step = self.width as usize * bytes_per_pixel;
        if (self.step as usize) < minimum_step {
            return Err(ImageError::Invalid(format!(
                "step {} is smaller than width * bytes_per_pixel {}",
                self.step, minimum_step
            )));
        }
        let expected = self.step as usize * self.height as usize;
        if self.data.len() != expected {
            return Err(ImageError::Invalid(format!(
                "data length {} must equal step * height {}",
                self.data.len(),
                expected
            )));
        }
        Ok(())
    }
}

impl CompressedImage {
    pub fn new(format: impl Into<String>, data: Bytes) -> Result<Self, ImageError> {
        let value = Self {
            format: format.into(),
            data,
        };
        if value.format.is_empty() {
            return Err(ImageError::Invalid("format must be non-empty".to_string()));
        }
        Ok(value)
    }

    pub fn to_record_batch(&self) -> Result<RecordBatch, ImageError> {
        let schema = Arc::new(Schema::new(vec![
            Field::new("format", DataType::Utf8, false),
            Field::new("data", DataType::LargeBinary, false),
        ]));
        let columns: Vec<ArrayRef> = vec![
            Arc::new(StringArray::from(vec![self.format.as_str()])),
            Arc::new(LargeBinaryArray::from_iter_values(std::iter::once(
                &self.data,
            ))),
        ];
        RecordBatch::try_new(schema, columns).map_err(|e| ImageError::Arrow(e.to_string()))
    }

    pub fn from_record_batch(batch: &RecordBatch) -> Result<Self, ImageError> {
        if batch.num_rows() == 0 {
            return Err(ImageError::Invalid(
                "RecordBatch must contain one row".to_string(),
            ));
        }
        Self::new(read_string(batch, "format")?, read_binary(batch, "data")?)
    }

    pub fn to_rgb8_ndarray(&self) -> Result<Array3<u8>, ImageError> {
        if self.data.is_empty() {
            return Ok(Array3::zeros((0, 0, 0)));
        }
        let dynamic = image_crate::load_from_memory(&self.data).map_err(ImageError::Decode)?;
        let rgb = dynamic.to_rgb8();
        let (width, height) = rgb.dimensions();
        Array3::from_shape_vec((height as usize, width as usize, 3), rgb.into_raw())
            .map_err(|e| ImageError::Invalid(e.to_string()))
    }
}

fn bytes_per_pixel(encoding: &str) -> Result<usize, ImageError> {
    match encoding {
        "rgb8" | "bgr8" => Ok(3),
        "mono8" | "8UC1" => Ok(1),
        "16UC1" => Ok(2),
        "32SC1" | "32FC1" => Ok(4),
        _ => Err(ImageError::UnsupportedEncoding(encoding.to_string())),
    }
}

fn read_u32(batch: &RecordBatch, name: &str) -> Result<u32, ImageError> {
    let array = column_as::<UInt32Array>(batch, name)?;
    Ok(array.value(0))
}

fn read_string(batch: &RecordBatch, name: &str) -> Result<String, ImageError> {
    let array = column_as::<StringArray>(batch, name)?;
    Ok(array.value(0).to_string())
}

fn read_binary(batch: &RecordBatch, name: &str) -> Result<Bytes, ImageError> {
    let array = column_as::<LargeBinaryArray>(batch, name)?;
    Ok(Bytes::copy_from_slice(array.value(0)))
}

fn column_as<'a, T: 'static + Array>(
    batch: &'a RecordBatch,
    name: &str,
) -> Result<&'a T, ImageError> {
    let idx = batch
        .schema()
        .index_of(name)
        .map_err(|_| ImageError::Invalid(format!("missing {name} column")))?;
    batch
        .column(idx)
        .as_any()
        .downcast_ref::<T>()
        .ok_or_else(|| ImageError::Invalid(format!("{name} column has unexpected type")))
}

#[derive(Debug)]
pub enum ImageError {
    Arrow(String),
    Decode(image_crate::ImageError),
    Invalid(String),
    UnsupportedEncoding(String),
}

impl std::fmt::Display for ImageError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ImageError::Arrow(msg) => write!(f, "arrow error: {msg}"),
            ImageError::Decode(e) => write!(f, "decode error: {e}"),
            ImageError::Invalid(msg) => write!(f, "invalid image message: {msg}"),
            ImageError::UnsupportedEncoding(msg) => write!(f, "unsupported encoding: {msg}"),
        }
    }
}

impl std::error::Error for ImageError {}

#[cfg(test)]
mod tests {
    use super::{CompressedImage, Image};
    use bytes::Bytes;
    use ndarray::{Array2, Array3, array};

    #[test]
    fn rgb8_roundtrip_record_batch_and_ndarray() {
        let frame: Array3<u8> = array![
            [[10u8, 20, 30], [40, 50, 60]],
            [[70u8, 80, 90], [100, 110, 120]]
        ];
        let image = Image::from_rgb8_ndarray(frame.view()).unwrap();
        let batch = image.to_record_batch().unwrap();
        let back = Image::from_record_batch(&batch).unwrap();
        assert_eq!(back, image);
        let frame2 = back.to_rgb8_ndarray().unwrap();
        assert_eq!(frame2.as_slice().unwrap(), frame.as_slice().unwrap());
    }

    #[test]
    fn depth_16uc1_roundtrip_record_batch_and_ndarray() {
        let frame: Array2<u16> = array![[100u16, 200], [300, 400]];
        let image = Image::from_16uc1_ndarray(frame.view()).unwrap();
        let batch = image.to_record_batch().unwrap();
        let back = Image::from_record_batch(&batch).unwrap();
        assert_eq!(back, image);
        let frame2 = back.to_16uc1_ndarray().unwrap();
        assert_eq!(frame2.as_slice().unwrap(), frame.as_slice().unwrap());
    }

    #[test]
    fn rejects_invalid_data_length() {
        let result = Image::new(2, 2, "rgb8", 6, Bytes::from_static(b"bad"));
        assert!(result.is_err());
    }

    #[test]
    fn compressed_image_roundtrip_record_batch() {
        let image =
            CompressedImage::new("jpeg", Bytes::from_static(&[0xff, 0xd8, 0xff, 0xd9])).unwrap();
        let batch = image.to_record_batch().unwrap();
        let back = CompressedImage::from_record_batch(&batch).unwrap();
        assert_eq!(back, image);
    }
}
