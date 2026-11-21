"""Windows 10+ pseudo-console transport using the system ConPTY API."""

from __future__ import annotations

from contextlib import contextmanager
import ctypes as c
from ctypes import wintypes as w
import os
import subprocess
import sys


class COORD(c.Structure):
    _fields_ = [("X", c.c_short), ("Y", c.c_short)]


class STARTUPINFO(c.Structure):
    _fields_ = [("cb", w.DWORD), ("lpReserved", w.LPWSTR), ("lpDesktop", w.LPWSTR),
                ("lpTitle", w.LPWSTR), ("dwX", w.DWORD), ("dwY", w.DWORD),
                ("dwXSize", w.DWORD), ("dwYSize", w.DWORD), ("dwXCountChars", w.DWORD),
                ("dwYCountChars", w.DWORD), ("dwFillAttribute", w.DWORD), ("dwFlags", w.DWORD),
                ("wShowWindow", w.WORD), ("cbReserved2", w.WORD), ("lpReserved2", c.c_void_p),
                ("hStdInput", w.HANDLE), ("hStdOutput", w.HANDLE), ("hStdError", w.HANDLE)]


class STARTUPINFOEX(c.Structure):
    _fields_ = [("startup", STARTUPINFO), ("attributes", c.c_void_p)]


class PROCESSINFO(c.Structure):
    _fields_ = [("process", w.HANDLE), ("thread", w.HANDLE), ("pid", w.DWORD), ("tid", w.DWORD)]


def kernel():
    dll = c.WinDLL("kernel32", use_last_error=True)
    signatures = {
        "CreatePipe": ([c.POINTER(w.HANDLE), c.POINTER(w.HANDLE), c.c_void_p, w.DWORD], w.BOOL),
        "CreatePseudoConsole": ([COORD, w.HANDLE, w.HANDLE, w.DWORD, c.POINTER(w.HANDLE)], w.LONG),
        "ResizePseudoConsole": ([w.HANDLE, COORD], w.LONG),
        "ClosePseudoConsole": ([w.HANDLE], None),
        "CloseHandle": ([w.HANDLE], w.BOOL),
        "InitializeProcThreadAttributeList": ([c.c_void_p, w.DWORD, w.DWORD, c.POINTER(c.c_size_t)], w.BOOL),
        "UpdateProcThreadAttribute": ([c.c_void_p, w.DWORD, c.c_size_t, c.c_void_p, c.c_size_t,
                                       c.c_void_p, c.c_void_p], w.BOOL),
        "DeleteProcThreadAttributeList": ([c.c_void_p], None),
        "CreateProcessW": ([w.LPCWSTR, w.LPWSTR, c.c_void_p, c.c_void_p, w.BOOL, w.DWORD,
                             c.c_void_p, w.LPCWSTR, c.POINTER(STARTUPINFO), c.POINTER(PROCESSINFO)], w.BOOL),
        "WaitForSingleObject": ([w.HANDLE, w.DWORD], w.DWORD),
        "GetExitCodeProcess": ([w.HANDLE, c.POINTER(w.DWORD)], w.BOOL),
        "TerminateProcess": ([w.HANDLE, w.UINT], w.BOOL),
        "GetStdHandle": ([w.DWORD], w.HANDLE),
        "GetConsoleMode": ([w.HANDLE, c.POINTER(w.DWORD)], w.BOOL),
        "SetConsoleMode": ([w.HANDLE, w.DWORD], w.BOOL),
        "GetConsoleCP": ([], w.UINT),
        "GetConsoleOutputCP": ([], w.UINT),
        "SetConsoleCP": ([w.UINT], w.BOOL),
        "SetConsoleOutputCP": ([w.UINT], w.BOOL),
    }
    for name, (args, result) in signatures.items():
        function = getattr(dll, name)
        function.argtypes, function.restype = args, result
    return dll


def check(success):
    if not success:
        raise c.WinError(c.get_last_error())


