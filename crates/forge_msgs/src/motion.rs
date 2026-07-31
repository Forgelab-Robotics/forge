use std::collections::HashSet;
use std::sync::Arc;

use arrow_array::{
    Array, ArrayRef, BooleanArray, Float64Array, Int64Array, RecordBatch, StringArray, StructArray,
    UInt32Array, UInt64Array,
};
use arrow_schema::{DataType, Field, Fields, Schema};

use crate::pose::Pose;
use crate::trajectory::{
    JointTolerance, JointTrajectory, JointTrajectoryPoint, TrajectoryError, float_list_array,
    float_list_type, point_fields, read_float_list, read_optional_f64, read_point_struct,
    read_required_i64, read_required_string, read_string_list, read_tolerance_list,
    read_trajectory_struct, string_list_array, string_list_type, tolerance_list_array,
    tolerance_list_type, trajectory_fields, trajectory_struct_array, validate_joint_names,
    validate_non_empty, validate_non_negative_i64, validate_optional_non_negative_f64,
    validate_optional_non_negative_i64,
};

macro_rules! string_enum {
    ($name:ident { $($variant:ident => $value:literal),+ $(,)? }) => {
        #[derive(Copy, Clone, Debug, Eq, Hash, PartialEq)]
        pub enum $name {
            $($variant),+
        }

        impl $name {
            pub const fn as_str(self) -> &'static str {
                match self {
                    $(Self::$variant => $value),+
                }
            }
        }

        impl TryFrom<&str> for $name {
            type Error = MotionError;

            fn try_from(value: &str) -> Result<Self, Self::Error> {
                match value {
                    $($value => Ok(Self::$variant),)+
                    _ => invalid(format!("unsupported {} value: {value}", stringify!($name))),
                }
            }
        }

        impl std::fmt::Display for $name {
            fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
                formatter.write_str(self.as_str())
            }
        }
    };
}

string_enum!(FollowJointTrajectoryErrorCode {
    Success => "SUCCESS",
    InvalidGoal => "INVALID_GOAL",
    InvalidJoints => "INVALID_JOINTS",
    Busy => "BUSY",
    NoFreshRobotState => "NO_FRESH_ROBOT_STATE",
    StartStateMismatch => "START_STATE_MISMATCH",
    PathToleranceViolated => "PATH_TOLERANCE_VIOLATED",
    GoalToleranceViolated => "GOAL_TOLERANCE_VIOLATED",
    FeedbackStale => "FEEDBACK_STALE",
    ExecutionTimedOut => "EXECUTION_TIMED_OUT",
    HardwareFault => "HARDWARE_FAULT",
    Canceled => "CANCELED",
    InternalError => "INTERNAL_ERROR",
});

string_enum!(MotionPhase {
    Validating => "VALIDATING",
    Planning => "PLANNING",
    WaitingForController => "WAITING_FOR_CONTROLLER",
    Executing => "EXECUTING",
    Settling => "SETTLING",
});

string_enum!(MotionErrorCode {
    Success => "SUCCESS",
    InvalidGoal => "INVALID_GOAL",
    Busy => "BUSY",
    InvalidGroup => "INVALID_GROUP",
    InvalidJoints => "INVALID_JOINTS",
    InvalidFrame => "INVALID_FRAME",
    NoFreshRobotState => "NO_FRESH_ROBOT_STATE",
    IkFailed => "IK_FAILED",
    IkTimedOut => "IK_TIMED_OUT",
    JointLimitViolation => "JOINT_LIMIT_VIOLATION",
    PlanningFailed => "PLANNING_FAILED",
    TrajectoryGenerationFailed => "TRAJECTORY_GENERATION_FAILED",
    TrajectoryRejected => "TRAJECTORY_REJECTED",
    TrajectoryExecutionFailed => "TRAJECTORY_EXECUTION_FAILED",
    FinalJointToleranceViolated => "FINAL_JOINT_TOLERANCE_VIOLATED",
    FinalPoseToleranceViolated => "FINAL_POSE_TOLERANCE_VIOLATED",
    Canceled => "CANCELED",
    InternalError => "INTERNAL_ERROR",
});

string_enum!(GripperCommandErrorCode {
    Success => "SUCCESS",
    InvalidGoal => "INVALID_GOAL",
    Busy => "BUSY",
    PositionLimitViolation => "POSITION_LIMIT_VIOLATION",
    UnsupportedVelocity => "UNSUPPORTED_VELOCITY",
    UnsupportedEffort => "UNSUPPORTED_EFFORT",
    NoFreshRobotState => "NO_FRESH_ROBOT_STATE",
    FeedbackStale => "FEEDBACK_STALE",
    Stalled => "STALLED",
    ExecutionTimedOut => "EXECUTION_TIMED_OUT",
    HardwareFault => "HARDWARE_FAULT",
    Canceled => "CANCELED",
    InternalError => "INTERNAL_ERROR",
});

#[derive(Clone, Debug, PartialEq)]
pub struct FollowJointTrajectoryGoal {
    pub trajectory: JointTrajectory,
    pub path_tolerance: Vec<JointTolerance>,
    pub goal_tolerance: Vec<JointTolerance>,
    pub goal_time_tolerance_ns: Option<i64>,
}

#[derive(Clone, Debug, PartialEq)]
pub struct FollowJointTrajectoryFeedback {
    pub sequence: u64,
    pub point_index: u32,
    pub elapsed_ns: i64,
    pub duration_ns: i64,
    pub desired: JointTrajectoryPoint,
    pub actual: JointTrajectoryPoint,
    pub error: JointTrajectoryPoint,
}

#[derive(Clone, Debug, PartialEq)]
pub struct FollowJointTrajectoryResult {
    pub error_code: FollowJointTrajectoryErrorCode,
    pub message: String,
    pub elapsed_ns: i64,
    pub joint_names: Vec<String>,
    pub final_position_error: Vec<f64>,
    pub final_velocity_error: Vec<f64>,
}

#[derive(Clone, Debug, PartialEq)]
pub struct GripperCommandGoal {
    pub position: f64,
    pub max_velocity: Option<f64>,
    pub max_effort: Option<f64>,
}

#[derive(Clone, Debug, PartialEq)]
pub struct GripperCommandFeedback {
    pub elapsed_ns: i64,
    pub position: f64,
    pub velocity: Option<f64>,
    pub effort: Option<f64>,
    pub stalled: bool,
    pub reached_goal: bool,
}

#[derive(Clone, Debug, PartialEq)]
pub struct GripperCommandResult {
    pub error_code: GripperCommandErrorCode,
    pub message: String,
    pub elapsed_ns: i64,
    pub position: Option<f64>,
    pub velocity: Option<f64>,
    pub effort: Option<f64>,
    pub stalled: bool,
    pub reached_goal: bool,
}

#[derive(Clone, Debug, PartialEq)]
pub struct MoveJointsGoal {
    pub group_name: String,
    pub joint_names: Vec<String>,
    pub positions: Vec<f64>,
    pub velocity_scale: f64,
    pub acceleration_scale: f64,
    pub requested_duration_ns: Option<i64>,
}

#[derive(Clone, Debug, PartialEq)]
pub struct MoveJointsFeedback {
    pub phase: MotionPhase,
    pub progress: Option<f64>,
    pub elapsed_ns: i64,
    pub estimated_duration_ns: Option<i64>,
    pub joint_names: Vec<String>,
    pub actual_positions: Vec<f64>,
    pub target_positions: Vec<f64>,
    pub position_errors: Vec<f64>,
    pub message: String,
}

#[derive(Clone, Debug, PartialEq)]
pub struct MoveJointsResult {
    pub error_code: MotionErrorCode,
    pub message: String,
    pub elapsed_ns: i64,
    pub joint_names: Vec<String>,
    pub final_positions: Vec<f64>,
    pub final_position_errors: Vec<f64>,
}

#[derive(Clone, Debug, PartialEq)]
pub struct MovePoseGoal {
    pub group_name: String,
    pub reference_frame: String,
    pub target_frame: String,
    pub target_pose: Pose,
    pub velocity_scale: f64,
    pub acceleration_scale: f64,
    pub requested_duration_ns: Option<i64>,
    pub position_tolerance_m: Option<f64>,
    pub orientation_tolerance_rad: Option<f64>,
}

#[derive(Clone, Debug, PartialEq)]
pub struct MovePoseFeedback {
    pub phase: MotionPhase,
    pub progress: Option<f64>,
    pub elapsed_ns: i64,
    pub estimated_duration_ns: Option<i64>,
    pub actual_pose: Option<Pose>,
    pub position_error_m: Option<f64>,
    pub orientation_error_rad: Option<f64>,
    pub message: String,
}

#[derive(Clone, Debug, PartialEq)]
pub struct MovePoseResult {
    pub error_code: MotionErrorCode,
    pub message: String,
    pub elapsed_ns: i64,
    pub final_pose: Option<Pose>,
    pub final_position_error_m: Option<f64>,
    pub final_orientation_error_rad: Option<f64>,
    pub joint_names: Vec<String>,
    pub final_joint_positions: Vec<f64>,
}

impl FollowJointTrajectoryGoal {
    pub fn new(
        trajectory: JointTrajectory,
        path_tolerance: Vec<JointTolerance>,
        goal_tolerance: Vec<JointTolerance>,
        goal_time_tolerance_ns: Option<i64>,
    ) -> Result<Self, MotionError> {
        let value = Self {
            trajectory,
            path_tolerance,
            goal_tolerance,
            goal_time_tolerance_ns,
        };
        value.validate()?;
        Ok(value)
    }

