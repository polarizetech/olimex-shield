#!/usr/bin/env python3
"""check_docs.py -- keep the README and the blog post in step with the code.

    python3 scripts/check_docs.py
    OLIMEX_BLOG_POST=/path/to/post.md python3 scripts/check_docs.py

1. The README's safety list is the workbench's list, word for word.
2. The Polarize.Tech post "Can a $70 board tell me I'm wrong?" states SPEC figures this repo
   defines (the default µV per count, the datasheet figure, the analog band, the converter bits,
   the declared rate), and the README shows photos taken from it. Each shared spec figure must
   appear in the post as the code has it, each photo must be byte-identical to the post's copy,
   and the post must link to this repo.

The post's measured results for its board (noise, rate error) are findings, not constants of this
tool, so they are not checked here: they live with the research, not in the code.

The post lives in the polarize.tech site repo. It is found through `$OLIMEX_BLOG_POST`, else as a
sibling checkout `../polarize.tech`. If neither exists, part 2 says SKIP.
When this fails, fix whichever side is wrong: the code, or the post.
"""

import hashlib
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "apps" / "server"), str(REPO / "apps" / "web")]

import hookup  # noqa: E402
import rig  # noqa: E402

POST_NAME = "2026-08-25-can-a-70-dollar-board-tell-me-im-wrong.md"
REPO_URL = "github.com/polarizetech/olimex-shield"
# README photo -> the post's copy, relative to the site repo.
PHOTOS = {
    "docs/images/olimex-shield-ekg-emg.jpg": "assets/posts/rig/olimex-shield-ekg-emg.jpg",
    "docs/images/olimex-shield-ekg-emg-pro-cable.jpg": (
        "assets/posts/rig/olimex-shield-ekg-emg-pro-cable.jpg"
    ),
}

failures = []


def check(ok, label):
    print(f"  {'ok  ' if ok else 'FAIL'} {label}")
    if not ok:
        failures.append(label)


def num(x):
    """7.9 -> '7.9', 40.0 -> '40'."""
    return f"{x:g}"


def find_post():
    env = os.environ.get("OLIMEX_BLOG_POST")
    if env:
        return Path(env).expanduser()
    return REPO.parent / "polarize.tech" / "_posts" / POST_NAME


print("README")
readme = (REPO / "README.md").read_text()
listed = re.findall(r"^\d+\. (.+)$", readme.split("## Safety", 1)[-1].split("\n## ", 1)[0], re.M)
check(listed == list(hookup.SAFETY), "safety list matches apps/web/hookup.py SAFETY word for word")

print("blog post")
post_path = find_post()
if not post_path.is_file():
    print(f"  SKIP post not found at {post_path} (set OLIMEX_BLOG_POST)")
else:
    post = post_path.read_text()
    site = post_path.parents[1]
    facts = [
        ("default µV per count", f"{num(rig.UV_PER_COUNT)} µV/count"),
        ("datasheet µV per count", f"implies {num(rig.UV_PER_COUNT_DATASHEET)}"),
        ("analog band", f"{num(rig.FRONT_END_HP_HZ)}–{num(rig.FRONT_END_LP_HZ)} Hz"),
        ("converter bits", f"{rig.ADC_BITS}-bit"),
        ("declared rate", f"{num(rig.NOMINAL_RATE_HZ)} Hz"),
    ]
    for label, text in facts:
        check(text in post, f"{label}: post says '{text}'")
    check(REPO_URL in post, f"post links to {REPO_URL}")
    for mine, theirs in PHOTOS.items():
        a, b = REPO / mine, site / theirs
        same = b.is_file() and (
            hashlib.sha256(a.read_bytes()).digest() == hashlib.sha256(b.read_bytes()).digest()
        )
        check(same, f"{mine} is the post's {theirs}")

if failures:
    print(f"{len(failures)} out of step: fix the code or the post")
    sys.exit(1)
print("docs in step")
