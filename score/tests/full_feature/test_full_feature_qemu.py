
def test_whatever(target):
    exit_code, output = target.execute("echo 'Hello from target!'")
    assert exit_code == 0
    assert b"Hello from target!" in output


def test_whatelse(target):
    exit_code, output = target.execute("echo 'Hello from foo!'")
    assert exit_code == 0
    assert b"Hello from boo!" in output
