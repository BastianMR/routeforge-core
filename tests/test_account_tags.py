"""Tests for account tags and the enabled flag."""

from __future__ import annotations

import pytest

from routeforge.accounts import normalize_tags


def test_add_persists_tags(repo) -> None:
    account = repo.add(
        provider="firecrawl", label="fc1", api_key="k", tags="scrape,web"
    )
    assert account.tags == ["scrape", "web"]
    assert repo.get_by_id(account.id).tags == ["scrape", "web"]


def test_tags_default_to_empty(repo) -> None:
    account = repo.add(provider="firecrawl", label="fc1", api_key="k")
    assert account.tags == []
    assert repo.get_by_id(account.id).enabled is True


def test_list_by_tag_returns_the_expected_subset(repo) -> None:
    repo.add(provider="firecrawl", label="fc1", api_key="k", tags="scrape")
    repo.add(provider="tavily", label="tv1", api_key="k", tags="scrape,search")
    repo.add(provider="exa", label="ex1", api_key="k", tags="search")
    repo.add(provider="openai", label="oa1", api_key="k")

    labels = sorted(a.label for a in repo.list_by_tag("scrape"))
    assert labels == ["fc1", "tv1"]

    assert sorted(a.label for a in repo.list_by_tag("search")) == ["ex1", "tv1"]
    assert repo.list_by_tag("nosuchtag") == []


def test_list_by_tag_is_exact_not_a_substring(repo) -> None:
    repo.add(provider="firecrawl", label="fc1", api_key="k", tags="scrape")
    assert repo.list_by_tag("scrap") == []
    assert repo.list_by_tag("scrape") != []


def test_list_tags_is_sorted_and_deduplicated(repo) -> None:
    repo.add(provider="a", label="x", api_key="k", tags="web,scrape")
    repo.add(provider="b", label="y", api_key="k", tags="scrape,search")
    assert repo.list_tags() == ["scrape", "search", "web"]


def test_update_tags_replaces_the_list(repo) -> None:
    account = repo.add(provider="firecrawl", label="fc1", api_key="k", tags="scrape")
    assert repo.update_tags(account.id, ["alpha", "beta"]) == ["alpha", "beta"]
    assert repo.get_by_id(account.id).tags == ["alpha", "beta"]


def test_add_tags_is_a_union(repo) -> None:
    account = repo.add(provider="firecrawl", label="fc1", api_key="k", tags="scrape")
    assert repo.add_tags(account.id, "web,scrape") == ["scrape", "web"]
    assert repo.get_by_id(account.id).tags == ["scrape", "web"]


def test_remove_tags_only_drops_the_named_ones(repo) -> None:
    account = repo.add(provider="firecrawl", label="fc1", api_key="k", tags="scrape,web")
    assert repo.remove_tags(account.id, "scrape") == ["web"]
    assert repo.get_by_id(account.id).tags == ["web"]


def test_tags_on_missing_account_raise(repo) -> None:
    with pytest.raises(KeyError):
        repo.update_tags(999, ["x"])
    with pytest.raises(KeyError):
        repo.add_tags(999, "x")
    with pytest.raises(KeyError):
        repo.remove_tags(999, "x")


def test_set_enabled_and_toggle(repo) -> None:
    account = repo.add(provider="firecrawl", label="fc1", api_key="k")
    assert repo.set_enabled(account.id, False) is False
    assert repo.get_by_id(account.id).enabled is False
    assert repo.toggle_enabled(account.id) is True
    assert repo.get_by_id(account.id).enabled is True


def test_toggle_on_missing_account_raises(repo) -> None:
    with pytest.raises(KeyError):
        repo.toggle_enabled(999)
    with pytest.raises(KeyError):
        repo.set_enabled(999, True)


def test_account_info_exposes_tags_and_enabled(repo) -> None:
    repo.add(provider="firecrawl", label="fc1", api_key="k", tags="scrape")
    (info,) = repo.list_all()
    assert info.tags == ["scrape"]
    assert info.enabled is True


def test_api_key_never_appears_in_account_info(repo) -> None:
    repo.add(provider="firecrawl", label="fc1", api_key="super-secret")
    dumped = repo.list_all()[0].model_dump()
    assert "super-secret" not in str(dumped)
    assert "api_key" not in dumped


def test_get_by_label(repo) -> None:
    repo.add(provider="firecrawl", label="fc1", api_key="k")
    assert repo.get_by_label("fc1") is not None
    assert repo.get_by_label("nope") is None


def test_upsert_on_same_provider_label_replaces_tags(repo) -> None:
    repo.add(provider="firecrawl", label="fc1", api_key="k1", tags="scrape")
    account = repo.add(provider="firecrawl", label="fc1", api_key="k2", tags="web")
    assert account.tags == ["web"]
    assert len(repo.list_by_provider("firecrawl")) == 1


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, []),
        ("", []),
        ("scrape", ["scrape"]),
        ("scrape,web", ["scrape", "web"]),
        (" scrape , web ", ["scrape", "web"]),
        ("scrape,scrape", ["scrape"]),
        (["a", "b", "a"], ["a", "b"]),
        ("scrape,,web", ["scrape", "web"]),
    ],
)
def test_normalize_tags(raw, expected) -> None:
    assert normalize_tags(raw) == expected
