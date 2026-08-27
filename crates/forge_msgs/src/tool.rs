use std::{collections::HashSet, sync::Arc};

use arrow_array::{Array, ArrayRef, Int64Array, RecordBatch, StringArray};
use arrow_schema::{DataType, Field, Schema};
use serde::de::{self, DeserializeSeed, MapAccess, SeqAccess, Visitor};

pub const TOOL_ENDPOINT_PROTOCOL: &str = "forge.tool.endpoint/v1alpha1";
pub const MAX_SAFE_JSON_INTEGER: i64 = 9_007_199_254_740_991;
const MAX_JSON_NESTING_DEPTH: usize = 64;
pub const TOOL_MESSAGE_TYPES: [&str; 14] = [
    "endpoint.register",
    "endpoint.unregister",
    "endpoint.registry.response",
    "endpoint.status",
    "tool.invoke.request",
    "tool.invoke.response",
    "tool.status.request",
    "tool.status.response",
    "tool.result.request",
    "tool.result.response",
    "tool.control.request",
    "tool.control.response",
    "tool.event",
    "tool.error",
];

const MANAGEMENT_MESSAGE_TYPES: [&str; 4] = [
    "endpoint.register",
    "endpoint.unregister",
    "endpoint.registry.response",
    "endpoint.status",
];
const MANAGEMENT_MESSAGE_TYPES_REQUIRING_REQUEST_ID: [&str; 3] = [
    "endpoint.register",
    "endpoint.unregister",
    "endpoint.registry.response",
];
const EVENT_MESSAGE_TYPE: &str = "tool.event";

/// Single-row Arrow carrier for one Forge ToolEndpoint logical message.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ToolMessage {
    pub protocol: String,
    pub message_type: String,
    pub request_id: Option<String>,
    pub invocation_id: Option<String>,
    pub attempt_id: Option<String>,
    pub endpoint_id: String,
    pub endpoint_instance_id: Option<String>,
    pub operation: Option<String>,
    pub sequence: Option<i64>,
    pub payload_json: String,
}

