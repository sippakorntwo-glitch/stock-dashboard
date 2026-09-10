"""A code-only deployment should not republish identical market-data assets."""
from deployment_seed import needs_publication


def test_first_seed_always_publishes():
    assert needs_publication(None,{})


def test_no_changed_data_reuses_previous_generation():
    assert not needs_publication({'generation':'existing'},{'price_attempted':0,'metadata_success':0,'metadata_failed':0})


def test_success_and_failure_state_both_publish():
    for key in ('price_attempted','metadata_success','metadata_failed'):
        assert needs_publication({'generation':'existing'},{key:1})
