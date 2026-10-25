"""Victron VE.Direct text protocol (MPPT 75/10). Optional: only used when the solar module is fitted."""
from __future__ import annotations


def parse_block(lines) -> dict:
    """one VE.Direct block -> dict with SI units. Checksum line is ignored (the USB cable already checks)."""
    raw = {}
    for ln in lines:
        if "\t" in ln:
            k, v = ln.rstrip("\r\n").split("\t", 1); raw[k] = v
    f = lambda k, s=1.0: float(raw[k]) * s if k in raw and raw[k].lstrip("-").isdigit() else None
    return dict(battery_v=f("V", 1e-3), battery_a=f("I", 1e-3), panel_v=f("VPV", 1e-3), panel_w=f("PPV"),
                state=int(raw["CS"]) if raw.get("CS", "").isdigit() else None, yield_today_wh=f("H20", 10.0),
                error=int(raw["ERR"]) if raw.get("ERR", "").isdigit() else None)


STATES = {0: "off", 2: "fault", 3: "bulk", 4: "absorption", 5: "float"}
