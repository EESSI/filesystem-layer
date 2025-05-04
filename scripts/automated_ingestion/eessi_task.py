from enum import Enum, auto

from eessi_task_action import EESSITaskAction
from eessi_task_description import EESSITaskDescription

class TaskState(Enum):
    NEW = auto()  # The task has been created but not yet processed
    STAGED = auto()  # The task has been staged to the Stratum-0
    PR_OPENED = auto()  # The task has been opened as a PR in some staging repository
    APPROVED = auto()  # The task has been approved
    REJECTED = auto()  # The task has been rejected
    INGESTED = auto()  # The task has been ingested into the target CernVM-FS repository

    def __str__(self):
        return self.name.lower()

class EESSITask:
    task_description: EESSITaskDescription
    action: EESSITaskAction
    state: TaskState

    def __init__(self, task_description: EESSITaskDescription):
        self.task_description = task_description
        self.action = self._determine_action()
        self.state = TaskState.NEW

        # Define valid state transitions for all actions
        self.valid_transitions = {
            TaskState.NEW: [TaskState.STAGED],
            TaskState.STAGED: [TaskState.PR_OPENED],
            TaskState.PR_OPENED: [TaskState.APPROVED, TaskState.REJECTED],
            TaskState.APPROVED: [TaskState.INGESTED],
            TaskState.REJECTED: [],  # Terminal state
            TaskState.INGESTED: []   # Terminal state
        }

    def _determine_action(self) -> EESSITaskAction:
        """
        Determine the action type based on task description metadata.
        """
        if 'task' in self.task_description.metadata and 'action' in self.task_description.metadata['task']:
            action_str = self.task_description.metadata['task']['action'].lower()
            if action_str == "nop":
                return EESSITaskAction.NOP
            elif action_str == "delete":
                return EESSITaskAction.DELETE
            elif action_str == "add":
                return EESSITaskAction.ADD
            elif action_str == "update":
                return EESSITaskAction.UPDATE
        return EESSITaskAction.UNKNOWN

    def handle(self):
        """
        Dynamically find and execute the appropriate handler based on action and state.
        """
        state_before_handle = self.state

        # Construct handler method name
        handler_name = f"_handle_{self.action}_{self.state}"

        # Check if the handler exists
        handler = getattr(self, handler_name, None)

        if handler and callable(handler):
            # Execute the handler if it exists
            handler()
            # if state has changed, run handle() again; otherwise, do nothing
            if self.state != state_before_handle:
                print(f"handler {handler_name} changed state from {state_before_handle} to {self.state} ; running handle() again")
                self.handle()
        else:
            # Default behavior for missing handlers
            print(f"No handler for action {self.action} and state {self.state} implemented; nothing to be done")

    # Implement handlers for ADD action
    def _handle_add_new(self):
        """Handler for ADD action in NEW state"""
        print("Handling ADD action in NEW state")
        # Implementation for adding in NEW state
        return True

    def _handle_add_staged(self):
        """Handler for ADD action in STAGED state"""
        print("Handling ADD action in STAGED state")
        # Implementation for adding in STAGED state
        return True

    def _handle_add_pr_opened(self):
        """Handler for ADD action in PR_OPENED state"""
        print("Handling ADD action in PR_OPENED state")
        # Implementation for adding in PR_OPENED state
        return True

    def _handle_add_approved(self):
        """Handler for ADD action in APPROVED state"""
        print("Handling ADD action in APPROVED state")
        # Implementation for adding in APPROVED state
        return True

    def _handle_add_ingested(self):
        """Handler for ADD action in INGESTED state"""
        print("Handling ADD action in INGESTED state")
        # Implementation for adding in INGESTED state
        return True

    def transition_to(self, new_state: TaskState):
        """
        Transition the task to a new state if valid.
        """
        if new_state in self.valid_transitions[self.state]:
            self.state = new_state
            return True
        return False

    def __str__(self):
        return f"EESSITask(task_description={self.task_description})"