from enum import Enum, auto
from typing import Dict, List, Tuple, Optional

import os
import traceback
import base64

from eessi_data_object import EESSIDataAndSignatureObject
from eessi_task_action import EESSITaskAction
from eessi_task_description import EESSITaskDescription
from eessi_task_payload import EESSITaskPayload
from utils import log_message, LoggingScope, log_function_entry_exit

from github import Github, GithubException, InputGitTreeElement, UnknownObjectException
from github.PullRequest import PullRequest


class SequenceStatus(Enum):
    DOES_NOT_EXIST = auto()
    IN_PROGRESS = auto()
    FINISHED = auto()


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

#        try:
#            log_message(LoggingScope.TASK_OPS, 'INFO', "from_string will iterate over: %s", cls.__members__)
#            to_return = next(
#                member for member_name, member in cls.__members__.items()
#                if member_name.lower() == name.lower()
#            )
#            log_message(LoggingScope.TASK_OPS, 'INFO', "from_string will return: %s", to_return)
#            return to_return
#        except StopIteration:
#            return default

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
            TaskState.UNDETERMINED: [TaskState.NEW_TASK, TaskState.PAYLOAD_STAGED, TaskState.PULL_REQUEST,
                                     TaskState.APPROVED, TaskState.REJECTED, TaskState.INGESTED, TaskState.DONE],
            TaskState.NEW_TASK: [TaskState.PAYLOAD_STAGED],
            TaskState.PAYLOAD_STAGED: [TaskState.PULL_REQUEST],
            TaskState.PULL_REQUEST: [TaskState.APPROVED, TaskState.REJECTED],
            TaskState.APPROVED: [TaskState.INGESTED],
            TaskState.REJECTED: [TaskState.DONE],
            TaskState.INGESTED: [TaskState.DONE],
            TaskState.DONE: []  # Terminal state
        }

        # self.state = self._find_state()

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
        return 0

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
        pr = self.git_repo.create_pull(title=f"Add task for {repo_name} PR {pr_number} seq {sequence_number}",
                                       body=f"Add task for {repo_name} PR {pr_number} seq {sequence_number}",
                                       head=branch_name, base=self.git_repo.default_branch)
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
    def _path_exists_in_branch(self, path: str, branch: str = None) -> bool:
        """
        Check if a path exists in a branch.
        """
        branch = self.git_repo.default_branch if branch is None else branch
        try:
            self.git_repo.get_contents(path, ref=branch)
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
    def _read_target_dir_from_file(self, path: str, branch: str = None) -> str:
        """
        Read the target directory from the file in the given branch.
        """
        branch = self.git_repo.default_branch if branch is None else branch
        content = self.git_repo.get_contents(path, ref=branch)

        # Decode the content from base64
        content_str = content.decoded_content.decode('utf-8')

        # Parse into dictionary
        config_dict = self._read_dict_from_string(content_str)

        return config_dict.get('target_dir', None)

    @log_function_entry_exit()
    def _branch_exists(self, branch_name: str) -> bool:
        """
        Check if a branch exists.
        """
        try:
            self.git_repo.get_branch(branch_name)
            return True
        except Exception as err:
            log_message(LoggingScope.TASK_OPS, 'ERROR', "error checking if branch %s exists: %s",
                        branch_name, err)
            return False

    @log_function_entry_exit()
    def _read_task_state_from_file(self, path: str, branch: str = None) -> TaskState:
        """
        Read the task state from the file in the given branch.
        """
        branch = self.git_repo.default_branch if branch is None else branch
        content = self.git_repo.get_contents(path, ref=branch)

        # Decode the content from base64
        content_str = content.decoded_content.decode('utf-8').strip()
        log_message(LoggingScope.TASK_OPS, 'INFO', "content in TaskState file: %s", content_str)

        task_state = TaskState.from_string(content_str)
        log_message(LoggingScope.TASK_OPS, 'INFO', "task state: %s", task_state)

        return task_state

    @log_function_entry_exit()
    def determine_state(self) -> TaskState:
        """
        Determine the state of the task based on the state of the staging repository.
        """
        # High-level logic:
        # 1. Check if path representing the task file exists in the default branch
        path_in_default_branch = self.description.task_object.remote_file_path
        default_branch = self.git_repo.default_branch
        if self._path_exists_in_branch(path_in_default_branch, branch=default_branch):
            log_message(LoggingScope.TASK_OPS, 'INFO', "path %s exists in default branch",
                        path_in_default_branch)
            # TODO: determine state
            # - get state from task file in default branch
            #   - get target_dir from path_in_default_branch
            target_dir = self._read_target_dir_from_file(path_in_default_branch, default_branch)
            # read the TaskState file in target dir
            task_state_file_path = f"{target_dir}/TaskState"
            task_state_default_branch = self._read_task_state_from_file(task_state_file_path, default_branch)
            # - if branch for sequence number exists, get state from task file in corresponding branch
            #   - branch name is of the form REPO-PR-SEQ
            #   - target dir is of the form REPO/PR/SEQ/TASK_FILE_NAME/
            #   - obtain repo, pr, seq from target dir
            org, repo, pr, seq, _ = target_dir.split('/')
            staging_branch_name = f"{org}-{repo}-PR-{pr}-SEQ-{seq}"
            if self._branch_exists(staging_branch_name):
                # read the TaskState file in staging branch
                task_state_staging_branch = self._read_task_state_from_file(task_state_file_path, staging_branch_name)
                log_message(LoggingScope.TASK_OPS, 'INFO', "task state in staging branch %s: %s",
                            staging_branch_name, task_state_staging_branch)
                return task_state_staging_branch
            else:
                log_message(LoggingScope.TASK_OPS, 'INFO', "task state in default branch: %s",
                            task_state_default_branch)
                return task_state_default_branch
        else:
            log_message(LoggingScope.TASK_OPS, 'INFO', "path %s does not exist in default branch",
                        path_in_default_branch)
            return TaskState.UNDETERMINED

    @log_function_entry_exit()
    def handle(self):
        """
        Dynamically find and execute the appropriate handler based on action and state.
        """
        state_before_handle = self.determine_state()

        # Construct handler method name
        handler_name = f"_handle_{self.action}_{state_before_handle}"

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
    def _create_symlink(self, source_path: str, target_path: str, branch: str = None):
        """Create a symlink in the given branch."""
        try:
            branch = self.git_repo.default_branch if branch is None else branch
            ref = self.git_repo.get_git_ref(f"heads/{branch}")
            commit = self.git_repo.get_git_commit(ref.object.sha)
            base_tree = self.git_repo.get_git_tree(commit.tree.sha)

            # Create blob for symlink target
            blob = self.git_repo.create_git_blob(target_path, "utf-8")
            log_message(LoggingScope.TASK_OPS, 'INFO', "blob created: %s", blob)

            # Create tree element
            tree_element = InputGitTreeElement(
                path=source_path,
                mode="120000",
                type="blob",
                sha=blob.sha
            )
            log_message(LoggingScope.TASK_OPS, 'INFO', "tree element created: %s", tree_element)

            # Create new tree
            try:
                new_tree = self.git_repo.create_git_tree([tree_element], base_tree)
                log_message(LoggingScope.TASK_OPS, 'INFO', "new tree created: %s", new_tree)
            except GithubException as err:
                log_message(LoggingScope.TASK_OPS, 'ERROR', "Error creating new tree: %s", err)
                log_message(LoggingScope.TASK_OPS, 'ERROR', "  Status Code: %s", err.status)
                log_message(LoggingScope.TASK_OPS, 'ERROR', "  Error Message: %s", err.data)
                log_message(LoggingScope.TASK_OPS, 'ERROR', "  Headers: %s", err.headers)
                log_message(LoggingScope.TASK_OPS, 'ERROR', "  Raw Response: %s", err.response)
                return False
            except Exception as err:
                log_message(LoggingScope.TASK_OPS, 'ERROR', "\n=== General Exception ===")
                log_message(LoggingScope.TASK_OPS, 'ERROR', "  Type: %s", type(err).__name__)
                log_message(LoggingScope.TASK_OPS, 'ERROR', "  Message: %s", str(err))
                log_message(LoggingScope.TASK_OPS, 'ERROR', "  Traceback:")
                log_message(LoggingScope.TASK_OPS, 'ERROR', "    %s", traceback.format_exc())
                return False

            # Create new commit
            commit_message = f"Add symlink {source_path} -> {target_path}"
            new_commit = self.git_repo.create_git_commit(commit_message, new_tree, [commit])
            log_message(LoggingScope.TASK_OPS, 'INFO', "new commit created: %s", new_commit)

            # Update reference
            ref.edit(new_commit.sha)

            log_message(LoggingScope.TASK_OPS, 'INFO', "Symlink created: %s -> %s",
                        source_path, target_path)
            return True

        except Exception as err:
            log_message(LoggingScope.TASK_OPS, 'ERROR', "Error creating symlink: %s", err)
            return False

    @log_function_entry_exit()
    def _safe_create_file(self, path: str, message: str, content: str, branch: str = None):
        """Create a file in the given branch."""
        try:
            branch = self.git_repo.default_branch if branch is None else branch
            existing_file = self.git_repo.get_contents(path, ref=branch)
            log_message(LoggingScope.TASK_OPS, 'INFO', "File %s already exists", path)
            return existing_file
        except GithubException as err:
            if err.status == 404:  # File doesn't exist
                # Safe to create
                return self.git_repo.create_file(path, message, content, branch=branch)
            else:
                raise err  # Some other error

    @log_function_entry_exit()
    def _create_multi_file_commit(self, files_data, commit_message, branch=None):
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
        branch = self.git_repo.default_branch if branch is None else branch
        ref = self.git_repo.get_git_ref(f"heads/{branch}")
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
    def _handle_add_undetermined(self):
        """Handler for ADD action in UNDETERMINED state"""
        print("Handling ADD action in UNDETERMINED state")
        # create target directory (REPO/PR/SEQ/TASK_FILE_NAME/)
        # create task file in target directory (TARGET_DIR/TaskDescription)
        # create task status file in target directory (TARGET_DIR/TaskState.NEW_TASK)
        # create pointer file from task file path to target directory (remote_file_path -> TARGET_DIR)
        branch = self.git_repo.default_branch
        repo_name = self.description.get_repo_name()
        pr_number = self.description.get_pr_number()
        sequence_number = self._get_fixed_sequence_number()  # corresponds to an open or yet to be created PR
        task_file_name = self.description.get_task_file_name()
        target_dir = f"{repo_name}/{pr_number}/{sequence_number}/{task_file_name}"
        task_description_file_path = f"{target_dir}/TaskDescription"
        task_state_file_path = f"{target_dir}/TaskState"
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
                "content": f"remote_file_path = {remote_file_path}\ntarget_dir = {target_dir}",
                "mode": "100644"
            }
        }

        try:
            commit = self._create_multi_file_commit(
                files_to_commit,
                f"new task for {repo_name} PR {pr_number} seq {sequence_number}",
                branch=branch
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
    def _handle_add_new_task(self):
        """Handler for ADD action in NEW_TASK state"""
        print("Handling ADD action in NEW_TASK state")
        # Implementation for adding in NEW_TASK state: a task is only NEW_TASK if it was not processed yet
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
        # REPO/PR_NUM/SEQ_NUM/task_file_name.NEXT_STATE
        next_state = self._next_state()
        log_message(LoggingScope.TASK_OPS, 'INFO', "next_state: %s", next_state)
        repo_name = self.description.get_repo_name()
        pr_number = self.description.get_pr_number()
        repo_pr_dir = f"{repo_name}/{pr_number}"
        sequence_numbers = self._determine_sequence_numbers_including_task_file(repo_name, pr_number)
        if len(sequence_numbers) == 0:
            sequence_number = 0
        else:
            # we need to figure out the status of the last deployment (with the highest sequence number)
            # if a PR exists and it is closed, we add the task to the *next* higher sequence number
            # otherwise we add the task to the highest sequence number
            sequence_number = self._find_highest_number(sequence_numbers.keys())
            branch_name = f"{repo_name.replace('/', '-')}-PR-{pr_number}-SEQ-{sequence_number}"
            if branch_name in [branch.name for branch in self.git_repo.get_branches()]:
                # branch exists, check if PR exists
                find_pr = [pr for pr in self.git_repo.get_pulls(head=branch_name, state='all')]
                if find_pr:
                    pr = find_pr.pop(0)
                    if pr.state == 'closed':
                        sequence_number += 1
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
    def _handle_add_payload_staged(self):
        """Handler for ADD action in PAYLOAD_STAGED state"""
        print("Handling ADD action in PAYLOAD_STAGED state")
        # Implementation for adding in PAYLOAD_STAGED state
        #  - create or find PR
        #  - update PR contents
        # determine PR
        #  - no PR -> create one
        #  - PR && closed -> create one (may require to move task file to different sequence number)
        #  - PR && open -> update PR contents, task file status, etc
        # TODO: determine sequence number, then use it to find staging pr
        # find staging PR
        sequence_number = self._get_sequence_number_for_task_file()
        staging_pr, staging_branch = self._find_staging_pr(sequence_number)
        # create PR if necessary
        if staging_pr is None and sequence_number is None:
            # no PR found, create one
            staging_pr, staging_branch = self._create_staging_pr(sequence_number)
        elif staging_pr is None and sequence_number is not None:
            # no PR found, create one
            staging_pr, staging_branch = self._create_staging_pr(sequence_number)
        elif staging_pr.state == 'closed':
            # PR closed, create new one
            staging_pr, staging_branch = self._create_staging_pr(sequence_number + 1)
        if staging_pr is None:
            # something went wrong, we cannot continue
            log_message(LoggingScope.ERROR, 'ERROR', "no staging PR found for task %s", self.description)
            return False
        # update PR contents
        self._update_pr_contents(staging_pr)
        # update task file status
        self._update_task_file_status(staging_branch)

        repo_name = self.description.get_repo_name()
        pr_number = self.description.get_pr_number()
        # current sequence
        sequence_number = self._get_current_sequence_number()
        sequence_status = self._determine_sequence_status(sequence_number)
        if sequence_status == SequenceStatus.FINISHED:
            sequence_number += 1
            # re-determine sequence status
            sequence_status = self._determine_sequence_status(sequence_number)
        if sequence_status == SequenceStatus.DOES_NOT_EXIST:
            # something is odd, the task file should already be in the default branch
            log_message(LoggingScope.ERROR, 'ERROR', "sequence number %s does not exist", sequence_number)
            return False
        elif sequence_status == SequenceStatus.FINISHED:
            # we need to figure out the status of the last deployment (with the highest sequence number)
            branch_name = f"{repo_name.replace('/', '-')}-PR-{pr_number}-SEQ-{sequence_number}"
            log_message(LoggingScope.TASK_OPS, 'INFO', "branch %s exists", branch_name)
        # check if branch exists
        # - yes: check if corresponding PR exists
        #   - yes: check status of PR
        #     - open: rename file and add it to branch, set state, update PR contents, return
        #     - closed && !merged: rename file to rejected, set state
        #     - else: weird state, log message, return
        #   - no: delete branch
        # create new branch, add task file to branch, set state, create PR, update PR contents, return
        return True

    @log_function_entry_exit()
    def _handle_add_pull_request(self):
        """Handler for ADD action in PULL_REQUEST state"""
        print("Handling ADD action in PULL_REQUEST state")
        # Implementation for adding in PULL_REQUEST state
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
        return f"EESSITask(description={self.description}, action={self.action}, state={self.determine_state()})"
