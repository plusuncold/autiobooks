from setuptools import setup, find_packages

setup(
    name='autiobooks',
    version='1.0.3',
    packages=find_packages(),
    install_requires=[
    ],
    author='David Nesbitt',
    description='Automatically convert epubs to audiobooks',
    long_description=open('README.md').read(),
    long_description_content_type='text/markdown',
    url='https://github.com/plusuncold/autiobooks',
    classifiers=[
        'Programming Language :: Python :: 3',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
    ],
    python_requires='>=3.10',
)