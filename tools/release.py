#!/usr/bin/env python3
"""Cut a release: run the tests, write the changelog, bump the version, tag it.

    python3 tools/release.py patch              # 0.1.0 -> 0.1.1
    python3 tools/release.py minor --push
    python3 tools/release.py 1.0.0 --dry-run
    python3 tools/release.py 0.1.0 --notes-file notes.md   # prose you wrote

The version lives in one place, `colwin/__init__.py`; `colwin --version` and the
`colwin_version` field of a workspace manifest both read it from there. This
script is the only thing that edits it.

What one run does, in order, stopping at the first thing that is wrong:

  1. refuses unless the checkout is clean, on the main branch, and not behind
     the remote (the release is pushed from here, so what is here has to be
     what everyone else has);
  2. runs `tests/test_roundtrip.py`, `tests/test_map.py` and
     `tests/test_docs.py` -- with the game
     directory if `--game` or `$COLWIN_GAME` names one, and with a warning if
     not, because the asset tests skip without it;
  3. drafts the changelog section from the commits since the last `v*` tag and
     opens it in `$EDITOR` for you to turn into prose (or takes a section you
     have already written, with `--notes-file`);
  4. writes it into `CHANGELOG.md`, bumps `__version__`, and checks that the
     bumped package really reports the new version;
  5. commits the two files and writes an annotated tag `v<version>` carrying
     the section body.

Pushing that tag is what publishes the release: `.github/workflows/release.yml`
re-runs the tests, rebuilds the artifacts and creates the GitHub release from
the same changelog section. This script pushes only when asked (`--push`), and
otherwise prints the two commands, plus how to undo the commit and the tag.

Stdlib only, like the rest of the repository.
"""
import argparse
import datetime
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INIT = os.path.join(ROOT, "colwin", "__init__.py")
CHANGELOG = os.path.join(ROOT, "CHANGELOG.md")
PROJECT_URL = "https://github.com/colonization-re/win-tools"
MAIN = "main"

VERSION_RE = re.compile(r'^__version__ = "(\d+\.\d+\.\d+)"$', re.M)
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
# "feat: ...", "fix(sprt)!: ..." -- used only if the history happens to be
# written that way; plain subjects are listed under one heading instead.
CONVENTIONAL_RE = re.compile(r"^([a-z]+)(\([^)]*\))?(!)?: (.+)$")
SECTIONS = [
    ("feat", "Added"),
    ("fix", "Fixed"),
    ("perf", "Changed"),
    ("refactor", "Changed"),
    ("docs", "Documentation"),
    ("test", "Tests"),
    ("build", "Housekeeping"),
    ("ci", "Housekeeping"),
    ("chore", "Housekeeping"),
]
ORDER = ["Added", "Changed", "Fixed", "Documentation", "Tests", "Housekeeping",
         "Other"]

EDIT_HELP = """
<!-- Write the section above the way you want it read: this is what the tag
     message and the GitHub release will say. Commit subjects are a draft, not
     the release notes. Keep the `## <version> - <date>` heading line: the
     release workflow finds the section by it. Everything from this comment
     down is dropped. Save an empty file to abort the release. -->
"""

CHANGELOG_HEADER = """# Changelog

Every released version of `colwin`, newest first. Versions are
[semantic](https://semver.org/spec/v2.0.0.html): the major number moves when a
workspace written by an older version stops rebuilding, the minor when formats
or commands are added, the patch for fixes. Cut a release with
`python3 tools/release.py`.
"""


def fail(msg):
    print("release: %s" % msg, file=sys.stderr)
    sys.exit(2)


def git(*args):
    out = subprocess.run(["git"] + list(args), cwd=ROOT, check=True,
                         stdout=subprocess.PIPE)
    return out.stdout.decode("utf-8", "replace").strip()


