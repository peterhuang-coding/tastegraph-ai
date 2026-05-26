class TasteGraphError(Exception):
    """Base error for TasteGraph AI."""


class SourceNotFoundError(TasteGraphError):
    """Source not found in repository."""


class ImageNotFoundError(TasteGraphError):
    """Image not found in repository."""


class PackNotFoundError(TasteGraphError):
    """Daily pack not found in repository."""


class TaskNotFoundError(TasteGraphError):
    """Task not found in repository."""


class DuplicateSourceError(TasteGraphError):
    """Source URL already exists."""


class GraphIntegrityError(TasteGraphError):
    """Graph constraint violation (e.g. duplicate edge, invalid node type)."""
