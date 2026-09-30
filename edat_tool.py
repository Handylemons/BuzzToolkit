"""EDAT (NPDRM data) encryption/decryption for PS3 files - a Python port of Hykem's
make_npdata (data_makenp-master) pack/extract paths, restricted to what Buzz DLC needs:
version 3, FREE licence (3), flags 0x3C (per-block SHA1-HMAC, encrypted-key mode,
metadata before each block). Free-licence EDATs are unlocked by the title's klicensee
alone - no .rap/.rif needed.

    python edat_tool.py encrypt <in.DAT> <out.EDAT> <klic_hex> <content_id>
    python edat_tool.py decrypt <in.EDAT> <out.DAT> <klic_hex>

The output file NAME matters: the NPD title hash covers content_id + file name, so encrypt
straight to the final name (e.g. GBRPACK0500.EDAT).
"""
import hmac
import hashlib
import os
import struct
import sys

from Crypto.Cipher import AES
from Crypto.Hash import CMAC

EDAT_KEY_0 = bytes.fromhex("BE959CA8308DEFA2E5E180C63712A9AE")
EDAT_KEY_1 = bytes.fromhex("4CA9C14B01C95309969BEC68AA0BC081")
NPDRM_OMAC_KEY_2 = bytes.fromhex("6BA52976EFDA16EF3C339FB2971E256B")
NPDRM_OMAC_KEY_3 = bytes.fromhex("9B515FEACF75064981AA604D91A54E97")
ZERO16 = bytes(16)

F_COMPRESSED, F_02, F_ENC_KEY, F_10, F_20 = 0x1, 0x2, 0x8, 0x10, 0x20
F_SDAT, F_DEBUG = 0x01000000, 0x80000000
FOOTER_V3 = b"EDATA 3.3.0.W\x00\x00\x00"


def cmac(key, data):
    return CMAC.new(key, msg=data, ciphermod=AES).digest()


def ecb_enc(key, block):
    return AES.new(key, AES.MODE_ECB).encrypt(block)


def ecb_dec(key, block):
    return AES.new(key, AES.MODE_ECB).decrypt(block)


def _edat_key(version):
    return EDAT_KEY_1 if version == 4 else EDAT_KEY_0


def _block_keys(i, dev_hash, crypt_key, flags):
    """Per-block key and hash seed (make_npdata get_block_key + encrypt_data)."""
    b_key = dev_hash[:12] + struct.pack(">I", i)
    key_result = ecb_enc(crypt_key, b_key)
    hash_seed = ecb_enc(crypt_key, key_result) if flags & F_10 else key_result
    return key_result, hash_seed


def _modes(flags):
    crypto_mode = 0x2 if not flags & F_02 else 0x1
    if not flags & F_10:
        hash_mode = 0x02
    elif not flags & F_20:
        hash_mode = 0x04
    else:
        hash_mode = 0x01
    if flags & F_ENC_KEY:
        crypto_mode |= 0x10000000
        hash_mode |= 0x10000000
    return crypto_mode, hash_mode


def _final_key_hash(crypto_mode, hash_mode, version, key, iv, hsh):
    ek = _edat_key(version)
    if crypto_mode & 0xF0000000 == 0x10000000:
        key_final, iv_final = ecb_dec(ek, key), iv
    else:
        key_final, iv_final = key, iv
    if hash_mode & 0xF0000000 == 0x10000000:
        hash_final = ecb_dec(ek, hsh)
    else:
        hash_final = hsh
    if hash_mode & 0xFF == 0x01:          # 0x14-byte HMAC key: 16 bytes + 4 zeros
        hash_final = hash_final + bytes(4)
    return key_final, iv_final, hash_final


def _hash(hash_mode, key, data):
    m = hash_mode & 0xFF
    if m == 0x01:
        return hmac.new(key, data, hashlib.sha1).digest()             # 0x14
    if m == 0x02:
        return cmac(key, data)                                        # 0x10
    if m == 0x04:
        return hmac.new(key, data, hashlib.sha1).digest()[:0x10]
    raise ValueError("unknown hash mode %x" % hash_mode)


