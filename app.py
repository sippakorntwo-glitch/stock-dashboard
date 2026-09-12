"""Stock Research Workspace release 2026-09-12.25; single-page entrypoint."""
import dashboard_runtime as runtime

EXPECTED_RELEASE = '2026-09-12.25'


def __getattr__(name):
    return getattr(runtime, name)


if __name__ == '__main__':
    from workspace_boot import ensure_release
    runtime, ui = ensure_release(EXPECTED_RELEASE)
    ui.main()
