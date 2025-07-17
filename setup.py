from setuptools import setup, find_packages
from pathlib import Path

# Read the contents of README file
this_directory = Path(__file__).parent
long_description = (this_directory / "README.md").read_text(encoding='utf-8')

setup(
    name='edx-downloader',
    version='2.0.0',
    description='Modern CLI downloader for EDX video courses with updated APIs and improved reliability.',
    long_description=long_description,
    long_description_content_type='text/markdown',
    author='Rehmat Alam',
    author_email='contact@rehmat.works',
    url='https://github.com/rehmatworks/edx-downloader',
    license='MIT',
    packages=find_packages(),
    python_requires='>=3.8',
    entry_points={
        'console_scripts': [
            'edxdl = edx_downloader.cli:main',
        ],
    },
    install_requires=[
        'beautifulsoup4>=4.12.0',
        'requests>=2.31.0',
        'lxml>=4.9.0',
        'tqdm>=4.65.0',
        'click>=8.1.0',
        'validators>=0.22.0',
        'python-slugify>=8.0.0',
        'keyring>=24.0.0',
        'cryptography>=41.0.0',
        'aiohttp>=3.9.0',
        'aiofiles>=24.1.0',
        'rich>=13.7.0',
    ],
    extras_require={
        'dev': [
            'pytest>=7.4.0',
            'pytest-cov>=4.1.0',
            'black>=23.7.0',
            'flake8>=6.0.0',
            'mypy>=1.5.0',
            'pre-commit>=3.3.0',
        ],
    },
    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: End Users/Desktop',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'Programming Language :: Python :: 3.12',
        'Topic :: Education',
        'Topic :: Internet :: WWW/HTTP',
        'Topic :: Multimedia :: Video',
    ],
    keywords='edx education video downloader cli course',
)