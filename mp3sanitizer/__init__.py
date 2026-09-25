"""Mp3Sanitizer: inventariseren, opschonen en hernoemen van een muziekcollectie."""

try:
    from mp3sanitizer._version import __version__
except ImportError:  # pragma: no cover - alleen zonder build/installatie
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