impl ToolMessage {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        message_type: impl Into<String>,
        request_id: Option<String>,
        invocation_id: Option<String>,
        attempt_id: Option<String>,
        endpoint_id: impl Into<String>,
        endpoint_instance_id: Option<String>,
        operation: Option<String>,
        sequence: Option<i64>,
        payload_json: impl Into<String>,
    ) -> Result<Self, ToolMessageError> {
        let value = Self {
            protocol: TOOL_ENDPOINT_PROTOCOL.to_string(),
            message_type: message_type.into(),
            request_id,
            invocation_id,
            attempt_id,
            endpoint_id: endpoint_id.into(),
            endpoint_instance_id,
            operation,
            sequence,
            payload_json: payload_json.into(),
        };
        value.validate()?;
        Ok(value)
    }

    /// Return the exact ordered Arrow schema for a `ToolMessage` carrier.
    pub fn schema() -> Schema {
        tool_message_schema()
    }

    pub fn validate(&self) -> Result<(), ToolMessageError> {
        if self.protocol != TOOL_ENDPOINT_PROTOCOL {
            return invalid(format!("protocol must equal {TOOL_ENDPOINT_PROTOCOL:?}"));
        }
        if !TOOL_MESSAGE_TYPES.contains(&self.message_type.as_str()) {
            return invalid(format!("unsupported message_type: {:?}", self.message_type));
        }

        validate_required_string("endpoint_id", &self.endpoint_id)?;
        validate_optional_string("endpoint_instance_id", self.endpoint_instance_id.as_deref())?;
        if self.endpoint_instance_id.is_none()
            && MANAGEMENT_MESSAGE_TYPES.contains(&self.message_type.as_str())
        {
            return invalid(
                "endpoint_instance_id must be non-null for endpoint management messages",
            );
        }
        validate_optional_string("request_id", self.request_id.as_deref())?;
        validate_optional_string("invocation_id", self.invocation_id.as_deref())?;
        validate_optional_string("attempt_id", self.attempt_id.as_deref())?;
        validate_optional_string("operation", self.operation.as_deref())?;

        if MANAGEMENT_MESSAGE_TYPES.contains(&self.message_type.as_str()) {
            if MANAGEMENT_MESSAGE_TYPES_REQUIRING_REQUEST_ID.contains(&self.message_type.as_str())
                && self.request_id.is_none()
            {
                return invalid("request_id must be non-null for endpoint management exchanges");
            }
            if self.message_type == "endpoint.status" && self.request_id.is_some() {
                return invalid("request_id must be null for unsolicited endpoint.status");
            }
            for (field_name, is_present) in [
                ("invocation_id", self.invocation_id.is_some()),
                ("attempt_id", self.attempt_id.is_some()),
                ("operation", self.operation.is_some()),
                ("sequence", self.sequence.is_some()),
            ] {
                if is_present {
                    return invalid(format!(
                        "{field_name} must be null for endpoint management messages"
                    ));
                }
            }
        } else {
            for (field_name, is_present) in [
                ("invocation_id", self.invocation_id.is_some()),
                ("attempt_id", self.attempt_id.is_some()),
                ("operation", self.operation.is_some()),
            ] {
                if !is_present {
                    return invalid(format!(
                        "{field_name} must be non-null for Tool execution messages"
                    ));
                }
            }

            if self.message_type == EVENT_MESSAGE_TYPE {
                if self.request_id.is_some() {
                    return invalid("request_id must be null for tool.event");
                }
            } else if self.request_id.is_none() {
                return invalid(
                    "request_id must be non-null for non-event Tool execution messages",
                );
            }
        }

        if self.message_type == EVENT_MESSAGE_TYPE {
            let Some(sequence) = self.sequence else {
                return invalid("sequence must be non-null for tool.event");
            };
            if !(0..=MAX_SAFE_JSON_INTEGER).contains(&sequence) {
                return invalid(format!("sequence must be in [0, {MAX_SAFE_JSON_INTEGER}]"));
            }
        } else if self.sequence.is_some() {
            return invalid("sequence must be null for non-event messages");
        }

        validate_json_object("payload_json", &self.payload_json)
    }

    pub fn to_record_batch(&self) -> Result<RecordBatch, ToolMessageError> {
        self.validate()?;

        let columns: Vec<ArrayRef> = vec![
            Arc::new(StringArray::from(vec![self.protocol.as_str()])),
            Arc::new(StringArray::from(vec![self.message_type.as_str()])),
            Arc::new(StringArray::from(vec![self.request_id.as_deref()])),
            Arc::new(StringArray::from(vec![self.invocation_id.as_deref()])),
            Arc::new(StringArray::from(vec![self.attempt_id.as_deref()])),
            Arc::new(StringArray::from(vec![self.endpoint_id.as_str()])),
            Arc::new(StringArray::from(vec![
                self.endpoint_instance_id.as_deref(),
            ])),
            Arc::new(StringArray::from(vec![self.operation.as_deref()])),
            Arc::new(Int64Array::from(vec![self.sequence])),
            Arc::new(StringArray::from(vec![self.payload_json.as_str()])),
        ];

        RecordBatch::try_new(Arc::new(Self::schema()), columns)
            .map_err(|error| ToolMessageError::Arrow(error.to_string()))
    }

    pub fn from_record_batch(batch: &RecordBatch) -> Result<Self, ToolMessageError> {
        validate_record_batch(batch)?;

        let value = Self {
            protocol: read_required_string(batch, 0, "protocol")?,
            message_type: read_required_string(batch, 1, "message_type")?,
            request_id: read_optional_string(batch, 2, "request_id")?,
            invocation_id: read_optional_string(batch, 3, "invocation_id")?,
            attempt_id: read_optional_string(batch, 4, "attempt_id")?,
            endpoint_id: read_required_string(batch, 5, "endpoint_id")?,
            endpoint_instance_id: read_optional_string(batch, 6, "endpoint_instance_id")?,
            operation: read_optional_string(batch, 7, "operation")?,
            sequence: read_optional_i64(batch, 8, "sequence")?,
            payload_json: read_required_string(batch, 9, "payload_json")?,
        };
        value.validate()?;
        Ok(value)
    }
}

