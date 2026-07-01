import re

from models import DbCredentials, WordpressSiteInfo

# The WordpressSite CRD only constrains `path` to start with a slash
# (`^/(.*)`), so unlike `hostname` it cannot be trusted to be free of
# characters that would break out of an nginx `location` block.
_SAFE_HOST_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)+$")
_SAFE_PATH_RE = re.compile(r"^/[A-Za-z0-9_\-./]*$")


def build_site_info(raw_site: dict, db: DbCredentials) -> WordpressSiteInfo:
    """Turn a raw WordpressSite object plus its resolved DB credentials into
    a WordpressSiteInfo. Raises ValueError if the site cannot be safely
    rendered into an nginx configuration."""
    metadata = raw_site.get("metadata", {})
    spec = raw_site.get("spec", {})
    name = metadata.get("name")
    namespace = metadata.get("namespace")

    hostname = spec.get("hostname", "")
    if not _SAFE_HOST_RE.match(hostname):
        raise ValueError(f"WordpressSite {namespace}/{name} has an unsafe hostname: {hostname!r}")

    path = spec.get("path", "")
    if not _SAFE_PATH_RE.match(path):
        raise ValueError(f"WordpressSite {namespace}/{name} has an unsafe path: {path!r}")

    wordpress = spec.get("wordpress", {})

    return WordpressSiteInfo(
        name=name,
        namespace=namespace,
        hostname=hostname,
        path=path,
        uploads_dirname=name,
        debug=bool(wordpress.get("debug", False)),
        db=db,
        protection_script=wordpress.get("downloadsProtectionScript", "") or "",
    )
