from __future__ import annotations
import abc

class BaseActuator:
    def __init__(self, name: str, id: int, control_mode: str, min_value: float, max_value: float):
        self.name = name
        self.id = id
        self.control_mode = control_mode
        self.min_value = min_value
        self.max_value = max_value
    

class BaseJoint(abc.ABC):
  """
  关节基类，显式定义关节的相关数据信息
  """
  def __init__(self, name: str, mode: str):
    self.name = name
    self.mode = mode