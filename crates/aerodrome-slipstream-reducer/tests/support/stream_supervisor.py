"""Test-only supervisor: actual child exit gates the private completion pipe."""
import hashlib
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import time

root, case = Path(sys.argv[1]), sys.argv[2]
config = json.loads((root / "stream-config.json").read_bytes())
request = json.loads((root / "stream-request.json").read_bytes())
original = (root / "input").read_bytes()
input_bytes = original[:-1] if case == "short-input" else original
native_exit = 7 if case == "failed-native" else 0
read_fd, write_fd = os.pipe()
if case == "regular-control":
    os.close(read_fd)
    read_fd = os.open(root / "input", os.O_RDONLY)
native = subprocess.Popen(
    [sys.executable, "-c", "import sys;sys.stdout.buffer.write(bytes.fromhex(sys.argv[1]));sys.stdout.buffer.flush();sys.exit(int(sys.argv[2]))", input_bytes.hex(), str(native_exit)],
    stdout=subprocess.PIPE,
)
args = config["args"] + ["--upstream-completion-fd", str(read_fd)]
producer = subprocess.Popen(args, stdin=native.stdout, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, pass_fds=(read_fd,))
native.stdout.close()
os.close(read_fd)
status = native.wait(timeout=20)
prefix = b""
provisional_before_control = False
if case not in ("short-input", "regular-control"):
    ready, _, _ = select.select([producer.stdout], [], [], 20)
    assert ready, "producer did not stream before completion"
    prefix = os.read(producer.stdout.fileno(), 52)
    assert len(prefix) == 52 and prefix[:4] == b"BCF1", "missing provisional frame"
    provisional_before_control = True
    time.sleep(0.03)
    assert producer.poll() is None, "producer exited before native completion proof"
    assert not (Path(config["output"]) / "complete.json").exists()
if status == 0 and case not in ("short-input", "regular-control"):
    completion = {
        "format": "pinax.backfill.upstream-completion/v1",
        "request": request,
        "native_exit_code": status,
        "input_sha256": hashlib.sha256(input_bytes).hexdigest(),
        "input_bytes": len(input_bytes),
        "head": {"block_number": config["head"]["block_number"], "block_hash": config["head"]["block_hash"]},
    }
    if case == "bad-nonce":
        completion["request"]["attempt_nonce"] = "99" * 32
    if case == "bad-digest":
        completion["input_sha256"] = "aa" * 32
    if case == "stale-lineage":
        completion["request"]["engine_lineage_before"] = "bb" * 32
    data = (json.dumps(completion, indent=2) + "\n").encode()
    if case == "extra-control":
        data += b"\n"
    if case == "short-control":
        data = data[:-10]
    os.write(write_fd, data)
os.close(write_fd)
tail, stderr = producer.communicate(timeout=20)
Path(config["output"] + ".stdout").write_bytes(prefix + tail)
Path(config["output"] + ".stderr").write_bytes(stderr)
print(json.dumps({"native_exit": status, "producer_exit": producer.returncode,
                  "provisional_before_control": provisional_before_control}))
