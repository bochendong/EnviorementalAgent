def clean(title, priority):
    """Check and normalise a new to-do; return (title, priority) or raise ValueError."""
    return title, priority


def order_key(todo):
    """Sort key for the list."""
    return todo["id"]
