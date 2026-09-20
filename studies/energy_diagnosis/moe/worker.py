"""Private pipe RPC worker. Backend stdout is redirected before imports/load."""
import json
import os
import sys
import traceback


def main():
    mode = sys.argv[1]
    # Preserve a private protocol descriptor; native printf must not corrupt JSON RPC.
    protocol = os.fdopen(os.dup(sys.stdout.fileno()), "w", buffering=1)
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    device = None
    methods = {
        "snapshot": "snapshot",
        "prepare": "prepare",
        "cancel": "cancel",
        "drain": "drain",
        "transfers": "transfers",
        "demands": "demands_rpc",
        "generate": "generate",
    }
    for line in sys.stdin:
        message = json.loads(line)
        try:
            method = message["method"]
            if method == "init":
                if device is not None:
                    raise RuntimeError("worker already initialized")
                if mode == "native":
                    from .native_backend import NativeDevice as Device
                elif mode == "fixture":
                    from .fixture_backend import FixtureDevice as Device
                else:
                    raise ValueError("unknown backend mode")
                device = Device(message["args"])
                result = device.boot
            else:
                result = getattr(device, methods[method])(message["args"])
            response = dict(id=message["id"], ok=True, result=result)
        except Exception as exc:
            traceback.print_exc(file=sys.stderr)
            response = dict(
                id=message["id"], ok=False, error=f"{type(exc).__name__}: {exc}"
            )
        protocol.write(json.dumps(response) + "\n")


if __name__ == "__main__":
    main()
