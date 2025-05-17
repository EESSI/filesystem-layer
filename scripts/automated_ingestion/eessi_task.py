from enum import Enum, auto
from typing import Dict, List
from eessi_data_object import EESSIDataAndSignatureObject
from eessi_task_action import EESSITaskAction
from eessi_task_description import EESSITaskDescription
from eessi_task_payload import EESSITaskPayload
from utils import log_message, LoggingScope, log_function_entry_exit
from github import Github, GithubException, UnknownObjectException
import os


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
    payload: EESSITaskPayload
    action: EESSITaskAction
    state: TaskState
    git_repo: Github

    @log_function_entry_exit()
    def __init__(self, description: EESSITaskDescription, git_repo: Github):
        self.description = description
        self.git_repo = git_repo
        self.action = self._determine_task_action()

        # Define valid state transitions for all actions
        # NOTE, TaskState.APPROVED must be the first element or _next_state() will not work
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
    def _state_file_with_prefix_exists_in_repo_branch(self, file_path_prefix: str, branch=None) -> bool:
        """
        Check if a file exists in a repository branch.

        Args:
            file_path_prefix: the prefix of the file path
            branch: the branch to check

        Returns:
            True if a file with the prefix exists in the branch, False otherwise
        """
        if branch is None:
            branch = self.git_repo.default_branch
        try:
            # get all files in directory part of file_path_prefix
            directory_part = os.path.dirname(file_path_prefix)
            files = self.git_repo.get_contents(directory_part, ref=branch)
            log_msg = "Found files %s in directory %s in branch %s"
            log_message(LoggingScope.TASK_OPS, 'INFO', log_msg, files, directory_part, branch)
            # check if any of the files has file_path_prefix as prefix
            for file in files:
                if file.path.startswith(file_path_prefix):
                    log_msg = "Found file %s in directory %s in branch %s"
                    log_message(LoggingScope.TASK_OPS, 'INFO', log_msg, file.path, directory_part, branch)
                    return True
            log_msg = "No file with prefix %s found in directory %s in branch %s"
            log_message(LoggingScope.TASK_OPS, 'INFO', log_msg, file_path_prefix, directory_part, branch)
            return False
        except UnknownObjectException:
            # file_path does not exist in branch
            log_msg = "Directory %s or file with prefix %s does not exist in branch %s"
            log_message(LoggingScope.TASK_OPS, 'INFO', log_msg, directory_part, file_path_prefix, branch)
            return False
        except GithubException as err:
            if err.status == 404:
                # file_path does not exist in branch
                log_msg = "Directory %s or file with prefix %s does not exist in branch %s"
                log_message(LoggingScope.TASK_OPS, 'INFO', log_msg, directory_part, file_path_prefix, branch)
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
        try:
            directories = self._list_directory_contents(repo_pr_dir)
            for dir in directories:
                # check if the directory is a number
                if dir.name.isdigit():
                    # determine if a state file with prefix exists in the sequence number directory
                    #   we need to use the basename of the remote file path
                    remote_file_path_basename = os.path.basename(self.description.task_object.remote_file_path)
                    state_file_name_prefix = f"{repo_pr_dir}/{dir.name}/{remote_file_path_basename}"
                    if self._state_file_with_prefix_exists_in_repo_branch(state_file_name_prefix):
                        sequence_numbers[int(dir.name)] = True
                    else:
                        sequence_numbers[int(dir.name)] = False
                else:
                    # directory is not a number, so we skip it
                    continue
        except FileNotFoundError:
            # repo_pr_dir does not exist, so we return an empty dictionary
            return {}
        except GithubException as err:
            if err.status != 404:  # 404 is catched by FileNotFoundError
                # some other error than the directory not existing
                return {}
        return sequence_numbers

    @log_function_entry_exit()
    def _find_highest_number(self, str_list: List[str]) -> int:
        """
        Find the highest number in a list of strings.
        """
        # Convert all strings to integers
        int_list = [int(num) for num in str_list]
        return max(int_list)

    @log_function_entry_exit()
    def _find_state(self) -> TaskState:
        """
        Determine the state of the task based on the task description metadata.

        Returns:
            The state of the task.
        """
        # obtain repo and pr from metadata
        log_message(LoggingScope.TASK_OPS, 'INFO', "finding state of task %s", self.description.task_object)
        repo = self.description.get_repo_name()
        pr = self.description.get_pr_number()
        log_message(LoggingScope.TASK_OPS, 'INFO', "repo: %s, pr: %s", repo, pr)

        # obtain all sequence numbers in repo/pr dir which include a state file for this task
        sequence_numbers = self._determine_sequence_numbers_including_task_file(repo, pr)
        if len(sequence_numbers) == 0:
            # no sequence numbers found, so we return NEW
            log_message(LoggingScope.TASK_OPS, 'INFO', "no sequence numbers found, state: NEW")
            return TaskState.NEW
        # because a new sequence number is only created after the previous staging PR has been approved or rejected,
        #   we need to check if the processing of the highest sequence number is finished.
        highest_sequence_number = self._find_highest_number(sequence_numbers.keys())
        # we obtain the state from the file in the highest sequence number directory
        # TODO: verify if the state matches other information, e.g. the state of the staging PR
        #       for now, we assume that the state is correct
        task_file_name = self.description.get_task_file_name()
        metadata_file_state_path_prefix = f"{repo}/{pr}/{highest_sequence_number}/{task_file_name}."
        state = self._get_state_for_metadata_file_prefix(metadata_file_state_path_prefix)
        log_message(LoggingScope.TASK_OPS, 'INFO', "state: %s", state)
        return state

    @log_function_entry_exit()
    def _get_state_for_metadata_file_prefix(self, metadata_file_state_path_prefix: str) -> TaskState:
        """
        Get the state from the file in the metadata_file_state_path_prefix.
        """
        # first get all files in directory part of metadata_file_state_path_prefix
        directory_part = os.path.dirname(metadata_file_state_path_prefix)
        files = self._list_directory_contents(directory_part)
        # check if any of the files has metadata_file_state_path_prefix as prefix
        for file in files:
            if file.path.startswith(metadata_file_state_path_prefix):
                # get state from file name taking only the suffix
                state = TaskState.from_string(file.name.split('.')[-1])
            return state
        # did not find any file with metadata_file_state_path_prefix as prefix
        log_message(LoggingScope.TASK_OPS, 'INFO', "did not find any file with prefix %s",
                    metadata_file_state_path_prefix)
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
    def _next_state(self) -> TaskState:
        """
        Determine the next state based on the current state using the valid_transitions dictionary.

        NOTE, it assumes that function is only called for non-terminal states and that the next state is the first
        element of the list returned by the valid_transitions dictionary.
        """
        return self.valid_transitions[self.state][0]

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
        # get name of of payload from metadata
        payload_name = self.description.metadata['payload']['filename']
        log_message(LoggingScope.TASK_OPS, 'INFO', "payload_name: %s", payload_name)
        # get config and remote_client from self.description.task_object
        config = self.description.task_object.config
        remote_client = self.description.task_object.remote_client
        # determine remote_file_path by replacing basename of remote_file_path in self.description.task_object
        #   with payload_name
        description_remote_file_path = self.description.task_object.remote_file_path
        payload_remote_file_path = os.path.join(os.path.dirname(description_remote_file_path), payload_name)
        log_message(LoggingScope.TASK_OPS, 'INFO', "payload_remote_file_path: %s", payload_remote_file_path)
        # initialize payload object
        payload_object = EESSIDataAndSignatureObject(config, payload_remote_file_path, remote_client)
        self.payload = EESSITaskPayload(payload_object)
        log_message(LoggingScope.TASK_OPS, 'INFO', "payload: %s", self.payload)
        # determine next state (NEXT_STATE), put metadata/task file into GH staging repo in main branch under directory
        # REPO/PR_NUM/SEQ_NUM/payload_name.NEXT_STATE
        next_state = self._next_state()
        log_message(LoggingScope.TASK_OPS, 'INFO', "next_state: %s", next_state)
        repo_name = self.description.get_repo_name()
        pr_number = self.description.get_pr_number()
        repo_pr_dir = f"{repo_name}/{pr_number}"
        sequence_numbers = self._determine_sequence_numbers_including_task_file(repo_name, pr_number)
        if len(sequence_numbers) == 0:
            sequence_number = 0
        else:
            sequence_number = self._find_highest_number(sequence_numbers.keys())
        # we use the basename of the remote file path for the task description file
        task_file_name = self.description.get_task_file_name()
        staging_repo_path = f"{repo_pr_dir}/{sequence_number}/{task_file_name}.{next_state}"
        log_message(LoggingScope.TASK_OPS, 'INFO', "staging_repo_path: %s", staging_repo_path)
        # contents of task description / metadata file
        contents = self.description.get_contents()
        self.git_repo.create_file(staging_repo_path,
                                  f"new task for {repo_name} PR {pr_number} seq {sequence_number}: add build for arch",
                                  contents)
        self.state = next_state
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
