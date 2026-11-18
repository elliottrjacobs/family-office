"""macOS login-keychain storage for credential blobs, through Security.framework.

One generic-password item holds one credential file's bytes. Items are added without the
synchronizable attribute, so they stay on this Mac and never enter iCloud Keychain. macOS
trusts the program that added an item; when another program asks for its data, macOS asks
the user first. Only `read` returns an item's data, and nothing here logs it.

ctypes keeps this dependency-free. Every Core Foundation object created here is released
before the call returns.
"""

import ctypes
import sys

NOT_FOUND = -25300
UTF8 = 0x08000100
CONSTANTS = (
    "kSecClass",
    "kSecClassGenericPassword",
    "kSecAttrService",
    "kSecAttrAccount",
    "kSecAttrLabel",
    "kSecValueData",
    "kSecReturnData",
    "kSecMatchLimit",
    "kSecMatchLimitOne",
)


class KeychainError(Exception):
    """A Keychain call failed. Carries the OSStatus, never an item's data."""

    def __init__(self, status):
        super().__init__(f"Keychain status {status}")
        self.status = status


_state = None


def _load():
    global _state
    if _state is not None:
        return _state
    if sys.platform != "darwin":
        raise KeychainError("unsupported")
    void, pointer = ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)
    try:
        cf = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
        sec = ctypes.CDLL("/System/Library/Frameworks/Security.framework/Security")
        signatures = [
            (cf.CFStringCreateWithCString, void, [void, ctypes.c_char_p, ctypes.c_uint32]),
            (cf.CFDataCreate, void, [void, ctypes.c_char_p, ctypes.c_long]),
            (cf.CFDataGetLength, ctypes.c_long, [void]),
            (cf.CFDataGetBytePtr, void, [void]),
            (cf.CFDictionaryCreate, void, [void, pointer, pointer, ctypes.c_long, void, void]),
            (cf.CFRelease, None, [void]),
            (sec.SecItemCopyMatching, ctypes.c_int32, [void, pointer]),
            (sec.SecItemAdd, ctypes.c_int32, [void, pointer]),
            (sec.SecItemUpdate, ctypes.c_int32, [void, void]),
            (sec.SecItemDelete, ctypes.c_int32, [void]),
        ]
        for function, restype, argtypes in signatures:
            function.restype, function.argtypes = restype, argtypes
        names = {name: void.in_dll(sec, name) for name in CONSTANTS}
        names["true"] = void.in_dll(cf, "kCFBooleanTrue")
        callbacks = tuple(
            ctypes.addressof(ctypes.c_char.in_dll(cf, name))
            for name in ("kCFTypeDictionaryKeyCallBacks", "kCFTypeDictionaryValueCallBacks")
        )
    except (OSError, ValueError, AttributeError) as exc:
        raise KeychainError("unavailable") from exc
    _state = cf, sec, names, callbacks
    return _state


class _Objects:
    """Core Foundation objects for one call, released together on exit."""

    def __init__(self):
        self.cf, self.sec, self.names, self.callbacks = _load()
        self.owned = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        for item in reversed(self.owned):
            self.cf.CFRelease(item)

    def keep(self, item):
        if not item:
            raise KeychainError("allocation")
        self.owned.append(item)
        return item

    def string(self, text):
        return self.keep(self.cf.CFStringCreateWithCString(None, text.encode(), UTF8))

    def data(self, value):
        return self.keep(self.cf.CFDataCreate(None, value, len(value)))

    def dictionary(self, pairs):
        count = len(pairs)
        keys = (ctypes.c_void_p * count)(*[self.names[key] for key, _ in pairs])
        values = (ctypes.c_void_p * count)(
            *[
                self.names.get(value, value) if isinstance(value, str) else value
                for _, value in pairs
            ]
        )
        return self.keep(self.cf.CFDictionaryCreate(None, keys, values, count, *self.callbacks))

    def item(self, service, account):
        return [
            ("kSecClass", "kSecClassGenericPassword"),
            ("kSecAttrService", self.string(service)),
            ("kSecAttrAccount", self.string(account)),
        ]


def read(service: str, account: str) -> bytes | None:
    """The item's data, or None when no such item exists."""
    with _Objects() as objects:
        query = objects.dictionary(
            objects.item(service, account)
            + [("kSecReturnData", "true"), ("kSecMatchLimit", "kSecMatchLimitOne")]
        )
        result = ctypes.c_void_p()
        status = objects.sec.SecItemCopyMatching(query, ctypes.byref(result))
        if status == NOT_FOUND:
            return None
        if status or not result.value:
            raise KeychainError(status)
        objects.keep(result.value)
        length = objects.cf.CFDataGetLength(result)
        return ctypes.string_at(objects.cf.CFDataGetBytePtr(result), length)


def exists(service: str, account: str) -> bool:
    """Whether the item exists. Asks for no data, so macOS never prompts."""
    with _Objects() as objects:
        query = objects.dictionary(
            objects.item(service, account) + [("kSecMatchLimit", "kSecMatchLimitOne")]
        )
        status = objects.sec.SecItemCopyMatching(query, None)
        if status not in (0, NOT_FOUND):
            raise KeychainError(status)
        return status == 0


def write(service: str, account: str, data: bytes, label: str) -> None:
    """Replace the item's data, adding the item when it does not exist yet.

    Empty data is refused: the Keychain reports success for an empty update and keeps the
    old value.
    """
    if not data:
        raise KeychainError("empty")
    with _Objects() as objects:
        item = objects.item(service, account)
        value = objects.data(data)
        status = objects.sec.SecItemUpdate(
            objects.dictionary(item), objects.dictionary([("kSecValueData", value)])
        )
        if status == NOT_FOUND:
            status = objects.sec.SecItemAdd(
                objects.dictionary(
                    item + [("kSecValueData", value), ("kSecAttrLabel", objects.string(label))]
                ),
                None,
            )
        if status:
            raise KeychainError(status)


def delete(service: str, account: str) -> None:
    """Remove the item; a missing item is not an error."""
    with _Objects() as objects:
        status = objects.sec.SecItemDelete(objects.dictionary(objects.item(service, account)))
        if status not in (0, NOT_FOUND):
            raise KeychainError(status)
