#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Raw XCP traffic recorder.

Data is stored in LZ4 compressed containers.

Examples
--------

See

- `https://github.com/christoph2/asamint/xcp.__init__.py`_ for recording / writing

-  `https://github.com/christoph2/asamint/scripts/xcp_log.py`_ for reading / exporting.
"""

__copyright__ = """
   pySART - Simplified AUTOSAR-Toolkit for Python.

   (C) 2020-2021 by Christoph Schueler <cpu12.gems.googlemail.com>

   All Rights Reserved

   This program is free software; you can redistribute it and/or modify
   it under the terms of the GNU General Public License as published by
   the Free Software Foundation; either version 2 of the License, or
   (at your option) any later version.

   This program is distributed in the hope that it will be useful,
   but WITHOUT ANY WARRANTY; without even the implied warranty of
   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
   GNU General Public License for more details.

   You should have received a copy of the GNU General Public License along
   with this program; if not, write to the Free Software Foundation, Inc.,
   51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

   s. FLOSS-EXCEPTION.txt
"""

import bisect
from collections import namedtuple
import enum
import mmap
from multiprocessing import Event, Process, Pool, Queue, cpu_count
import os
import pathlib
from pprint import pprint
import struct

import lz4.block as lz4block


FILE_EXTENSION = ".xmraw"   # XCP Measurement / raw data.

MAGIC = b'ASAMINT::XCP_RAW'

FILE_HEADER_STRUCT = struct.Struct("<{:d}sHHHLLLL".format(len(MAGIC)))
FileHeader = namedtuple("FileHeader", "magic hdr_size version options num_containers record_count size_compressed size_uncompressed") #

CONTAINER_HEADER_STRUCT = struct.Struct("<LLL")
ContainerHeader = namedtuple("ContainerHeader", "record_count size_compressed size_uncompressed")

DAQ_RECORD_STRUCT = struct.Struct("<BHdL")
DAQRecord = namedtuple("DAQRecord", "category counter timestamp payload")


def struct_byte_order_prefix(byte_order: str) -> str:
    """Get byte order prefix needed for struct (un)packing.

    Parameters
    ----------
    byte_order: str
        "INTEL" or "MOTOROLA" (s. `pyxcp.types.ByteOrder`).

    Returns
    -------
    str
        "<" or ">"
    """
    return "<" if byte_order == "INTEL" else ">"


class XcpLogCategory(enum.IntEnum):
    """ """

    DAQ = 1


class XcpLogFileParseError(Exception):
    """Log file is damaged is some way."""
    pass


class XcpLogFileCapacityExceededError(Exception):
    pass

class XcpLogFileWriter:
    """
    Parameters
    ----------
    file_name: str
        Don't specify extension.

    prealloc: int
        Pre-allocate a sparse file (size in MB).

    chunk_size: int
        Number of kilobytes to collect before compressing.

    compression_level: int
        s. LZ4 documentation.

    Notes
    -----

    `prealloc` is a **HARD limit**, if filesize is exceeded a `XcpLogFileCapacityExceededError`
    exception is raised, but only the last `chunk_size` kilobytes of data are lost.
    """

    def __init__(self, file_name: str, prealloc: int = 10, chunk_size: int = 1024,
        compression_level: int = 9
    ):
        self._is_closed = True
        try:
            self._of = open("{}{}".format(file_name, FILE_EXTENSION), "w+b")
        except Exception as e:
            raise
        else:
            self._of.truncate(1024 * 1024 * prealloc)   # Create sparse file (hopefully).
            self._mapping = mmap.mmap(self._of.fileno(), 0)
        self.container_header_offset = FILE_HEADER_STRUCT.size
        self.current_offset = self.container_header_offset + CONTAINER_HEADER_STRUCT.size
        self.total_size_uncompressed = self.total_size_compressed = 0
        self.container_size_uncompressed = self.container_size_compressed = 0
        self.total_record_count = 0
        self.chunk_size = chunk_size * 1024
        self.num_containers = 0
        self.intermediate_storage = []
        self.compression_level = compression_level
        self.prealloc = prealloc
        self._is_closed = False

    def add_xcp_frames(self, xcp_frames: list):
        for counter, timestamp, raw_data in xcp_frames:
            length = len(raw_data)
            item = DAQ_RECORD_STRUCT.pack(1, counter, timestamp, length) + raw_data
            self.intermediate_storage.append(item)
            self.container_size_uncompressed += len(item)
            if self.container_size_uncompressed > self.chunk_size:
                self._compress_framez()

    def _compress_framez(self):
        compressed_data = lz4block.compress(b''.join(self.intermediate_storage), compression = self.compression_level)
        record_count = len(self.intermediate_storage)
        hdr = CONTAINER_HEADER_STRUCT.pack(record_count, len(compressed_data), self.container_size_uncompressed)
        self.set(self.current_offset, compressed_data)
        self.set(self.container_header_offset, hdr)
        self.container_header_offset = self.current_offset + len(compressed_data)
        self.current_offset = self.container_header_offset + CONTAINER_HEADER_STRUCT.size
        self.intermediate_storage = []
        self.total_record_count += record_count
        self.num_containers +=1
        self.total_size_uncompressed += self.container_size_uncompressed
        self.total_size_compressed += len(compressed_data)
        self.container_size_uncompressed = 0
        self.container_size_compressed = 0

    def __del__(self):
        if not self._is_closed:
            self.close()

    def close(self):
        if not self._is_closed:
            if hasattr(self, "_mapping"):
                if self.intermediate_storage:
                    self._compress_framez()
                self._write_header(
                    version = 0x0100,
                    options = 0x0000,
                    num_containers = self.num_containers,
                    record_count = self.total_record_count,
                    size_compressed = self.total_size_compressed,
                    size_uncompressed = self.total_size_uncompressed
                )
                self._mapping.flush()
                self._mapping.close()
                self._of.truncate(self.current_offset)
            self._of.close()
            self._is_closed = True

    def set(self, address: int, data: bytes):
        """Write to memory mapped file.

        Parameters
        ----------
        address: int

        data: bytes-like
        """
        length = len(data)
        try:
            self._mapping[address : address + length] = data
        except IndexError as e:
            raise XcpLogFileCapacityExceededError("Maximum file size of {} MBytes exceeded.".format(self.prealloc))

    def _write_header(self, version, options, num_containers, record_count, size_compressed, size_uncompressed):
        hdr = FILE_HEADER_STRUCT.pack(
            MAGIC, FILE_HEADER_STRUCT.size, version, options, num_containers, record_count, size_compressed, size_uncompressed
        )
        self.set(0x00000000, hdr)

    @property
    def compression_ratio(self):
        if self.total_size_compressed:
            return self.total_size_uncompressed / self.total_size_compressed


class XcpLogFileReader:
    """
    Parameters
    ----------
    file_name: str
        Don't specify extension.
    """

    def __init__(self, file_name):
        self._is_closed = True
        try:
            self._log_file = open("{}{}".format(file_name, FILE_EXTENSION), "r+b")
        except Exception as e:
            raise
        else:
            self._mapping = mmap.mmap(self._log_file.fileno(), 0)
        self._is_closed = False
        magic, _, _, _, self.num_containers, self.total_record_count, self.total_size_compressed, self.total_size_uncompressed = (
            FILE_HEADER_STRUCT.unpack(self.get(0, FILE_HEADER_STRUCT.size))
        )
        if magic != MAGIC:
            raise XcpLogFileParseError("Invalid file magic: '{}'.".format(magic))

    def __del__(self):
        if not self._is_closed:
            self.close()

    @property
    def frames(self):
        """Iterate over all frames in file.

        Yields
        ------
        DAQRecord
        """
        offset = FILE_HEADER_STRUCT.size
        for _ in range(self.num_containers):
            record_count, size_compressed, size_uncompressed = CONTAINER_HEADER_STRUCT.unpack(
                self.get(offset, CONTAINER_HEADER_STRUCT.size)
            )
            offset += CONTAINER_HEADER_STRUCT.size
            uncompressed_data = memoryview(lz4block.decompress(self.get(offset, size_compressed)))
            frame_offset = 0
            for _ in range(record_count):
                category, counter, timestamp, frame_length = DAQ_RECORD_STRUCT.unpack(
                    uncompressed_data[frame_offset : frame_offset + DAQ_RECORD_STRUCT.size]
                )
                frame_offset += DAQ_RECORD_STRUCT.size
                frame_data = uncompressed_data[frame_offset : frame_offset + frame_length] # .tobytes()
                frame_offset += len(frame_data)
                frame = DAQRecord(category, counter, timestamp, frame_data)
                yield frame
            offset += size_compressed

    def get(self, address: int, length: int):
        """Read from memory mapped file.

        Parameters
        ----------
        address: int

        length: int

        Returns
        -------
        memoryview
        """
        return self._mapping[address : address + length]

    def close(self):
        if hasattr(self, "self._mapping"):
            self._mapping.close()
        self._log_file.close()
        self._is_closed = True

    @property
    def compression_ratio(self):
        if self.total_size_compressed:
            return self.total_size_uncompressed / self.total_size_compressed


class Worker(Process):
    """
    """

    def __init__(self, file_name, prealloc: int = 10, chunk_size: int = 1024, compression_level: int = 9):
        super(Worker, self).__init__()
        self.shutdown_event = Event()
        self.frame_queue = Queue()
        self.file_name = file_name
        self.prealloc = prealloc
        self.chunk_size = chunk_size
        self.compression_level = compression_level

    def run(self):
        log_writer = XcpLogFileWriter(
            self.file_name, self.prealloc, chunk_size = self.chunk_size, compression_level = self.compression_level
        )
        while True:
            self.shutdown_event.wait(0.1)
            if self.shutdown_event.is_set():
                break
            try:
                 frames = self.frame_queue.get(block = True, timeout = 0.1)
            except Exception:
                continue
            else:
                log_writer.add_xcp_frames(frames)
        log_writer.close()
        self.frame_queue.close()
        self.frame_queue.join_thread()


class LogConverter(Process):

    def __init__(self, slave_properties, daq_info, log_file_name):
        super(LogConverter, self).__init__()
        self.daq_info = daq_info
        self.slave_properties = slave_properties
        self.byte_order_prefix = struct_byte_order_prefix(slave_properties["byteOrder"])

        self.log_file_name = log_file_name

    def run(self):

        DAQ_TIMESTAMP_FORMAT = {
            "S1": "B",
            "S2": "H",
            "S4": "L",
        }

        DAQ_PID_FORMAT = {
            "IDF_ABS_ODT_NUMBER": "B",
            "IDF_REL_ODT_NUMBER_ABS_DAQ_LIST_NUMBER_BYTE": "BB",
            "IDF_REL_ODT_NUMBER_ABS_DAQ_LIST_NUMBER_WORD": "BH",
            "IDF_REL_ODT_NUMBER_ABS_DAQ_LIST_NUMBER_WORD_ALIGNED": "BxH",
        }

        daq_pro = self.daq_info.get("processor")
        daq_key_byte = daq_pro.get("keyByte")
        daq_resolution = self.daq_info.get("resolution")
        time_stamp_mode = daq_resolution.get("timestampMode")
        time_stamp_size = time_stamp_mode.get("size")
        idf = daq_key_byte['identificationField']

        if idf:
            daq_pid_struct = struct.Struct("{}{}".format(self.byte_order_prefix, DAQ_PID_FORMAT.get(idf)))
            daq_pid_size = daq_pid_struct.size
        else:
            daq_pid_struct = None
            daq_pid_size = 0
        ts_format = DAQ_TIMESTAMP_FORMAT.get(time_stamp_size)
        if ts_format:
            daq_timestamp_struct = struct.Struct("{}{}".format(self.byte_order_prefix, ts_format))
            daq_timestamp_size = daq_timestamp_struct.size
        else:
            daq_timestamp_struct = None
            daq_timestamp_size = 0

        reader = XcpLogFileReader(self.log_file_name)
        print("# of containers:    ", reader.num_containers)
        print("# of frames:        ", reader.total_record_count)
        print("Size / uncompressed:", reader.total_size_uncompressed)
        print("Size / compressed:  ", reader.total_size_compressed)
        print("Compression ratio:   {:3.3f}".format(reader.compression_ratio or 0.0))
        print("-" * 32, end = "\n\n")
        print("Processing frames...")
        for frame in reader.frames:
            cat, counter, timestamp, data = frame
            if daq_pid_struct:
                daq_pid = daq_pid_struct.unpack(data[ : daq_pid_size])
                daq_timestamp = daq_timestamp_struct.unpack(data[daq_pid_size : daq_pid_size + daq_timestamp_size])
                payload = data[daq_pid_size  + daq_timestamp_size :]
                #print("PID/TS", daq_pid, daq_timestamp, "DATA:", payload.tolist())
        print("OK, done.")

