"""Compatibility facade for the shared read-only catalog."""
from ai_lib_qor.application.library_catalog import LibraryCatalog


def global_model(work, runs):
    return LibraryCatalog(work, runs).refresh().overview()


def library_model(work, runs, vendor, library):
    return LibraryCatalog(work, runs).refresh().library_detail(vendor, library)
