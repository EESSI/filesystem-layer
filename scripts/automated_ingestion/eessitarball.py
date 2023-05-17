from utils import send_slack_message, sha256sum

from pathlib import PurePosixPath

import boto3
import github
import json
import logging
import os
import re
import subprocess
import tarfile

from datetime import datetime, timezone

class EessiTarball:
    """
    Class that represents an EESSI tarball containing software installations
    or a compatibility layer, and which is stored in an S3 bucket. It has
    several functions to handle the different states of such a tarball in the
    actual ingestion process, for which it interfaces with the S3 bucket,
    GitHub, and CVMFS.
    """

    def __init__(self, object_name, config, github, s3):
        """Initialize the tarball object."""
        self.config = config
        self.github = github
        self.git_repo = github.get_repo(config['github']['staging_repo'])
        self.metadata_file = object_name + config['paths']['metadata_file_extension']
        self.object = object_name
        self.s3 = s3
        self.local_path = os.path.join(config['paths']['download_dir'], os.path.basename(object_name))
        self.local_metadata_path = self.local_path + config['paths']['metadata_file_extension']

        self.contents = ''
        self.metadata = {}

        self.sw_repo_name = ''
        self.sw_repo = None

        self.sw_pr_number = -1
        self.sw_pr = None

        self.sw_pr_comment_id = -1
        self.sw_pr_comment = None

        self.tarball_name = ''

