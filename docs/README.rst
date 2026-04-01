========================
ASAM Integration Package
========================

.. image:: http://img.shields.io/badge/license-GPL-blue.svg
   :target: http://opensource.org/licenses/GPL-2.0

.. image:: https://img.shields.io/badge/code%20style-black-000000.svg
    :target: https://github.com/psf/black



**asamint** (ASAM integration package) integrates several automotive related opensource projects.

The projects in question projects are mainly following an mechanism-not-policy approach, but **asamint** aims to
add higher level APIs, that could be used to implement common measurement and calibration tasks.

To put it into another words, **asamint** will be a command-line MCS (measurement and calibration system).

The aggregated Python projects in alphabetical order:

======================================================   =============
Project / repository                                     pip/PyPI name
======================================================   =============
`asammdf <https://github.com/danielhrisca/asammdf>`_     asammdf
`objutils <https://github.com/christoph2/objutils>`_     objutils
`pya2ldb <https://github.com/christoph2/pya2l>`_         pya2ldb
`pyxcp <https://github.com/christoph2/pyxcp>`_           pyxcp
======================================================   =============



And yes, all listed projects are `Raspberry PI <https://raspberrypi.org>`_ tested :smile:

Installation
------------

clone / fork / download from `here. <https://github.com/christoph2/asamint>`_

Then run

.. code-block:: python

   python setup.py develop

Dependencies
~~~~~~~~~~~~
**asamint** currently doesn't specify dependencies on its own -- installing the above listed projects should be sufficient.

License
-------
**asamint** is released under `GPLv2 license terms <../LICENSE>`_.


Features
--------

 Note: At this stage, the project is highly experimental and hacky, so don't expect stable APIs and tons of features!

Functions are basically orchestrated using ASAM MCD-2MC (A2L) files.

Some examples include (not necessarily in a working condition yet):

* Create calibration data files (ASAM CDF) from XCP slaves or HEX files.

* Setup dynamic DAQs.

* High-level API to create MDF files.


Migration & Compatibility
-------------------------

* Prefer public imports from ``asamint.api`` (Calibration/OfflineCalibration/OnlineCalibration, ParameterCache, measurement helpers, finalize_daq_csv, config snapshots) instead of deep package paths; consume pyxcp/pya2l/asammdf/objutils only through their adapters.
* CLI/config: use ``asamint.cmdline.finalize_daq_csv`` for DAQ CSV → CSV/HDF5 finalization; configuration is traitlets-based (``asamint.config``) with ``Path`` and ``configure_logging`` defaults.
* Fixtures stay under ``tests/`` (A2L/HEX/MSRSW, DAQ CSV/HDF5); external-facing formats (CDF/MDF/HDF5) remain compatible, with new helpers added behind existing facades.
* When migrating older code, update imports, replace direct adapter usage, and validate with ``poetry run pytest`` plus ``poetry run ruff check .``.

API Stability & Deprecation
---------------------------

* The stable public surface is exported from ``asamint.api``. Prefer these names in application code.
* Renamed or removed API names are kept as deprecated aliases in ``asamint.api`` and emit ``DeprecationWarning`` when accessed.
* Deprecated aliases include a removal version in ``asamint.api._DEPRECATED_ALIASES``; remove legacy usage before that version.
* If you need a new alias for migration, add it to ``asamint.api._DEPRECATED_ALIASES`` and cover it with a small test.

Please refer to `examples <../asamint/examples>`_ directory.

Measurement Formats & Registry
------------------------------

* CSV, HDF5, and MDF handling lives under ``asamint.measurement.{csv,hdf5,mdf}`` and is registered in the measurement format registry; thin shims stay at ``asamint.hdf5``/``asamint.mdf`` for compatibility.
* Custom backends can be registered without touching core code. Example (InfluxDB placeholder):

.. code-block:: python

   from pathlib import Path
   from asamint.adapters.measurement import MeasurementFormat, register_measurement_format
   from asamint import measurement

   def persist_influx(*, data, units=None, project_meta=None, output_path: str | Path | None = None, **kwargs):
       return measurement.RunResult(
           mdf_path=None,
           csv_path=None,
           hdf5_path=str(output_path) if output_path else None,
           signals={},
           timebases=None,
       )

   register_measurement_format(
       MeasurementFormat(
           name="INFLUX",
           persist=persist_influx,
           description="Persist measurements to InfluxDB",
           default_extension=".influx",
       )
   )


Further Readings
----------------

`Here's <further_readings.rst>`_ a collection of some public accessible documents, if you want to dig deeper into the wonderworld of automotive measurement and calibration.


Miscellaneous
-------------

**asamint** includes some more or less useful `tools <../tools/README.rst>`_.
