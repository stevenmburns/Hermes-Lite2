#!/usr/bin/env python3
"""Convert Quartus .mif files into $readmemh files for altsyncram_model.v.

usage: mif2mem.py OUTPUT_DIR INPUT.mif [INPUT.mif ...]

Each output keeps its input's file name, because the RTL passes that name to
altsyncram as init_file.  Reading the .mif itself keeps the simulation on the
same ROM contents that Quartus programs into the FPGA.
"""

import os
import re
import sys

RADIX = {"HEX": 16, "DEC": 10, "UNS": 10, "BIN": 2, "OCT": 8}


def parse_mif(path):
    with open(path) as f:
        text = f.read()
    text = re.sub(r"--.*", "", text)
    text = re.sub(r"%.*?%", "", text, flags=re.S)
    text = re.sub(r"^\s*;.*$", "", text, flags=re.M)

    def header(name):
        match = re.search(rf"{name}\s*=\s*(\w+)\s*;", text, re.I)
        if match is None:
            raise ValueError(f"{path}: missing {name}")
        return match.group(1)

    depth = int(header("DEPTH"))
    width = int(header("WIDTH"))
    addr_radix = RADIX[header("ADDRESS_RADIX").upper()]
    data_radix = RADIX[header("DATA_RADIX").upper()]

    body = re.search(r"CONTENT\s+BEGIN(.*?)END\s*;", text, re.S | re.I)
    if body is None:
        raise ValueError(f"{path}: missing CONTENT BEGIN ... END")

    words = [None] * depth
    for entry in body.group(1).split(";"):
        entry = entry.strip()
        if not entry:
            continue
        addr, value = (part.strip() for part in entry.split(":"))
        word = int(value, data_radix)
        if word >> width:
            raise ValueError(f"{path}: value {value} exceeds {width} bits")
        span = re.fullmatch(r"\[(\w+)\.\.(\w+)\]", addr)
        if span:
            first = int(span.group(1), addr_radix)
            last = int(span.group(2), addr_radix)
        else:
            first = last = int(addr, addr_radix)
        for index in range(first, last + 1):
            words[index] = word

    missing = [i for i, word in enumerate(words) if word is None]
    if missing:
        raise ValueError(f"{path}: {len(missing)} undefined addresses")
    return width, words


def main(argv):
    if len(argv) < 3:
        print(__doc__, file=sys.stderr)
        return 2
    out_dir = argv[1]
    for path in argv[2:]:
        width, words = parse_mif(path)
        digits = (width + 3) // 4
        out_path = os.path.join(out_dir, os.path.basename(path))
        with open(out_path, "w") as f:
            f.writelines(f"{word:0{digits}x}\n" for word in words)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