def git_ok(*args):
    return subprocess.run(["git"] + list(args), cwd=ROOT,
                          stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode == 0


# ---------------------------------------------------------------------- #
# versions

def current_version():
    with open(INIT, "r", encoding="utf-8") as f:
        text = f.read()
    m = VERSION_RE.search(text)
    if not m:
        fail("no `__version__ = \"x.y.z\"` line in %s"
             % os.path.relpath(INIT, ROOT))
    return m.group(1)


def parts(version):
    return tuple(int(p) for p in version.split("."))


def next_version(cur, spec):
    if SEMVER_RE.match(spec):
        return spec
    major, minor, patch = parts(cur)
    if spec == "major":
        return "%d.0.0" % (major + 1)
    if spec == "minor":
        return "%d.%d.0" % (major, minor + 1)
    if spec == "patch":
        return "%d.%d.%d" % (major, minor, patch + 1)
    fail("%r is neither major, minor, patch nor an x.y.z version" % spec)


def write_version(new):
    with open(INIT, "r", encoding="utf-8") as f:
        text = f.read()
    text, n = VERSION_RE.subn('__version__ = "%s"' % new, text, count=1)
    if n != 1:
        fail("could not rewrite the version in %s" % os.path.relpath(INIT, ROOT))
    with open(INIT, "w", encoding="utf-8") as f:
        f.write(text)


# ---------------------------------------------------------------------- #
# preconditions

def check_tree(args, version):
    if not git_ok("rev-parse", "--git-dir"):
        fail("%s is not a git checkout" % ROOT)
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    if branch != MAIN and not args.allow_branch:
        fail("on branch %s, not %s -- releases are cut from %s "
             "(--allow-branch to override)" % (branch, MAIN, MAIN))
    dirty = git("status", "--porcelain")
    if dirty:
        fail("the checkout has uncommitted changes:\n%s" % dirty)
    tag = "v" + version
    if git_ok("rev-parse", "--verify", "--quiet", "refs/tags/" + tag):
        fail("tag %s already exists -- that version is released" % tag)

    if args.no_fetch:
        return branch
    if not git_ok("remote", "get-url", "origin"):
        print("release: no origin remote; skipping the up-to-date check")
        return branch
    print("release: fetching origin")
    if not git_ok("fetch", "--quiet", "origin", "--tags"):
        fail("git fetch origin failed (--no-fetch to skip the check)")
    remote = "origin/" + branch
    if not git_ok("rev-parse", "--verify", "--quiet", remote):
        return branch
    behind = git("rev-list", "--count", "HEAD..%s" % remote)
    if behind != "0":
        fail("%s is %s commit(s) ahead of this checkout -- pull first"
             % (remote, behind))
    if git_ok("rev-parse", "--verify", "--quiet", "refs/tags/" + tag):
        fail("tag %s exists on origin -- that version is released" % tag)
    return branch


def run_tests(args):
    game = args.game or os.environ.get("COLWIN_GAME")
    if not game:
        print("release: no game directory (--game or $COLWIN_GAME); the asset "
              "tests will skip and only the codec, palette and PNG tests run")
    elif not os.path.isdir(game):
        fail("--game %s is not a directory" % game)
    suites = [["tests/test_roundtrip.py"], ["tests/test_map.py"],
              ["tests/test_docs.py"]]
    for suite in suites:
        cmd = [sys.executable] + suite + ([game] if game else [])
        print("release: %s" % " ".join(cmd))
        if subprocess.run(cmd, cwd=ROOT).returncode != 0:
            fail("%s failed -- not releasing" % suite[0])
    if subprocess.run([sys.executable, "colwin.py", "--help"], cwd=ROOT,
                      stdout=subprocess.DEVNULL).returncode != 0:
        fail("colwin.py --help failed -- not releasing")


# ---------------------------------------------------------------------- #
# changelog

def previous_tag():
    out = subprocess.run(["git", "describe", "--tags", "--abbrev=0",
                          "--match", "v[0-9]*"], cwd=ROOT,
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    if out.returncode != 0:
        return None
    return out.stdout.decode().strip() or None


def commits_since(tag):
    span = ["%s..HEAD" % tag] if tag else ["HEAD"]
    out = git("log", "--no-merges", "--reverse", "--pretty=%h\x1f%s", *span)
    commits = []
    for line in out.splitlines():
        if "\x1f" not in line:
            continue
        sha, subject = line.split("\x1f", 1)
        if subject.startswith("Release "):
            continue
        commits.append((sha, subject))
    return commits


def group(commits):
    """Group by conventional-commit type, or return one 'Other' bucket."""
    types = dict(SECTIONS)
    grouped = {}
    conventional = 0
    for sha, subject in commits:
        m = CONVENTIONAL_RE.match(subject)
        if m and m.group(1) in types:
            conventional += 1
            heading = types[m.group(1)]
            text = m.group(4)
            if m.group(3):
                text += " (breaking)"
        else:
            heading = "Other"
            text = subject
        grouped.setdefault(heading, []).append((sha, text))
    if conventional < len(commits) / 2.0:
        return {"Other": [(sha, subject) for sha, subject in commits]}
    return grouped


def draft(version, date, commits, prev):
    lines = ["## %s - %s" % (version, date), ""]
    if not commits:
        lines += ["- Nothing recorded since %s." % (prev or "the first commit"),
                  ""]
    else:
        grouped = group(commits)
        for heading in ORDER:
            if heading not in grouped:
                continue
            if list(grouped) != ["Other"]:
                lines += ["### %s" % heading, ""]
            for sha, text in grouped[heading]:
                lines.append("- %s (%s)" % (text, sha))
            lines.append("")
    if prev:
        lines.append("[Compare with %s](%s/compare/%s...v%s)"
                     % (prev, PROJECT_URL, prev, version))
    else:
        lines.append("[Commits](%s/commits/v%s)" % (PROJECT_URL, version))
    return "\n".join(lines).rstrip() + "\n"


def notes_from(path, version, date, prev):
    """A section written by hand instead of drafted from the commits.

    The file is the body of the section; the heading and the compare link are
    added around it. A file that brings its own `## <version> - <date>` heading
    is taken exactly as it stands.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read().strip()
    except IOError as e:
        fail("cannot read %s: %s" % (path, e))
    if not text:
        fail("%s is empty" % path)
    if text.startswith("## "):
        heading = text.split("\n", 1)[0]
        if not heading.startswith("## %s " % version):
            fail("%s leads with %r; the release workflow looks for a "
                 "'## %s - <date>' heading" % (path, heading, version))
        return text + "\n"
    lines = ["## %s - %s" % (version, date), "", text, ""]
    if prev:
        lines.append("[Compare with %s](%s/compare/%s...v%s)"
                     % (prev, PROJECT_URL, prev, version))
    else:
        lines.append("[Commits](%s/commits/v%s)" % (PROJECT_URL, version))
    return "\n".join(lines).rstrip() + "\n"


def edit(text):
    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL")
    if not editor:
        print("release: $EDITOR is not set; keeping the draft as it stands")
        return text
    fd, path = tempfile.mkstemp(prefix="colwin-release-", suffix=".md")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text + EDIT_HELP)
        if subprocess.run("%s %s" % (editor, path), shell=True).returncode != 0:
            fail("%s exited non-zero -- nothing has been changed" % editor)
        with open(path, "r", encoding="utf-8") as f:
            edited = f.read()
    finally:
        os.unlink(path)
    edited = edited.split("<!--")[0].strip()
    if not edited:
        fail("the changelog section came back empty -- release aborted")
    return edited + "\n"


def prepend_changelog(section):
    if os.path.exists(CHANGELOG):
        with open(CHANGELOG, "r", encoding="utf-8") as f:
            old = f.read()
    else:
        old = CHANGELOG_HEADER
    head, sep, rest = old.partition("\n## ")
    body = head.rstrip() + "\n\n" + section.rstrip() + "\n"
    if sep:
        body += "\n## " + rest.lstrip("\n")
    with open(CHANGELOG, "w", encoding="utf-8") as f:
        f.write(body)


# ---------------------------------------------------------------------- #

def main(argv=None):
    p = argparse.ArgumentParser(
        prog="release.py",
        description="Cut a colwin release: test, changelog, bump, tag.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="The tag is what publishes: pushing v<version> makes the "
               "release workflow build the artifacts and write the release "
               "notes from CHANGELOG.md.")
    p.add_argument("version", help="major, minor, patch, or an exact x.y.z")
    p.add_argument("--push", action="store_true",
                   help="push the branch and the tag when everything is done")
    p.add_argument("--dry-run", action="store_true",
                   help="say what would happen; write nothing, tag nothing")
    p.add_argument("--no-edit", action="store_true",
                   help="keep the drafted changelog section as it is")
    p.add_argument("--notes-file", metavar="PATH",
                   help="a changelog section you have written, in place of "
                        "the drafted commit list (implies --no-edit)")
    p.add_argument("--skip-tests", action="store_true",
                   help="do not run the test suites first")
    p.add_argument("--game", metavar="DIR",
                   help="the installed game, for the asset tests "
                        "(default: $COLWIN_GAME)")
    p.add_argument("--no-fetch", action="store_true",
                   help="do not fetch origin before checking the tree")
    p.add_argument("--allow-branch", action="store_true",
                   help="release from a branch other than %s" % MAIN)
    args = p.parse_args(argv)

    cur = current_version()
    new = next_version(cur, args.version)
    if parts(new) < parts(cur):
        fail("%s is older than the current %s" % (new, cur))
    branch = check_tree(args, new)
    prev = previous_tag()
    commits = commits_since(prev)
    print("release: %s -> %s, %d commit(s) since %s"
          % (cur, new, len(commits), prev or "the first commit"))

    if args.skip_tests:
        print("release: skipping the tests (--skip-tests)")
    else:
        run_tests(args)

    date = datetime.date.today().isoformat()
    if args.notes_file:
        section = notes_from(args.notes_file, new, date, prev)
    else:
        section = draft(new, date, commits, prev)
        if not args.no_edit and not args.dry_run:
            section = edit(section)

    if args.dry_run:
        print("\nrelease: --dry-run, nothing written. The section would be:\n")
        print(section)
        print("release: would bump %s to %s, commit CHANGELOG.md and "
              "colwin/__init__.py, and tag v%s"
              % (os.path.relpath(INIT, ROOT), new, new))
        return 0

    prepend_changelog(section)
    write_version(new)
    reported = subprocess.run(
        [sys.executable, "colwin.py", "--version"], cwd=ROOT,
        stdout=subprocess.PIPE).stdout.decode().strip()
    if reported != "colwin " + new:
        fail("after the bump colwin reports %r, not %r -- the working tree is "
             "edited but nothing is committed" % (reported, "colwin " + new))

    git("add", "CHANGELOG.md", "colwin/__init__.py")
    git("commit", "-m", "Release %s" % new)
    fd, path = tempfile.mkstemp(prefix="colwin-tag-")
    try:
        message = section.split("\n", 1)[1].strip()
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("colwin %s\n\n%s\n" % (new, message))
        git("tag", "-a", "v" + new, "-F", path)
    finally:
        os.unlink(path)
    print("release: committed and tagged v%s" % new)

    if args.push:
        git("push", "origin", branch)
        git("push", "origin", "v" + new)
        print("release: pushed. The release workflow is building %s/releases"
              % PROJECT_URL)
    else:
        print("\nNothing is pushed yet. To publish:\n"
              "    git push origin %s\n"
              "    git push origin v%s\n"
              "\nTo undo, before pushing:\n"
              "    git tag -d v%s && git reset --hard HEAD~1"
              % (branch, new, new))
    return 0


if __name__ == "__main__":
    sys.exit(main())
