from enum import Enum, auto
from typing import Dict
from eessi_task_action import EESSITaskAction
from eessi_task_description import EESSITaskDescription
from utils import log_message, LoggingScope, log_function_entry_exit
from github import Github, GithubException, UnknownObjectException


class TaskState(Enum):
    NEW = auto()  # The task has been created but not yet processed
    STAGED = auto()  # The task has been staged to the Stratum-0
    PR_OPENED = auto()  # The task has been opened as a PR in some staging repository
    APPROVED = auto()  # The task has been approved
    REJECTED = auto()  # The task has been rejected
    INGESTED = auto()  # The task has been ingested into the target CernVM-FS repository

    @classmethod
    def from_string(cls, name, default=None, case_sensitive=False):
        if case_sensitive:
            return cls.__members__.get(name, default)

        try:
            return next(
                member for member_name, member in cls.__members__.items()
                if member_name.lower() == name.lower()
            )
        except StopIteration:
            return default

    def __str__(self):
        return self.name.lower()


class EESSITask:
    description: EESSITaskDescription
    action: EESSITaskAction
    state: TaskState
    git_repo: Github

    @log_function_entry_exit()
    def __init__(self, description: EESSITaskDescription, git_repo: Github):
        self.description = description
        self.git_repo = git_repo
        self.action = self._determine_task_action()

        # Define valid state transitions for all actions
        self.valid_transitions = {
            TaskState.NEW: [TaskState.STAGED],
            TaskState.STAGED: [TaskState.PR_OPENED],
            TaskState.PR_OPENED: [TaskState.APPROVED, TaskState.REJECTED],
            TaskState.APPROVED: [TaskState.INGESTED],
            TaskState.REJECTED: [],  # Terminal state
            TaskState.INGESTED: []   # Terminal state
        }

        self.state = self._find_state()

    @log_function_entry_exit()
    def _determine_task_action(self) -> EESSITaskAction:
        """
        Determine the action type based on task description metadata.
        """
        if 'task' in self.description.metadata and 'action' in self.description.metadata['task']:
            action_str = self.description.metadata['task']['action'].lower()
            if action_str == "nop":
                return EESSITaskAction.NOP
            elif action_str == "delete":
                return EESSITaskAction.DELETE
            elif action_str == "add":
                return EESSITaskAction.ADD
            elif action_str == "update":
                return EESSITaskAction.UPDATE
        return EESSITaskAction.UNKNOWN

    @log_function_entry_exit()
    def _file_exists_in_repo_branch(self, file_path, branch=None) -> bool:
        """
        Check if a file exists in a repository branch.
        """
        if branch is None:
            branch = self.git_repo.default_branch
        try:
            self.git_repo.get_contents(file_path, ref=branch)
            log_msg = "Found file %s in branch %s"
            log_message(LoggingScope.TASK_OPS, 'INFO', log_msg, file_path, branch)
            return True
        except UnknownObjectException:
            # file_path does not exist in branch
            return False
        except GithubException as err:
            if err.status == 404:
                # file_path does not exist in branch
                return False
            else:
                # if there was some other (e.g. connection) issue, log message and return False
                log_msg = 'Unable to determine the state of %s, the GitHub API returned status %s!'
                log_message(LoggingScope.ERROR, 'WARNING', log_msg, self.object, err.status)
                return False
        return False

    @log_function_entry_exit()
    def _determine_sequence_numbers_including_task_file(self, repo: str, pr: str) -> Dict[int, bool]:
        """
        Determines in which sequence numbers the metadata/task file is included and in which it is not.

        Args:
            repo: the repository name
            pr: the pull request number

        Returns:
            A dictionary with the sequence numbers as keys and a boolean value indicating if the metadata/task file is
            included in that sequence number.

        Idea:
         - The deployment for a single source PR could be split into multiple staging PRs each is assigned a unique
           sequence number.
         - For a given source PR (identified by the repo name and the PR number), a staging PR using a branch named
           `REPO/PR_NUM/SEQ_NUM` is created.
         - In the staging repo we create a corresponding directory `REPO/PR_NUM/SEQ_NUM`.
         - If a metadata/task file is handled by the staging PR with sequence number, it is included in that directory.
         - We iterate over all directories under `REPO/PR_NUM`:
           - If the metadata/task file is available in the directory, we add the sequence number to the list.

        Note: this is a placeholder for now, as we do not know yet if we need to use a sequence number.
        """
        sequence_numbers = {}
        repo_pr_dir = f"{repo}/{pr}"
        # iterate over all directories under repo_pr_dir
        for dir in self._list_directory_contents(repo_pr_dir):
            # check if the directory is a number
            if dir.name.isdigit():
                remote_file_path = self.description.task_object.remote_file_path
                if self._file_exists_in_repo_branch(f"{repo_pr_dir}/{dir.name}/{remote_file_path}"):
                    sequence_numbers[int(dir.name)] = True
                else:
                    sequence_numbers[int(dir.name)] = False
            else:
                # directory is not a number, so we skip it
                continue
        return sequence_numbers

    @log_function_entry_exit()
    def _find_state(self) -> TaskState:
        """
        Determine the state of the task based on the task description metadata.

        Returns:
            The state of the task.
        """
        # obtain repo and pr from metadata
        log_message(LoggingScope.TASK_OPS, 'INFO', "finding state of task %s", self.description.task_object)
        task = self.description.task
        source = self.description.source
        if 'repo' in task and 'pr' in task:
            log_message(LoggingScope.TASK_OPS, 'INFO', "task found in metadata: %s", task)
            repo = task['repo']
            pr = task['pr']
        elif 'repo' in source and 'pr' in source:
            log_message(LoggingScope.TASK_OPS, 'INFO', "source found in metadata: %s", source)
            repo = source['repo']
            pr = source['pr']
        else:
            raise ValueError("no repo or pr found in metadata")
        log_message(LoggingScope.TASK_OPS, 'INFO', "repo: %s, pr: %s", repo, pr)

        # iterate over all sequence numbers in repo/pr dir
        sequence_numbers = self._determine_sequence_numbers_including_task_file(repo, pr)
        log_message(LoggingScope.TASK_OPS, 'INFO', "sequence_numbers: %s", sequence_numbers)
        for sequence_number in [key for key, value in sequence_numbers.items() if value]:
            # create path to metadata file from repo, PR, repo, sequence number, metadata file name, state name
            # format of the metadata file name is:
            #   eessi-VERSION-COMPONENT-OS-ARCHITECTURE-TIMESTAMP.SUFFIX
            # all uppercase words are placeholders
            # all placeholders (except ARCHITECTURE) do not include any hyphens
            # ARCHITECTURE can include one to two hyphens
            # The SUFFIX is composed of two parts: TARBALLSUFFIX and METADATASUFFIX
            # TARBALLSUFFIX is defined by the task object or in the configuration file
            # METADATASUFFIX is defined by the task object or in the configuration file
            #   Later, we may switch to using task action files instead of metadata files. The format of the
            #   SUFFIX would then be defined by the task action or the configuration file.
            version, component, os, architecture, timestamp, suffix = self.description.get_metadata_file_components()
            log_msg = "version: %s, component: %s, os: %s, architecture: %s, timestamp: %s, suffix: %s"
            log_message(LoggingScope.TASK_OPS, 'INFO', log_msg, version, component, os, architecture, timestamp, suffix)
            metadata_file_name = f"eessi-{version}-{component}-{os}-{architecture}-{timestamp}.{suffix}"
            metadata_file_state_path = f"{repo}/{pr}/{sequence_number}/{metadata_file_name}"
            # get the state from the file in the metadata_file_state_path
            state = self._get_state_from_metadata_file(metadata_file_state_path)
            log_message(LoggingScope.TASK_OPS, 'INFO', "state: %s", state)
            return state
        # did not find metadata file in staging repo on GitHub
        log_message(LoggingScope.TASK_OPS, 'INFO', "did not find metadata file in staging repo on GitHub, state: NEW")
        return TaskState.NEW

    @log_function_entry_exit()
    def _get_state_from_metadata_file(self, metadata_file_state_path: str) -> TaskState:
        """
        Get the state from the file in the metadata_file_state_path.
        """
        # get contents of metadata_file_state_path
        contents = self.git_repo.get_contents(metadata_file_state_path)
        try:
            state = TaskState.from_string(contents.name)
            return state
        except ValueError:
            return TaskState.NEW

    @log_function_entry_exit()
    def _list_directory_contents(self, directory_path, branch=None):
        try:
            # Get contents of the directory
            branch = self.git_repo.default_branch if branch is None else branch
            log_message(LoggingScope.TASK_OPS, 'INFO', "listing contents of %s in branch %s", directory_path, branch)
            contents = self.git_repo.get_contents(directory_path, ref=branch)

            # If contents is a list, it means we successfully got directory contents
            if isinstance(contents, list):
                return contents
            else:
                # If it's not a list, it means the path is not a directory
                raise ValueError(f"{directory_path} is not a directory")
        except GithubException as err:
            if err.status == 404:
                raise FileNotFoundError(f"Directory not found: {directory_path}")
            raise err

    @log_function_entry_exit()
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
                msg = f"handler {handler_name} changed state from {state_before_handle} to {self.state}"
                msg += " running handle() again"
                print(msg)
                self.handle()
        else:
            # Default behavior for missing handlers
            print(f"No handler for action {self.action} and state {self.state} implemented; nothing to be done")

    # Implement handlers for ADD action
    @log_function_entry_exit()
    def _handle_add_new(self):
        """Handler for ADD action in NEW state"""
        print("Handling ADD action in NEW state")
        # Implementation for adding in NEW state
        return True

    @log_function_entry_exit()
    def _handle_add_staged(self):
        """Handler for ADD action in STAGED state"""
        print("Handling ADD action in STAGED state")
        # Implementation for adding in STAGED state
        return True

    @log_function_entry_exit()
    def _handle_add_pr_opened(self):
        """Handler for ADD action in PR_OPENED state"""
        print("Handling ADD action in PR_OPENED state")
        # Implementation for adding in PR_OPENED state
        return True

    @log_function_entry_exit()
    def _handle_add_approved(self):
        """Handler for ADD action in APPROVED state"""
        print("Handling ADD action in APPROVED state")
        # Implementation for adding in APPROVED state
        return True

    @log_function_entry_exit()
    def _handle_add_ingested(self):
        """Handler for ADD action in INGESTED state"""
        print("Handling ADD action in INGESTED state")
        # Implementation for adding in INGESTED state
        return True

    @log_function_entry_exit()
    def transition_to(self, new_state: TaskState):
        """
        Transition the task to a new state if valid.
        """
        if new_state in self.valid_transitions[self.state]:
            self.state = new_state
            return True
        return False

    @log_function_entry_exit()
    def __str__(self):
        return f"EESSITask(description={self.description}, action={self.action}, state={self.state})"
