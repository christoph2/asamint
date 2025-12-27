import logging
from pathlib import Path

from asamint.calibration.msrsw_db import MSRSWDatabase, Parser


def import_cdf_to_db(
    xml_path: str | Path, db_path: str | Path, logger: logging.Logger = None
):
    logger = logger or logging.getLogger(__name__)
    logger.info(f"Importing {xml_path} to {db_path}")

    db = MSRSWDatabase(db_path)
    try:
        db.begin_transaction()
        # Parser.__init__ handles the parsing and committing to DB
        Parser(str(xml_path), db)
        logger.info("Import completed successfully.")
        return True
    except Exception as e:
        logger.error(f"Import failed: {e}")
        db.rollback_transaction()
        return False
    finally:
        # Parser actually closes the DB connection in its __init__ (line 25690 of msrsw_db.py)
        # but let's be safe if it didn't reach that point.
        if not db._closed:
            db.close()


class CDFImporter:
    def __init__(self, logger: logging.Logger = None):
        self.logger = logger or logging.getLogger(__name__)

    def import_file(self, xml_path: str | Path, db_path: str | Path):
        return import_cdf_to_db(xml_path, db_path, self.logger)