#        self.url = f'https://{config["aws"]["staging_bucket"]}.s3.amazonaws.com/{object_name}'
        # TODO verify if staging bucket and object_name are added correctly
        self.url = f'{config["aws"]["endpoint_url"]}/{config["aws"]["staging_bucket"]}/{object_name}'

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
        bucket = self.config['aws']['staging_bucket']
        if force or not os.path.exists(self.local_path):
            try:
                self.s3.download_file(bucket, self.object, self.local_path)
            except:
                logging.error(
                    f'Failed to download tarball {self.object} from {bucket} to {self.local_path}.'
                )
                self.local_path = None
        if force or not os.path.exists(self.local_metadata_path):
            try:
                self.s3.download_file(bucket, self.metadata_file, self.local_metadata_path)
            except:
                logging.error(
                    f'Failed to download metadata file {self.metadata_file} from {bucket} to {self.local_metadata_path}.'
                )
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
            except github.GithubException:
                # if there was some other (e.g. connection) issue, abort the search for this tarball
                logging.warning(f'Unable to determine the state of {self.object}!')
                return "unknown"
        else:
            # if no state was found, we assume this is a new tarball that was ingested to the bucket
            return "new"

    def get_contents_overview(self):
        """Return an overview of what is included in the tarball."""
        logging.debug(f'get contents overview for "{self.local_path}"')
        tar = tarfile.open(self.local_path, 'r')
        members = tar.getmembers()
        tar_num_members = len(members)
        paths = sorted([m.path for m in members])

        if tar_num_members < 100:
            tar_members_desc = 'Full listing of the contents of the tarball:'
            members_list = paths
        else:
            tar_members_desc = 'Summarized overview of the contents of the tarball:'
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

    def verify_checksum(self):
        """Verify the checksum of the downloaded tarball with the one in its metadata file."""
        local_sha256 = sha256sum(self.local_path)
        meta_sha256 = self.metadata['payload']['sha256sum']
        logging.debug(f'Checksum of downloaded tarball: {local_sha256}')
        logging.debug(f'Checksum stored in metadata file: {meta_sha256}')
        return local_sha256 == meta_sha256

    def ingest(self):
        """Process a tarball that is ready to be ingested by running the ingestion script."""
        # TODO: check if there is an open issue for this tarball, and if there is, skip it.
        logging.info(f'Tarball {self.object} is ready to be ingested.')
        # update comment in software-layer repo: approved
        self.update_sw_repo_comment('ingest_approved')
        self.download()
        logging.info('Verifying its checksum...')
        if not self.verify_checksum():
            logging.error('Checksum of downloaded tarball does not match the one in its metadata file!')
            # TODO Open issue?
            return
        else:
            logging.debug(f'Checksum of {self.object} matches the one in its metadata file.')
        script = self.config['paths']['ingestion_script']
        sudo = ['sudo'] if self.config['cvmfs'].getboolean('ingest_as_root', True) else []
        logging.info(f'Running the ingestion script for {self.object}...')

        # TODO add additional parameters for more info in cvmfs_server tag history
        sw_branch = self.sw_pr.base.ref
        uploader = self.metadata['uploader']['username']

        ingest_cmd = sudo + [script, self.local_path, self.sw_repo_name, sw_branch, self.sw_pr_number, uploader]
        logging.info(f'ingesting with /{" ".join(ingest_cmd)}/')
        ingest_run = subprocess.run(
            ingest_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE)
        if ingest_run.returncode == 0:
            next_state = self.next_state(self.state)
            self.move_metadata_file(self.state, next_state)
            if self.config.has_section('slack') and self.config['slack'].getboolean('ingestion_notification', False):
                send_slack_message(
                    self.config['secrets']['slack_webhook'],
                    self.config['slack']['ingestion_message'].format(tarball=os.path.basename(self.object))
                )
            logging.info(f'ingesting stdout: /{ingest_run.stdout.decode("UTF-8")}/')
            logging.info(f'ingesting stderr: /{ingest_run.stderr.decode("UTF-8")}/')
            # update comment in software-layer repo: ingested
            self.update_sw_repo_comment('ingest_done', prefix=self.determine_tarball_prefix())
        else:
            issue_title = f'Failed to ingest {self.object}'
            issue_body = self.config['github']['failed_ingestion_issue_body'].format(
                command=' '.join(ingest_run.args),
                tarball=self.object,
                return_code=ingest_run.returncode,
                stdout=ingest_run.stdout.decode('UTF-8'),
                stderr=ingest_run.stderr.decode('UTF-8'),
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

        # read metadata and init data structures
        contents = ''
        with open(self.local_metadata_path, 'r') as meta:
            self.contents = meta.read()
        self.metadata = json.loads(self.contents)

        self.sw_repo_name = self.metadata['link2pr']['repo']
        self.sw_repo = self.github.get_repo(self.sw_repo_name)

        self.sw_pr_number = self.metadata['link2pr']['pr']
        self.sw_pr = self.sw_repo.get_pull(int(self.sw_pr_number))

        if 'pr_comment_id' in self.metadata['link2pr']:
            self.sw_pr_comment_id = self.metadata['link2pr']['pr_comment_id']
            self.sw_pr_comment = self.sw_pr.get_issue_comment(int(self.sw_pr_comment_id))

        self.tarball_name = self.metadata['payload']['filename']

        logging.info(f'Adding tarball\'s metadata to the "{next_state}" folder of the git repository.')
        file_path_staged = next_state + '/' + self.metadata_file
        new_file = self.git_repo.create_file(file_path_staged, 'new tarball', self.contents, branch='main')

        self.state = next_state
        self.run_handler()

    def print_rejected(self):
        """Process a (rejected) tarball for which the corresponding PR has been closed witout merging."""
        logging.info("This tarball was rejected, so we're skipping it.")
        # Do we want to delete rejected tarballs at some point?

    def print_unknown(self):
        """Process a tarball which has an unknown state."""
        logging.info("The state of this tarball could not be determined, so we're skipping it.")

    def find_comment(self, pull_request, tarball_name):
        """Find comment in pull request that contains name of a tarball.
        Args:
            pull_request (object): PullRequest object (PyGithub) representing
                                   a pull request.
            tarball_name (string): Name of tarball used to identify a comment.
        Returns:
            issue_comment (object): IssueComment object (PyGithub) representing
                                    an issue comment.
        """
        comments = pull_request.get_issue_comments()
        for comment in comments:
            cms = f".*{tarball_name}.*"
            comment_match = re.search(cms, comment.body)
            if comment_match:
                return comment
        return None


    def find_approval_pr(self):
        """Find URL to approval PR if any exists."""
        filename = os.path.basename(self.object)
        git_branch = filename + '_approved'

        if git_branch in [branch.name for branch in self.git_repo.get_branches()]:
            find_pr = [pr for pr in self.git_repo.get_pulls(head=git_branch, state='all') if pr.head.ref == git_branch]
            if find_pr:
                return find_pr.pop(0).html_url
        else:
            return None


    def determine_sw_repo_pr_comment(self, tarball_name):
        """Determine PR comment."""
        if self.sw_pr_comment:
            return self.sw_pr_comment
        else:
            return self.find_comment(self.sw_pr, tarball_name)


    def determine_tarball_prefix(self):
        """Determine common prefix of tarball."""
        tar = tarfile.open(self.local_path, 'r')
        members = tar.getmembers()
        paths = sorted([m.path for m in members])

        return os.path.commonprefix(paths)


    def update_sw_repo_comment(self, comment_template, prefix=None):
        """Update comment in PR of software-layer repository.
        """
        # obtain issue_comment (use previously stored value in self or determine via tarball_name)
        issue_comment = self.determine_sw_repo_pr_comment(self.tarball_name)

        if issue_comment:
            comment_update = self.config['github'][comment_template].format(
                date=datetime.now(timezone.utc).strftime('%b %d %X %Z %Y'),
                tarball=self.tarball_name,
                approval_pr=self.find_approval_pr(),
                prefix=prefix,
                )
            logging.info(f'Comment found (id: {issue_comment.id}); '
                         f'adding row "{comment_update}"')
            # get current data/time
            issue_comment.edit(issue_comment.body + f"\n" + comment_update)
        else:
            logging.info(f'Failed to find a comment for tarball '
                         f'{tarball_name} in pull request '
                         f'#{sw_pr_number} in repo {sw_repo_name}.')


    def make_approval_request(self):
        """Process a staged tarball by opening a pull request for ingestion approval."""
        next_state = self.next_state(self.state)

        filename = os.path.basename(self.object)
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

        # Try to get the tarball contents and open a PR to get approval for the ingestion
        try:
            tarball_contents = self.get_contents_overview()
            pr_body = self.config['github']['pr_body'].format(
                tar_overview=tarball_contents,
                metadata=self.contents,
            )
            new_pr = self.git_repo.create_pull(title='Ingest ' + filename, body=pr_body, head=git_branch, base='main')

            # update comment in pull request of softwares-layer repo
            self.update_sw_repo_comment('ingest_staged')

        except Exception as err:
            print(f'caught an exception "{err}"')
            issue_title = f'Failed to get contents of {self.object}'
            issue_body = self.config['github']['failed_tarball_overview_issue_body'].format(
                tarball=self.object,
                error=err
            )
            if len([i for i in self.git_repo.get_issues(state='open') if i.title == issue_title]) == 0:
                self.git_repo.create_issue(title=issue_title, body=issue_body)
            else:
                logging.info(f'Failed to create tarball overview, but an issue already exists.')
                print(f'Failed to create tarball overview, but an issue already exists.')

    def move_metadata_file(self, old_state, new_state, branch='main'):
        """Move the metadata file of a tarball from an old state's directory to a new state's directory."""
        file_path_old = old_state + '/' + self.metadata_file
        file_path_new = new_state + '/' + self.metadata_file
        logging.debug(f'Moving metadata file {self.metadata_file} from {file_path_old} to {file_path_new}.')
        tarball_metadata = self.git_repo.get_contents(file_path_old)
        # TODO maybe first create file, then remove? if remove succeeds and create fails, it may be lost
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
        # update comment in software-layer repo: rejected
        self.update_sw_repo_comment('ingest_rejected')

    def issue_exists(self, title, state='open'):
        """Check if an issue with the given title and state already exists."""
        issues = self.git_repo.get_issues(state=state)
        for issue in issues:
            if issue.title == title and issue.state == state:
                return True
        else:
            return False