    pub fn validate(&self) -> Result<(), MotionError> {
        self.trajectory.validate().map_err(from_trajectory_error)?;
        validate_tolerances(
            "path_tolerance",
            &self.path_tolerance,
            &self.trajectory.joint_names,
        )?;
        validate_tolerances(
            "goal_tolerance",
            &self.goal_tolerance,
            &self.trajectory.joint_names,
        )?;
        validate_optional_non_negative_i64("goal_time_tolerance_ns", self.goal_time_tolerance_ns)
            .map_err(from_trajectory_error)
    }

    pub fn to_record_batch(&self) -> Result<RecordBatch, MotionError> {
        self.validate()?;
        make_batch(
            follow_goal_schema(),
            vec![
                Arc::new(trajectory_struct_array(&self.trajectory)),
                Arc::new(tolerance_list_array(&self.path_tolerance)),
                Arc::new(tolerance_list_array(&self.goal_tolerance)),
                Arc::new(Int64Array::from(vec![self.goal_time_tolerance_ns])),
            ],
        )
    }

    pub fn from_record_batch(batch: &RecordBatch) -> Result<Self, MotionError> {
        validate_batch(batch, &follow_goal_schema())?;
        let trajectory = struct_column(batch.column(0), "trajectory")?;
        Self::new(
            read_trajectory_struct(trajectory, 0, "trajectory").map_err(from_trajectory_error)?,
            read_tolerance_list(batch.column(1), 0, "path_tolerance")
                .map_err(from_trajectory_error)?,
            read_tolerance_list(batch.column(2), 0, "goal_tolerance")
                .map_err(from_trajectory_error)?,
            read_optional_i64(batch.column(3), 0, "goal_time_tolerance_ns")?,
        )
    }
}

impl FollowJointTrajectoryFeedback {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        sequence: u64,
        point_index: u32,
        elapsed_ns: i64,
        duration_ns: i64,
        desired: JointTrajectoryPoint,
        actual: JointTrajectoryPoint,
        error: JointTrajectoryPoint,
    ) -> Result<Self, MotionError> {
        let value = Self {
            sequence,
            point_index,
            elapsed_ns,
            duration_ns,
            desired,
            actual,
            error,
        };
        value.validate()?;
        Ok(value)
    }

    pub fn validate(&self) -> Result<(), MotionError> {
        validate_non_negative_i64("elapsed_ns", self.elapsed_ns).map_err(from_trajectory_error)?;
        validate_non_negative_i64("duration_ns", self.duration_ns)
            .map_err(from_trajectory_error)?;
        self.desired.validate().map_err(from_trajectory_error)?;
        self.actual.validate().map_err(from_trajectory_error)?;
        self.error.validate().map_err(from_trajectory_error)?;
        let expected = self.desired.positions.len();
        if self.actual.positions.len() != expected || self.error.positions.len() != expected {
            return invalid("desired, actual, and error must have equal positions lengths");
        }
        Ok(())
    }

    pub fn to_record_batch(&self) -> Result<RecordBatch, MotionError> {
        self.validate()?;
        make_batch(
            follow_feedback_schema(),
            vec![
                Arc::new(UInt64Array::from(vec![self.sequence])),
                Arc::new(UInt32Array::from(vec![self.point_index])),
                Arc::new(Int64Array::from(vec![self.elapsed_ns])),
                Arc::new(Int64Array::from(vec![self.duration_ns])),
                Arc::new(crate::trajectory::point_struct_array(&self.desired)),
                Arc::new(crate::trajectory::point_struct_array(&self.actual)),
                Arc::new(crate::trajectory::point_struct_array(&self.error)),
            ],
        )
    }

    pub fn from_record_batch(batch: &RecordBatch) -> Result<Self, MotionError> {
        validate_batch(batch, &follow_feedback_schema())?;
        Self::new(
            read_required_u64(batch.column(0), 0, "sequence")?,
            read_required_u32(batch.column(1), 0, "point_index")?,
            read_i64(batch.column(2), 0, "elapsed_ns")?,
            read_i64(batch.column(3), 0, "duration_ns")?,
            read_point_struct(struct_column(batch.column(4), "desired")?, 0, "desired")
                .map_err(from_trajectory_error)?,
            read_point_struct(struct_column(batch.column(5), "actual")?, 0, "actual")
                .map_err(from_trajectory_error)?,
            read_point_struct(struct_column(batch.column(6), "error")?, 0, "error")
                .map_err(from_trajectory_error)?,
        )
    }
}

impl FollowJointTrajectoryResult {
    pub fn new(
        error_code: FollowJointTrajectoryErrorCode,
        message: impl Into<String>,
        elapsed_ns: i64,
        joint_names: Vec<String>,
        final_position_error: Vec<f64>,
        final_velocity_error: Vec<f64>,
    ) -> Result<Self, MotionError> {
        let value = Self {
            error_code,
            message: message.into(),
            elapsed_ns,
            joint_names,
            final_position_error,
            final_velocity_error,
        };
        value.validate()?;
        Ok(value)
    }

    pub fn validate(&self) -> Result<(), MotionError> {
        validate_non_negative_i64("elapsed_ns", self.elapsed_ns).map_err(from_trajectory_error)?;
        validate_joint_names("joint_names", &self.joint_names, true)
            .map_err(from_trajectory_error)?;
        validate_empty_or_len(
            "final_position_error",
            &self.final_position_error,
            self.joint_names.len(),
        )?;
        validate_empty_or_len(
            "final_velocity_error",
            &self.final_velocity_error,
            self.joint_names.len(),
        )
    }

    pub fn to_record_batch(&self) -> Result<RecordBatch, MotionError> {
        self.validate()?;
        make_batch(
            follow_result_schema(),
            vec![
                string_array(self.error_code.as_str()),
                string_array(&self.message),
                Arc::new(Int64Array::from(vec![self.elapsed_ns])),
                Arc::new(string_list_array(&self.joint_names)),
                Arc::new(float_list_array(&self.final_position_error)),
                Arc::new(float_list_array(&self.final_velocity_error)),
            ],
        )
    }

    pub fn from_record_batch(batch: &RecordBatch) -> Result<Self, MotionError> {
        validate_batch(batch, &follow_result_schema())?;
        Self::new(
            FollowJointTrajectoryErrorCode::try_from(
                read_string(batch.column(0), 0, "error_code")?.as_str(),
            )?,
            read_string(batch.column(1), 0, "message")?,
            read_i64(batch.column(2), 0, "elapsed_ns")?,
            read_string_list(batch.column(3), 0, "joint_names").map_err(from_trajectory_error)?,
            read_float_list(batch.column(4), 0, "final_position_error")
                .map_err(from_trajectory_error)?,
            read_float_list(batch.column(5), 0, "final_velocity_error")
                .map_err(from_trajectory_error)?,
        )
    }
}

impl GripperCommandGoal {
    pub fn new(
        position: f64,
        max_velocity: Option<f64>,
        max_effort: Option<f64>,
    ) -> Result<Self, MotionError> {
        let value = Self {
            position,
            max_velocity,
            max_effort,
        };
        value.validate()?;
        Ok(value)
    }

    pub fn validate(&self) -> Result<(), MotionError> {
        validate_finite("position", self.position)?;
        validate_optional_non_negative_f64("max_velocity", self.max_velocity)
            .map_err(from_trajectory_error)?;
        validate_optional_non_negative_f64("max_effort", self.max_effort)
            .map_err(from_trajectory_error)
    }

    pub fn to_record_batch(&self) -> Result<RecordBatch, MotionError> {
        self.validate()?;
        make_batch(
            gripper_command_goal_schema(),
            vec![
                Arc::new(Float64Array::from(vec![self.position])),
                Arc::new(Float64Array::from(vec![self.max_velocity])),
                Arc::new(Float64Array::from(vec![self.max_effort])),
            ],
        )
    }

    pub fn from_record_batch(batch: &RecordBatch) -> Result<Self, MotionError> {
        validate_batch_ignoring_schema_metadata(batch, &gripper_command_goal_schema())?;
        Self::new(
            read_f64(batch.column(0), 0, "position")?,
            read_optional_f64(batch.column(1), 0, "max_velocity").map_err(from_trajectory_error)?,
            read_optional_f64(batch.column(2), 0, "max_effort").map_err(from_trajectory_error)?,
        )
    }
}

impl GripperCommandFeedback {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        elapsed_ns: i64,
        position: f64,
        velocity: Option<f64>,
        effort: Option<f64>,
        stalled: bool,
        reached_goal: bool,
    ) -> Result<Self, MotionError> {
        let value = Self {
            elapsed_ns,
            position,
            velocity,
            effort,
            stalled,
            reached_goal,
        };
        value.validate()?;
        Ok(value)
    }

    pub fn validate(&self) -> Result<(), MotionError> {
        validate_non_negative_i64("elapsed_ns", self.elapsed_ns).map_err(from_trajectory_error)?;
        validate_finite("position", self.position)?;
        validate_optional_finite("velocity", self.velocity)?;
        validate_optional_finite("effort", self.effort)
    }

    pub fn to_record_batch(&self) -> Result<RecordBatch, MotionError> {
        self.validate()?;
        make_batch(
            gripper_command_feedback_schema(),
            vec![
                Arc::new(Int64Array::from(vec![self.elapsed_ns])),
                Arc::new(Float64Array::from(vec![self.position])),
                Arc::new(Float64Array::from(vec![self.velocity])),
                Arc::new(Float64Array::from(vec![self.effort])),
                Arc::new(BooleanArray::from(vec![self.stalled])),
                Arc::new(BooleanArray::from(vec![self.reached_goal])),
            ],
        )
    }

    pub fn from_record_batch(batch: &RecordBatch) -> Result<Self, MotionError> {
        validate_batch_ignoring_schema_metadata(batch, &gripper_command_feedback_schema())?;
        Self::new(
            read_i64(batch.column(0), 0, "elapsed_ns")?,
            read_f64(batch.column(1), 0, "position")?,
            read_optional_f64(batch.column(2), 0, "velocity").map_err(from_trajectory_error)?,
            read_optional_f64(batch.column(3), 0, "effort").map_err(from_trajectory_error)?,
            read_bool(batch.column(4), 0, "stalled")?,
            read_bool(batch.column(5), 0, "reached_goal")?,
        )
    }
}

