#!/usr/bin/env python3
"""Fetch the shared stylesheet for docs/ from a pinned web-ui release.

    python3 tools/fetch_webui.py            # what docs/_config.yml pins
    python3 tools/fetch_webui.py v1.1.0     # a different release, once
    python3 tools/fetch_webui.py --pin v1.1.0   # and write it into _config.yml

The design system lives in colonization-re/web-ui and ships `col.css` as a
release asset. The pages cannot link that asset directly -- GitHub serves it as
`application/octet-stream` with `X-Content-Type-Options: nosniff`, so a browser
refuses to apply it as a stylesheet, and the download URL is a signed redirect
that expires. So it is fetched at build time instead, pinned to one version:

  * `web_ui_version` in `docs/_config.yml` is the pin, and the only line to
    edit to move to a new release;
  * `.github/workflows/pages.yml` runs this script before Jekyll, so the
    deployed site always carries exactly that version;
  * `docs/assets/col.css` is the result and is not in git -- it is a download,
    not a source file. Run this once to preview the site locally.

The release also carries `SHA256SUMS.txt`; the asset is checked against it and
nothing is written if it does not match. A failure here fails the Pages build
rather than deploying a site with no stylesheet.
"""
import hashlib
import os
import re
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(ROOT, "docs", "_config.yml")
OUT = os.path.join(ROOT, "docs", "assets", "col.css")
REPO = "colonization-re/web-ui"
ASSET = "col.css"
SUMS = "SHA256SUMS.txt"
URL = "https://github.com/%s/releases/download/%%s/%%s" % REPO

HEADER = """/* %s %s -- the project's shared design system, from
 * https://github.com/%s/releases/tag/%s
 *
 * DOWNLOADED, not edited here and not in git. The pin is `web_ui_version` in
 * docs/_config.yml; `python3 tools/fetch_webui.py` puts this file back.
 */
"""


def pinned_version():
    """The `web_ui_version:` line of docs/_config.yml."""
    with open(CONFIG) as f:
        text = f.read()
    m = re.search(r"^web_ui_version:\s*(\S+)\s*$", text, re.M)
    if not m:
        raise SystemExit("no `web_ui_version:` line in docs/_config.yml")
    return m.group(1).strip("\"'")


def repin(version):
    with open(CONFIG) as f:
        text = f.read()
    new, n = re.subn(r"^(web_ui_version:\s*)\S+\s*$",
                     lambda m: m.group(1) + version, text, flags=re.M)
    if n != 1:
        raise SystemExit("no `web_ui_version:` line in docs/_config.yml")
    with open(CONFIG, "w") as f:
        f.write(new)


def get(url):
    try:
        with urllib.request.urlopen(url) as r:
            return r.read()
    except Exception as e:                      # noqa: BLE001 - message is the point
        raise SystemExit("%s: %s" % (url, e))


def expected_sha(sums, name):
    """The digest `name` is listed with in a sha256sum-format file."""
    for line in sums.decode("utf-8", "replace").splitlines():
        parts = line.split()
        if len(parts) == 2 and os.path.basename(parts[1].lstrip("*")) == name:
            return parts[0]
    raise SystemExit("%s lists no %s" % (SUMS, name))


def main(argv):
    pin = False
    args = []
    for a in argv:
        if a == "--pin":
            pin = True
        elif a in ("-h", "--help"):
            print(__doc__)
            return 0
        else:
            args.append(a)
    version = args[0] if args else pinned_version()
    if pin and not args:
        raise SystemExit("--pin needs a version")

    css = get(URL % (version, ASSET))
    want = expected_sha(get(URL % (version, SUMS)), ASSET)
    got = hashlib.sha256(css).hexdigest()
    if got != want:
        raise SystemExit("%s of %s is %s, %s says %s"
                         % (ASSET, version, got, SUMS, want))

    name = os.path.basename(REPO)
    text = HEADER % (name, version, REPO, version) + css.decode("utf-8")
    d = os.path.dirname(OUT)
    if not os.path.isdir(d):
        os.makedirs(d)
    with open(OUT, "w") as f:
        f.write(text)
    if pin:
        repin(version)
        print("pinned web_ui_version: %s in docs/_config.yml" % version)
    print("%s %s -> %s (%d bytes, sha256 %s)"
          % (ASSET, version, os.path.relpath(OUT, ROOT), len(css), got[:12]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
