use std::sync::Arc;

use arrow_array::{Array, ArrayRef, Int32Array, Int8Array, LargeBinaryArray, RecordBatch};
use arrow_schema::{DataType, Field, Schema};
use bytes::Bytes;
use image as image_crate;
use ndarray::{Array3, ArrayView3};

/// 图像编码/格式，对齐 Python 版 `ImageEncoding`。
#[derive(Copy, Clone, Debug, Eq, PartialEq)]
#[repr(i8)]
pub enum ImageEncoding {
    Rgb8 = 0,
    Bgr8 = 1,
    Gray8 = 2,
    Jpeg = 3,
    Png = 4,
}

impl ImageEncoding {
    pub fn from_i8(v: i8) -> Self {
        match v {
            0 => ImageEncoding::Rgb8,
            1 => ImageEncoding::Bgr8,
            2 => ImageEncoding::Gray8,
            3 => ImageEncoding::Jpeg,
            4 => ImageEncoding::Png,
            _ => ImageEncoding::Rgb8,
        }
    }

    pub fn as_i8(self) -> i8 {
        self as i8
    }

    pub fn is_compressed(self) -> bool {
        matches!(self, ImageEncoding::Jpeg | ImageEncoding::Png)
    }
}

/// Rust 版统一图像消息。
///
/// - `width` / `height`: 图像尺寸
/// - `channels`: 原始像素通道数（压缩格式时可为 0）
/// - `encoding`: 像素或压缩格式
/// - `data`: 原始像素 bytes（H*W*C）或压缩 bitstream
#[derive(Clone, Debug)]
pub struct Image {
    pub width: i32,
    pub height: i32,
    pub channels: i8,
    pub encoding: ImageEncoding,
    pub data: Bytes,
}

impl Image {
    pub fn new(
        width: i32,
        height: i32,
        channels: i8,
        encoding: ImageEncoding,
        data: Bytes,
    ) -> Self {
        Self {
            width,
            height,
            channels,
            encoding,
            data,
        }
    }

    pub fn empty() -> Self {
        Self {
            width: 0,
            height: 0,
            channels: 0,
            encoding: ImageEncoding::Rgb8,
            data: Bytes::new(),
        }
    }

    pub fn is_compressed(&self) -> bool {
        self.encoding.is_compressed()
    }

    /// 将当前图像编码为单行 Arrow `RecordBatch`。
    ///
    /// schema: { width: int32, height: int32, channels: int8, encoding: int8, data: large_binary }
    pub fn to_record_batch(&self) -> RecordBatch {
        let width_arr = Int32Array::from(vec![self.width]);
        let height_arr = Int32Array::from(vec![self.height]);
        let channels_arr = Int8Array::from(vec![self.channels]);
        let encoding_arr = Int8Array::from(vec![self.encoding.as_i8()]);
        // 这里会复制一份数据以构造 LargeBinaryArray
        // 如果需要极致零拷贝，通常需要直接操作 arrow_buffer::Buffer，但 Bytes 类型已足够通用
        let data_arr = LargeBinaryArray::from_iter_values(std::iter::once(&self.data));

        let fields = vec![
            Field::new("width", DataType::Int32, false),
            Field::new("height", DataType::Int32, false),
            Field::new("channels", DataType::Int8, false),
            Field::new("encoding", DataType::Int8, false),
            Field::new("data", DataType::LargeBinary, false),
        ];
        let schema = Arc::new(Schema::new(fields));

        let columns: Vec<ArrayRef> = vec![
            Arc::new(width_arr),
            Arc::new(height_arr),
            Arc::new(channels_arr),
            Arc::new(encoding_arr),
            Arc::new(data_arr),
        ];

        RecordBatch::try_new(schema, columns).expect("valid Image record batch")
    }

    /// 从 Arrow `RecordBatch` 解析图像。
    ///
    /// - 当 `batch.num_rows() == 0` 时，返回空图像。
    /// - 当列缺失或类型不匹配时，返回空图像（避免在运行时 panic）。
    pub fn from_record_batch(batch: &RecordBatch) -> Self {
        if batch.num_rows() == 0 {
            return Self::empty();
        }

        let schema = batch.schema();

        macro_rules! get_column_as {
            ($col_name:expr, $ty:ty) => {{
                let idx = match schema.index_of($col_name) {
                    Ok(i) => i,
                    Err(_) => return Self::empty(),
                };
                let col = batch.column(idx);
                match col.as_any().downcast_ref::<$ty>() {
                    Some(arr) => arr,
                    None => return Self::empty(),
                }
            }};
        }

        let width_arr = get_column_as!("width", Int32Array);
        let height_arr = get_column_as!("height", Int32Array);
        let channels_arr = get_column_as!("channels", Int8Array);
        let encoding_arr = get_column_as!("encoding", Int8Array);
        let data_arr = get_column_as!("data", LargeBinaryArray);

        if width_arr.is_empty()
            || height_arr.is_empty()
            || channels_arr.is_empty()
            || encoding_arr.is_empty()
            || data_arr.is_empty()
        {
            return Self::empty();
        }

        let width = width_arr.value(0);
        let height = height_arr.value(0);
        let channels = channels_arr.value(0);
        let encoding = ImageEncoding::from_i8(encoding_arr.value(0));

        let data = Bytes::copy_from_slice(data_arr.value(0));

        Self {
            width,
            height,
            channels,
            encoding,
            data,
        }
    }

