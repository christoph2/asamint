import csv
import io
import logging
from pathlib import Path


class CVXExporter:
    """
    Exporter for Calibration Values Exchange (CVX) format.
    Generates CSV-based CVX files according to ASAM specification.
    """

    def __init__(
        self,
        delimiter=";",
        string_delimiter='"',
        float_format="%.9g",
        logger: logging.Logger = None,
    ):
        self.delimiter = delimiter
        self.string_delimiter = string_delimiter
        self.float_format = float_format
        self.logger = logger or logging.getLogger(__name__)

    def _format_float(self, value):
        return self.float_format % value

    def _format_string(self, s):
        if s is None:
            return ""
        return f"{self.string_delimiter}{s}{self.string_delimiter}"

    def _write_header(self, f, functions, variants):
        f.write("KENNUNGEN\r\n")
        if functions:
            f.write(f"FUNKTIONEN {self.delimiter.join(functions)}\r\n")
        if variants:
            for key, values in variants.items():
                f.write(f"VARIANTE {key} {self.delimiter.join(values)}\r\n")
        f.write("END\r\n")

    def _write_record_value(self, f, record):
        f.write("VALUE\r\n")
        value = self._format_float(record.get("values", [0.0])[0])
        f.write(f"WERT {value}\r\n")
        if "display_identifier" in record:
            f.write(f"DISPLAYNAME {record['display_identifier']}\r\n")

    def _write_record_val_blk(self, f, record):
        f.write("VAL_BLK\r\n")
        values = [self._format_float(v) for v in record.get("values", [])]
        f.write(f"WERT {self.delimiter.join(values)}\r\n")
        if "function" in record:
            f.write(f"FUNKTION {record['function']}\r\n")

    def _write_record_curve(self, f, record):
        f.write("CURVE\r\n")
        # Axis
        x_axis = [self._format_float(v) for v in record.get("axis_x", [])]
        f.write(f"ST/X {self.delimiter.join(x_axis)}\r\n")
        # Values
        values = [self._format_float(v) for v in record.get("values", [])]
        f.write(f"WERT {self.delimiter.join(values)}\r\n")

    def _write_record_map(self, f, record):
        f.write("MAP\r\n")
        # X Axis
        x_axis = [self._format_float(v) for v in record.get("axis_x", [])]
        f.write(f"ST/X {self.delimiter.join(x_axis)}\r\n")
        # Y Axis
        y_axis = [self._format_float(v) for v in record.get("axis_y", [])]
        f.write(f"ST/Y {self.delimiter.join(y_axis)}\r\n")
        # Values
        for row in record.get("values", []):
            values_row = [self._format_float(v) for v in row]
            f.write(f"WERT {self.delimiter.join(values_row)}\r\n")

    def _write_record(self, f, record):
        rec_type = record.get("type")
        if not rec_type:
            return

        f.write(f"KENNUNG {record['identifier']}\r\n")

        if rec_type == "VALUE":
            self._write_record_value(f, record)
        elif rec_type == "VAL_BLK":
            self._write_record_val_blk(f, record)
        elif rec_type == "CURVE":
            self._write_record_curve(f, record)
        elif rec_type == "MAP":
            self._write_record_map(f, record)

        if "variants" in record:
            for var_name, var_value in record["variants"]:
                f.write(f"VARIANTE {var_name} {var_value}\r\n")

        f.write("END\r\n")

    def export_file(self, file_path, records, functions=None, variants=None):
        with open(file_path, "w", encoding="latin-1", newline="") as f:
            # Header
            self._write_header(f, functions, variants)

            # Records
            for record in records:
                self._write_record(f, record)

    def export_stream(self, records, functions=None, variants=None):
        string_io = io.StringIO()
        self.export_file(string_io, records, functions, variants)
        return string_io.getvalue()
