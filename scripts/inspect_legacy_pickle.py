"""Read-only legacy inspection with an explicit data-class unpickler allowlist.

Analysis-only dependencies: uv run --no-project --with pandas==2.2.3 --with numpy==1.26.4.
Never import the legacy repository or execute its pipeline.
"""

import argparse
import pickle
from collections import OrderedDict
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from dateutil.parser._parser import parser, parserinfo
from numpy.core.multiarray import _reconstruct, scalar
from numpy.core.numeric import _frombuffer
from pandas._libs.internals import _unpickle_block
from pandas.core.indexes.base import _new_Index
from pandas.core.internals.managers import BlockManager

ALLOWED = {
    ("collections", "OrderedDict"): OrderedDict,
    ("dateutil.parser._parser", "parser"): parser,
    ("dateutil.parser._parser", "parserinfo"): parserinfo,
    ("datetime", "datetime"): datetime,
    ("datetime", "date"): date,
    ("numpy.core.numeric", "_frombuffer"): _frombuffer,
    ("pandas.core.frame", "DataFrame"): pd.DataFrame,
    ("pandas.core.internals.managers", "BlockManager"): BlockManager,
    ("pandas._libs.internals", "_unpickle_block"): _unpickle_block,
    ("pandas.core.indexes.base", "_new_Index"): _new_Index,
    ("pandas.core.indexes.base", "Index"): pd.Index,
    ("pandas.core.indexes.range", "RangeIndex"): pd.RangeIndex,
    ("pandas.core.indexes.numeric", "Int64Index"): pd.Index,
    ("numpy.core.multiarray", "_reconstruct"): _reconstruct,
    ("numpy.core.multiarray", "scalar"): scalar,
    ("numpy", "ndarray"): np.ndarray,
    ("numpy", "dtype"): np.dtype,
    ("builtins", "slice"): slice,
}


class DataOnlyUnpickler(pickle.Unpickler):
    def find_class(self, module, name):
        target = ALLOWED.get((module, name))
        if target is None:
            raise pickle.UnpicklingError(f"Unapproved pickle global: {module}.{name}")
        return target

    def persistent_load(self, pid):
        raise pickle.UnpicklingError("Persistent references are not supported")


def load_data(path):
    with Path(path).open("rb") as handle:
        return DataOnlyUnpickler(handle).load()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    value = load_data(args.path)
    print(type(value).__name__, getattr(value, "shape", len(value)), flush=True)
    if isinstance(value, pd.DataFrame):
        print(list(value.columns), flush=True)
    elif isinstance(value, list) and value:
        print(
            "first element keys:",
            list(value[0]) if isinstance(value[0], dict) else type(value[0]).__name__,
        )
