# Sphinx configuration for the model notes in docs/.

project = "vivarium_gates_lsff_2026"
author = "IHME Simulation Science"
copyright = f"2026, {author}"

extensions = ["myst_parser"]

source_suffix = {".rst": "restructuredtext", ".md": "markdown"}
master_doc = "index"
language = "en"
exclude_patterns = ["build"]

html_theme = "sphinx_rtd_theme"
