import io

from setuptools import find_packages
from setuptools import setup

with io.open("README.rst", "rt", encoding="utf8") as f:
    readme = f.read()

setup(
    name="LibraryGames",
    version="1.0.0",
    license="BSD",
    maintainer="Peter Hansen",
    maintainer_email="previsualconsent@gmail.com",
    description="Basic List of Games available at Anoka County Library",
    long_description=readme,
    packages=find_packages(),
    include_package_data=True,
    zip_safe=False,
    install_requires=["flask"],
    extras_require={"test": ["pytest", "coverage"]},
)
