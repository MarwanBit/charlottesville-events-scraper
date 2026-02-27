from models import Base, engine

# Create tables; always dispose engine so connection is released
try:
    Base.metadata.create_all(bind=engine)
    print("Tables created")
finally:
    engine.dispose()
