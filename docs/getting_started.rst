.. _getting_started:

Getting Started
===============

Requirements
------------

* Python **3.10 or newer**
* `Poetry <https://python-poetry.org/>`_ (recommended) **or** pip

Installation
------------

From PyPI
~~~~~~~~~

.. code-block:: bash

   pip install asamint

From source (recommended for development)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

   git clone https://github.com/christoph2/asamint.git
   cd asamint
   poetry install

This installs all runtime *and* development dependencies (pytest, ruff, mypy, sphinx, …).

.. tip::

   After cloning, activate the pre-commit hooks once::

       poetry run pre-commit install

Verify the installation
~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   import asamint
   print(asamint.__version__)   # e.g. 0.2.2

Project setup
-------------

asamint uses a **traitlets-based configuration file** named ``asamint_conf.py``.
Create one in your project directory:

.. code-block:: python
   :caption: asamint_conf.py

   # Minimal project configuration
   c.General.project     = "MyProject"
   c.General.a2l_file    = "path/to/description.a2l"
   c.General.master_hexfile      = "path/to/calibration.hex"
   c.General.master_hexfile_type = "ihex"   # or "srec"

   # Optional: link an existing pyxcp config for online (hardware) use
   c.General.pyxcp_config_file = "pyxcp_conf.py"

See :ref:`config_reference` for the full list of options.

Your first offline calibration
-------------------------------

The following example reads every calibration parameter from a HEX file
and exports it to an ASAM CDF 2.0 XML file — all in six lines:

.. code-block:: python

   from asamint.api import open_project, load_all_characteristics, export_to_cdf

   with open_project("asamint_conf.py") as mc:
       params = load_all_characteristics(mc)
       for name, val in params["VALUE"].items():
           print(f"{name:40s} = {val.phys}")
       cdf_path = export_to_cdf(mc=mc, parameters=params)
   print(f"CDF exported to: {cdf_path}")

Your first measurement run
---------------------------

A skeleton for an online measurement session over XCP:

.. code-block:: python

   from asamint.api import open_project, run_measurement, build_daq_lists

   with open_project("asamint_conf.py") as mc:
       daq = build_daq_lists(mc, group="AllSignals")
       result = run_measurement(mc, daq_lists=daq, duration_s=5.0)
   print(f"MDF written to: {result.mdf_path}")

.. seealso::

   * :ref:`offline_calibration` — step-by-step calibration guide
   * :ref:`measurement_guide` — measurement and DAQ guide
   * :ref:`data_formats` — CDF / CVX / DCM import & export
   * :ref:`config_reference` — complete configuration reference
