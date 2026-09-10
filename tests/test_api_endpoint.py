"""Regression: repository metadata must not use a trailing slash."""
from github_store import GitHubReleaseStore
from test_github_store import FakeGitHub

def test_repository_metadata_uses_canonical_endpoint():
    api = FakeGitHub()
    store = GitHubReleaseStore({'DASHBOARD_DATA_REPO': api.repo, 'DASHBOARD_GITHUB_TOKEN': 'writer', 'DASHBOARD_DATA_VISIBILITY': 'private'}, session=api)
    store._verify_repository()
    assert api.calls[0] == ('GET', '')
    assert store.verified
