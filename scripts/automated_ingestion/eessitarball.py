from utils import send_slack_message, sha256sum

from pathlib import PurePosixPath

import github
import json
import logging
import os
import subprocess
import tarfile


class EessiTarball:
    """
    Class that represents an EESSI tarball containing software installations or a compatibility layer,
    and which is stored in an S3 bucket.
    It has several functions to handle the different states of such a tarball in the actual ingestion process,
    for which it interfaces with the S3 bucket, GitHub, and CVMFS.
    """

    def __init__(self, object_name, config, git_staging_repo, s3, bucket, cvmfs_repo):
        """Initialize the tarball object."""
        self.config = config
        self.git_repo = git_staging_repo
        self.metadata_file = object_name + config['paths']['metadata_file_extension']
        self.metadata_sig_file = self.metadata_file + config['signatures']['signature_file_extension']
        self.object = object_name
        self.object_sig = object_name + config['signatures']['signature_file_extension']
        self.s3 = s3
        self.bucket = bucket
        self.cvmfs_repo = cvmfs_repo
        self.local_path = os.path.join(config['paths']['download_dir'], os.path.basename(object_name))
        self.local_sig_path = self.local_path + config['signatures']['signature_file_extension']
        self.local_metadata_path = self.local_path + config['paths']['metadata_file_extension']
        self.local_metadata_sig_path = self.local_metadata_path + config['signatures']['signature_file_extension']
        self.sig_verified = False
        self.url = f'https://{bucket}.s3.amazonaws.com/{object_name}'

        self.states = {
            'new': {'handler': self.mark_new_tarball_as_staged, 'next_state': 'staged'},
            'staged': {'handler': self.make_approval_request, 'next_state': 'approved'},
            'approved': {'handler': self.ingest, 'next_state': 'ingested'},
            'ingested': {'handler': self.print_ingested},
            'rejected': {'handler': self.print_rejected},
            'unknown': {'handler': self.print_unknown},
        }

        # Find the initial state of this tarball.
        self.state = self.find_state()

    def download(self, force=False):
        """
        Download this tarball and its corresponding metadata file, if this hasn't been already done.
        """
        files = [
            (self.object, self.local_path, self.object_sig, self.local_sig_path),
            (self.metadata_file, self.local_metadata_path, self.metadata_sig_file, self.local_metadata_sig_path),
        ]
        skip = False
        for (object, local_file, sig_object, local_sig_file) in files:
            if force or not os.path.exists(local_file):
                # First we try to download signature file, which may or may not be available
                # and may be optional or required.
                try:
                    self.s3.download_file(self.bucket, sig_object, local_sig_file)
                except Exception as err:
                    log_msg = 'Failed to download signature file %s for %s from %s to %s.'
                    if self.config['signatures'].getboolean('signatures_required', True):
                        log_msg += '\nException: %s'
                        logging.error(log_msg, sig_object, object, self.bucket, local_sig_file, err)
                        skip = True
                        break
                    else:
                        log_msg += ' Ignoring this, because signatures are not required with the current configuration.'
                        log_msg += '\nException: %s'
                        logging.warning(log_msg, sig_object, object, self.bucket, local_sig_file, err)
                # Now we download the file itself.
                try:
                    self.s3.download_file(self.bucket, object, local_file)
                except Exception as err:
                    log_msg = 'Failed to download %s from %s to %s.\nException: %s'
                    logging.error(log_msg, object, self.bucket, local_file, err)
                    skip = True
                    break
        # If any required download failed, make sure to skip this tarball completely.
        if skip:
            self.local_path = None
            self.local_metadata_path = None

    def find_state(self):
        """Find the state of this tarball by searching through the state directories in the git repository."""
        logging.debug(f"Find state for {self.object}")
        for state in list(self.states.keys()):
            try:
                self.git_repo.get_contents(state + '/' + self.metadata_file)
                logging.info(f"Found metadata file {self.metadata_file} in state: {state}")
                return state
            except github.UnknownObjectException:
                # no metadata file found in this state's directory, so keep searching...
                continue
            except github.GithubException as err:
                if err.status == 404:
                    # no metadata file found in this state's directory, so keep searching...
                    continue
                else:
                    # if there was some other (e.g. connection) issue, abort the search for this tarball
                    log_msg = 'Unable to determine the state of %s, the GitHub API returned status %s!'
                    logging.warning(log_msg, self.object, err.status)
                    return "unknown"
        logging.info(f"Tarball {self.metadata_file} is new")
        return "new"

    def get_contents_overview(self):
        """Return an overview of what is included in the tarball."""
        tar = tarfile.open(self.local_path, 'r')
        members = tar.getmembers()
        tar_num_members = len(members)
        paths = sorted([m.path for m in members])

        if tar_num_members < 100:
            tar_members_desc = 'Full listing of the contents of the tarball:'
            members_list = paths

        else:
            tar_members_desc = 'Summarized overview of the contents of the tarball:'
            # determine prefix after filtering out '<EESSI version>/init' subdirectory,
            # to get actual prefix for specific CPU target (like '2023.06/software/linux/aarch64/neoverse_v1')
            init_subdir = os.path.join('*', 'init')
            non_init_paths = sorted(
                [p for p in paths if not any(x.match(init_subdir) for x in PurePosixPath(p).parents)]
            )
            if non_init_paths:
                prefix = os.path.commonprefix(non_init_paths)
            else:
                prefix = os.path.commonprefix(paths)

            # TODO: this only works for software tarballs, how to handle compat layer tarballs?
            swdirs = [  # all directory names with the pattern: <prefix>/software/<name>/<version>
                m.path
                for m in members
                if m.isdir() and PurePosixPath(m.path).match(os.path.join(prefix, 'software', '*', '*'))
            ]
            modfiles = [  # all filenames with the pattern: <prefix>/modules/<category>/<name>/*.lua
                m.path
                for m in members
                if m.isfile() and PurePosixPath(m.path).match(os.path.join(prefix, 'modules', '*', '*', '*.lua'))
            ]
            other = [  # anything that is not in <prefix>/software nor <prefix>/modules
                m.path
                for m in members
                if (not PurePosixPath(prefix).joinpath('software') in PurePosixPath(m.path).parents
                    and not PurePosixPath(prefix).joinpath('modules') in PurePosixPath(m.path).parents)
                # if not fnmatch.fnmatch(m.path, os.path.join(prefix, 'software', '*'))
                # and not fnmatch.fnmatch(m.path, os.path.join(prefix, 'modules', '*'))
            ]
            members_list = sorted(swdirs + modfiles + other)

        # Construct the overview.
        tar_members = '\n'.join(members_list)
        overview = f'Total number of items in the tarball: {tar_num_members}'
        overview += f'\nURL to the tarball: {self.url}'
        overview += f'\n{tar_members_desc}\n'
        overview += f'```\n{tar_members}\n```'

        # Make sure that the overview does not exceed Github's maximum length (65536 characters).
        if len(overview) > 60000:
            overview = overview[:60000] + '\n\nWARNING: output exceeded the maximum length and was truncated!\n```'
        return overview

    def next_state(self, state):
        """Find the next state for this tarball."""
        if state in self.states and 'next_state' in self.states[state]:
            return self.states[state]['next_state']
        else:
            return None

    def run_handler(self):
        """Process this tarball by running the process function that corresponds to the current state."""
        if not self.state:
            self.state = self.find_state()
        handler = self.states[self.state]['handler']
        handler()

    def to_string(self):
        """Serialize tarball info so it can be printed."""
        str = f"tarball: {self.object}"
        str += f"\n   metadt: {self.metadata_file}"
        str += f"\n   config: {self.config}"
        str += f"\n   s3....: {self.s3}"
        str += f"\n   bucket: {self.bucket}"
        str += f"\n   cvmfs.: {self.cvmfs_repo}"
        str += f"\n   GHrepo: {self.git_repo}"
        return str

    def verify_signatures(self):
        """Verify the signatures of the downloaded tarball and metadata file using the corresponding signature files."""

        sig_missing_msg = 'Signature file %s is missing.'
        sig_missing = False
        for sig_file in [self.local_sig_path, self.local_metadata_sig_path]:
            if not os.path.exists(sig_file):
                logging.warning(sig_missing_msg % sig_file)
                sig_missing = True

        if sig_missing:
            # If signature files are missing, we return a failure,
            # unless the configuration specifies that signatures are not required.
            if self.config['signatures'].getboolean('signatures_required', True):
                return False
            else:
                return True

        # If signatures are provided, we should always verify them, regardless of the signatures_required.
        # In order to do so, we need the verification script and an allowed signers file.
        verify_script = self.config['signatures']['signature_verification_script']
        allowed_signers_file = self.config['signatures']['allowed_signers_file']
        if not os.path.exists(verify_script):
            logging.error('Unable to verify signatures, the specified signature verification script does not exist!')
            return False

        if not os.path.exists(allowed_signers_file):
            logging.error('Unable to verify signatures, the specified allowed signers file does not exist!')
            return False

        for (file, sig_file) in [
            (self.local_path, self.local_sig_path),
            (self.local_metadata_path, self.local_metadata_sig_path)
        ]:
            verify_cmd = subprocess.run(
                [verify_script, '--verify', '--allowed-signers-file', allowed_signers_file,
                 '--file', file, '--signature-file', sig_file],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE)
            if verify_cmd.returncode == 0:
                logging.debug(f'Signature for {file} successfully verified.')
            else:
                logging.error(f'Failed to verify signature for {file}.')
                return False

        self.sig_verified = True
        return True

    def verify_checksum(self):
        """Verify the checksum of the downloaded tarball with the one in its metadata file."""
        local_sha256 = sha256sum(self.local_path)
        meta_sha256 = None
        with open(self.local_metadata_path, 'r') as meta:
            meta_sha256 = json.load(meta)['payload']['sha256sum']
        logging.debug(f'Checksum of downloaded tarball: {local_sha256}')
        logging.debug(f'Checksum stored in metadata file: {meta_sha256}')
        return local_sha256 == meta_sha256

    def ingest(self):
        """Process a tarball that is ready to be ingested by running the ingestion script."""
        # TODO: check if there is an open issue for this tarball, and if there is, skip it.
        logging.info(f'Tarball {self.object} is ready to be ingested.')
        self.download()
        logging.info('Verifying its signature...')
        if not self.verify_signatures():
            issue_msg = f'Failed to verify signatures for `{self.object}`'
            logging.error(issue_msg)
            if not self.issue_exists(issue_msg, state='open'):
                self.git_repo.create_issue(title=issue_msg, body=issue_msg)
            return
        else:
            logging.debug(f'Signatures of {self.object} and its metadata file successfully verified.')

        logging.info('Verifying its checksum...')
        if not self.verify_checksum():
            issue_msg = f'Failed to verify checksum for `{self.object}`'
            logging.error(issue_msg)
            if not self.issue_exists(issue_msg, state='open'):
                self.git_repo.create_issue(title=issue_msg, body=issue_msg)
            return
        else:
            logging.debug(f'Checksum of {self.object} matches the one in its metadata file.')

        script = self.config['paths']['ingestion_script']
        sudo = ['sudo'] if self.config['cvmfs'].getboolean('ingest_as_root', True) else []
        logging.info(f'Running the ingestion script for {self.object}...')
        ingest_cmd = subprocess.run(
            sudo + [script, self.cvmfs_repo, self.local_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE)
        if ingest_cmd.returncode == 0:
            next_state = self.next_state(self.state)
            self.move_metadata_file(self.state, next_state)
            if self.config.has_section('slack') and self.config['slack'].getboolean('ingestion_notification', False):
                send_slack_message(
                    self.config['secrets']['slack_webhook'],
                    self.config['slack']['ingestion_message'].format(
                        tarball=os.path.basename(self.object),
                        cvmfs_repo=self.cvmfs_repo)
                )
        else:
            issue_title = f'Failed to ingest {self.object}'
            issue_body = self.config['github']['failed_ingestion_issue_body'].format(
                command=' '.join(ingest_cmd.args),
                tarball=self.object,
                return_code=ingest_cmd.returncode,
                stdout=ingest_cmd.stdout.decode('UTF-8'),
                stderr=ingest_cmd.stderr.decode('UTF-8'),
            )
            if self.issue_exists(issue_title, state='open'):
                logging.info(f'Failed to ingest {self.object}, but an open issue already exists, skipping...')
            else:
                self.git_repo.create_issue(title=issue_title, body=issue_body)

    def print_ingested(self):
        """Process a tarball that has already been ingested."""
        logging.info(f'{self.object} has already been ingested, skipping...')

    def mark_new_tarball_as_staged(self, branch=None):
        """Process a new tarball that was added to the staging bucket."""
        next_state = self.next_state(self.state)
        logging.info(f'Found new tarball {self.object}, downloading it...')
        # Download the tarball and its metadata file.
        # Use force as it may be a new attempt for an existing tarball that failed before.
        self.download(force=True)
        if not self.local_path or not self.local_metadata_path:
            logging.warning(f"Skipping tarball {self.object} - download failed")
            return

        # Verify the signatures of the tarball and metadata file.
        if not self.verify_signatures():
            logging.warning(f"Skipping tarball {self.object} - signature verification failed")
            return

        # If no branch is provided, use the main branch
        target_branch = branch if branch else 'main'
        logging.info(f"Adding metadata to '{next_state}' folder in {target_branch} branch")

        file_path_staged = next_state + '/' + self.metadata_file
        contents = ''
        with open(self.local_metadata_path, 'r') as meta:
            contents = meta.read()
        self.git_repo.create_file(file_path_staged, 'new tarball', contents, branch=target_branch)

        self.state = next_state
        if not branch:  # Only run handler if we're not part of a group
            self.run_handler()

    def print_rejected(self):
        """Process a (rejected) tarball for which the corresponding PR has been closed witout merging."""
        logging.info("This tarball was rejected, so we're skipping it.")
        # Do we want to delete rejected tarballs at some point?

    def print_unknown(self):
        """Process a tarball which has an unknown state."""
        logging.info("The state of this tarball could not be determined, so we're skipping it.")

    def find_next_sequence_number(self, repo, pr_id):
        """Find the next available sequence number for staging PRs of a source PR."""
        # Search for existing branches for this source PR
        base_branch = f'staging-{repo.replace("/", "-")}-{pr_id}'
        existing_branches = [
            ref.ref for ref in self.git_repo.get_git_refs()
            if ref.ref.startswith(f'refs/heads/{base_branch}')
        ]

        if not existing_branches:
            return 1

        # Extract sequence numbers from existing branches
        sequence_numbers = []
        for branch in existing_branches:
            try:
                # Extract the sequence number from branch name
                # Format: staging-repo-pr_id-sequence
                sequence = int(branch.split('-')[-1])
                sequence_numbers.append(sequence)
            except (ValueError, IndexError):
                continue

        if not sequence_numbers:
            return 1

        # Return next available sequence number
        return max(sequence_numbers) + 1

    def make_approval_request(self, tarballs_in_group=None):
        """Process a staged tarball by opening a pull request for ingestion approval."""
        next_state = self.next_state(self.state)

        # obtain link2pr information (repo and pr_id) from metadata file
        with open(self.local_metadata_path, 'r') as meta:
            metadata = meta.read()
        meta_dict = json.loads(metadata)
        repo, pr_id = meta_dict['link2pr']['repo'], meta_dict['link2pr']['pr']

        # find next sequence number for staging PRs of this source PR
        sequence = self.find_next_sequence_number(repo, pr_id)
        git_branch = f'staging-{repo.replace("/", "-")}-{pr_id}-{sequence}'

        # Check if git_branch exists and what the status of the corressponding PR is
        main_branch = self.git_repo.get_branch('main')
        if git_branch in [branch.name for branch in self.git_repo.get_branches()]:
            logging.info(f"Branch {git_branch} already exists, checking the status of the corresponding PR...")
            find_pr = [pr for pr in self.git_repo.get_pulls(head=git_branch, state='all')
                       if pr.head.ref == git_branch]
            if find_pr:
                pr = find_pr.pop(0)
                if pr.state == 'open':
                    logging.info('PR is still open, skipping this tarball...')
                    return
                elif pr.state == 'closed' and not pr.merged:
                    logging.info('PR was rejected')
                    self.reject()
                    return
                else:
                    logging.warn(f'Warning, tarball {self.object} is in a weird state:')
                    logging.warn(f'Branch: {git_branch}\nPR: {pr}\nPR state: {pr.state}\nPR merged: {pr.merged}')
                    # TODO:  should we delete the branch or open an issue? 
                    return
            else:
                logging.info(f'Tarball {self.object} has a branch, but no PR.')
                logging.info('Removing existing branch...')
                ref = self.git_repo.get_git_ref(f'heads/{git_branch}')
                ref.delete()

        # Create new branch
        self.git_repo.create_git_ref(ref='refs/heads/' + git_branch, sha=main_branch.commit.sha)

        # Move metadata file(s) to staged directory
        if tarballs_in_group is None:
            logging.info(f"Moving metadata for individual tarball to staged")
            self.move_metadata_file(self.state, next_state, branch=git_branch)
        else:
            logging.info(f"Moving metadata for {len(tarballs_in_group)} tarballs to staged")
            for tarball in tarballs_in_group:
                temp_tar = EessiTarball(tarball, self.config, self.git_repo, self.s3, self.bucket, self.cvmfs_repo)
                temp_tar.move_metadata_file('new', 'staged', branch=git_branch)

        # Create PR with appropriate template
        try:
            pr_url=f"https://github.com/{repo}/pull/{pr_id}",
            if tarballs_in_group is None:
                logging.info(f"Creating PR for individual tarball: {self.object}")
                tarball_contents = self.get_contents_overview()
                pr_body = self.config['github']['individual_pr_body'].format(
                    cvmfs_repo=self.cvmfs_repo,
                    pr_url=pr_url,
                    tar_overview=tarball_contents,
                    metadata=metadata,
                )
                pr_title = f'[{self.cvmfs_repo}] Ingest {os.path.basename(self.object)}'
            else:
                # Group of tarballs
                tar_overviews = []
                for tarball in tarballs_in_group:
                    try:
                        temp_tar = EessiTarball(
                            tarball, self.config, self.git_repo, self.s3, self.bucket, self.cvmfs_repo)
                        temp_tar.download()
                        overview = temp_tar.get_contents_overview()
                        tar_details_tpl = "<details>\n<summary>Contents of %s</summary>\n\n%s\n</details>\n"
                        tar_overviews.append(tar_details_tpl % (tarball, overview))
                    except Exception as err:
                        logging.error(f"Failed to get contents overview for {tarball}: {err}")
                        tar_details_tpl = "<details>\n<summary>Contents of %s</summary>\n\n"
                        tar_details_tpl += "Failed to get contents overview: %s\n</details>\n"
                        tar_overviews.append(tar_details_tpl % (tarball, err))

                pr_body = self.config['github']['grouped_pr_body'].format(
                    cvmfs_repo=self.cvmfs_repo,
                    pr_url=pr_url,
                    tarballs=self.format_tarball_list(tarballs_in_group),
                    metadata=self.format_metadata_list(tarballs_in_group),
                    tar_overview="\n".join(tar_overviews)
                )
                pr_title = f'[{self.cvmfs_repo}] Staging PR #{sequence} for {repo}#{pr_id}'

            # Add signature verification status if applicable
            if self.sig_verified:
                pr_body += "\n\n:heavy_check_mark: :closed_lock_with_key: "
                pr_body += "The signature of this tarball has been successfully verified."
                pr_title += ' :closed_lock_with_key:'

            self.git_repo.create_pull(title=pr_title, body=pr_body, head=git_branch, base='main')
            logging.info(f"Created PR: {pr_title}")

        except Exception as err:
            logging.error(f"Failed to create PR: {err}")
            if not self.issue_exists(f'Failed to get contents of {self.object}', state='open'):
                self.git_repo.create_issue(
                    title=f'Failed to get contents of {self.object}',
                    body=self.config['github']['failed_tarball_overview_issue_body'].format(
                        tarball=self.object,
                        error=err
                    )
                )

    def format_tarball_list(self, tarballs):
        """Format a list of tarballs with checkboxes for approval."""
        formatted = "### Tarballs to be ingested\n\n"
        for tarball in tarballs:
            formatted += f"- [ ] {tarball}\n"
        return formatted

    def format_metadata_list(self, tarballs):
        """Format metadata for all tarballs in collapsible sections."""
        formatted = "### Metadata\n\n"
        for tarball in tarballs:
            with open(self.get_metadata_path(tarball), 'r') as meta:
                metadata = meta.read()
                formatted += f"<details>\n<summary>Metadata for {tarball}</summary>\n\n```\n{metadata}\n```\n</details>\n\n"
        return formatted

    def move_metadata_file(self, old_state, new_state, branch='main'):
        """Move the metadata file of a tarball from an old state's directory to a new state's directory."""
        file_path_old = old_state + '/' + self.metadata_file
        file_path_new = new_state + '/' + self.metadata_file
        logging.debug(f'Moving metadata file {self.metadata_file} from {file_path_old} to {file_path_new}.')
        tarball_metadata = self.git_repo.get_contents(file_path_old)
        # Remove the metadata file from the old state's directory...
        self.git_repo.delete_file(file_path_old, 'remove from ' + old_state, sha=tarball_metadata.sha, branch=branch)
        # and move it to the new state's directory
        self.git_repo.create_file(file_path_new, 'move to ' + new_state, tarball_metadata.decoded_content,
                                  branch=branch)

    def process_pr_merge(self, pr_number):
        """Process a merged PR by handling the checkboxes and moving tarballs to appropriate states."""
        pr = self.git_repo.get_pull(pr_number)

        # Get the branch name
        branch_name = pr.head.ref

        # Get the list of tarballs from the PR body
        tarballs = self.extract_tarballs_from_pr_body(pr.body)

        # Get the checked status for each tarball
        checked_tarballs = self.extract_checked_tarballs(pr.body)

        # Process each tarball
        for tarball in tarballs:
            if tarball in checked_tarballs:
                # Move to approved state
                self.move_metadata_file('staged', 'approved', branch=branch_name)
            else:
                # Move to rejected state
                self.move_metadata_file('staged', 'rejected', branch=branch_name)

        # Delete the branch after processing
        ref = self.git_repo.get_git_ref(f'heads/{branch_name}')
        ref.delete()

    def extract_checked_tarballs(self, pr_body):
        """Extract list of checked tarballs from PR body."""
        checked_tarballs = []
        for line in pr_body.split('\n'):
            if line.strip().startswith('- [x] '):
                tarball = line.strip()[6:] # Remove '- [x] ' prefix
                checked_tarballs.append(tarball)
        return checked_tarballs

    def extract_tarballs_from_pr_body(self, pr_body):
        """Extract list of all tarballs from PR body."""
        tarballs = []
        for line in pr_body.split('\n'):
            if line.strip().startswith('- ['):
                tarball = line.strip()[6:] # Remove '- [ ] ' or '- [x] ' prefix
                tarballs.append(tarball)
        return tarballs

    def reject(self):
        """Reject a tarball for ingestion."""
        # Let's move the the tarball to the directory for rejected tarballs.
        logging.info(f'Marking tarball {self.object} as rejected...')
        next_state = 'rejected'
        self.move_metadata_file(self.state, next_state)

    def issue_exists(self, title, state='open'):
        """Check if an issue with the given title and state already exists."""
        issues = self.git_repo.get_issues(state=state)
        for issue in issues:
            if issue.title == title and issue.state == state:
                return True
        else:
            return False

    def get_link2pr_info(self):
        """Get the link2pr information from the metadata file."""
        with open(self.local_metadata_path, 'r') as meta:
            metadata = json.load(meta)
        return metadata['link2pr']['repo'], metadata['link2pr']['pr']


class EessiTarballGroup:
    """Class to handle a group of tarballs that share the same link2pr information."""

    def __init__(self, first_tarball, config, git_staging_repo, s3, bucket, cvmfs_repo):
        """Initialize with the first tarball in the group."""
        self.first_tar = EessiTarball(first_tarball, config, git_staging_repo, s3, bucket, cvmfs_repo)
        self.config = config
        self.git_repo = git_staging_repo
        self.s3 = s3
        self.bucket = bucket
        self.cvmfs_repo = cvmfs_repo

    def download_tarballs_and_more(self, tarballs):
        """Download all files associated with this group of tarballs."""
        for tarball in tarballs:
            temp_tar = EessiTarball(tarball, self.config, self.git_repo, self.s3, self.bucket, self.cvmfs_repo)
            print(f"downloading files for '{temp_tar.object}'")
            temp_tar.download(force=True)
            if not temp_tar.local_path or not temp_tar.local_metadata_path:
                logging.warn(f"Skipping this tarball: {temp_tar.object}")
                return False
        return True

    def process_group(self, tarballs):
        """Process a group of tarballs together."""
        logging.info(f"Processing group of {len(tarballs)} tarballs")

        if not self.download_tarballs_and_more(tarballs):
            logging.error("Downloading tarballs, metadata files and/or their signatures failed")
            return

        # Verify all tarballs have the same link2pr info
        if not self.verify_group_consistency(tarballs):
            logging.error("Tarballs have inconsistent link2pr information")
            return

        # Get branch name from first tarball
        with open(self.first_tar.local_metadata_path, 'r') as meta:
            metadata = json.load(meta)
        repo, pr_id = metadata['link2pr']['repo'], metadata['link2pr']['pr']
        sequence = self.first_tar.find_next_sequence_number(repo, pr_id)
        git_branch = f'staging-{repo.replace("/", "-")}-{pr_id}-{sequence}'

        logging.info(f"Creating group branch: {git_branch}")

        # Mark all tarballs as staged in the group branch
        for tarball in tarballs:
            logging.info(f"Processing tarball in group: {tarball}")
            temp_tar = EessiTarball(tarball, self.config, self.git_repo, self.s3, self.bucket, self.cvmfs_repo)
            temp_tar.mark_new_tarball_as_staged(branch=git_branch)

        # Process the group for approval
        self.first_tar.make_approval_request(tarballs)

    def to_string(self):
        """Serialize tarball group info so it can be printed."""
        str = f"first tarball: {self.first_tar.to_string()}"
        str += f"\n   config: {self.config}"
        str += f"\n   GHrepo: {self.git_repo}"
        str += f"\n   s3....: {self.s3}"
        str += f"\n   bucket: {self.bucket}"
        str += f"\n   cvmfs.: {self.cvmfs_repo}"
        return str

    def verify_group_consistency(self, tarballs):
        """Verify all tarballs in the group have the same link2pr information."""
        first_repo, first_pr = self.first_tar.get_link2pr_info()

        for tarball in tarballs[1:]:  # Skip first tarball as we already have its info
            temp_tar = EessiTarball(tarball, self.config, self.git_repo, self.s3, self.bucket, self.cvmfs_repo)
            print(f"temp tar: {temp_tar.to_string()}")
            repo, pr = temp_tar.get_link2pr_info()
            if repo != first_repo or pr != first_pr:
                return False
        return True
