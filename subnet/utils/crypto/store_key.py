import os
import secrets
import time

from Crypto.PublicKey import RSA
from fastecdsa.encoding.pem import PEMEncoder
from libp2p.crypto.ecc import (
    ECCPrivateKey,
    create_new_key_pair as create_new_ecc_key_pair,
    infer_local_type,
)
from libp2p.crypto.ed25519 import (
    Ed25519PrivateKey,
    create_new_key_pair as create_new_ed25519_key_pair,
)
from libp2p.crypto.keys import KeyPair
from libp2p.crypto.rsa import (
    RSAPrivateKey,
    create_new_key_pair as create_new_rsa_key_pair,
)
from libp2p.crypto.secp256k1 import (
    Secp256k1PrivateKey,
    create_new_key_pair as create_new_secp256k1_key_pair,
)
from libp2p.peer.id import ID as PeerID
from libp2p.peer.pb import crypto_pb2

SUPPORTED_KEY_TYPES = ("ecc", "ed25519", "rsa", "secp256k", "secp256k1")
PRIVATE_KEY_FILE_MODE = 0o600

_KEY_TYPE_ALIASES = {
    "ecc": "ecc",
    "ecdsa": "ecc",
    "p256": "ecc",
    "eccp256": "ecc",
    "ed25519": "ed25519",
    "rsa": "rsa",
    "secp256k": "secp256k1",
    "secp256k1": "secp256k1",
}

_PROTOBUF_KEY_TYPES = {
    "ecc": crypto_pb2.KeyType.ECDSA,
    "ed25519": crypto_pb2.KeyType.Ed25519,
    "rsa": crypto_pb2.KeyType.RSA,
    "secp256k1": crypto_pb2.KeyType.Secp256k1,
}


def _private_key_file_exists_error(path: str) -> FileExistsError:
    return FileExistsError(f"Private key file already exists: {path}. Pass overwrite=True to replace it.")


def _secure_create_flags() -> int:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    return flags


def _write_private_key_fd(fd: int, data: bytes) -> None:
    try:
        os.fchmod(fd, PRIVATE_KEY_FILE_MODE)
        with os.fdopen(fd, "wb") as f:
            fd = -1
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
    finally:
        if fd >= 0:
            os.close(fd)


def _fsync_parent_directory(path: str) -> None:
    directory = os.path.dirname(os.path.abspath(path)) or "."
    if not hasattr(os, "O_DIRECTORY"):
        return

    try:
        dir_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    except OSError:
        return

    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def _create_private_key_file(path: str, data: bytes) -> None:
    try:
        fd = os.open(path, _secure_create_flags(), PRIVATE_KEY_FILE_MODE)
    except FileExistsError as exc:
        raise _private_key_file_exists_error(path) from exc

    _write_private_key_fd(fd, data)
    _fsync_parent_directory(path)


def _replace_private_key_file(path: str, data: bytes) -> None:
    directory = os.path.dirname(os.path.abspath(path)) or "."
    filename = os.path.basename(path)
    if not filename:
        raise ValueError("Private key path must include a filename")

    temp_path = ""
    fd = -1
    flags = _secure_create_flags()
    for _ in range(100):
        candidate = os.path.join(directory, f".{filename}.{secrets.token_hex(16)}.tmp")
        try:
            fd = os.open(candidate, flags, PRIVATE_KEY_FILE_MODE)
            temp_path = candidate
            break
        except FileExistsError:
            continue
    else:
        raise FileExistsError(f"Could not create a unique temporary file in {directory}")

    try:
        write_fd = fd
        fd = -1
        _write_private_key_fd(write_fd, data)
        os.replace(temp_path, path)
        temp_path = ""
        _fsync_parent_directory(path)
    finally:
        if fd >= 0:
            os.close(fd)
        if temp_path:
            try:
                os.unlink(temp_path)
            except FileNotFoundError:
                pass


def _write_private_key_file(path: str, data: bytes, *, overwrite: bool) -> None:
    if overwrite:
        _replace_private_key_file(path, data)
    else:
        _create_private_key_file(path, data)


