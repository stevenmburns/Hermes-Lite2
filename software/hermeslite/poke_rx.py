"""Stream every receiver of an HL2 at once and measure a test carrier in each.

Talks openHPSDR Protocol 1 directly, so close any other SDR program first. Feed the RX port
a steady carrier (a signal generator, or a TinySA in generator mode at about -73 dBm).

  python3 poke_rx.py                              # 18.130 MHz carrier, all receivers the gateware reports
  python3 poke_rx.py --freq 7.1e6 --nrx 4 --lna 20
  python3 poke_rx.py --ifaddr 169.254.116.5       # discover only on the interface with this address

Needs numpy and netifaces, and hermeslite.py from this folder. The open-collector bits it sends
select the N2ADR filter board's low-pass filter for --freq.

Two passes:
  same       every receiver tuned 10 kHz below the carrier, so it should appear at +10 kHz in all of them
             at the same level.
  staggered  receiver k tuned (5 + 2.5k) kHz below the carrier, so the carrier lands at a different
             offset in each. This proves each receiver obeys its own frequency command
             (an address mix-up shows the carrier at another receiver's offset).

  python3 poke_rx.py --sweep    # response and alias rejection instead of the two passes above

--sweep keeps receiver 1 at +10 kHz as the reference and tunes the others so the carrier sits at
SWEEP_OFFSETS from their centre, two passes of up to 11. Each receiver's level is read at the
frequency where the carrier must land (folded into +-rate/2 past the band edge), whether or not it
is the strongest bin, and printed against the gateware design response when the cic_fir bench's
coefficients are in this checkout. A strong carrier (about -15 dBFS) is needed to see 100 dB.
"""
import argparse, select, socket, struct, sys, time
import numpy as np
import hermeslite

RATE_CODES = {48000: 0, 96000: 1, 192000: 2, 384000: 3}
FREQ_ADDR = [0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x12, 0x13, 0x14, 0x15, 0x16]
# N2ADR filter board bits, as in Quisk's Hermes-Lite settings
FILTERS = [(2.0e6, 0b0000001), (4.0e6, 0b1000010), (7.5e6, 0b1000100), (14.5e6, 0b1001000),
           (21.5e6, 0b1010000), (30.0e6, 0b1100000)]
PACKETS_PER_S = 48000 / 126       # EP2 packets the radio consumes: 2 frames x 63 TX samples at 48 kHz


def filter_bits(freq):
    for top, bits in FILTERS:
        if freq <= top:
            return bits
    return FILTERS[-1][1]