pub fn tool_message_schema() -> Schema {
    Schema::new(vec![
        Field::new("protocol", DataType::Utf8, false),
        Field::new("message_type", DataType::Utf8, false),
        Field::new("request_id", DataType::Utf8, true),
        Field::new("invocation_id", DataType::Utf8, true),
        Field::new("attempt_id", DataType::Utf8, true),
        Field::new("endpoint_id", DataType::Utf8, false),
        Field::new("endpoint_instance_id", DataType::Utf8, true),
        Field::new("operation", DataType::Utf8, true),
        Field::new("sequence", DataType::Int64, true),
        Field::new("payload_json", DataType::Utf8, false),
    ])
}

fn validate_record_batch(batch: &RecordBatch) -> Result<(), ToolMessageError> {
    if batch.num_rows() != 1 {
        return invalid("ToolMessage RecordBatch must contain exactly one row");
    }

    let actual = batch.schema();
    let expected = tool_message_schema();
    let schema_matches = actual.fields().len() == expected.fields().len()
        && actual
            .fields()
            .iter()
            .zip(expected.fields())
            .all(|(actual, expected)| {
                actual.name() == expected.name()
                    && actual.data_type() == expected.data_type()
                    && actual.is_nullable() == expected.is_nullable()
            });
    if !schema_matches {
        return invalid("ToolMessage RecordBatch schema must exactly match ToolMessage::schema()");
    }
    Ok(())
}

fn read_required_string(
    batch: &RecordBatch,
    index: usize,
    name: &str,
) -> Result<String, ToolMessageError> {
    let array = batch
        .column(index)
        .as_any()
        .downcast_ref::<StringArray>()
        .ok_or_else(|| ToolMessageError::Invalid(format!("{name} column must be utf8")))?;
    if array.is_null(0) {
        return invalid(format!("{name} must not be null"));
    }
    Ok(array.value(0).to_string())
}

fn read_optional_string(
    batch: &RecordBatch,
    index: usize,
    name: &str,
) -> Result<Option<String>, ToolMessageError> {
    let array = batch
        .column(index)
        .as_any()
        .downcast_ref::<StringArray>()
        .ok_or_else(|| ToolMessageError::Invalid(format!("{name} column must be utf8")))?;
    Ok((!array.is_null(0)).then(|| array.value(0).to_string()))
}

fn read_optional_i64(
    batch: &RecordBatch,
    index: usize,
    name: &str,
) -> Result<Option<i64>, ToolMessageError> {
    let array = batch
        .column(index)
        .as_any()
        .downcast_ref::<Int64Array>()
        .ok_or_else(|| ToolMessageError::Invalid(format!("{name} column must be int64")))?;
    Ok((!array.is_null(0)).then(|| array.value(0)))
}

fn validate_required_string(name: &str, value: &str) -> Result<(), ToolMessageError> {
    if value.trim().is_empty() {
        return invalid(format!("{name} must be non-empty"));
    }
    Ok(())
}

fn validate_optional_string(name: &str, value: Option<&str>) -> Result<(), ToolMessageError> {
    if value.is_some_and(|value| value.trim().is_empty()) {
        return invalid(format!("{name} must be non-empty when present"));
    }
    Ok(())
}

