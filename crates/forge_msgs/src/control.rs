use std::sync::Arc;

use arrow_array::{Array, ArrayRef, RecordBatch, StringArray};
use arrow_schema::{DataType, Field, Schema};

#[derive(Clone, Debug, PartialEq)]
pub struct PolicyCommand {
    pub policy_id: String,
    pub command: String,
    pub request_id: String,
    pub inputs_json: String,
}

#[derive(Clone, Debug, PartialEq)]
pub struct PolicyCommandStatus {
    pub policy_id: String,
    pub command: String,
    pub request_id: String,
    pub status: PolicyCommandStatusValue,
    pub message: String,
    pub outputs_json: String,
}

#[derive(Copy, Clone, Debug, Eq, PartialEq)]
pub enum PolicyCommandStatusValue {
    Accepted,
    Rejected,
    Running,
    Done,
    ErrorStatus,
}

impl PolicyCommandStatusValue {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Accepted => "accepted",
            Self::Rejected => "rejected",
            Self::Running => "running",
            Self::Done => "done",
            Self::ErrorStatus => "error",
        }
    }
}

impl TryFrom<&str> for PolicyCommandStatusValue {
    type Error = ControlError;

    fn try_from(value: &str) -> Result<Self, Self::Error> {
        match value {
            "accepted" => Ok(Self::Accepted),
            "rejected" => Ok(Self::Rejected),
            "running" => Ok(Self::Running),
            "done" => Ok(Self::Done),
            "error" => Ok(Self::ErrorStatus),
            _ => Err(ControlError::Invalid(format!(
                "unsupported status: {value}"
            ))),
        }
    }
}

impl PolicyCommand {
    pub fn new(
        policy_id: impl Into<String>,
        command: impl Into<String>,
        request_id: impl Into<String>,
        inputs_json: impl Into<String>,
    ) -> Result<Self, ControlError> {
        let value = Self {
            policy_id: policy_id.into(),
            command: command.into(),
            request_id: request_id.into(),
            inputs_json: inputs_json.into(),
        };
        value.validate()?;
        Ok(value)
    }

    pub fn to_record_batch(&self) -> Result<RecordBatch, ControlError> {
        self.validate()?;
        record_batch(
            vec![
                ("policy_id", self.policy_id.as_str()),
                ("command", self.command.as_str()),
                ("request_id", self.request_id.as_str()),
                ("inputs_json", self.inputs_json.as_str()),
            ],
            vec!["policy_id", "command", "request_id", "inputs_json"],
        )
    }

    pub fn from_record_batch(batch: &RecordBatch) -> Result<Self, ControlError> {
        if batch.num_rows() == 0 {
            return Err(ControlError::Invalid(
                "RecordBatch must contain one row".to_string(),
            ));
        }
        Self::new(
            read_string(batch, "policy_id")?,
            read_string(batch, "command")?,
            read_string(batch, "request_id")?,
            read_string(batch, "inputs_json")?,
        )
    }

    fn validate(&self) -> Result<(), ControlError> {
        validate_required("policy_id", &self.policy_id)?;
        validate_required("command", &self.command)?;
        validate_snake_case(&self.command)?;
        validate_json_object("inputs_json", &self.inputs_json)?;
        Ok(())
    }
}

impl PolicyCommandStatus {
    pub fn new(
        policy_id: impl Into<String>,
        command: impl Into<String>,
        request_id: impl Into<String>,
        status: PolicyCommandStatusValue,
        message: impl Into<String>,
        outputs_json: impl Into<String>,
    ) -> Result<Self, ControlError> {
        let value = Self {
            policy_id: policy_id.into(),
            command: command.into(),
            request_id: request_id.into(),
            status,
            message: message.into(),
            outputs_json: outputs_json.into(),
        };
        value.validate()?;
        Ok(value)
    }

    pub fn to_record_batch(&self) -> Result<RecordBatch, ControlError> {
        self.validate()?;
        record_batch(
            vec![
                ("policy_id", self.policy_id.as_str()),
                ("command", self.command.as_str()),
                ("request_id", self.request_id.as_str()),
                ("status", self.status.as_str()),
                ("message", self.message.as_str()),
                ("outputs_json", self.outputs_json.as_str()),
            ],
            vec![
                "policy_id",
                "command",
                "request_id",
                "status",
                "message",
                "outputs_json",
            ],
        )
    }