impl GripperCommandResult {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        error_code: GripperCommandErrorCode,
        message: impl Into<String>,
        elapsed_ns: i64,
        position: Option<f64>,
        velocity: Option<f64>,
        effort: Option<f64>,
        stalled: bool,
        reached_goal: bool,
    ) -> Result<Self, MotionError> {
        let value = Self {
            error_code,
            message: message.into(),
            elapsed_ns,
            position,
            velocity,
            effort,
            stalled,
            reached_goal,
        };
        value.validate()?;
        Ok(value)
    }

    pub fn validate(&self) -> Result<(), MotionError> {
        validate_non_negative_i64("elapsed_ns", self.elapsed_ns).map_err(from_trajectory_error)?;
        validate_optional_finite("position", self.position)?;
        validate_optional_finite("velocity", self.velocity)?;
        validate_optional_finite("effort", self.effort)?;
        if self.stalled && self.reached_goal {
            return invalid("stalled and reached_goal cannot both be true");
        }
        if self.error_code == GripperCommandErrorCode::Success
            && !self.stalled
            && !self.reached_goal
        {
            return invalid("SUCCESS requires exactly one of stalled/reached_goal true");
        }
        if self.error_code == GripperCommandErrorCode::Stalled
            && (!self.stalled || self.reached_goal)
        {
            return invalid("STALLED requires stalled=true and reached_goal=false");
        }
        Ok(())
    }

    pub fn to_record_batch(&self) -> Result<RecordBatch, MotionError> {
        self.validate()?;
        make_batch(
            gripper_command_result_schema(),
            vec![
                string_array(self.error_code.as_str()),
                string_array(&self.message),
                Arc::new(Int64Array::from(vec![self.elapsed_ns])),
                Arc::new(Float64Array::from(vec![self.position])),
                Arc::new(Float64Array::from(vec![self.velocity])),
                Arc::new(Float64Array::from(vec![self.effort])),
                Arc::new(BooleanArray::from(vec![self.stalled])),
                Arc::new(BooleanArray::from(vec![self.reached_goal])),
            ],
        )
    }

    pub fn from_record_batch(batch: &RecordBatch) -> Result<Self, MotionError> {
        validate_batch_ignoring_schema_metadata(batch, &gripper_command_result_schema())?;
        Self::new(
            GripperCommandErrorCode::try_from(
                read_string(batch.column(0), 0, "error_code")?.as_str(),
            )?,
            read_string(batch.column(1), 0, "message")?,
            read_i64(batch.column(2), 0, "elapsed_ns")?,
            read_optional_f64(batch.column(3), 0, "position").map_err(from_trajectory_error)?,
            read_optional_f64(batch.column(4), 0, "velocity").map_err(from_trajectory_error)?,
            read_optional_f64(batch.column(5), 0, "effort").map_err(from_trajectory_error)?,
            read_bool(batch.column(6), 0, "stalled")?,
            read_bool(batch.column(7), 0, "reached_goal")?,
        )
    }
}

impl MoveJointsGoal {
    pub fn new(
        group_name: impl Into<String>,
        joint_names: Vec<String>,
        positions: Vec<f64>,
        velocity_scale: f64,
        acceleration_scale: f64,
        requested_duration_ns: Option<i64>,
    ) -> Result<Self, MotionError> {
        let value = Self {
            group_name: group_name.into(),
            joint_names,
            positions,
            velocity_scale,
            acceleration_scale,
            requested_duration_ns,
        };
        value.validate()?;
        Ok(value)
    }

    pub fn validate(&self) -> Result<(), MotionError> {
        validate_non_empty("group_name", &self.group_name).map_err(from_trajectory_error)?;
        validate_joint_names("joint_names", &self.joint_names, false)
            .map_err(from_trajectory_error)?;
        if self.positions.len() != self.joint_names.len() {
            return invalid("positions must have the same length as joint_names");
        }
        validate_finite_values("positions", &self.positions)?;
        validate_scale("velocity_scale", self.velocity_scale)?;
        validate_scale("acceleration_scale", self.acceleration_scale)?;
        validate_optional_non_negative_i64("requested_duration_ns", self.requested_duration_ns)
            .map_err(from_trajectory_error)
    }

    pub fn to_record_batch(&self) -> Result<RecordBatch, MotionError> {
        self.validate()?;
        make_batch(
            move_joints_goal_schema(),
            vec![
                string_array(&self.group_name),
                Arc::new(string_list_array(&self.joint_names)),
                Arc::new(float_list_array(&self.positions)),
                Arc::new(Float64Array::from(vec![self.velocity_scale])),
                Arc::new(Float64Array::from(vec![self.acceleration_scale])),
                Arc::new(Int64Array::from(vec![self.requested_duration_ns])),
            ],
        )
    }

    pub fn from_record_batch(batch: &RecordBatch) -> Result<Self, MotionError> {
        validate_batch(batch, &move_joints_goal_schema())?;
        Self::new(
            read_string(batch.column(0), 0, "group_name")?,
            read_string_list(batch.column(1), 0, "joint_names").map_err(from_trajectory_error)?,
            read_float_list(batch.column(2), 0, "positions").map_err(from_trajectory_error)?,
            read_f64(batch.column(3), 0, "velocity_scale")?,
            read_f64(batch.column(4), 0, "acceleration_scale")?,
            read_optional_i64(batch.column(5), 0, "requested_duration_ns")?,
        )
    }
}

impl MoveJointsFeedback {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        phase: MotionPhase,
        progress: Option<f64>,
        elapsed_ns: i64,
        estimated_duration_ns: Option<i64>,
        joint_names: Vec<String>,
        actual_positions: Vec<f64>,
        target_positions: Vec<f64>,
        position_errors: Vec<f64>,
        message: impl Into<String>,
    ) -> Result<Self, MotionError> {
        let value = Self {
            phase,
            progress,
            elapsed_ns,
            estimated_duration_ns,
            joint_names,
            actual_positions,
            target_positions,
            position_errors,
            message: message.into(),
        };
        value.validate()?;
        Ok(value)
    }

    pub fn validate(&self) -> Result<(), MotionError> {
        validate_progress(self.progress)?;
        validate_non_negative_i64("elapsed_ns", self.elapsed_ns).map_err(from_trajectory_error)?;
        validate_optional_non_negative_i64("estimated_duration_ns", self.estimated_duration_ns)
            .map_err(from_trajectory_error)?;
        validate_joint_names("joint_names", &self.joint_names, false)
            .map_err(from_trajectory_error)?;
        if self.target_positions.len() != self.joint_names.len() {
            return invalid("target_positions must have the same length as joint_names");
        }
        validate_empty_or_len(
            "actual_positions",
            &self.actual_positions,
            self.joint_names.len(),
        )?;
        validate_empty_or_len(
            "position_errors",
            &self.position_errors,
            self.joint_names.len(),
        )
    }

    pub fn to_record_batch(&self) -> Result<RecordBatch, MotionError> {
        self.validate()?;
        make_batch(
            move_joints_feedback_schema(),
            vec![
                string_array(self.phase.as_str()),
                Arc::new(Float64Array::from(vec![self.progress])),
                Arc::new(Int64Array::from(vec![self.elapsed_ns])),
                Arc::new(Int64Array::from(vec![self.estimated_duration_ns])),
                Arc::new(string_list_array(&self.joint_names)),
                Arc::new(float_list_array(&self.actual_positions)),
                Arc::new(float_list_array(&self.target_positions)),
                Arc::new(float_list_array(&self.position_errors)),
                string_array(&self.message),
            ],
        )
    }

    pub fn from_record_batch(batch: &RecordBatch) -> Result<Self, MotionError> {
        validate_batch(batch, &move_joints_feedback_schema())?;
        Self::new(
            MotionPhase::try_from(read_string(batch.column(0), 0, "phase")?.as_str())?,
            read_optional_f64(batch.column(1), 0, "progress").map_err(from_trajectory_error)?,
            read_i64(batch.column(2), 0, "elapsed_ns")?,
            read_optional_i64(batch.column(3), 0, "estimated_duration_ns")?,
            read_string_list(batch.column(4), 0, "joint_names").map_err(from_trajectory_error)?,
            read_float_list(batch.column(5), 0, "actual_positions")
                .map_err(from_trajectory_error)?,
            read_float_list(batch.column(6), 0, "target_positions")
                .map_err(from_trajectory_error)?,
            read_float_list(batch.column(7), 0, "position_errors")
                .map_err(from_trajectory_error)?,
            read_string(batch.column(8), 0, "message")?,
        )
    }
}

impl MoveJointsResult {
    pub fn new(
        error_code: MotionErrorCode,
        message: impl Into<String>,
        elapsed_ns: i64,
        joint_names: Vec<String>,
        final_positions: Vec<f64>,
        final_position_errors: Vec<f64>,
    ) -> Result<Self, MotionError> {
        let value = Self {
            error_code,
            message: message.into(),
            elapsed_ns,
            joint_names,
            final_positions,
            final_position_errors,
        };
        value.validate()?;
        Ok(value)
    }

    pub fn validate(&self) -> Result<(), MotionError> {
        validate_non_negative_i64("elapsed_ns", self.elapsed_ns).map_err(from_trajectory_error)?;
        validate_joint_names("joint_names", &self.joint_names, true)
            .map_err(from_trajectory_error)?;
        validate_empty_or_len(
            "final_positions",
            &self.final_positions,
            self.joint_names.len(),
        )?;
        validate_empty_or_len(
            "final_position_errors",
            &self.final_position_errors,
            self.joint_names.len(),
        )
    }

