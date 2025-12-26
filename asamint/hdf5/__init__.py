#!/usr/bin/env python
# -*- coding: utf-8 -*-

import h5py
import numpy as np
import threading
import queue
import time
import os
from datetime import datetime


from typing import Any, Iterable

from asamint.asam import AsamMC
from pya2l.api import inspect


class AsyncHDF5StreamingWriter:
    """
    Asynchroner, multi-dataset HDF5-Streaming-Writer mit:
    - mehreren parallelen Datasets (1D/2D/ND)
    - Kompression (gzip, lzf, None)
    - Metadaten
    - Auto-Rotation nach Dateigröße
    - Queue-basiertem Async-Writer
    """

    def __init__(
        self,
        base_filename: str,
        datasets: dict,
        compression="gzip",  # str | None | dict[dataset_name] -> str|None
        metadata: dict | None = None,
        max_file_size_mb: int = 512,
        flush_interval: float = 1.0,
        queue_maxsize: int = 10000,
    ):
        """
        Parameters
        ----------
        base_filename : str
            Basisname für Dateien, z.B. 'messung'
        datasets : dict
            Dict: name -> { 'dtype': ..., 'shape': (...), 'chunks': (...,) }
            shape: Form PRO SAMPLE (ohne Sample-Dimension)
        compression : str | None | dict
            'gzip', 'lzf' oder None; optional dict pro Dataset
        metadata : dict | None
            Metadaten für die HDF5-Datei (werden als HDF5-Attribute gespeichert)
        max_file_size_mb : int
            Rotationsgrenze für Dateigröße
        flush_interval : float
            Maximale Zeit zwischen Flushes (Sekunden)
        queue_maxsize : int
            Maximale Länge der internen Queue (Backpressure)
        """
        self.base_filename = base_filename
        self.datasets_spec = datasets
        self.compression = compression
        self.metadata = metadata or {}
        self.max_file_size_mb = max_file_size_mb
        self.flush_interval = flush_interval

        self.file_index = 0
        self.lock = threading.Lock()

        # Async-Queue für Samples
        self.queue = queue.Queue(maxsize=queue_maxsize)
        self.running = False
        self.last_flush = time.time()

        self._open_new_file()

    # ---------------------------------------------------------
    # Datei-Handling
    # ---------------------------------------------------------

    def _get_dataset_compression(self, name: str):
        """Ermittelt Kompression für ein Dataset."""
        if isinstance(self.compression, dict):
            return self.compression.get(name, None)
        return self.compression

    def _open_new_file(self):
        """Öffnet eine neue HDF5-Datei und legt Datasets + Metadaten an."""
        # Vorherige Datei schließen
        if hasattr(self, "file") and self.file:
            self.file.close()

        filename = f"{self.base_filename}_{self.file_index:04d}.h5"
        self.file_index += 1

        self.file = h5py.File(filename, "w")
        self.datasets = {}

        # Metadaten als File-Attribute
        self.file.attrs["created_at"] = datetime.utcnow().isoformat() + "Z"
        for k, v in self.metadata.items():
            # einfache Typen direkt als Attribute speichern
            try:
                self.file.attrs[k] = v
            except TypeError:
                # notfalls String-Repräsentation
                self.file.attrs[k] = str(v)

        # Datasets anlegen
        for name, spec in self.datasets_spec.items():
            dtype = spec["dtype"]
            sample_shape = tuple(spec.get("shape", ()))
            chunks = spec.get("chunks", None)

            # Gesamtdataset-Shape: (N, *sample_shape)
            initial_shape = (0,) + sample_shape
            maxshape = (None,) + sample_shape

            compression = self._get_dataset_compression(name)

            ds = self.file.create_dataset(
                name,
                shape=initial_shape,
                maxshape=maxshape,
                dtype=dtype,
                chunks=chunks,
                compression=compression,
            )
            self.datasets[name] = ds

        self.last_flush = time.time()

    def _rotate_if_needed(self):
        """Rotiert die Datei, wenn sie zu groß wird."""
        filename = self.file.filename
        if not os.path.exists(filename):
            return
        size_mb = os.path.getsize(filename) / (1024 * 1024)
        if size_mb >= self.max_file_size_mb:
            self.file.flush()
            self._open_new_file()

    # ---------------------------------------------------------
    # Async-Interface (Producer-Seite)
    # ---------------------------------------------------------

    def enqueue(self, sample: dict):
        """
        Fügt ein Sample in die Queue ein.

        sample: dict {dataset_name: value}
        - Für jedes definierte Dataset kann ein Wert angegeben werden.
        - Werte können Skalar, 1D-Array, 2D-Array, ... entsprechend der 'shape' Spezifikation sein.
        """
        # Du kannst hier noch Validation einbauen, falls gewünscht.
        self.queue.put(sample, block=True)

    # ---------------------------------------------------------
    # Hintergrund-Thread (Consumer-Seite)
    # ---------------------------------------------------------

    def start(self):
        """Startet den Hintergrund-Thread."""
        if self.running:
            return
        self.running = True
        self.worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self.worker_thread.start()

    def _worker_loop(self):
        """
        Worker-Loop:
        - nimmt Samples aus der Queue
        - schreibt sie batched in die Datasets
        - rotiert Dateien bei Bedarf
        """
        # Puffer pro Dataset
        buffers = {name: [] for name in self.datasets_spec.keys()}

        def flush_buffers():
            """Schreibt alle Puffer in die Datasets."""
            if not any(buffers[name] for name in buffers):
                return

            with self.lock:
                # Alle Datasets müssen entlang der ersten Dimension (Samples) erweitert werden
                # Wir gehen davon aus, dass alle Datasets, die in diesem Batch geschrieben werden,
                # die gleiche Anzahl an neuen Samples haben (oder leer bleiben).
                # Wir bestimmen max_len über alle Datasets.
                max_len = 0
                for name, buf in buffers.items():
                    if buf:
                        max_len = max(max_len, len(buf))

                if max_len == 0:
                    return

                for name, spec in self.datasets_spec.items():
                    buf = buffers[name]
                    if not buf:
                        continue

                    ds = self.datasets[name]
                    # buf -> np.array mit Shape (batch, *sample_shape)
                    arr = np.asarray(buf, dtype=spec["dtype"])
                    n_new = arr.shape[0]

                    old_size = ds.shape[0]
                    new_size = old_size + n_new
                    ds.resize((new_size,) + ds.shape[1:])
                    ds[old_size:new_size, ...] = arr

                    buffers[name].clear()

                self.file.flush()
                self.last_flush = time.time()
                self._rotate_if_needed()

        while self.running or not self.queue.empty():
            try:
                # kleines Timeout, damit wir regelmäßig flushen
                sample = self.queue.get(timeout=0.1)
                # sample ist ein dict: name -> value
                for name, value in sample.items():
                    if name not in buffers:
                        # unbekanntes Dataset ignorieren oder Exception werfen
                        continue
                    buffers[name].append(value)

                # optional: hier könnte man batching nach Anzahl Samples einbauen
            except queue.Empty:
                pass

            # Zeitbasiertes Flushen
            if time.time() - self.last_flush >= self.flush_interval:
                flush_buffers()

        # Am Ende alles flushen
        flush_buffers()

    # ---------------------------------------------------------
    # Shutdown
    # ---------------------------------------------------------

    def stop(self):
        """Stoppt den Worker-Thread und schließt die Datei."""
        self.running = False
        if hasattr(self, "worker_thread"):
            self.worker_thread.join()

        with self.lock:
            self.file.flush()
            self.file.close()