class HL2Stream:
    def __init__(self, radio_ip, nrx, rate, lna_db, rf_freq, ifaddr=None):
        self.addr = (radio_ip, 1024)
        self.nrx, self.rate = nrx, rate
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8 * 1024 * 1024)
        self.sock.bind((ifaddr or '', 0))
        self.seq = 0
        self.regs = {}
        # Address 0: C1[1:0] rate, C2[7:1] open-collector (filter) bits, C4[6:3] receivers - 1, C4[2] duplex
        self.regs[0x00] = bytes([RATE_CODES[rate], filter_bits(rf_freq) << 1, 0, ((nrx - 1) << 3) | 0x04])
        # Address 0x0A: C4[6] = 1 selects the HL2 gain format, C4[5:0] = gain + 12
        self.regs[0x0A] = bytes([0, 0, 0, 0x40 | (lna_db + 12)])
        self.regs[0x01] = struct.pack('!I', int(rf_freq))          # TX frequency, unused here
        self.cycle = []
        self.rx_seq_last = None
        self.dropped = 0
        self.overload = 0

    def set_freqs(self, freqs):
        for k, f in enumerate(freqs):
            self.regs[FREQ_ADDR[k]] = struct.pack('!I', int(round(f)))
        self.cycle = [a for a in sorted(self.regs) if a != 0x00]

    def _frame(self, addr):
        return bytes([0x7F, 0x7F, 0x7F, addr << 1]) + self.regs[addr] + bytes(504)

    def send_packet(self):
        addr = self.cycle[self.seq % len(self.cycle)]
        pkt = struct.pack('!BBBBI', 0xEF, 0xFE, 0x01, 0x02, self.seq) + self._frame(0x00) + self._frame(addr)
        self.sock.sendto(pkt, self.addr)
        self.seq += 1

    def start(self):
        for _ in range(2 * len(self.cycle)):      # load every register before streaming
            self.send_packet()
        self.sock.sendto(bytes([0xEF, 0xFE, 0x04, 0x01]) + bytes(60), self.addr)

    def stop(self):
        self.sock.sendto(bytes([0xEF, 0xFE, 0x04, 0x00]) + bytes(60), self.addr)

    def parse(self, pkt, out):
        if len(pkt) != 1032 or pkt[:4] != b'\xef\xfe\x01\x06':
            return
        seq = struct.unpack('!I', pkt[4:8])[0]
        if self.rx_seq_last is not None and seq != (self.rx_seq_last + 1) & 0xFFFFFFFF:
            self.dropped += 1
        self.rx_seq_last = seq
        step = 6 * self.nrx + 2
        nsamp = 504 // step
        for f in (pkt[8:520], pkt[520:1032]):
            if f[:3] != b'\x7f\x7f\x7f':
                continue
            if (f[3] >> 1) == 0 and f[4] & 0x01:
                self.overload += 1
            body = np.frombuffer(f[8:8 + nsamp * step], dtype=np.uint8).reshape(nsamp, step)[:, :6 * self.nrx]
            b = body.reshape(nsamp, self.nrx, 2, 3).astype(np.int32)
            v = (b[..., 0] << 16) | (b[..., 1] << 8) | b[..., 2]
            v = np.where(v & 0x800000, v - 0x1000000, v)
            out.append(v[..., 0] - 1j * v[..., 1])                  # nsamp x nrx; HL2 spectrum is mirrored, so conjugate

    def capture(self, seconds, settle):
        """Run for settle + seconds, keep TX packets flowing, return samples (n x nrx)."""
        chunks, t0 = [], time.monotonic()
        sent = 0
        while True:
            now = time.monotonic() - t0
            if now > settle + seconds:
                break
            while sent < now * PACKETS_PER_S:
                self.send_packet(); sent += 1
            r, _, _ = select.select([self.sock], [], [], 0.002)
            while r:
                pkt, _ = self.sock.recvfrom(2048)
                if now >= settle:
                    self.parse(pkt, chunks)
                r, _, _ = select.select([self.sock], [], [], 0)
        return np.concatenate(chunks) if chunks else np.zeros((0, self.nrx))


SWEEP_OFFSETS = [20e3, 35e3, 50e3, 60e3, 70e3, 75e3, 85e3, 100e3, 110e3, 125e3, 140e3,
                 150e3, 160e3, 175e3, 200e3, 225e3, 250e3, 300e3, 400e3, 600e3]


def fold(f, rate):
    """Where an offset f appears in a complex stream sampled at rate."""
    return (f + rate / 2) % rate - rate / 2


def design_response_db(offset, chain='cicfir'):
    """Design response relative to DC.
    cicfir (75.13 and later): CIC N=4 R=16, CIC N=4 R=5, 109-tap FIR /5; None if the cic_fir
    bench's coefficient file is not in this checkout.
    cicrx (75.12): CIC N=4 R=16, then CIC N=4 R=25, no FIR."""
    import os

    def stage(f, rate_in, r, n):
        x = np.pi * f / rate_in
        return 1.0 if abs(np.sin(x)) < 1e-15 else abs(np.sin(r * x) / (r * np.sin(x))) ** n
    if chain == 'cicrx':
        g = stage(offset, 76.8e6, 16, 4) * stage(offset, 4.8e6, 25, 4)
        return 20 * np.log10(max(g, 1e-30))
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'gateware',
                        'sim_cocotb', 'cic_fir', 'coefs.txt')
    try:
        with open(path) as fp:
            fp.readline()
            h = np.array([int(l) for l in fp if l.strip()], dtype=float)
    except OSError:
        return None
    k = np.arange(len(h))
    fir = abs(np.exp(-2j * np.pi * offset / 960e3 * k) @ h) / h.sum()
    g = stage(offset, 76.8e6, 16, 4) * stage(offset, 4.8e6, 5, 4) * fir
    return 20 * np.log10(max(g, 1e-30))


