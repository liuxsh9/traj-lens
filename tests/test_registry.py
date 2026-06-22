import pytest

from trajlens.core.registry import Registry


def test_register_and_get():
    r = Registry()
    r.register("a", 1)
    assert r.get("a") == 1
    assert "a" in r
    assert r.keys() == ["a"]


def test_duplicate_rejected():
    r = Registry()
    r.register("a", 1)
    with pytest.raises(KeyError):
        r.register("a", 2)
