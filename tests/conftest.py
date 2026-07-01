import pytest

from models import DbCredentials


@pytest.fixture
def sample_wordpresssite_body():
    return {
        "apiVersion": "wordpress.epfl.ch/v2",
        "kind": "WordpressSite",
        "metadata": {
            "name": "www-labs-lo",
            "namespace": "wordpress-test",
            "uid": "www-labs-lo-uid",
        },
        "spec": {
            "hostname": "wpn.fsd.team",
            "path": "/labs/lo",
            "wordpress": {
                "title": "LO",
                "tagline": "lol",
                "theme": "wp-theme-2018",
                "debug": True,
            },
        },
    }


@pytest.fixture
def sample_db_credentials():
    return DbCredentials(host="mariadb-min", name="wp-db-www-labs-lo", user="wp-db-user-www-labs-lo", password="s3cr3t")
