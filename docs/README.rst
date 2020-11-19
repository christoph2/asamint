========================
ASAM Integration Package
========================


.. image:: https://img.shields.io/pypi/v/asamint.svg
        :target: https://pypi.python.org/pypi/asamint


**asamint** (ASAM integration package), as the name implies, integrates several automotive related (ASAM standards)

To put it into another words, **asamint** aims to be a command-line MCS (measurement and calibration system).

These (The projects in question) projects are mainly following an mechanism-not-policy approach, but **asamint** aims to
add higher layers, which could more or less directly be used to implement common measurement and calibration tasks.

The projects in alphabetical order:

======================================================   =============
Project / repository                                     pip/PyPI name
======================================================   =============
`asammdf <https://github.com/danielhrisca/asammdf>`_     asammdf
`objutils <https://github.com/christoph2/objutils>`_     objutils
`pya2ldb <https://github.com/christoph2/pya2l>`_         pya2ldb
`pyxcp <https://github.com/christoph2/pyxcp>`_           pydbc
======================================================   =============



And yes, all listed projects are `Raspberry PI <https://raspberrypi.org>`_ tested :smile:

Installation
------------

`clone / fork / download from here. <https://github.com/christoph2/asamint>`_

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

Further Readings
----------------

`Here's <further_readings.rst>`_ a collection of some public accessible documents, if you want to dig deeper into the wonderworld of automotive measurement and calibration.


Miscellaneous
-------------

**asamint** includes some more or less useful `tools <../tools/README.rst>`_.