    pub fn to_record_batch(&self) -> Result<RecordBatch, MotionError> {
        self.validate()?;
        make_batch(
            move_joints_result_schema(),
            vec![
                string_array(self.error_code.as_str()),
                string_array(&self.message),
                Arc::new(Int64Array::from(vec![self.elapsed_ns])),
                Arc::new(string_list_array(&self.joint_names)),
                Arc::new(float_list_array(&self.final_positions)),
                Arc::new(float_list_array(&self.final_position_errors)),
            ],
        )
    }

    pub fn from_record_batch(batch: &RecordBatch) -> Result<Self, MotionError> {
        validate_batch(batch, &move_joints_result_schema())?;
        Self::new(
            MotionErrorCode::try_from(read_string(batch.column(0), 0, "error_code")?.as_str())?,
            read_string(batch.column(1), 0, "message")?,
            read_i64(batch.column(2), 0, "elapsed_ns")?,
            read_string_list(batch.column(3), 0, "joint_names").map_err(from_trajectory_error)?,
            read_float_list(batch.column(4), 0, "final_positions")
                .map_err(from_trajectory_error)?,
            read_float_list(batch.column(5), 0, "final_position_errors")
                .map_err(from_trajectory_error)?,
        )
    }
}

impl MovePoseGoal {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        group_name: impl Into<String>,
        reference_frame: impl Into<String>,
        target_frame: impl Into<String>,
        target_pose: Pose,
        velocity_scale: f64,
        acceleration_scale: f64,
        requested_duration_ns: Option<i64>,
        position_tolerance_m: Option<f64>,
        orientation_tolerance_rad: Option<f64>,
    ) -> Result<Self, MotionError> {
        let value = Self {
            group_name: group_name.into(),
            reference_frame: reference_frame.into(),
            target_frame: target_frame.into(),
            target_pose,
            velocity_scale,
            acceleration_scale,
            requested_duration_ns,
            position_tolerance_m,
            orientation_tolerance_rad,
        };
        value.validate()?;
        Ok(value)
    }

    pub fn validate(&self) -> Result<(), MotionError> {
        validate_non_empty("group_name", &self.group_name).map_err(from_trajectory_error)?;
        validate_non_empty("reference_frame", &self.reference_frame)
            .map_err(from_trajectory_error)?;
        validate_non_empty("target_frame", &self.target_frame).map_err(from_trajectory_error)?;
        validate_pose("target_pose", &self.target_pose)?;
        validate_scale("velocity_scale", self.velocity_scale)?;
        validate_scale("acceleration_scale", self.acceleration_scale)?;
        validate_optional_non_negative_i64("requested_duration_ns", self.requested_duration_ns)
            .map_err(from_trajectory_error)?;
        validate_optional_non_negative_f64("position_tolerance_m", self.position_tolerance_m)
            .map_err(from_trajectory_error)?;
        validate_optional_non_negative_f64(
            "orientation_tolerance_rad",
            self.orientation_tolerance_rad,
        )
        .map_err(from_trajectory_error)
    }

    pub fn to_record_batch(&self) -> Result<RecordBatch, MotionError> {
        self.validate()?;
        make_batch(
            move_pose_goal_schema(),
            vec![
                string_array(&self.group_name),
                string_array(&self.reference_frame),
                string_array(&self.target_frame),
                Arc::new(pose_struct_array(&self.target_pose)),
                Arc::new(Float64Array::from(vec![self.velocity_scale])),
                Arc::new(Float64Array::from(vec![self.acceleration_scale])),
                Arc::new(Int64Array::from(vec![self.requested_duration_ns])),
                Arc::new(Float64Array::from(vec![self.position_tolerance_m])),
                Arc::new(Float64Array::from(vec![self.orientation_tolerance_rad])),
            ],
        )
    }

    pub fn from_record_batch(batch: &RecordBatch) -> Result<Self, MotionError> {
        validate_batch(batch, &move_pose_goal_schema())?;
        Self::new(
            read_string(batch.column(0), 0, "group_name")?,
            read_string(batch.column(1), 0, "reference_frame")?,
            read_string(batch.column(2), 0, "target_frame")?,
            read_pose_struct(
                struct_column(batch.column(3), "target_pose")?,
                0,
                "target_pose",
            )?
            .ok_or_else(|| MotionError::Invalid("target_pose must be non-null".into()))?,
            read_f64(batch.column(4), 0, "velocity_scale")?,
            read_f64(batch.column(5), 0, "acceleration_scale")?,
            read_optional_i64(batch.column(6), 0, "requested_duration_ns")?,
            read_optional_f64(batch.column(7), 0, "position_tolerance_m")
                .map_err(from_trajectory_error)?,
            read_optional_f64(batch.column(8), 0, "orientation_tolerance_rad")
                .map_err(from_trajectory_error)?,
        )
    }
}

impl MovePoseFeedback {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        phase: MotionPhase,
        progress: Option<f64>,
        elapsed_ns: i64,
        estimated_duration_ns: Option<i64>,
        actual_pose: Option<Pose>,
        position_error_m: Option<f64>,
        orientation_error_rad: Option<f64>,
        message: impl Into<String>,
    ) -> Result<Self, MotionError> {
        let value = Self {
            phase,
            progress,
            elapsed_ns,
            estimated_duration_ns,
            actual_pose,
            position_error_m,
            orientation_error_rad,
            message: message.into(),
        };
        value.validate()?;
        Ok(value)
    }

    pub fn validate(&self) -> Result<(), MotionError> {
        validate_progress(self.progress)?;
        validate_non_negative_i64("elapsed_ns", self.elapsed_ns).map_err(from_trajectory_error)?;
        validate_optional_non_negative_i64("estimated_duration_ns", self.estimated_duration_ns)
            .map_err(from_trajectory_error)?;
        if let Some(pose) = &self.actual_pose {
            validate_pose("actual_pose", pose)?;
        }
        validate_optional_non_negative_f64("position_error_m", self.position_error_m)
            .map_err(from_trajectory_error)?;
        validate_optional_non_negative_f64("orientation_error_rad", self.orientation_error_rad)
            .map_err(from_trajectory_error)
    }

    pub fn to_record_batch(&self) -> Result<RecordBatch, MotionError> {
        self.validate()?;
        make_batch(
            move_pose_feedback_schema(),
            vec![
                string_array(self.phase.as_str()),
                Arc::new(Float64Array::from(vec![self.progress])),
                Arc::new(Int64Array::from(vec![self.elapsed_ns])),
                Arc::new(Int64Array::from(vec![self.estimated_duration_ns])),
                Arc::new(optional_pose_struct_array(self.actual_pose.as_ref())),
                Arc::new(Float64Array::from(vec![self.position_error_m])),
                Arc::new(Float64Array::from(vec![self.orientation_error_rad])),
                string_array(&self.message),
            ],
        )
    }

    pub fn from_record_batch(batch: &RecordBatch) -> Result<Self, MotionError> {
        validate_batch(batch, &move_pose_feedback_schema())?;
        Self::new(
            MotionPhase::try_from(read_string(batch.column(0), 0, "phase")?.as_str())?,
            read_optional_f64(batch.column(1), 0, "progress").map_err(from_trajectory_error)?,
            read_i64(batch.column(2), 0, "elapsed_ns")?,
            read_optional_i64(batch.column(3), 0, "estimated_duration_ns")?,
            read_pose_struct(
                struct_column(batch.column(4), "actual_pose")?,
                0,
                "actual_pose",
            )?,
            read_optional_f64(batch.column(5), 0, "position_error_m")
                .map_err(from_trajectory_error)?,
            read_optional_f64(batch.column(6), 0, "orientation_error_rad")
                .map_err(from_trajectory_error)?,
            read_string(batch.column(7), 0, "message")?,
        )
    }
}

impl MovePoseResult {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        error_code: MotionErrorCode,
        message: impl Into<String>,
        elapsed_ns: i64,
        final_pose: Option<Pose>,
        final_position_error_m: Option<f64>,
        final_orientation_error_rad: Option<f64>,
        joint_names: Vec<String>,
        final_joint_positions: Vec<f64>,
    ) -> Result<Self, MotionError> {
        let value = Self {
            error_code,
            message: message.into(),
            elapsed_ns,
            final_pose,
            final_position_error_m,
            final_orientation_error_rad,
            joint_names,
            final_joint_positions,
        };
        value.validate()?;
        Ok(value)
    }

    pub fn validate(&self) -> Result<(), MotionError> {
        validate_non_negative_i64("elapsed_ns", self.elapsed_ns).map_err(from_trajectory_error)?;
        if let Some(pose) = &self.final_pose {
            validate_pose("final_pose", pose)?;
        }
        validate_optional_non_negative_f64("final_position_error_m", self.final_position_error_m)
            .map_err(from_trajectory_error)?;
        validate_optional_non_negative_f64(
            "final_orientation_error_rad",
            self.final_orientation_error_rad,
        )
        .map_err(from_trajectory_error)?;
        validate_joint_names("joint_names", &self.joint_names, true)
            .map_err(from_trajectory_error)?;
        validate_empty_or_len(
            "final_joint_positions",
            &self.final_joint_positions,
            self.joint_names.len(),
        )
    }

    pub fn to_record_batch(&self) -> Result<RecordBatch, MotionError> {
        self.validate()?;
        make_batch(
            move_pose_result_schema(),
            vec![
                string_array(self.error_code.as_str()),
                string_array(&self.message),
                Arc::new(Int64Array::from(vec![self.elapsed_ns])),
                Arc::new(optional_pose_struct_array(self.final_pose.as_ref())),
                Arc::new(Float64Array::from(vec![self.final_position_error_m])),
                Arc::new(Float64Array::from(vec![self.final_orientation_error_rad])),
                Arc::new(string_list_array(&self.joint_names)),
                Arc::new(float_list_array(&self.final_joint_positions)),
            ],
        )
    }

    pub fn from_record_batch(batch: &RecordBatch) -> Result<Self, MotionError> {
        validate_batch(batch, &move_pose_result_schema())?;
        Self::new(
            MotionErrorCode::try_from(read_string(batch.column(0), 0, "error_code")?.as_str())?,
            read_string(batch.column(1), 0, "message")?,
            read_i64(batch.column(2), 0, "elapsed_ns")?,
            read_pose_struct(
                struct_column(batch.column(3), "final_pose")?,
                0,
                "final_pose",
            )?,
            read_optional_f64(batch.column(4), 0, "final_position_error_m")
                .map_err(from_trajectory_error)?,
            read_optional_f64(batch.column(5), 0, "final_orientation_error_rad")
                .map_err(from_trajectory_error)?,
            read_string_list(batch.column(6), 0, "joint_names").map_err(from_trajectory_error)?,
            read_float_list(batch.column(7), 0, "final_joint_positions")
                .map_err(from_trajectory_error)?,
        )
    }
}

