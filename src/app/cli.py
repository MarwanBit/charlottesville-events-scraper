from app.client import create_session
from app.pipeline import run_pipeline

def main():
    session = create_session()
    run_pipeline(session)

if __name__ == "__main__":
    main()
