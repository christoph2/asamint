.. _index:

asamint — ASAM Integration Package
====================================

.. image:: https://github.com/christoph2/asamint/actions/workflows/pythonapp.yml/badge.svg
   :target: https://github.com/christoph2/asamint/actions/workflows/pythonapp.yml
   :alt: CI Status

.. image:: https://img.shields.io/pypi/v/asamint.svg
   :target: https://pypi.org/project/asamint/
   :alt: PyPI Version

.. image:: https://img.shields.io/pypi/pyversions/asamint.svg
   :target: https://pypi.org/project/asamint/
   :alt: Python Versions

.. image:: https://codecov.io/gh/christoph2/asamint/branch/master/graph/badge.svg
   :target: https://codecov.io/gh/christoph2/asamint
   :alt: Coverage

.. image:: http://img.shields.io/badge/license-GPL-blue.svg
   :target: http://opensource.org/licenses/GPL-2.0
   :alt: License

----

**asamint** is a Python library that integrates several ASAM-related open-source
projects into a cohesive high-level API for automotive measurement and calibration
(MCS) workflows.

.. note::

   All public symbols are imported from :mod:`asamint.api`.  Never import from
   deep internal paths — they may change without notice.

.. code-block:: python

   from asamint.api import open_project, load_all_characteristics, export_to_cdf

   with open_project() as mc:
       params = load_all_characteristics(mc)
       cdf_path = export_to_cdf(mc=mc, parameters=params)
       print(f"Written to {cdf_path}")

----

.. toctree::
   :maxdepth: 1
   :caption: 🚀 Getting Started

   getting_started
   README

.. toctree::
   :maxdepth: 2
   :caption: 📖 User Guide

   user_guide/index

.. toctree::
   :maxdepth: 2
   :caption: 🏛️ Architecture

   architecture

.. toctree::
   :maxdepth: 2
   :caption: 📚 API Reference

   api/index

.. toctree::
   :maxdepth: 1
   :caption: 🔖 Project

   contributing
   history
   authors
   further_readings

----

Indices and tables
------------------

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