fn follow_goal_schema() -> Schema {
    Schema::new(vec![
        Field::new("trajectory", DataType::Struct(trajectory_fields()), false),
        Field::new("path_tolerance", tolerance_list_type(), false),
        Field::new("goal_tolerance", tolerance_list_type(), false),
        Field::new("goal_time_tolerance_ns", DataType::Int64, true),
    ])
}

fn follow_feedback_schema() -> Schema {
    Schema::new(vec![
        Field::new("sequence", DataType::UInt64, false),
        Field::new("point_index", DataType::UInt32, false),
        Field::new("elapsed_ns", DataType::Int64, false),
        Field::new("duration_ns", DataType::Int64, false),
        Field::new("desired", DataType::Struct(point_fields()), false),
        Field::new("actual", DataType::Struct(point_fields()), false),
        Field::new("error", DataType::Struct(point_fields()), false),
    ])
}

fn follow_result_schema() -> Schema {
    Schema::new(vec![
        Field::new("error_code", DataType::Utf8, false),
        Field::new("message", DataType::Utf8, false),
        Field::new("elapsed_ns", DataType::Int64, false),
        Field::new("joint_names", string_list_type(), false),
        Field::new("final_position_error", float_list_type(), false),
        Field::new("final_velocity_error", float_list_type(), false),
    ])
}

fn gripper_command_goal_schema() -> Schema {
    Schema::new(vec![
        Field::new("position", DataType::Float64, false),
        Field::new("max_velocity", DataType::Float64, true),
        Field::new("max_effort", DataType::Float64, true),
    ])
}

fn gripper_command_feedback_schema() -> Schema {
    Schema::new(vec![
        Field::new("elapsed_ns", DataType::Int64, false),
        Field::new("position", DataType::Float64, false),
        Field::new("velocity", DataType::Float64, true),
        Field::new("effort", DataType::Float64, true),
        Field::new("stalled", DataType::Boolean, false),
        Field::new("reached_goal", DataType::Boolean, false),
    ])
}

fn gripper_command_result_schema() -> Schema {
    Schema::new(vec![
        Field::new("error_code", DataType::Utf8, false),
        Field::new("message", DataType::Utf8, false),
        Field::new("elapsed_ns", DataType::Int64, false),
        Field::new("position", DataType::Float64, true),
        Field::new("velocity", DataType::Float64, true),
        Field::new("effort", DataType::Float64, true),
        Field::new("stalled", DataType::Boolean, false),
        Field::new("reached_goal", DataType::Boolean, false),
    ])
}

fn move_joints_goal_schema() -> Schema {
    Schema::new(vec![
        Field::new("group_name", DataType::Utf8, false),
        Field::new("joint_names", string_list_type(), false),
        Field::new("positions", float_list_type(), false),
        Field::new("velocity_scale", DataType::Float64, false),
        Field::new("acceleration_scale", DataType::Float64, false),
        Field::new("requested_duration_ns", DataType::Int64, true),
    ])
}

fn move_joints_feedback_schema() -> Schema {
    Schema::new(vec![
        Field::new("phase", DataType::Utf8, false),
        Field::new("progress", DataType::Float64, true),
        Field::new("elapsed_ns", DataType::Int64, false),
        Field::new("estimated_duration_ns", DataType::Int64, true),
        Field::new("joint_names", string_list_type(), false),
        Field::new("actual_positions", float_list_type(), false),
        Field::new("target_positions", float_list_type(), false),
        Field::new("position_errors", float_list_type(), false),
        Field::new("message", DataType::Utf8, false),
    ])
}

fn move_joints_result_schema() -> Schema {
    Schema::new(vec![
        Field::new("error_code", DataType::Utf8, false),
        Field::new("message", DataType::Utf8, false),
        Field::new("elapsed_ns", DataType::Int64, false),
        Field::new("joint_names", string_list_type(), false),
        Field::new("final_positions", float_list_type(), false),
        Field::new("final_position_errors", float_list_type(), false),
    ])
}

fn move_pose_goal_schema() -> Schema {
    Schema::new(vec![
        Field::new("group_name", DataType::Utf8, false),
        Field::new("reference_frame", DataType::Utf8, false),
        Field::new("target_frame", DataType::Utf8, false),
        Field::new("target_pose", DataType::Struct(pose_fields()), false),
        Field::new("velocity_scale", DataType::Float64, false),
        Field::new("acceleration_scale", DataType::Float64, false),
        Field::new("requested_duration_ns", DataType::Int64, true),
        Field::new("position_tolerance_m", DataType::Float64, true),
        Field::new("orientation_tolerance_rad", DataType::Float64, true),
    ])
}

fn move_pose_feedback_schema() -> Schema {
    Schema::new(vec![
        Field::new("phase", DataType::Utf8, false),
        Field::new("progress", DataType::Float64, true),
        Field::new("elapsed_ns", DataType::Int64, false),
        Field::new("estimated_duration_ns", DataType::Int64, true),
        Field::new("actual_pose", DataType::Struct(pose_fields()), true),
        Field::new("position_error_m", DataType::Float64, true),
        Field::new("orientation_error_rad", DataType::Float64, true),
        Field::new("message", DataType::Utf8, false),
    ])
}

fn move_pose_result_schema() -> Schema {
    Schema::new(vec![
        Field::new("error_code", DataType::Utf8, false),
        Field::new("message", DataType::Utf8, false),
        Field::new("elapsed_ns", DataType::Int64, false),
        Field::new("final_pose", DataType::Struct(pose_fields()), true),
        Field::new("final_position_error_m", DataType::Float64, true),
        Field::new("final_orientation_error_rad", DataType::Float64, true),
        Field::new("joint_names", string_list_type(), false),
        Field::new("final_joint_positions", float_list_type(), false),
    ])
}

fn pose_fields() -> Fields {
    vec![
        Field::new("x", DataType::Float64, false),
        Field::new("y", DataType::Float64, false),
        Field::new("z", DataType::Float64, false),
        Field::new("qx", DataType::Float64, false),
        Field::new("qy", DataType::Float64, false),
        Field::new("qz", DataType::Float64, false),
        Field::new("qw", DataType::Float64, false),
    ]
    .into()
}

fn pose_struct_array(pose: &Pose) -> StructArray {
    StructArray::new(
        pose_fields(),
        vec![
            Arc::new(Float64Array::from(vec![pose.x])),
            Arc::new(Float64Array::from(vec![pose.y])),
            Arc::new(Float64Array::from(vec![pose.z])),
            Arc::new(Float64Array::from(vec![pose.qx])),
            Arc::new(Float64Array::from(vec![pose.qy])),
            Arc::new(Float64Array::from(vec![pose.qz])),
            Arc::new(Float64Array::from(vec![pose.qw])),
        ],
        None,
    )
}

fn optional_pose_struct_array(pose: Option<&Pose>) -> StructArray {
    pose.map_or_else(
        || StructArray::new_null(pose_fields(), 1),
        pose_struct_array,
    )
}

fn read_pose_struct(
    array: &StructArray,
    index: usize,
    name: &str,
) -> Result<Option<Pose>, MotionError> {
    if index >= array.len() {
        return invalid(format!("{name} is missing row {index}"));
    }
    if array.is_null(index) {
        return Ok(None);
    }
    Pose::new(
        read_f64(array.column(0), index, &format!("{name}.x"))?,
        read_f64(array.column(1), index, &format!("{name}.y"))?,
        read_f64(array.column(2), index, &format!("{name}.z"))?,
        read_f64(array.column(3), index, &format!("{name}.qx"))?,
        read_f64(array.column(4), index, &format!("{name}.qy"))?,
        read_f64(array.column(5), index, &format!("{name}.qz"))?,
        read_f64(array.column(6), index, &format!("{name}.qw"))?,
    )
    .map(Some)
    .map_err(|error| MotionError::Invalid(format!("{name}: {error}")))
}

fn validate_pose(name: &str, pose: &Pose) -> Result<(), MotionError> {
    Pose::new(pose.x, pose.y, pose.z, pose.qx, pose.qy, pose.qz, pose.qw)
        .map(|_| ())
        .map_err(|error| MotionError::Invalid(format!("{name}: {error}")))
}

