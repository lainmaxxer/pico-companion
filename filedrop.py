"""Receive files dragged from Explorer onto a Tk window (Windows, standard library only).

Tk has no built-in file drop, so this hooks the window's WM_DROPFILES message through ctypes.
Dropped paths are queued from inside the window procedure and handed to the callback from Tk's own
timer: calling Tk from inside the window procedure crashes Python.
"""
import ctypes
from ctypes import wintypes

WM_DROPFILES, GWLP_WNDPROC = 0x0233, -4
WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

user32, shell32 = ctypes.windll.user32, ctypes.windll.shell32
user32.SetWindowLongPtrW.restype = ctypes.c_void_p
user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
user32.CallWindowProcW.restype = ctypes.c_ssize_t
user32.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.GetParent.restype = wintypes.HWND
user32.GetParent.argtypes = [wintypes.HWND]
shell32.DragQueryFileW.argtypes = [ctypes.c_void_p, wintypes.UINT, wintypes.LPWSTR, wintypes.UINT]
shell32.DragFinish.argtypes = [ctypes.c_void_p]
shell32.DragAcceptFiles.argtypes = [wintypes.HWND, wintypes.BOOL]


def enable_file_drop(root, callback):
    """Call callback(list_of_paths) on Tk's thread whenever files are dropped on the window `root`."""
    hwnd = user32.GetParent(root.winfo_id())
    old, queue = {}, []

    def poll():
        while queue:
            callback(queue.pop(0))
        root.after(100, poll)

    def proc(h, msg, wparam, lparam):
        if msg == WM_DROPFILES:
            count = shell32.DragQueryFileW(wparam, 0xFFFFFFFF, None, 0)
            paths = []
            for i in range(count):
                n = shell32.DragQueryFileW(wparam, i, None, 0)
                buf = ctypes.create_unicode_buffer(n + 1)
                shell32.DragQueryFileW(wparam, i, buf, n + 1)
                paths.append(buf.value)
            shell32.DragFinish(wparam)
            queue.append(paths)
            return 0
        return user32.CallWindowProcW(old["proc"], h, msg, wparam, lparam)

    root._drop_proc = WNDPROC(proc)   # keep a reference, or it is garbage collected and Tk crashes
    old["proc"] = user32.SetWindowLongPtrW(hwnd, GWLP_WNDPROC, ctypes.cast(root._drop_proc, ctypes.c_void_p))
    shell32.DragAcceptFiles(hwnd, True)
    poll()
    return hwnd
