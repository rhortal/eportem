"""Where core code sends its progress messages."""


def default_say(*args, **kwargs):
    # `print` is looked up on every call, so contextlib.redirect_stdout and a
    # patched builtins.print still see the output.
    print(*args, **kwargs)