fn validate_tolerances(
    name: &str,
    values: &[JointTolerance],
    trajectory_joint_names: &[String],
) -> Result<(), MotionError> {
    let trajectory_names = trajectory_joint_names
        .iter()
        .map(String::as_str)
        .collect::<HashSet<_>>();
    let mut names = HashSet::new();
    for tolerance in values {
        tolerance.validate().map_err(from_trajectory_error)?;
        if !names.insert(tolerance.joint_name.as_str()) {
            return invalid(format!("{name} joint names must be unique"));
        }
        if !trajectory_names.contains(tolerance.joint_name.as_str()) {
            return invalid(format!(
                "{name} joint {} does not belong to trajectory.joint_names",
                tolerance.joint_name
            ));
        }
    }
    Ok(())
}

fn validate_scale(name: &str, value: f64) -> Result<(), MotionError> {
    if !value.is_finite() || value <= 0.0 || value > 1.0 {
        return invalid(format!("{name} must be finite and in the interval (0, 1]"));
    }
    Ok(())
}

fn validate_progress(value: Option<f64>) -> Result<(), MotionError> {
    if value.is_some_and(|value| !value.is_finite() || !(0.0..=1.0).contains(&value)) {
        return invalid("progress must be finite and in the interval [0, 1] when specified");
    }
    Ok(())
}

fn validate_finite(name: &str, value: f64) -> Result<(), MotionError> {
    if !value.is_finite() {
        return invalid(format!("{name} must be finite"));
    }
    Ok(())
}

fn validate_optional_finite(name: &str, value: Option<f64>) -> Result<(), MotionError> {
    if value.is_some_and(|value| !value.is_finite()) {
        return invalid(format!("{name} must be finite when specified"));
    }
    Ok(())
}

fn validate_finite_values(name: &str, values: &[f64]) -> Result<(), MotionError> {
    if values.iter().any(|value| !value.is_finite()) {
        return invalid(format!("{name} values must be finite"));
    }
    Ok(())
}

fn validate_empty_or_len(name: &str, values: &[f64], expected: usize) -> Result<(), MotionError> {
    if !values.is_empty() && values.len() != expected {
        return invalid(format!(
            "{name} must be empty or have the same length as joint_names"
        ));
    }
    Ok(())
}

fn validate_batch(batch: &RecordBatch, expected: &Schema) -> Result<(), MotionError> {
    if batch.num_rows() != 1 {
        return invalid("RecordBatch must contain exactly one row");
    }
    if batch.schema().as_ref() != expected {
        return invalid("RecordBatch schema does not match the message schema");
    }
    Ok(())
}

fn validate_batch_ignoring_schema_metadata(
    batch: &RecordBatch,
    expected: &Schema,
) -> Result<(), MotionError> {
    if batch.num_rows() != 1 {
        return invalid("RecordBatch must contain exactly one row");
    }
    if batch.schema().fields() != expected.fields() {
        return invalid("RecordBatch schema fields do not match the message schema");
    }
    Ok(())
}

fn make_batch(schema: Schema, columns: Vec<ArrayRef>) -> Result<RecordBatch, MotionError> {
    RecordBatch::try_new(Arc::new(schema), columns)
        .map_err(|error| MotionError::Arrow(error.to_string()))
}

fn string_array(value: &str) -> ArrayRef {
    Arc::new(StringArray::from(vec![value]))
}

fn struct_column<'a>(array: &'a ArrayRef, name: &str) -> Result<&'a StructArray, MotionError> {
    array
        .as_any()
        .downcast_ref::<StructArray>()
        .ok_or_else(|| MotionError::Invalid(format!("{name} must be struct")))
}

fn read_string(array: &ArrayRef, index: usize, name: &str) -> Result<String, MotionError> {
    read_required_string(array, index, name).map_err(from_trajectory_error)
}

fn read_i64(array: &ArrayRef, index: usize, name: &str) -> Result<i64, MotionError> {
    read_required_i64(array, index, name).map_err(from_trajectory_error)
}

fn read_optional_i64(
    array: &ArrayRef,
    index: usize,
    name: &str,
) -> Result<Option<i64>, MotionError> {
    let values = array
        .as_any()
        .downcast_ref::<Int64Array>()
        .ok_or_else(|| MotionError::Invalid(format!("{name} must be int64")))?;
    if index >= values.len() {
        return invalid(format!("{name} is missing row {index}"));
    }
    Ok((!values.is_null(index)).then(|| values.value(index)))
}

fn read_f64(array: &ArrayRef, index: usize, name: &str) -> Result<f64, MotionError> {
    let values = array
        .as_any()
        .downcast_ref::<Float64Array>()
        .ok_or_else(|| MotionError::Invalid(format!("{name} must be float64")))?;
    if index >= values.len() || values.is_null(index) {
        return invalid(format!("{name} must be non-null"));
    }
    Ok(values.value(index))
}

fn read_bool(array: &ArrayRef, index: usize, name: &str) -> Result<bool, MotionError> {
    let values = array
        .as_any()
        .downcast_ref::<BooleanArray>()
        .ok_or_else(|| MotionError::Invalid(format!("{name} must be bool")))?;
    if index >= values.len() || values.is_null(index) {
        return invalid(format!("{name} must be non-null"));
    }
    Ok(values.value(index))
}

fn read_required_u64(array: &ArrayRef, index: usize, name: &str) -> Result<u64, MotionError> {
    let values = array
        .as_any()
        .downcast_ref::<UInt64Array>()
        .ok_or_else(|| MotionError::Invalid(format!("{name} must be uint64")))?;
    if index >= values.len() || values.is_null(index) {
        return invalid(format!("{name} must be non-null"));
    }
    Ok(values.value(index))
}

fn read_required_u32(array: &ArrayRef, index: usize, name: &str) -> Result<u32, MotionError> {
    let values = array
        .as_any()
        .downcast_ref::<UInt32Array>()
        .ok_or_else(|| MotionError::Invalid(format!("{name} must be uint32")))?;
    if index >= values.len() || values.is_null(index) {
        return invalid(format!("{name} must be non-null"));
    }
    Ok(values.value(index))
}

fn from_trajectory_error(error: TrajectoryError) -> MotionError {
    match error {
        TrajectoryError::Arrow(message) => MotionError::Arrow(message),
        TrajectoryError::Invalid(message) => MotionError::Invalid(message),
    }
}

fn invalid<T>(message: impl Into<String>) -> Result<T, MotionError> {
    Err(MotionError::Invalid(message.into()))
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum MotionError {
    Arrow(String),
    Invalid(String),
}

impl std::fmt::Display for MotionError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Arrow(message) => write!(formatter, "arrow error: {message}"),
            Self::Invalid(message) => write!(formatter, "invalid motion message: {message}"),
        }
    }
}

