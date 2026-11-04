"""Point the backend at a temp data folder and a nonexistent env file, so
integration tests never open the real database, statement files or secrets.
The folder is deleted when the run ends."""

import atexit
import os
import shutil
import tempfile

_data_dir = tempfile.mkdtemp(prefix="balanceai-integ-")
os.environ["BALANCEAI_DATA_DIR"] = _data_dir
os.environ["BALANCEAI_ENV_FILE"] = os.path.join(_data_dir, "nonexistent.env")
atexit.register(shutil.rmtree, _data_dir, ignore_errors=True)
