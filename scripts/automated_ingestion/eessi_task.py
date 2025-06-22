from enum import Enum, auto
from typing import Dict, List, Tuple, Optional
from functools import total_ordering

import base64
import os
import subprocess
import traceback

from eessi_data_object import EESSIDataAndSignatureObject
from eessi_task_action import EESSITaskAction
from eessi_task_description import EESSITaskDescription
from eessi_task_payload import EESSITaskPayload
from utils import send_slack_message, log_message, LoggingScope, log_function_entry_exit

from github import Github, GithubException, InputGitTreeElement, UnknownObjectException
from github.PullRequest import PullRequest
from github.Branch import Branch


class SequenceStatus(Enum):
    DOES_NOT_EXIST = auto()
    IN_PROGRESS = auto()
    FINISHED = auto()


@total_ordering
class TaskState(Enum):
    UNDETERMINED = auto()  # The task state was not determined yet
    NEW_TASK = auto()  # The task has been created but not yet processed
    PAYLOAD_STAGED = auto()  # The task's payload has been staged to the Stratum-0
    PULL_REQUEST = auto()  # A PR for the task has been created or updated in some staging repository
    APPROVED = auto()  # The PR for the task has been approved
    REJECTED = auto()  # The PR for the task has been rejected
    INGESTED = auto()  # The task's payload has been applied to the target CernVM-FS repository
    DONE = auto()  # The task has been completed

    @classmethod
    def from_string(cls, name, default=None, case_sensitive=False):
        log_message(LoggingScope.TASK_OPS, 'INFO', "from_string: %s", name)
        if case_sensitive:
            to_return = cls.__members__.get(name, default)
            log_message(LoggingScope.TASK_OPS, 'INFO', "from_string will return: %s", to_return)
            return to_return

        try:
            to_return = cls[name.upper()]
            log_message(LoggingScope.TASK_OPS, 'INFO', "from_string will return: %s", to_return)
            return to_return
        except KeyError:
            return default

    def __lt__(self, other):
        if self.__class__ is other.__class__:
            return self.value < other.value
        return NotImplemented

    def __str__(self):
        return self.name.upper()


