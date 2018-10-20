import sys
from setuptools import setup, find_packages

if sys.version_info[0] < 3:
    sys.exit("This package does not work with Python 2.")


# You can't just put `from pypandoc import convert` at the top of your
# setup.py and then put `description=convert("README.md", "rst")` in
# your `setup()` invocation, because even if you list list `pypandoc`
# in `setup_requires`, it won't be interpreted and installed until
# after the keyword argument values of the `setup()` invocation have
# been evaluated. Therefore, we define a `lazy_convert` class which
# impersonates a string but doesn't actually import or use `pypandoc`
# until the value of the string is needed. This defers the use of
# `pypandoc` until after setuptools has figured out that it is needed
# and made it available.
class lazy_convert(object):
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

    def __str__(self):
        from pypandoc import convert
        return str(convert(*self.args, **self.kwargs))

    def __repr__(self):
        return repr(str(self))

    def split(self, *args, **kwargs):
        return str(self).split(*args, **kwargs)

    def replace(self, *args, **kwargs):
        return str(self).replace(*args, **kwargs)


setup(
    name="coal_mine",
    version='0.4.17',
    author='Quantopian Inc.',
    author_email='opensource@quantopian.com',
    description="Coal Mine - Periodic task execution monitor",
    url='https://github.com/quantopian/coal-mine',
    long_description=lazy_convert('README.md', 'rst'),
    license='Apache 2.0',
    classifiers=[
        'Development Status :: 3 - Alpha',
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
    setup_requires=['pypandoc'],
    install_requires=open('requirements.txt').read(),
    entry_points={
        'console_scripts': [
            "coal-mine = coal_mine.server:main",
            "cmcli = coal_mine.cli:main"
        ]
    },
    zip_safe=True,
)
