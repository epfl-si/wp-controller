import base64
from types import SimpleNamespace

import pytest

from managers.site_repository import resolve_db_credentials
from models import WordpressSiteLookupError

SITE_UID = "site-uid-1"
OTHER_UID = "other-site-uid"


@pytest.fixture
def site():
    return {"metadata": {"name": "weird-site-name", "namespace": "ns", "uid": SITE_UID}}


def owner(uid=SITE_UID, kind="WordpressSite"):
    return [{"kind": kind, "name": "whatever", "uid": uid}]


def database(name="db-1", uid=SITE_UID):
    return {"metadata": {"name": name, "ownerReferences": owner(uid)}, "spec": {"mariaDbRef": {"name": "mariadb-02"}}}


def user(name="user-1", uid=SITE_UID, secret="pw-secret", key="password"):
    return {
        "metadata": {"name": name, "ownerReferences": owner(uid)},
        "spec": {"mariaDbRef": {"name": "mariadb-02"}, "passwordSecretKeyRef": {"name": secret, "key": key}},
    }


def secret(name="pw-secret", uid=SITE_UID, key="password", value="s3cret;"):
    refs = [SimpleNamespace(kind="WordpressSite", name="x", uid=uid)]
    return SimpleNamespace(
        metadata=SimpleNamespace(name=name, owner_references=refs),
        data={key: base64.b64encode(value.encode()).decode()},
    )


class TestResolveDbCredentials:
    def test_resolved_through_owner_references_whatever_the_names(self, site):
        creds = resolve_db_credentials(site, [database()], [user()], [secret()])

        assert (creds.host, creds.name, creds.user, creds.password) == ("mariadb-02", "db-1", "user-1", "s3cret;")

    def test_ignores_children_of_other_sites(self, site):
        creds = resolve_db_credentials(
            site,
            [database("db-other", OTHER_UID), database()],
            [user("user-other", OTHER_UID, secret="pw-other"), user()],
            [secret("pw-other", OTHER_UID, value="other"), secret()],
        )

        assert (creds.name, creds.user, creds.password) == ("db-1", "user-1", "s3cret;")

    def test_owner_kind_must_be_wordpresssite(self, site):
        db = database()
        db["metadata"]["ownerReferences"] = owner(kind="MariaDB")

        with pytest.raises(WordpressSiteLookupError, match="no Database"):
            resolve_db_credentials(site, [db], [user()], [secret()])

    def test_missing_database_or_user(self, site):
        with pytest.raises(WordpressSiteLookupError, match="no Database"):
            resolve_db_credentials(site, [], [user()], [secret()])
        with pytest.raises(WordpressSiteLookupError, match="no User"):
            resolve_db_credentials(site, [database()], [], [secret()])

    def test_ambiguous_children_are_refused(self, site):
        with pytest.raises(WordpressSiteLookupError, match="expected exactly one"):
            resolve_db_credentials(site, [database("a"), database("b")], [user()], [secret()])

    def test_secret_not_owned_by_the_site_is_refused(self, site):
        # A User pointing at some other Secret of the namespace must not
        # be a way to read it.
        with pytest.raises(WordpressSiteLookupError, match="not found, or not owned"):
            resolve_db_credentials(site, [database()], [user()], [secret(uid=OTHER_UID)])

    def test_secret_key_comes_from_the_user(self, site):
        creds = resolve_db_credentials(site, [database()], [user(key="pw")], [secret(key="pw", value="x")])
        assert creds.password == "x"

        with pytest.raises(WordpressSiteLookupError, match="key 'pw'"):
            resolve_db_credentials(site, [database()], [user(key="pw")], [secret(key="password")])

    def test_site_without_uid(self):
        with pytest.raises(WordpressSiteLookupError, match="no uid"):
            resolve_db_credentials({"metadata": {"name": "x", "namespace": "ns"}}, [], [], [])
