import pytest

from crawlers.config import ConfigError, load_sources, parse_sources


def test_shipped_sources_yaml_is_valid():
    sources = load_sources()
    slugs = [s.slug for s in sources]
    assert len(slugs) == len(set(slugs))
    assert {"geezjobs", "reliefweb", "tg_abayjobs21", "ethiojobs", "hahu"} <= set(slugs)
    # every database seed slug from 0001_init.sql is covered
    assert {"ethiojobs", "reliefweb", "tg_abayjobs21", "hahu", "ethiopianreporter", "geezjobs", "ethiopiawork",
            "palmjobs", "muyalogy", "ethiongojobs", "tg_josad", "tg_freelance", "unjobs", "impactpool"} <= set(slugs)


def test_defaults_merge_and_options_split():
    s = parse_sources({"defaults": {"delay": 3, "max_pages": 7},
                       "sources": [{"slug": "a", "name": "A", "kind": "portal", "engine": "html",
                                    "base_url": "https://a.test/", "discovery": {"list_urls": ["x"]}}]})[0]
    assert s.delay == 3.0 and s.options["max_pages"] == 7 and s.options["discovery"] == {"list_urls": ["x"]}
    assert s.enabled is False and s.respect_robots is True


@pytest.mark.parametrize("entry, fragment", [
    ({"slug": "A B", "name": "x", "kind": "portal", "engine": "html", "base_url": "u"}, "slug must be"),
    ({"slug": "a", "name": "x", "kind": "blog", "engine": "html", "base_url": "u"}, "kind must be"),
    ({"slug": "a", "name": "x", "kind": "portal", "engine": "scrapy", "base_url": "u"}, "engine must be"),
    ({"slug": "a", "name": "x", "kind": "portal", "engine": "html"}, "missing required field 'base_url'"),
    ({"slug": "a", "name": "x", "kind": "telegram", "engine": "telegram", "base_url": "u", "enabled": True},
     "needs 'channel'"),
    ({"slug": "a", "name": "x", "kind": "portal", "engine": "json_api", "base_url": "u", "enabled": True},
     "needs 'url'"),
])
def test_validation_problems(entry, fragment):
    with pytest.raises(ConfigError) as e:
        parse_sources({"sources": [entry]})
    assert fragment in str(e.value)


def test_disabled_stub_is_allowed_and_duplicate_slug_rejected():
    stub = {"slug": "a", "name": "x", "kind": "telegram", "engine": "telegram", "base_url": "u"}
    assert parse_sources({"sources": [stub]})[0].enabled is False
    with pytest.raises(ConfigError, match="duplicate slug"):
        parse_sources({"sources": [stub, stub]})


def test_bad_yaml_and_missing_file(tmp_path):
    p = tmp_path / "s.yaml"
    p.write_text("sources: [unclosed", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_sources(p)
    with pytest.raises(ConfigError, match="not found"):
        load_sources(tmp_path / "nope.yaml")
