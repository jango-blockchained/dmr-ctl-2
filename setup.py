from setuptools import setup, find_packages

with open("README.md", "w") as f:
    f.write("""# DMR Controller

A Python-based Digital Media Controller for DLNA/UPnP networks that enables seamless media streaming, device discovery, and control.

## Features

- Automatic discovery of DLNA/UPnP devices on the network
- Support for media renderers and media servers
- Media playback control (play, pause, stop)
- Volume control
- User-friendly graphical interface
- Real-time device status updates

## Installation

```bash
pip install -r requirements.txt
python setup.py install
```

## Usage

To start the application:

```bash
python -m dmr_controller
```

## Requirements

- Python 3.7+
- upnpclient
- requests
- python-didl-lite
""")

setup(
    name="dmr_controller",
    version="0.1.0",
    description="Digital Media Controller for DLNA/UPnP networks",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    author="DMR Controller Team",
    packages=find_packages(),
    install_requires=[
        "upnpclient>=1.0.3",
        "requests>=2.31.0",
        "python-didl-lite>=1.3.1",
    ],
    python_requires=">=3.7",
    entry_points={
        "console_scripts": [
            "dmr-controller=dmr_controller.__main__:main",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: End Users/Desktop",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Topic :: Multimedia :: Sound/Audio",
        "Topic :: Multimedia :: Video",
        "Topic :: Home Automation",
    ],
)
