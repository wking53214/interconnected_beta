from beta.fingerprint import decision_fingerprint


def test_deterministic_for_identical_dicts():
    d = {"a": 1, "b": "x"}
    assert decision_fingerprint(d) == decision_fingerprint(d)


def test_key_order_does_not_matter():
    assert decision_fingerprint({"a": 1, "b": 2}) == decision_fingerprint({"b": 2, "a": 1})


def test_different_values_produce_different_fingerprints():
    assert decision_fingerprint({"a": 1}) != decision_fingerprint({"a": 2})


def test_handles_non_json_native_values_via_default_str():
    # Matches source contract (json.dumps(..., default=str)) -- objects
    # without a native JSON representation get str()-ed rather than
    # raising.
    class Weird:
        def __str__(self):
            return "weird-repr"

    fp = decision_fingerprint({"a": Weird()})
    assert isinstance(fp, str)
    assert len(fp) == 64  # sha256 hex digest length
