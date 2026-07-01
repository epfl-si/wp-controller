import os
import tempfile
from itertools import groupby
from operator import attrgetter
from pathlib import Path
from typing import List

from jinja2 import Environment, FileSystemLoader

from constants import FASTCGI_INCLUDE_PATH
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
    template = _env.get_template("nginx.conf.j2")
    return template.render(hosts=_group_by_hostname(sites), fastcgi_include_path=FASTCGI_INCLUDE_PATH)


def write_config_atomic(content: str, path: str) -> None:
    """Write the rendered config to `path` atomically: write to a temp file
    in the same directory, then os.replace() so nginx never observes a
    half-written config file."""
    directory = os.path.dirname(path) or "."
    fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".wp-controller-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
        os.replace(tmp_path, path)
    except BaseException:
        os.unlink(tmp_path)
        raise
