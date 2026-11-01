"""Setup for orchestrator package."""

from setuptools import setup, find_packages

setup(
    name="orchestrator",
    version="0.1.0",
    description="Integration layer for Metadata-Pipeline and graph-doc-gen",
    packages=find_packages(),
    python_requires=">=3.9",
)
