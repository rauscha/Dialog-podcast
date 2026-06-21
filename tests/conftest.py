import sys
from pathlib import Path
import pytest

# Make generate_podcast importable when tests run from repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class _FakeBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _FakeResponse:
    def __init__(self, text):
        self.content = [_FakeBlock(text)]


class FakeAnthropic:
    """Minimal stand-in for anthropic.Anthropic.

    Feed it a list of response strings (FIFO). Each call to
    messages.create() pops the next one. Records every call's kwargs
    in .calls for assertions.
    """

    def __init__(self, responses=None):
        self._responses = list(responses or [])
        self.calls = []

        outer = self

        class _Messages:
            def create(self, **kwargs):
                outer.calls.append(kwargs)
                if not outer._responses:
                    raise AssertionError("FakeAnthropic ran out of queued responses")
                return _FakeResponse(outer._responses.pop(0))

        self.messages = _Messages()

    def queue(self, text):
        self._responses.append(text)


@pytest.fixture
def fake_client():
    return FakeAnthropic()
