"""Stock Research Workspace release 2026-09-11.16; single-page entrypoint."""
import dashboard_runtime as runtime

EXPECTED_RELEASE = '2026-09-11.16'


def __getattr__(name):
    return getattr(runtime, name)


if __name__ == '__main__':
    from workspace_boot import ensure_release
    runtime, ui = ensure_release(EXPECTED_RELEASE)
    ui.main()
