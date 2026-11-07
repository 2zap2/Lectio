"""Persist session cookies privately; Windows uses current-user DPAPI.

The long-lived Lectio cookie remains in Chromium's native cookie store. This
extra file retains session-only cookies across browser restarts without changing
their server-side lifetimes. No encryption key is stored beside this file.
"""
from __future__ import annotations

import json
import os
from pathlib import Path


_MAGIC = b"LECTIO-DPAPI-v1\x00"


def _dpapi(data: bytes, *, decrypt: bool = False) -> bytes:
    """Protect/unprotect for the current Windows user, without UI prompts."""
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    output = Blob()
    if decrypt:
        operation = crypt32.CryptUnprotectData
        operation.argtypes = [ctypes.POINTER(Blob), ctypes.POINTER(wintypes.LPWSTR),
                              ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                              wintypes.DWORD, ctypes.POINTER(Blob)]
        description = None
    else:
        operation = crypt32.CryptProtectData
        operation.argtypes = [ctypes.POINTER(Blob), wintypes.LPCWSTR,
                              ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                              wintypes.DWORD, ctypes.POINTER(Blob)]
        description = "Lectio Sync session cookies"
    operation.restype = wintypes.BOOL
    # CRYPTPROTECT_UI_FORBIDDEN. Deliberately do not use LOCAL_MACHINE scope.
    if not operation(ctypes.byref(source), description, None, None, None, 1, ctypes.byref(output)):
        raise OSError("Windows could not protect/unprotect the saved session cookies")
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    try:
        return ctypes.string_at(output.data, output.size)
    finally:
        kernel32.LocalFree(ctypes.cast(output.data, ctypes.c_void_p))


def save_session_cookies(profile: Path, cookies: list) -> None:
    payload = json.dumps(cookies).encode("utf-8")
    if os.name == "nt":
        protected = _dpapi(payload)
        if _dpapi(protected, decrypt=True) != payload:
            raise OSError("Saved session cookie protection could not be verified")
        payload = _MAGIC + protected
        target = profile / "session-cookies.dpapi"
    else:
        target = profile / "session-cookies.json"
    temporary = target.with_suffix(".tmp")
    with temporary.open("wb") as stream:
        if os.name != "nt":
            os.chmod(temporary, 0o600)
        stream.write(payload)
    temporary.replace(target)
    if os.name == "nt":
        # Remove plaintext only after the encrypted write and decrypt check.
        (profile / "session-cookies.json").unlink(missing_ok=True)


def load_session_cookies(profile: Path) -> list:
    legacy = profile / "session-cookies.json"
    encrypted = profile / "session-cookies.dpapi"
    if os.name == "nt" and encrypted.exists():
        payload = encrypted.read_bytes()
        if not payload.startswith(_MAGIC):
            raise ValueError("Saved session cookie format is invalid")
        payload = _dpapi(payload[len(_MAGIC):], decrypt=True)
        saved = json.loads(payload)
        if not isinstance(saved, list):
            raise ValueError("Saved session cookies are invalid")
        return saved
    saved = json.loads(legacy.read_text(encoding="utf-8"))
    if not isinstance(saved, list):
        raise ValueError("Saved session cookies are invalid")
    if os.name == "nt":
        save_session_cookies(profile, saved)
    return saved
