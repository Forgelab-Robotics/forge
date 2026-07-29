"""Pinocchio-backed robot states, contexts, and kinematic-group models."""

from __future__ import annotations

import importlib
import math
import os
import xml.etree.ElementTree as ET
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from numbers import Real
from pathlib import Path
from typing import Any, Self

import numpy as np
import numpy.typing as npt

try:
    pin: Any = importlib.import_module("pinocchio")
except ImportError:  # pragma: no cover - only without the optional backend.
    pin = None

type FloatArray = npt.NDArray[np.float64]
_SUPPORTED_JOINT_TYPES = frozenset({"revolute", "continuous", "prismatic"})


@dataclass(frozen=True)
class _UrdfJoint:
    name: str
    joint_type: str
    parent_link: str
    child_link: str
    mimic_joint: str | None


@dataclass(frozen=True)
class _JointMetadata:
    name: str
    joint_type: str
    joint_id: int
    idx_q: int
    nq: int
    idx_v: int
    lower: float
    upper: float


@dataclass(frozen=True)
class _GroupEvaluation:
    poses: dict[str, FloatArray]
    jacobians: dict[str, FloatArray]


def _write_public_position(
    q: FloatArray, joint: _JointMetadata, position: float
) -> None:
    if joint.joint_type == "continuous":
        q[joint.idx_q] = math.cos(position)
        q[joint.idx_q + 1] = math.sin(position)
    else:
        q[joint.idx_q] = position


def _read_public_position(q: FloatArray, joint: _JointMetadata) -> float:
    if joint.joint_type == "continuous":
        return math.atan2(q[joint.idx_q + 1], q[joint.idx_q])
    return float(q[joint.idx_q])