    /// 将图像转换为 `ndarray::Array3<u8>`（HWC）。
    ///
    /// - 对于 `rgb8` / `bgr8` / `gray8`：从原始像素数据 reshape。
    /// - 对于 `jpeg` / `png`：使用 `image` crate 解码后再转换为 ndarray。
    pub fn to_ndarray(&self) -> Result<Array3<u8>, ImageError> {
        if self.width <= 0 || self.height <= 0 {
            return Ok(Array3::zeros((0, 0, 0)));
        }

        if self.is_compressed() {
            return self.decode_compressed_to_ndarray();
        }

        let w = self.width as usize;
        let h = self.height as usize;
        let c = self.channels as usize;
        if c == 0 {
            return Err(ImageError::InvalidShape(
                "channels must be > 0 for raw encodings".to_string(),
            ));
        }

        let expected = w
            .checked_mul(h)
            .and_then(|v| v.checked_mul(c))
            .ok_or_else(|| {
                ImageError::InvalidShape("width * height * channels overflow".to_string())
            })?;

        if self.data.len() != expected {
            return Err(ImageError::InvalidShape(format!(
                "data length {} does not match width*height*channels={}",
                self.data.len(),
                expected
            )));
        }

        let arr = Array3::from_shape_vec((h, w, c), self.data.clone())
            .map_err(|e| ImageError::InvalidShape(e.to_string()))?;

        Ok(arr)
    }

    /// 从 ndarray (HWC, u8) 构建图像（仅支持原始像素编码）。
    pub fn from_ndarray(
        frame: ArrayView3<u8>,
        encoding: ImageEncoding,
    ) -> Result<Self, ImageError> {
        if matches!(encoding, ImageEncoding::Jpeg | ImageEncoding::Png) {
            return Err(ImageError::UnsupportedEncoding(
                "from_ndarray does not support compressed encodings (jpeg/png)".to_string(),
            ));
        }

        let (h, w, c) = frame.dim();

        let channels = c as i8;
        if channels <= 0 {
            return Err(ImageError::InvalidShape(
                "channels must be > 0".to_string(),
            ));
        }

        let (data, _offset) = frame.to_owned().into_raw_vec_and_offset();

        Ok(Self {
            width: w as i32,
            height: h as i32,
            channels,
            encoding,
            data: Bytes::from(data),
        })
    }

    /// 将当前图像转为 JPEG 字节流。
    ///
    /// - 若当前已为 jpeg 且 data 非空，则直接返回拷贝。
    /// - 其它格式会先解码为 ndarray，再重新编码为 jpeg。
    pub fn to_jpeg_bytes(&self, quality: u8) -> Result<Bytes, ImageError> {
        if matches!(self.encoding, ImageEncoding::Jpeg) && !self.data.is_empty() {
            return Ok(self.data.clone());
        }

        let arr = self.to_ndarray()?;
        if arr.is_empty() {
            return Ok(Bytes::new());
        }

        let (_, _, c) = arr.dim();
        let mut buf = Vec::new();

        // 对 bgr8 做通道翻转，统一为 RGB
        let mut rgb_arr = match (self.encoding, c) {
            (ImageEncoding::Bgr8, 3) => {
                let mut tmp = arr.to_owned();
                for pix in tmp.iter_mut().collect::<Vec<_>>().chunks_exact_mut(3) {
                    pix.swap(0, 2);
                }
                tmp
            }
            _ => arr,
        };

        // 灰度转 RGB
        let (h, w, c) = rgb_arr.dim();
        if c == 1 {
            let mut rgb = Array3::<u8>::zeros((h, w, 3));
            for y in 0..h {
                for x in 0..w {
                    let g = rgb_arr[(y, x, 0)];
                    rgb[(y, x, 0)] = g;
                    rgb[(y, x, 1)] = g;
                    rgb[(y, x, 2)] = g;
                }
            }
            rgb_arr = rgb;
        }

        let (h, w, _) = rgb_arr.dim();
        let (rgb_flat, _offset) = rgb_arr.into_raw_vec_and_offset();
        let img_buf = image_crate::RgbImage::from_raw(w as u32, h as u32, rgb_flat)
            .ok_or_else(|| ImageError::InvalidShape("failed to create RgbImage".to_string()))?;

        let mut encoder = image_crate::codecs::jpeg::JpegEncoder::new_with_quality(&mut buf, quality);
        encoder
            .encode(
                &img_buf,
                img_buf.width(),
                img_buf.height(),
                image_crate::ColorType::Rgb8.into(),
            )
            .map_err(ImageError::Encode)?;

        Ok(Bytes::from(buf))
    }

