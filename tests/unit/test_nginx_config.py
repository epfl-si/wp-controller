import pytest

from managers.nginx_config import nginx_quote, render_config
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