@contextmanager
def raw_console():
    import msvcrt
    dll = kernel()
    modes = []
    binary = []
    code_pages = dll.GetConsoleCP(), dll.GetConsoleOutputCP()
    try:
        check(dll.SetConsoleCP(65001))
        check(dll.SetConsoleOutputCP(65001))
        for number, stream in ((-10, sys.stdin), (-11, sys.stdout)):
            handle, mode = dll.GetStdHandle(number), w.DWORD()
            check(dll.GetConsoleMode(handle, c.byref(mode)))
            modes.append((handle, mode.value))
            value = ((mode.value & ~(1 | 2 | 4)) | 0x200) if number == -10 else mode.value | 1 | 4
            check(dll.SetConsoleMode(handle, value))
            binary.append((stream.fileno(), msvcrt.setmode(stream.fileno(), os.O_BINARY)))
        yield
    finally:
        for fd, mode in reversed(binary):
            msvcrt.setmode(fd, mode)
        for handle, mode in reversed(modes):
            dll.SetConsoleMode(handle, mode)
        dll.SetConsoleCP(code_pages[0])
        dll.SetConsoleOutputCP(code_pages[1])


class WindowsChild:
    def __init__(self, command, env, cwd, size):
        import msvcrt
        self.dll = dll = kernel()
        self.console, self.process = w.HANDLE(), None
        self.input_fd = self.output_fd = None
        handles = []
        attributes = None
        try:
            input_read, input_write, output_read, output_write = [w.HANDLE() for _ in range(4)]
            check(dll.CreatePipe(c.byref(input_read), c.byref(input_write), None, 0))
            handles.extend((input_read, input_write))
            check(dll.CreatePipe(c.byref(output_read), c.byref(output_write), None, 0))
            handles.extend((output_read, output_write))
            result = dll.CreatePseudoConsole(COORD(size.columns, size.lines), input_read, output_write,
                                             0, c.byref(self.console))
            if result != 0:
                raise OSError(f"Could not create the Codex pseudo-console (HRESULT {result:#x})")
            length = c.c_size_t()
            dll.InitializeProcThreadAttributeList(None, 1, 0, c.byref(length))
            attributes = c.create_string_buffer(length.value)
            check(dll.InitializeProcThreadAttributeList(attributes, 1, 0, c.byref(length)))
            check(dll.UpdateProcThreadAttribute(attributes, 0, 0x20016, self.console,
                                                c.sizeof(w.HANDLE), None, None))
            startup = STARTUPINFOEX()
            startup.startup.cb = c.sizeof(startup)
            startup.attributes = c.cast(attributes, c.c_void_p)
            process = PROCESSINFO()
            environment = c.create_unicode_buffer("\0".join(
                f"{key}={env[key]}" for key in sorted(env, key=str.casefold)) + "\0\0")
            check(dll.CreateProcessW(None, c.create_unicode_buffer(subprocess.list2cmdline(command)),
                                     None, None, False, 0x80000 | 0x400, environment, str(cwd),
                                     c.byref(startup.startup), c.byref(process)))
            self.process = process.process
            dll.CloseHandle(process.thread)
            self.input_fd = msvcrt.open_osfhandle(input_write.value, os.O_WRONLY | os.O_BINARY)
            handles.remove(input_write)
            self.output_fd = msvcrt.open_osfhandle(output_read.value, os.O_RDONLY | os.O_BINARY)
            handles.remove(output_read)
        except BaseException:
            self.close()
            raise
        finally:
            if attributes:
                dll.DeleteProcThreadAttributeList(attributes)
            for handle in handles:
                dll.CloseHandle(handle)

    def read(self):
        return os.read(self.output_fd, 65536)

    def write(self, data):
        while data:
            data = data[os.write(self.input_fd, data):]

    def resize(self, size):
        result = self.dll.ResizePseudoConsole(self.console, COORD(size.columns, size.lines))
        if result != 0:
            raise OSError(f"Could not resize the Codex pseudo-console (HRESULT {result:#x})")

    def poll(self):
        if self.dll.WaitForSingleObject(self.process, 0) == 0x102:
            return None
        code = w.DWORD()
        check(self.dll.GetExitCodeProcess(self.process, c.byref(code)))
        return code.value

    def close(self):
        if self.process:
            if self.poll() is None:
                if self.input_fd is not None:
                    try:
                        self.write(b"\x03/quit\r")
                    except OSError:
                        pass
                if self.dll.WaitForSingleObject(self.process, 2000) == 0x102:
                    self.dll.TerminateProcess(self.process, 1)
            self.dll.CloseHandle(self.process)
            self.process = None
        if self.console:
            self.dll.ClosePseudoConsole(self.console)
            self.console = None
        for field in ("input_fd", "output_fd"):
            fd = getattr(self, field)
            if fd is not None:
                os.close(fd)
                setattr(self, field, None)
