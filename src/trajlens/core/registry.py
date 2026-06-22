class Registry:
    """Dict-with-a-duplicate-guard. Extension points are registries (design §5.3)."""

    def __init__(self):
        self._d: dict = {}

    def register(self, key: str, value):
        if key in self._d:
            raise KeyError(f"duplicate registration: {key}")
        self._d[key] = value
        return value

    def get(self, key):
        return self._d[key]

    def items(self):
        return list(self._d.items())

    def keys(self):
        return list(self._d.keys())

    def __contains__(self, key):
        return key in self._d
