.. highlight:: shell

============
Contributing
============

Contributions are welcome, and they are greatly appreciated! Every little bit
helps, and credit will always be given.

You can contribute in many ways:

Types of Contributions
----------------------

Report Bugs
~~~~~~~~~~~

Report bugs at https://github.com/christoph2/asamint/issues.

If you are reporting a bug, please include:

* Your operating system name and version.
* Any details about your local setup that might be helpful in troubleshooting.
* Detailed steps to reproduce the bug.

Fix Bugs
~~~~~~~~

Look through the GitHub issues for bugs. Anything tagged with "bug" and "help
wanted" is open to whoever wants to implement it.

Implement Features
~~~~~~~~~~~~~~~~~~

Look through the GitHub issues for features. Anything tagged with "enhancement"
and "help wanted" is open to whoever wants to implement it.

Write Documentation
~~~~~~~~~~~~~~~~~~~

asamint could always use more documentation, whether as part of the
official docs, in docstrings, or even on the web in blog posts,
articles, and such.

Submit Feedback
~~~~~~~~~~~~~~~

The best way to send feedback is to file an issue at https://github.com/christoph2/asamint/issues.

If you are proposing a feature:

* Explain in detail how it would work.
* Keep the scope as narrow as possible, to make it easier to implement.
* Remember that this is a volunteer-driven project, and that contributions
  are welcome :)

Get Started!
------------

Ready to contribute? Here's how to set up ``asamint`` for local development.

1. Fork the ``asamint`` repo on GitHub.

2. Clone your fork locally::

    $ git clone git@github.com:your_name_here/asamint.git

3. Install your local copy into a virtual environment using Poetry::

    $ cd asamint/
    $ poetry install

   This installs all runtime **and** development dependencies (pytest, ruff,
   mypy, bandit, sphinx, …) into an isolated virtual environment.

4. Install the pre-commit hooks so they run automatically before each commit::

    $ poetry run pre-commit install

5. Create a branch for local development::

    $ git checkout -b name-of-your-bugfix-or-feature

   Now you can make your changes locally.

6. When you're done making changes, run the full quality suite::

    $ poetry run ruff check .               # lint
    $ poetry run ruff format .              # format (auto-fix)
    $ poetry run mypy asamint/              # type checking
    $ poetry run bandit -r asamint/ -c bandit.yml -q   # security scan
    $ poetry run pytest                     # tests + coverage
    $ poetry run sphinx-build docs/ docs/_build/html -W  # docs

   You can also run all of the above via pre-commit::

    $ poetry run pre-commit run --all-files

7. Commit your changes and push your branch to GitHub::

    $ git add .
    $ git commit -m "feat: your detailed description of your changes."
    $ git push origin name-of-your-bugfix-or-feature

8. Submit a pull request through the GitHub website.

Pull Request Guidelines
-----------------------

Before you submit a pull request, check that it meets these guidelines:

1. **Tests**: The pull request must include tests.  Place new test fixtures
   under ``tests/`` and register shared fixtures in ``tests/conftest.py``
   instead of duplicating them across test modules.

2. **Documentation**: If the pull request adds public API, add a docstring
   and update ``docs/api.rst`` or ``docs/usage.rst``.  Put new public
   functions into a function with a complete docstring.

3. **API stability**: If you rename or remove a public API symbol, add a
   deprecated alias in ``asamint.api._DEPRECATED_ALIASES`` and cover it in
   ``tests/test_api_stability.py`` (see lines 105–107 in this file).

4. **Python versions**: The pull request must work for Python 3.10 and newer.
   The CI matrix covers Python 3.10–3.13 on Ubuntu, Windows, and macOS.

5. **Adapter boundary**: External libraries (``pya2l``, ``pyxcp``,
   ``objutils``, ``asammdf``) must **only** be imported inside
   ``asamint/adapters/``.  Production code and tests must use the adapter
   re-exports (e.g. ``from asamint.adapters.a2l import inspect``).

6. **No global side-effects**: Library modules must not call
   ``sys.setrecursionlimit()``, ``logging.basicConfig()``, or similar
   process-wide mutations at module level.

7. **CI must pass**: All jobs in ``.github/workflows/pythonapp.yml`` must be
   green — this includes ``quality`` (lint, format, mypy, bandit, pre-commit)
   and ``test`` (pytest with coverage on all platforms).

Architecture Conventions
------------------------

Adapter Layer
~~~~~~~~~~~~~

``asamint/adapters/`` is the **only** place that may import external libraries
directly:

.. code-block:: text

    asamint/adapters/
        a2l.py        ← pya2l imports
        xcp.py        ← pyxcp imports
        objutils.py   ← objutils imports
        mdf.py        ← asammdf imports
        parsers.py    ← antlr4 / parserlib imports

All other modules (including tests) must import these symbols from the adapter
modules.  Examples::

    # ✅ correct
    from asamint.adapters.a2l import inspect, model, open_a2l_database
    from asamint.adapters.objutils import load, Image

    # ❌ wrong — breaks the adapter boundary
    import pya2l
    from objutils import load

Public API
~~~~~~~~~~

External users import everything from ``asamint.api``::

    from asamint.api import Calibration, OfflineCalibration, export_to_cdf

Never expose internal symbols at the top-level without routing them through
``asamint.api`` first.

Testing Strategy
----------------

- Default commands::

    $ poetry run pytest                               # full test suite
    $ poetry run pytest --cov=asamint --cov-report=term-missing  # with coverage
    $ poetry run pytest tests/test_calibration.py -v  # single module
    $ poetry run pytest -k "test_load" --tb=short      # keyword filter

- Test layers:

  - **Core/unit** (``asamint.core``): fast, parametrized, no external I/O.
  - **Adapter tests**: use mocks/fakes; never hit real hardware or the network.
    External libraries stay behind the adapter boundary.
  - **Calibration/measurement integration**: reuse fixtures under
    ``tests/*.a2l`` / ``*.hex`` / ``*.msrswdb`` — **do not move them**.
    Shared fixtures live in ``tests/conftest.py``;
    use ``calibration_context``, ``hex_image``, ``cdf20demo_session``, etc.
  - **API surface** (``tests/test_api_stability.py``): imports only from
    ``asamint.api``; validates all ``__all__`` exports and deprecation hooks.

- General rules:

  * No network/hardware calls in tests.
  * Use ``pathlib.Path``, never ``os.path``.
  * Raise and catch project-specific exceptions from ``asamint.core.exceptions``.
  * Log via ``asamint.core.logging.configure_logging``, never ``print()``.

Tips
----

Run the full quality gate (same as CI) in a single command::

    $ poetry run pre-commit run --all-files

Build the HTML documentation locally::

    $ poetry run sphinx-build docs/ docs/_build/html -W

Deploying (maintainers only)
----------------------------

1. Make sure all changes are committed, including an entry in ``HISTORY.rst``.

2. Bump the version with ``bumpver``::

    $ poetry run bumpver update --patch   # or --minor / --major

   This updates ``pyproject.toml`` and ``asamint/version.py`` in one commit.

3. Push the commit and create a tag::

    $ git push
    $ git tag v0.2.3          # use the new version
    $ git push --tags

   The CI pipeline will automatically build wheels + sdist and publish to
   PyPI via OIDC Trusted Publisher when a version tag is pushed.
