"""Stock Research Workspace release 2026-09-11.13; Streamlit entrypoint."""
import dashboard_runtime as runtime


def __getattr__(name):
    return getattr(runtime, name)


if __name__ == '__main__':
    from dashboard_ui import main
    main()