    pub fn from_record_batch(batch: &RecordBatch) -> Result<Self, ControlError> {
        if batch.num_rows() == 0 {
            return Err(ControlError::Invalid(
                "RecordBatch must contain one row".to_string(),
            ));
        }
        let status_text = read_string(batch, "status")?;
        Self::new(
            read_string(batch, "policy_id")?,
            read_string(batch, "command")?,
            read_string(batch, "request_id")?,
            PolicyCommandStatusValue::try_from(status_text.as_str())?,
            read_string(batch, "message")?,
            read_string(batch, "outputs_json")?,
        )
    }

    fn validate(&self) -> Result<(), ControlError> {
        validate_required("policy_id", &self.policy_id)?;
        validate_required("command", &self.command)?;
        validate_snake_case(&self.command)?;
        validate_json_object("outputs_json", &self.outputs_json)?;
        Ok(())
    }
}

fn record_batch(
    values: Vec<(&'static str, &str)>,
    field_names: Vec<&'static str>,
) -> Result<RecordBatch, ControlError> {
    let fields = field_names
        .iter()
        .map(|name| Field::new(*name, DataType::Utf8, false))
        .collect::<Vec<_>>();
    let columns = values
        .iter()
        .map(|(_, value)| Arc::new(StringArray::from(vec![*value])) as ArrayRef)
        .collect::<Vec<_>>();
    RecordBatch::try_new(Arc::new(Schema::new(fields)), columns)
        .map_err(|e| ControlError::Arrow(e.to_string()))
}

fn read_string(batch: &RecordBatch, name: &str) -> Result<String, ControlError> {
    let idx = batch
        .schema()
        .index_of(name)
        .map_err(|_| ControlError::Invalid(format!("missing {name} column")))?;
    let array = batch
        .column(idx)
        .as_any()
        .downcast_ref::<StringArray>()
        .ok_or_else(|| ControlError::Invalid(format!("{name} column must be utf8")))?;
    Ok(array.value(0).to_string())
}

fn validate_required(name: &str, value: &str) -> Result<(), ControlError> {
    if value.is_empty() {
        return Err(ControlError::Invalid(format!("{name} must be non-empty")));
    }
    Ok(())
}

fn validate_snake_case(value: &str) -> Result<(), ControlError> {
    let mut chars = value.chars();
    let Some(first) = chars.next() else {
        return Err(ControlError::Invalid(
            "command must be non-empty".to_string(),
        ));
    };
    if !first.is_ascii_lowercase() {
        return Err(ControlError::Invalid(
            "command must use snake_case".to_string(),
        ));
    }
    if chars.any(|c| !(c.is_ascii_lowercase() || c.is_ascii_digit() || c == '_')) {
        return Err(ControlError::Invalid(
            "command must use snake_case".to_string(),
        ));
    }
    Ok(())
}

fn validate_json_object(name: &str, value: &str) -> Result<(), ControlError> {
    let trimmed = value.trim();
    if !(trimmed.starts_with('{') && trimmed.ends_with('}')) {
        return Err(ControlError::Invalid(format!(
            "{name} must be a JSON object"
        )));
    }
    Ok(())
}

#[derive(Debug)]
pub enum ControlError {
    Arrow(String),
    Invalid(String),
}

impl std::fmt::Display for ControlError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ControlError::Arrow(msg) => write!(f, "arrow error: {msg}"),
            ControlError::Invalid(msg) => write!(f, "invalid control message: {msg}"),
        }
    }
}

impl std::error::Error for ControlError {}

#[cfg(test)]
mod tests {
    use super::{PolicyCommand, PolicyCommandStatus, PolicyCommandStatusValue};

    #[test]
    fn policy_command_roundtrip_record_batch() {
        let command = PolicyCommand::new(
            "default",
            "start_recording",
            "rec-001",
            r#"{"output_path":"runs/demo.mcap"}"#,
        )
        .unwrap();
        let batch = command.to_record_batch().unwrap();
        let back = PolicyCommand::from_record_batch(&batch).unwrap();
        assert_eq!(back, command);
    }

    #[test]
    fn policy_command_status_roundtrip_record_batch() {
        let status = PolicyCommandStatus::new(
            "default",
            "start_recording",
            "rec-001",
            PolicyCommandStatusValue::Done,
            "recording started",
            r#"{"path":"runs/demo.mcap"}"#,
        )
        .unwrap();
        let batch = status.to_record_batch().unwrap();
        let back = PolicyCommandStatus::from_record_batch(&batch).unwrap();
        assert_eq!(back, status);
    }

    #[test]
    fn rejects_invalid_command() {
        let command = PolicyCommand::new("default", "Start", "", "{}");
        assert!(command.is_err());
    }

    #[test]
    fn rejects_invalid_json_object_shape() {
        let command = PolicyCommand::new("default", "start", "", "[]");
        assert!(command.is_err());
    }
}
