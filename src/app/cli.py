"""CLI entrypoint. Run from project root as: python -m src.app.cli  or  python -m src.app"""
from .pipeline import PostgreSQLPipeline


def main():
    """Run the pipeline. Uses session_scope() for a single DB connection that is closed on exit."""
    pipeline = PostgreSQLPipeline()
    pipeline.run()


if __name__ == "__main__":
    main()
