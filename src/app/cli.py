from .pipeline import PostgreSQLPipeline

def main():
    pipeline = PostgreSQLPipeline()
    pipeline.run()

if __name__ == "__main__":
    main()
