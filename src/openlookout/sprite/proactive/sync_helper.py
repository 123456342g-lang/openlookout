import sys, time, psutil
chunks = []
for _ in range(int(float(sys.argv[1]) * 16)):
    if psutil.swap_memory().free < 2 * 2**30: break
    b = bytearray(64 * 2**20); b[::4096] = b"\x01" * len(range(0, len(b), 4096)); chunks.append(b); time.sleep(0.05)
while True: time.sleep(5)
