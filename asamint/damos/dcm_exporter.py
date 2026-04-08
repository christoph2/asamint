import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from asamint.calibration.db import CalibrationDB
from asamint.calibration.msrsw_db import MSRSWDatabase, SwInstance
from asamint.utils.templates import do_template


@dataclass
class AxisData:
    category: str
    unit: str
    converted_values: Any


@dataclass
class ParamData:
    name: str
    category: str
    comment: str
    displayIdentifier: str
    unit: str
    values: Any
    axes: list[AxisData] = field(default_factory=list)
    fnc_unit: str | None = None
    converted_value: Any = 0
    converted_values: Any = field(default_factory=list)
    value: Any = 0

    def __post_init__(self) -> None:
        if self.values is None:
            return
        if self.category in ("VALUE", "BOOLEAN", "TEXT"):
            self.converted_value = (
                self.values.values.item()
                if hasattr(self.values.values, "item")
                else self.values.values
            )
            self.value = self.converted_value
        else:
            self.converted_values = self.values.values


class DcmExporter:
    def __init__(
        self,
        db: MSRSWDatabase,
        h5_db: CalibrationDB = None,
        logger: logging.Logger = None,
    ):
        self.db = db
        self.h5_db = h5_db
        self.logger = logger or logging.getLogger(__name__)
        self.template_path = (
            Path(__file__).parent.parent / "data" / "templates" / "dcm.tmpl"
        )

    def export(self, output_path: str | Path) -> bool:
        self.logger.info(f"Exporting DCM to {output_path}")
        self.logger.info(f"Using template from {self.template_path}")
        params = self._collect_params()
        namespace = self._create_namespace(params)
        return self._render_template(output_path, namespace)

    @staticmethod
    def _empty_params() -> dict[str, dict[str, ParamData]]:
        return {
            "AXIS_PTS": {},
            "VALUE": {},
            "ASCII": {},
            "VAL_BLK": {},
            "CURVE": {},
            "MAP": {},
        }

    def _collect_params(self) -> dict[str, dict[str, ParamData]]:
        params = self._empty_params()
        instances = self.db.session.query(SwInstance).all()
        for inst in instances:
            param_data = self._prepare_param_data(inst)
            bucket = (
                self._bucket_for_category(param_data.category) if param_data else None
            )
            if bucket and param_data:
                params[bucket][param_data.name] = param_data
        return params

    @staticmethod
    def _bucket_for_category(category: str) -> str | None:
        if category in ("VALUE", "BOOLEAN", "TEXT"):
            return "VALUE"
        if category == "ASCII":
            return "ASCII"
        if category == "VAL_BLK":
            return "VAL_BLK"
        if category == "STUETZSTELLENVERTEILUNG":
            return "AXIS_PTS"
        if category == "CURVE":
            return "CURVE"
        if category == "MAP":
            return "MAP"
        return None

    @staticmethod
    def _create_namespace(params: dict[str, dict[str, ParamData]]) -> dict[str, Any]:
        return {
            "params": params,
            "dataset": {},
            "experiment": {},
            "current_datetime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    def _render_template(
        self, output_path: str | Path, namespace: dict[str, Any]
    ) -> bool:
        try:
            res = do_template(
                str(self.template_path),
                namespace,
                formatExceptions=True,
                encoding="latin-1",
            )
            if res is None:
                self.logger.error("Template rendering returned None")
                return False

            with open(output_path, "w", encoding="latin-1") as of:
                of.write(res)
            return True
        except (OSError, ValueError, TypeError) as e:
            self.logger.error(f"Error rendering DCM template: {e}")
            return False

    def _prepare_param_data(self, inst: SwInstance) -> Any:
        name = self._instance_name(inst)
        if not name:
            return None

        data = self._load_h5_data(name)
        category = self._normalize_category(
            inst.category.content if inst.category else "VALUE"
        )
        comment, display_id, unit = self._metadata_from_data(data)
        return ParamData(
            name,
            category,
            comment,
            display_id,
            unit,
            data,
            axes=self._build_axes_data(data),
            fnc_unit=unit,
        )

    @staticmethod
    def _instance_name(inst: SwInstance) -> str | None:
        return inst.short_name.content if inst.short_name else None

    def _load_h5_data(self, name: str) -> Any:
        if not self.h5_db:
            return None
        try:
            return self.h5_db.load(name)
        except (KeyError, ValueError, TypeError) as e:
            self.logger.debug(f"Could not load values for {name} from H5: {e}")
            return None

    @staticmethod
    def _normalize_category(category: str) -> str:
        if category == "VALUE_ARRAY":
            return "VAL_BLK"
        if category == "AXIS_PTS":
            return "STUETZSTELLENVERTEILUNG"
        return category

    @staticmethod
    def _metadata_from_data(data: Any) -> tuple[str, str, str]:
        if data is None:
            return "", "", ""
        return (
            data.attrs.get("comment", ""),
            data.attrs.get("display_identifier", ""),
            data.attrs.get("unit", ""),
        )

    @staticmethod
    def _build_axes_data(data: Any) -> list[AxisData]:
        if data is None:
            return []
        axes_data: list[AxisData] = []
        for dim_name in data.dims:
            axis_values = (
                data.coords[dim_name].values if dim_name in data.coords else []
            )
            axes_data.append(AxisData("STD_AXIS", "", axis_values))
        return axes_data


def export_to_dcm(
    db_path: str | Path, output_dcm_path: str | Path, h5_path: str | Path = None
):
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
