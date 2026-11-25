"""Port of openFPGALoader v1.2.0 FsParser::parse() checksum step for GW2A-18 (nb_line 1342, padding 0).
Shows where 'checksum data is truncated' triggers and why. Usage: python fsparse_port.py file.fs [fix]   (fix: treat a key of 0 as "no key", the Apicula convention)"""
import sys

FIX = len(sys.argv) > 2

def main(path):
    hdr, data, comp, k8, k4, k2, crc, clen = [], [], False, 0, 0, 0, False, 0
    in_hdr = True
    for ln in open(path):
        ln = ln.strip()
        if not ln or ln.startswith("//"):
            continue
        if in_hdr:
            key, val = int(ln[:8], 2), int(ln, 2)
            if key == 0x10 and len(ln) == 64:
                comp = bool(val >> 13 & 1)
            elif key == 0x51 and len(ln) == 64:
                k8, k4, k2 = (val >> 16) & 255, (val >> 8) & 255, val & 255
            elif key == 0x3B and len(ln) == 32:
                in_hdr, crc, clen = False, bool(val >> 23 & 1), val & 0xFFFF
            continue
        data.append(ln)
    drop = 6 * 8 + (16 if crc else 0)
    nb = min(1342, clen)
    print(f"compressed={comp} keys 8Z={k8} 4Z={k4} 2Z={k2} lines={len(data)} used={nb} crc={crc}")
    tmp = 0
    lit0 = 0
    for l in data[:nb]:
        pl = l[: len(l) - drop]
        for i in range(0, len(pl), 8):
            c = int(pl[i:i + 8], 2)
            if not comp:
                tmp += 8
            elif c == k8:
                tmp += 64
            elif c == k4 and (k4 or not FIX):
                tmp += 32
                lit0 += c == 0
            elif c == k2 and (k2 or not FIX):
                tmp += 16
                lit0 += c == 0
            else:
                tmp += 8
    print(f"checksum bits={tmp}  mod16={tmp % 16}  literal 0x00 bytes read as 4Z/2Z key={lit0}")
    print("FsParser: checksum data is truncated" if tmp % 16 else "OK")

main(sys.argv[1])