def level_at(x, rate, f0):
    """Power (dBFS) within +-3 bins of f0, and the median floor per bin away from it."""
    n = 1 << int(np.floor(np.log2(len(x))))
    n = min(n, 1 << 16)
    x = x[-n:] / float(1 << 23)
    w = np.blackman(n)
    p = np.abs(np.fft.fftshift(np.fft.fft(x * w)) / w.sum()) ** 2
    f = np.fft.fftshift(np.fft.fftfreq(n, 1.0 / rate))
    k = int(np.argmin(np.abs(f - f0)))
    lvl = 10 * np.log10(p[max(k - 3, 0):k + 4].sum() + 1e-30)
    floor = 10 * np.log10(np.median(p[np.abs(f - f0) > 3000]) + 1e-30)
    return lvl, floor


def run_sweep(hl, rf, args, chain):
    groups = [SWEEP_OFFSETS[i:i + hl.nrx - 1] for i in range(0, len(SWEEP_OFFSETS), hl.nrx - 1)]
    print(f'\nsweep ({chain} design): receiver 1 at +10 kHz is the reference; level read where the carrier must land')
    print('  offset kHz  lands at kHz   level dBc   design dBc   floor dBc/bin')
    for g in groups:
        offsets = [10e3] + g
        hl.set_freqs([rf - o for o in offsets] + [rf - 10e3] * (hl.nrx - len(offsets)))
        hl.dropped = hl.overload = 0
        x = hl.capture(args.seconds, args.settle)
        if len(x) < 4096:
            print('  not enough data'); return
        # The generator's frequency error moves every receiver's carrier by the same amount:
        # find it on the reference (strongest bin within 2 kHz of +10 kHz) and apply it to all.
        _, fpk, _ = measure(x[:, 0], args.rate, 10e3)
        err = fpk - 10e3 if abs(fpk - 10e3) < 2000 else 0.0
        ref, _ = level_at(x[:, 0], args.rate, 10e3 + err)
        for k, o in enumerate(g, start=1):
            lvl, fl = level_at(x[:, k], args.rate, fold(o + err, args.rate))
            d = design_response_db(o, chain)
            dtxt = f'{d - design_response_db(10e3, chain):10.1f}' if d is not None else '         -'
            print(f'  {o / 1e3:10.1f}  {fold(o, args.rate) / 1e3:+12.1f}  {lvl - ref:10.1f}   {dtxt}   {fl - ref:13.1f}')
        print(f'  (reference {ref:.1f} dBFS, carrier {err:+.0f} Hz off; {hl.dropped} dropped packets, '
              f'{hl.overload} ADC overload flags)')


def measure(x, rate, expect_hz):
    """Carrier level (dBFS), its offset, and the noise floor per bin (dBFS) for one receiver."""
    n = 1 << int(np.floor(np.log2(len(x))))
    n = min(n, 1 << 16)
    x = x[-n:] / float(1 << 23)
    w = np.blackman(n)
    spec = np.fft.fftshift(np.fft.fft(x * w)) / w.sum()
    p = np.abs(spec) ** 2
    f = np.fft.fftshift(np.fft.fftfreq(n, 1.0 / rate))
    k = int(np.argmax(p))
    carrier = 10 * np.log10(p[max(k - 3, 0):k + 4].sum() + 1e-30)
    near = np.abs(f - expect_hz) > 2000
    inband = np.abs(f) < 35000                                      # the clean part of a CIC-only receiver
    floor = 10 * np.log10(np.median(p[near & inband]) + 1e-30)
    return carrier, f[k], floor