    fn decode_compressed_to_ndarray(&self) -> Result<Array3<u8>, ImageError> {
        if self.data.is_empty() {
            return Ok(Array3::zeros((0, 0, 0)));
        }

        let dyn_img =
            image_crate::load_from_memory(&self.data).map_err(ImageError::Decode)?;

        // 为了简化实现，这里区分灰度和彩色两类情况：
        // - 灰度：输出 (H, W, 1)
        // - 其它：统一转为 RGB，输出 (H, W, 3)
        use image_crate::ColorType;
        match dyn_img.color() {
            ColorType::L8 | ColorType::La8 => {
                let gray = dyn_img.to_luma8();
                let (w, h) = gray.dimensions();
                let (h_usize, w_usize) = (h as usize, w as usize);
                let data = gray.into_raw();
                let arr = Array3::from_shape_vec((h_usize, w_usize, 1), data)
                    .map_err(|e| ImageError::InvalidShape(e.to_string()))?;
                Ok(arr)
            }
            _ => {
                let rgb = dyn_img.to_rgb8();
                let (w, h) = rgb.dimensions();
                let (h_usize, w_usize) = (h as usize, w as usize);
                let data = rgb.into_raw();
                let arr = Array3::from_shape_vec((h_usize, w_usize, 3), data)
                    .map_err(|e| ImageError::InvalidShape(e.to_string()))?;
                Ok(arr)
            }
        }
    }
}

#[derive(Debug)]
pub enum ImageError {
    Decode(image_crate::ImageError),
    Encode(image_crate::ImageError),
    InvalidShape(String),
    UnsupportedEncoding(String),
}

impl std::fmt::Display for ImageError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ImageError::Decode(e) => write!(f, "decode error: {e}"),
            ImageError::Encode(e) => write!(f, "encode error: {e}"),
            ImageError::InvalidShape(msg) => write!(f, "invalid shape: {msg}"),
            ImageError::UnsupportedEncoding(msg) => write!(f, "unsupported encoding: {msg}"),
        }
    }
}

impl std::error::Error for ImageError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        match self {
            ImageError::Decode(e) => Some(e),
            ImageError::Encode(e) => Some(e),
            ImageError::InvalidShape(_) => None,
            ImageError::UnsupportedEncoding(_) => None,
        }
    }
}

impl From<image_crate::ImageError> for ImageError {
    fn from(e: image_crate::ImageError) -> Self {
        ImageError::Decode(e)
    }
}


#[cfg(test)]
mod tests {
    use super::{Image, ImageEncoding};
    use ndarray::{array, Array3};

    #[test]
    fn raw_rgb_roundtrip_record_batch_and_ndarray() {
        // 构造一个 2x2 RGB 小图
        let frame: Array3<u8> = array![
            [[10u8, 20, 30], [40, 50, 60]],
            [[70u8, 80, 90], [100, 110, 120]]
        ];
        let img = Image::from_ndarray(frame.view(), ImageEncoding::Rgb8).unwrap();

        // Image -> RecordBatch
        let batch = img.to_record_batch();
        assert_eq!(batch.num_rows(), 1);

        // RecordBatch -> Image
        let img2 = Image::from_record_batch(&batch);
        assert_eq!(img2.width, img.width);
        assert_eq!(img2.height, img.height);
        assert_eq!(img2.channels, img.channels);
        assert_eq!(img2.encoding, img.encoding);
        assert_eq!(img2.data, img.data);

        // 再转回 ndarray，检查内容一致
        let frame2 = img2.to_ndarray().unwrap();
        assert_eq!(frame2.shape(), frame.shape());
        assert_eq!(frame2.as_slice().unwrap(), frame.as_slice().unwrap());
    }

    #[test]
    fn gray_roundtrip_preserves_shape() {
        // 2x2 灰度图，channels = 1
        let frame: Array3<u8> = array![
            [[0u8], [128u8]],
            [[200u8], [255u8]],
        ];
        let img = Image::from_ndarray(frame.view(), ImageEncoding::Gray8).unwrap();

        let batch = img.to_record_batch();
        let img2 = Image::from_record_batch(&batch);

        let frame2 = img2.to_ndarray().unwrap();
        assert_eq!(frame2.shape(), frame.shape());
        assert_eq!(frame2.as_slice().unwrap(), frame.as_slice().unwrap());
    }

    #[test]
    fn jpeg_roundtrip_to_ndarray_has_correct_shape() {
        // 构造一个 2x2 RGB 图像
        let frame: Array3<u8> = array![
            [[10u8, 20, 30], [40, 50, 60]],
            [[70u8, 80, 90], [100, 110, 120]]
        ];
        let img = Image::from_ndarray(frame.view(), ImageEncoding::Rgb8).unwrap();

        let jpeg_bytes = img.to_jpeg_bytes(90).unwrap();
        assert!(!jpeg_bytes.is_empty());

        // 构造压缩编码的 Image（channels 对压缩格式可以为 0）
        let compressed = Image::new(
            img.width,
            img.height,
            0,
            ImageEncoding::Jpeg,
            jpeg_bytes,
        );

        let decoded = compressed.to_ndarray().unwrap();
        // 解码后统一为 HWC, 3 通道 RGB
        assert_eq!(decoded.shape(), &[img.height as usize, img.width as usize, 3]);
    }
}


