"""Carry commits between this install and our fork of the upstream source repo.

This folder is a built install: the contents of upstream's `dist/` sit at its root. Upstream
(Teravibes/L2-Living-Worlds) and our fork (cybercyberz/L2-Living-Worlds, branch living-world-mods) use the
source layout. PATH_MAP translates between the two.

  python tools/forksync/forksync.py map <local-path>...
      Print where each local path lives in the fork (or "skip").

  python tools/forksync/forksync.py replay <fork-dir> <rev-range>
      Replay local commits (e.g. 92b064b4..HEAD) onto the fork checkout's current branch, one fork commit per
      local commit, with the same message, author and author date. Commits that only touch skipped paths
      are dropped. Push the fork yourself afterwards.

  python tools/forksync/forksync.py import <fork-dir> <fork-rev-range>
      The other way round, for a selective update: write the files that <fork-rev-range> changed (e.g. one
      upstream commit, abc123~1..abc123) into this install's working tree, through the reverse map.
      Nothing is committed; review with `git diff`, then commit and log it in CHANGELOG.md.
"""

import os
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SRC = "L2J_Mobius_CT_0_Interlude github"

# (local prefix, fork prefix). First match wins, so specific entries go first. None means "not carried".
PATH_MAP = [
    (".gitignore", None),                  # our whitelist; the fork uses upstream's .gitignore
    (".gitattributes", None),
    ("brain/README.md", None),             # written by upstream's build-pack.ps1
    ("brain/knowledge/", SRC + "/knowledge/"),
    ("brain/fpc_brain.py", SRC + "/fpc_brain.py"),
    ("brain/requirements.txt", SRC + "/requirements.txt"),
    ("brain/setup_brain.bat", SRC + "/setup_brain.bat"),
    ("brain/setup_brain.sh", SRC + "/setup_brain.sh"),
    ("brain/", None),                      # anything new here needs its own entry above
    ("tools/", SRC + "/tools/"),
    ("docs/", "docs/mods/"),               # upstream docs/ holds its own guides
    ("CHANGELOG.md", "CHANGELOG-mods.md"),
    ("CLAUDE.md", "CLAUDE.md"),
    ("readme.txt", SRC + "/readme.txt"),
    ("", SRC + "/dist/"),                  # game/, login/, db_installer/, launcher/, scripts/, *.bat
]

# Fork-only paths that have no place in the install.
FORK_ONLY = ("docs/MODULE_", ".github/", "fpc data/", "README.md", "LICENSE", SRC + "/java/", SRC + "/tests/",
             SRC + "/launcher/", SRC + "/dist/libs/", SRC + "/dist/images/", SRC + "/dist/launcher-app/",
             SRC + "/dist/backup/", SRC + "/dist/build-launcher.bat", SRC + "/dist/launcher/build-pack.",
             SRC + "/dist/launcher/assets/")


def to_fork(path):
    for local, fork in PATH_MAP:
        if path == local or (local.endswith("/") or local == "") and path.startswith(local):
            return None if fork is None else fork + path[len(local):]
    return None


def to_local(path):
    if path.startswith(FORK_ONLY) and not path.startswith("docs/mods/"):
        return None
    best = None
    for local, fork in PATH_MAP:
        if fork is None:
            continue
        if path == fork or fork.endswith("/") and path.startswith(fork):
            if best is None or len(fork) > len(best[1]):
                best = (local, fork)
    return None if best is None else best[0] + path[len(best[1]):]


def git(repo, *args, data=None):
    return subprocess.run(["git", "-C", repo, *args], input=data, capture_output=True, check=True).stdout


def changed(repo, rev):
    """(status, path) for each file a commit changed, renames split into delete + add."""
    out = git(repo, "diff-tree", "-r", "--no-commit-id", "--no-renames", "-z", "--name-status", rev + "~1", rev)
    parts = out.decode("utf-8").split("\0")
    return [(parts[i], parts[i + 1]) for i in range(0, len(parts) - 1, 2)]


def copy_changes(src_repo, rev, dst_repo, mapper):
    """Write rev's changes from src_repo into dst_repo's working tree; returns the dst paths touched."""
    touched = []
    for status, path in changed(src_repo, rev):
        dst = mapper(path)
        if dst is None:
            continue
        full = os.path.join(dst_repo, dst)
        if status == "D":
            if os.path.exists(full):
                os.remove(full)
        else:
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "wb") as f:
                f.write(git(src_repo, "show", rev + ":" + path))
        touched.append(dst)
    return touched


def revs(repo, rev_range):
    return git(repo, "rev-list", "--reverse", "--no-merges", rev_range).decode().split()


def replay(fork, rev_range):
    for rev in revs(ROOT, rev_range):
        subject = git(ROOT, "log", "-1", "--format=%h %s", rev).decode().strip()
        touched = copy_changes(ROOT, rev, fork, to_fork)
        for _, path in changed(ROOT, rev):
            if to_fork(path) is None:
                print("       not carried: " + path)
        if touched:
            git(fork, "add", "-A", "--", *touched)
        if not touched or not git(fork, "diff", "--cached", "--name-only").strip():
            print("skip   " + subject + "  (nothing to carry)")
            continue
        meta = git(ROOT, "log", "-1", "--format=%an%x00%ae%x00%aI", rev).decode().split("\0")
        env = dict(os.environ, GIT_AUTHOR_NAME=meta[0], GIT_AUTHOR_EMAIL=meta[1], GIT_AUTHOR_DATE=meta[2])
        message = git(ROOT, "log", "-1", "--format=%B", rev)
        subprocess.run(["git", "-C", fork, "commit", "-q", "-F", "-"], input=message, env=env, check=True)
        print("commit " + subject)


def import_(fork, rev_range):
    for rev in revs(fork, rev_range):
        subject = git(fork, "log", "-1", "--format=%h %s", rev).decode().strip()
        skipped = [p for _, p in changed(fork, rev) if to_local(p) is None]
        touched = copy_changes(fork, rev, ROOT, to_local)
        print("%s  (%d files written, %d fork-only skipped)" % (subject, len(touched), len(skipped)))


def main(argv):
    if len(argv) >= 2 and argv[0] == "map":
        for p in argv[1:]:
            print("%s -> %s" % (p, to_fork(p.replace("\\", "/")) or "skip"))
    elif len(argv) == 3 and argv[0] == "replay":
        replay(argv[1], argv[2])
    elif len(argv) == 3 and argv[0] == "import":
        import_(argv[1], argv[2])
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