def encrypt(plain, out_name, klic, content_id, version=3, block_size=0x4000):
    klic = bytes.fromhex(klic) if isinstance(klic, str) else klic
    cid = content_id.encode("ascii").ljust(0x30, b"\x00")[:0x30]
    fname = os.path.basename(out_name).encode("ascii")
    flags = 0x3C
    digest = os.urandom(16)                      # used as the data IV for version >= 2

    npd = bytearray(b"NPD\x00" + struct.pack(">III", version, 3, 0) + cid + digest)
    title_hash = cmac(NPDRM_OMAC_KEY_3, cid + fname)
    npd += title_hash
    dev_key = bytes(a ^ b for a, b in zip(klic, NPDRM_OMAC_KEY_2))
    dev_hash = cmac(dev_key, bytes(npd[:0x60]))
    npd += dev_hash + bytes(16)                  # unk1, unk2
    assert len(npd) == 0x80

    size = len(plain)
    header = bytearray(npd + struct.pack(">IIQ", flags, block_size, size))
    header += bytes(0x100 - len(header))
    crypto_mode, hash_mode = _modes(flags)
    nblocks = (size + block_size - 1) // block_size

    body = bytearray()
    metadata_all = bytearray()
    for i in range(nblocks):
        chunk = plain[i * block_size:(i + 1) * block_size]
        padded = chunk + bytes((-len(chunk)) % 16)
        key_result, hash_seed = _block_keys(i, dev_hash, klic, flags)
        kf, ivf, hf = _final_key_hash(crypto_mode, hash_mode, version, key_result, digest, hash_seed)
        enc = AES.new(kf, AES.MODE_CBC, ivf).encrypt(padded)
        hres = _hash(hash_mode, hf, enc)                           # 0x14 bytes
        # flag 0x20: metadata = (hash[0:16] ^ r, r) with r[0:4] = hash[16:20]
        r = hres[16:20] + os.urandom(12)
        meta = bytes(a ^ b for a, b in zip(hres[:16], r)) + r
        metadata_all += meta
        body += meta + enc
    body += FOOTER_V3

    # metadata-section hash (0x90) and header hash (0xA0): CMAC with the encrypted-hash key
    fhash_mode = 0x10000002 if flags & F_ENC_KEY else 0x00000002
    _, _, hkey = _final_key_hash(0x1, fhash_mode, version, ZERO16, ZERO16, klic)
    header[0x90:0xA0] = cmac(hkey, bytes(metadata_all))
    header[0xA0:0xB0] = cmac(hkey, bytes(header[:0xA0]))
    header[0xB0:0x100] = os.urandom(0x50)       # ECDSA signatures: unchecked, random like make_npdata
    return bytes(header) + bytes(body)


def decrypt(data, klic):
    """Decrypt + verify a version 2-4 EDAT with flags 0x3C (free licence)."""
    klic = bytes.fromhex(klic) if isinstance(klic, str) else klic
    version, lic, typ = struct.unpack(">III", data[4:16])
    digest, dev_hash = data[0x40:0x50], data[0x60:0x70]
    flags, block_size, size = struct.unpack(">IIQ", data[0x80:0x90])
    if flags != 0x3C:
        raise ValueError("only flags 0x3C supported here, got 0x%x" % flags)
    crypto_mode, hash_mode = _modes(flags)
    nblocks = (size + block_size - 1) // block_size
    out = bytearray()
    pos = 0x100
    for i in range(nblocks):
        length = block_size if i < nblocks - 1 or size % block_size == 0 else size % block_size
        plen = (length + 15) & ~15
        meta, enc = data[pos:pos + 0x20], data[pos + 0x20:pos + 0x20 + plen]
        pos += 0x20 + plen
        want = bytes(a ^ b for a, b in zip(meta[:16], meta[16:])) + meta[16:20]
        key_result, hash_seed = _block_keys(i, dev_hash, klic, flags)
        kf, ivf, hf = _final_key_hash(crypto_mode, hash_mode, version, key_result, digest, hash_seed)
        if _hash(hash_mode, hf, enc) != want:
            raise ValueError("block %d hash mismatch" % i)
        out += AES.new(kf, AES.MODE_CBC, ivf).decrypt(enc)[:length]
    return bytes(out)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "encrypt" and len(sys.argv) == 6:
        _, _, src, dst, k, cid = sys.argv
        open(dst, "wb").write(encrypt(open(src, "rb").read(), dst, k, cid))
        print("wrote", dst)
    elif cmd == "decrypt" and len(sys.argv) == 5:
        _, _, src, dst, k = sys.argv
        open(dst, "wb").write(decrypt(open(src, "rb").read(), k))
        print("wrote", dst)
    else:
        print(__doc__)
        sys.exit(1)
