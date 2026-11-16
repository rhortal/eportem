"""Prefix every output line with HH:MM:SS, so cron mails and logs show timing."""
import datetime
import sys


class TimestampedStream:
    """Wraps a text stream. Writes may be partial or hold several lines: the
    prefix goes only at the start of a line, and a line cut over two writes
    gets one prefix."""

    def __init__(self, stream, clock=datetime.datetime.now):
        self._stream = stream
        self._clock = clock
        self._at_line_start = True

    def write(self, text):
        out = []
        for piece in text.splitlines(keepends=True):
            if self._at_line_start:
                out.append(f"{self._clock():%H:%M:%S} ")
            out.append(piece)
            self._at_line_start = piece.endswith(("\n", "\r"))
        if out:
            self._stream.write("".join(out))
        return len(text)

    def writelines(self, lines):
        for line in lines:
            self.write(line)

    def flush(self):
        self._stream.flush()

    def __getattr__(self, name):  # isatty, encoding, fileno, ...
        return getattr(self._stream, name)


def install():
    """Timestamp sys.stdout and sys.stderr (once)."""
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name)
        if not isinstance(stream, TimestampedStream):
            setattr(sys, name, TimestampedStream(stream))
