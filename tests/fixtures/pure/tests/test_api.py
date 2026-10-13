from mps_fixture_pure import add


def test_public_api():
    assert add(2, 3) == 5
