from pathlib import Path

import pytest

from api_mapper.normalize.lexicon import Lexicon

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SAMPLES = PROJECT_ROOT / "samples"
FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(scope="session")
def lexicon() -> Lexicon:
    return Lexicon.load()
