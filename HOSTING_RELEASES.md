# Production release procedure

Production runs with source watching and fast reruns disabled. Never evict or reload shared application modules inside an active process: simultaneous session imports can fail with KeyError or retain different module identities.

For each application release, update APP_VERSION in dashboard_runtime.py, EXPECTED_RELEASE in app.py and the release comment in requirements.txt together. The requirements-file change requests a clean Streamlit Community Cloud deployment; dependency pins need not change. After merging a tested PR, verify the expected version on the public URL and inspect the production browser report. A version mismatch requires a clean hosting restart, not in-process module replacement.

Scheduled market-data refreshes continue through the existing polling and quote fragments; they do not depend on watching Python source files. Browser-local saved workspaces survive a process restart, while unsaved server-session state may reset.

The uploaded host log showed repeated importlib KeyError failures for application modules during deployments, followed by a failed health check. This fix addresses that specific failure mechanism; production verification is still required to distinguish any remaining latency or provider issue.
