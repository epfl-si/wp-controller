import pytest

from managers.site_builder import build_site_info


class TestBuildSiteInfo:
    def test_builds_site_info_from_valid_body(self, sample_wordpresssite_body, sample_db_credentials):
        site = build_site_info(sample_wordpresssite_body, sample_db_credentials)

        assert site.name == "www-labs-lo"
        assert site.namespace == "wordpress-test"
        assert site.hostname == "wpn.fsd.team"
        assert site.path == "/labs/lo"
        assert site.uploads_dirname == "www-labs-lo"
        assert site.debug is True
        assert site.db is sample_db_credentials
        assert site.protection_script == ""

    def test_root_uri_adds_trailing_slash(self, sample_wordpresssite_body, sample_db_credentials):
        site = build_site_info(sample_wordpresssite_body, sample_db_credentials)
        assert site.root_uri == "/labs/lo/"

    def test_root_uri_keeps_existing_trailing_slash(self, sample_wordpresssite_body, sample_db_credentials):
        sample_wordpresssite_body["spec"]["path"] = "/labs/lo/"
        site = build_site_info(sample_wordpresssite_body, sample_db_credentials)
        assert site.root_uri == "/labs/lo/"

    def test_passes_through_protection_script(self, sample_wordpresssite_body, sample_db_credentials):
        sample_wordpresssite_body["spec"]["wordpress"]["downloadsProtectionScript"] = "/scripts/protect.php"
        site = build_site_info(sample_wordpresssite_body, sample_db_credentials)
        assert site.protection_script == "/scripts/protect.php"

    def test_rejects_unsafe_hostname(self, sample_wordpresssite_body, sample_db_credentials):
        sample_wordpresssite_body["spec"]["hostname"] = "evil.com; server { }"
        with pytest.raises(ValueError, match="unsafe hostname"):
            build_site_info(sample_wordpresssite_body, sample_db_credentials)

    @pytest.mark.parametrize(
        "unsafe_path",
        [
            "/labs/lo; fastcgi_pass evil;",
            "/labs/{lo}",
            '/labs/"lo"',
            "/labs/$lo",
        ],
    )
    def test_rejects_unsafe_path(self, sample_wordpresssite_body, sample_db_credentials, unsafe_path):
        sample_wordpresssite_body["spec"]["path"] = unsafe_path
        with pytest.raises(ValueError, match="unsafe path"):
            build_site_info(sample_wordpresssite_body, sample_db_credentials)
