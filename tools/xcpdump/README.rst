=======
xcpdump
=======

 note:  **xcpdump** is Linux/SocketCAN only.

**xcpdump** is a busmonitor similar to **candump**, but with a big difference:
The messages on the bus are represented in a human-readable form.

How-to build
------------

Depending on your Linux distribution, you may need to install a **linux-headers** package.

On Debian based systems use
.. code-block:: shell

   apt-cache search linux-headers

At least **zsh** users are able to auto-complete **apt-get**
.. code-block:: shell

   sudo apt-get install linux-headers-<TAB>


Then run

.. code-block:: shell

   make

in the `tools/xcpdump` directory, that's it.

How-to install
--------------

The `Makefile` has no `install` target, so you have to copy the executable file manually, like:

.. code-block:: shell

   $ cp xcpdump ~/.local/bin

or wherever your personal executable files are located.

Usage
-----

..code-block:: shell

    Usage: xcpdump [options] <CAN interface>
    Options:
             -m <can_id>  (XCP master can_id. Use 8 digits for extended IDs)
             -s <can_id>  (XCP slave can_id. Use 8 digits for extended IDs)
             -c           (color mode)
             -t <type>    (timestamp: (a)bsolute/(d)elta/(z)ero/(A)bsolute w date)

    CAN IDs and addresses are given and expected in hexadecimal values.

