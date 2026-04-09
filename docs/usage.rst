=====
Usage
=====

Installation
------------

Install from source using `Poetry <https://python-poetry.org/>`_::

    git clone https://github.com/christoph2/asamint.git
    cd asamint
    poetry install

Quick Start
-----------

All public symbols are available from ``asamint.api``:

.. code-block:: python

    from asamint.api import OfflineCalibration

    cal = OfflineCalibration("CDF20demo.a2l", "CDF20demo.hex")
    value = cal.load_value("KfRpmEngSp_Trq")
    print(value)

Configuration
-------------

asamint uses a traitlets-based configuration system.
Create an ``asamint_conf.py`` in your project directory:

.. code-block:: python

    c.General.loglevel = "INFO"
    c.General.a2l_file = "path/to/file.a2l"
    c.General.hex_file = "path/to/file.hex"

See :mod:`asamint.config` for all configuration options.

API Stability & Deprecation
----------------------------

The stable public surface is exported from ``asamint.api``. When names change,
the old name remains available as a deprecated alias and emits
``DeprecationWarning``. See :doc:`readme` for the full policy and migration
guidelines.
