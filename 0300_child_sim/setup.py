#!/usr/bin/env python
import os

from setuptools import find_packages, setup

if __name__ == "__main__":
    base_dir = os.path.dirname(__file__)
    src_dir = os.path.join(base_dir, "src")

    about = {}
    with open(os.path.join(src_dir, "vivarium_gates_lsff_2026_child", "__about__.py")) as f:
        exec(f.read(), about)

    with open(os.path.join(base_dir, "README.rst")) as f:
        long_description = f.read()

    install_requirements = [
        "vivarium-gbd-mapping>=6.0.7",
        "vivarium-engine>=5.5.3",
        "vivarium-public-health>=6.4.5",
        "click",
        "jinja2",
        "loguru",
        "numpy",
        "pandas",
        "pyyaml",
        "scipy",
        "tables",
        "vivarium-config-tree>=5.0.0",
    ]

    # use "pip install -e .[dev]" to install required components + extra components
    data_requirements = ["vivarium-inputs>=8.0.2"]
    # NOTE: Do not add jobmon_installer_ihme here. It reaches this environment only as
    # a transitive dependency of vivarium-cluster-tools[cluster]; naming it directly
    # makes the build unresolvable, because the index this install step uses does not
    # carry it under that name.
    cluster_requirements = ["vivarium-cluster-tools[cluster]>=4.2.14"]
    test_requirements = [
        "vivarium-dependencies[pytest]",
        "vivarium-testing-utils",
        "papermill",
        "jupyterlab",
    ]
    validation_requirements = ["vivarium-testing-utils[validation]"]
    lint_requirements = ["vivarium-dependencies[lint]"]
    interactive_requirements = ["vivarium-dependencies[interactive]", "nbdime"]

    setup(
        name=about["__title__"],
        version=about["__version__"],
        description=about["__summary__"],
        long_description=long_description,
        license=about["__license__"],
        url=about["__uri__"],
        author=about["__author__"],
        author_email=about["__email__"],
        package_dir={"": "src"},
        packages=find_packages(where="src"),
        include_package_data=True,
        install_requires=install_requirements,
        extras_require={
            "test": test_requirements,
            "cluster": cluster_requirements,
            "data": data_requirements
            + cluster_requirements
            + lint_requirements
            + test_requirements
            + validation_requirements,
            "interactive": interactive_requirements,
            "dev": test_requirements
            + cluster_requirements
            + lint_requirements
            + interactive_requirements,
        },
        zip_safe=False,
        # NOTE: Deliberately no 'make_artifacts' console script -- see the note in
        # 0200_pregnancy_sim/setup.py. The repo-level vivarium_gates_lsff_2026
        # package owns that name and dispatches here via '-p/--project child'.
    )
