import os
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


def nginx_quote(value) -> str:
    """Render `value` as a single nginx string argument, whatever it
    contains. Unquoted, a `;` (or a space, `#`, `{`...) in e.g. a database
    password would end or split the directive; inside double quotes only
    `\\`, `"` and `$` stay special. `$` would be read as a variable, and
    nginx has no escape for it, so it goes through the `$dollar` variable
    that templates/generic.conf defines as a literal `$`."""
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"').replace("$", "${dollar}")
    return f'"{escaped}"'


_env.filters["nginx_quote"] = nginx_quote


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
    """Write `content` to a temp file next to `path` (same filesystem, so
    os.rename stays atomic) and return its path. The `.candidate` suffix
    keeps nginx's `conf.d/*.conf` include from ever picking it up."""
    directory = os.path.dirname(path) or "."
    fd, candidate_path = tempfile.mkstemp(dir=directory, prefix="wp-controller-", suffix=".candidate")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
    except BaseException:
        os.unlink(candidate_path)
        raise
    return candidate_path


def build_validation_config(candidate_path: str, path: str) -> str:
    """Build a single throwaway main config to `nginx -t` the candidate
    with, leaving everything under nginx's config directory untouched: it
    is the real main config byte-for-byte, except that its
    `include <conf.d>/*.conf;` becomes one explicit include per file already
    in conf.d/ *other than the live config at `path`* (which the candidate
    replaces - both declare the same `default_server`, so nginx would
    reject having both), plus the candidate. Returns its path; the caller
    must remove it with cleanup_validation_config(). Raises RuntimeError if
    the main config has no such include - before anything was touched."""
    conf_d_dir = os.path.dirname(path)
    with open(NGINX_MAIN_CONF_PATH) as f:
        main_conf = f.read()
    real_include = f"include {conf_d_dir}/*.conf;"
    if real_include not in main_conf:
        raise RuntimeError(f"{NGINX_MAIN_CONF_PATH} does not contain {real_include!r} - cannot validate candidate")

    live_name = os.path.basename(path)
    kept = sorted(
        os.path.join(conf_d_dir, name)
        for name in os.listdir(conf_d_dir)
        if name.endswith(".conf") and name != live_name
    )
    includes = "\n".join(f"include {p};" for p in [*kept, candidate_path])

    fd, validation_path = tempfile.mkstemp(prefix="wp-controller-validate-", suffix=".conf")
    with os.fdopen(fd, "w") as f:
        f.write(main_conf.replace(real_include, includes))
    return validation_path


def cleanup_validation_config(validation_path: str) -> None:
    try:
        os.unlink(validation_path)
    except FileNotFoundError:
        pass


def commit_candidate_config(candidate_path: str, path: str) -> None:
    """Move an already-validated candidate over the live config: a single
    atomic os.rename, the only step that touches the live config."""
    
    if not os.path.exists(candidate_path):
        raise FileNotFoundError(f"Candidate config {candidate_path} does not exist, refusing to commit to {path}")
    os.rename(candidate_path, path)
