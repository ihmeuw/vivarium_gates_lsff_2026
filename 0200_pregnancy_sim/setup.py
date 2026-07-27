#!/usr/bin/env python
import os

from setuptools import find_packages, setup

if __name__ == "__main__":
    base_dir = os.path.dirname(__file__)
    src_dir = os.path.join(base_dir, "src")

    about = {}
    with open(
        os.path.join(src_dir, "vivarium_gates_lsff_by_wealth_quintile", "__about__.py")
    ) as f:
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
    ]

    # use "pip install -e .[dev]" to install required components + extra components
    data_requirements = ["vivarium-inputs[data]>=8.0.2"]
    cluster_requirements = ["vivarium-cluster-tools>=4.2.14"]
    test_requirements = ["pytest"]

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
            "data": data_requirements + cluster_requirements,
            "dev": test_requirements + cluster_requirements,
        },
        zip_safe=False,
        entry_points="""
            [console_scripts]
            make_artifacts=vivarium_gates_lsff_by_wealth_quintile.tools.cli:make_artifacts
        """,
    )
