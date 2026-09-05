"""Add Relay's public attribution memo before the payment is submitted."""

import base64
import json

from xrpl.core.binarycodec import decode
from xrpl.models.transactions import Payment
from xrpl.transaction import sign

RELAY_COMMENT = "AlbertoRelay"


def add_relay_comment(payment_header, wallet):
    """Preserve the SDK's invoice binding and re-sign with our public memo.

    The SDK has no custom-memo option. Its original signed blob has not been
    submitted; only the resulting header is sent to the settlement service.
    Attribution relies on the signing account, not on the copyable memo text.
    """
    payload = json.loads(base64.b64decode(payment_header))
    tx = decode(payload["payload"]["signedTxBlob"])
    if tx.get("TransactionType") != "Payment" or tx.get("Account") != wallet.classic_address:
        raise ValueError("Expected a Payment from the configured Relay wallet")
    tx.pop("TxnSignature", None)
    tx.pop("SigningPubKey", None)
    tx.setdefault("Memos", []).append({"Memo": {
        "MemoType": "relay:comment".encode().hex().upper(),
        "MemoFormat": "text/plain".encode().hex().upper(),
        "MemoData": RELAY_COMMENT.encode().hex().upper(),
    }})
    signed = sign(Payment.from_xrpl(tx), wallet)
    payload["payload"]["signedTxBlob"] = signed.blob()
    return base64.b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode()