def _normalize_key_type(key_type: str) -> str:
    normalized = key_type.lower().replace("-", "").replace("_", "")
    try:
        return _KEY_TYPE_ALIASES[normalized]
    except KeyError as e:
        supported_key_types = ", ".join(SUPPORTED_KEY_TYPES)
        raise ValueError(f"Unsupported key type '{key_type}'. Supported key types: {supported_key_types}") from e


def _create_key_pair(key_type: str) -> KeyPair:
    key_type = _normalize_key_type(key_type)
    if key_type == "ecc":
        return create_new_ecc_key_pair("P-256")
    if key_type == "ed25519":
        return create_new_ed25519_key_pair(secrets.token_bytes(32))
    if key_type == "rsa":
        return create_new_rsa_key_pair()
    if key_type == "secp256k1":
        return create_new_secp256k1_key_pair()

    raise ValueError(f"Unsupported key type '{key_type}'. Supported key types: {', '.join(SUPPORTED_KEY_TYPES)}")


def _rsa_private_key_from_bytes(data: bytes) -> RSAPrivateKey:
    return RSAPrivateKey(RSA.import_key(data))


def _ecc_private_key_from_bytes(data: bytes) -> ECCPrivateKey:
    private_key_impl, public_key_impl = PEMEncoder.decode_private_key(data.decode())
    curve = public_key_impl.curve if public_key_impl is not None else infer_local_type("P-256")
    return ECCPrivateKey(private_key_impl, curve)


_PRIVATE_KEY_DESERIALIZERS = {
    crypto_pb2.KeyType.ECDSA: _ecc_private_key_from_bytes,
    crypto_pb2.KeyType.Ed25519: Ed25519PrivateKey.from_bytes,
    crypto_pb2.KeyType.RSA: _rsa_private_key_from_bytes,
    crypto_pb2.KeyType.Secp256k1: Secp256k1PrivateKey.from_bytes,
}


def _deserialize_private_key(protobuf: crypto_pb2.PrivateKey):
    try:
        deserializer = _PRIVATE_KEY_DESERIALIZERS[protobuf.Type]
    except KeyError as e:
        if protobuf.Type in crypto_pb2.KeyType.values():
            key_type = crypto_pb2.KeyType.Name(protobuf.Type)
        else:
            key_type = protobuf.Type
        raise ValueError(f"Unsupported key type: {key_type}") from e

    return deserializer(protobuf.Data)


def _load_private_key(path: str):
    try:
        with open(path, "rb") as f:
            data = f.read()
    except FileNotFoundError:
        raise ValueError("Private key not found")

    protobuf = crypto_pb2.PrivateKey.FromString(data)
    return _deserialize_private_key(protobuf)


def store_private_key(path: str, key_type: str = "ed25519", overwrite: bool = False):
    normalized_key_type = _normalize_key_type(key_type)
    path = os.fspath(path)
    if not overwrite and os.path.lexists(path):
        raise _private_key_file_exists_error(path)

    key_pair = _create_key_pair(normalized_key_type)

    peer_id = PeerID.from_pubkey(key_pair.public_key)
    print(f"Peer ID: {peer_id}")

    protobuf = crypto_pb2.PrivateKey(
        Type=_PROTOBUF_KEY_TYPES[normalized_key_type],
        Data=key_pair.private_key.to_bytes(),
    )

    _write_private_key_file(path, protobuf.SerializeToString(), overwrite=overwrite)

    time.sleep(0.5)

    try:
        key_pair = get_key_pair(path)
        print("✅ Success")
    except Exception as e:
        print(f"❌ Error getting key pair: {e}")


def get_key_pair(
    path: str,
) -> KeyPair:
    """
    Get a keypair if it exists in path.
    """
    private_key = _load_private_key(path)
    return KeyPair(private_key, private_key.get_public_key())


def get_peer_id(
    path: str,
) -> PeerID:
    """
    Get a peer ID if it exists in path.
    """
    private_key = _load_private_key(path)
    return PeerID.from_pubkey(private_key.get_public_key())