def _nonempty_name(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    if not value.strip():
        raise ValueError(f"{field} must not be empty")
    return value


def _name_tuple(values: object, field: str, *, allow_empty: bool) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise TypeError(f"{field} must be a sequence of strings")
    result = tuple(_nonempty_name(value, field) for value in values)
    if not allow_empty and not result:
        raise ValueError(f"{field} must not be empty")
    seen: set[str] = set()
    for name in result:
        if name in seen:
            raise ValueError(f"{field} contains duplicate name {name!r}")
        seen.add(name)
    return result


def _positions_vector(value: object, size: int, field: str) -> FloatArray:
    try:
        result = np.array(value, dtype=np.float64, copy=True)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{field} must be a numeric vector") from exc
    if result.shape != (size,):
        raise ValueError(f"{field} must have shape ({size},)")
    if not np.all(np.isfinite(result)):
        raise ValueError(f"{field} must contain only finite values")
    return result


def _parse_urdf(path: Path) -> tuple[frozenset[str], dict[str, _UrdfJoint]]:
    try:
        tree = ET.parse(path)
    except ET.ParseError as exc:
        raise ValueError(f"failed to parse URDF XML {path}: {exc}") from exc
    except OSError as exc:
        raise OSError(f"failed to read URDF {path}: {exc}") from exc

    root = tree.getroot()
    if root.tag != "robot":
        raise ValueError(f"URDF root element in {path} must be <robot>")

    links: set[str] = set()
    for element in root.findall("link"):
        name = element.get("name")
        if name is None or not name.strip():
            raise ValueError(f"URDF {path} contains a link without a name")
        if name in links:
            raise ValueError(f"URDF {path} contains duplicate link {name!r}")
        links.add(name)
    if not links:
        raise ValueError(f"URDF {path} does not define any links")

    joints: dict[str, _UrdfJoint] = {}
    child_joints: dict[str, str] = {}
    for element in root.findall("joint"):
        name = element.get("name")
        joint_type = element.get("type")
        parent_element = element.find("parent")
        child_element = element.find("child")
        parent_link = None if parent_element is None else parent_element.get("link")
        child_link = None if child_element is None else child_element.get("link")
        if name is None or not name.strip():
            raise ValueError(f"URDF {path} contains a joint without a name")
        if name in joints:
            raise ValueError(f"URDF {path} contains duplicate joint {name!r}")
        if joint_type is None or not joint_type.strip():
            raise ValueError(f"URDF joint {name!r} does not define a type")
        if parent_link is None or not parent_link.strip():
            raise ValueError(f"URDF joint {name!r} does not define a parent link")
        if child_link is None or not child_link.strip():
            raise ValueError(f"URDF joint {name!r} does not define a child link")
        if parent_link not in links:
            raise ValueError(
                f"URDF joint {name!r} references unknown parent link {parent_link!r}"
            )
        if child_link not in links:
            raise ValueError(
                f"URDF joint {name!r} references unknown child link {child_link!r}"
            )
        if child_link in child_joints:
            raise ValueError(
                f"URDF link {child_link!r} has multiple parent joints: "
                f"{child_joints[child_link]!r} and {name!r}"
            )

        mimic_element = element.find("mimic")
        mimic_joint = None
        if mimic_element is not None:
            mimic_joint = mimic_element.get("joint")
            if mimic_joint is None or not mimic_joint.strip():
                raise ValueError(f"URDF joint {name!r} has an invalid mimic element")

        joints[name] = _UrdfJoint(
            name=name,
            joint_type=joint_type,
            parent_link=parent_link,
            child_link=child_link,
            mimic_joint=mimic_joint,
        )
        child_joints[child_link] = name

    for joint in joints.values():
        if joint.mimic_joint is not None and joint.mimic_joint not in joints:
            raise ValueError(
                f"URDF joint {joint.name!r} mimics unknown joint {joint.mimic_joint!r}"
            )

    return frozenset(links), joints


class RobotModel:
    """A complete fixed-base Pinocchio model plus its URDF topology."""

    __slots__ = (
        "_joints",
        "_links",
        "_model",
        "_neutral_q",
        "_path",
        "_position_joints",
    )

    def __init__(
        self,
        path: Path,
        model: Any,
        links: frozenset[str],
        joints: dict[str, _UrdfJoint],
    ) -> None:
        self._path = path
        self._model = model
        self._links = links
        self._joints = dict(joints)
        self._position_joints: dict[str, _JointMetadata] = {}
        for joint in self._joints.values():
            if (
                joint.mimic_joint is not None
                or joint.joint_type not in _SUPPORTED_JOINT_TYPES
            ):
                continue
            try:
                metadata = self._build_joint_metadata(joint, "model")
            except ValueError:
                continue
            self._position_joints[joint.name] = metadata
        self._neutral_q = self._make_neutral_configuration()

    @classmethod
    def from_urdf(cls, path: str | os.PathLike[str]) -> Self:
        """Load a complete fixed-base model without visual/collision geometry."""

        try:
            urdf_path = Path(path).expanduser()
        except TypeError as exc:
            raise TypeError("path must be a string or path-like object") from exc
        if not urdf_path.exists():
            raise FileNotFoundError(f"URDF file does not exist: {urdf_path}")
        if not urdf_path.is_file():
            raise ValueError(f"URDF path is not a file: {urdf_path}")

        links, joints = _parse_urdf(urdf_path)
        if pin is None:
            raise ImportError(
                "pinocchio is required to load RobotModel; install the optional "
                "kinematics backend"
            )
        try:
            model = pin.buildModelFromUrdf(str(urdf_path))
        except Exception as exc:
            raise ValueError(
                f"failed to build fixed-base Pinocchio model from {urdf_path}: {exc}"
            ) from exc
        return cls(urdf_path, model, links, joints)

    def create_group(
        self,
        name: str,
        joint_names: Sequence[str],
        base_frame: str,
        tip_frames: Sequence[str],
        locked_joint_positions: Mapping[str, float] | None = None,
    ) -> KinematicGroup:
        """Create a validated group while preserving caller-provided joint order."""

        return KinematicGroup(
            robot_model=self,
            name=name,
            joint_names=joint_names,
            base_frame=base_frame,
            tip_frames=tip_frames,
            locked_joint_positions=locked_joint_positions,
        )

    def create_state(
        self, joint_positions: Mapping[str, float] | None = None
    ) -> RobotState:
        """Create a complete state at projected neutral, then apply named positions."""

        return RobotState(self, joint_positions)

    def create_context(self) -> KinematicsContext:
        """Create mutable, model-bound Pinocchio evaluation storage."""

        return KinematicsContext(self)

    def _build_joint_metadata(
        self, urdf_joint: _UrdfJoint, role: str
    ) -> _JointMetadata:
        if not self._model.existJointName(urdf_joint.name):
            raise ValueError(
                f"{role} joint {urdf_joint.name!r} is not an independent "
                "Pinocchio joint"
            )
        joint_id = int(self._model.getJointId(urdf_joint.name))
        joint_model = self._model.joints[joint_id]
        nq = int(joint_model.nq)
        nv = int(joint_model.nv)
        expected_nq = 2 if urdf_joint.joint_type == "continuous" else 1
        if nq != expected_nq or nv != 1:
            raise ValueError(
                f"{role} joint {urdf_joint.name!r} must be an independent "
                f"single-DOF {urdf_joint.joint_type} joint; Pinocchio reports "
                f"nq={nq}, nv={nv}"
            )
        idx_q = int(joint_model.idx_q)
        idx_v = int(joint_model.idx_v)
        if urdf_joint.joint_type == "continuous":
            lower = -math.inf
            upper = math.inf
        else:
            lower = float(self._model.lowerPositionLimit[idx_q])
            upper = float(self._model.upperPositionLimit[idx_q])
            if math.isnan(lower) or math.isnan(upper) or lower > upper:
                raise ValueError(
                    f"{role} joint {urdf_joint.name!r} has invalid position limits"
                )
        return _JointMetadata(
            name=urdf_joint.name,
            joint_type=urdf_joint.joint_type,
            joint_id=joint_id,
            idx_q=idx_q,
            nq=nq,
            idx_v=idx_v,
            lower=lower,
            upper=upper,
        )

    def _position_joint(self, name: object, role: str) -> _JointMetadata:
        joint_name = _nonempty_name(name, f"{role} joint name")
        urdf_joint = self._joints.get(joint_name)
        if urdf_joint is None:
            raise ValueError(f"unknown {role} joint {joint_name!r}")
        if urdf_joint.mimic_joint is not None:
            raise ValueError(f"{role} joint {joint_name!r} must not be a mimic joint")
        if urdf_joint.joint_type not in _SUPPORTED_JOINT_TYPES:
            raise ValueError(
                f"{role} joint {joint_name!r} has unsupported type "
                f"{urdf_joint.joint_type!r}"
            )
        metadata = self._position_joints.get(joint_name)
        if metadata is not None:
            return metadata
        return self._build_joint_metadata(urdf_joint, role)

    @staticmethod
    def _validated_position(
        joint: _JointMetadata, raw_position: object, role: str
    ) -> float:
        if isinstance(raw_position, bool) or not isinstance(raw_position, Real):
            raise TypeError(f"{role} joint {joint.name!r} position must be real")
        try:
            position = float(raw_position)
        except OverflowError as exc:
            raise ValueError(
                f"{role} joint {joint.name!r} position must be finite"
            ) from exc
        if not math.isfinite(position):
            raise ValueError(f"{role} joint {joint.name!r} position must be finite")
        if joint.joint_type != "continuous" and not (
            joint.lower <= position <= joint.upper
        ):
            raise ValueError(
                f"{role} joint {joint.name!r} position {position} is outside "
                f"[{joint.lower}, {joint.upper}]"
            )
        return position

    def _apply_joint_positions(
        self,
        q: FloatArray,
        joint_positions: Mapping[str, float],
        role: str,
    ) -> None:
        for name, raw_position in joint_positions.items():
            joint = self._position_joint(name, role)
            position = self._validated_position(joint, raw_position, role)
            _write_public_position(q, joint, position)

    def _make_neutral_configuration(self) -> FloatArray:
        assert pin is not None
        q = np.array(pin.neutral(self._model), dtype=np.float64, copy=True)
        if q.shape != (self._model.nq,) or not np.all(np.isfinite(q)):
            raise FloatingPointError("Pinocchio neutral configuration is invalid")
        for joint in self._position_joints.values():
            position = _read_public_position(q, joint)
            if joint.joint_type != "continuous":
                position = float(np.clip(position, joint.lower, joint.upper))
            _write_public_position(q, joint, position)
        return q

    def _neutral_configuration(self) -> FloatArray:
        return self._neutral_q.copy()

    def _link_frame_id(self, name: str) -> int:
        assert pin is not None
        for frame_id, frame in enumerate(self._model.frames):
            if frame.name == name and frame.type == pin.FrameType.BODY:
                return frame_id
        raise ValueError(f"link {name!r} has no Pinocchio body frame")

    def _joint_path(self, base_link: str, tip_link: str) -> tuple[str, ...]:
        parent_joint_by_child = {
            joint.child_link: joint for joint in self._joints.values()
        }
        path: list[str] = []
        current = tip_link
        visited: set[str] = set()
        while current != base_link:
            if current in visited:
                raise ValueError(f"URDF topology contains a cycle at link {current!r}")
            visited.add(current)
            parent_joint = parent_joint_by_child.get(current)
            if parent_joint is None:
                raise ValueError(
                    f"tip frame {tip_link!r} is not a descendant of base frame "
                    f"{base_link!r}"
                )
            path.append(parent_joint.name)
            current = parent_joint.parent_link
        path.reverse()
        return tuple(path)


class RobotState:
    """A complete named-joint configuration bound to one :class:`RobotModel`."""

    __slots__ = ("_q", "_robot_model")

    def __init__(
        self,
        robot_model: RobotModel,
        joint_positions: Mapping[str, float] | None = None,
    ) -> None:
        if not isinstance(robot_model, RobotModel):
            raise TypeError("robot_model must be a RobotModel")
        if joint_positions is None:
            positions: Mapping[str, float] = {}
        elif isinstance(joint_positions, Mapping):
            positions = joint_positions
        else:
            raise TypeError("joint_positions must be a mapping or None")

        self._robot_model = robot_model
        self._q = robot_model._neutral_configuration()
        robot_model._apply_joint_positions(self._q, positions, "state")

    @classmethod
    def _from_configuration(cls, robot_model: RobotModel, q: FloatArray) -> RobotState:
        state = cls.__new__(cls)
        state._robot_model = robot_model
        state._q = np.array(q, dtype=np.float64, copy=True)
        return state

    @property
    def robot_model(self) -> RobotModel:
        return self._robot_model

    @property
    def joint_positions(self) -> dict[str, float]:
        return {
            name: _read_public_position(self._q, joint)
            for name, joint in self._robot_model._position_joints.items()
        }

    def position(self, name: str) -> float:
        joint = self._robot_model._position_joint(name, "state")
        return _read_public_position(self._q, joint)

    def with_joint_positions(self, joint_positions: Mapping[str, float]) -> RobotState:
        if not isinstance(joint_positions, Mapping):
            raise TypeError("joint_positions must be a mapping")
        q = self._q.copy()
        self._robot_model._apply_joint_positions(q, joint_positions, "state")
        return self._from_configuration(self._robot_model, q)

    def copy(self) -> RobotState:
        return self._from_configuration(self._robot_model, self._q)


class KinematicsContext:
    """Mutable per-thread Pinocchio storage bound to exactly one robot model.

    Contexts may be reused across related evaluations, but must not be shared by
    concurrent threads or used with groups from another :class:`RobotModel`.
    """

    __slots__ = ("_data", "_robot_model")

    def __init__(self, robot_model: RobotModel) -> None:
        if not isinstance(robot_model, RobotModel):
            raise TypeError("robot_model must be a RobotModel")
        self._robot_model = robot_model
        self._data = robot_model._model.createData()

    @property
    def robot_model(self) -> RobotModel:
        return self._robot_model


class KinematicGroup:
    """An ordered active-joint view into a complete :class:`RobotModel`."""

    __slots__ = (
        "_active_joints",
        "_active_velocity_indices",
        "_base_frame",
        "_base_frame_id",
        "_locked_joints",
        "_lower_limits",
        "_model",
        "_name",
        "_neutral_positions",
        "_robot_model",
        "_tip_frame_ids",
        "_tip_frames",
        "_upper_limits",
    )

    def __init__(
        self,
        *,
        robot_model: RobotModel,
        name: str,
        joint_names: Sequence[str],
        base_frame: str,
        tip_frames: Sequence[str],
        locked_joint_positions: Mapping[str, float] | None,
    ) -> None:
        if pin is None:  # Defensive: RobotModel construction already enforces this.
            raise ImportError("pinocchio is required to create KinematicGroup")

        self._robot_model = robot_model
        self._model = robot_model._model
        self._name = _nonempty_name(name, "name")
        ordered_joint_names = _name_tuple(joint_names, "joint_names", allow_empty=False)
        self._base_frame = _nonempty_name(base_frame, "base_frame")
        self._tip_frames = _name_tuple(tip_frames, "tip_frames", allow_empty=False)

        if self._base_frame not in robot_model._links:
            raise ValueError(f"base_frame {self._base_frame!r} is not a URDF link")
        for tip_frame in self._tip_frames:
            if tip_frame not in robot_model._links:
                raise ValueError(f"tip frame {tip_frame!r} is not a URDF link")

        paths = {
            tip_frame: robot_model._joint_path(self._base_frame, tip_frame)
            for tip_frame in self._tip_frames
        }
        path_joints = set().union(*(set(path) for path in paths.values()))

        active_joints: list[_JointMetadata] = []
        for joint_name in ordered_joint_names:
            active_joint = robot_model._position_joint(joint_name, "active")
            if joint_name not in path_joints:
                raise ValueError(
                    f"active joint {joint_name!r} is not on a descendant path from "
                    f"base frame {self._base_frame!r} to any configured tip"
                )
            active_joints.append(active_joint)

        if locked_joint_positions is None:
            locked_positions: dict[str, float] = {}
        elif isinstance(locked_joint_positions, Mapping):
            locked_positions = dict(locked_joint_positions)
        else:
            raise TypeError("locked_joint_positions must be a mapping or None")
        overlap = set(ordered_joint_names).intersection(locked_positions)
        if overlap:
            names = ", ".join(sorted(overlap))
            raise ValueError(f"locked joints overlap active joints: {names}")

        locked_joints: list[tuple[_JointMetadata, float]] = []
        for joint_name, raw_position in locked_positions.items():
            locked_joint = robot_model._position_joint(joint_name, "locked")
            position = robot_model._validated_position(
                locked_joint, raw_position, "locked"
            )
            locked_joints.append((locked_joint, position))

        declared_joints = set(ordered_joint_names) | set(locked_positions)
        unrelated_locks = sorted(set(locked_positions) - path_joints)
        if unrelated_locks:
            raise ValueError(
                "locked joints are not on a configured base-to-tip path: "
                f"{unrelated_locks}"
            )
        for tip_frame, path in paths.items():
            for joint_name in path:
                path_joint = robot_model._joints[joint_name]
                if path_joint.joint_type == "fixed":
                    continue
                if path_joint.mimic_joint is not None:
                    raise ValueError(
                        f"path to tip {tip_frame!r} contains unsupported mimic joint "
                        f"{joint_name!r}"
                    )
                if path_joint.joint_type not in _SUPPORTED_JOINT_TYPES:
                    raise ValueError(
                        f"path to tip {tip_frame!r} contains unsupported joint "
                        f"{joint_name!r} of type {path_joint.joint_type!r}"
                    )
                if joint_name not in declared_joints:
                    raise ValueError(
                        f"path joint {joint_name!r} must be active or explicitly locked"
                    )

        self._active_joints = tuple(active_joints)
        self._locked_joints = tuple(locked_joints)
        self._active_velocity_indices = np.array(
            [joint.idx_v for joint in active_joints], dtype=np.int64
        )
        self._base_frame_id = robot_model._link_frame_id(self._base_frame)
        self._tip_frame_ids = {
            tip_frame: robot_model._link_frame_id(tip_frame)
            for tip_frame in self._tip_frames
        }
        self._lower_limits = np.array(
            [joint.lower for joint in active_joints], dtype=np.float64
        )
        self._upper_limits = np.array(
            [joint.upper for joint in active_joints], dtype=np.float64
        )
        neutral_q = robot_model._neutral_configuration()
        neutral_positions: list[float] = []
        for joint in active_joints:
            position = _read_public_position(neutral_q, joint)
            if joint.joint_type != "continuous":
                position = float(np.clip(position, joint.lower, joint.upper))
            neutral_positions.append(position)
        self._neutral_positions = np.array(neutral_positions, dtype=np.float64)

    def _configuration(
        self,
        positions: object,
        state: RobotState | None = None,
        *,
        validate_limits: bool = False,
    ) -> FloatArray:
        public_positions = _positions_vector(
            positions, len(self._active_joints), "positions"
        )
        if state is None:
            q = self._robot_model._neutral_configuration()
        else:
            if not isinstance(state, RobotState):
                raise TypeError("state must be a RobotState or None")
            if state.robot_model is not self._robot_model:
                raise ValueError("state belongs to a different RobotModel")
            q = state._q.copy()

        for joint, position in self._locked_joints:
            _write_public_position(q, joint, position)
        for joint, position in zip(self._active_joints, public_positions, strict=True):
            public_position = float(position)
            if validate_limits:
                public_position = self._robot_model._validated_position(
                    joint, public_position, "active"
                )
            _write_public_position(q, joint, public_position)
        return q

    def _evaluation_data(self, context: KinematicsContext | None) -> Any:
        if context is None:
            return self._robot_model.create_context()._data
        if not isinstance(context, KinematicsContext):
            raise TypeError("context must be a KinematicsContext or None")
        if context.robot_model is not self._robot_model:
            raise ValueError("context belongs to a different RobotModel")
        return context._data

    def _selected_tip(self, tip_frame: str | None) -> str:
        if tip_frame is None:
            if len(self._tip_frames) != 1:
                raise ValueError("tip_frame is required for groups with multiple tips")
            return self._tip_frames[0]
        tip = _nonempty_name(tip_frame, "tip_frame")
        if tip not in self._tip_frame_ids:
            raise ValueError(f"tip frame {tip!r} is not configured for this group")
        return tip

    @property
    def robot_model(self) -> RobotModel:
        return self._robot_model

    @property
    def name(self) -> str:
        return self._name

    @property
    def joint_names(self) -> tuple[str, ...]:
        return tuple(joint.name for joint in self._active_joints)

    @property
    def base_frame(self) -> str:
        return self._base_frame

    @property
    def tip_frames(self) -> tuple[str, ...]:
        return self._tip_frames

    @property
    def lower_limits(self) -> FloatArray:
        return self._lower_limits.copy()

    @property
    def upper_limits(self) -> FloatArray:
        return self._upper_limits.copy()

    @property
    def neutral_positions(self) -> FloatArray:
        return self._neutral_positions.copy()

    def forward(
        self,
        positions: object,
        tip_frame: str | None = None,
        *,
        state: RobotState | None = None,
        context: KinematicsContext | None = None,
    ) -> FloatArray:
        """Return the homogeneous transform ``T_base_tip``."""

        selected_tip = self._selected_tip(tip_frame)
        return (
            self._evaluate(positions, (selected_tip,), state=state, context=context)
            .poses[selected_tip]
            .copy()
        )

    def forward_all(
        self,
        positions: object,
        *,
        state: RobotState | None = None,
        context: KinematicsContext | None = None,
    ) -> dict[str, FloatArray]:
        """Return all configured ``T_base_tip`` transforms in tip order."""

        evaluation = self._evaluate(
            positions, self._tip_frames, state=state, context=context
        )
        return {tip: evaluation.poses[tip].copy() for tip in self._tip_frames}

    def jacobian(
        self,
        positions: object,
        tip_frame: str | None = None,
        *,
        state: RobotState | None = None,
        context: KinematicsContext | None = None,
    ) -> FloatArray:
        """Return a base-aligned geometric Jacobian with linear rows first."""

        selected_tip = self._selected_tip(tip_frame)
        return (
            self._evaluate(positions, (selected_tip,), state=state, context=context)
            .jacobians[selected_tip]
            .copy()
        )

    def to_robot_state(
        self, positions: object, state: RobotState | None = None
    ) -> RobotState:
        """Apply permanent locks and active positions to a complete robot state."""

        q = self._configuration(positions, state, validate_limits=True)
        return RobotState._from_configuration(self._robot_model, q)

    def integrate(self, positions: object, delta: object) -> FloatArray:
        """Integrate an ordered tangent step and enforce public joint semantics."""

        q = self._configuration(positions)
        public_delta = _positions_vector(delta, len(self._active_joints), "delta")
        velocity = np.zeros(self._model.nv, dtype=np.float64)
        for joint, value in zip(self._active_joints, public_delta, strict=True):
            velocity[joint.idx_v] = float(value)
        integrated = np.array(
            pin.integrate(self._model, q, velocity), dtype=np.float64, copy=True
        )
        if not np.all(np.isfinite(integrated)):
            raise FloatingPointError("Pinocchio integration produced non-finite values")

        result = np.empty(len(self._active_joints), dtype=np.float64)
        for index, joint in enumerate(self._active_joints):
            position = _read_public_position(integrated, joint)
            if joint.joint_type != "continuous":
                position = float(np.clip(position, joint.lower, joint.upper))
            result[index] = position
        if not np.all(np.isfinite(result)):
            raise FloatingPointError("joint integration produced non-finite positions")
        return result

    def difference(self, start: object, end: object) -> FloatArray:
        """Return the caller-ordered tangent displacement from ``start`` to ``end``."""

        start_q = self._configuration(start)
        end_q = self._configuration(end)
        full_delta = np.array(
            pin.difference(self._model, start_q, end_q),
            dtype=np.float64,
            copy=True,
        )
        if full_delta.shape != (self._model.nv,) or not np.all(np.isfinite(full_delta)):
            raise FloatingPointError("Pinocchio difference produced invalid values")
        return full_delta[self._active_velocity_indices].copy()

    def _evaluate(
        self,
        positions: object,
        tip_frames: Sequence[str] | None = None,
        state: RobotState | None = None,
        context: KinematicsContext | None = None,
    ) -> _GroupEvaluation:
        """Evaluate multiple tips with one model-bound Pinocchio data/FK pass."""

        if tip_frames is None:
            selected_tips = self._tip_frames
        else:
            selected_tips = _name_tuple(tip_frames, "tip_frames", allow_empty=False)
            unknown = [tip for tip in selected_tips if tip not in self._tip_frame_ids]
            if unknown:
                raise ValueError(
                    f"tip frames are not configured for this group: {unknown}"
                )

        q = self._configuration(positions, state)
        data = self._evaluation_data(context)
        pin.computeJointJacobians(self._model, data, q)
        pin.updateFramePlacements(self._model, data)

        base_placement = data.oMf[self._base_frame_id]
        world_to_base_rotation = np.array(
            base_placement.rotation.T, dtype=np.float64, copy=True
        )
        poses: dict[str, FloatArray] = {}
        jacobians: dict[str, FloatArray] = {}
        for tip_frame in selected_tips:
            tip_frame_id = self._tip_frame_ids[tip_frame]
            relative = base_placement.inverse() * data.oMf[tip_frame_id]
            pose = np.array(relative.homogeneous, dtype=np.float64, copy=True)

            full_jacobian = np.array(
                pin.getFrameJacobian(
                    self._model,
                    data,
                    tip_frame_id,
                    pin.ReferenceFrame.LOCAL_WORLD_ALIGNED,
                ),
                dtype=np.float64,
                copy=True,
            )
            if full_jacobian.ndim == 1:
                full_jacobian = full_jacobian.reshape(6, self._model.nv)
            jacobian = full_jacobian[:, self._active_velocity_indices].copy()
            jacobian[:3, :] = world_to_base_rotation @ jacobian[:3, :]
            jacobian[3:, :] = world_to_base_rotation @ jacobian[3:, :]
            if not np.all(np.isfinite(pose)) or not np.all(np.isfinite(jacobian)):
                raise FloatingPointError(
                    f"Pinocchio evaluation for tip {tip_frame!r} was non-finite"
                )
            poses[tip_frame] = pose
            jacobians[tip_frame] = jacobian
        return _GroupEvaluation(poses=poses, jacobians=jacobians)
