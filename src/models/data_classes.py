from dataclasses import dataclass


@dataclass
class DbCredentials:
    host: str
    name: str
    user: str
    password: str


@dataclass
class WordpressSiteInfo:
    name: str
    namespace: str
    hostname: str
    path: str
    uploads_dirname: str
    debug: bool
    db: DbCredentials
    protection_script: str = ""

    @property
    def root_uri(self) -> str:
        """WP_ROOT_URI always needs a trailing slash."""
        return self.path if self.path.endswith("/") else f"{self.path}/"
