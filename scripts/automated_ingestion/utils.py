import hashlib
import json
import requests

def send_slack_message(webhook, msg):
    """Send a Slack message."""
    slack_data = {'text': msg}
    response = requests.post(
        webhook, data=json.dumps(slack_data),
        headers={'Content-Type': 'application/json'}
    )
    if response.status_code != 200:
        raise ValueError(
            'Request to slack returned an error %s, the response is:\n%s'
            % (response.status_code, response.text)
        )

def sha256sum(path):
    """Calculate the sha256 checksum of a given file."""
    sha256_hash = hashlib.sha256()
    with open(path, 'rb') as f:
        # Read and update hash string value in blocks of 4K
        for byte_block in iter(lambda: f.read(8192), b''):
            sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()