def run_pass(name, hl, rf, offsets, args):
    freqs = [rf - o for o in offsets]
    hl.set_freqs(freqs)
    hl.dropped = hl.overload = 0
    x = hl.capture(args.seconds, args.settle)
    print(f'\n{name}: {len(x):,} samples per receiver, {hl.dropped} dropped packets, '
          f'{hl.overload} ADC overload flags')
    if len(x) < 4096:
        print('  not enough data'); return None
    rows = []
    for k in range(hl.nrx):
        c, fpk, fl = measure(x[:, k], args.rate, offsets[k])
        ok = abs(fpk - offsets[k]) < 200    # allows for the TinySA's frequency error
        rows.append((k + 1, offsets[k], fpk, c, fl, ok))
    ref = rows[0][3]
    print('  rx  expected Hz   peak Hz   carrier dBFS  vs rx1 dB  floor dBFS/bin  result')
    for (rx, exp, fpk, c, fl, ok) in rows:
        print(f'  {rx:2d}  {exp:+10.0f}  {fpk:+9.0f}  {c:12.2f}  {c - ref:+9.2f}  {fl:14.1f}  '
              f'{"ok" if ok else "WRONG FREQUENCY"}')
    spread = max(r[3] for r in rows) - min(r[3] for r in rows)
    bad = [r[0] for r in rows if not r[5]]
    print(f'  carrier spread across receivers: {spread:.2f} dB;  wrong frequency: {bad or "none"}')
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--freq', type=float, default=18.130e6, help='carrier frequency, Hz')
    ap.add_argument('--nrx', type=int, default=0, help='receivers to stream (default: what the gateware reports)')
    ap.add_argument('--rate', type=int, default=192000, choices=sorted(RATE_CODES))
    ap.add_argument('--lna', type=int, default=20, help='HL2 LNA gain, -12 to 48 dB')
    ap.add_argument('--seconds', type=float, default=1.0)
    ap.add_argument('--settle', type=float, default=0.5)
    ap.add_argument('--sweep', action='store_true', help='response and alias rejection sweep (see top)')
    ap.add_argument('--ifaddr', default=None, help="this computer's address on the radio's network (default: try every interface)")
    args = ap.parse_args()

    found = hermeslite.discover(ifaddr=args.ifaddr, verbose=0) if args.ifaddr else hermeslite.discover_all(verbose=0)
    if not found:
        sys.exit('No HL2 answered.')
    if len(found) > 1:
        sys.exit('More than one HL2 answered. Use --ifaddr to pick the interface.')
    (addr, r) = found[0]
    print(f'radio {addr[0]}  gateware {r.gateware}  receivers {r.receivers}  board {r.board_id}')
    if r.type != 2:
        sys.exit('The radio is already streaming to another program. Close Quisk first.')
    nrx = args.nrx or r.receivers
    if not 1 <= nrx <= min(12, r.receivers):
        sys.exit(f'--nrx must be 1..{min(12, r.receivers)}')

    hl = HL2Stream(addr[0], nrx, args.rate, args.lna, args.freq, args.ifaddr)
    hl.set_freqs([args.freq - 10000] * nrx)
    hl.start()
    try:
        if args.sweep:
            # 75.12 is the CIC-only cicrx build; later 12-receiver builds have the FIR.
            chain = 'cicrx' if str(r.gateware) in ('75.12', '75.11', '75.10') else 'cicfir'
            run_sweep(hl, args.freq, args, chain)
            return
        run_pass('same (all receivers 10 kHz below the carrier)', hl, args.freq, [10000.0] * nrx, args)
        run_pass('staggered (receiver k tuned 5 + 2.5k kHz below)', hl, args.freq,
                 [5000.0 + 2500.0 * k for k in range(nrx)], args)
    finally:
        hl.stop()


if __name__ == '__main__':
    main()
