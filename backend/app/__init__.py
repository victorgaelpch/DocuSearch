"""Application core and modules."""

from importlib.metadata import PackageNotFoundError, version as _version

try:
    __version__ = _version("docusearch-ai")
except PackageNotFoundError:  # ejecución sin instalar el paquete
    __version__ = "1.0.0"
