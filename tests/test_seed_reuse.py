"""A code-only deployment should not republish identical market-data assets."""
from deployment_seed import needs_publication
from screening import SCREENER_SCHEMA


def test_first_seed_always_publishes():
    assert needs_publication(None,{})


def test_no_changed_data_reuses_previous_generation():
    assert not needs_publication({'generation':'existing','screener_schema':SCREENER_SCHEMA},{'price_attempted':0,'metadata_success':0,'metadata_failed':0})


def test_success_and_failure_state_both_publish():
    for key in ('price_attempted','metadata_success','metadata_failed'):
        assert needs_publication({'generation':'existing','screener_schema':SCREENER_SCHEMA},{key:1})


def test_new_screener_fields_republish_existing_source_records_once():
    for previous_schema in (None, SCREENER_SCHEMA - 1):
        assert needs_publication({'generation':'existing','screener_schema':previous_schema},{})
    assert not needs_publication({'generation':'rebuilt','screener_schema':SCREENER_SCHEMA},{})
