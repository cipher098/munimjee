#!/usr/bin/env python3
"""Private bounded exec helper: safe alternative to preexec_fn in worker threads."""
import os
import resource
import sys


def main():
    try:
        # All command arguments are nonsecret. Credentials stay in the private
        # process environment. execve preserves the PID owned by subprocess.run.
        limit = int(sys.argv[1])
        if limit != 64 * 1024 * 1024 or len(sys.argv) < 3 or not os.path.isabs(sys.argv[2]):
            return 125
        resource.setrlimit(resource.RLIMIT_FSIZE, (limit, limit))
        os.execve(sys.argv[2], sys.argv[2:], dict(os.environ))
    except Exception:
        return 125  # Never print environment, command, errors or row content.


if __name__ == "__main__":
    raise SystemExit(main())
