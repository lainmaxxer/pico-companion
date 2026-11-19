"""Serial connection to a pico controller's built-in CLI (Windows, standard library only).

`Serial` is a minimal non-blocking COM port built on the Win32 API (so no pyserial is needed), `find_ports()` lists
the COM ports, and `Device` wraps a port as a thread-safe "send a command, get the reply lines" object.
"""
import ctypes
import re
import threading
import time
from ctypes import wintypes


class Serial:
    GENERIC_RW = 0xC0000000
    OPEN_EXISTING = 3

    class TIMEOUTS(ctypes.Structure):
        _fields_ = [(n, wintypes.DWORD) for n in (
            "ReadIntervalTimeout", "ReadTotalTimeoutMultiplier", "ReadTotalTimeoutConstant",
            "WriteTotalTimeoutMultiplier", "WriteTotalTimeoutConstant")]

    def __init__(self, port):
        k = ctypes.windll.kernel32
        k.CreateFileW.restype = wintypes.HANDLE
        k.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                  wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        k.ReadFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                               ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
        k.WriteFile.argtypes = k.ReadFile.argtypes
        k.SetCommTimeouts.argtypes = [wintypes.HANDLE, ctypes.POINTER(self.TIMEOUTS)]
        k.EscapeCommFunction.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        self.k = k
        h = k.CreateFileW("\\\\.\\" + port, self.GENERIC_RW, 0, None, self.OPEN_EXISTING, 0, None)
        if h in (None, wintypes.HANDLE(-1).value):
            raise OSError(f"Cannot open {port} (in use by another program?)")
        self.h = h
        # Non-blocking reads: return immediately with whatever is buffered.
        k.SetCommTimeouts(h, ctypes.byref(self.TIMEOUTS(0xFFFFFFFF, 0, 0, 0, 0)))
        k.EscapeCommFunction(h, 5)  # SETDTR - firmware only talks when DTR is up

    def read(self):
        buf = ctypes.create_string_buffer(4096)
        n = wintypes.DWORD(0)
        self.k.ReadFile(self.h, buf, 4096, ctypes.byref(n), None)
        return buf.raw[:n.value].decode("utf-8", "replace")

    def write(self, text):
        data = text.encode()
        n = wintypes.DWORD(0)
        self.k.WriteFile(self.h, data, len(data), ctypes.byref(n), None)

    def close(self):
        self.k.CloseHandle(self.h)


def find_ports():
    """All COM ports Windows lists, unique and in numeric order (read from the registry)."""
    import winreg
    ports = []
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DEVICEMAP\SERIALCOMM") as k:
            for i in range(winreg.QueryInfoKey(k)[1]):
                ports.append(winreg.EnumValue(k, i)[1])
    except OSError:
        pass
    return sorted(set(ports), key=lambda p: int(re.sub(r"\D", "", p) or 0))


class Device:
    """Thread-safe request/response wrapper over the CLI. `prompt` is the CLI prompt, e.g. "musec_pico>"."""

    def __init__(self, port, prompt):
        self.prompt = prompt
        self.ser = Serial(port)
        self.lock = threading.Lock()
        time.sleep(0.5)          # firmware prints a banner ~200 ms after DTR
        self.ser.read()
        self.ask("")             # sync to a fresh prompt

    def ask(self, cmd, timeout=3.0):
        with self.lock:
            self.ser.read()
            self.ser.write(cmd + "\r")
            out, end = "", time.time() + timeout
            while time.time() < end:
                time.sleep(0.02)
                out += self.ser.read()
                if out.rstrip().endswith(self.prompt):
                    break
            lines = [l.strip() for l in out.replace("\r", "\n").split("\n")]
            lines = [l for l in lines if l and l != cmd and not l.startswith(self.prompt)
                     and not l.startswith("Save requested") and not l.startswith("Program Flash")]
            return lines

    def close(self):
        self.ser.close()
