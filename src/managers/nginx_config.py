import os
import shutil
import tempfile
from itertools import groupby
from operator import attrgetter
from pathlib import Path
from typing import List

from jinja2 import Environment, FileSystemLoader

from settings import FASTCGI_INCLUDE_PATH, NGINX_MAIN_CONF_PATH, STATIC_ASSET_WHITELIST_RE, UPLOADS_ROOT
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
    `path` itself, and return the temp file's path. The caller must either
    discard it with os.unlink() (on a failed validation) or move it into
    place with commit_candidate_config (once validated): the live config
    path must never be overwritten with unverified content. Validate it via
    prepare_validation_root - not by including it alongside `path` as-is,
    since both declare a `default_server` for the same address and nginx
    rejects having both present at once."""
    directory = os.path.dirname(path) or "."
    fd, candidate_path = tempfile.mkstemp(dir=directory, prefix="wp-controller-candidate-", suffix=".conf")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
    except BaseException:
        os.unlink(candidate_path)
        raise
    return candidate_path


def prepare_validation_root(candidate_path: str, path: str) -> str:
    """Build a throwaway copy of nginx's config tree to validate
    `candidate_path` in full isolation from the live config at `path`,
    without ever touching conf.d/ itself: a scratch conf.d/ is populated
    with symlinks to every real file there (generic.conf, shared snippets,
    etc.) *except* `path`, plus the candidate. Everything else - events{},
    http{} settings, mime types, ... - is reused byte-for-byte from the
    real main config, so what's tested matches what actually runs; only
    its `conf.d/*.conf` include is repointed at the scratch directory.
    Returns the scratch main config's path, to pass to NginxProcess.
    validate(); the caller must remove its parent dir with
    cleanup_validation_root() once done, pass or fail."""
    conf_d_dir = os.path.dirname(path)
    scratch_dir = tempfile.mkdtemp(prefix="wp-controller-validate-")
    scratch_conf_d = os.path.join(scratch_dir, "conf.d")
    os.mkdir(scratch_conf_d)

    # write_candidate_config already dropped candidate_path inside conf_d_dir
    # (see its docstring) - exclude it here too, it's (re-)linked in below.
    live_name = os.path.basename(path)
    candidate_name = os.path.basename(candidate_path)
    for name in os.listdir(conf_d_dir):
        if name not in (live_name, candidate_name):
            os.symlink(os.path.join(conf_d_dir, name), os.path.join(scratch_conf_d, name))
    os.symlink(os.path.abspath(candidate_path), os.path.join(scratch_conf_d, candidate_name))

    with open(NGINX_MAIN_CONF_PATH) as f:
        main_conf = f.read()
    real_include = f"include {conf_d_dir}/*.conf;"
    scratch_include = f"include {scratch_conf_d}/*.conf;"
    if real_include not in main_conf:
        shutil.rmtree(scratch_dir)
        raise RuntimeError(f"{NGINX_MAIN_CONF_PATH} does not contain {real_include!r} - cannot isolate validation")

    scratch_main_conf = os.path.join(scratch_dir, "nginx.conf")
    with open(scratch_main_conf, "w") as f:
        f.write(main_conf.replace(real_include, scratch_include))
    return scratch_main_conf


def cleanup_validation_root(scratch_main_conf: str) -> None:
    shutil.rmtree(os.path.dirname(scratch_main_conf), ignore_errors=True)


def commit_candidate_config(candidate_path: str, path: str) -> None:
    """Atomically move an already-validated candidate config into place.
    Raises FileNotFoundError if candidate_path is gone - callers must only
    call this once, right after a successful validate(), never blindly."""
    if not os.path.exists(candidate_path):
        raise FileNotFoundError(f"Candidate config {candidate_path} does not exist, refusing to commit to {path}")
    os.replace(candidate_path, path)
