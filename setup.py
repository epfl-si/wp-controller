from setuptools import (
    find_packages,
    setup,
)

setup(
    name="wp-controller",
    version="0.0.1",
    description="A Kubernetes controller for generating Nginx Ingress configurations based on WordPress custom resources.",
    url="https://github.com/epfl-si/wp-controller",
    packages=find_packages(),
)
