"""The clock engine, with no global state.

Nothing in this package reads environment variables, config files or the
current directory: every setting is an argument. Progress messages go through
a `say` callable (default: print), so a caller running several users at once
can give each run its own log instead of sharing stdout.
"""
