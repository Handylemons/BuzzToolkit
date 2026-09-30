#!/usr/bin/env python3
"""
fake_buzz_server.py -- reconstructed Medius/RT_MSG + SVO/SVML fake server for
Buzz! Quiz World (BCES00645), running under RPCS3 with the IP-swap list
pointing buzzps3.online.scee.com -> 127.0.0.1.

This is a from-scratch RECONSTRUCTION. The original file (developed across many
prior sessions) no longer exists on disk -- it lived in a session scratchpad
that gets cleared between sessions. Every behavior below is either:
  (a) ported byte-exact from PSRewired/Memdusa's real, public C# Medius
      implementation (Memdusa.Medius/Crypto/Rc/Ps3RcCipher.cs and
      Crypto/Rsa/{RsaCipher,Ps3RsaCipher}.cs, Services/MediusPacketHandler.cs,
      Objects/MediusRequestObject.cs -- fetched and ported directly, not
      guessed), which is the same family of reference this project's crypto
      work was originally verified against, or
  (b) taken from this project's own memory, where it was independently
      confirmed correct via live capture against a real Buzz client
      (message opcodes, field offsets, the two real structural bugs already
      found and fixed: SvoURL as a separate 0x1E message, StatusCode=1 not 0).

Known-still-guessed values (flagged inline) are the universe name/description/
status/user-count fields in UniverseVariableInformationResponse -- these were
never confirmed correct; the client's disconnect (reason=1, NORMAL) persisted
through every fix applied so far, and the true remaining cause is either one
of these guesses or a native client-side validation step that resisted every
static-analysis technique tried (see project memory / the "Connection
Protocol Map" artifact for the full writeup).

Ports (confirmed from real captures across many sessions):
    10071 -- Medius login/auth (main handshake, GetUniverseInformation)
    10075 -- Medius DME/lobby (second-stage connect; same handshake protocol)
    10060 -- SVO HTTP content layer (SVML/XML)
"""
import http.server
import logging
import random
import socket
import struct
import threading
import hashlib
import os
import re
import time

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(threadName)s] %(message)s")
log = logging.getLogger("buzz")

HOST = "0.0.0.0"
MEDIUS_LOGIN_PORT = 10071
MEDIUS_DME_PORT = 10075
SVO_HTTP_PORT = 10060

SVO_HOSTNAME = os.environ.get("SVO_HOSTNAME", "buzzps3.online.scee.com")  # Buzz default; set sing3.online.scee.com for SingStar
def _load_svomac_salt():
    """The game's SVO request-signing salt (a 32-character string in Buzz's EBOOT). Not shipped
    with the toolkit: `python -m buzz_engine setup --eboot <decrypted EBOOT.elf>` finds it in the
    user's own game and stores it in buzz_engine/game_keys.json (or set BUZZ_SVOMAC_SALT)."""
    if os.environ.get("BUZZ_SVOMAC_SALT"):
        return os.environ["BUZZ_SVOMAC_SALT"]
    import json
    for name in ("game_keys.json", "server_config.json"):
        cfg = os.path.join(os.path.dirname(os.path.abspath(__file__)), "buzz_engine", name)
        if os.path.exists(cfg):
            salt = json.load(open(cfg)).get("svomac_salt")
            if salt:
                return salt
    raise SystemExit("Buzz server is not set up: run the server setup in Buzz Pack Studio (or "
                     "buzz_engine.online.setup_server) with your decrypted EBOOT.elf first.")


SVOMAC_SALT = _load_svomac_salt()

# Real, genuine captured Sony Medius certificate (not a placeholder) -- from
# PSRewired/Memdusa's HelloRequest.cs, which embeds it verbatim with the
# comment "Extracted from a hello request in a PS3 packet dump". Issuer:
# SCERT Root Authority / SONY Computer Entertainment America Inc. Subject CN:
# "MAS 1" (Medius Authentication Server). Valid 2005-04-26 to 2035-04-25.
# If the PS3's firmware trust store has the matching SCERT root CA (plausible
# for first-party Sony online infrastructure of this era), replying with this
# exact certificate has a real chance of passing genuine chain validation,
# not just looking structurally plausible.
_MAS_CERT_HEX = (
    "308202e3308201cba00302010202140100000000000000000000001100000000000001"
    "300d06092a864886f70d0101050500308196310b3009060355040613025553310b3009"
    "060355040813024341311230100603550407130953616e20446965676f3131302f0603"
    "55040a1328534f4e5920436f6d707574657220456e7465727461696e6d656e7420416d"
    "657269636120496e632e31143012060355040b130b53434552542047726f7570311d30"
    "1b06035504031314534345525420526f6f7420417574686f72697479301e170d303530"
    "3432363231303133385a170d3335303432353233353935395a308187310b3009060355"
    "040613025553310b3009060355040813024341311230100603550407130953616e2044"
    "6965676f3131302f060355040a1328534f4e5920436f6d707574657220456e74657274"
    "61696e6d656e7420416d657269636120496e632e31143012060355040b130b53434552"
    "542047726f7570310e300c060355040313054d41532031305c300d06092a864886f70d"
    "0101010500034b003048024100c4f75716ec835d2325689f91ff85ed9bfc3211db9c16"
    "4f41852e264e569d2802008054a0ef459e7e3eabb87fae576e735434d1d124b30b11bd"
    "6de0981486015502030000113 00d06092a864886f70d010105050003820101006c91"
    "abeeb59ac01dfbb080646e4df616f833c36a5a448773f7c1acb8ec162ff811ab11f805"
    "1294e20754361827b259a534b010dfbb42e56b571ae453779682ca8650ac5dd0b3888c"
    "fb16fb858e5c39dff094380bc4f6f0268ade80c22878afc4c16099c64d435a9ab67101"
    "e63b0f5336febb1f71683ba0b0ac7eab2ef0d10d9324b6ce5683d1ab359deda17c47f2"
    "a253162674be37c2ce185d90c76b7fd7d9983c289747ad10828b385b82d7eb18f52f2e"
    "ced4c3a65b0dd63dd8c83c5f92203829fdbf1a85c78b869283b0b1d5fe1bb5e85749ab"
    "f50e46d9decca190c2d954b6e442e58fbde9958af397e9af575e1f76d63f35ee598740"
    "6c109db7da50557e86"
).replace(" ", "")
MAS_CERTIFICATE = bytes.fromhex(_MAS_CERT_HEX)

_CERT_MODULUS_OFFSET = MAS_CERTIFICATE.find(bytes([0x02, 0x41, 0x00])) + 3


def build_session_certificate(rsa: "RsaCipher") -> bytes:
    """Real captured cert structure kept byte-identical (the client already
    tolerates it being unsigned/re-keyed -- it accepted the stock version far
    enough to proceed to CLIENT_CRYPTKEY_PUBLIC), but with the embedded
    RSAPublicKey modulus replaced by OUR generated keypair's modulus, so we
    actually hold the matching private key needed to decrypt what the client
    encrypts back to us. Requires rsa.n to be exactly 64 bytes (guaranteed by
    a genuine 512-bit modulus with the top bit set)."""
    modulus = rsa.n.to_bytes(64, "big")
    cert = bytearray(MAS_CERTIFICATE)
    cert[_CERT_MODULUS_OFFSET:_CERT_MODULUS_OFFSET + 64] = modulus
    return bytes(cert)

# =============================================================================
# Crypto: Ps3RcCipher -- ported byte-exact from PSRewired/Memdusa
# (Memdusa.Medius/Crypto/Rc/Ps3RcCipher.cs)
# =============================================================================

_MASK32 = 0xFFFFFFFF


def _rotl32(v, n):
    v &= _MASK32
    return ((v << n) | (v >> (32 - n))) & _MASK32


def _rotr32(v, n):
    v &= _MASK32
    return ((v >> n) | (v << (32 - n))) & _MASK32


def _flip_words(buf: bytearray):
    """Reverse byte order within each 4-byte word (endianness swap)."""
    for i in range(0, len(buf) - (len(buf) % 4), 4):
        buf[i], buf[i + 3] = buf[i + 3], buf[i]
        buf[i + 1], buf[i + 2] = buf[i + 2], buf[i + 1]


def _pad4(data: bytes) -> bytearray:
    pad = (-len(data)) % 4
    return bytearray(data + b"\x00" * pad)


def _rc_pass(data: bytes, iv, sign=False, decrypt=False):
    """
    Core Medius RC keystream pass. `iv` is a list of 4 uint32 (mutated in place
    conceptually -- returned as a new list here). Returns (new_iv, output_bytes)
    where output_bytes is only meaningful if sign=True (ciphertext/plaintext).
    """
    r3 = 0x5B3AA654
    r5 = 0x75970A4D

    buf = _pad4(data)
    _flip_words(buf)

    r16, r17, r18, r19 = iv[0], iv[1], iv[2], iv[3]
    out = bytearray(buf)

    for i in range(0, len(data), 4):
        r19 ^= r3
        r18 = (r18 + r16) & _MASK32
        r18 = (r18 + r19) & _MASK32
        r18 = _rotl32(r18, 7)
        r17 = (r17 + r19) & _MASK32
        r17 = (r17 + r18) & _MASK32
        r18 ^= r5
        r17 = _rotl32(r17, 11)
        r16 = (r16 + r18) & _MASK32
        r16 = (r16 + r17) & _MASK32
        r16 = _rotr32(r16, 15)
        r0 = r16 & r17
        r17 = (~r17) & _MASK32
        r6 = r18 & r17
        r0 |= r6
        r19 = (r19 + r0) & _MASK32
        r16 = (~r16) & _MASK32

        r0 = (buf[i] << 24) | (buf[i + 1] << 16) | (buf[i + 2] << 8) | buf[i + 3]
        if decrypt:
            r0 ^= r19
        r19 ^= r0

        if sign:
            val = r0 if decrypt else r19
            out[i:i + 4] = struct.pack("<I", val)  # BitConverter.GetBytes is little-endian

    new_iv = [r16, r17, r18, r19]
    if sign:
        return new_iv, bytes(out[:len(data)])
    return new_iv, None


def ps3_hash(data: bytes, context: int) -> bytes:
    """Compute the 4-byte Medius integrity hash for `data`, tagged with a
    3-bit `context`/cipher-type value in the top bits (context << 29)."""
    r3 = 0x5B3AA654
    r5 = 0x75970A4D

    buf = _pad4(data)
    _flip_words(buf)

    iv, _ = _rc_pass(b"\x00" * 16, [0, 0, 0, 0])
    r16, r17, r18, r19 = iv

    for i in range(0, len(data), 4):
        r19 ^= r3
        r18 = (r18 + r16) & _MASK32
        r18 = (r18 + r19) & _MASK32
        r18 = _rotl32(r18, 7)
        r17 = (r17 + r19) & _MASK32
        r17 = (r17 + r18) & _MASK32
        r18 ^= r5
        r17 = _rotl32(r17, 11)
        r16 = (r16 + r18) & _MASK32
        r16 = (r16 + r17) & _MASK32
        r16 = _rotr32(r16, 15)
        r0 = r16 & r17
        r17n = (~r17) & _MASK32
        r6 = r18 & r17n
        r0 |= r6
        r19 = (r19 + r0) & _MASK32
        r16 = (~r16) & _MASK32
        r17 = r17n

        r0 = (buf[i] << 24) | (buf[i + 1] << 16) | (buf[i + 2] << 8) | buf[i + 3]
        r19 ^= r0

    total = (r16 + r17 + r18 + r19) & _MASK32
    h = (total & 0x1FFFFFFF) | ((context & 0x7) << 29)
    return struct.pack("<I", h & _MASK32)  # BitConverter.GetBytes is little-endian


