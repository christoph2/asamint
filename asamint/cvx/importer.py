import csv
import logging
from typing import Any, Dict, List, TextIO, Tuple

from .constants import CVX_TYPES


class CVXImporter:
    """
    Importer for CVX files.
    """

    def __init__(self):
        self.comment_indicator = "#"
        self.value_separator = ","
        self.string_delimiter = '"'
        self.functions: list[str] = []
        self.variants: dict[str, list[str]] = {}
        self.records: list[dict[str, Any]] = []

    def import_file(self, filename: str) -> list[dict[str, Any]]:
        """
        Import calibration records from a CVX file.

        :param filename: The path to the CVX file.
        :return: A list of dictionaries, where each dictionary represents a calibration record.
        """
        self.records = []
        self.functions = []
        self.variants = {}
        with open(filename, encoding="latin-1") as f:
            self._parse_lines(f)
        return self.records

    def _parse_float(self, s: str) -> float:
        try:
            return float(s)
        except (ValueError, TypeError):
            return 0.0

    def _parse_lines(self, f: TextIO):
        lines = f.readlines()
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if not line or line.startswith(self.comment_indicator):
                i += 1
                continue

            reader = csv.reader(
                [line],
                delimiter=self.value_separator,
                quotechar=self.string_delimiter,
            )
            fields = next(reader)
            first_field = fields[0].strip() if fields else ""

            if first_field == "FUNCTION_HDR":
                i = self._parse_function_header(lines, i)
            elif first_field == "VARIANT_HDR":
                i = self._parse_variant_header(lines, i)
            elif len(fields) >= 2 and fields[1].strip():
                i, record = self._parse_record_start(lines, i, fields)
                if record:
                    self.records.append(record)
            else:
                i += 1

    def _parse_function_header(self, lines: list[str], i: int) -> int:
        i += 1
        if i < len(lines):
            f_line = lines[i].strip()
            f_reader = csv.reader(
                [f_line],
                delimiter=self.value_separator,
                quotechar=self.string_delimiter,
            )
            self.functions = [f.strip() for f in next(f_reader) if f.strip()]
        return i + 1

    def _parse_variant_header(self, lines: list[str], i: int) -> int:
        i += 1
        while i < len(lines):
            v_line = lines[i].strip()
            if not v_line:
                break
            v_reader = csv.reader(
                [v_line],
                delimiter=self.value_separator,
                quotechar=self.string_delimiter,
            )
            v_fields = next(v_reader)
            if v_fields:
                criterion = v_fields[0].strip()
                values = [v.strip() for v in v_fields[1:] if v.strip()]
                self.variants[criterion] = values
            i += 1
        return i

    def _parse_record_start(
        self, lines: list[str], i: int, fields: list[str]
    ) -> tuple[int, dict[str, Any]]:
        record = {
            "identifier": fields[1].strip(),
            "type": None,
            "values": [],
            "variants": [],
            "function": None,
        }

        i += 1
        if i >= len(lines):
            return i, record

        desc_line = lines[i].strip()
        d_reader = csv.reader(
            [desc_line],
            delimiter=self.value_separator,
            quotechar=self.string_delimiter,
        )
        d_fields = next(d_reader)
        if not d_fields:
            return i + 1, record

        record["type"] = d_fields[0].strip()
        rec_type = record["type"]

        if rec_type == "VALUE":
            if len(d_fields) >= 3:
                record["values"] = [self._parse_float(d_fields[2])]
        elif rec_type == "ASCII":
            if len(d_fields) >= 3:
                record["values"] = [d_fields[2]]
        elif rec_type == "VAL_BLK":
            record["values"] = [self._parse_float(f) for f in d_fields[2:] if f.strip()]
        elif rec_type == "CURVE":
            i = self._parse_curve(lines, i, record)
        elif rec_type == "MAP":
            i = self._parse_map(lines, i, record)
        elif rec_type in ("AXIS_PTS", "X_AXIS_PTS", "Y_AXIS_PTS", "Z_AXIS_PTS"):
            record["values"] = [self._parse_float(f) for f in d_fields[2:] if f.strip()]
        elif rec_type == "RESCALE_AXIS_PTS":
            values = [self._parse_float(f) for f in d_fields[2:] if f.strip()]
            record["values"] = list(zip(values[::2], values[1::2]))

        # After parsing the main body, check for additional attributes
        i, record = self._parse_record_attributes(lines, i, record)
        return i, record

    def _parse_curve(self, lines: list[str], i: int, record: dict[str, Any]) -> int:
        i += 1
        if i >= len(lines):
            return i

        line1 = lines[i].rstrip("\r\n")
        reader1 = csv.reader(
            [line1], delimiter=self.value_separator, quotechar=self.string_delimiter
        )
        fields1 = next(reader1)

        # Check for a second line of data
        if i + 1 < len(lines):
            line2 = lines[i + 1].rstrip("\r\n")
            reader2 = csv.reader(
                [line2], delimiter=self.value_separator, quotechar=self.string_delimiter
            )
            fields2 = next(reader2)

            if len(fields2) >= 3 and (
                fields2[0].strip() == "" or fields2[0].strip() == self.value_separator
            ):
                # Two lines of data -> first is axis, second is values
                record["axis_x"] = [
                    self._parse_float(f) for f in fields1[2:] if f.strip()
                ]
                record["values"] = [
                    self._parse_float(f) for f in fields2[2:] if f.strip()
                ]
                i += 1
            else:
                # Only one line of data -> it's values
                record["values"] = [
                    self._parse_float(f) for f in fields1[2:] if f.strip()
                ]
        else:
            record["values"] = [self._parse_float(f) for f in fields1[2:] if f.strip()]
        return i

    def _parse_map(self, lines: list[str], i: int, record: dict[str, Any]) -> int:
        i += 1
        if i >= len(lines):
            return i

        line1 = lines[i].rstrip("\r\n")
        reader1 = csv.reader(
            [line1], delimiter=self.value_separator, quotechar=self.string_delimiter
        )
        fields1 = next(reader1)

        # First line after MAP is usually X-axis
        record["axis_x"] = [self._parse_float(f) for f in fields1[2:] if f.strip()]

        i += 1
        map_values = []
        y_axis = []
        while i < len(lines):
            m_line = lines[i].rstrip("\r\n")
            if not m_line.strip() or m_line.startswith(self.comment_indicator):
                break
            m_reader = csv.reader(
                [m_line],
                delimiter=self.value_separator,
                quotechar=self.string_delimiter,
            )
            m_fields = next(m_reader)

            if m_fields and m_fields[0].strip() in (
                "VARIANT",
                "FUNCTION",
                "DISPLAY_IDENTIFIER",
            ):
                break

            # MAP lines: y_val at index 2, Z vals at index 3 onwards?
            # Actually spec says: line 3: y[1] z[1,1] z[1,2] ... z[1,n]
            # If y[1] is at col 3 (index 2), then z[1,1] is at index 3.
            if len(m_fields) < 3:
                break

            y_val_str = m_fields[2].strip()
            if not y_val_str:
                break  # Should have a value

            y_axis.append(self._parse_float(y_val_str))
            map_values.append([self._parse_float(f) for f in m_fields[3:] if f.strip()])
            i += 1
        record["axis_y"] = y_axis
        record["values"] = map_values
        return (
            i - 1
        )  # Step back so that i+1 in the next loop points to the correct line

    def _parse_record_attributes(
        self, lines: list[str], i: int, record: dict[str, Any]
    ) -> tuple[int, dict[str, Any]]:
        while i + 1 < len(lines):
            next_line = lines[i + 1].strip()
            if not next_line:
                i += 1
                continue
            n_reader = csv.reader(
                [next_line],
                delimiter=self.value_separator,
                quotechar=self.string_delimiter,
            )
            n_fields = next(n_reader)
            if not n_fields:
                i += 1
                continue

            tag = n_fields[0].strip()
            if tag == "FUNCTION":
                if len(n_fields) >= 3:
                    record["function"] = n_fields[2].strip()
                i += 1
            elif tag == "VARIANT":
                # VARIANT;; "Car"."Limousine";"Gear"."Manual"
                for v_spec in n_fields[2:]:
                    if v_spec.strip():
                        # Car.Limousine
                        v_parts = v_spec.strip().split(".")
                        if len(v_parts) == 2:
                            record["variants"].append(
                                (
                                    v_parts[0].strip(self.string_delimiter),
                                    v_parts[1].strip(self.string_delimiter),
                                )
                            )
                i += 1
            elif tag == "DISPLAY_IDENTIFIER":
                if len(n_fields) >= 3:
                    record["display_identifier"] = n_fields[2].strip()
                i += 1
            else:
                break
        return i + 1, record
