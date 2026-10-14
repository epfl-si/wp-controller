import pytest

from managers.nginx_config import force_invalid, nginx_quote, render_config
from managers.site_builder import build_site_info
from models import DbCredentials


@pytest.mark.parametrize(
    "value, expected",
    [
        ("plain", '"plain"'),
        ("a;b", '"a;b"'),
        ('say "hi"', '"say \\"hi\\""'),
        ("back\\slash", '"back\\\\slash"'),
        ("pa$word", '"pa${dollar}word"'),
        ("", '""'),
    ],
)
def test_nginx_quote(value, expected):
    assert nginx_quote(value) == expected


def test_password_with_special_characters_cannot_break_out_of_its_directive(sample_wordpresssite_body):
    password = 'a;b c#d"e\\f$g{h}'
    db = DbCredentials(host="mariadb", name="db", user="user", password=password)
    rendered = render_config([build_site_info(sample_wordpresssite_body, db)])

    assert f"fastcgi_param WP_DB_PASSWORD     {nginx_quote(password)};" in rendered
    assert 'fastcgi_param WP_DB_PASSWORD     "a;b c#d\\"e\\\\f${dollar}g{h}";' in rendered


def test_missing_files_keep_their_url_and_get_the_error_page(sample_wordpresssite_body, sample_db_credentials):
    rendered = render_config([build_site_info(sample_wordpresssite_body, sample_db_credentials)])

    # try_files with a URI fallback is an internal redirect: $uri becomes the
    # fallback, so the request used to reach PHP as the site root.
    assert "try_files" not in rendered
    assert "error_page 403 404 500 502 503 504 /global-error/index.php;" in rendered


def test_site_location_defaults_to_php(sample_wordpresssite_body, sample_db_credentials):
    rendered = render_config([build_site_info(sample_wordpresssite_body, sample_db_credentials)])
    site_block = rendered.split("location /labs/lo/ {", 1)[1]

    # a fastcgi_pass directly in the site's location, before its nested ones
    assert site_block.index("fastcgi_pass") < site_block.index("location ~")


def test_force_invalid_appends_an_unknown_directive():
    broken = force_invalid("server {}\n")

    assert broken.startswith("server {}\n")
    assert "\nwp_controller_forced_invalid_directive;\n" in broken


def test_health_endpoints_answer_200_whatever_the_sites(sample_wordpresssite_body, sample_db_credentials):
    """Neither /healthz (readiness) nor /livez (liveness) may answer 503: a
    site that can't be resolved just 404s, it must not take the sites that
    did resolve out of the Service."""
    for sites in ([], [build_site_info(sample_wordpresssite_body, sample_db_credentials)]):
        rendered = render_config(sites)

        for path in ("/healthz", "/livez"):
            block = rendered.split(f"location {path} {{", 1)[1].split("}", 1)[0]
            assert 'return 200 "ok\\n";' in block
        assert "return 503" not in rendered
