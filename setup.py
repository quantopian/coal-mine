from pathlib import Path
from setuptools import setup, find_packages


setup(
    name="coal_mine",
    version='0.7.1',
    author='Jonathan Kamens',
    author_email='jik+coalmine@kamens.us',
    description="Coal Mine - Periodic task execution monitor",
    url='https://github.com/quantopian/coal-mine',
    long_description=(Path(__file__).parent / 'README.md').read_text(),
    long_description_content_type='text/markdown',
    license='Apache 2.0',
    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'Intended Audience :: System Administrators',
        'License :: OSI Approved :: Apache Software License',
        'Natural Language :: English',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3 :: Only',
        'Topic :: Internet :: WWW/HTTP :: WSGI :: Server',
        'Topic :: System :: Monitoring',
        'Topic :: System :: Systems Administration',
    ],
    packages=find_packages(),
    # Once this goes to 3.11, we can get rid of the shenanigans for getting UTC
    # from datetime.timezone instead of directly from datetime.UTC.
    python_requires='>=3.8',
    install_requires=open('requirements.txt').read(),
    entry_points={
        'console_scripts': [
            "coal-mine = coal_mine.server:main",
            "cmcli = coal_mine.cli:main"
        ]
    },
    zip_safe=True,
)