class HDF5Creator(AsamMC):
    """
    Create and save HDF5 files from ECU measurements,
    integrating with pya2l and pyxcp. Same interface as MDFCreator.
    """

    def on_init(self, project_config, experiment_config, *args, **kws):
        self.loadConfig(project_config, experiment_config)
        self.measurement_variables: list[Any] = []
        try:
            self._resolve_measurements_from_config()
        except Exception as e:
            self.logger.debug(
                f"HDF5Creator: could not resolve measurements from config: {e}"
            )

    def add_measurements(self, names: Iterable[str]) -> None:
        """Add measurement items by name using pya2l inspect.Measurement."""
        for name in names:
            try:
                meas = inspect.Measurement.get(self.session, name)
                if meas is not None:
                    self.measurement_variables.append(meas)
            except Exception as e:
                self.logger.warning(f"Unknown measurement '{name}': {e}")

    def _resolve_measurements_from_config(self) -> None:
        """Resolve measurements from experiment_config (MEASUREMENTS only)."""
        names = self.experiment_config.get("MEASUREMENTS") or []
        if names:
            self.add_measurements(names)

    def save_measurements(
        self,
        h5_filename: str | None = None,
        data: dict[str, Any] | None = None,
        **kwargs,
    ) -> None:
        """
        Save collected measurements into an HDF5 file using AsyncHDF5StreamingWriter.
        """
        if not data:
            return

        if h5_filename is None:
            h5_filename = self.generate_filename(".h5")

        # Determine datasets spec from data
        datasets_spec = {}
        for name, values in data.items():
            arr = np.asarray(values)
            datasets_spec[name] = {
                "dtype": arr.dtype,
                "shape": arr.shape[1:],  # shape per sample
            }

        # Project metadata
        metadata = {
            "author": self.config.general.author,
            "project": self.config.general.project,
            "subject": self.experiment_config.get("SUBJECT", ""),
            "description": self.experiment_config.get("DESCRIPTION", ""),
        }

        # Create writer - AsyncHDF5StreamingWriter expects a base filename without extension
        # because it appends _0000.h5 etc.
        # But if we want exactly h5_filename, we might need to adjust AsyncHDF5StreamingWriter
        # or just use it as is.
        base = h5_filename
        if base.lower().endswith(".h5"):
            base = base[:-3]

        writer = AsyncHDF5StreamingWriter(
            base_filename=base,
            datasets=datasets_spec,
            metadata=metadata,
        )
        writer.start()

        # Enqueue all data at once (AsyncHDF5StreamingWriter will batch it)
        # We need to transform data dict of arrays into a list of sample dicts
        # or we could optimize AsyncHDF5StreamingWriter to take a batch.
        # Given it's a "StreamingWriter", it's designed for samples.

        # Find max length to know how many samples we have
        sample_counts = [len(v) for v in data.values()]
        if not sample_counts:
            writer.stop()
            return
        num_samples = max(sample_counts)

        for i in range(num_samples):
            sample = {}
            for name in datasets_spec:
                if i < len(data[name]):
                    sample[name] = data[name][i]
            writer.enqueue(sample)

        writer.stop()
