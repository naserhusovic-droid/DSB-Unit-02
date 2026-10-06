#!/usr/bin/env python3
"""Set this repository to use one chosen SSH key and check GitHub access.

Run from inside the repository:
    python3 scripts/setup_git_ssh.py

Only this repository's .git/config is changed. Existing SSH keys and global
Git/SSH configuration are left alone. The script saves a config backup first.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path


def run_git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    # These environment variables override core.sshCommand, so clear stale
    # values inherited from a terminal or editor for this script's Git calls.
    env.pop("GIT_SSH_COMMAND", None)
    env.pop("GIT_SSH", None)
    return subprocess.run(
        ["git", *args], text=True, capture_output=True, check=check, env=env
    )


def ask_required(label: str) -> str:
    while True:
        value = input(f"{label}: ").strip()
        if value:
            return value
        print("Please enter a value.")


def github_path(remote: str) -> str | None:
    """Get owner/repo from common HTTPS and SSH GitHub remote formats."""
    value = remote.strip()
    match = re.match(r"^(?:https?://)?(?:www\.)?github\.com[:/](.+)$", value)
    if not match:
        match = re.match(r"^git@[^:]+:(.+)$", value)
    if not match:
        match = re.match(r"^ssh://git@[^/]+/(.+)$", value)
    if not match:
        return None

    path = match.group(1).strip("/")
    if path.endswith(".git"):
        path = path[:-4]
    parts = path.split("/")
    if len(parts) != 2 or not all(parts):
        return None
    return f"{parts[0]}/{parts[1]}"


def choose_key() -> Path:
    ssh_dir = Path.home() / ".ssh"
    paired_keys = sorted(
        public_key.with_suffix("")
        for public_key in ssh_dir.glob("*.pub")
        if public_key.with_suffix("").is_file()
    )

    print("\nAvailable private keys (matching .pub files):")
    if paired_keys:
        for number, key in enumerate(paired_keys, start=1):
            print(f"  {number}. {key}")
    else:
        print("  No matching key pairs found.")

    while True:
        answer = input("Choose a number, or enter a private key path: ").strip()
        if answer.isdigit() and 1 <= int(answer) <= len(paired_keys):
            key = paired_keys[int(answer) - 1]
        else:
            key = Path(answer).expanduser()
            if not key.is_absolute():
                key = Path.cwd() / key
        if key.is_file() and os.access(key, os.R_OK):
            return key.resolve()
        print("That file was not found or cannot be read. Try again.")


def main() -> int:
    try:
        root = Path(run_git("rev-parse", "--show-toplevel").stdout.strip())
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("Run this script from inside a Git repository.", file=sys.stderr)
        return 2

    try:
        current_remote = run_git("remote", "get-url", "origin").stdout.strip()
    except subprocess.CalledProcessError:
        current_remote = ""

    repo_path = github_path(current_remote) if current_remote else None
    if repo_path:
        print(f"Repository: {repo_path}")
    else:
        print("Enter this repository's GitHub HTTPS or SSH URL.")
        while True:
            entered_remote = ask_required("GitHub repository URL")
            repo_path = github_path(entered_remote)
            if repo_path:
                break
            print("Could not read an owner/repository path from that GitHub URL.")

    name = ask_required("Your name for Git commits")
    email = ask_required("Your email for Git commits")
    key = choose_key()

    branch = run_git("branch", "--show-current").stdout.strip()
    destination = f"git@github.com:{repo_path}.git"
    # Ignore prior per-user SSH host rules for this repo and offer exactly the
    # selected identity. GitHub's host key is still checked against known_hosts.
    ssh_command = (
        f"ssh -F {shlex.quote(os.devnull)} -i {shlex.quote(str(key))} "
        "-o IdentitiesOnly=yes"
    )

    print("\nThe script will set these values for this repository:")
    print(f"  origin:          {destination}")
    print(f"  commit name:     {name}")
    print(f"  commit email:    {email}")
    print(f"  SSH private key: {key}")
    if branch:
        print(f"  branch upstream: origin/{branch}")
    else:
        print("  branch upstream: unchanged (detached HEAD)")
    if input("Apply these settings? [y/N] ").strip().lower() not in {"y", "yes"}:
        print("No changes made.")
        return 0

    config_path = Path(run_git("rev-parse", "--git-path", "config").stdout.strip())
    if not config_path.is_absolute():
        config_path = root / config_path
    if not config_path.is_file():
        print(f"Cannot find this repository's Git config: {config_path}", file=sys.stderr)
        return 2

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = config_path.with_name(f"config.student-setup-{stamp}.bak")
    shutil.copy2(config_path, backup)

    def set_config(setting: str, value: str) -> None:
        run_git("config", "--local", setting, value)

    def unset_config(setting: str) -> None:
        run_git("config", "--local", "--unset-all", setting, check=False)

    try:
        set_config("user.name", name)
        set_config("user.email", email)
        set_config("core.sshCommand", ssh_command)
        set_config("remote.origin.url", destination)
        unset_config("remote.origin.pushurl")
        set_config("remote.pushDefault", "origin")
        if branch:
            set_config(f"branch.{branch}.remote", "origin")
            set_config(f"branch.{branch}.merge", f"refs/heads/{branch}")
            set_config(f"branch.{branch}.pushRemote", "origin")
    except (subprocess.CalledProcessError, OSError) as error:
        shutil.copy2(backup, config_path)
        print(f"Could not apply settings; restored the original config.\n{error}", file=sys.stderr)
        return 2

    print(f"\nSettings saved. Config backup: {backup}")
    effective_push_url = run_git("remote", "get-url", "--push", "origin").stdout.strip()
    if effective_push_url != destination:
        print("FAIL: Another Git URL rewrite changes the effective push destination.")
        print(f"  Expected: {destination}")
        print(f"  Actual:   {effective_push_url}")
        print("No network checks were run. Review URL rewrite rules in Git config.")
        return 1

    print("Checking read access with git ls-remote...")
    read_check = run_git("ls-remote", "origin", "HEAD", check=False)
    if read_check.returncode == 0:
        print("  PASS: GitHub allowed read access to this repository.")
    else:
        print("  FAIL: GitHub read access did not work.")
        print((read_check.stderr or read_check.stdout).strip())

    has_commit = run_git("rev-parse", "--verify", "HEAD", check=False).returncode == 0
    if not has_commit:
        print("  SKIP: Push dry run needs at least one commit in this repository.")
        return 0 if read_check.returncode == 0 else 1
    if not branch:
        print("  SKIP: Push dry run needs a named branch; this checkout is detached.")
        return 0 if read_check.returncode == 0 else 1

    print("Checking push access with a dry run (no remote changes are made)...")
    push_check = run_git(
        "push", "--dry-run", "origin", f"HEAD:refs/heads/{branch}", check=False
    )
    if push_check.returncode == 0:
        print("  PASS: GitHub accepted the push dry run.")
    else:
        print("  FAIL: Push dry run did not succeed.")
        print((push_check.stderr or push_check.stdout).strip())

    return 0 if read_check.returncode == 0 and push_check.returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
