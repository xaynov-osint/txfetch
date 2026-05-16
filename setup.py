from setuptools import setup, find_packages

setup(
    name="txfetch",
    version="1.0.0",
    description="blockchain transaction retrieval tool",
    author="xaynov",
    packages=find_packages(),
    install_requires=[
        "requests>=2.31.0",
        "prompt_toolkit>=3.0.0",
        "openpyxl>=3.1.0",
    ],
    entry_points={
        "console_scripts": [
            "txfetch=main:main",
            "txf=main:main",
        ],
    },
    python_requires=">=3.10",
)
