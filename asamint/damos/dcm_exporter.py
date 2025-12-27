import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from asamint.calibration.db import CalibrationDB
from asamint.calibration.msrsw_db import MSRSWDatabase, SwInstance
from asamint.utils.templates import do_template


class DcmExporter:
    def __init__(self, db: MSRSWDatabase, h5_db: CalibrationDB = None, logger: logging.Logger = None):
        self.db = db
        self.h5_db = h5_db
        self.logger = logger or logging.getLogger(__name__)
        self.template_path = (
            Path(__file__).parent.parent / "data" / "templates" / "dcm.tmpl"
        )

    def export(self, output_path: str | Path) -> bool:
        self.logger.info(f"Exporting DCM to {output_path}")
        self.logger.info(f"Using template from {self.template_path}")

        params = {
            "AXIS_PTS": {},
            "VALUE": {},
            "ASCII": {},
            "VAL_BLK": {},
            "CURVE": {},
            "MAP": {},
        }

        session = self.db.session
        instances = session.query(SwInstance).all()

        for inst in instances:
            param_data = self._prepare_param_data(inst)
            if not param_data:
                continue

            category = param_data.category
            if category in ("VALUE", "BOOLEAN", "TEXT"):
                params["VALUE"][param_data.name] = param_data
            elif category == "ASCII":
                params["ASCII"][param_data.name] = param_data
            elif category == "VAL_BLK":
                params["VAL_BLK"][param_data.name] = param_data
            elif category == "STUETZSTELLENVERTEILUNG":
                params["AXIS_PTS"][param_data.name] = param_data
            elif category == "CURVE":
                params["CURVE"][param_data.name] = param_data
            elif category == "MAP":
                params["MAP"][param_data.name] = param_data

        namespace = {
            "params": params,
            "dataset": {},
            "experiment": {},
            "current_datetime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

        try:
            res = do_template(str(self.template_path), namespace, formatExceptions=True, encoding="latin-1")
            if res is None:
                self.logger.error("Template rendering returned None")
                return False

            with open(output_path, "w", encoding="latin-1") as of:
                of.write(res)
            return True
        except Exception as e:
            self.logger.error(f"Error rendering DCM template: {e}")
            return False

    def _prepare_param_data(self, inst: SwInstance) -> Any:
        name = inst.short_name.content if inst.short_name else None
        if not name:
            return None

        # Load data from H5
        data = None
        if self.h5_db:
            try:
                data = self.h5_db.load(name)
            except Exception as e:
                self.logger.debug(f"Could not load values for {name} from H5: {e}")

        class ParamData:
            def __init__(self, name, category, comment, display_id, unit, values, axes=None, fnc_unit=None):
                self.name = name
                self.category = category
                self.comment = comment
                self.displayIdentifier = display_id
                self.unit = unit
                self.axes = axes or []
                self.fnc_unit = fnc_unit

                if values is not None:
                    # Template expects converted_value for single values and converted_values for arrays
                    if category in ("VALUE", "BOOLEAN", "TEXT"):
                        self.converted_value = values.values.item() if hasattr(values.values, "item") else values.values
                        # For ASCII, it might expect .value
                        self.value = self.converted_value
                    else:
                        self.converted_values = values.values
                else:
                    self.converted_value = 0
                    self.converted_values = []

        category = inst.category.content if inst.category else "VALUE"
        comment = ""
        # Find comment in MSRSW DB if available
        # In our model, SwInstance might have relationships to Desc/Comment
        # But for now, let's use what's in H5 if MSRSW is empty
        if data is not None:
             comment = data.attrs.get("comment", "")
             display_id = data.attrs.get("display_identifier", "")
             unit = data.attrs.get("unit", "")
        else:
             display_id = ""
             unit = ""

        # Mapping CDF categories to DCM-friendly ones for the template
        dcm_category = category
        if category == "VALUE_ARRAY":
            dcm_category = "VAL_BLK"
        elif category == "AXIS_PTS":
            dcm_category = "STUETZSTELLENVERTEILUNG"

        axes_data = []
        fnc_unit = unit
        if data is not None:
            # Reconstruct axes for the template
            # The template expects axis objects with category, unit, axis_pts_ref or converted_values
            for dim_name in data.dims:
                # In xarray, coords for dim_name contains the axis values
                if dim_name in data.coords:
                    axis_vals = data.coords[dim_name].values
                else:
                    axis_vals = []

                class AxisData:
                    def __init__(self, category, unit, values):
                        self.category = category # Standard vs Fixed vs Common
                        self.unit = unit
                        self.converted_values = values

                # Assume STD_AXIS for now
                axes_data.append(AxisData("STD_AXIS", "", axis_vals))

        return ParamData(name, dcm_category, comment, display_id, unit, data, axes=axes_data, fnc_unit=fnc_unit)

def export_to_dcm(db_path: str | Path, output_dcm_path: str | Path, h5_path: str | Path = None):
    db = MSRSWDatabase(db_path)

    h5_db = None
    if h5_path:
        h5_db = CalibrationDB(h5_path, mode="r")
    else:
        # Try to find corresponding .h5 file
        potential_h5 = Path(db_path).with_suffix(".h5")
        if potential_h5.exists():
            h5_db = CalibrationDB(potential_h5, mode="r")

    exporter = DcmExporter(db, h5_db=h5_db)
    success = exporter.export(output_dcm_path)

    if h5_db:
        h5_db.close()
    db.close()
    return success
