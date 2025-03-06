from utils import send_slack_message, sha256sum

from pathlib import PurePosixPath

import boto3
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
        for (object, local_file, sig_object, local_sig_file) in files:
            if force or not os.path.exists(local_file):
                try:
                    self.s3.download_file(self.bucket, object, local_file)
                    # Also try to download the corresponding signature file; they may be optional.
                    try:
                        self.s3.download_file(self.bucket, sig_object, local_sig_file)
                    except:
                        if config['signatures'].getboolean('signatures_required', True):
                            logging.error(
                                f'Failed to download signature file {sig_object} for {object} from {self.bucket} to {local_sig_file}.'
                            )
                        else:
                            logging.warning(
                                f'Failed to download signature file {sig_object} for {object} from {self.bucket} to {local_sig_file}.' +
                                 'Ignoring this, because signatures are not required with the current configuration.'
                            )
                except:
                    logging.error(
                        f'Failed to download {object} from {self.bucket} to {local_file}.'
                    )
                    # If either the tarball itself or its metadata cannot be downloaded, set both to None
                    # to make sure that this tarball is completely ignored/skipped.
                    self.local_path = None
                    self.local_metadata_path = None

    def find_state(self):
        """Find the state of this tarball by searching through the state directories in the git repository."""
        for state in list(self.states.keys()):
            # iterate through the state dirs and try to find the tarball's metadata file
            try:
                self.git_repo.get_contents(state + '/' + self.metadata_file)
                return state
            except github.UnknownObjectException:
                # no metadata file found in this state's directory, so keep searching...
                continue
            except github.GithubException as e:
                if e.status == 404:
                    # no metadata file found in this state's directory, so keep searching...
                    continue
                else:
                    # if there was some other (e.g. connection) issue, abort the search for this tarball
                    logging.warning(f'Unable to determine the state of {self.object}, the GitHub API returned status {e.status}!')
                    return "unknown"
        else:
            # if no state was found, we assume this is a new tarball that was ingested to the bucket
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
            non_init_paths = sorted([p for p in paths if not any(x.match(init_subdir) for x in PurePosixPath(p).parents)])
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
                if not PurePosixPath(prefix).joinpath('software') in PurePosixPath(m.path).parents
                   and not PurePosixPath(prefix).joinpath('modules') in PurePosixPath(m.path).parents
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

        verify_script = self.config['signatures']['signature_verification_script']
        allowed_signers_file = self.config['signatures']['allowed_signers_file']
        if not os.path.exists(verify_script):
            logging.error(f'Unable to verify signatures, the specified signature verification script does not exist!')
            return False

        if not os.path.exists(allowed_signers_file):
            logging.error(f'Unable to verify signatures, the specified allowed signers file does not exist!')
            return False

        for (file, sig_file) in [(self.local_path, self.local_sig_path), (self.local_metadata_path, self.local_metadata_sig_path)]:
            verify_cmd = subprocess.run(
                [verify_script, 'verify', file, allowed_signers_file, sig_file],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE)
            if verify_cmd.returncode == 0:
                logging.debug(f'Signature for {file} successfully verified.')
            else:
                logging.error(f'Failed to verify signature for {file}.')
                return False

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
        #TODO: check if there is an open issue for this tarball, and if there is, skip it.
        logging.info(f'Tarball {self.object} is ready to be ingested.')
        self.download()
        logging.info('Verifying its signature...')
        if not self.verify_signatures():
            logging.error('Signature of tarball (or its metadata file) could not be verified!')
            # Open issue?
            return
        else:
            logging.debug(f'Signatures of {self.object} and its metadata file successfully verified.')
        logging.info('Verifying its checksum...')
        if not self.verify_checksum():
            logging.error('Checksum of downloaded tarball does not match the one in its metadata file!')
            # Open issue?
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
                    self.config['slack']['ingestion_message'].format(tarball=os.path.basename(self.object), cvmfs_repo=self.cvmfs_repo)
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

    def mark_new_tarball_as_staged(self):
        """Process a new tarball that was added to the staging bucket."""
        next_state = self.next_state(self.state)
        logging.info(f'Found new tarball {self.object}, downloading it...')
        # Download the tarball and its metadata file.
        # Use force as it may be a new attempt for an existing tarball that failed before.
        self.download(force=True)
        if not self.local_path or not self.local_metadata_path:
            logging.warn('Skipping this tarball...')
            return

        # Verify the signatures of the tarball and metadata file.
        if not self.verify_signatures():
            logging.warn('Signature verification of the tarball or its metadata failed, skipping this tarball...')

        contents = ''
        with open(self.local_metadata_path, 'r') as meta:
            contents = meta.read()

        logging.info(f'Adding tarball\'s metadata to the "{next_state}" folder of the git repository.')
        file_path_staged = next_state + '/' + self.metadata_file
        new_file = self.git_repo.create_file(file_path_staged, 'new tarball', contents, branch='main')

        self.state = next_state
        self.run_handler()

    def print_rejected(self):
        """Process a (rejected) tarball for which the corresponding PR has been closed witout merging."""
        logging.info("This tarball was rejected, so we're skipping it.")
        # Do we want to delete rejected tarballs at some point?

    def print_unknown(self):
        """Process a tarball which has an unknown state."""
        logging.info("The state of this tarball could not be determined, so we're skipping it.")

    def make_approval_request(self):
        """Process a staged tarball by opening a pull request for ingestion approval."""
        next_state = self.next_state(self.state)
        file_path_staged = self.state + '/' + self.metadata_file
        file_path_to_ingest = next_state + '/' + self.metadata_file

        filename = os.path.basename(self.object)
        tarball_metadata = self.git_repo.get_contents(file_path_staged)
        git_branch = filename + '_' + next_state
        self.download()

        main_branch = self.git_repo.get_branch('main')
        if git_branch in [branch.name for branch in self.git_repo.get_branches()]:
            # Existing branch found for this tarball, so we've run this step before.
            # Try to find out if there's already a PR as well...
            logging.info("Branch already exists for " + self.object)
            # Filtering with only head=<branch name> returns all prs if there's no match, so double-check
            find_pr = [pr for pr in self.git_repo.get_pulls(head=git_branch, state='all') if pr.head.ref == git_branch]
            logging.debug('Found PRs: ' + str(find_pr))
            if find_pr:
                # So, we have a branch and a PR for this tarball (if there are more, pick the first one)...
                pr = find_pr.pop(0)
                logging.info(f'PR {pr.number} found for {self.object}')
                if pr.state == 'open':
                    # The PR is still open, so it hasn't been reviewed yet: ignore this tarball.
                    logging.info('PR is still open, skipping this tarball...')
                    return
                elif pr.state == 'closed' and not pr.merged:
                    # The PR was closed but not merged, i.e. it was rejected for ingestion.
                    logging.info('PR was rejected')
                    self.reject()
                    return
                else:
                    logging.warn(f'Warning, tarball {self.object} is in a weird state:')
                    logging.warn(f'Branch: {git_branch}\nPR: {pr}\nPR state: {pr.state}\nPR merged: {pr.merged}')
            else:
                # There is a branch, but no PR for this tarball.
                # This is weird, so let's remove the branch and reprocess the tarball.
                logging.info(f'Tarball {self.object} has a branch, but no PR.')
                logging.info(f'Removing existing branch...')
                ref = self.git_repo.get_git_ref(f'heads/{git_branch}')
                ref.delete()
        logging.info(f'Making pull request to get ingestion approval for {self.object}.')
        # Create a new branch
        self.git_repo.create_git_ref(ref='refs/heads/' + git_branch, sha=main_branch.commit.sha)
        # Move the file to the directory of the next stage in this branch
        self.move_metadata_file(self.state, next_state, branch=git_branch)
        # Get metadata file contents
        metadata = ''
        with open(self.local_metadata_path, 'r') as meta:
            metadata = meta.read()
        meta_dict = json.loads(metadata)
        repo, pr_id = meta_dict['link2pr']['repo'], meta_dict['link2pr']['pr']
        pr_url = f"https://github.com/{repo}/pull/{pr_id}"
        # Try to get the tarball contents and open a PR to get approval for the ingestion
        try:
            tarball_contents = self.get_contents_overview()
            pr_body = self.config['github']['pr_body'].format(
                cvmfs_repo=self.cvmfs_repo,
                pr_url=pr_url,
                tar_overview=self.get_contents_overview(),
                metadata=metadata,
            )
            pr_title = '[%s] Ingest %s' % (self.cvmfs_repo, filename)
            self.git_repo.create_pull(title=pr_title, body=pr_body, head=git_branch, base='main')
        except Exception as err:
            issue_title = f'Failed to get contents of {self.object}'
            issue_body = self.config['github']['failed_tarball_overview_issue_body'].format(
                tarball=self.object,
                error=err
            )
            if len([i for i in self.git_repo.get_issues(state='open') if i.title == issue_title]) == 0:
                self.git_repo.create_issue(title=issue_title, body=issue_body)
            else:
                logging.info(f'Failed to create tarball overview, but an issue already exists.')

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
