def clean_text(text):
    if not text:
        return ""
    return " ".join(str(text).split())


def val(x, missing="NULL"):
    if x is None:
        return missing
    s = str(x).strip()
    return s if s else missing