impl std::error::Error for MotionError {}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;
    use std::sync::Arc;

    use arrow_array::{Array, ArrayRef, Int64Array, RecordBatch};
    use arrow_schema::{DataType, Field, Schema};

    use super::{
        FollowJointTrajectoryErrorCode, FollowJointTrajectoryFeedback, FollowJointTrajectoryGoal,
        FollowJointTrajectoryResult, GripperCommandErrorCode, GripperCommandFeedback,
        GripperCommandGoal, GripperCommandResult, MotionErrorCode, MotionPhase, MoveJointsFeedback,
        MoveJointsGoal, MoveJointsResult, MovePoseFeedback, MovePoseGoal, MovePoseResult,
    };
    use crate::{JointTolerance, JointTrajectory, JointTrajectoryPoint, Pose};

    fn point(time: i64) -> JointTrajectoryPoint {
        JointTrajectoryPoint::new(vec![1.0, 2.0], vec![], vec![], vec![], time).unwrap()
    }

    fn trajectory() -> JointTrajectory {
        JointTrajectory::new(vec!["j1".into(), "j2".into()], vec![point(0), point(10)]).unwrap()
    }

    fn pose() -> Pose {
        Pose::new(1.0, 2.0, 3.0, 0.0, 0.0, 0.0, 1.0).unwrap()
    }

    fn roundtrip<T: std::fmt::Debug + PartialEq>(
        value: T,
        to_batch: impl FnOnce(&T) -> arrow_array::RecordBatch,
        from_batch: impl FnOnce(&arrow_array::RecordBatch) -> T,
    ) {
        let batch = to_batch(&value);
        assert_eq!(batch.num_rows(), 1);
        assert_eq!(from_batch(&batch), value);
    }

    #[test]
    fn all_follow_joint_trajectory_messages_roundtrip() {
        let goal = FollowJointTrajectoryGoal::new(
            trajectory(),
            vec![JointTolerance::new("j1", Some(0.1), None, None).unwrap()],
            vec![],
            Some(20),
        )
        .unwrap();
        roundtrip(
            goal,
            |value| value.to_record_batch().unwrap(),
            |batch| FollowJointTrajectoryGoal::from_record_batch(batch).unwrap(),
        );

        let feedback = FollowJointTrajectoryFeedback::new(
            4,
            1,
            8,
            10,
            point(8),
            point(8),
            JointTrajectoryPoint::new(vec![0.1, 0.2], vec![], vec![], vec![], 8).unwrap(),
        )
        .unwrap();
        roundtrip(
            feedback,
            |value| value.to_record_batch().unwrap(),
            |batch| FollowJointTrajectoryFeedback::from_record_batch(batch).unwrap(),
        );

        let result = FollowJointTrajectoryResult::new(
            FollowJointTrajectoryErrorCode::Success,
            "done",
            10,
            vec!["j1".into(), "j2".into()],
            vec![0.0, 0.0],
            vec![],
        )
        .unwrap();
        roundtrip(
            result,
            |value| value.to_record_batch().unwrap(),
            |batch| FollowJointTrajectoryResult::from_record_batch(batch).unwrap(),
        );
    }

    #[test]
    fn all_gripper_command_messages_roundtrip() {
        let goal = GripperCommandGoal::new(0.08, None, Some(12.0)).unwrap();
        let goal_batch = goal.to_record_batch().unwrap();
        assert!(goal_batch.column(1).is_null(0));
        assert!(!goal_batch.column(2).is_null(0));
        assert_eq!(
            GripperCommandGoal::from_record_batch(&goal_batch).unwrap(),
            goal
        );

        let feedback =
            GripperCommandFeedback::new(5, 1.2, None, Some(-0.25), false, false).unwrap();
        roundtrip(
            feedback,
            |value| value.to_record_batch().unwrap(),
            |batch| GripperCommandFeedback::from_record_batch(batch).unwrap(),
        );

        let result = GripperCommandResult::new(
            GripperCommandErrorCode::NoFreshRobotState,
            "state unavailable",
            0,
            None,
            None,
            None,
            false,
            false,
        )
        .unwrap();
        let result_batch = result.to_record_batch().unwrap();
        assert!(result_batch.column(3).is_null(0));
        assert_eq!(
            GripperCommandResult::from_record_batch(&result_batch).unwrap(),
            result
        );
    }

    #[test]
    fn gripper_schema_ignores_schema_metadata_but_rejects_structural_changes() {
        let with_metadata = |batch: &RecordBatch| {
            let schema = Schema::new_with_metadata(
                batch.schema().fields().clone(),
                HashMap::from([("producer".to_owned(), "review-test".to_owned())]),
            );
            RecordBatch::try_new(Arc::new(schema), batch.columns().to_vec()).unwrap()
        };

        let goal = GripperCommandGoal::new(0.08, None, Some(12.0)).unwrap();
        let goal_batch = goal.to_record_batch().unwrap();
        assert_eq!(
            GripperCommandGoal::from_record_batch(&with_metadata(&goal_batch)).unwrap(),
            goal
        );

        let feedback =
            GripperCommandFeedback::new(5, 1.2, None, Some(-0.25), false, false).unwrap();
        let feedback_batch = feedback.to_record_batch().unwrap();
        assert_eq!(
            GripperCommandFeedback::from_record_batch(&with_metadata(&feedback_batch)).unwrap(),
            feedback
        );

        let result = GripperCommandResult::new(
            GripperCommandErrorCode::NoFreshRobotState,
            "state unavailable",
            0,
            None,
            None,
            None,
            false,
            false,
        )
        .unwrap();
        let result_batch = result.to_record_batch().unwrap();
        assert_eq!(
            GripperCommandResult::from_record_batch(&with_metadata(&result_batch)).unwrap(),
            result
        );

        let fields = goal_batch
            .schema()
            .fields()
            .iter()
            .cloned()
            .collect::<Vec<_>>();
        let columns = goal_batch.columns().to_vec();
        let assert_rejected =
            |fields: Vec<Arc<Field>>, columns: Vec<ArrayRef>, difference: &str| {
                let batch = RecordBatch::try_new(Arc::new(Schema::new(fields)), columns).unwrap();
                assert!(
                    GripperCommandGoal::from_record_batch(&batch).is_err(),
                    "accepted {difference}"
                );
            };

        let mut extra_fields = fields.clone();
        let mut extra_columns = columns.clone();
        extra_fields.push(Arc::new(Field::new("goal_id", DataType::Float64, false)));
        extra_columns.push(goal_batch.column(0).clone());
        assert_rejected(extra_fields, extra_columns, "an extra field");

        let mut reordered_fields = fields.clone();
        let mut reordered_columns = columns.clone();
        reordered_fields.swap(0, 1);
        reordered_columns.swap(0, 1);
        assert_rejected(reordered_fields, reordered_columns, "reordered fields");

        let mut wrong_type_fields = fields.clone();
        let mut wrong_type_columns = columns.clone();
        wrong_type_fields[0] = Arc::new(Field::new("position", DataType::Int64, false));
        wrong_type_columns[0] = Arc::new(Int64Array::from(vec![0]));
        assert_rejected(wrong_type_fields, wrong_type_columns, "a wrong field type");

        let mut wrong_nullability_fields = fields;
        wrong_nullability_fields[0] = Arc::new(Field::new("position", DataType::Float64, true));
        assert_rejected(wrong_nullability_fields, columns, "wrong field nullability");
    }

    #[test]
    fn all_move_joints_messages_roundtrip() {
        let goal = MoveJointsGoal::new(
            "arm",
            vec!["j1".into(), "j2".into()],
            vec![1.0, 2.0],
            0.5,
            0.4,
            None,
        )
        .unwrap();
        roundtrip(
            goal,
            |value| value.to_record_batch().unwrap(),
            |batch| MoveJointsGoal::from_record_batch(batch).unwrap(),
        );

        let feedback = MoveJointsFeedback::new(
            MotionPhase::Executing,
            Some(0.5),
            5,
            Some(10),
            vec!["j1".into(), "j2".into()],
            vec![0.5, 1.0],
            vec![1.0, 2.0],
            vec![],
            "moving",
        )
        .unwrap();
        roundtrip(
            feedback,
            |value| value.to_record_batch().unwrap(),
            |batch| MoveJointsFeedback::from_record_batch(batch).unwrap(),
        );

        let result = MoveJointsResult::new(
            MotionErrorCode::Success,
            "done",
            10,
            vec!["j1".into(), "j2".into()],
            vec![1.0, 2.0],
            vec![0.0, 0.0],
        )
        .unwrap();
        roundtrip(
            result,
            |value| value.to_record_batch().unwrap(),
            |batch| MoveJointsResult::from_record_batch(batch).unwrap(),
        );
    }

    #[test]
    fn all_move_pose_messages_roundtrip_with_nullable_structs() {
        let goal = MovePoseGoal::new(
            "arm",
            "world",
            "tool",
            pose(),
            0.5,
            0.4,
            Some(10),
            Some(0.01),
            None,
        )
        .unwrap();
        roundtrip(
            goal,
            |value| value.to_record_batch().unwrap(),
            |batch| MovePoseGoal::from_record_batch(batch).unwrap(),
        );

        let feedback = MovePoseFeedback::new(
            MotionPhase::Planning,
            None,
            1,
            None,
            None,
            None,
            Some(0.2),
            "planning",
        )
        .unwrap();
        let feedback_batch = feedback.to_record_batch().unwrap();
        assert!(feedback_batch.column(4).is_null(0));
        assert_eq!(
            MovePoseFeedback::from_record_batch(&feedback_batch).unwrap(),
            feedback
        );

        let result = MovePoseResult::new(
            MotionErrorCode::Success,
            "done",
            10,
            Some(pose()),
            Some(0.0),
            Some(0.0),
            vec!["j1".into()],
            vec![1.0],
        )
        .unwrap();
        roundtrip(
            result,
            |value| value.to_record_batch().unwrap(),
            |batch| MovePoseResult::from_record_batch(batch).unwrap(),
        );
    }

    #[test]
    fn enum_strings_cover_the_contract() {
        let follow = [
            (FollowJointTrajectoryErrorCode::Success, "SUCCESS"),
            (FollowJointTrajectoryErrorCode::InvalidGoal, "INVALID_GOAL"),
            (
                FollowJointTrajectoryErrorCode::InvalidJoints,
                "INVALID_JOINTS",
            ),
            (FollowJointTrajectoryErrorCode::Busy, "BUSY"),
            (
                FollowJointTrajectoryErrorCode::NoFreshRobotState,
                "NO_FRESH_ROBOT_STATE",
            ),
            (
                FollowJointTrajectoryErrorCode::StartStateMismatch,
                "START_STATE_MISMATCH",
            ),
            (
                FollowJointTrajectoryErrorCode::PathToleranceViolated,
                "PATH_TOLERANCE_VIOLATED",
            ),
            (
                FollowJointTrajectoryErrorCode::GoalToleranceViolated,
                "GOAL_TOLERANCE_VIOLATED",
            ),
            (
                FollowJointTrajectoryErrorCode::FeedbackStale,
                "FEEDBACK_STALE",
            ),
            (
                FollowJointTrajectoryErrorCode::ExecutionTimedOut,
                "EXECUTION_TIMED_OUT",
            ),
            (
                FollowJointTrajectoryErrorCode::HardwareFault,
                "HARDWARE_FAULT",
            ),
            (FollowJointTrajectoryErrorCode::Canceled, "CANCELED"),
            (
                FollowJointTrajectoryErrorCode::InternalError,
                "INTERNAL_ERROR",
            ),
        ];
        for (value, text) in follow {
            assert_eq!(value.as_str(), text);
            assert_eq!(
                FollowJointTrajectoryErrorCode::try_from(text).unwrap(),
                value
            );
        }

        let gripper_codes = [
            (GripperCommandErrorCode::Success, "SUCCESS"),
            (GripperCommandErrorCode::InvalidGoal, "INVALID_GOAL"),
            (GripperCommandErrorCode::Busy, "BUSY"),
            (
                GripperCommandErrorCode::PositionLimitViolation,
                "POSITION_LIMIT_VIOLATION",
            ),
            (
                GripperCommandErrorCode::UnsupportedVelocity,
                "UNSUPPORTED_VELOCITY",
            ),
            (
                GripperCommandErrorCode::UnsupportedEffort,
                "UNSUPPORTED_EFFORT",
            ),
            (
                GripperCommandErrorCode::NoFreshRobotState,
                "NO_FRESH_ROBOT_STATE",
            ),
            (GripperCommandErrorCode::FeedbackStale, "FEEDBACK_STALE"),
            (GripperCommandErrorCode::Stalled, "STALLED"),
            (
                GripperCommandErrorCode::ExecutionTimedOut,
                "EXECUTION_TIMED_OUT",
            ),
            (GripperCommandErrorCode::HardwareFault, "HARDWARE_FAULT"),
            (GripperCommandErrorCode::Canceled, "CANCELED"),
            (GripperCommandErrorCode::InternalError, "INTERNAL_ERROR"),
        ];
        for (value, text) in gripper_codes {
            assert_eq!(value.as_str(), text);
            assert_eq!(GripperCommandErrorCode::try_from(text).unwrap(), value);
        }

        let phases = [
            (MotionPhase::Validating, "VALIDATING"),
            (MotionPhase::Planning, "PLANNING"),
            (MotionPhase::WaitingForController, "WAITING_FOR_CONTROLLER"),
            (MotionPhase::Executing, "EXECUTING"),
            (MotionPhase::Settling, "SETTLING"),
        ];
        for (value, text) in phases {
            assert_eq!(MotionPhase::try_from(text).unwrap(), value);
        }

        let motion_codes = [
            (MotionErrorCode::Success, "SUCCESS"),
            (MotionErrorCode::InvalidGoal, "INVALID_GOAL"),
            (MotionErrorCode::Busy, "BUSY"),
            (MotionErrorCode::InvalidGroup, "INVALID_GROUP"),
            (MotionErrorCode::InvalidJoints, "INVALID_JOINTS"),
            (MotionErrorCode::InvalidFrame, "INVALID_FRAME"),
            (MotionErrorCode::NoFreshRobotState, "NO_FRESH_ROBOT_STATE"),
            (MotionErrorCode::IkFailed, "IK_FAILED"),
            (MotionErrorCode::IkTimedOut, "IK_TIMED_OUT"),
            (
                MotionErrorCode::JointLimitViolation,
                "JOINT_LIMIT_VIOLATION",
            ),
            (MotionErrorCode::PlanningFailed, "PLANNING_FAILED"),
            (
                MotionErrorCode::TrajectoryGenerationFailed,
                "TRAJECTORY_GENERATION_FAILED",
            ),
            (MotionErrorCode::TrajectoryRejected, "TRAJECTORY_REJECTED"),
            (
                MotionErrorCode::TrajectoryExecutionFailed,
                "TRAJECTORY_EXECUTION_FAILED",
            ),
            (
                MotionErrorCode::FinalJointToleranceViolated,
                "FINAL_JOINT_TOLERANCE_VIOLATED",
            ),
            (
                MotionErrorCode::FinalPoseToleranceViolated,
                "FINAL_POSE_TOLERANCE_VIOLATED",
            ),
            (MotionErrorCode::Canceled, "CANCELED"),
            (MotionErrorCode::InternalError, "INTERNAL_ERROR"),
        ];
        for (value, text) in motion_codes {
            assert_eq!(MotionErrorCode::try_from(text).unwrap(), value);
        }
        assert!(MotionPhase::try_from("executing").is_err());
    }

    #[test]
    fn schemas_match_field_order_nullability_and_exclude_dora_metadata() {
        let goal = FollowJointTrajectoryGoal::new(trajectory(), vec![], vec![], None)
            .unwrap()
            .to_record_batch()
            .unwrap();
        let fields = goal.schema().fields().clone();
        assert_eq!(
            fields.iter().map(|field| field.name()).collect::<Vec<_>>(),
            vec![
                "trajectory",
                "path_tolerance",
                "goal_tolerance",
                "goal_time_tolerance_ns"
            ]
        );
        assert!(!fields[0].is_nullable());
        assert!(!fields[1].is_nullable());
        assert!(!fields[2].is_nullable());
        assert!(fields[3].is_nullable());
        assert!(goal.schema().index_of("goal_id").is_err());
        assert!(goal.schema().index_of("goal_status").is_err());

        let gripper_goal = GripperCommandGoal::new(0.0, None, None)
            .unwrap()
            .to_record_batch()
            .unwrap();
        let gripper_fields = gripper_goal.schema().fields().clone();
        assert_eq!(
            gripper_fields
                .iter()
                .map(|field| field.name())
                .collect::<Vec<_>>(),
            vec!["position", "max_velocity", "max_effort"]
        );
        assert!(!gripper_fields[0].is_nullable());
        assert!(gripper_fields[1].is_nullable());
        assert!(gripper_fields[2].is_nullable());
        assert!(gripper_goal.schema().index_of("joint_name").is_err());
        assert!(gripper_goal.schema().index_of("goal_id").is_err());

        let feedback =
            MovePoseFeedback::new(MotionPhase::Validating, None, 0, None, None, None, None, "")
                .unwrap()
                .to_record_batch()
                .unwrap();
        let feedback_schema = feedback.schema();
        let actual_pose = feedback_schema.field(4);
        assert!(actual_pose.is_nullable());
        let DataType::Struct(pose_fields) = actual_pose.data_type() else {
            panic!("actual_pose must be struct")
        };
        assert_eq!(
            pose_fields
                .iter()
                .map(|field| field.name())
                .collect::<Vec<_>>(),
            vec!["x", "y", "z", "qx", "qy", "qz", "qw"]
        );
        assert!(pose_fields.iter().all(|field| !field.is_nullable()));
    }

    #[test]
    fn validates_gripper_command_values() {
        assert!(GripperCommandGoal::new(f64::INFINITY, None, None).is_err());
        assert!(GripperCommandGoal::new(0.0, Some(-0.1), None).is_err());
        assert!(GripperCommandGoal::new(0.0, None, Some(f64::NAN)).is_err());
        assert!(GripperCommandFeedback::new(-1, 0.0, None, None, false, false).is_err());
        assert!(
            GripperCommandFeedback::new(0, 0.0, Some(f64::INFINITY), None, false, false).is_err()
        );
        assert!(
            GripperCommandResult::new(
                GripperCommandErrorCode::Success,
                "",
                0,
                Some(f64::NAN),
                None,
                None,
                false,
                true,
            )
            .is_err()
        );
    }

    #[test]
    fn validates_gripper_command_result_flag_combinations() {
        let result = |error_code, stalled, reached_goal| {
            GripperCommandResult::new(error_code, "", 0, None, None, None, stalled, reached_goal)
        };

        assert!(result(GripperCommandErrorCode::Success, false, false).is_err());
        assert!(result(GripperCommandErrorCode::Success, true, true).is_err());
        assert!(result(GripperCommandErrorCode::Stalled, false, false).is_err());
        assert!(result(GripperCommandErrorCode::Stalled, false, true).is_err());
        assert!(result(GripperCommandErrorCode::Stalled, true, true).is_err());
        assert!(result(GripperCommandErrorCode::InternalError, true, true).is_err());

        assert!(result(GripperCommandErrorCode::Success, true, false).is_ok());
        assert!(result(GripperCommandErrorCode::Success, false, true).is_ok());
        assert!(result(GripperCommandErrorCode::Stalled, true, false).is_ok());
        assert!(result(GripperCommandErrorCode::InternalError, false, false).is_ok());
        assert!(result(GripperCommandErrorCode::InternalError, true, false).is_ok());
        assert!(result(GripperCommandErrorCode::InternalError, false, true).is_ok());
    }

    #[test]
    fn validates_goal_tolerances_scales_progress_and_lengths() {
        assert!(
            FollowJointTrajectoryGoal::new(
                trajectory(),
                vec![JointTolerance::new("unknown", Some(0.1), None, None).unwrap()],
                vec![],
                None,
            )
            .is_err()
        );
        assert!(
            MoveJointsGoal::new("arm", vec!["j1".into()], vec![f64::NAN], 0.5, 0.5, None,).is_err()
        );
        assert!(MoveJointsGoal::new("arm", vec!["j1".into()], vec![1.0], 0.0, 0.5, None,).is_err());
        assert!(
            MoveJointsFeedback::new(
                MotionPhase::Executing,
                Some(1.1),
                0,
                None,
                vec!["j1".into()],
                vec![],
                vec![1.0],
                vec![],
                "",
            )
            .is_err()
        );
        assert!(
            MoveJointsResult::new(
                MotionErrorCode::Success,
                "",
                0,
                vec!["j1".into(), "j2".into()],
                vec![1.0],
                vec![],
            )
            .is_err()
        );
    }

    #[test]
    fn validates_pose_fields_times_and_errors() {
        assert!(
            MovePoseGoal::new("", "world", "tool", pose(), 0.5, 0.5, None, None, None,).is_err()
        );
        assert!(
            MovePoseGoal::new(
                "arm",
                "world",
                "tool",
                pose(),
                0.5,
                0.5,
                Some(-1),
                None,
                None,
            )
            .is_err()
        );
        assert!(
            MovePoseFeedback::new(MotionPhase::Executing, None, -1, None, None, None, None, "",)
                .is_err()
        );
        assert!(
            MovePoseResult::new(
                MotionErrorCode::Success,
                "",
                0,
                None,
                Some(f64::NAN),
                None,
                vec![],
                vec![],
            )
            .is_err()
        );
    }

    #[test]
    fn nullable_values_roundtrip_as_none_and_zero_as_some() {
        let feedback = MoveJointsFeedback::new(
            MotionPhase::Planning,
            Some(0.0),
            0,
            None,
            vec!["j1".into()],
            vec![],
            vec![1.0],
            vec![],
            "",
        )
        .unwrap();
        let batch = feedback.to_record_batch().unwrap();
        assert!(!batch.column(1).is_null(0));
        assert!(batch.column(3).is_null(0));
        assert_eq!(
            MoveJointsFeedback::from_record_batch(&batch).unwrap(),
            feedback
        );

        let result = MovePoseResult::new(
            MotionErrorCode::PlanningFailed,
            "no plan",
            3,
            None,
            None,
            None,
            vec![],
            vec![],
        )
        .unwrap();
        let batch = result.to_record_batch().unwrap();
        assert!(batch.column(3).is_null(0));
        assert!(batch.column(4).is_null(0));
        assert!(batch.column(5).is_null(0));
        assert_eq!(MovePoseResult::from_record_batch(&batch).unwrap(), result);
    }
}
