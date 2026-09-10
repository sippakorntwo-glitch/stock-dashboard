"""Streamlit entrypoint; data collection imports the runtime, not the UI."""
import dashboard_runtime as runtime

def __getattr__(name):
    return getattr(runtime, name)

if __name__ == '__main__':
    from dashboard_ui import main
    main()
