from __future__ import annotations

import argparse
import json
import sys
import threading
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from enum import Enum
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.broker.types import Order, OrderSide, OrderStatus, OrderType
from src.broker.wmca import WmcaBroker
from src.config import load_env, set_env_secret_loading_allowed
from src.config.settings import load_wmca_settings
from src.data.pykrx_provider import PykrxProvider
from src.data.top100 import load_top100
from src.data.usd_quote import LAOER_TICKER_POOL
from src.live.laoer_auto import LaoerAutoConfig, LaoerAutoRunner
from src.live.state import StateRepository


class BridgeError(Exception):
    def __init__(self, status: HTTPStatus, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


class BridgeState:
    def __init__(self, *, db_path: Path, dry_run_default: bool):
        self.lock = threading.RLock()
        self.db_path = db_path
        self.state = StateRepository(db_path)
        self.dry_run_default = dry_run_default
        self.broker: WmcaBroker | None = None
        self.history_provider = PykrxProvider(cache_ttl_seconds=60)

    def get_broker(self) -> WmcaBroker:
        if self.broker is None:
            settings = load_wmca_settings(include_secrets=True)
            self.broker = WmcaBroker(
                python_32bit=settings.python_32bit,
                worker_script=settings.worker_script,
                dll_path=settings.dll_path,
                media_type=settings.media_type,
                user_type=settings.user_type,
                cert_pos=settings.cert_pos,
                cert_password=settings.cert_password,
                account_password=settings.account_password,
                order_password=settings.order_password,
                account_index=settings.account_index,
            )
        return self.broker


def encode_json(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if is_dataclass(value):
        return {k: encode_json(v) for k, v in asdict(value).items()}
    if isinstance(value, dict):
        return {str(k): encode_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [encode_json(v) for v in value]
    return value


def position_to_dict(pos) -> dict[str, Any]:
    return {
        "ticker": pos.ticker,
        "name": pos.name,
        "quantity": pos.quantity,
        "avg_price": pos.avg_price,
        "current_price": pos.current_price,
        "market_value": pos.market_value,
        "unrealized_pnl": pos.unrealized_pnl,
        "unrealized_pnl_pct": pos.unrealized_pnl_pct,
    }


def order_to_dict(order: Order) -> dict[str, Any]:
    return {
        "ticker": order.ticker,
        "side": order.side.value,
        "quantity": order.quantity,
        "order_type": order.order_type.value,
        "limit_price": order.limit_price,
        "client_order_id": order.client_order_id,
        "broker_order_id": order.broker_order_id,
        "status": order.status.value,
        "filled_quantity": order.filled_quantity,
        "avg_fill_price": order.avg_fill_price,
        "submitted_at": order.submitted_at.isoformat() if order.submitted_at else None,
        "rejection_reason": order.rejection_reason,
    }


class BridgeHandler(BaseHTTPRequestHandler):
    server_version = "TradingMobileBridge/0.1"

    def _bridge(self) -> BridgeState:
        return self.server.bridge_state  # type: ignore[attr-defined]

    def _token(self) -> str:
        return self.server.bridge_token  # type: ignore[attr-defined]

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"{datetime.now().isoformat(timespec='seconds')} {self.address_string()} {fmt % args}")

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self._send_headers()
        self.end_headers()

    def do_GET(self) -> None:
        self._handle("GET")

    def do_POST(self) -> None:
        self._handle("POST")

    def _handle(self, method: str) -> None:
        try:
            self._authorize()
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            body = self._read_json_body() if method == "POST" else {}
            data = self._route(method, parsed.path, query, body)
            self._send_json(HTTPStatus.OK, {"ok": True, "data": data})
        except BridgeError as exc:
            self._send_json(exc.status, {"ok": False, "error": exc.message})
        except Exception as exc:
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"ok": False, "error": str(exc)},
            )

    def _authorize(self) -> None:
        token = self._token()
        if not token:
            return
        header = self.headers.get("Authorization", "")
        bearer = header.removeprefix("Bearer ").strip()
        api_token = self.headers.get("X-Bridge-Token", "").strip()
        if bearer == token or api_token == token:
            return
        raise BridgeError(HTTPStatus.UNAUTHORIZED, "invalid bridge token")

    def _read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise BridgeError(HTTPStatus.BAD_REQUEST, f"invalid JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise BridgeError(HTTPStatus.BAD_REQUEST, "JSON body must be an object")
        return data

    def _route(
        self,
        method: str,
        path: str,
        query: dict[str, list[str]],
        body: dict[str, Any],
    ) -> Any:
        bridge = self._bridge()
        if method == "GET" and path == "/api/health":
            broker = bridge.broker
            return {
                "connected": bool(broker and broker.is_connected),
                "db_path": str(bridge.db_path),
                "laoer_pool": LAOER_TICKER_POOL,
            }

        if method == "GET" and path == "/api/top100":
            limit = self._query_int(query, "limit", default=100, minimum=1, maximum=200)
            market = (self._query_optional(query, "market") or "ALL").upper()
            sort_by = self._query_optional(query, "sort") or "trading_value"
            return [
                item.to_dict()
                for item in load_top100(limit=limit, market=market, sort_by=sort_by)
            ]

        if method == "GET" and path == "/api/chart":
            ticker = self._query_one(query, "ticker").zfill(6)
            count = self._query_int(query, "count", default=120, minimum=20, maximum=300)
            frame = bridge.history_provider.get_ohlcv(ticker, count=count)
            return [
                {
                    "date": str(row.get("date") or ""),
                    "open": float(row.get("open") or 0),
                    "high": float(row.get("high") or 0),
                    "low": float(row.get("low") or 0),
                    "close": float(row.get("close") or 0),
                    "volume": int(row.get("volume") or 0),
                    "trading_value": float(row.get("trading_value") or 0),
                }
                for row in frame.to_dict("records")
            ]

        if method == "POST" and path == "/api/connect":
            with bridge.lock:
                broker = bridge.get_broker()
                if not broker.is_connected:
                    broker.connect()
                balance = broker.get_account_balance()
                positions = broker.get_positions()
            return {
                "balance": encode_json(balance),
                "positions": [position_to_dict(p) for p in positions],
            }

        if method == "GET" and path == "/api/account":
            broker = self._connected_broker(bridge)
            with bridge.lock:
                balance = broker.get_account_balance()
            return encode_json(balance)

        if method == "GET" and path == "/api/positions":
            broker = self._connected_broker(bridge)
            with bridge.lock:
                positions = broker.get_positions()
            return [position_to_dict(p) for p in positions]

        if method == "GET" and path == "/api/quote":
            broker = self._connected_broker(bridge)
            ticker = self._query_one(query, "ticker").zfill(6)
            with bridge.lock:
                quote = broker.get_quote(ticker)
            return encode_json(quote)

        if method == "GET" and path == "/api/sellable":
            broker = self._connected_broker(bridge)
            ticker = self._query_one(query, "ticker").zfill(6)
            with bridge.lock:
                single = getattr(broker, "get_individual_sellable_quantity", None)
                p8104 = single(ticker) if callable(single) else None
                p8101 = broker.get_sellable_quantity(ticker)
            return {"ticker": ticker, "p8104": p8104, "p8101": p8101, "max": max(p8104 or 0, p8101)}

        if method == "POST" and path == "/api/order":
            return self._place_order(bridge, body)

        if method == "POST" and path == "/api/laoer/tick":
            return self._laoer_tick(bridge, body)

        raise BridgeError(HTTPStatus.NOT_FOUND, f"unknown route: {method} {path}")

    def _place_order(self, bridge: BridgeState, body: dict[str, Any]) -> dict[str, Any]:
        broker = self._connected_broker(bridge)
        ticker = str(body.get("ticker") or "").strip().zfill(6)
        side_raw = str(body.get("side") or "").strip().upper()
        quantity = int(body.get("quantity") or 0)
        limit_price = float(body.get("limit_price") or body.get("price") or 0)
        dry_run = bool(body.get("dry_run", bridge.dry_run_default))
        if not ticker or quantity <= 0 or limit_price <= 0:
            raise BridgeError(HTTPStatus.BAD_REQUEST, "ticker, quantity, and limit_price are required")
        if side_raw not in {"BUY", "SELL"}:
            raise BridgeError(HTTPStatus.BAD_REQUEST, "side must be BUY or SELL")

        order = Order(
            ticker=ticker,
            side=OrderSide(side_raw),
            quantity=quantity,
            order_type=OrderType.LIMIT,
            limit_price=limit_price,
        )
        with bridge.lock:
            if dry_run:
                order.status = OrderStatus.REJECTED
                order.rejection_reason = "dry-run ON: mobile order not sent"
            else:
                order = broker.place_order(order)
        return order_to_dict(order)

    def _laoer_tick(self, bridge: BridgeState, body: dict[str, Any]) -> dict[str, Any]:
        broker = self._connected_broker(bridge)
        tickers = body.get("tickers") or []
        if isinstance(tickers, str):
            tickers = [t.strip() for t in tickers.split(",") if t.strip()]
        if not isinstance(tickers, list):
            raise BridgeError(HTTPStatus.BAD_REQUEST, "tickers must be a list or comma string")
        dry_run = bool(body.get("dry_run", bridge.dry_run_default))
        config = LaoerAutoConfig(
            tickers=[str(t).strip().upper() for t in tickers if str(t).strip()],
            splits=int(body.get("splits") or 40),
            target_profit_pct=float(body.get("target_profit_pct") or 0.10),
            seed_per_ticker_krw=(
                float(body["seed_per_ticker_krw"])
                if body.get("seed_per_ticker_krw") not in {None, ""}
                else None
            ),
        )
        with bridge.lock:
            runner = LaoerAutoRunner(broker, bridge.state, dry_run=dry_run)
            report = runner.tick(config)
        return encode_json(report)

    @staticmethod
    def _connected_broker(bridge: BridgeState) -> WmcaBroker:
        broker = bridge.get_broker()
        if not broker.is_connected:
            raise BridgeError(HTTPStatus.CONFLICT, "broker is not connected; call POST /api/connect first")
        return broker

    @staticmethod
    def _query_one(query: dict[str, list[str]], key: str) -> str:
        values = query.get(key) or []
        value = values[0].strip() if values else ""
        if not value:
            raise BridgeError(HTTPStatus.BAD_REQUEST, f"missing query parameter: {key}")
        return value

    @staticmethod
    def _query_optional(query: dict[str, list[str]], key: str) -> str | None:
        values = query.get(key) or []
        value = values[0].strip() if values else ""
        return value or None

    @staticmethod
    def _query_int(
        query: dict[str, list[str]],
        key: str,
        *,
        default: int,
        minimum: int,
        maximum: int,
    ) -> int:
        raw = BridgeHandler._query_optional(query, key)
        try:
            value = int(raw) if raw is not None else int(default)
        except ValueError:
            value = int(default)
        return min(max(value, minimum), maximum)

    def _send_headers(self) -> None:
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, X-Bridge-Token")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def _send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        raw = json.dumps(encode_json(payload), ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self._send_headers()
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="PC bridge API for the Android companion app.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--token", default="", help="Bearer token required by the Android app.")
    parser.add_argument("--db", type=Path, default=PROJECT_ROOT / "data" / "trading.db")
    parser.add_argument("--live-orders", action="store_true", help="Allow mobile manual orders to be sent by default.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    set_env_secret_loading_allowed(True)
    load_env(include_secrets=True)
    bridge = BridgeState(db_path=args.db, dry_run_default=not args.live_orders)
    httpd = ThreadingHTTPServer((args.host, args.port), BridgeHandler)
    httpd.bridge_state = bridge  # type: ignore[attr-defined]
    httpd.bridge_token = args.token  # type: ignore[attr-defined]
    print(f"Mobile bridge listening on http://{args.host}:{args.port}")
    if not args.token:
        print("WARNING: no token set. Use --token on a network you do not fully trust.")
    print(f"Default mobile order mode: {'LIVE' if args.live_orders else 'DRY-RUN'}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("Stopping mobile bridge...")
    finally:
        if bridge.broker is not None:
            try:
                bridge.broker.disconnect()
            except Exception:
                pass
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
