"""Routine that explores the `logging` hierarchy and builds a `Node` tree."""

import logging

def tree():
    """Return a tree of tuples representing the logger layout.

    Each tuple looks like ``('logger-name', <Logger>, [...])`` where the
    third element is a list of zero or more child tuples that share the
    same layout.

    """
    root = ('', logging.root, [])
    nodes = {}
    # See https://stackoverflow.com/questions/61683713/why-does-mypy-complain-typelogger-has-no-attribute-manager
    items = list(logging.root.manager.loggerDict.items())  # pytype: disable=attribute-error
    items.sort()
    for name, logger in items:
        nodes[name] = node = (name, logger, [])
        i = name.rfind('.', 0, len(name) - 1)  # same formula used in `logging`
        if i == -1:
            parent = root
        else:
            parent = nodes[name[:i]]
        parent[2].append(node)
    return root
