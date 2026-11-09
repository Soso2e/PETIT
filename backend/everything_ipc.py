"""Bounded read-only Everything IPC v2 query for Windows."""
import ctypes as c
from ctypes import wintypes as w
import struct
import time

WM_COPYDATA = 0x004A
QUERY2W = 18
FULL_PATH = 4
REPLY = 0x50455449
LIMIT = 500


def decode_paths(data):
    if len(data) < 20:
        return None
    _, count, _, flags, _ = struct.unpack_from("<5I", data)
    if flags != FULL_PATH or count > LIMIT or len(data) < 20 + count * 8:
        return None
    paths = []
    for index in range(count):
        _, offset = struct.unpack_from("<II", data, 20 + index * 8)
        if offset < 20 + count * 8 or offset + 4 > len(data):
            return None
        length, = struct.unpack_from("<I", data, offset)
        start, end = offset + 4, offset + 4 + 2 * length
        if end + 2 > len(data) or data[end:end + 2] != b"\0\0":
            return None
        paths.append(data[start:end].decode("utf-16-le", errors="replace"))
    return paths


def search(query):
    user = c.WinDLL("user32", use_last_error=True)
    user.FindWindowW.argtypes, user.FindWindowW.restype = [w.LPCWSTR, w.LPCWSTR], w.HWND
    server = next((handle for name in ("EVERYTHING_TASKBAR_NOTIFICATION", "EVERYTHING_TASKBAR_NOTIFICATION_(1.5a)")
                   if (handle := user.FindWindowW(name, None))), None)
    if not server:
        return None

    class CopyData(c.Structure):
        _fields_ = [("kind", c.c_size_t), ("size", w.DWORD), ("buffer", c.c_void_p)]

    user.CreateWindowExW.argtypes = [w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD, c.c_int, c.c_int,
                                    c.c_int, c.c_int, w.HWND, w.HMENU, w.HINSTANCE, c.c_void_p]
    user.CreateWindowExW.restype = w.HWND
    user.DestroyWindow.argtypes, user.DestroyWindow.restype = [w.HWND], w.BOOL
    proc_args = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
    user.DefWindowProcW.argtypes, user.DefWindowProcW.restype = proc_args, c.c_ssize_t
    callback_type = c.WINFUNCTYPE(c.c_ssize_t, *proc_args)
    set_proc = getattr(user, "SetWindowLongPtrW", user.SetWindowLongW)
    set_proc.argtypes, set_proc.restype = [w.HWND, c.c_int, callback_type], c.c_ssize_t
    user.SendMessageTimeoutW.argtypes = [*proc_args, w.UINT, w.UINT, c.POINTER(c.c_size_t)]
    user.SendMessageTimeoutW.restype = c.c_ssize_t
    user.PeekMessageW.argtypes = [c.POINTER(w.MSG), w.HWND, w.UINT, w.UINT, w.UINT]
    user.DispatchMessageW.argtypes, user.DispatchMessageW.restype = [c.POINTER(w.MSG)], c.c_ssize_t
    replies = []

    @callback_type
    def receive(hwnd, message, sender, param):
        if message == WM_COPYDATA and sender == server and param:
            packet = CopyData.from_address(param)
            if packet.kind == REPLY and packet.buffer and 20 <= packet.size <= 4_000_000:
                replies.append(decode_paths(c.string_at(packet.buffer, packet.size)))
                return 1
        return user.DefWindowProcW(hwnd, message, sender, param)

    # A message-only window is never visible and lives on this request's thread.
    hwnd = user.CreateWindowExW(0, "STATIC", None, 0, 0, 0, 0, 0, w.HWND(-3), None, None, None)
    if not hwnd:
        return None
    try:
        if not set_proc(hwnd, -4, receive):
            return None
        payload = struct.pack("<7I", hwnd & 0xFFFFFFFF, REPLY, 0, 0, LIMIT, FULL_PATH, 1)
        payload += ('file:"' + query.replace('"', "") + '"\0').encode("utf-16-le")
        buffer = c.create_string_buffer(payload)
        packet = CopyData(QUERY2W, len(payload), c.addressof(buffer))
        accepted = c.c_size_t()
        if not user.SendMessageTimeoutW(server, WM_COPYDATA, hwnd, c.addressof(packet), 2, 1200, c.byref(accepted)) or not accepted.value:
            return None
        message = w.MSG()
        deadline = time.monotonic() + 1.5
        while not replies and time.monotonic() < deadline:
            while user.PeekMessageW(c.byref(message), hwnd, 0, 0, 1):
                user.DispatchMessageW(c.byref(message))
            if not replies:
                time.sleep(.02)
        return replies[0] if replies else None
    finally:
        user.DestroyWindow(hwnd)
