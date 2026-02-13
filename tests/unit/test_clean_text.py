from src.app.main import clean_text

def test_clean_text_none():
    assert clean_text(None) == ""

def test_clean_text_collapses_spaces():
    assert clean_text("  hello   world \n") == "hello world"
