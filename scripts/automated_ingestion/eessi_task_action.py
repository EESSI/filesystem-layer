from enum import Enum, auto

class EESSITaskAction(Enum):
    NOP = auto()  # perform no action
    DELETE = auto()  # perform a delete operation
    ADD = auto()  # perform an add operation
    UPDATE = auto()  # perform an update operation
    UNKNOWN = auto()  # unknown action

    def __str__(self):
        return self.name.lower()
