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


Please refer to `examples <../asamint/examples>`_ directory.


Further Readings
----------------

`Here's <further_readings.rst>`_ a collection of some public accessible documents, if you want to dig deeper into the wonderworld of automotive measurement and calibration.


Miscellaneous
-------------

**asamint** includes some more or less useful `tools <../tools/README.rst>`_.