fn validate_json_object(name: &str, value: &str) -> Result<(), ToolMessageError> {
    let strict_json_error = |error: serde_json::Error| {
        ToolMessageError::Invalid(format!("{name} must be valid strict JSON: {error}"))
    };
    let mut deserializer = serde_json::Deserializer::from_str(value);
    let root_kind = StrictJsonSeed { depth: 0 }
        .deserialize(&mut deserializer)
        .map_err(&strict_json_error)?;
    deserializer.end().map_err(strict_json_error)?;

    if root_kind != JsonValueKind::Object {
        return invalid(format!("{name} must be a JSON object"));
    }
    Ok(())
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum JsonValueKind {
    Object,
    Other,
}

struct StrictJsonSeed {
    depth: usize,
}

impl<'de> DeserializeSeed<'de> for StrictJsonSeed {
    type Value = JsonValueKind;

    fn deserialize<D>(self, deserializer: D) -> Result<Self::Value, D::Error>
    where
        D: serde::Deserializer<'de>,
    {
        if self.depth > MAX_JSON_NESTING_DEPTH {
            return Err(de::Error::custom(format!(
                "JSON nesting exceeds {MAX_JSON_NESTING_DEPTH}"
            )));
        }
        deserializer.deserialize_any(StrictJsonVisitor { depth: self.depth })
    }
}

struct StrictJsonVisitor {
    depth: usize,
}

impl<'de> Visitor<'de> for StrictJsonVisitor {
    type Value = JsonValueKind;

    fn expecting(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str("a strict JSON value")
    }

    fn visit_bool<E>(self, _value: bool) -> Result<Self::Value, E> {
        Ok(JsonValueKind::Other)
    }

    fn visit_i64<E>(self, value: i64) -> Result<Self::Value, E>
    where
        E: de::Error,
    {
        if !(-MAX_SAFE_JSON_INTEGER..=MAX_SAFE_JSON_INTEGER).contains(&value) {
            return Err(E::custom(format!(
                "integer exceeds interoperable range ±{MAX_SAFE_JSON_INTEGER}"
            )));
        }
        Ok(JsonValueKind::Other)
    }

    fn visit_u64<E>(self, value: u64) -> Result<Self::Value, E>
    where
        E: de::Error,
    {
        if value > MAX_SAFE_JSON_INTEGER as u64 {
            return Err(E::custom(format!(
                "integer exceeds interoperable range ±{MAX_SAFE_JSON_INTEGER}"
            )));
        }
        Ok(JsonValueKind::Other)
    }

    fn visit_f64<E>(self, value: f64) -> Result<Self::Value, E>
    where
        E: de::Error,
    {
        if !value.is_finite() {
            return Err(E::custom("floating-point values must be finite"));
        }
        Ok(JsonValueKind::Other)
    }

    fn visit_str<E>(self, _value: &str) -> Result<Self::Value, E> {
        Ok(JsonValueKind::Other)
    }

    fn visit_unit<E>(self) -> Result<Self::Value, E> {
        Ok(JsonValueKind::Other)
    }

    fn visit_seq<A>(self, mut sequence: A) -> Result<Self::Value, A::Error>
    where
        A: SeqAccess<'de>,
    {
        while sequence
            .next_element_seed(StrictJsonSeed {
                depth: self.depth + 1,
            })?
            .is_some()
        {}
        Ok(JsonValueKind::Other)
    }

    fn visit_map<A>(self, mut object: A) -> Result<Self::Value, A::Error>
    where
        A: MapAccess<'de>,
    {
        let mut keys = HashSet::new();
        while let Some(key) = object.next_key::<String>()? {
            if !keys.insert(key.clone()) {
                return Err(de::Error::custom(format!(
                    "duplicate JSON object key: {key:?}"
                )));
            }
            object.next_value_seed(StrictJsonSeed {
                depth: self.depth + 1,
            })?;
        }
        Ok(JsonValueKind::Object)
    }
}

fn invalid<T>(message: impl Into<String>) -> Result<T, ToolMessageError> {
    Err(ToolMessageError::Invalid(message.into()))
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ToolMessageError {
    Arrow(String),
    Invalid(String),
}

impl std::fmt::Display for ToolMessageError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Arrow(message) => write!(formatter, "arrow error: {message}"),
            Self::Invalid(message) => write!(formatter, "invalid ToolMessage: {message}"),
        }
    }
}

impl std::error::Error for ToolMessageError {}

#[cfg(test)]
mod tests {
    use std::{collections::HashMap, sync::Arc};

    use arrow_array::{Array, ArrayRef, Int64Array, RecordBatch, StringArray};
    use arrow_schema::{DataType, Field, Schema};

    use super::{
        MAX_SAFE_JSON_INTEGER, TOOL_ENDPOINT_PROTOCOL, TOOL_MESSAGE_TYPES, ToolMessage,
        tool_message_schema,
    };

    fn execution_message(message_type: &str) -> ToolMessage {
        ToolMessage::new(
            message_type,
            Some("request-1".to_string()),
            Some("invocation-1".to_string()),
            Some("attempt-1".to_string()),
            "endpoint-1",
            Some("instance-1".to_string()),
            Some("move".to_string()),
            None,
            r#"{"speed":0.5}"#,
        )
        .unwrap()
    }

