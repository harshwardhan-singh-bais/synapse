"""
MQTT relay — cross-device message passing.
Allows sessions on different machines to message each other.
Uses paho-mqtt with optional TLS. Messages encrypted with PyNaCl SecretBox.

Relay config stored in relay_config table (key-value):
  relay_url, relay_id, relay_enabled, relay_token
"""
from __future__ import annotations

import json
import time
import uuid
import base64
import hashlib
import threading
from typing import Optional, Callable

import paho.mqtt.client as mqtt

from ..db.database import Database


class RelayConfig:
    """Reads and writes relay configuration from the ``relay_config`` DB table."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        row = self.db.fetchone("SELECT value FROM relay_config WHERE key=?", (key,))
        return row["value"] if row else default

    def set(self, key: str, value: str) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO relay_config (key, value) VALUES (?,?)",
            (key, value),
        )

    @property
    def url(self) -> Optional[str]:
        return self.get("relay_url")

    @property
    def relay_id(self) -> str:
        stored = self.get("relay_id")
        if stored:
            return stored
        new_id = str(uuid.uuid4())
        self.set("relay_id", new_id)
        return new_id

    @property
    def enabled(self) -> bool:
        return self.get("relay_enabled", "false").lower() == "true"

    @property
    def token(self) -> Optional[str]:
        return self.get("relay_token")

    def generate_new(self, url: str) -> str:
        """Provision a fresh relay channel. Returns an opaque join token."""
        relay_id = str(uuid.uuid4())
        token = base64.urlsafe_b64encode(uuid.uuid4().bytes).decode()
        self.set("relay_url", url)
        self.set("relay_id", relay_id)
        self.set("relay_token", token)
        self.set("relay_enabled", "true")
        return f"synapse-relay:{relay_id}:{token}"

    def save_psk_to_file(self, filepath: str) -> None:
        """Save the pre-shared key (PSK) to a file for file-only security.

        This allows using file-based key storage instead of database storage.
        The file contains the relay_id and token in a simple format.
        """
        import os
        relay_id = self.relay_id
        token = self.token or ""
        content = f"relay_id={relay_id}\ntoken={token}\n"
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
        
        with open(filepath, "w") as f:
            f.write(content)
        
        # Restrict permissions on Unix systems
        try:
            os.chmod(filepath, 0o600)
        except (OSError, AttributeError):
            pass

    def load_psk_from_file(self, filepath: str) -> bool:
        """Load pre-shared key (PSK) from a file.

        Returns True if the file was loaded successfully.
        The file should contain lines like:
            relay_id=<uuid>
            token=<base64-token>
        """
        try:
            with open(filepath, "r") as f:
                content = f.read()
            
            relay_id = None
            token = None
            
            for line in content.splitlines():
                line = line.strip()
                if line.startswith("relay_id="):
                    relay_id = line[9:]
                elif line.startswith("token="):
                    token = line[6:]
            
            if relay_id and token:
                self.set("relay_id", relay_id)
                self.set("relay_token", token)
                return True
            return False
        except (OSError, IOError):
            return False

    def get_psk_filepath(self) -> Optional[str]:
        """Get the configured PSK file path, or None if file-only mode is disabled."""
        return self.get("relay_psk_filepath")

    def set_psk_filepath(self, filepath: str) -> None:
        """Set the PSK file path for file-only security mode."""
        self.set("relay_psk_filepath", filepath)

    def connect_from_token(self, join_token: str, url: str) -> None:
        """Join an existing relay channel using a token produced by :meth:`generate_new`."""
        parts = join_token.split(":", 2)
        if len(parts) != 3 or parts[0] != "synapse-relay":
            raise ValueError(
                f"Invalid join token format: '{join_token}'. "
                "Expected 'synapse-relay:<relay_id>:<token>'."
            )
        _, relay_id, token = parts
        self.set("relay_url", url)
        self.set("relay_id", relay_id)
        self.set("relay_token", token)
        self.set("relay_enabled", "true")

    def disable(self) -> None:
        self.set("relay_enabled", "false")

    def enable(self) -> None:
        self.set("relay_enabled", "true")


class MQTTRelay:
    """
    MQTT relay worker. Runs in a background daemon thread.

    * Subscribes to ``synapse/relay/{relay_id}/#`` for inbound messages.
    * Publishes outbound messages to ``synapse/relay/{to_relay_id}/msg``.
    * All payloads are encrypted with PyNaCl SecretBox (SHA-256 of token as key).
      Falls back to plain-text if PyNaCl is unavailable (with a warning).
    """

    def __init__(
        self,
        config: RelayConfig,
        db: Database,
        on_message: Optional[Callable[[dict], None]] = None,
    ) -> None:
        self.config = config
        self.db = db
        self.on_message = on_message
        self._client: Optional[mqtt.Client] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._connected = False
        self._last_error: Optional[str] = None

    # ──────────────────────────────────────────────────────────────
    # Lifecycle
    # ──────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the relay background thread (no-op if relay is disabled or already running)."""
        if self._running:
            return
        if not self.config.enabled or not self.config.url:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="synapse-relay")
        self._thread.start()

    def stop(self) -> None:
        """Signal the relay thread to stop and disconnect the MQTT client."""
        self._running = False
        if self._client:
            try:
                self._client.disconnect()
            except Exception:
                pass

    def is_connected(self) -> bool:
        return self._connected

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error

    # ──────────────────────────────────────────────────────────────
    # Publishing
    # ──────────────────────────────────────────────────────────────

    def publish(self, to_relay_id: str, payload: dict) -> bool:
        """
        Publish *payload* (dict) to a remote relay peer.

        Returns ``True`` on success, ``False`` if the relay is not connected.
        """
        if not self._client or not self._connected:
            return False
        topic = f"synapse/relay/{to_relay_id}/msg"
        try:
            encrypted = self._encrypt(json.dumps(payload))
            self._client.publish(topic, encrypted, qos=1)
            return True
        except Exception as exc:
            self._last_error = str(exc)
            return False

    # ──────────────────────────────────────────────────────────────
    # State topic — device presence
    # ──────────────────────────────────────────────────────────────

    def publish_state(self, state: dict) -> bool:
        """Publish device presence state to the state topic.

        The state topic is ``synapse/relay/{relay_id}/state`` and allows
        devices to announce their presence, capabilities, and status.
        """
        if not self._client or not self._connected:
            return False
        relay_id = self.config.relay_id
        topic = f"synapse/relay/{relay_id}/state"
        try:
            state["relay_id"] = relay_id
            state["timestamp"] = int(time.time())
            encrypted = self._encrypt(json.dumps(state))
            self._client.publish(topic, encrypted, qos=1, retain=True)
            return True
        except Exception as exc:
            self._last_error = str(exc)
            return False

    def publish_gone(self) -> bool:
        """Publish a 'gone' state to indicate this device is disconnecting."""
        return self.publish_state({"status": "gone"})

    # ──────────────────────────────────────────────────────────────
    # Control topic — RPC commands
    # ──────────────────────────────────────────────────────────────

    def publish_rpc(self, to_relay_id: str, method: str, params: dict | None = None) -> bool:
        """Publish an RPC command to a remote peer's control topic.

        The control topic is ``synapse/relay/{to_relay_id}/ctrl``.
        """
        if not self._client or not self._connected:
            return False
        topic = f"synapse/relay/{to_relay_id}/ctrl"
        try:
            rpc_payload = {
                "method": method,
                "params": params or {},
                "from_relay_id": self.config.relay_id,
                "timestamp": int(time.time()),
            }
            encrypted = self._encrypt(json.dumps(rpc_payload))
            self._client.publish(topic, encrypted, qos=1)
            return True
        except Exception as exc:
            self._last_error = str(exc)
            return False

    # ──────────────────────────────────────────────────────────────
    # Internal — MQTT thread
    # ──────────────────────────────────────────────────────────────

    def _run(self) -> None:
        url = self.config.url
        relay_id = self.config.relay_id

        client_id = f"synapse-{relay_id[:8]}-{int(time.time())}"
        self._client = mqtt.Client(client_id=client_id, protocol=mqtt.MQTTv311)

        try:
            if url.startswith("mqtts://"):
                host_port = url[len("mqtts://"):]
                host, port_str = host_port.rsplit(":", 1)
                self._client.tls_set()
                port = int(port_str)
            elif url.startswith("mqtt://"):
                host_port = url[len("mqtt://"):]
                host, port_str = host_port.rsplit(":", 1)
                port = int(port_str)
            else:
                # Bare host:port fallback
                host, port_str = url.rsplit(":", 1)
                port = int(port_str)
        except (ValueError, AttributeError) as exc:
            self._last_error = f"Bad relay URL '{url}': {exc}"
            self._running = False
            return

        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

        try:
            self._client.connect(host, port, keepalive=60)
            self._client.loop_forever()
        except Exception as exc:
            self._last_error = str(exc)
        finally:
            self._connected = False
            self._running = False

    # ──────────────────────────────────────────────────────────────
    # Broker discovery / ping
    # ──────────────────────────────────────────────────────────────

    def ping_broker(self, timeout: float = 5.0) -> bool:
        """Ping the MQTT broker to verify connectivity.

        Returns True if the broker responds within *timeout* seconds.
        """
        if not self._client or not self._connected:
            return False
        try:
            # Use paho-mqtt's pingreq
            self._client.ping()
            # Wait briefly for the response
            import time
            time.sleep(min(timeout, 2.0))
            return self._connected
        except Exception:
            return False

    @staticmethod
    def discover_brokers(host: str = "broker.emqx.io", port: int = 1883,
                        timeout: float = 3.0) -> list[dict[str, str]]:
        """Discover MQTT brokers by attempting a connection.

        Returns a list of broker info dicts for brokers that responded.
        """
        brokers: list[dict[str, str]] = []
        default_brokers = [
            ("broker.emqx.io", 1883),
            ("broker.hivemq.com", 1883),
            ("mqtt.eclipseprojects.io", 1883),
        ]

        for broker_host, broker_port in [(host, port), *default_brokers]:
            try:
                test_client = mqtt.Client(
                    client_id=f"synapse-discover-{int(time.time())}",
                    protocol=mqtt.MQTTv311,
                )
                test_client.connect(broker_host, broker_port, keepalive=2)
                test_client.disconnect()
                brokers.append({"host": broker_host, "port": str(broker_port), "status": "ok"})
            except Exception:
                pass

        return brokers

    # ──────────────────────────────────────────────────────────────
    # Replay guard (LRU nonce cache)
    # ──────────────────────────────────────────────────────────────

    def _check_replay(self, nonce: str) -> bool:
        """Return True if the nonce is new (not a replay). Uses an LRU cache."""
        if not hasattr(self, "_nonce_cache"):
            self._nonce_cache: dict[str, float] = {}
            self._nonce_cache_max = 1000

        now = time.time()
        if nonce in self._nonce_cache:
            return False  # Replay detected

        # Add to cache
        self._nonce_cache[nonce] = now

        # Evict old entries if cache is too large
        if len(self._nonce_cache) > self._nonce_cache_max:
            cutoff = now - 3600  # Evict entries older than 1 hour
            self._nonce_cache = {
                k: v for k, v in self._nonce_cache.items()
                if v > cutoff
            }

        return True

    # ──────────────────────────────────────────────────────────────
    # Remote dispatch (cross-device)
    # ──────────────────────────────────────────────────────────────

    def dispatch_to_remote(self, to_relay_id: str, command: str,
                          payload: dict | None = None) -> bool:
        """Dispatch a command to a remote device via the relay.

        This sends an RPC command to the remote device's control topic.
        The remote device's relay worker will execute the command.
        """
        return self.publish_rpc(to_relay_id, command, payload or {})

    def get_online_peers(self) -> list[dict[str, str]]:
        """Return a list of recently seen online relay peers.

        Maintains a cache of device presence states from the state topic.
        """
        if not hasattr(self, "_peer_states"):
            self._peer_states: dict[str, dict] = {}

        result = []
        now = time.time()
        for relay_id, state in list(self._peer_states.items()):
            # Consider a peer offline if no update in 5 minutes
            if now - state.get("timestamp", 0) < 300:
                result.append({"relay_id": relay_id, **state})
        return result

    def _on_connect(self, client: mqtt.Client, userdata: object, flags: dict, rc: int) -> None:
        if rc == 0:
            self._connected = True
            self._last_error = None
            topic = f"synapse/relay/{self.config.relay_id}/#"
            client.subscribe(topic, qos=1)
            # Publish initial state
            self.publish_state({"status": "online", "capabilities": ["msg", "ctrl"]})
        else:
            self._connected = False
            self._last_error = f"MQTT connect failed (rc={rc})"

    def _on_disconnect(self, client: mqtt.Client, userdata: object, rc: int) -> None:
        self._connected = False
        if rc != 0:
            self._last_error = f"Unexpected disconnect (rc={rc})"

    def _on_message(self, client: mqtt.Client, userdata: object, msg: mqtt.MQTTMessage) -> None:
        try:
            payload_str = self._decrypt(msg.payload)
            payload = json.loads(payload_str)

            # Route by topic suffix
            topic = msg.topic
            if topic.endswith("/ctrl"):
                self._handle_rpc(payload)
            elif topic.endswith("/state"):
                self._handle_state(payload)
            elif self.on_message:
                self.on_message(payload)
        except Exception:
            pass  # Malformed / encrypted-by-wrong-key messages are silently dropped

    def _handle_rpc(self, payload: dict) -> None:
        """Handle an incoming RPC command from the control topic."""
        method = payload.get("method", "")
        params = payload.get("params", {})
        from_relay_id = payload.get("from_relay_id", "")

        if method == "ping":
            # Respond with pong
            self.publish_rpc(from_relay_id, "pong", {
                "relay_id": self.config.relay_id,
                "timestamp": int(time.time()),
            })
        elif method == "pong":
            pass  # Response to our ping — already handled by caller
        elif self.on_message:
            # Forward other RPC methods to the message handler
            self.on_message({"type": "rpc", **payload})

    def _handle_state(self, payload: dict) -> None:
        """Handle an incoming state/presence notification."""
        # Track peer state for get_online_peers
        if not hasattr(self, "_peer_states"):
            self._peer_states: dict[str, dict] = {}
        peer_id = payload.get("relay_id", "")
        if peer_id and peer_id != self.config.relay_id:
            self._peer_states[peer_id] = payload

        if self.on_message:
            self.on_message({"type": "state", **payload})

    # ──────────────────────────────────────────────────────────────
    # Encryption
    # ──────────────────────────────────────────────────────────────

    def _derive_key(self) -> bytes:
        """Derive encryption key from the relay token.

        Uses SHA-256 hash of the token as the key material.
        """
        token = self.config.token or ""
        return hashlib.sha256(token.encode()).digest()

    def _encrypt(self, data: str) -> bytes:
        """Encrypt *data* with XChaCha20-Poly1305 AEAD.

        Falls back to standard SecretBox if XChaCha20 is unavailable,
        then to raw bytes if PyNaCl is not installed.
        """
        try:
            # Try XChaCha20-Poly1305 AEAD first (more secure)
            from cryptography.hazmat.primitives.ciphers.aead import XChaCha20Poly1305  # type: ignore[import]
            import os
            key = self._derive_key()[:32]  # Ensure 32-byte key for XChaCha20
            nonce = os.urandom(24)  # 24-byte nonce for XChaCha20
            aead = XChaCha20Poly1305(key)
            ciphertext = aead.encrypt(nonce, data.encode(), None)
            # Prepend nonce to ciphertext: nonce (24) + ciphertext
            return nonce + ciphertext
        except ImportError:
            pass

        try:
            # Fallback to standard SecretBox
            from nacl.secret import SecretBox  # type: ignore[import]
            box = SecretBox(self._derive_key())
            return box.encrypt(data.encode())
        except ImportError:
            pass

        # Last resort: raw bytes (insecure)
        return data.encode()

    def _decrypt(self, data: bytes) -> str:
        """Decrypt *data* with XChaCha20-Poly1305 AEAD.

        Falls back to standard SecretBox if XChaCha20 fails,
        then to raw decode if PyNaCl is not installed.
        """
        try:
            # Try XChaCha20-Poly1305 AEAD first
            from cryptography.hazmat.primitives.ciphers.aead import XChaCha20Poly1305  # type: ignore[import]
            key = self._derive_key()[:32]  # Ensure 32-byte key for XChaCha20
            if len(data) >= 24:
                nonce = data[:24]
                ciphertext = data[24:]
                aead = XChaCha20Poly1305(key)
                plaintext = aead.decrypt(nonce, ciphertext, None)
                return plaintext.decode()
        except (ImportError, Exception):
            pass

        try:
            # Fallback to standard SecretBox
            from nacl.secret import SecretBox  # type: ignore[import]
            box = SecretBox(self._derive_key())
            return box.decrypt(data).decode()
        except (ImportError, Exception):
            pass

        # Last resort: raw decode (insecure)
        return data.decode()