class Ps3RcCipher:
    """Session cipher. `key` is 64 bytes (only the first 16 are used as IV seed,
    matching the reference implementation)."""

    def __init__(self, key: bytes):
        assert len(key) >= 16, "RC cipher key must be >= 16 bytes"
        self.key = key

    def _initial_iv(self, cipher_hash: bytes):
        """Port of the real binary's per-message state setup, FUN_004f8004
        (verified against EBOOT_patched.elf):

            memcpy(state, key, 16);
            flip_words(state, 16);          // reverses each 4-byte group
            RC_advance(state, hash32, 4);   // FUN_004f84d8, no output written
            copy = state; flip_words(copy, 16);
            RC_encrypt(state, copy, 16);    // FUN_004f8200

        The state is rebuilt from the key on EVERY message -- it is not chained
        across messages.

        The memcpy+flip_words pair means each state word is the LITTLE-endian
        reading of the key bytes, and the same holds when the state is re-packed
        for the second pass. Using big-endian here was the bug that made every
        candidate session key fail regardless of its value.
        """
        iv = [struct.unpack("<I", self.key[i:i + 4])[0] for i in range(0, 16, 4)]
        iv, _ = _rc_pass(cipher_hash, iv)
        iv_bytes = b"".join(struct.pack("<I", v) for v in iv)
        iv, _ = _rc_pass(iv_bytes, iv, sign=True)
        return iv

    def encrypt(self, plain: bytes, context: int):
        # NOTE: the C# reference passes `iv` by `ref` through all three
        # RC_Pass calls -- each one mutates the SAME iv state for the next,
        # it does not reset back to the key-derived iv0 in between.
        cipher_hash = ps3_hash(plain, context)
        iv = self._initial_iv(cipher_hash)
        iv, cipher = _rc_pass(plain, iv, sign=True)
        return cipher, cipher_hash

    def decrypt(self, cipher: bytes, cipher_hash: bytes):
        # An all-zero (low 29 bits + context bits masked) hash means plaintext.
        if cipher_hash[0] == 0 and cipher_hash[1] == 0 and cipher_hash[2] == 0 and (cipher_hash[3] & 0x1F) == 0:
            return True, cipher

        iv = self._initial_iv(cipher_hash)
        iv, plain = _rc_pass(cipher, iv, sign=True, decrypt=True)

        context = cipher_hash[3] >> 5
        check = ps3_hash(plain, context)
        return check == cipher_hash, plain


# =============================================================================
# Crypto: RSA-512, reversed-byte-order convention -- ported from
# PSRewired/Memdusa's RsaCipher.cs / Ps3RsaCipher.cs
# =============================================================================

def _is_probable_prime(n: int, rounds: int = 20) -> bool:
    if n < 2:
        return False
    for p in (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31):
        if n % p == 0:
            return n == p
    d = n - 1
    r = 0
    while d % 2 == 0:
        d //= 2
        r += 1
    for _ in range(rounds):
        a = random.randrange(2, n - 1)
        x = pow(a, d, n)
        if x == 1 or x == n - 1:
            continue
        for _ in range(r - 1):
            x = pow(x, 2, n)
            if x == n - 1:
                break
        else:
            return False
    return True


def _random_prime(bits: int) -> int:
    while True:
        candidate = random.getrandbits(bits) | (1 << (bits - 1)) | 1
        if _is_probable_prime(candidate):
            return candidate