    fn event_message(sequence: i64) -> ToolMessage {
        ToolMessage::new(
            "tool.event",
            None,
            Some("invocation-1".to_string()),
            Some("attempt-1".to_string()),
            "endpoint-1",
            Some("instance-1".to_string()),
            Some("move".to_string()),
            Some(sequence),
            r#"{"kind":"progress"}"#,
        )
        .unwrap()
    }

    fn management_message(message_type: &str) -> ToolMessage {
        ToolMessage::new(
            message_type,
            Some("management-request-1".to_string()),
            None,
            None,
            "endpoint-1",
            Some("instance-1".to_string()),
            None,
            None,
            "{}",
        )
        .unwrap()
    }

    fn endpoint_status_message() -> ToolMessage {
        ToolMessage::new(
            "endpoint.status",
            None,
            None,
            None,
            "endpoint-1",
            Some("instance-1".to_string()),
            None,
            None,
            "{}",
        )
        .unwrap()
    }

    fn assert_payload_rejected(payload_json: impl Into<String>) {
        let mut message = execution_message("tool.invoke.request");
        message.payload_json = payload_json.into();
        assert!(
            message.validate().is_err(),
            "payload_json was unexpectedly accepted: {:?}",
            message.payload_json
        );
    }

    fn nested_array_payload(depth: usize) -> String {
        assert!(depth > 0);
        let mut nested = "[]".to_string();
        for _ in 1..depth {
            nested = format!("[{nested}]");
        }
        format!(r#"{{"value":{nested}}}"#)
    }

    #[test]
    fn execution_message_roundtrips() {
        let message = execution_message("tool.invoke.request");
        let batch = message.to_record_batch().unwrap();
        let decoded = ToolMessage::from_record_batch(&batch).unwrap();

        assert_eq!(decoded, message);
        assert_eq!(batch.num_rows(), 1);
        assert_eq!(batch.num_columns(), 10);
    }

    #[test]
    fn tool_messages_without_instance_roundtrip_as_null() {
        for message_type in TOOL_MESSAGE_TYPES {
            if !message_type.starts_with("tool.") {
                continue;
            }
            let mut message = if message_type == "tool.event" {
                event_message(1)
            } else {
                execution_message(message_type)
            };
            message.endpoint_instance_id = None;

            let batch = message.to_record_batch().unwrap();

            assert!(batch.column(6).is_null(0), "{message_type}");
            assert_eq!(
                ToolMessage::from_record_batch(&batch).unwrap(),
                message,
                "{message_type}"
            );
        }
    }

    #[test]
    fn event_requires_null_request_and_safe_sequence_and_roundtrips() {
        for sequence in [0, MAX_SAFE_JSON_INTEGER] {
            let message = event_message(sequence);
            let batch = message.to_record_batch().unwrap();

            assert!(batch.column(2).is_null(0));
            assert_eq!(
                batch
                    .column(8)
                    .as_any()
                    .downcast_ref::<Int64Array>()
                    .unwrap()
                    .value(0),
                sequence
            );
            assert_eq!(ToolMessage::from_record_batch(&batch).unwrap(), message);
        }
    }

    #[test]
    fn management_exchanges_require_request_id_and_clear_execution_correlation() {
        for message_type in [
            "endpoint.register",
            "endpoint.unregister",
            "endpoint.registry.response",
        ] {
            let message = management_message(message_type);
            let batch = message.to_record_batch().unwrap();

            assert!(!batch.column(2).is_null(0));
            for index in [3, 4, 7, 8] {
                assert!(batch.column(index).is_null(0));
            }
            assert_eq!(ToolMessage::from_record_batch(&batch).unwrap(), message);
        }

        let endpoint_status = endpoint_status_message();
        let batch = endpoint_status.to_record_batch().unwrap();
        assert!(batch.column(2).is_null(0));
        assert_eq!(
            ToolMessage::from_record_batch(&batch).unwrap(),
            endpoint_status
        );
    }

    #[test]
    fn protocol_and_message_type_registry_match_contract() {
        assert_eq!(TOOL_ENDPOINT_PROTOCOL, "forge.tool.endpoint/v1alpha1");
        assert_eq!(
            TOOL_MESSAGE_TYPES,
            [
                "endpoint.register",
                "endpoint.unregister",
                "endpoint.registry.response",
                "endpoint.status",
                "tool.invoke.request",
                "tool.invoke.response",
                "tool.status.request",
                "tool.status.response",
                "tool.result.request",
                "tool.result.response",
                "tool.control.request",
                "tool.control.response",
                "tool.event",
                "tool.error",
            ]
        );

        for message_type in TOOL_MESSAGE_TYPES {
            let message = if message_type == "endpoint.status" {
                endpoint_status_message()
            } else if message_type.starts_with("endpoint.") {
                management_message(message_type)
            } else if message_type == "tool.event" {
                event_message(1)
            } else {
                execution_message(message_type)
            };
            assert!(message.validate().is_ok());
        }

        let mut invalid_protocol = execution_message("tool.invoke.request");
        invalid_protocol.protocol = "forge.tool.endpoint/v2".to_string();
        assert!(invalid_protocol.validate().is_err());
        assert!(
            ToolMessage::new(
                "tool.unknown",
                Some("request-1".to_string()),
                Some("invocation-1".to_string()),
                Some("attempt-1".to_string()),
                "endpoint-1",
                Some("instance-1".to_string()),
                Some("move".to_string()),
                None,
                "{}",
            )
            .is_err()
        );
    }

    #[test]
    fn rejects_invalid_management_and_execution_correlation() {
        let mut management = management_message("endpoint.register");
        management.invocation_id = Some("invocation-1".to_string());
        assert!(management.validate().is_err());

        for message_type in [
            "endpoint.register",
            "endpoint.unregister",
            "endpoint.registry.response",
        ] {
            let mut management_without_request = management_message(message_type);
            management_without_request.request_id = None;
            assert!(management_without_request.validate().is_err());
        }

        let mut endpoint_status = endpoint_status_message();
        assert!(endpoint_status.validate().is_ok());
        endpoint_status.request_id = Some("status-1".to_string());
        assert!(endpoint_status.validate().is_err());

        let mut execution = execution_message("tool.invoke.response");
        execution.request_id = None;
        assert!(execution.validate().is_err());

        let mut execution = execution_message("tool.status.request");
        execution.invocation_id = None;
        assert!(execution.validate().is_err());

        let mut execution = execution_message("tool.result.response");
        execution.attempt_id = None;
        assert!(execution.validate().is_err());

        let mut execution = execution_message("tool.control.request");
        execution.operation = None;
        assert!(execution.validate().is_err());

        let mut event = event_message(1);
        event.request_id = Some("request-1".to_string());
        assert!(event.validate().is_err());

        let mut event = event_message(1);
        event.sequence = None;
        assert!(event.validate().is_err());

        let mut non_event = execution_message("tool.error");
        non_event.sequence = Some(1);
        assert!(non_event.validate().is_err());
    }

    #[test]
    fn rejects_sequence_outside_safe_json_integer_range() {
        for sequence in [-1, MAX_SAFE_JSON_INTEGER + 1] {
            assert!(
                ToolMessage::new(
                    "tool.event",
                    None,
                    Some("invocation-1".to_string()),
                    Some("attempt-1".to_string()),
                    "endpoint-1",
                    Some("instance-1".to_string()),
                    Some("move".to_string()),
                    Some(sequence),
                    "{}",
                )
                .is_err()
            );
        }
    }

    #[test]
    fn rejects_empty_strings_and_non_object_payload_shape() {
        for endpoint_id in ["  ", "\u{00a0}"] {
            let mut message = execution_message("tool.invoke.request");
            message.endpoint_id = endpoint_id.to_string();
            assert!(message.validate().is_err());
        }

        let mut message = execution_message("tool.invoke.request");
        message.endpoint_instance_id = Some(String::new());
        assert!(message.validate().is_err());

        for message_type in TOOL_MESSAGE_TYPES {
            if !message_type.starts_with("endpoint.") {
                continue;
            }
            let mut message = if message_type == "endpoint.status" {
                endpoint_status_message()
            } else {
                management_message(message_type)
            };
            message.endpoint_instance_id = None;
            assert!(message.validate().is_err(), "{message_type}");
        }

        let mut message = execution_message("tool.invoke.request");
        message.request_id = Some(String::new());
        assert!(message.validate().is_err());

        let mut message = execution_message("tool.invoke.request");
        message.invocation_id = Some(" \t".to_string());
        assert!(message.validate().is_err());

        let mut message = execution_message("tool.invoke.request");
        message.attempt_id = Some(String::new());
        assert!(message.validate().is_err());

        let mut message = execution_message("tool.invoke.request");
        message.operation = Some("  ".to_string());
        assert!(message.validate().is_err());

        let mut message = execution_message("tool.invoke.request");
        message.payload_json = "[]".to_string();
        assert!(message.validate().is_err());

        let mut message = execution_message("tool.invoke.request");
        message.payload_json = "   ".to_string();
        assert!(message.validate().is_err());

        let mut message = execution_message("tool.invoke.request");
        message.payload_json = " \n {\"ok\":true} \t".to_string();
        assert!(message.validate().is_ok());
    }

    #[test]
    fn rejects_malformed_and_duplicate_payload_json() {
        for payload_json in [
            "not-json",
            "{",
            r#"{"value":}"#,
            r#"{"value":1} trailing"#,
            r#"{"duplicate":1,"duplicate":2}"#,
            r#"{"nested":{"duplicate":1,"duplicate":2}}"#,
        ] {
            assert_payload_rejected(payload_json);
        }
    }

    #[test]
    fn rejects_nonfinite_overflowing_and_out_of_range_payload_numbers() {
        for value in ["NaN", "Infinity", "-Infinity", "1e999", "-1e999"] {
            assert_payload_rejected(format!(r#"{{"value":{value}}}"#));
        }
        for value in [MAX_SAFE_JSON_INTEGER + 1, -(MAX_SAFE_JSON_INTEGER + 1)] {
            assert_payload_rejected(format!(r#"{{"value":{value}}}"#));
        }

        let mut boundary = execution_message("tool.invoke.request");
        boundary.payload_json = format!(
            r#"{{"minimum":{},"maximum":{}}}"#,
            -MAX_SAFE_JSON_INTEGER, MAX_SAFE_JSON_INTEGER
        );
        assert!(boundary.validate().is_ok());
    }

    #[test]
    fn rejects_payload_nesting_deeper_than_64() {
        let mut boundary = execution_message("tool.invoke.request");
        boundary.payload_json = nested_array_payload(64);
        assert!(boundary.validate().is_ok());

        assert_payload_rejected(nested_array_payload(65));
    }

    #[test]
    fn rejects_invalid_unicode_escape_in_payload_json() {
        assert_payload_rejected(r#"{"value":"\uD800"}"#);
    }

    #[test]
    fn arrow_schema_has_exact_contract_order_types_and_nullability() {
        let schema = tool_message_schema();
        assert_eq!(schema.fields().len(), 10);

        let expected = [
            ("protocol", DataType::Utf8, false),
            ("message_type", DataType::Utf8, false),
            ("request_id", DataType::Utf8, true),
            ("invocation_id", DataType::Utf8, true),
            ("attempt_id", DataType::Utf8, true),
            ("endpoint_id", DataType::Utf8, false),
            ("endpoint_instance_id", DataType::Utf8, true),
            ("operation", DataType::Utf8, true),
            ("sequence", DataType::Int64, true),
            ("payload_json", DataType::Utf8, false),
        ];

        for (field, (name, data_type, nullable)) in schema.fields().iter().zip(expected) {
            assert_eq!(field.name(), name);
            assert_eq!(field.data_type(), &data_type);
            assert_eq!(field.is_nullable(), nullable);
        }

        let batch = execution_message("tool.invoke.request")
            .to_record_batch()
            .unwrap();
        assert_eq!(batch.schema().fields(), schema.fields());
    }

    #[test]
    fn record_batch_decoding_ignores_schema_and_field_metadata() {
        let message = execution_message("tool.invoke.request");
        let valid = message.to_record_batch().unwrap();
        let fields = tool_message_schema()
            .fields()
            .iter()
            .map(|field| {
                field.as_ref().clone().with_metadata(HashMap::from([(
                    "field-metadata".to_string(),
                    "ignored".to_string(),
                )]))
            })
            .collect::<Vec<_>>();
        let schema = Schema::new_with_metadata(
            fields,
            HashMap::from([("schema-metadata".to_string(), "ignored".to_string())]),
        );
        let batch = RecordBatch::try_new(Arc::new(schema), valid.columns().to_vec()).unwrap();

        assert_eq!(ToolMessage::from_record_batch(&batch).unwrap(), message);
    }

    #[test]
    fn optional_strings_encode_none_as_null_not_empty() {
        let message = management_message("endpoint.register");
        let batch = message.to_record_batch().unwrap();

        for index in [3, 4, 7] {
            let array = batch
                .column(index)
                .as_any()
                .downcast_ref::<StringArray>()
                .unwrap();
            assert!(array.is_null(0));
        }
    }

    #[test]
    fn from_record_batch_requires_exact_schema_and_one_row() {
        let schema = Arc::new(tool_message_schema());
        let empty = RecordBatch::new_empty(schema.clone());
        assert!(ToolMessage::from_record_batch(&empty).is_err());

        let two_rows = RecordBatch::try_new(
            schema,
            vec![
                Arc::new(StringArray::from(vec![
                    TOOL_ENDPOINT_PROTOCOL,
                    TOOL_ENDPOINT_PROTOCOL,
                ])),
                Arc::new(StringArray::from(vec![
                    "tool.invoke.request",
                    "tool.invoke.request",
                ])),
                Arc::new(StringArray::from(vec![
                    Some("request-1"),
                    Some("request-2"),
                ])),
                Arc::new(StringArray::from(vec![
                    Some("invocation-1"),
                    Some("invocation-2"),
                ])),
                Arc::new(StringArray::from(vec![
                    Some("attempt-1"),
                    Some("attempt-2"),
                ])),
                Arc::new(StringArray::from(vec!["endpoint-1", "endpoint-1"])),
                Arc::new(StringArray::from(vec!["instance-1", "instance-1"])),
                Arc::new(StringArray::from(vec![Some("move"), Some("move")])),
                Arc::new(Int64Array::from(vec![None, None])),
                Arc::new(StringArray::from(vec!["{}", "{}"])),
            ],
        )
        .unwrap();
        assert!(ToolMessage::from_record_batch(&two_rows).is_err());

        let valid = execution_message("tool.invoke.request")
            .to_record_batch()
            .unwrap();
        let mut wrong_fields = tool_message_schema()
            .fields()
            .iter()
            .map(|field| field.as_ref().clone())
            .collect::<Vec<_>>();
        wrong_fields[0] = Field::new("protocol", DataType::Utf8, true);
        let wrong_nullability = RecordBatch::try_new(
            Arc::new(Schema::new(wrong_fields)),
            valid.columns().to_vec(),
        )
        .unwrap();
        assert!(ToolMessage::from_record_batch(&wrong_nullability).is_err());

        let mut reordered_fields = tool_message_schema()
            .fields()
            .iter()
            .map(|field| field.as_ref().clone())
            .collect::<Vec<_>>();
        reordered_fields.swap(0, 1);
        let mut reordered_columns: Vec<ArrayRef> = valid.columns().to_vec();
        reordered_columns.swap(0, 1);
        let reordered =
            RecordBatch::try_new(Arc::new(Schema::new(reordered_fields)), reordered_columns)
                .unwrap();
        assert!(ToolMessage::from_record_batch(&reordered).is_err());
    }

    #[test]
    fn decoding_revalidates_arrow_values() {
        let message = execution_message("tool.invoke.request");
        let valid = message.to_record_batch().unwrap();
        let mut columns = valid.columns().to_vec();
        columns[2] = Arc::new(StringArray::from(vec![Some("")]));
        let empty_request = RecordBatch::try_new(Arc::new(tool_message_schema()), columns).unwrap();

        assert!(ToolMessage::from_record_batch(&empty_request).is_err());
    }
}
