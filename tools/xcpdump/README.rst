=======
xcpdump
=======

 note:  **xcpdump** is Linux/SocketCAN only.

**xcpdump** is a busmonitor similar to **candump**, but with a big difference:
The messages on the bus are represented in a human-readable form.

How-to build
------------

Run

.. code-block:: shell

   make

in the `tools/xcpdump` directory, that's it.

How-to install
--------------

The `Makefile` has no `install` target, so you have to copy the executable file manually, like:

.. code-block:: shell

   $ cp xcpdump ~/.local/bin

or wherever your personal executable files are located.

How-to use
----------

..code-block:: shell