class RsaCipher:
    def __init__(self, n: int, e: int, d: int):
        self.n = n
        self.e = e
        self.d = d

    @classmethod
    def generate(cls, bits=512):
        # Real Medius servers use a fixed/persistent keypair; a fresh one each
        # boot is fine for a private fake server (client only ever needs our
        # public N to encrypt its RC4 key to us). Self-contained prime
        # generation (Miller-Rabin) to avoid an external dependency.
        half = bits // 2
        e = 17
        while True:
            p = _random_prime(half)
            q = _random_prime(half)
            if q == p:
                continue
            n = p * q
            if n.bit_length() != bits:
                # Two top-bit-set half-size primes don't always multiply out
                # to the full target bit length (511 vs 512 happens often) --
                # live-observed to plausibly cause client decrypt failures
                # when the modulus isn't a full, consistent 512 bits. Retry
                # rather than accept a short modulus.
                continue
            phi = (p - 1) * (q - 1)
            if phi % e == 0:
                continue  # e not invertible mod phi for this prime pair, retry
            d = pow(e, -1, phi)
            return cls(n, e, d)

    @classmethod
    def from_client_key(cls, key_bytes: bytes):
        """Build a 'cipher' from the client's public-key bytes -- per the
        reference implementation, e=d=17 for this specific direction."""
        pub = int.from_bytes(key_bytes[::-1], "big")
        return cls(pub, 17, 17)

    def pub_key_bytes(self, min_len=0) -> bytes:
        raw = self.n.to_bytes((self.n.bit_length() + 7) // 8, "big")[::-1]
        if len(raw) < min_len:
            raw = raw + b"\x00" * (min_len - len(raw))
        return raw

    def encrypt(self, data: bytes) -> bytes:
        # Matches the reference's `ToBA(input.Length)`: output is truncated or
        # zero-padded to exactly the ORIGINAL plaintext length, not left at
        # full modulus width.
        m = int.from_bytes(data[::-1], "big")
        c = pow(m, self.e, self.n)
        out = c.to_bytes((self.n.bit_length() + 7) // 8, "big")[::-1]
        if len(out) < len(data):
            out = out + b"\x00" * (len(data) - len(out))
        return out[:len(data)]

    def decrypt(self, data: bytes, expected_hash: bytes, context: int):
        c = int.from_bytes(data[::-1], "big")
        m = pow(c, self.d, self.n)
        plain = m.to_bytes((self.n.bit_length() + 7) // 8, "big")[::-1]
        plain = plain[:len(data)]
        if ps3_hash(plain, context) == expected_hash:
            return True, plain
        # Reference falls back to (m + n) if the first hash check fails,
        # covering the case where the true plaintext was >= n.
        m2 = m + self.n
        plain2 = m2.to_bytes((self.n.bit_length() + 7) // 8, "big")[::-1][:len(data)]
        if ps3_hash(plain2, context) == expected_hash:
            return True, plain2
        return False, plain


# =============================================================================
# RT_MSG outer framing -- ported exactly from MediusPacketHandler.cs /
# MediusRequestObject.cs
# =============================================================================

RT_MSG_CLIENT_CONNECT_TCP = 0x00
RT_MSG_CLIENT_DISCONNECT = 0x01           # generic; WITH_REASON variant below
RT_MSG_CLIENT_DISCONNECT_WITH_REASON = 0x20
RT_MSG_CLIENT_CONNECT_READY_TCP = 0x21
RT_MSG_CLIENT_CONNECT_READY_REQUIRE = 0x23
RT_MSG_SERVER_CONNECT_REQUIRE = 0x22      # server->client companion, not yet independently verified
RT_MSG_SERVER_CONNECT_ACCEPT_TCP = 0x07
RT_MSG_CLIENT_APP_TOSERVER = 0x0B
# 0x0A, NOT 0x0C. Recovered from the client's own dispatch jump table (0x3d
# entries, base at TOC+0x5644, read out of EBOOT_patched.elf): type 0x0C maps to
# the reject stub at 0x3f0528, whose first instructions are
# `addi r0,r0,4 / stw r0,0x80(r31)` -- it sets Result=4, exactly the
# "Result ... TraceValue:4" the client logged at rtmsgcl_tcp.c:3378 for every
# app message we sent. The real app-data handler (0x3f021c) serves types
# 0x02/0x03/0x04/0x0A/0x32-0x36; of those, 0x03/0x33 carry 2 extra bytes (a
# sender id, see the +6 vs +4 data offset in FUN_003efbf8), so the plain
# server->client app type is 0x0A -- the mirror of CLIENT_APP_TOSERVER (0x0B).
RT_MSG_SERVER_APP = 0x0A                  # server->client application payload (fragmented)
RT_MSG_CLIENT_ECHO = 0x05                 # heartbeat; client sends it, expects it echoed back
RT_MSG_CLIENT_CRYPTKEY_PUBLIC = 0x12
RT_MSG_SERVER_CRYPTKEY_PEER = 0x13
RT_MSG_SERVER_CRYPTKEY_GAME = 0x14        # accompanies SERVER_CONNECT_ACCEPT_TCP
RT_MSG_SERVER_CONNECT_COMPLETE = 0x1A
RT_MSG_CLIENT_HELLO = 0x24
RT_MSG_SERVER_HELLO = 0x25

MEDIUS_MAX_MESSAGE_LENGTH = 0xFFFF


def parse_rt_frames(data: bytes):
    """Yields (rt_type, encrypted, cipher_hash_or_None, payload) tuples, and
    returns the number of bytes consumed."""
    messages = []
    pos = 0
    n = len(data)
    while pos + 3 <= n:
        rt_type_raw = data[pos]
        encrypted = rt_type_raw >= 0x80
        rt_type = rt_type_raw & 0x7F
        header_size = 3 + (4 if encrypted else 0)
        msg_size = struct.unpack("<H", data[pos + 1:pos + 3])[0]
        if msg_size > MEDIUS_MAX_MESSAGE_LENGTH:
            raise ValueError(f"invalid frame size {msg_size}")
        if pos + header_size + msg_size > n:
            break
        cipher_hash = None
        if encrypted:
            cipher_hash = data[pos + 3:pos + 7]
        payload = data[pos + header_size:pos + header_size + msg_size]
        messages.append((rt_type, encrypted, cipher_hash, payload))
        pos += header_size + msg_size
    return messages, pos


def build_rt_frame(rt_type: int, payload: bytes, cipher: Ps3RcCipher = None, context: int = 0) -> bytes:
    if cipher is not None:
        cipher_bytes, cipher_hash = cipher.encrypt(payload, context)
        header = bytes([rt_type | 0x80]) + struct.pack("<H", len(cipher_bytes)) + cipher_hash
        return header + cipher_bytes
    header = bytes([rt_type]) + struct.pack("<H", len(payload))
    return header + payload


# =============================================================================
# Medius application-layer message builders
# =============================================================================

MESSAGECLASS_LOBBY = 0x01
MESSAGECLASS_LOBBYEXT = 0x04

GET_UNIVERSE_INFORMATION = 0xC8
# 0xC9, not 0x11. Recovered by dumping all 323 handler registrations from the
# binary (see dump_registrations.py). Registration serves both directions, and
# the two are distinguishable: an id registered with a marshaller but a NULL
# callback is one the CLIENT SENDS (marshaller only needed to serialise it),
# while an id with a real game callback is one the client RECEIVES. Ids pair up
# as request/response -- 0xC8 (null callback; the request it sent us) pairs with
# 0xC9 (game callback 0x507df8). 0x11 has a null callback, i.e. it is a
# client->server message we should never have been replying with.
UNIVERSE_INFO_RESPONSE = 0xC9
UNIVERSESVOURLRESPONSE_TYPE = 0x1E

INFO_UNIVERSES = 1
INFO_NEWS = 2
INFO_ID = 4
INFO_NAME = 8
INFO_DNS = 16
INFO_DESCRIPTION = 32
INFO_STATUS = 64
INFO_BILLING = 128
INFO_EXTRAINFO = 256
INFO_SVO_URL = 512

MEDIUS_SUCCESS = 1   # confirmed real value from the recovered MediusCallbackStatus enum (NOT 0)
MEDIUS_FAIL = -965


def _message_id_field(s: str) -> bytes:
    b = s.encode("ascii")[:21]
    return b + b"\x00" * (21 - len(b))


def build_universe_information_response(message_id: str, name: str,
                                        value: int = 1, end_of_list: int = 1) -> bytes:
    """The real reply to GetUniverseInformation: class 0x01, id 0xC9.

    Layout read straight off the client's marshaller FUN_00516fcc:

        FUN_005a0a18(ctx, base + 0x000, 0x15)    # 21  MessageID
        func_0x005a0a38(ctx, 3)                   #  3  alignment pad
        func_0x005a0a48(ctx, base + 0x018)        #  4  u32
        FUN_005a0a18(ctx, base + 0x01c, 0x100)    # 256 string
        func_0x005a0a28(ctx, base + 0x11c)        #  1  flag
        func_0x005a0a38(ctx, 3)                   #  3  alignment pad

    Total 288 bytes, independently confirmed by its callback FUN_00507df8
    returning 0x120 (the byte count the dispatcher advances by).

    That callback forwards (u32, string) as one struct and passes the flag byte
    at 0x11c where the sibling 0x1E handler passes a hardcoded 1 -- so the flag
    reads as an end-of-list marker; send 1 for the final entry.
    """
    body = bytearray()
    body += _message_id_field(message_id)           # 21
    body += b"\x00" * 3                              # 3 pad
    body += struct.pack("<I", value)                 # 4
    nb = name.encode("ascii")[:255]
    body += nb + b"\x00" * (0x100 - len(nb))         # 256
    body += bytes([end_of_list & 0xFF])              # 1
    body += b"\x00" * 3                              # 3 pad
    assert len(body) == 0x120, len(body)
    return bytes(body)


def _pascal_str(s: str) -> bytes:
    b = s.encode("ascii")
    return struct.pack("<H", len(b)) + b


# ---------------------------------------------------------------------------
# The REAL replies to GetUniverseInformation live in class 0x04 (LOBBYEXT),
# not class 0x01 (dump_registrations.py: class 0x04 id 0x11 -> game callback
# FUN_00508024 with marshaller FUN_005170dc; class 0x04 id 0x1E -> game
# callback FUN_00507f14 which parses itself). Class 0x01 id 0x11 is a NULL-
# callback (client->server) message, which is why "0x11" looked wrong before.
# ---------------------------------------------------------------------------
UNIVERSE_VARIABLE_INFO_RESPONSE = 0x11     # class 0x04
UNIVERSE_SVO_URL_RESPONSE = 0x1E           # class 0x04


def _fixed_str(s: str, n: int) -> bytes:
    b = s.encode("ascii")[:n - 1]
    return b + b"\x00" * (n - len(b))


def build_universe_svo_url_response_ext(message_id: str, url: str) -> bytes:
    """Class 0x04, id 0x1E (MediusUniverseSvoURLResponse). FUN_00507f14 parses
    it directly: FUN_005a0a18(ctx, msgid, 0x15) then FUN_005a0b38(ctx, url):
    u16 LE length INCLUDING the NUL, then the bytes; it rejects the string if
    the last byte is not NUL. It stashes (msgid, url) in globals; the 0x11
    handler later merges the url in when its own msgid matches, so the two
    must carry the same MessageID and 0x1E must arrive FIRST."""
    ub = url.encode("ascii")[:127] + b"\x00"
    return _message_id_field(message_id) + _varlen(len(ub)) + ub


def _varlen(n: int) -> bytes:
    """Length prefix as read by FUN_003b15d8 (mode 2): a single byte when
    n < 0x80, otherwise two bytes [(n >> 8) | 0x80][n & 0xff] (max 0x7ffe).
    NOT a little-endian u16 -- sending `34 00` made the reader take 0x34 as
    the length starting at the 00 byte, fail the trailing-NUL check and
    return -1, which the dispatcher reports as error 1001."""
    if n < 0x80:
        return bytes([n])
    return bytes([(n >> 8) | 0x80, n & 0xFF])


def build_universe_variable_information_response(message_id: str, info_filter: int,
                                                 universe_id: int = 1,
                                                 name: str = "Buzz Universe",
                                                 dns: str = "127.0.0.1",
                                                 port: int = MEDIUS_DME_PORT,
                                                 description: str = "Buzz Quiz World",
                                                 status: int = 1, user_count: int = 0,
                                                 max_users: int = 256,
                                                 billing: str = "", billing_name: str = "",
                                                 extended_info: str = "",
                                                 status_code: int = 0,
                                                 end_of_list: int = 1) -> bytes:
    """Class 0x04, id 0x11 (MediusUniverseVariableInformationResponse), laid
    out exactly as the client's marshaller FUN_005170dc consumes it. The
    stream readers (FUN_005a0a48 etc.) do NOT align, so this is byte-packed:

        msgid[21]  status_code u32  info_filter u32
        & 0x004: universe_id u32
        & 0x008: name[128]
        & 0x010: dns[128] port u32
        & 0x020: description[256]
        & 0x040: status u32, user_count u32, max_users u32
        & 0x080: billing[8] billing_name[128]
        & 0x100: extended_info[256]
        end_of_list u8

    The marshaller parses by THIS message's info_filter, so any subset of the
    request's bits is accepted. Bit 0x200 (SVO URL) makes FUN_00508024 merge
    the stashed 0x1E url and, if the msgid does not match, force status
    -966. With the client's 0x27c all bits present this is 562 bytes."""
    body = bytearray()
    body += _message_id_field(message_id)
    body += struct.pack("<i", status_code)
    body += struct.pack("<I", info_filter)
    if info_filter & INFO_ID:
        body += struct.pack("<I", universe_id)
    if info_filter & INFO_NAME:
        body += _fixed_str(name, 128)
    if info_filter & INFO_DNS:
        body += _fixed_str(dns, 128) + struct.pack("<I", port)
    if info_filter & INFO_DESCRIPTION:
        body += _fixed_str(description, 256)
    if info_filter & INFO_STATUS:
        body += struct.pack("<III", status, user_count, max_users)
    if info_filter & INFO_BILLING:
        body += _fixed_str(billing, 8) + _fixed_str(billing_name, 128)
    if info_filter & INFO_EXTRAINFO:
        body += _fixed_str(extended_info, 256)
    body += bytes([end_of_list & 0xFF])
    return bytes(body)


def build_universe_svo_url_response(message_id: str, a: int = 0, b: int = 0) -> bytes:
    """Message class 0x01, id 0x1E. Layout from the client's marshaller
    FUN_0050dbd8:

        func_0x005a0a18(ctx, base + 0x00, 0x15)   # 21 bytes (MessageID)
        func_0x005a0a38(ctx, 3)                    # 3 bytes alignment pad
        func_0x005a0a48(ctx, base + 0x18)          # u32
        func_0x005a0a48(ctx, base + 0x1c)          # u32

    Body is EXACTLY 21 + 3 + 4 + 4 = 32 bytes. Sending 72 bytes previously made
    the dispatcher consume 32 and then try to parse the leftovers as another
    sub-message, reading a garbage (class, id) pair -- that is where the
    error 1001 came from, NOT an unregistered id (0x1E is registered).
    """
    body = bytearray()
    body += _message_id_field(message_id)          # 21
    body += b"\x00" * 3                             # 3 pad
    body += struct.pack("<I", a)                    # 4
    body += struct.pack("<I", b)                    # 4
    assert len(body) == 32, len(body)
    return bytes(body)


_CERT_LENGTH_OFFSET = 0x13  # confirmed real, from Memdusa's CertificatePacketParser
_CERT_DATA_OFFSET = 0x15
_CN_OID = bytes([0x55, 0x04, 0x03])
_STRING_TAGS = (0x13, 0x0C, 0x16, 0x1E)  # PrintableString, UTF8String, IA5String, BMPString


def parse_client_hello_cert(payload: bytes):
    """Extract the last (Subject) Common Name from a client's CLIENT_HELLO-
    embedded certificate, if present. Confirmed real header layout: magic at
    [0:2], cert length (u16 LE) at 0x13, cert DER bytes starting at 0x15.
    Returns None if the payload is too short / doesn't look like it has one
    (e.g. an older/simpler client that skips the cert entirely)."""
    if len(payload) < _CERT_DATA_OFFSET + 4:
        return None
    cert_len = payload[_CERT_LENGTH_OFFSET] | (payload[_CERT_LENGTH_OFFSET + 1] << 8)
    if _CERT_DATA_OFFSET + cert_len > len(payload) or cert_len == 0:
        return None
    der = payload[_CERT_DATA_OFFSET:_CERT_DATA_OFFSET + cert_len]

    common_names = []
    pos = 0
    while pos <= len(der) - len(_CN_OID) - 4:
        if der[pos:pos + 3] == _CN_OID:
            value_tag = der[pos + 3]
            value_len = der[pos + 4]
            value_off = pos + 5
            if value_off + value_len <= len(der) and value_tag in _STRING_TAGS:
                try:
                    cn = der[value_off:value_off + value_len].decode("ascii").rstrip("\x00")
                    common_names.append(cn)
                except UnicodeDecodeError:
                    pass
        pos += 1
    return common_names[-1] if common_names else None


def build_app_message(msg_class: int, msg_id: int, body: bytes) -> bytes:
    # Envelope is [class][id], NOT [id][class]. Confirmed from a live capture of
    # the client's own GetUniverseInformation, whose first bytes are `01 c8`
    # (class 0x01 = LOBBY, id 0xC8), and from the client's dispatcher: it looks
    # the handler up as limit2 * payload[0] + payload[1] where payload[0] is
    # bounded by the number of CLASSES (FUN_003b3634 / FUN_003b2a68).
    # Emitting [id][class] put our response id (0x11) in the class slot, which is
    # out of range, and the client rejected it with error 1001.
    return bytes([msg_class, msg_id]) + body


MESSAGECLASS_DME = 0x00                 # NetMessageClass.MessageClassDME
DME_MSG_PACKET_FRAGMENT = 0x02          # MediusDmeMessageIds.PacketFragment
DME_FRAGMENT_MAX_PAYLOAD_SIZE = 484     # Constants.DME_FRAGMENT_MAX_PAYLOAD_SIZE


def build_packet_fragments(packet_class: int, packet_type: int, data: bytes):
    """Split an app message body too big for one RT frame into DME PacketFragment
    sub-messages, byte-exact to PSHome-MultiServer's TypePacketFragment
    (RT.Models/DME/TypePacketFragment.cs) -- the authoritative Medius reference.

    The client re-parses fragments as class 0x00 (MessageClassDME) / id 0x02
    (PacketFragment). My earlier format was wrong (a bogus TotalPacketSize /
    0x212a77 magic header): a 562-byte 0x11 split into two fragments the client
    could not parse, which is exactly the DME "err 1001" seen TWICE (one per
    fragment) before it gave up with NetUpdateAll 2500.

    Each returned bytes-string is the BODY of one RT_MSG_SERVER_APP frame:
        [0]      FragmentMessageClass  = the original message's class (e.g. 0x04)
        [1]      FragmentMessageType   = the original message's id    (e.g. 0x11)
        [2:4]    SubPacketSize   u16 LE = bytes of the original body in THIS frag
        [4:6]    SubPacketCount  u16 LE = total number of fragments
        [6:8]    SubPacketIndex  u16 LE = 0-based index of this fragment
        [8]      MultiPacketIndex      = 0
        [9:12]   3 bytes zero padding
        [12:16]  PacketBufferSize i32 LE = total original body length
        [16:20]  PacketBufferOffset i32 LE = this fragment's byte offset
        [20:]    this fragment's slice of the original body
    Note: `data` is the original message BODY only (the [class][id] envelope is
    NOT included -- class/type are carried in the fragment header fields).
    """
    total_len = len(data)
    # size each fragment's payload, then fill in the (now known) count
    slices = []
    pos = 0
    while pos < total_len:
        n = min(total_len - pos, DME_FRAGMENT_MAX_PAYLOAD_SIZE)
        slices.append((pos, data[pos:pos + n]))
        pos += n
    count = len(slices)
    fragments = []
    for index, (offset, chunk) in enumerate(slices):
        hdr = bytearray()
        hdr.append(packet_class & 0xFF)          # FragmentMessageClass
        hdr.append(packet_type & 0xFF)           # FragmentMessageType
        hdr += struct.pack("<H", len(chunk))     # SubPacketSize
        hdr += struct.pack("<H", count)          # SubPacketCount
        hdr += struct.pack("<H", index)          # SubPacketIndex
        hdr.append(0x00)                         # MultiPacketIndex
        hdr += b"\x00\x00\x00"                   # 3 pad
        hdr += struct.pack("<i", total_len)      # PacketBufferSize
        hdr += struct.pack("<i", offset)         # PacketBufferOffset
        fragments.append(bytes(hdr) + chunk)
    return fragments


# =============================================================================
# Per-connection Medius session state machine
# =============================================================================

class MediusSession:
    def __init__(self, sock: socket.socket, addr, port_label: str):
        self.sock = sock
        self.addr = addr
        self.port_label = port_label
        self.rsa = RsaCipher.generate(512)
        # Inbound and outbound use DIFFERENT keys. The client encrypts to us with
        # the key we hand it in SERVER_CRYPTKEY_PEER (self.rc_cipher), and we must
        # encrypt to the client with the key IT hands us in CLIENT_CRYPTKEY_PUBLIC
        # (self.rc_cipher_out). Using one key for both made the client fail with
        # "(RC_NOERROR == cryptError)" at rtmsgcl_tcp.c:3167 while our own inbound
        # decryption worked perfectly.
        self.rc_cipher: Ps3RcCipher = None
        self.rc_cipher_out: Ps3RcCipher = None
        self.buf = b""
        self.alive = True

    def log(self, msg):
        log.info("[%s %s] %s", self.port_label, self.addr, msg)

    # context 3 is what the real client uses on every encrypted message it sends,
    # and the context lives in the top 3 bits of the 4-byte hash (hash[3] >> 5).
    # The client passes that whole hash into its decrypt call
    # (interface[0x44] in FUN_003efbf8), which uses it to select the key -- so
    # sending context 0 made it pick the wrong/absent key and fail with
    # "(RC_NOERROR == cryptError)" at rtmsgcl_tcp.c:3167.
    def send_frame(self, rt_type, payload, encrypted=True, context=3):
        # Use the SERVER_CRYPTKEY_PEER key (self.rc_cipher) in both directions:
        # the client encrypts to us with it under context 3, and the context in
        # the hash selects the key slot, so context 3 should resolve to the same
        # key on its side. self.rc_cipher_out (the client's own CRYPTKEY_PUBLIC
        # material) is kept for reference but was tried and did not work either.
        cipher = self.rc_cipher if encrypted else None
        frame = build_rt_frame(rt_type, payload, cipher, context)
        self.sock.sendall(frame)

    def run(self):
        try:
            self._loop()
        except (ConnectionResetError, BrokenPipeError):
            self.log("connection reset")
        except Exception:
            log.exception("[%s %s] session error", self.port_label, self.addr)
        finally:
            try:
                self.sock.close()
            except OSError:
                pass

    def _loop(self):
        while self.alive:
            chunk = self.sock.recv(4096)
            if not chunk:
                break
            self.buf += chunk
            messages, consumed = parse_rt_frames(self.buf)
            self.buf = self.buf[consumed:]
            for rt_type, encrypted, cipher_hash, payload in messages:
                self._handle(rt_type, encrypted, cipher_hash, payload)

    def _handle(self, rt_type, encrypted, cipher_hash, payload):
        if encrypted and rt_type == RT_MSG_CLIENT_CRYPTKEY_PUBLIC:
            # Confirmed via live packet capture: this message arrives with the
            # encrypted bit set (71 wire bytes = 1+2+4+64) even though no RC4
            # session cipher exists yet -- it's RSA-encrypted using the public
            # key embedded in the certificate we just sent (see
            # build_session_certificate). Decrypt with our own matching
            # private key instead of treating the ciphertext as raw.
            context = cipher_hash[3] >> 5 if cipher_hash else 0
            ok, plain = self.rsa.decrypt(payload, cipher_hash, context)
            if not ok:
                # Best-effort only: the reference never actually uses this
                # decrypted content for anything the handshake depends on (the
                # real session key is always a fresh, independently-generated
                # one, sent next regardless). A previous version of this code
                # `return`ed here, which left self.rc_cipher permanently unset
                # for the rest of the session on RSA failure -- a real,
                # confirmed bug (caused later messages to silently skip
                # decryption and be treated as raw ciphertext). Log and
                # continue instead.
                self.log(f"WARNING: RSA decrypt/hash check failed for CLIENT_CRYPTKEY_PUBLIC "
                          f"(declared_context={context}) -- continuing anyway")
                self.log(f"  our_rsa_n(hex)={self.rsa.n.to_bytes(64, 'big').hex()}")
                self.log(f"  cipher_hash(hex)={cipher_hash.hex()}")
                self.log(f"  ciphertext(hex)={payload.hex()}")
            else:
                self.log(f"  RSA-decrypted client key material(hex)={plain.hex()}")
                payload = plain
        elif encrypted and self.rc_cipher is not None:
            ok, plain = self.rc_cipher.decrypt(payload, cipher_hash)
            if not ok:
                context = cipher_hash[3] >> 5 if cipher_hash else -1
                self.log(f"WARNING: hash check failed for rt_type=0x{rt_type:02x}, dropping "
                          f"(declared_context={context})")
                self.log(f"  session_key(hex)={self.rc_cipher.key.hex()}")
                self.log(f"  cipher_hash(hex)={cipher_hash.hex()}")
                self.log(f"  ciphertext(hex)={payload.hex()}")
                return
            payload = plain

        if rt_type == RT_MSG_CLIENT_HELLO:
            protocol_version = struct.unpack("<H", payload[2:4])[0] if len(payload) >= 4 else 0
            self.log(f"CLIENT_HELLO protocolVersion={protocol_version} ({len(payload)} bytes)")

            game_id = parse_client_hello_cert(payload)
            if game_id:
                self.log(f"  client cert Subject CN (game id): {game_id!r}")

            if protocol_version <= 110:
                resp = struct.pack("<H", protocol_version) + struct.pack("<H", 0x0600) + b"\x00" * 4
            else:
                # Confirmed real structure: [protocolVersion(2)][encryptionVersion(2)]
                # [certLen(2)][cert][4-byte pad]. Real captured Sony MAS
                # certificate shape, but with OUR OWN generated RSA modulus
                # spliced in -- live-confirmed the client accepts this
                # unsigned/re-keyed cert and proceeds (it doesn't validate the
                # signature chain), but we need to hold the matching private
                # key so we can actually decrypt CLIENT_CRYPTKEY_PUBLIC next.
                session_cert = build_session_certificate(self.rsa)
                resp = (struct.pack("<H", protocol_version) + struct.pack("<H", 0x0600)
                        + struct.pack("<H", len(session_cert)) + session_cert + b"\x00" * 4)
            self.send_frame(RT_MSG_SERVER_HELLO, resp, encrypted=False)

        elif rt_type == RT_MSG_CLIENT_CRYPTKEY_PUBLIC:
            self.log(f"CLIENT_CRYPTKEY_PUBLIC ({len(payload)} bytes, now RSA-decrypted)")
            # `payload` has already been RSA-decrypted (in _handle, above) using
            # our own keypair -- this is the client's real 64-byte key material,
            # plaintext. Server does NOT reuse it as the session key though: it's
            # only used to build an RSA cipher object (client's bytes as N,
            # e=d=17) for potential later use; the actual session key is a fresh
            # one we generate ourselves and send back unencrypted next.
            self.client_rsa = RsaCipher.from_client_key(payload if len(payload) >= 64 else payload.ljust(64, b"\x00"))
            # This 64-byte plaintext is the key the client expects US to encrypt
            # WITH when sending to it -- the mirror of SERVER_CRYPTKEY_PEER below.
            if len(payload) >= 16:
                self.rc_cipher_out = Ps3RcCipher(payload)
                self.log(f"  outbound cipher key(hex)={payload[:16].hex()}...")
            # Found a real, working reference server (hashsploit/clank, Java,
            # RtMsgClientCryptKeyPublicHandler.java) that sends this exact
            # hardcoded 64-byte key, RAW/unencrypted, as SERVER_CRYPTKEY_PEER
            # -- confirms "raw, not RSA-wrapped" was right all along (reverted
            # that hypothesis), and tries this known-real value directly
            # rather than a freshly random one, in case the client validates
            # against it specifically.
            fresh_key = bytes.fromhex(
                "E7477438E0234BB8196D574F09337BE7A72971628C551C3373A68BE7F1F108"
                "181EAAC2419AFA7583215E79775E9D6DBC8D442545EF396F29C6294C69FC97E177"
            )
            self.send_frame(RT_MSG_SERVER_CRYPTKEY_PEER, fresh_key, encrypted=False)
            self.rc_cipher = Ps3RcCipher(fresh_key)

        elif rt_type == RT_MSG_CLIENT_CONNECT_TCP:
            app_id = struct.unpack("<I", payload[4:8])[0] if len(payload) >= 8 else -1
            self.log(f"CLIENT_CONNECT_TCP ({len(payload)} bytes, appId={app_id})")
            # One flags byte, and it must be present: the client's handler
            # (FUN_003f3040) reads it unconditionally, so an empty payload made it
            # parse garbage and fail with reason 7. Bit 0 = server password follows,
            # bits 1/2 = a u16 version field follows which must equal 0x643. Sending
            # 0x00 selects "no password, no version check", and the client then
            # replies RT_MSG_CLIENT_CONNECT_READY_REQUIRE (0x23).
            self.send_frame(RT_MSG_SERVER_CONNECT_REQUIRE, b"\x00", encrypted=False)

        elif rt_type == RT_MSG_CLIENT_CONNECT_READY_REQUIRE:
            self.log("CLIENT_CONNECT_READY_REQUIRE")
            game_key = bytes(random.getrandbits(8) for _ in range(64))
            self.send_frame(RT_MSG_SERVER_CRYPTKEY_GAME, game_key)
            # SERVER_CONNECT_ACCEPT_TCP body must be EXACTLY 24 bytes -- the client's
            # handler (FUN_003f999c) asserts payload length == 0x18 and otherwise
            # tears the connection down. Layout, read back from that handler:
            #   u16 LE @0  -> conn+0x64   (client/player index)
            #   u32 LE @2  -> conn+0x68   (address)
            #   u16 LE @6  -> conn+0x74   (port)
            #   16 bytes @8 -> conn+0x6c
            body = (
                struct.pack("<H", 0)
                + bytes([127, 0, 0, 1])
                + struct.pack("<H", MEDIUS_DME_PORT)
                + b"\x00" * 16
            )
            assert len(body) == 0x18, len(body)
            self.send_frame(RT_MSG_SERVER_CONNECT_ACCEPT_TCP, body)
            # Deliberately NOT switching self.rc_cipher to game_key: the client keeps
            # using the original SERVER_CRYPTKEY_PEER key on THIS connection (proved
            # live -- its disconnect still decrypted under the original key while our
            # switched cipher failed). The game key is for the separate DME session.

        elif rt_type == RT_MSG_CLIENT_CONNECT_READY_TCP:
            self.log("CLIENT_CONNECT_READY_TCP")
            # Body must be EXACTLY 2 bytes: the client's handler (FUN_003f9c94)
            # reads one u16 LE into conn+0x74 and only accepts when the payload
            # length is 2, at which point it sets the connection state to 8
            # (connected). Any other length tears the connection down.
            self.send_frame(RT_MSG_SERVER_CONNECT_COMPLETE, struct.pack("<H", 0))

        elif rt_type == RT_MSG_CLIENT_ECHO:
            # Heartbeat -- the client's own assert string names it:
            # rtmsgcl_tcp_send_message(pChannel, RT_MSG_CLIENT_ECHO, 65535,
            #                          &HeartbeatData, sizeof(HeartbeatData), 0)
            # It arrives ~15s after connect and repeats; echo the body straight back.
            self.log(f"CLIENT_ECHO (heartbeat, {len(payload)} bytes) -> echoing back")
            self.send_frame(RT_MSG_CLIENT_ECHO, payload)

        elif rt_type == RT_MSG_CLIENT_APP_TOSERVER:
            self._handle_app_message(payload)

        elif rt_type == RT_MSG_CLIENT_DISCONNECT_WITH_REASON:
            reason = payload[0] if payload else -1
            names = {0: "NONE", 1: "NORMAL", 2: "CONNECT_FAIL", 3: "STREAMMEDIA_FAIL",
                     4: "UPDATE_FAIL", 5: "INACTIVITY", 6: "SHUTDOWN", 7: "LENGTH_MISMATCH"}
            self.log(f"CLIENT_DISCONNECT_WITH_REASON reason={reason} ({names.get(reason, '?')})")
            self.alive = False

        else:
            self.log(f"unhandled rt_type=0x{rt_type:02x}, {len(payload)} bytes: {payload[:32].hex()}")

    def _handle_app_message(self, payload):
        if len(payload) < 2:
            return
        # Log the raw envelope bytes verbatim. The client's dispatcher indexes a 2D
        # handler table as limit2*payload[0] + payload[1] (FUN_003b3634), while the
        # registration side uses limit2*class + id -- so which of the two bytes is
        # the class and which is the id is NOT obvious from our side, and getting it
        # backwards yields error 1001 ("no handler"/out of range) with no further
        # detail. Print the real bytes so this stops being guesswork.
        self.log(f"  app envelope raw: {payload[:8].hex()} (len={len(payload)})")
        msg_class, msg_id = payload[0], payload[1]
        body = payload[2:]

        if msg_class == MESSAGECLASS_LOBBY and msg_id == GET_UNIVERSE_INFORMATION:
            self._handle_get_universe_information(body)
        else:
            self.log(f"unhandled app message class=0x{msg_class:02x} id=0x{msg_id:02x}, {len(body)} bytes")

    def _handle_get_universe_information(self, body):
        message_id = body[0:21].decode("ascii", errors="replace").rstrip("\x00")
        info_filter = struct.unpack("<I", body[24:28])[0] if len(body) >= 28 else 0
        self.log(f"GetUniverseInformation InfoFilter=0x{info_filter:x}")

        # Both replies are FIXED size, taken from the client's own marshallers
        # (id 0x11 -> FUN_0050a59c, 294 bytes; id 0x1E -> FUN_0050dbd8, 32 bytes).
        # Sending anything else fails: too short sets lastError=8 in the field
        # reader, too long leaves trailing bytes that the dispatcher tries to
        # parse as a further sub-message and rejects with 1001.
        # The 0xC9 body carries ONE (u32, string) pair plus an end-of-list byte,
        # and the client asked for several info items at once (InfoFilter=0x27c
        # is six bits). So send one message per requested item, tagging each with
        # its InfoFilter bit in the u32, and only set end_of_list on the last.
        svo_url = f"http://{SVO_HOSTNAME}:{SVO_HTTP_PORT}/{os.environ.get('SVO_ROOT','BUZZPS3_SVML')}/"
        values = [
            (INFO_ID, "1"),
            (INFO_NAME, "Buzz Universe"),
            (INFO_DNS, "127.0.0.1"),
            (INFO_DESCRIPTION, "Buzz Quiz World"),
            (INFO_STATUS, "1"),
            (INFO_SVO_URL, svo_url),
        ]
        wanted = [(bit, text) for bit, text in values if info_filter & bit]

        # --- experiment knobs (env vars) so the reply can be varied per boot
        # without code edits. The 0xC9 fields are (u32 @0x18, string @0x1c,
        # byte @0x11c); the client parses them cleanly but then disconnects
        # NORMAL, so the semantics of those fields are what we are probing.
        import os as _os
        mode = _os.environ.get("UNIV_MODE", "ext")   # ext | per_bit | single
        flag_last = int(_os.environ.get("UNIV_FLAG_LAST", "1"))
        flag_other = int(_os.environ.get("UNIV_FLAG_OTHER", "0"))
        u32_mode = _os.environ.get("UNIV_U32", "bit")   # bit | port | id | zero
        single_text = _os.environ.get("UNIV_TEXT", "Buzz Universe")

        def u32_for(bit, i):
            return {"bit": bit, "port": MEDIUS_DME_PORT, "id": i + 1, "zero": 0}[u32_mode]

        if mode == "ext":
            # The real thing: class 0x04 0x1E (SVO url) then class 0x04 0x11.
            # UNIV_EXT_MASK lets a boot drop bits from the reply filter (e.g.
            # 0x25c = no 256-byte description -> 306-byte body, one RT frame).
            reply_filter = info_filter & int(_os.environ.get("UNIV_EXT_MASK", "0xffffffff"), 0)
            status_code = int(_os.environ.get("UNIV_STATUS", "0"))
            self.log(f"  replying ext: 0x1E url={svo_url!r} then 0x11 filter=0x{reply_filter:x} "
                     f"status_code={status_code} end_of_list={flag_last}")
            if reply_filter & INFO_SVO_URL:
                self._send_server_app_fragmented(
                    MESSAGECLASS_LOBBYEXT, UNIVERSE_SVO_URL_RESPONSE,
                    build_universe_svo_url_response_ext(message_id, svo_url))
            # DME DNS must be a HOSTNAME in RPCS3's IP-swap list
            # (buzzps3.online.scee.com=127.0.0.1), NOT a literal IP. The client
            # resolves this field via NetGetHostByName; a literal "127.0.0.1"
            # bypasses the swap, hits the real DNS (8.8.8.8), fails to resolve,
            # and the DME connect dies with "DME Net Error 2500". Sending the
            # swapped hostname makes it resolve to 127.0.0.1 -> our DME listener.
            # UNIV_DNS: literal "127.0.0.1" (default) lets SCE-RT's NetGetHostByName
            # inet_addr() it directly with no DNS lookup; the hostname form relies on
            # RPCS3's IP-swap AND on SCE-RT using gethostbyname (unconfirmed). Both
            # currently end in "DME Net Error 2500" (the DME connect aborts before
            # opening a socket — see project memory), so this is a knob for now.
            # DNS must be the swapped HOSTNAME, not a literal IP: RPCS3's DnsHook
            # resolves buzzps3.online.scee.com -> 127.0.0.1 (confirmed in RPCS3.log),
            # and the hostname makes the client's SelectServer perform its own
            # NetGetHostByName on the universe (the select->connect step fires).
            # A literal "127.0.0.1" skips that resolution entirely. (2026-09-14)
            dme_dns = _os.environ.get("UNIV_DNS", SVO_HOSTNAME)
            body11 = build_universe_variable_information_response(
                message_id, reply_filter, universe_id=1, name=single_text,
                dns=dme_dns, port=MEDIUS_DME_PORT, status_code=status_code,
                end_of_list=flag_last)
            self.log(f"  0x11 body {len(body11)} bytes")
            self._send_server_app_fragmented(MESSAGECLASS_LOBBYEXT,
                                             UNIVERSE_VARIABLE_INFO_RESPONSE, body11)
            return

        packets = []
        if mode == "single":
            packets.append((UNIVERSE_INFO_RESPONSE,
                            build_universe_information_response(
                                message_id, single_text, value=u32_for(0, 0),
                                end_of_list=flag_last)))
        else:
            for i, (bit, text) in enumerate(wanted):
                last = flag_last if i == len(wanted) - 1 else flag_other
                packets.append((UNIVERSE_INFO_RESPONSE,
                                build_universe_information_response(
                                    message_id, text, value=u32_for(bit, i),
                                    end_of_list=last)))
        self.log(f"  replying with {len(packets)} universe item(s) mode={mode} "
                 f"u32={u32_mode} flag_last={flag_last} flag_other={flag_other}")

        # Reply in the SAME message class the request arrived in (0x01), not
        # LOBBYEXT (0x04). The client's handler table is indexed by both envelope
        # bytes and rejects an unregistered/out-of-range pair with error 1001,
        # which is exactly what we got back using 0x04.
        for rt_sub_type, body_bytes in packets:
            self._send_server_app_fragmented(MESSAGECLASS_LOBBY, rt_sub_type, body_bytes)

    def _send_server_app_fragmented(self, packet_class: int, packet_type: int, body: bytes, max_chunk=512):
        """Send an application-layer message. A message whose [class][id][body]
        envelope fits in one RT frame (<= MEDIUS_MESSAGE_MAXLEN = 512) goes as a
        single RT_MSG_SERVER_APP. A larger one is split into DME PacketFragment
        sub-messages (class 0x00 / id 0x02), byte-exact to the PSHome-MultiServer
        Medius reference -- each fragment is its own RT_MSG_SERVER_APP frame with
        the [0x00][0x02] DME envelope. The reference's own threshold is the
        message length (envelope + body) exceeding 512."""
        if len(body) + 2 <= max_chunk:
            self.send_frame(RT_MSG_SERVER_APP, build_app_message(packet_class, packet_type, body))
            return
        fragments = build_packet_fragments(packet_class, packet_type, body)
        self.log(f"  fragmenting {len(body)}-byte class=0x{packet_class:02x} id=0x{packet_type:02x} "
                 f"into {len(fragments)} DME PacketFragment(s)")
        for frag in fragments:
            self.send_frame(RT_MSG_SERVER_APP,
                            build_app_message(MESSAGECLASS_DME, DME_MSG_PACKET_FRAGMENT, frag))


# =============================================================================
# TCP listener plumbing
# =============================================================================

def serve_medius(port: int, label: str):
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((HOST, port))
    srv.listen(8)
    log.info("Medius listener [%s] on %s:%d", label, HOST, port)
    while True:
        conn, addr = srv.accept()
        # Log the bare accept, before any protocol parsing: without this a client
        # that opens a TCP connection but never sends a CLIENT_HELLO is completely
        # invisible in the log, which makes "the game didn't retry at all" and
        # "the game retried but stalled before sending anything" indistinguishable.
        log.info("[%s %s] TCP ACCEPT", label, addr)
        session = MediusSession(conn, addr, label)
        threading.Thread(target=session.run, daemon=True, name=f"{label}-{addr[1]}").start()


# =============================================================================
# SVO / SVML HTTP layer (port 10060)
# =============================================================================

def compute_svomac(client_mac: str) -> str:
    return hashlib.md5((client_mac + SVOMAC_SALT).encode("ascii")).hexdigest()


SVML_START_HOME = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<SVML>
  <DATA dataType="URI" name="getRandomUCQ" value="http://{host}:{port}/BUZZPS3_SVML/usercreated/homeapp/HomeApp_UCQBatch.jsp" />
  <DATA dataType="URI" name="reportUCQ" value="http://{host}:{port}/BUZZPS3_SVML/servlets/HomeUCQReportServlet" />
  <DATA dataType="URI" name="getRandomAdvert" value="http://{host}:{port}/BUZZPS3_SVML/usercreated/homeapp/start_HOME.jsp" />
  <DATA dataType="URI" name="getVariants" value="http://{host}:{port}/BUZZPS3_SVML/usercreated/homeapp/start_HOME.jsp" />
  <DATA dataType="URI" name="logger" value="http://{host}:{port}/BUZZPS3_SVML/usercreated/homeapp/start_HOME.jsp" />
</SVML>"""

# The game's SVO "URI store" start page (GET <svo_url>?languageID=N, issued
# by unity state 10 right after universe selection). Format taken from
# PSHome-MultiServer's SingStar/RFOM handlers (same SCEE SVO middleware);
# the names are the ones Buzz's own binary looks up (SVURIStore strings at
# 0x6eed08 / 0x6fbc28). The client-side ticket login (FUN_00367888) insists
# TicketLoginURI starts with "https:", so that one is served over the
# SVO_HTTPS_PORT when SVO_TICKET_SCHEME=https.
# The COMPLETE set of URI names Buzz's native code looks up in the SVURIStore
# (every `FUN_00364d5c(store, name)` call site in EBOOT_patched.elf). If a name
# the current unity state needs is ABSENT, the lookup fails and the page load
# returns status 4 -> "Wait unity not busy error screen". unitySimplePolicyURI
# is the one loaded right after the URI store, so it is mandatory. Paths are our
# own; the server serves each (see do_GET) -- what matters first is that every
# name RESOLVES.
_SVO_URI_NAMES_HTTP = [
    ("unitySimplePolicyURI", "policy.jsp"),
    ("homeURI", "home.jsp"),
    ("landingPageURI_2009", "landingpage.jsp"),
    ("localeDataURI_2009", "localedata.jsp"),
    ("propertiesURI_2009", "properties.jsp"),
    ("advertisingListURI_2009", "advertlist.jsp"),
    ("leaderboards_2009", "leaderboards.jsp"),
    ("leaderBoardTimeFrameURI", "leaderboard.jsp"),
    ("staticImageURLBase", "images/"),
    ("myBuzzQuizURL", "mybuzz/quiz.jsp"),
    ("buzzTheGameURL", "mybuzz/game.jsp"),
    ("tagList_2009", "mybuzz/taglist.jsp"),
    ("categoryList_2009", "mybuzz/categorylist.jsp"),
    ("categoryParentList_2009", "mybuzz/categoryparentlist.jsp"),
    ("myPlaylists_2009", "mybuzz/myplaylists.jsp"),
    ("myFavourites_2009", "mybuzz/myfavourites.jsp"),
    ("myQuizzes_2009", "mybuzz/myquizzes.jsp"),
    ("myBuddyQuizList_2009", "mybuzz/buddyquizlist.jsp"),
    ("myBuddyList_2009", "mybuzz/buddylist.jsp"),
    ("reportURL", "mybuzz/report.jsp"),
    ("ratingURL", "mybuzz/rating.jsp"),
    ("myFacebookInfo_2009", "facebook/info.jsp"),
    ("facebookWallPostNotify_2009", "facebook/wallpost.jsp"),
    ("fileServicesSnapshotUploadServletURI", "servlets/SnapshotUpload"),
    ("fileServicesUploadServletURI", "servlets/FileUpload"),
    ("ucqDownloadURL", "usercreated/homeapp/HomeApp_UCQBatch.jsp"),
    ("gamePostBinaryStatsURI", "game/Game_PostBinaryStats_Submit.jsp"),
    ("gameBinaryStatsPostURI", "game/Game_BinaryStatsPost_Submit.jsp"),
    ("createGameURI", "game/Game_Create.jsp?gameMode=%d"),
    ("gameCreateURL", "game/tempgame.jsp"),
    ("createGameSubmitURI", "game/Game_Create_Submit.jsp"),
    ("createGamePlayerURI", "game/Game_Create_Player_Submit.jsp?SVOGameID=%d&playerSide=%d"),
    ("createGamePlayerURL", "game/Game_Create_Player_Submit.jsp"),
    ("gameFinishURI", "game/Game_Finish_Submit.jsp"),
    ("gameFinishURL", "game/Game_Finish_Submit.jsp"),
    ("finishGameURI", "game/Finish_Game_Submit.jsp"),
    ("finishGameURL", "game/Finish_Game_Submit.jsp"),
    ("drmSignatureURI", "commerce/Commerce_BufferedSignature.jsp"),
    # UCQ channel/browse game lists (Best/Fresh/Quick/Subject/Tag) - needed so the
    # channel games can pull a quiz list. Route all to the quiz-list handler.
    ("ucqFreshGameList_2009", "mybuzz/freshgamelist.jsp"),
    ("ucqBestGameList_2009", "mybuzz/bestgamelist.jsp"),
    ("ucqQuickGameList_2009", "mybuzz/quickgamelist.jsp"),
    ("ucqBestOfChannelGameList_2009", "mybuzz/bestofchannelgamelist.jsp"),
    ("ucqListURI_Live", "mybuzz/ucqlist.jsp"),
    ("myPlaylistQuizList_2009", "mybuzz/myplaylistquizlist.jsp"),
    ("categoryQuizList_2009", "mybuzz/categoryquizlist.jsp"),
    ("tagQuizList_2009", "mybuzz/tagquizlist.jsp"),
]
_SVO_URI_NAMES_SECURE = [
    ("TicketLoginURI", "account/SP_Login_Submit.jsp"),
    ("loginEncryptedURI", "account/Account_Encrypted_Login_Submit.jsp"),
    ("loginEncryptedURL", "account/Account_Encrypted_Login_Submit.jsp"),
    ("spUpdateTicketURI", "account/SP_UpdateTicket.jsp"),
    ("SetBuddyListURI", "buddy/Buddy_SetList_Submit.jsp"),
    ("SetIgnoreListURI", "account/SP_UpdateIgnoreList_Submit.jsp"),
    ("SetUniversePasswordURI", "account/SP_SetPassword_Submit.jsp"),
]
SVO_HTTPS_PORT = 10061
CRLF = chr(13) + chr(10)
SVML_EMPTY = '<?xml version="1.0" encoding="UTF-8"?>' + CRLF + '<SVML>' + CRLF + '</SVML>' + CRLF


# SVO root path: BUZZPS3_SVML for Buzz, HOST_SVML for SingStar. env SVO_ROOT.
SVO_ROOT = os.environ.get("SVO_ROOT", "BUZZPS3_SVML")

# SingStar SVURIStore names (reversed from SingStar Queen EBOOT). .svml pages, HOST_SVML
# root. Names match SingStar's FUN lookups; paths are ours (what matters is the names
# RESOLVE). Shared with Buzz: TicketLoginURI/loginEncrypted*/spUpdateTicketURI/createGame*/
# gameFinish*/finishGame*/drmSignatureURI/Set*URI. SingStar-only: back/patch/photo/etc.
_SVO_URI_NAMES_SINGSTAR = [
    ("TicketLoginURI", "account/SP_Login_Submit.svml"),
    ("loginEncryptedURI", "account/Account_Encrypted_Login_Submit.svml"),
    ("loginEncryptedURL", "account/Account_Encrypted_Login_Submit.svml"),
    ("spUpdateTicketURI", "account/SP_UpdateTicket.svml"),
    ("SetBuddyListURI", "buddy/Buddy_SetList_Submit.svml"),
    ("SetIgnoreListURI", "account/SP_UpdateIgnoreList_Submit.svml"),
    ("SetUniversePasswordURI", "account/SP_SetPassword_Submit.svml"),
    ("createGameURI", "game/Game_Create.svml?gameMode=%d"),
    ("createGameSubmitURI", "game/Game_Create_Submit.svml"),
    ("createGamePlayerURI", "game/Game_Create_Player_Submit.svml?SVOGameID=%d&playerSide=%d"),
    ("createGamePlayerURL", "game/Game_Create_Player_Submit.svml"),
    ("gameFinishURI", "game/Game_Finish_Submit.svml"),
    ("gameFinishURL", "game/Game_Finish_Submit.svml"),
    ("finishGameURI", "game/Finish_Game_Submit.svml"),
    ("finishGameURL", "game/Finish_Game_Submit.svml"),
    ("gamePostBinaryStatsURI", "game/Game_PostBinaryStats_Submit.svml"),
    ("gameBinaryStatsPostURI", "game/Game_BinaryStatsPost_Submit.svml"),
    ("gameCreateURL", "game/tempgame.svml"),
    ("drmSignatureURI", "commerce/Commerce_BufferedSignature.svml"),
    ("backRequestURL", "back.svml"),
    ("patchURL", "patch.svml"),
    ("photoTakenURL", "photo.svml"),
    ("noCameraURL", "nocamera.svml"),
    ("PRODUCT_IMAGEURL", "images/"),
    ("EXCEPTIONURL", "exception.svml"),
]


# URI-store values are TEMPLATES. The game looks up a URI, finds a literal token in it
# (std::string::find) and replaces it with the selected item's value - e.g. FUN_0021a1f8
# replaces "fileNameBeginsWith=%s" with "fileNameBeginsWith=<filename>" and "fileID=%d"
# with "fileID=<quizid>". A value WITHOUT the token is silently left alone, which is why
# the plain "HomeApp_UCQBatch.jsp" value never told us which favourite was played, and why
# rating.jsp arrived without its parameters. Tokens come from the EBOOT's parameter-string
# cluster (each "x=%d"/"x=%s" needle sits beside its "x=" replacement prefix). Real Sony
# SVML used raw unescaped '&' inside attributes, so we do too. BUZZ_URI_TEMPLATES=0 reverts.
_URI_TEMPLATES = {
    "ucqDownloadURL": "servlets/DownloadFileServlet?fileID=%d&fileNameBeginsWith=%s&fileTypeID=6",
    "ratingURL": "mybuzz/rating.jsp?fileID=%d&fileRating=%d&correctAnswers=%d",
    "reportURL": "mybuzz/report.jsp?fileID=%d&fileGriefReportType=%d",
    "tagList_2009": "mybuzz/taglist.jsp?tag=%s",
    "myPlaylists_2009": "mybuzz/myplaylists.jsp?fileID=%d",
    "categoryList_2009": "mybuzz/categorylist.jsp?categoryId=%s",
    "myBuddyQuizList_2009": "mybuzz/buddyquizlist.jsp?fileOwnerID=%d",
    # StartDownloadLeaderboards printf()s this value with a locale id (FUN_0015ee68), so it
    # must contain %d. The leaderboard menu screen instead appends "%s%d" to the next one.
    "leaderboards_2009": "leaderboards.jsp?region=%d",
    "leaderBoardTimeFrameURI": "mybuzz/leaderboard.jsp?menu=",
}


def build_svo_start_page(client_ip: str) -> str:
    base_http = f"http://{SVO_HOSTNAME}:{SVO_HTTP_PORT}/{SVO_ROOT}/"
    if os.environ.get("SVO_TICKET_SCHEME", "http") == "https":
        base_sec = f"https://{SVO_HOSTNAME}:{SVO_HTTPS_PORT}/{SVO_ROOT}/"
    else:
        base_sec = base_http
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', "<SVML>",
             f'    <SET name="IP" IPAddress="{client_ip}" />']
    if SVO_ROOT == "HOST_SVML":  # SingStar
        for name, path in _SVO_URI_NAMES_SINGSTAR:
            lines.append(f'    <DATA dataType="URI" name="{name}" value="{base_http}{path}" />')
    else:  # Buzz
        templates = os.environ.get("BUZZ_URI_TEMPLATES", "1") == "1"
        for name, path in _SVO_URI_NAMES_HTTP:
            if templates:
                # the game's parser drops a raw '&' here, so escape it (see _query)
                path = _URI_TEMPLATES.get(name, path).replace("&", "&amp;")
            lines.append(f'    <DATA dataType="URI" name="{name}" value="{base_http}{path}" />')
        for name, path in _SVO_URI_NAMES_SECURE:
            lines.append(f'    <DATA dataType="URI" name="{name}" value="{base_sec}{path}" />')
    lines.append('    <BROWSER_INIT name="init" />')
    lines.append("</SVML>")
    return "\r\n".join(lines) + "\r\n"


SVML_UCQ_BATCH = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<SVML>
  <COUNT value="1" />
  <UCQ>
    <Content>
      <root>
        <round>
          <question>Placeholder question -- fake server stub</question>
          <answerset>
            <answer correct="true">Correct</answer>
            <answer correct="false">Wrong 1</answer>
            <answer correct="false">Wrong 2</answer>
            <answer correct="false">Wrong 3</answer>
          </answerset>
        </round>
      </root>
    </Content>
  </UCQ>
</SVML>"""


_HP_UCQ_CACHE = None
def _hp_ucq():
    """Real Harry Potter quiz UCQ (hp_raw.json) in the correct schema
    (root/round/question/questiontext/answerset/answer/answertext/answercorrect),
    reversed from the EBOOT parser. Falls back to the placeholder if unavailable."""
    global _HP_UCQ_CACHE
    if _HP_UCQ_CACHE is not None:
        return _HP_UCQ_CACHE
    try:
        import build_hp_ucq
        hp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hp_raw.json")
        _HP_UCQ_CACHE = build_hp_ucq.build(hp)
    except Exception as e:
        log.warning("HP UCQ build failed (%s); using placeholder", e)
        _HP_UCQ_CACHE = SVML_UCQ_BATCH
    return _HP_UCQ_CACHE


_HP_FAV_CACHE = None
def _hp_favourites(only_id=None):
    """Quiz LIST SVML (<UCQ type=QUIZ_LIST/QUIZITEM>) for favourites/myquizzes/
    category list pages. Content is fetched separately via HomeApp_UCQBatch.jsp."""
    global _HP_FAV_CACHE
    if only_id is None and _HP_FAV_CACHE is not None:
        return _HP_FAV_CACHE
    try:
        import build_hp_ucq
        hp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hp_raw.json")
        # REAL Buzz format: <MyBuzzTag2009Tag><MyBuzzQuizItem2009Tag .../></...>
        out = build_hp_ucq.build_mybuzz_list(hp, only_id=only_id)
    except Exception as e:
        log.warning("HP favourites build failed (%s); using empty", e)
        out = SVML_EMPTY
    if only_id is None:
        _HP_FAV_CACHE = out
    return out


def _hp_single_quiz(qid):
    """Raw content XML for one downloaded quiz (root/round/question...). Served for the
    per-item download (StartQuizDownloadFromQuizItem -> IsDownloadedQuizValidXML)."""
    try:
        import build_hp_ucq
        hp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hp_raw.json")
        return build_hp_ucq.build_single_quiz(int(qid), hp)
    except Exception as e:
        log.warning("HP single-quiz build failed (%s)", e)
        return SVML_EMPTY


_CATALOG_FAILED = False
def _catalog():
    """The quiz catalogue (buzz_catalog.py, packs in content/packs/*.json), or None if it is
    disabled (BUZZ_CATALOG=0) or has no quizzes - then the legacy HP handlers serve."""
    global _CATALOG_FAILED
    if _CATALOG_FAILED or os.environ.get("BUZZ_CATALOG", "1") != "1":
        return None
    try:
        import buzz_catalog
        cat = buzz_catalog.get_catalog()
        if cat.quizzes:
            return cat
        log.warning("[CATALOG] no quizzes in %s; using legacy handlers", buzz_catalog.PACK_DIR)
    except Exception as e:
        log.warning("[CATALOG] failed to load (%s); using legacy handlers", e)
    _CATALOG_FAILED = True
    return None


def _qid_from_query(full_path, default=1):
    """Pull a quiz id from ?fileID= / ?quizid= / ?id= in the raw request path."""
    try:
        from urllib.parse import urlparse, parse_qs
        q = parse_qs(urlparse(full_path).query)
        for k in ("fileID", "quizid", "quizID", "id", "quizItemID", "fileNameBeginsWith"):
            if k in q and q[k]:
                try:
                    return int(q[k][0])
                except (ValueError, TypeError):
                    # fileNameBeginsWith may be a hash/name; fall back to a valid quiz
                    return default
    except Exception:
        pass
    return default


# unitySimplePolicyURI page. The front-end loads this right after the URI store;
# GetPolicyText/EULA read from it. Kept minimal but non-empty.
def _svml_policy():
    mode = os.environ.get("SVO_POLICY", "unity")
    if mode == "unity":
        # The <UNITY> element triggers the policy completion handler (case 22,
        # FUN_00350b7c), which calls strlen(getContent()) -> the tag MUST have
        # non-null TEXT CONTENT (the policy text) or the game crashes with a null
        # read in strlen. So use an open/close <UNITY> with the policy text inside,
        # NOT a self-closing tag.
        policy_text = ("Buzz Quiz World online play is subject to the terms of the "
                       "PlayStation Network Terms of Service and User Agreement.")
        # Post-policy navigation (2026-09-14, from SingStar LoginTagModule/RedirectTagModule
        # analysis): the browser must proceed to a login/home page after the policy. Use an
        # ABSOLUTE href to the swapped hostname (relative "../home.jsp" resolved wrong, to
        # /home.jsp outside BUZZPS3_SVML, and the client never navigated). linkoption is a
        # knob (SingStar navigates via CLIENT_REDIRECT).
        home_url = f"http://{SVO_HOSTNAME}:{SVO_HTTP_PORT}/BUZZPS3_SVML/home.jsp"
        linkopt = os.environ.get("SVO_POLICY_LINKOPT", "CLIENT_REDIRECT")
        return ('<?xml version="1.0" encoding="UTF-8"?>' + CRLF + "<SVML>" + CRLF +
                f'    <UNITY name="policy" type="POLICY" success_href="{home_url}" success_linkoption="{linkopt}">' +
                policy_text + "</UNITY>" + CRLF +
                "</SVML>" + CRLF)
    if mode == "page":
        return ('<?xml version="1.0" encoding="UTF-8"?>' + CRLF + "<SVML>" + CRLF +
                '    <TEXT name="text" x="640" y="171" width="636" height="26" fontSize="26" align="center">Usage Policy</TEXT>' + CRLF +
                '    <QUICKLINK name="accept" button="SV_PAD_X" linkOption="NORMAL" href="../home.jsp"/>' + CRLF +
                "</SVML>" + CRLF)
    return ('<?xml version="1.0" encoding="UTF-8"?>' + CRLF + "<SVML>" + CRLF +
            '    <DATA dataType="STRING" name="policy" value="Buzz Quiz World online." />' + CRLF +
            "</SVML>" + CRLF)


SVML_POLICY = _svml_policy()


_SVO_HTTP_MODE = os.environ.get("SVO_HTTP", "10close")   # 10close | 11keepalive | 11close


class SvoHandler(http.server.BaseHTTPRequestHandler):
    server_version = "Apache-Coyote/1.1"
    sys_version = ""
    protocol_version = "HTTP/1.1" if _SVO_HTTP_MODE.startswith("11") else "HTTP/1.0"

    def log_message(self, fmt, *args):
        log.info("[SVO %s] %s", self.client_address, fmt % args)

    def _log_request(self):
        hdrs = "; ".join(f"{k}: {v}" for k, v in self.headers.items())
        log.info("[SVO] %s %s  headers{%s}", self.command, self.path, hdrs)

    def _reply(self, body, content_type=None, extra_headers=()):
        if content_type is None:
            # The page-downloader may match the type exactly; the "; charset=UTF-8"
            # suffix is a suspect. SVO_CT knob: "plain" -> "text/svml"; else full.
            content_type = "text/svml" if os.environ.get("SVO_CT", "plain") == "plain" else "text/svml; charset=UTF-8"
        data = body.encode("utf-8") if isinstance(body, str) else body
        keepalive = _SVO_HTTP_MODE == "11keepalive"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Connection", "keep-alive" if keepalive else "close")
        if os.environ.get("SVO_STATUSCODE", "1") == "1":
            self.send_header("x-statuscode", "0")   # SCEE SVO success status; RFOM/Home set this
        client_mac = self.headers.get("X-SVOMac")
        if client_mac:
            self.send_header("X-SVOMac", compute_svomac(client_mac))
        for k, v in extra_headers:
            self.send_header(k, v)
        self.end_headers()
        # Send headers and body as SEPARATE TCP segments. The SVO page-downloader
        # appears to read the header block in one recv() and then the body in a
        # later recv(); when a small response arrives headers+body in a single
        # packet it reads the headers and then blocks waiting for a body that has
        # already been delivered (large responses like the URI store split across
        # packets naturally and worked). Flushing + TCP_NODELAY + a tiny gap
        # forces two segments. Toggle with SVO_SPLIT=0.
        if os.environ.get("SVO_SPLIT", "1") == "1":
            try:
                self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                self.wfile.flush()
                time.sleep(0.05)
            except OSError:
                pass
        self.wfile.write(data)
        self.wfile.flush()
        if not keepalive:
            # Force the write side shut so the guest gets EOF promptly.
            try:
                self.connection.shutdown(socket.SHUT_WR)
            except OSError:
                pass
            self.close_connection = True
        else:
            self.close_connection = False
        log.info("[SVO]   -> 200 %s %d bytes (%s)", content_type, len(data), _SVO_HTTP_MODE)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        self._log_request()
        # Debug knob: hold the reply so the client parks in whatever unity
        # state issued this request (lets a GDB read see the live state object).
        delay = float(os.environ.get("SVO_DELAY", "0"))
        if delay:
            log.info("[SVO] holding reply for %.0fs (SVO_DELAY)", delay)
            time.sleep(delay)

        if path in ("/BUZZPS3_SVML/", "/BUZZPS3_SVML", "/HOST_SVML/", "/HOST_SVML"):
            self._reply(build_svo_start_page(self.client_address[0]))
        elif path.endswith("policy.jsp"):
            self._reply(SVML_POLICY)
        elif path.endswith("home.jsp"):
            # Post-policy login page (SingStar SVO LoginTagModule reference): a <LOGIN>
            # tag that submits to the ticket-login URI; our do_POST answers it with the
            # SP_Login response (status/accountID/userContext). SVO_HOME knob to vary.
            login_url = f"http://{SVO_HOSTNAME}:{SVO_HTTP_PORT}/BUZZPS3_SVML/account/SP_Login_Submit.jsp"
            hmode = os.environ.get("SVO_HOME", "login")
            if hmode == "login":
                home = ('<?xml version="1.0" encoding="UTF-8"?>' + CRLF + '<SVML>' + CRLF +
                        f'    <LOGIN name="login" href="{login_url}" />' + CRLF +
                        '</SVML>' + CRLF)
            else:  # plain text page (test navigation only)
                home = ('<?xml version="1.0" encoding="UTF-8"?>' + CRLF + '<SVML>' + CRLF +
                        '    <TEXT name="t" x="320" y="200" width="600" height="30" fontSize="24" align="center">Buzz Online</TEXT>' + CRLF +
                        '</SVML>' + CRLF)
            self._reply(home)
        elif path.endswith("start_HOME.jsp"):
            self._reply(SVML_START_HOME.format(host=SVO_HOSTNAME, port=SVO_HTTP_PORT))
        elif _catalog() is not None and self._catalog_route(path):
            pass   # served from the quiz catalogue (content/packs/*.json)
        elif "DownloadFileServlet" in path:
            # Per-quiz CONTENT download (StartQuizDownloadFromQuizItem, fileTypeID=6).
            # Serve one valid quiz's raw XML keyed by fileID.
            self._reply(_hp_single_quiz(_qid_from_query(self.path)), "text/xml")
        elif path.endswith("HomeApp_UCQBatch.jsp") or "UCQBatch" in path or "getRandomUCQ" in path \
                or "ucqDownload" in path.lower():
            # CONTENT download endpoint (getRandomUCQ / ucqDownloadURL). This is the ONLY
            # content request the game makes when playing a favourite (proven from the log:
            # myfavourites -> HomeApp_UCQBatch.jsp?agecat=7 -> rating; no DownloadFileServlet).
            # The play-time content parser (FUN_000f3d40 -> FUN_000f3b70 -> FUN_000f3274)
            # requires the parsed document's TOP-LEVEL element to be <root>: it looks up
            # "root" as a DIRECT (non-recursive) child of the document, confirmed from the
            # DOM primitives FUN_004b97c8 (child-by-name, siblings only) and FUN_004b9dbc.
            # So serve BARE <root><round version="1.0" type="standard"><question>... and do
            # NOT wrap it in <SVML>/<COUNT>/<UCQ>/<Content> - that wrapper made <SVML> the
            # document's top element, so "root" was never found -> 0 questions -> the game
            # jumped straight to the rating screen. (UCQ_BATCH_STYLE=batch restores the old
            # SVML-wrapped batch for A/B comparison.)
            qid = _qid_from_query(self.path, default=0)
            style = os.environ.get("UCQ_BATCH_STYLE", "single")
            if style == "batch":
                self._reply(_hp_ucq())                       # OLD SVML batch (kept for A/B)
            else:
                if not qid:
                    qid = int(os.environ.get("UCQ_QID", "1"))
                content = _hp_single_quiz(qid)
                # BACKUP: if the DOM parser treats the <?xml?> PI as document.firstChild
                # (so firstChild is the PI, not <root>, and the type-5 check fails), set
                # UCQ_XMLDECL=0 to strip the declaration so <root> is unambiguously first.
                if os.environ.get("UCQ_XMLDECL", "1") == "0":
                    content = "\r\n".join(l for l in content.splitlines()
                                          if not l.lstrip().startswith("<?xml")) + "\r\n"
                self._reply(content, "text/xml")
        elif any(k in path.lower() for k in (
                "myfavourites", "myquizzes", "gamelist", "quizlist", "ucqlist",
                "categorylist", "buddyquizlist")):
            # LIST pages (favourites/myquizzes/channel game lists/category/tag/buddy):
            # quiz metadata list <MYBUZZ_V1 type=TAG2009/QUIZITEM2009>. Backup-hypothesis
            # knobs: MYBUZZ_ROOT=bare (drop <SVML>), MYBUZZ_CT=text/xml (content-type).
            _ct = os.environ.get("MYBUZZ_CT")  # e.g. 'text/xml; charset="utf-8"'
            self._reply(_hp_favourites(), _ct)
        else:
            self._reply(SVML_EMPTY)

    # ---- quiz catalogue routes ------------------------------------------------------
    # Parameter names the game substitutes into our URI templates. The game's SVML parser
    # DROPS a raw '&' inside the URI-store attribute (observed 2026-09-26:
    # "fileID=2fileNameBeginsWith=2fileTypeID=6&agecat=7"), so re-split glued queries on
    # these known names before parsing. The store now sends &amp; as well.
    _QKEYS = ("fileID", "fileNameBeginsWith", "fileTypeID", "fileRating", "correctAnswers",
              "fileGriefReportType", "fileOwnerID", "categoryId", "tag", "agecat",
              "languageID", "playlistid", "quizid", "board", "menu", "region")

    def _query(self):
        import re
        from urllib.parse import urlparse, parse_qs
        q = urlparse(self.path).query.replace("amp;", "")
        q = re.sub(r"(?<![&?])(?=(?:%s)=)" % "|".join(self._QKEYS), "&", q)
        return parse_qs(q)

    def _qstr(self, key):
        """Query value, or None when absent or still the untouched template token."""
        v = self._query().get(key, [""])[0].strip()
        return None if not v or v.startswith("%") else v

    def _qint(self, key):
        try:
            return int(round(float(self._qstr(key))))    # rating arrives as "3.00"
        except (TypeError, ValueError):
            return None

    def _catalog_route(self, path):
        """Serve MyBuzz content/list/landing pages from the catalogue. Returns False for
        paths it does not own (the legacy handlers below then take over)."""
        cat = _catalog()
        low = path.lower()
        if "downloadfileservlet" in low or "ucqbatch" in low or "getrandomucq" in low:
            # With templates on, ucqDownloadURL substitutes the selected quiz's id into
            # fileID; otherwise (no usable id) fall back to UCQ_QID.
            qid = self._qint("fileID") or self._qint("quizid") or int(os.environ.get("UCQ_QID", "1"))
            quiz = cat.resolve(qid)
            content = cat.quiz_content(qid)
            if os.environ.get("UCQ_XMLDECL", "1") == "0":
                content = "\r\n".join(l for l in content.splitlines()
                                      if not l.lstrip().startswith("<?xml")) + "\r\n"
            cat.record_play(quiz["id"])
            log.info("[CATALOG] content: requested id %s -> quiz %d %r", qid, quiz["id"], quiz["name"])
            self._reply(content, "text/xml")
        elif low.endswith("landingpage.jsp"):
            self._reply(cat.landing_page())
        elif low.endswith("advertlist.jsp"):
            # <ADVERT type="MOVIE" size checksum srcLocation> makes the game download and
            # verify a video; serve none until we have a real movie to offer.
            self._reply(SVML_EMPTY)
        elif low.endswith("taglist.jsp") or low.endswith("tagquizlist.jsp"):
            tag = self._qstr("tag")
            self._reply(cat.quiz_list(cat.quizzes_with_tag(tag), tag) if tag else cat.tag_list())
        elif low.endswith("myplaylists.jsp") or low.endswith("myplaylistquizlist.jsp"):
            pid = self._qint("fileID") or self._qint("playlistid")
            self._reply(cat.quiz_list(cat.quizzes_in_playlist(pid), "Playlist") if pid
                        else cat.playlist_list())
        elif low.endswith("categoryparentlist.jsp"):
            self._reply(cat.category_list())
        elif low.endswith("categorylist.jsp") or low.endswith("categoryquizlist.jsp"):
            self._reply(cat.category_list(self._qstr("categoryId")))
        elif low.endswith("buddylist.jsp"):
            self._reply(cat.buddy_list())
        elif low.endswith("buddyquizlist.jsp"):
            owner = self._qint("fileOwnerID")
            buddy, qs = cat.buddy_quizzes(owner) if owner else (None, [])
            self._reply(cat.quiz_list(qs, buddy["name"] if buddy else "Friends"))
        elif low.endswith("leaderboards.jsp"):
            self._reply(cat.leaderboards())
        elif low.endswith("leaderboard.jsp"):
            board = self._qstr("board")
            base = f"http://{SVO_HOSTNAME}:{SVO_HTTP_PORT}/{SVO_ROOT}/mybuzz/leaderboard.jsp"
            self._reply(cat.leaderboard_single(board) if board else cat.leaderboard_menu(base))
        elif low.endswith("rating.jsp"):
            qid = self._qint("fileID")
            try:
                stars = float(self._qstr("fileRating"))      # half-stars, e.g. "3.50"
            except (TypeError, ValueError):
                stars = None
            if qid and stars is not None:
                quiz = cat.resolve(qid)
                correct = self._qstr("correctAnswers")
                correct = float(correct) if correct and correct.replace(".", "", 1).isdigit() else None
                cat.record_rating(quiz["id"], stars, correct)
                log.info("[CATALOG] rating: quiz %d %r -> %.2f stars, correctAnswers=%s",
                         quiz["id"], quiz["name"], stars, correct)
            self._reply(SVML_EMPTY)
        elif low.endswith("report.jsp"):
            log.warning("[CATALOG] quiz reported: fileID=%s type=%s",
                        self._qstr("fileID"), self._qstr("fileGriefReportType"))
            self._reply(SVML_EMPTY)
        elif any(k in low for k in ("myfavourites", "myquizzes", "gamelist", "quizlist",
                                    "ucqlist")):
            # pad=True keeps channel games at NUM_REQUIRED_FOR_UCQ_GAME (16) entries.
            self._reply(cat.quiz_list(cat.quizzes, "My Favourites", pad=True),
                        os.environ.get("MYBUZZ_CT"))
        else:
            return False
        return True

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        path = self.path.split("?", 1)[0]
        self._log_request()
        log.info("[SVO]   POST body %d bytes: %s", length, body[:96].hex())

        if "FileUpload" in path or "SnapshotUpload" in path:
            # The game uploads files here, e.g. Telemetry<n>.xml (fileTypeID=10) after a quiz,
            # carrying the player's PSN ID and game data. Keep every upload for decoding.
            name = self._qstr("fileNameBeginsWith") or "upload"
            os.makedirs(os.path.join("server_data", "uploads"), exist_ok=True)
            fn = os.path.join("server_data", "uploads", "%d_%s" % (int(time.time()), re.sub(r"[^A-Za-z0-9._-]", "_", name)))
            with open(fn, "wb") as f:
                f.write(body)
            log.info("[UPLOAD] %s (%d bytes) saved to %s", name, length, fn)
            self._reply(SVML_EMPTY)     # the game already accepts an empty 200 here
        elif "Buddy_SetList_Submit" in path or "/game/" in path:
            # Not yet seen from the game. Save the raw body so real RPCN friends (buddy list
            # upload) and score submissions (STC/OTE) can be decoded and wired in later.
            os.makedirs("server_data", exist_ok=True)
            fn = os.path.join("server_data", "captured_%s_%d.bin" % (path.strip("/").replace("/", "_"), int(time.time())))
            with open(fn, "wb") as f:
                f.write(body)
            log.warning("[CAPTURE] %s POST %d bytes saved to %s", path, length, fn)
            self._reply(SVML_EMPTY)
        elif "HomeUCQReportServlet" in path:
            self._reply('<XML><XMLSVOFILETRANSFER direction="upload" filename="ack" /></XML>', "text/xml")
        elif path.endswith("SP_Login_Submit.jsp"):
            # Shape from PSHome-MultiServer's SingStar handler (same middleware).
            xml = ('<?xml version="1.0" encoding="UTF-8"?>' + CRLF + '<XML>' + CRLF
                   + '    <SP_Login>' + CRLF + '        <status>' + CRLF
                   + '            <id>20600</id>' + CRLF
                   + '            <message>ACCT_LOGIN_SUCCESS</message>' + CRLF
                   + '        </status>' + CRLF + '        <accountID>1</accountID>' + CRLF
                   + '        <userContext>0</userContext>' + CRLF + '    </SP_Login>' + CRLF
                   + '</XML>')
            cookies = ["LangID=2", "AcctID=1", "NPCountry=gb", "ClanID=-1", "NPLang=1",
                       "ModerateMode=false", "TimeZone=GMT", "AcctName=buzzplayer", "OwnerID=-255"]
            self._reply(xml, "text/xml", [("Set-Cookie", c + "; Path=/") for c in cookies])
        else:
            self._reply(SVML_EMPTY)


def serve_svo_http(port: int):
    srv = http.server.ThreadingHTTPServer((HOST, port), SvoHandler)
    log.info("SVO HTTP listener on %s:%d", HOST, port)
    srv.serve_forever()


# =============================================================================
# Entry point
# =============================================================================

def serve_udp_probe(port: int):
    """Log any UDP datagram that arrives. The Medius DME layer (rt_udp) uses UDP,
    so the client's DME connect to <universe dns>:<port> lands here, not on the
    TCP serve_medius listener. Pure diagnostic for now."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind((HOST, port))
    except OSError as e:
        log.warning("UDP probe bind %d failed: %s", port, e)
        return
    log.info("UDP probe listening on %s:%d", HOST, port)
    while True:
        try:
            data, addr = s.recvfrom(4096)
        except OSError:
            continue
        log.info("[UDP %d] %d bytes from %s: %s", port, len(data), addr, data[:48].hex())


def main():
    udp_ports = [MEDIUS_DME_PORT, MEDIUS_LOGIN_PORT, 10076, 10077, 10078, 10070, 10073]
    threads = [
        threading.Thread(target=serve_medius, args=(MEDIUS_LOGIN_PORT, "LOGIN"), daemon=True),
        threading.Thread(target=serve_medius, args=(MEDIUS_DME_PORT, "DME"), daemon=True),
        threading.Thread(target=serve_svo_http, args=(SVO_HTTP_PORT,), daemon=True),
    ] + [threading.Thread(target=serve_udp_probe, args=(p,), daemon=True) for p in udp_ports]
    for t in threads:
        t.start()
    log.info("fake_buzz_server running. Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        log.info("shutting down")


if __name__ == "__main__":
    main()