class EESSITask:
    description: EESSITaskDescription
    payload: EESSITaskPayload
    action: EESSITaskAction
    git_repo: Github
    config: Dict

    @log_function_entry_exit()
    def __init__(self, description: EESSITaskDescription, config: Dict, cvmfs_repo: str, git_repo: Github):
        self.description = description
        self.config = config
        self.cvmfs_repo = cvmfs_repo
        self.git_repo = git_repo
        self.action = self._determine_task_action()

        # Define valid state transitions for all actions
        # NOTE, TaskState.APPROVED must be the first element or _next_state() will not work
        self.valid_transitions = {
            TaskState.UNDETERMINED: [TaskState.NEW_TASK, TaskState.PAYLOAD_STAGED, TaskState.PULL_REQUEST,
                                     TaskState.APPROVED, TaskState.REJECTED, TaskState.INGESTED, TaskState.DONE],
            TaskState.NEW_TASK: [TaskState.PAYLOAD_STAGED],
            TaskState.PAYLOAD_STAGED: [TaskState.PULL_REQUEST],
            TaskState.PULL_REQUEST: [TaskState.APPROVED, TaskState.REJECTED],
            TaskState.APPROVED: [TaskState.INGESTED],
            TaskState.REJECTED: [],  # terminal state
            TaskState.INGESTED: [],  # terminal state
            TaskState.DONE: []  # virtual terminal state, not used to write on GitHub
        }

        self.payload = None
        state = self.determine_state()
        if state >= TaskState.PAYLOAD_STAGED:
            log_message(LoggingScope.TASK_OPS, 'INFO', "initializing payload object in constructor for EESSITask")
            self._init_payload_object()

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
    def _state_file_with_prefix_exists_in_repo_branch(self, file_path_prefix: str, branch_name: str = None) -> bool:
        """
        Check if a file exists in a repository branch.

        Args:
            file_path_prefix: the prefix of the file path
            branch_name: the branch to check

        Returns:
            True if a file with the prefix exists in the branch, False otherwise
        """
        branch_name = self.git_repo.default_branch if branch_name is None else branch_name
        # branch = self._get_branch_from_name(branch_name)
        try:
            # get all files in directory part of file_path_prefix
            directory_part = os.path.dirname(file_path_prefix)
            files = self.git_repo.get_contents(directory_part, ref=branch_name)
            log_msg = "Found files %s in directory %s in branch %s"
            log_message(LoggingScope.TASK_OPS, 'INFO', log_msg, files, directory_part, branch_name)
            # check if any of the files has file_path_prefix as prefix
            for file in files:
                if file.path.startswith(file_path_prefix):
                    log_msg = "Found file %s in directory %s in branch %s"
                    log_message(LoggingScope.TASK_OPS, 'INFO', log_msg, file.path, directory_part, branch_name)
                    return True
            log_msg = "No file with prefix %s found in directory %s in branch %s"
            log_message(LoggingScope.TASK_OPS, 'INFO', log_msg, file_path_prefix, directory_part, branch_name)
            return False
        except UnknownObjectException:
            # file_path does not exist in branch
            log_msg = "Directory %s or file with prefix %s does not exist in branch %s"
            log_message(LoggingScope.TASK_OPS, 'INFO', log_msg, directory_part, file_path_prefix, branch_name)
            return False
        except GithubException as err:
            if err.status == 404:
                # file_path does not exist in branch
                log_msg = "Directory %s or file with prefix %s does not exist in branch %s"
                log_message(LoggingScope.TASK_OPS, 'INFO', log_msg, directory_part, file_path_prefix, branch_name)
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
        NOTE, we only need to check the default branch of the repository, because a for a new task a file
        is added to the default branch and for the subsequent processing of the task we use a different branch.
        Thus, until the PR is closed, the task file stays in the default branch.

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
    def _get_sequence_number_for_task_file(self) -> int:
        """
        Get the sequence number this task is assigned to at the moment.
        NOTE, should only be called if the task is actually assigned to a sequence number.
        """
        repo_name = self.description.get_repo_name()
        pr_number = self.description.get_pr_number()
        sequence_numbers = self._determine_sequence_numbers_including_task_file(repo_name, pr_number)
        if len(sequence_numbers) == 0:
            raise ValueError("Found no sequence numbers at all")
        else:
            # get all entries with value True, there should be only one, so we return the first one
            sequence_numbers_true = [key for key, value in sequence_numbers.items() if value is True]
            if len(sequence_numbers_true) == 0:
                raise ValueError("Found no sequence numbers that include the task file for task %s",
                                 self.description)
            else:
                return sequence_numbers_true[0]

    @log_function_entry_exit()
    def _get_current_sequence_number(self, sequence_numbers: Dict[int, bool] = None) -> int:
        """
        Get the current sequence number based on the sequence numbers.
        If sequence_numbers is not provided, we determine the sequence numbers from the task description.
        """
        if sequence_numbers is None:
            repo_name = self.description.get_repo_name()
            pr_number = self.description.get_pr_number()
            sequence_numbers = self._determine_sequence_numbers_including_task_file(repo_name, pr_number)
        if len(sequence_numbers) == 0:
            return 0
        return self._find_highest_number(sequence_numbers.keys())

    @log_function_entry_exit()
    def _get_fixed_sequence_number(self) -> int:
        """
        Get a fixed sequence number.
        """
        return 11

    @log_function_entry_exit()
    def _determine_sequence_status(self, sequence_number: int = None) -> int:
        """
        Determine the status of the sequence number. It could be: DOES_NOT_EXIST, IN_PROGRESS, FINISHED
        If sequence_number is not provided, we use the highest existing sequence number.
        """
        if sequence_number is None:
            sequence_number = self._get_current_sequence_number()
        repo_name = self.description.get_repo_name()
        pr_number = self.description.get_pr_number()
        sequence_numbers = self._determine_sequence_numbers_including_task_file(repo_name, pr_number)
        if len(sequence_numbers) == 0:
            return SequenceStatus.DOES_NOT_EXIST
        elif sequence_number not in sequence_numbers.keys():
            return SequenceStatus.DOES_NOT_EXIST
        elif sequence_number < self._find_highest_number(sequence_numbers.keys()):
            return SequenceStatus.FINISHED
        else:
            # check status of PR if it exists
            branch_name = f"{repo_name.replace('/', '-')}-PR-{pr_number}-SEQ-{sequence_number}"
            if branch_name in [branch.name for branch in self.git_repo.get_branches()]:
                find_pr = [pr for pr in self.git_repo.get_pulls(head=branch_name, state='all')]
                if find_pr:
                    pr = find_pr.pop(0)
                    if pr.state == 'closed':
                        return SequenceStatus.FINISHED
            return SequenceStatus.IN_PROGRESS

    @log_function_entry_exit()
    def _find_staging_pr(self) -> Tuple[Optional[PullRequest], Optional[str], Optional[int]]:
        """
        Find the staging PR for the task.
        TODO: arg sequence number --> make function simpler
        """
        repo_name = self.description.get_repo_name()
        pr_number = self.description.get_pr_number()
        try:
            sequence_number = self._get_sequence_number_for_task_file()
        except ValueError:
            # no sequence number found, so we return None
            log_message(LoggingScope.ERROR, 'ERROR', "no sequence number found for task %s", self.description)
            return None, None, None
        except Exception as err:
            # some other error
            log_message(LoggingScope.ERROR, 'ERROR', "error finding staging PR for task %s: %s",
                        self.description, err)
            return None, None, None
        branch_name = f"{repo_name.replace('/', '-')}-PR-{pr_number}-SEQ-{sequence_number}"
        if branch_name in [branch.name for branch in self.git_repo.get_branches()]:
            find_pr = [pr for pr in self.git_repo.get_pulls(head=branch_name, state='all')]
            if find_pr:
                pr = find_pr.pop(0)
                return pr, branch_name, sequence_number
            else:
                return None, branch_name, sequence_number
        else:
            return None, None, None

    @log_function_entry_exit()
    def _create_staging_pr(self, sequence_number: int) -> Tuple[PullRequest, str]:
        """
        Create a staging PR for the task.
        NOTE, SHALL only be called if no staging PR for the task exists yet.
        """
        repo_name = self.description.get_repo_name()
        pr_number = self.description.get_pr_number()
        branch_name = f"{repo_name.replace('/', '-')}-PR-{pr_number}-SEQ-{sequence_number}"
        default_branch_name = self.git_repo.default_branch
        pr = self.git_repo.create_pull(title=f"Add task for {repo_name} PR {pr_number} seq {sequence_number}",
                                       body=f"Add task for {repo_name} PR {pr_number} seq {sequence_number}",
                                       head=branch_name, base=default_branch_name)
        return pr, branch_name

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
            # no sequence numbers found, so we return NEW_TASK
            log_message(LoggingScope.TASK_OPS, 'INFO', "no sequence numbers found, state: NEW_TASK")
            return TaskState.NEW_TASK
        # we got at least one sequence number
        # if one value for a sequence number is True, we can determine the state from the file in the directory
        sequence_including_task = [key for key, value in sequence_numbers.items() if value is True]
        if len(sequence_including_task) == 0:
            # no sequence number includes the task file, so we return NEW_TASK
            log_message(LoggingScope.TASK_OPS, 'INFO', "no sequence number includes the task file, state: NEW_TASK")
            return TaskState.NEW_TASK
        # we got at least one sequence number which includes the task file
        # we can determine the state from the filename in the directory
        # NOTE, we use the first element in sequence_including_task (there should be only one)
        #     we ignore other elements in sequence_including_task
        sequence_number = sequence_including_task[0]
        task_file_name = self.description.get_task_file_name()
        metadata_file_state_path_prefix = f"{repo}/{pr}/{sequence_number}/{task_file_name}."
        state = self._get_state_for_metadata_file_prefix(metadata_file_state_path_prefix, sequence_number)
        log_message(LoggingScope.TASK_OPS, 'INFO', "state: %s", state)
        return state

    @log_function_entry_exit()
    def _get_state_for_metadata_file_prefix(self, metadata_file_state_path_prefix: str,
                                            sequence_number: int) -> TaskState:
        """
        Get the state from the file in the metadata_file_state_path_prefix.
        """
        # depending on the state of the deployment (NEW_TASK, PAYLOAD_STAGED, PULL_REQUEST, APPROVED, REJECTED,
        # INGESTED, DONE)
        # we need to check the task file in the default branch or in the branch corresponding to the sequence number
        directory_part = os.path.dirname(metadata_file_state_path_prefix)
        repo_name = self.description.get_repo_name()
        pr_number = self.description.get_pr_number()
        default_branch_name = self.git_repo.default_branch
        branch_name = f"{repo_name.replace('/', '-')}-PR-{pr_number}-SEQ-{sequence_number}"
        all_branch_names = [branch.name for branch in self.git_repo.get_branches()]
        states = []
        for branch in [default_branch_name, branch_name]:
            if branch in all_branch_names:
                # first get all files in directory part of metadata_file_state_path_prefix
                files = self._list_directory_contents(directory_part, branch)
                # check if any of the files has metadata_file_state_path_prefix as prefix
                for file in files:
                    if file.path.startswith(metadata_file_state_path_prefix):
                        # get state from file name taking only the suffix
                        state = TaskState.from_string(file.name.split('.')[-1])
                        log_message(LoggingScope.TASK_OPS, 'INFO', "state: %s", state)
                        states.append(state)
        if len(states) == 0:
            # did not find any file with metadata_file_state_path_prefix as prefix
            log_message(LoggingScope.TASK_OPS, 'INFO', "did not find any file with prefix %s",
                        metadata_file_state_path_prefix)
            return TaskState.NEW_TASK
        # sort the states and return the last one
        states.sort()
        state = states[-1]
        log_message(LoggingScope.TASK_OPS, 'INFO', "state: %s", state)
        return state

    @log_function_entry_exit()
    def _list_directory_contents(self, directory_path, branch_name: str = None):
        try:
            # Get contents of the directory
            branch_name = self.git_repo.default_branch if branch_name is None else branch_name
            log_message(LoggingScope.TASK_OPS, 'INFO',
                        "listing contents of %s in branch %s", directory_path, branch_name)
            contents = self.git_repo.get_contents(directory_path, ref=branch_name)

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
    def _next_state(self, state: TaskState = None) -> TaskState:
        """
        Determine the next state based on the current state using the valid_transitions dictionary.

        NOTE, it assumes that function is only called for non-terminal states and that the next state is the first
        element of the list returned by the valid_transitions dictionary.
        """
        the_state = state if state is not None else self.determine_state()
        return self.valid_transitions[the_state][0]

    @log_function_entry_exit()
    def _path_exists_in_branch(self, path: str, branch_name: str = None) -> bool:
        """
        Check if a path exists in a branch.
        """
        branch_name = self.git_repo.default_branch if branch_name is None else branch_name
        try:
            self.git_repo.get_contents(path, ref=branch_name)
            return True
        except GithubException as err:
            if err.status == 404:
                return False
            else:
                raise err

    @log_function_entry_exit()
    def _read_dict_from_string(self, content: str) -> dict:
        """
        Read the dictionary from the string.
        """
        config_dict = {}
        for line in content.strip().split('\n'):
            if '=' in line and not line.strip().startswith('#'):  # Skip comments
                key, value = line.split('=', 1)  # Split only on first '='
                config_dict[key.strip()] = value.strip()
        return config_dict

    @log_function_entry_exit()
    def _read_pull_request_dir_from_file(self, task_pointer_file: str = None, branch_name: str = None) -> str:
        """
        Read the pull request directory from the file in the given branch.
        """
        # set default values for task pointer file and branch name
        if task_pointer_file is None:
            task_pointer_file = self.description.task_object.remote_file_path
        if branch_name is None:
            branch_name = self.git_repo.default_branch

        # read the pull request directory from the file in the given branch
        content = self.git_repo.get_contents(task_pointer_file, ref=branch_name)

        # Decode the content from base64
        content_str = content.decoded_content.decode('utf-8')

        # Parse into dictionary
        config_dict = self._read_dict_from_string(content_str)

        return config_dict.get('pull_request_dir', None)

    @log_function_entry_exit()
    def _determine_pull_request_dir(self, task_pointer_file: str = None, branch_name: str = None) -> str:
        """Determine the pull request directory via the task pointer file"""
        return self._read_pull_request_dir_from_file(task_pointer_file=task_pointer_file, branch_name=branch_name)

    @log_function_entry_exit()
    def _get_branch_from_name(self, branch_name: str = None) -> Optional[Branch]:
        """
        Get a branch object from its name.
        """
        branch_name = self.git_repo.default_branch if branch_name is None else branch_name

        try:
            branch = self.git_repo.get_branch(branch_name)
            log_message(LoggingScope.TASK_OPS, 'INFO', "branch %s exists: %s", branch_name, branch)
            return branch
        except Exception as err:
            log_message(LoggingScope.TASK_OPS, 'ERROR', "error checking if branch %s exists: %s",
                        branch_name, err)
            return None

    @log_function_entry_exit()
    def _read_task_state_from_file(self, path: str, branch_name: str = None) -> TaskState:
        """
        Read the task state from the file in the given branch.
        """
        branch_name = self.git_repo.default_branch if branch_name is None else branch_name
        content = self.git_repo.get_contents(path, ref=branch_name)

        # Decode the content from base64
        content_str = content.decoded_content.decode('utf-8').strip()
        log_message(LoggingScope.TASK_OPS, 'INFO', "content in TaskState file: %s", content_str)

        task_state = TaskState.from_string(content_str)
        log_message(LoggingScope.TASK_OPS, 'INFO', "task state: %s", task_state)

        return task_state

    @log_function_entry_exit()
    def determine_state(self, branch: str = None) -> TaskState:
        """
        Determine the state of the task based on the state of the staging repository.
        """
        # check if path representing the task file exists in the default branch or the "feature" branch
        task_pointer_file = self.description.task_object.remote_file_path
        branch_to_use = self.git_repo.default_branch if branch is None else branch

        if self._path_exists_in_branch(task_pointer_file, branch_name=branch_to_use):
            log_message(LoggingScope.TASK_OPS, 'INFO', "path %s exists in branch %s",
                        task_pointer_file, branch_to_use)

            # get state from task file in branch to use
            # - read the TaskState file in pull request directory
            pull_request_dir = self._determine_pull_request_dir(branch_name=branch_to_use)
            task_state_file_path = f"{pull_request_dir}/TaskState"
            task_state = self._read_task_state_from_file(task_state_file_path, branch_to_use)

            log_message(LoggingScope.TASK_OPS, 'INFO', "task state in branch %s: %s",
                        branch_to_use, task_state)
            return task_state
        else:
            log_message(LoggingScope.TASK_OPS, 'INFO', "path %s does not exist in branch %s",
                        task_pointer_file, branch_to_use)
            return TaskState.UNDETERMINED

    @log_function_entry_exit()
    def handle(self):
        """
        Dynamically find and execute the appropriate handler based on action and state.
        """
        state_before_handle = self.determine_state()

        # Construct handler method name
        handler_name = f"_handle_{self.action}_{str(state_before_handle).lower()}"

        # Check if the handler exists
        handler = getattr(self, handler_name, None)

        if handler and callable(handler):
            # Execute the handler if it exists
            return handler()
        else:
            # Default behavior for missing handlers
            log_message(LoggingScope.TASK_OPS, 'ERROR',
                        "No handler for action %s and state %s implemented; nothing to be done",
                        self.action, state_before_handle)
            return state_before_handle

    # Implement handlers for ADD action
    @log_function_entry_exit()
    def _safe_create_file(self, path: str, message: str, content: str, branch_name: str = None):
        """Create a file in the given branch."""
        try:
            branch_name = self.git_repo.default_branch if branch_name is None else branch_name
            existing_file = self.git_repo.get_contents(path, ref=branch_name)
            log_message(LoggingScope.TASK_OPS, 'INFO', "File %s already exists", path)
            return existing_file
        except GithubException as err:
            if err.status == 404:  # File doesn't exist
                # Safe to create
                return self.git_repo.create_file(path, message, content, branch=branch_name)
            else:
                raise err  # Some other error

    @log_function_entry_exit()
    def _create_multi_file_commit(self, files_data, commit_message, branch_name: str = None):
        """
        Create a commit with multiple file changes

        files_data: dict with structure:
        {
            "path/to/file1.txt": {
                "content": "file content",
                "mode": "100644"  # optional, defaults to 100644
            },
            "path/to/file2.py": {
                "content": "print('hello')",
                "mode": "100644"
            }
        }
        """
        branch_name = self.git_repo.default_branch if branch_name is None else branch_name
        ref = self.git_repo.get_git_ref(f"heads/{branch_name}")
        current_commit = self.git_repo.get_git_commit(ref.object.sha)
        base_tree = current_commit.tree

        # Create tree elements
        tree_elements = []
        for file_path, file_info in files_data.items():
            content = file_info["content"]
            if isinstance(content, str):
                content = content.encode('utf-8')

            blob = self.git_repo.create_git_blob(
                base64.b64encode(content).decode('utf-8'),
                "base64"
            )
            tree_elements.append(InputGitTreeElement(
                path=file_path,
                mode=file_info.get("mode", "100644"),
                type="blob",
                sha=blob.sha
            ))

        # Create new tree
        new_tree = self.git_repo.create_git_tree(tree_elements, base_tree)

        # Create commit
        new_commit = self.git_repo.create_git_commit(
            commit_message,
            new_tree,
            [current_commit]
        )

        # Update branch reference
        ref.edit(new_commit.sha)

        return new_commit

    @log_function_entry_exit()
    def _update_file(self, file_path, new_content, commit_message, branch_name: str = None) -> Optional[Dict]:
        try:
            branch_name = self.git_repo.default_branch if branch_name is None else branch_name

            # Get the current file
            file = self.git_repo.get_contents(file_path, ref=branch_name)

            # Update the file
            result = self.git_repo.update_file(
                path=file_path,
                message=commit_message,
                content=new_content,
                sha=file.sha,
                branch=branch_name
            )

            log_message(LoggingScope.TASK_OPS, 'INFO',
                        "File updated successfully. Commit SHA: %s", result['commit'].sha)
            return result

        except Exception as err:
            log_message(LoggingScope.TASK_OPS, 'ERROR', "Error updating file: %s", err)
            return None

    @log_function_entry_exit()
    def _handle_add_undetermined(self):
        """Handler for ADD action in UNDETERMINED state"""
        print("Handling ADD action in UNDETERMINED state: %s" % self.description.get_task_file_name())
        # task is in state UNDETERMINED if there is no pull request directory for the task yet
        #
        # create pull request directory (REPO/PR/SEQ/TASK_FILE_NAME/)
        # create task file in pull request directory (PULL_REQUEST_DIR/TaskDescription)
        # create task status file in pull request directory (PULL_REQUEST_DIR/TaskState.NEW_TASK)
        # create pointer file from task file path to pull request directory (remote_file_path -> PULL_REQUEST_DIR)
        repo_name = self.description.get_repo_name()
        pr_number = self.description.get_pr_number()
        sequence_number = self._get_fixed_sequence_number()  # corresponds to an open or yet to be created PR
        task_file_name = self.description.get_task_file_name()
        # we cannot use self._determine_pull_request_dir() here because it requires a task pointer file
        #   and we don't have one yet
        pull_request_dir = f"{repo_name}/{pr_number}/{sequence_number}/{task_file_name}"
        task_description_file_path = f"{pull_request_dir}/TaskDescription"
        task_state_file_path = f"{pull_request_dir}/TaskState"
        remote_file_path = self.description.task_object.remote_file_path

        files_to_commit = {
            task_description_file_path: {
                "content": self.description.get_contents(),
                "mode": "100644"
            },
            task_state_file_path: {
                "content": f"{TaskState.NEW_TASK.name}\n",
                "mode": "100644"
            },
            remote_file_path: {
                "content": f"remote_file_path = {remote_file_path}\npull_request_dir = {pull_request_dir}",
                "mode": "100644"
            }
        }

        branch_name = self.git_repo.default_branch
        try:
            commit = self._create_multi_file_commit(
                files_to_commit,
                f"new task for {repo_name} PR {pr_number} seq {sequence_number}",
                branch_name=branch_name
            )
            log_message(LoggingScope.TASK_OPS, 'INFO', "commit created: %s", commit)
        except Exception as err:
            log_message(LoggingScope.TASK_OPS, 'ERROR', "Error creating commit: %s", err)
            # TODO: rollback previous changes (task description file, task state file)
            return TaskState.UNDETERMINED

        # TODO: verify that the sequence number is still valid (PR corresponding to the sequence number
        #   is still open or yet to be created); if it is not valid, perform corrective actions
        return TaskState.NEW_TASK

    @log_function_entry_exit()
    def _update_task_state_file(self, next_state: TaskState, branch_name: str = None) -> Optional[Dict]:
        """Update the TaskState file content in default or given branch"""
        branch_name = self.git_repo.default_branch if branch_name is None else branch_name

        task_pointer_file = self.description.task_object.remote_file_path
        pull_request_dir = self._read_pull_request_dir_from_file(task_pointer_file, branch_name)
        task_state_file_path = f"{pull_request_dir}/TaskState"
        arch = self.description.get_metadata_file_components()[3]
        commit_message = f"change task state to {next_state} in {branch_name} for {arch}"
        result = self._update_file(task_state_file_path,
                                   f"{next_state.name}\n",
                                   commit_message,
                                   branch_name=branch_name)
        return result

    @log_function_entry_exit()
    def _init_payload_object(self):
        """Initialize the payload object"""
        if self.payload is not None:
            log_message(LoggingScope.TASK_OPS, 'INFO', "payload object already initialized")
            return

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

    @log_function_entry_exit()
    def _handle_add_new_task(self):
        """Handler for ADD action in NEW_TASK state"""
        print("Handling ADD action in NEW_TASK state: %s" % self.description.get_task_file_name())
        # determine next state
        next_state = self._next_state(TaskState.NEW_TASK)
        log_message(LoggingScope.TASK_OPS, 'INFO', "next_state: %s", next_state)

        # initialize payload object
        self._init_payload_object()

        # update TaskState file content
        self._update_task_state_file(next_state)

        # TODO: verify that the sequence number is still valid (PR corresponding to the sequence number
        #   is still open or yet to be created); if it is not valid, perform corrective actions
        return next_state

    @log_function_entry_exit()
    def _find_pr_for_branch(self, branch_name: str) -> Optional[PullRequest]:
        """
        Find the single PR for the given branch in any state.

        Args:
            repo: GitHub repository
            branch_name: Name of the branch

        Returns:
            PullRequest object if found, None otherwise
        """
        try:
            head_ref = f"{self.git_repo.owner.login}:{branch_name}"
            filter_prs = [16, 17, 18, 19, 20, 21, 22]  # TODO: remove this once the PR is merged
            prs = [pr for pr in list(self.git_repo.get_pulls(state='all', head=head_ref))
                   if pr.number not in filter_prs]
            return prs[0] if prs else None
        except Exception as err:
            log_message(LoggingScope.TASK_OPS, 'ERROR', "Error finding PR for branch %s: %s", branch_name, err)
            return None

    @log_function_entry_exit()
    def _determine_sequence_number_from_pull_request_directory(self) -> int:
        """Determine the sequence number from the pull request directory name"""
        task_pointer_file = self.description.task_object.remote_file_path
        pull_request_dir = self._read_pull_request_dir_from_file(task_pointer_file, self.git_repo.default_branch)
        # pull_request_dir is of the form REPO/PR/SEQ/TASK_FILE_NAME/ (REPO contains a '/' separating the org and repo)
        _, _, _, seq, _ = pull_request_dir.split('/')
        return int(seq)

    @log_function_entry_exit()
    def _determine_feature_branch_name(self) -> str:
        """Determine the feature branch name from the pull request directory name"""
        task_pointer_file = self.description.task_object.remote_file_path
        pull_request_dir = self._read_pull_request_dir_from_file(task_pointer_file, self.git_repo.default_branch)
        # pull_request_dir is of the form REPO/PR/SEQ/TASK_FILE_NAME/ (REPO contains a '/' separating the org and repo)
        org, repo, pr, seq, _ = pull_request_dir.split('/')
        return f"{org}-{repo}-PR-{pr}-SEQ-{seq}"

    @log_function_entry_exit()
    def _sync_task_state_file(self, source_branch: str, target_branch: str):
        """Update task state file from source to target branch"""
        task_pointer_file = self.description.task_object.remote_file_path
        pull_request_dir = self._read_pull_request_dir_from_file(task_pointer_file, self.git_repo.default_branch)
        task_state_file_path = f"{pull_request_dir}/TaskState"

        try:
            # Get content from source branch
            source_content = self.git_repo.get_contents(task_state_file_path, ref=source_branch)

            # Get current file in target branch
            target_file = self.git_repo.get_contents(task_state_file_path, ref=target_branch)

            # Update if content is different
            if source_content.sha != target_file.sha:
                result = self.git_repo.update_file(
                    path=task_state_file_path,
                    message=f"Sync {task_state_file_path} from {source_branch} to {target_branch}",
                    content=source_content.decoded_content,
                    sha=target_file.sha,
                    branch=target_branch
                )
                log_message(LoggingScope.TASK_OPS, 'INFO', "Updated %s", task_state_file_path)
                return result
            else:
                log_message(LoggingScope.TASK_OPS, 'INFO', "No changes needed for %s", task_state_file_path)
                return None

        except Exception as err:
            log_message(LoggingScope.TASK_OPS, 'ERROR', "Error syncing task state file: %s", err)
            return None

    @log_function_entry_exit()
    def _update_task_states(self, next_state: TaskState, default_branch_name: str,
                            approved_state: TaskState, feature_branch_name: str):
        """
        Update task states in default and feature branches

        States have to be updated in a specific order and in particular the default branch has to be
        merged into the feature branch before the feature branch can be updated to avoid a merge conflict.

        Args:
            next_state: next state to be applied to the default branch
            default_branch_name: name of the default branch
            approved_state: state to be applied to the feature branch
            feature_branch_name: name of the feature branch
        """
        # TODO: add failure handling (capture failures and return them somehow)

        # update TaskState file content
        # - next_state in default branch (interpreted as current state)
        # - approved_state in feature branch (interpreted as future state, ie, after
        #   the PR corresponding to the feature branch will be merged)

        # first, update the task state file in the default branch
        self._update_task_state_file(next_state, branch_name=default_branch_name)

        # second, merge default branch into feature branch (to avoid a merge conflict)
        # TODO: store arch info (CPU+ACCEL) in task/metdata file and then access that rather
        #       than using a part of the file name
        arch = self.description.get_metadata_file_components()[3]
        commit_message = f"merge {default_branch_name} into {feature_branch_name} for {arch}"
        self.git_repo.merge(
            head=default_branch_name,
            base=feature_branch_name,
            commit_message=commit_message
        )

        # last, update task state file in feature branch
        self._update_task_state_file(approved_state, branch_name=feature_branch_name)
        log_message(LoggingScope.TASK_OPS, 'INFO',
                    "TaskState file updated to %s in default branch (%s) and to %s in feature branch (%s)",
                    next_state, default_branch_name, approved_state, feature_branch_name)

    @log_function_entry_exit()
    def _create_task_summary(self) -> str:
        """Analyse contents of current task and create a file for it in the REPO-PR-SEQ directory."""

        # determine task summary file path in feature branch on GitHub
        feature_branch_name = self._determine_feature_branch_name()
        pull_request_dir = self._determine_pull_request_dir(branch_name=feature_branch_name)
        task_summary_file_path = f"{pull_request_dir}/TaskSummary.html"

        # check if task summary file already exists in repo on GitHub
        if self._path_exists_in_branch(task_summary_file_path, feature_branch_name):
            log_message(LoggingScope.TASK_OPS, 'INFO', "task summary file already exists: %s", task_summary_file_path)
            task_summary = self.git_repo.get_contents(task_summary_file_path, ref=feature_branch_name)
            # return task_summary.decoded_content
            return task_summary

        # create task summary
        payload_name = self.description.metadata['payload']['filename']
        payload_summary = self.payload.analyse_contents()
        metadata_contents = self.description.get_contents()
        task_summary = f"<details><summary><code>{payload_name}</code></summary>\n\n"
        task_summary += "<details><summary>Metadata</summary>\n\n"
        task_summary += f"```\n{metadata_contents}\n```\n</details>\n"
        task_summary += "<details><summary>Overview of payload contents</summary>\n\n"
        task_summary += self.config['github']['task_summary_payload_template'].format(
            payload_overview=payload_summary,
        )
        task_summary += "</details>\n"
        task_summary += "\n"
        task_summary += "</details>\n"

        # create HTML file with task summary in REPO-PR-SEQ directory
        # TODO: add failure handling (capture result and act on it)
        task_file_name = self.description.get_task_file_name()
        commit_message = f"create summary for {task_file_name} in {feature_branch_name}"
        self._safe_create_file(task_summary_file_path, commit_message, task_summary,
                               branch_name=feature_branch_name)
        log_message(LoggingScope.TASK_OPS, 'INFO', "task summary file created: %s", task_summary_file_path)

        # return task summary
        return task_summary

    @log_function_entry_exit()
    def _create_pr_contents_overview(self) -> str:
        """Create a contents overview for the pull request"""
        # TODO: implement
        feature_branch_name = self._determine_feature_branch_name()
        task_pointer_file = self.description.task_object.remote_file_path
        pull_request_dir = self._read_pull_request_dir_from_file(task_pointer_file, feature_branch_name)
        pr_dir = os.path.dirname(pull_request_dir)
        directories = self._list_directory_contents(pr_dir, feature_branch_name)
        contents_overview = ""
        if directories:
            contents_overview += "\n"
            for directory in directories:
                task_summary_file_path = f"{pr_dir}/{directory.name}/TaskSummary.html"
                if self._path_exists_in_branch(task_summary_file_path, feature_branch_name):
                    file_contents = self.git_repo.get_contents(task_summary_file_path, ref=feature_branch_name)
                    task_summary = base64.b64decode(file_contents.content).decode('utf-8')
                    contents_overview += f"{task_summary}\n"
                else:
                    contents_overview += f"Task summary file not found: {task_summary_file_path}\n"
            contents_overview += "\n"
        else:
            contents_overview += "No tasks found in this PR\n"

        print(f"contents_overview: {contents_overview}")
        return contents_overview

    @log_function_entry_exit()
    def _create_pull_request(self, feature_branch_name: str, default_branch_name: str):
        """
        Create a PR from the feature branch to the default branch

        Args:
            feature_branch_name: name of the feature branch
            default_branch_name: name of the default branch
        """
        pr_title_format = self.config['github']['grouped_pr_title']
        pr_body_format = self.config['github']['grouped_pr_body']
        repo_name = self.description.get_repo_name()
        pr_number = self.description.get_pr_number()
        pr_url = f"https://github.com/{repo_name}/pull/{pr_number}"
        seq_num = self._determine_sequence_number_from_pull_request_directory()
        pr_title = pr_title_format.format(
            cvmfs_repo=self.cvmfs_repo,
            pr=pr_number,
            repo=repo_name,
            seq_num=seq_num,
        )
        self._create_task_summary()
        contents_overview = self._create_pr_contents_overview()
        pr_body = pr_body_format.format(
            cvmfs_repo=self.cvmfs_repo,
            pr=pr_number,
            pr_url=pr_url,
            repo=repo_name,
            seq_num=seq_num,
            contents=contents_overview,
            analysis="TO BE DONE",
            action="TO BE DONE",
        )
        pr = self.git_repo.create_pull(
            title=pr_title,
            body=pr_body,
            head=feature_branch_name,
            base=default_branch_name
        )
        log_message(LoggingScope.TASK_OPS, 'INFO', "PR created: %s", pr)

    @log_function_entry_exit()
    def _update_pull_request(self, pull_request: PullRequest):
        """
        Update the pull request

        Args:
            pull_request: instance of the pull request
        """
        # TODO: update sections (contents analysis, action)
        repo_name = self.description.get_repo_name()
        pr_number = self.description.get_pr_number()
        pr_url = f"https://github.com/{repo_name}/pull/{pr_number}"
        seq_num = self._determine_sequence_number_from_pull_request_directory()

        self._create_task_summary()
        contents_overview = self._create_pr_contents_overview()
        pr_body_format = self.config['github']['grouped_pr_body']
        pr_body = pr_body_format.format(
            cvmfs_repo=self.cvmfs_repo,
            pr=pr_number,
            pr_url=pr_url,
            repo=repo_name,
            seq_num=seq_num,
            contents=contents_overview,
            analysis="TO BE DONE",
            action="TO BE DONE",
        )
        pull_request.edit(body=pr_body)

        log_message(LoggingScope.TASK_OPS, 'INFO', "PR updated: %s", pull_request)

    @log_function_entry_exit()
    def _handle_add_payload_staged(self):
        """Handler for ADD action in PAYLOAD_STAGED state"""
        print("Handling ADD action in PAYLOAD_STAGED state: %s" % self.description.get_task_file_name())
        next_state = self._next_state(TaskState.PAYLOAD_STAGED)
        approved_state = TaskState.APPROVED
        log_message(LoggingScope.TASK_OPS, 'INFO', "next_state: %s, approved_state: %s", next_state, approved_state)

        default_branch_name = self.git_repo.default_branch
        default_branch = self._get_branch_from_name(default_branch_name)
        default_sha = default_branch.commit.sha
        feature_branch_name = self._determine_feature_branch_name()
        feature_branch = self._get_branch_from_name(feature_branch_name)
        if not feature_branch:
            # feature branch does not exist
            # TODO: could have been merged already --> check if PR corresponding to the feature branch exists
            # ASSUME: it has not existed before --> create it
            log_message(LoggingScope.TASK_OPS, 'INFO',
                        "branch %s does not exist, creating it", feature_branch_name)

            feature_branch = self.git_repo.create_git_ref(f"refs/heads/{feature_branch_name}", default_sha)
            log_message(LoggingScope.TASK_OPS, 'INFO',
                        "branch %s created: %s", feature_branch_name, feature_branch)
        else:
            log_message(LoggingScope.TASK_OPS, 'INFO',
                        "found existing branch for %s: %s", feature_branch_name, feature_branch)

        pull_request = self._find_pr_for_branch(feature_branch_name)
        if not pull_request:
            log_message(LoggingScope.TASK_OPS, 'INFO',
                        "no PR found for branch %s", feature_branch_name)

            # TODO: add failure handling (capture result and act on it)
            self._update_task_states(next_state, default_branch_name, approved_state, feature_branch_name)

            # TODO: add failure handling (capture result and act on it)
            self._create_pull_request(feature_branch_name, default_branch_name)

            return TaskState.PULL_REQUEST
        else:
            log_message(LoggingScope.TASK_OPS, 'INFO',
                        "found existing PR for branch %s: %s", feature_branch_name, pull_request)
            # TODO: check if PR is open or closed
            if pull_request.state == 'closed':
                log_message(LoggingScope.TASK_OPS, 'INFO',
                            "PR %s is closed, creating issue", pull_request)
                # TODO: create issue
                return TaskState.PAYLOAD_STAGED
            else:
                log_message(LoggingScope.TASK_OPS, 'INFO',
                            "PR %s is open, updating task states", pull_request)
                # TODO: add failure handling (capture result and act on it)
                #   THINK about what a failure would mean and what to do about it.
                self._update_task_states(next_state, default_branch_name, approved_state, feature_branch_name)

                # TODO: add failure handling (capture result and act on it)
                self._update_pull_request(pull_request)

                return TaskState.PULL_REQUEST

    @log_function_entry_exit()
    def _handle_add_pull_request(self):
        """Handler for ADD action in PULL_REQUEST state"""
        print("Handling ADD action in PULL_REQUEST state: %s" % self.description.get_task_file_name())
        # Implementation for adding in PULL_REQUEST state
        # we got here because the state of the task is PULL_REQUEST in the default branch
        # determine branch and PR and state of PR
        # PR is open --> just return TaskState.PULL_REQUEST
        # PR is closed & merged --> deployment is approved
        # PR is closed & not merged --> deployment is rejected
        feature_branch_name = self._determine_feature_branch_name()
        # TODO: check if feature branch exists, for now ASSUME it does
        pull_request = self._find_pr_for_branch(feature_branch_name)
        if pull_request:
            log_message(LoggingScope.TASK_OPS, 'INFO',
                        "found PR for branch %s: %s", feature_branch_name, pull_request)
            if pull_request.state == 'closed':
                if pull_request.merged:
                    log_message(LoggingScope.TASK_OPS, 'INFO',
                                "PR %s is closed and merged, returning APPROVED state", pull_request)
                    # TODO: How could we ended up here? state in default branch is PULL_REQUEST but
                    #         PR is merged, hence it should have been in the APPROVED state
                    #    ==> for now, just return TaskState.PULL_REQUEST
                    #
                    #       there is the possibility that the PR was updated just before the
                    #         PR was merged
                    #       WHY is it a problem? because a task may have been accepted that wouldn't
                    #         have been accepted or worse shouldn't been accepted
                    #       WHAT to do? ACCEPT/IGNORE THE ISSUE FOR NOw
                    #       HOWEVER, the contents of the PR directory may be inconsistent with
                    #         respect to the TaskState file and missing TaskSummary.html file
                    #       WE could create an issue and only return TaskState.APPROVED if the
                    #         issue is closed
                    #       WE could also defer all handling of this to the handler for the
                    #         APPROVED state
                    # NOPE, we have to do some handling here, at least for the tasks where their
                    #   state file did
                    #   --> check if we could have ended up here? If so, create an issue.
                    #       Do we need a state ISSUE_OPENED to avoid processing the task again?
                    return TaskState.PULL_REQUEST
                else:
                    log_message(LoggingScope.TASK_OPS, 'INFO',
                                "PR %s is closed and not merged, returning REJECTED state", pull_request)
                    # TODO: there is the possibility that the PR was updated just before the
                    #         PR was closed
                    #       WHY is it a problem? because a task may have been rejected that wouldn't
                    #         have been rejected or worse shouldn't been rejected
                    #       WHAT to do? ACCEPT/IGNORE THE ISSUE FOR NOw
                    #       HOWEVER, the contents of the PR directory may be inconsistent with
                    #         respect to the TaskState file and missing TaskSummary.html file
                    #       WE could create an issue and only return TaskState.REJECTED if the
                    #         issue is closed
                    #       WE could also defer all handling of this to the handler for the
                    #         REJECTED state
                    # FOR NOW, we assume that the task was rejected on purpose
                    #   we need to change the state of the task in the default branch to REJECTED
                    self._update_task_state_file(TaskState.REJECTED)
                    return TaskState.REJECTED
            else:
                log_message(LoggingScope.TASK_OPS, 'INFO',
                            "PR %s is open, returning PULL_REQUEST state", pull_request)
                return TaskState.PULL_REQUEST
        else:
            log_message(LoggingScope.TASK_OPS, 'INFO',
                        "no PR found for branch %s", feature_branch_name)
            # the method was called because the state of the task is PULL_REQUEST in the default branch
            # however, it's weird that the PR was not found for the feature branch
            # TODO: may create or update an issue for the task or deployment
            return TaskState.PULL_REQUEST

        return TaskState.PULL_REQUEST

    @log_function_entry_exit()
    def _perform_task_action(self) -> bool:
        """Perform the task action"""
        # TODO: support other actions than ADD
        if self.action == EESSITaskAction.ADD:
            return self._perform_task_add()
        else:
            raise ValueError(f"Task action '{self.action}' not supported (yet)")

    @log_function_entry_exit()
    def _issue_exists(self, title: str, state: str = 'open') -> bool:
        """
        Check if an issue with the given title and state already exists.
        """
        issues = self.git_repo.get_issues(state=state)
        for issue in issues:
            if issue.title == title and issue.state == state:
                return True
        else:
            return False

    @log_function_entry_exit()
    def _perform_task_add(self) -> bool:
        """Perform the ADD task action"""
        # TODO: verify checksum here or before?
        script = self.config['paths']['ingestion_script']
        sudo = ['sudo'] if self.config['cvmfs'].getboolean('ingest_as_root', True) else []
        log_message(LoggingScope.STATE_OPS, 'INFO',
                    'Running the ingestion script for %s...\n  with script: %s\n  with sudo: %s',
                    self.description.get_task_file_name(),
                    script, 'no' if sudo == [] else 'yes')
        ingest_cmd = subprocess.run(
            sudo + [script, self.cvmfs_repo, str(self.payload.payload_object.local_file_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE)
        log_message(LoggingScope.STATE_OPS, 'INFO',
                    'Ingestion script returned code %s', ingest_cmd.returncode)
        log_message(LoggingScope.STATE_OPS, 'INFO',
                    'Ingestion script stdout: %s', ingest_cmd.stdout.decode('UTF-8'))
        log_message(LoggingScope.STATE_OPS, 'INFO',
                    'Ingestion script stderr: %s', ingest_cmd.stderr.decode('UTF-8'))
        if ingest_cmd.returncode == 0:
            next_state = self._next_state(TaskState.APPROVED)
            self._update_task_state_file(next_state)
            if self.config.has_section('slack') and self.config['slack'].getboolean('ingestion_notification', False):
                send_slack_message(
                    self.config['secrets']['slack_webhook'],
                    self.config['slack']['ingestion_message'].format(
                        tarball=os.path.basename(self.payload.payload_object.local_file_path),
                        cvmfs_repo=self.cvmfs_repo)
                )
            return True
        else:
            tarball = os.path.basename(self.payload.payload_object.local_file_path)
            log_message(LoggingScope.STATE_OPS, 'ERROR',
                        'Failed to add %s, return code %s',
                        tarball,
                        ingest_cmd.returncode)

            issue_title = f'Failed to add {tarball}'
            log_message(LoggingScope.STATE_OPS, 'INFO',
                        "Creating issue for failed ingestion: title: '%s'",
                        issue_title)

            command = ' '.join(ingest_cmd.args)
            failed_ingestion_issue_body = self.config['github']['failed_ingestion_issue_body']
            issue_body = failed_ingestion_issue_body.format(
                command=command,
                tarball=tarball,
                return_code=ingest_cmd.returncode,
                stdout=ingest_cmd.stdout.decode('UTF-8'),
                stderr=ingest_cmd.stderr.decode('UTF-8')
            )
            log_message(LoggingScope.STATE_OPS, 'INFO',
                        "Creating issue for failed ingestion: body: '%s'",
                        issue_body)

            if self._issue_exists(issue_title, state='open'):
                log_message(LoggingScope.STATE_OPS, 'INFO',
                            'Failed to add %s, but an open issue already exists, skipping...',
                            os.path.basename(self.payload.payload_object.local_file_path))
            else:
                log_message(LoggingScope.STATE_OPS, 'INFO',
                            'Failed to add %s, but an open issue does not exist, creating one...',
                            os.path.basename(self.payload.payload_object.local_file_path))
                self.git_repo.create_issue(title=issue_title, body=issue_body)
            return False

    @log_function_entry_exit()
    def _handle_add_approved(self):
        """Handler for ADD action in APPROVED state"""
        print("Handling ADD action in APPROVED state: %s" % self.description.get_task_file_name())
        # Implementation for adding in APPROVED state
        # If successful, _perform_task_action() will change the state
        #   to INGESTED on GitHub
        try:
            if self._perform_task_action():
                return TaskState.INGESTED
            else:
                return TaskState.APPROVED
        except Exception as err:
            log_message(LoggingScope.TASK_OPS, 'ERROR',
                        "Error performing task action: '%s'\nTraceback:\n%s", err, traceback.format_exc())
            return TaskState.APPROVED

    @log_function_entry_exit()
    def _handle_add_ingested(self):
        """Handler for ADD action in INGESTED state"""
        print("Handling ADD action in INGESTED state: %s" % self.description.get_task_file_name())
        # Implementation for adding in INGESTED state
        # DONT change state on GitHub, because the result
        #   (INGESTED/REJECTED) would be overwritten
        return TaskState.DONE

    @log_function_entry_exit()
    def _handle_add_rejected(self):
        """Handler for ADD action in REJECTED state"""
        print("Handling ADD action in REJECTED state: %s" % self.description.get_task_file_name())
        # Implementation for adding in REJECTED state
        # DONT change state on GitHub, because the result
        #   (INGESTED/REJECTED) would be overwritten
        return TaskState.DONE

    @log_function_entry_exit()
    def __str__(self):
        return f"EESSITask(description={self.description}, action={self.action}, state={self.determine_state()})"
