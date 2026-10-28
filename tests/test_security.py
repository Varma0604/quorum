from app.models import User
from app.security import hash_password, issue_token, verify_password


def test_password_hash_and_token_round_trip():
    password = "a-long-test-password"
    hashed = hash_password(password)
    assert hashed != password
    assert verify_password(password, hashed)
    assert not verify_password("wrong-password", hashed)
    user = User(id=7, email="user@example.test", password_hash=hashed)
    assert isinstance(issue_token(user), str)
