from forge_robots_core.value import ActuatorValue
from forge_robots_core.base import BaseActuator


def ensure_safe_actuator_values(
    action: list[ActuatorValue], actuator_map: dict[str, BaseActuator]
) -> list[ActuatorValue]:
    safe_action = []

    for val in action:
        actuator = actuator_map.get(val.name)
        if not actuator:
            continue

        clipped_val = max(min(val.value, actuator.max_value), actuator.min_value)
        safe_action.append(ActuatorValue(name=val.name, value=clipped_val))

    return safe_action
