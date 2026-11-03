import i18n
import pytest


@pytest.fixture(autouse=True)
def english_messages():
    """Run every test in English, whatever the language of the machine."""
    i18n.set_language("en")
    yield
    i18n.set_language(i18n.AUTO)
