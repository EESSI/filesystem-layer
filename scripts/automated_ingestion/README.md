# Automated ingestion

The automated ingestion script can be used to automatically ingest tarballs into the CVMFS repository.
It uses the following workflow:
- recursively scan the given AWS S3 bucket for tarballs;
- download the tarball and its accompanying metadata file to a local directory;
- insert the metadata file into a `staged` directory in the git repository that is used for bookkeeping;
- open a pull request to get approval for moving the metadata file from `staged` to `approved`, i.e. to get permission for ingesting the tarball into the CVMFS repository;
- for every tarball that has a metadata file in the `approved` directory, the CVMFS ingestion script is run;
- when the ingestion was successful, the metadata file is moved to `ingested` in the git repository;
- in case the pull request was rejected, the metadata file gets moved to `rejected`;
- when something goes wrong during the ingestion process, a GitHub issue is opened.

## Setup

- Make a new Python virtual environment, e.g. `python3 -m venv auto_ingest`.
- Activate the virtual environment: `source auto_ingest/bin/activate`.
- Install the requirements: `pip3 install -r requirements.txt`.

## Configuration
- Create a GitHub token at https://github.com/settings/tokens/new. It needs to have the `repo` scope.
- Create access keys (`AWS_SECRET_ACCESS_KEY` and `AWS_ACCESS_KEY_ID`) for the AWS account that you want to use for access to the S3 bucket.
- If you want to receive Slack notifications, set up a Slack App and create a Webhook URL for an Incoming Webhook.
- Make a configuration file based on `automated_ingestion.cfg.example`, and adjust it to your needs.

## Run
Make sure that your virtual environment is activated, and run the script manually using `python3 automated_ingestion.py`, or set up a cronjob to run it regularly.
