from mps_fixture_native import add


def test_native_api():
    assert add(2, 3) == 5
