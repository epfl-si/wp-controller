from itertools import groupby
from operator import attrgetter
from pathlib import Path
from typing import List

from jinja2 import Environment, FileSystemLoader

from models import WordpressSiteInfo

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
FASTCGI_INCLUDE_PATH = "/etc/nginx/conf.d/wordpress_fastcgi.conf"

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
