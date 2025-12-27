import csv
import logging
import re
from pathlib import Path
import io

class CVXImporter:
    """
    Importer for Calibration Values Exchange (CVX) format.
    Supports version 2.0 as specified in ASAM CVX documentation.
    """
    def __init__(self, logger: logging.Logger = None):
        self.logger = logger or logging.getLogger(__name__)
        self.value_separator = ','
        self.decimal_point = '.'
        self.comment_indicator = '*'
        self.string_delimiter = '"'
        self.version = "2.0"
        self.functions = []
        self.variants = {} # Criterion -> list of values

    def _parse_header(self, first_line):
        # CALIBRATION VALUES V2.0;,;*; ""
        match = re.match(r'CALIBRATION VALUES V(\d+\.\d+)(.)?(.)?(.*)?', first_line)
        if not match:
            self.logger.warning(f"Could not parse CVX header: {first_line}")
            return

        self.version = match.group(1)
        sep = match.group(2)
        if sep:
            self.value_separator = sep

        # The spec says:
        # The first character immediately following the file content identification determines the separator character
        # The character following the separator character determines the decimal point separator
        # The text following the decimal point separator determines the string to be used as the comment indicator
        # The character following the comment indicator determines the character to enclose all ASCII strings.
        # This character has to be stated two times without any <Value seperator> in between.

        # Let's try to split by value separator if we found it
        parts = first_line.split(self.value_separator)
        if len(parts) > 1:
            # part 0 is 'CALIBRATION VALUES V2.0'
            if len(parts) > 1:
                dp = parts[1].strip()
                if dp:
                    self.decimal_point = dp[0]
            if len(parts) > 2:
                ci = parts[2].strip()
                if ci:
                    self.comment_indicator = ci
            if len(parts) > 3:
                sd = parts[3].strip()
                if sd:
                    # Expecting something like "" or " "
                    # The spec says "stated two times without any <Value seperator> in between"
                    if len(sd) >= 2:
                        self.string_delimiter = sd[0]

        self.logger.info(f"CVX Header: Version={self.version}, Separator='{self.value_separator}', Decimal='{self.decimal_point}', Comment='{self.comment_indicator}', Delimiter='{self.string_delimiter}'")

    def _parse_float(self, val_str):
        if not val_str:
            return 0.0
        try:
            # Replace custom decimal point with standard dot for float()
            s = val_str.replace(self.decimal_point, '.')
            return float(s)
        except ValueError:
            return val_str # Might be a string

    def import_file(self, file_path):
        with open(file_path, 'r', encoding='latin-1') as f:
            lines = f.readlines()

        if not lines:
            return []

        self._parse_header(lines[0].strip())

        records = []
        current_record = None

        i = 1
        while i < len(lines):
            line = lines[i].strip()
            if not line or line.startswith(self.comment_indicator):
                i += 1
                continue

            # Split line using csv module to handle delimiters correctly
            reader = csv.reader([line], delimiter=self.value_separator, quotechar=self.string_delimiter)
            fields = next(reader)
            if not fields:
                i += 1
                continue

            first_field = fields[0].strip()

            if first_field == 'FUNCTION_HDR':
                i += 1
                if i < len(lines):
                    f_line = lines[i].strip()
                    f_reader = csv.reader([f_line], delimiter=self.value_separator, quotechar=self.string_delimiter)
                    self.functions = [f.strip() for f in next(f_reader) if f.strip()]
                i += 1
                continue

            if first_field == 'VARIANT_HDR':
                i += 1
                while i < len(lines):
                    v_line = lines[i].strip()
                    if not v_line:
                        break
                    v_reader = csv.reader([v_line], delimiter=self.value_separator, quotechar=self.string_delimiter)
                    v_fields = next(v_reader)
                    if v_fields:
                        criterion = v_fields[0].strip()
                        values = [v.strip() for v in v_fields[1:] if v.strip()]
                        self.variants[criterion] = values
                    i += 1
                continue

            # Check for calibration record start
            # "Calibration identifier is always found in column 2 of the first line of a record"
            # Actually col2 is index 1.
            if len(fields) >= 2 and fields[1].strip():
                # Start of a new record
                record = {
                    'identifier': fields[1].strip(),
                    'type': None,
                    'values': [],
                    'variants': [],
                    'function': None
                }

                # Next line should be the Calibration Description Line
                i += 1
                if i < len(lines):
                    desc_line = lines[i].strip()
                    d_reader = csv.reader([desc_line], delimiter=self.value_separator, quotechar=self.string_delimiter)
                    d_fields = next(d_reader)
                    if d_fields:
                        record['type'] = d_fields[0].strip()

                        if record['type'] == 'VALUE':
                            if len(d_fields) >= 3:
                                record['values'] = [self._parse_float(d_fields[2])]
                        elif record['type'] == 'ASCII':
                            if len(d_fields) >= 3:
                                record['values'] = [d_fields[2]]
                        elif record['type'] == 'VAL_BLK':
                            record['values'] = [self._parse_float(f) for f in d_fields[2:] if f.strip()]
                        elif record['type'] in ('CURVE', 'MAP', 'AXIS_PTS', 'X_AXIS_PTS', 'Y_AXIS_PTS', 'Z_AXIS_PTS', 'RESCALE_AXIS_PTS'):
                            # These might span multiple lines
                            if record['type'] == 'CURVE':
                                # Check if next line is x-axis or values
                                # Usually CURVE is followed by x-axis then values,
                                # but spec says embedded axis points can be skipped.
                                i += 1
                                line1 = lines[i].rstrip('\r\n')
                                reader1 = csv.reader([line1], delimiter=self.value_separator, quotechar=self.string_delimiter)
                                fields1 = next(reader1)

                                # Try to see if there is a second line of data
                                if i + 1 < len(lines):
                                    line2 = lines[i+1].rstrip('\r\n')
                                    reader2 = csv.reader([line2], delimiter=self.value_separator, quotechar=self.string_delimiter)
                                    fields2 = next(reader2)

                                    if len(fields2) >= 3 and (fields2[0].strip() == '' or fields2[0].strip() == self.value_separator):
                                        # Two lines of data -> first is axis, second is values
                                        record['axis_x'] = [self._parse_float(f) for f in fields1[2:] if f.strip()]
                                        record['values'] = [self._parse_float(f) for f in fields2[2:] if f.strip()]
                                        i += 1
                                    else:
                                        # Only one line of data -> it's values
                                        record['values'] = [self._parse_float(f) for f in fields1[2:] if f.strip()]
                                else:
                                    record['values'] = [self._parse_float(f) for f in fields1[2:] if f.strip()]
                            elif record['type'] == 'MAP':
                                # Similar to CURVE, but MAP has multiple rows
                                i += 1
                                line1 = lines[i].rstrip('\r\n')
                                reader1 = csv.reader([line1], delimiter=self.value_separator, quotechar=self.string_delimiter)
                                fields1 = next(reader1)

                                # First line after MAP is usually X-axis
                                record['axis_x'] = [self._parse_float(f) for f in fields1[2:] if f.strip()]

                                i += 1
                                map_values = []
                                y_axis = []
                                while i < len(lines):
                                    m_line = lines[i].rstrip('\r\n')
                                    if not m_line.strip() or m_line.startswith(self.comment_indicator):
                                        break
                                    m_reader = csv.reader([m_line], delimiter=self.value_separator, quotechar=self.string_delimiter)
                                    m_fields = next(m_reader)

                                    if m_fields and m_fields[0].strip() in ('VARIANT', 'FUNCTION', 'DISPLAY_IDENTIFIER'):
                                        break

                                    # MAP lines: y_val at index 2, Z vals at index 3 onwards?
                                    # Actually spec says: line 3: y[1] z[1,1] z[1,2] ... z[1,n]
                                    # If y[1] is at col 3 (index 2), then z[1,1] is at index 3.
                                    if len(m_fields) < 3: break

                                    y_val_str = m_fields[2].strip()
                                    if not y_val_str: break # Should have a value

                                    y_axis.append(self._parse_float(y_val_str))
                                    map_values.append([self._parse_float(f) for f in m_fields[3:] if f.strip()])
                                    i += 1
                                record['axis_y'] = y_axis
                                record['values'] = map_values
                                i -= 1 # Step back so that i+1 in the next loop points to the correct line
                            elif record['type'] in ('AXIS_PTS', 'X_AXIS_PTS', 'Y_AXIS_PTS', 'Z_AXIS_PTS'):
                                record['values'] = [self._parse_float(f) for f in d_fields[2:] if f.strip()]
                            elif record['type'] == 'RESCALE_AXIS_PTS':
                                # Pairs of values
                                record['values'] = [self._parse_float(f) for f in d_fields[2:] if f.strip()]

                # Optional lines: FUNCTION, VARIANT, DISPLAY_IDENTIFIER
                while i + 1 < len(lines):
                    next_line = lines[i+1].strip()
                    if not next_line:
                        i += 1
                        continue
                    n_reader = csv.reader([next_line], delimiter=self.value_separator, quotechar=self.string_delimiter)
                    n_fields = next(n_reader)
                    if not n_fields:
                        i += 1
                        continue

                    tag = n_fields[0].strip()
                    if tag == 'FUNCTION':
                        if len(n_fields) >= 3:
                            record['function'] = n_fields[2].strip()
                        i += 1
                    elif tag == 'VARIANT':
                        # VARIANT;; "Car"."Limousine";"Gear"."Manual"
                        for v_spec in n_fields[2:]:
                            if v_spec.strip():
                                # Car.Limousine
                                v_parts = v_spec.strip().split('.')
                                if len(v_parts) == 2:
                                    record['variants'].append((v_parts[0].strip(self.string_delimiter), v_parts[1].strip(self.string_delimiter)))
                        i += 1
                    elif tag == 'DISPLAY_IDENTIFIER':
                        if len(n_fields) >= 3:
                            record['display_identifier'] = n_fields[2].strip()
                        i += 1
                    else:
                        break

                records.append(record)

            i += 1

        return records

