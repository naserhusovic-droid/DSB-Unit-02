# Repair this repo's Git and SSH setup

From a terminal opened in the repository, run:

```sh
python3 scripts/setup_git_ssh.py
```

The script asks for the student's commit name and email, then lets them choose
the SSH private key already added to their GitHub account. It points `origin`
to the GitHub SSH URL and sets the commit identity and selected key for this
repository only. It does not delete or replace keys or change global Git/SSH
settings. Before changing anything, it makes a timestamped backup of `.git/config`.

At the end it checks repository read access and runs `git push --dry-run` to
check push access without changing the remote. A push dry run needs at least
one commit and a named branch. It cannot guarantee that a later push will
succeed if branch protection or repository permissions change.

The selected private key must already be registered with GitHub and have access
to this repository. If SSH reports that the GitHub host is unknown, verify the
host prompt before accepting it. The script uses the normal SSH known-hosts
file, while bypassing old per-user SSH host rules for this repository.
