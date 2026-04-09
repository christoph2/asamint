"""Sphinx configuration for asamint documentation."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asamint  # noqa: E402

# -- General configuration ---------------------------------------------

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx.ext.intersphinx",
]

templates_path = ["_templates"]
source_suffix = ".rst"
master_doc = "index"

project = "asamint"
copyright = "2020–2026, Christoph Schueler"
author = "Christoph Schueler"

version = asamint.__version__
release = asamint.__version__

language = "en"
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]
pygments_style = "sphinx"

# -- Napoleon settings -------------------------------------------------

napoleon_google_docstring = True
napoleon_numpy_docstring = True
napoleon_include_init_with_doc = True

# -- Options for HTML output -------------------------------------------

html_theme = "alabaster"

# -- Options for HTMLHelp output ---------------------------------------

htmlhelp_basename = "asamintdoc"

# -- Intersphinx -------------------------------------------------------

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "numpy": ("https://numpy.org/doc/stable/", None),
}
