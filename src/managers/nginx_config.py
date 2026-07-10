import os
import tempfile
from itertools import groupby
from operator import attrgetter
from pathlib import Path
from typing import List

from jinja2 import Environment, FileSystemLoader

from settings import FASTCGI_INCLUDE_PATH, STATIC_ASSET_WHITELIST_RE, UPLOADS_ROOT
from models import WordpressSiteInfo

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

_env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    trim_blocks=True,
    lstrip_blocks=True,
    autoescape=False,
)


def _group_by_hostname(sites: List[WordpressSiteInfo]):
    ordered = sorted(sites, key=attrgetter("hostname"))
    return [(hostname, list(group)) for hostname, group in groupby(ordered, key=attrgetter("hostname"))]


def render_config(sites: List[WordpressSiteInfo]) -> str:
    template = _env.get_template("wordpress.conf.j2")
    return template.render(
        hosts=_group_by_hostname(sites),
        fastcgi_include_path=FASTCGI_INCLUDE_PATH,
        uploads_root=UPLOADS_ROOT,
        static_whitelist_re=STATIC_ASSET_WHITELIST_RE,
    )


def write_candidate_config(content: str, path: str) -> str:
    """Write `content` to a temp file next to `path`, without touching
    `path` itself, and return the temp file's path. Named `*.conf` (and not
    dot-prefixed) so nginx's `include conf.d/*.conf` picks it up for
    validation - see NginxProcess.validate() - alongside the still-untouched
    current config. The caller must either discard it with os.unlink() (on
    a failed validation) or move it into place with commit_candidate_config
    (once validated): the live config path must never be overwritten with
    unverified content."""
    directory = os.path.dirname(path) or "."
    fd, candidate_path = tempfile.mkstemp(dir=directory, prefix="wp-controller-candidate-", suffix=".conf")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
    except BaseException:
        os.unlink(candidate_path)
        raise
    return candidate_path


def commit_candidate_config(candidate_path: str, path: str) -> None:
    """Atomically move an already-validated candidate config into place.
    Raises FileNotFoundError if candidate_path is gone - callers must only
    call this once, right after a successful validate(), never blindly."""
    if not os.path.exists(candidate_path):
        raise FileNotFoundError(f"Candidate config {candidate_path} does not exist, refusing to commit to {path}")
    os.replace(candidate_path, path)
