from schema import And, Schema, Use

STOFS_SCHEMA = Schema(
    {
        "type": And(str, lambda s: s.upper() in ["ADCIRC", "SCHISM"]),
        "name": Use(str),
        "version": Use(str),
        "script_directory": Use(str),
    }
)
