from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Callable, Literal, Mapping, Protocol, TypedDict
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from popbill import PopbillException

from app.config import Settings

_MANAGEMENT_KEY = re.compile(r"^[A-Za-z0-9_-]{1,24}$")
_CORP_NUMBER = re.compile(r"^(?:\d{10}|\d{3}-\d{2}-\d{5})$")
_TAX_TYPES = {"taxable": "과세", "tax_free": "면세"}
_ISSUED_STATE_CODES = set(range(300, 306))
_NTS_ACCEPTED_STATE_CODE = 304
_TEXT_LIMITS = {
    "name": 200,
    "representative": 100,
    "address": 300,
    "business_type": 100,
    "business_item": 100,
    "contact_name": 100,
    "tax_email": 100,
    "contact_phone": 20,
}


class PartySnapshotInput(TypedDict):
    registration_number: str
    name: str
    representative: str
    address: str
    business_type: str
    business_item: str
    tax_email: str
    contact_phone: str


class RecipientSnapshotInput(PartySnapshotInput):
    contact_name: str


class PersistedInvoiceInput(TypedDict):
    """Typed boundary for the persisted invoice row accepted by the SDK layer.

    Routers/repositories can pass their ordinary dictionaries directly; runtime validation below
    still fails closed when a database row is incomplete or malformed.
    """

    invoicer_mgt_key: str
    tax_type: Literal["taxable", "tax_free"]
    write_date: date | datetime | str
    supply_amount: int | str
    vat_amount: int | str
    total_amount: int | str
    supplier_snapshot: PartySnapshotInput
    recipient_snapshot: RecipientSnapshotInput


class TaxinvoiceSDK(Protocol):
    IsTest: bool
    IPRestrictOnOff: bool
    UseStaticIP: bool
    UseLocalTimeYN: bool

    def registIssue(
        self,
        CorpNum: str,
        taxinvoice: dict[str, Any],
        writeSpecification: bool = False,
        forceIssue: bool = False,
        dealInvoiceMgtKey: str | None = None,
        memo: str | None = None,
        emailSubject: str | None = None,
        UserID: str | None = None,
    ) -> Any: ...

    def getInfo(self, CorpNum: str, MgtKeyType: str, MgtKey: str) -> Any: ...

    def getViewURL(
        self, CorpNum: str, MgtKeyType: str, MgtKey: str, UserID: str | None = None
    ) -> str: ...

    def getPDFURL(
        self, CorpNum: str, MgtKeyType: str, MgtKey: str, UserID: str | None = None
    ) -> str: ...

    def checkMgtKeyInUse(self, CorpNum: str, MgtKeyType: str, MgtKey: str) -> bool: ...

    def checkCertValidation(self, CorpNum: str, UserID: str | None = None) -> Any: ...

    def getCertificateExpireDate(self, CorpNum: str) -> datetime: ...


SDKFactory = Callable[[str, str], TaxinvoiceSDK]


@dataclass(frozen=True)
class PopbillConfig:
    link_id: str = field(repr=False)
    secret_key: str = field(repr=False)
    corp_num: str = field(repr=False)
    user_id: str = field(repr=False)
    is_test: bool = True
    ip_restrict_on: bool = True
    use_static_ip: bool = False
    use_local_time: bool = True

    @classmethod
    def from_settings(cls, settings: Settings) -> "PopbillConfig":
        return cls(
            link_id=settings.popbill_link_id,
            secret_key=settings.popbill_secret_key,
            corp_num=settings.popbill_corp_num,
            user_id=settings.popbill_user_id,
            is_test=settings.popbill_is_test,
            ip_restrict_on=settings.popbill_ip_restrict_on,
            use_static_ip=settings.popbill_use_static_ip,
            use_local_time=settings.popbill_use_local_time,
        )


class PopbillError(Exception):
    """A caller-safe error. Raw provider messages and request data are never retained."""

    def __init__(self, code: str, message: str, *, provider_code: int | str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.provider_code = provider_code


@dataclass(frozen=True)
class PopbillIssueResult:
    management_key: str
    provider_code: int | str | None
    nts_accepted: bool
    reconciled: bool = False


@dataclass(frozen=True)
class PopbillStatus:
    management_key: str = field(repr=False)
    item_key: str | None = field(repr=False)
    provider_state_code: int | str | None = field(repr=False)
    provider_state_memo: str | None = field(repr=False)
    nts_accepted: bool
    nts_confirm_number: str | None = field(repr=False)
    issued_at: str | None
    nts_sent_at: str | None
    nts_result_at: str | None
    nts_result_code: str | None = field(default=None, repr=False)


@dataclass(frozen=True)
class PopbillCertificateReadiness:
    certificate_verified: bool
    certificate_expires_on: str


@dataclass(frozen=True)
class PopbillURLResult:
    management_key: str
    kind: Literal["view", "pdf"]
    url: str = field(repr=False)
    expires_in: int = 30

    def __post_init__(self) -> None:
        try:
            parts = urlsplit(self.url)
        except (TypeError, ValueError):
            raise PopbillError(
                "POPBILL_INVALID_PROVIDER_RESPONSE", "Popbill returned an invalid URL"
            ) from None
        if (
            self.expires_in != 30
            or parts.scheme != "https"
            or not parts.netloc
            or not parts.hostname
            or parts.username is not None
            or parts.password is not None
            or any(char.isspace() or unicodedata.category(char).startswith("C") for char in self.url)
        ):
            raise PopbillError("POPBILL_INVALID_PROVIDER_RESPONSE", "Popbill returned an invalid URL")


def _default_sdk_factory(link_id: str, secret_key: str) -> TaxinvoiceSDK:
    # Lazy construction keeps SDK behavior behind the service boundary.
    from popbill import TaxinvoiceService

    return TaxinvoiceService(link_id, secret_key)


def _corp_number(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _CORP_NUMBER.fullmatch(value):
        raise PopbillError("POPBILL_INVALID_INPUT", f"Invalid {field_name}")
    return value.replace("-", "")


def _party_text(snapshot: Mapping[str, Any], key: str) -> str:
    value = snapshot.get(key)
    if not isinstance(value, str):
        raise PopbillError("POPBILL_INVALID_INPUT", f"Invalid snapshot field: {key}")
    text = value.strip()
    if (
        not text
        or len(text) > _TEXT_LIMITS[key]
        or any(unicodedata.category(char).startswith("C") for char in text)
    ):
        raise PopbillError("POPBILL_INVALID_INPUT", f"Invalid snapshot field: {key}")
    return text


def _write_date(value: Any) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y%m%d")
    if isinstance(value, date):
        return value.strftime("%Y%m%d")
    if not isinstance(value, str):
        raise PopbillError("POPBILL_INVALID_INPUT", "Invalid write_date")
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(value, fmt).strftime("%Y%m%d")
        except ValueError:
            pass
    raise PopbillError("POPBILL_INVALID_INPUT", "Invalid write_date")


def _management_key(value: Any) -> str:
    if not isinstance(value, str) or not _MANAGEMENT_KEY.fullmatch(value):
        raise PopbillError("POPBILL_INVALID_INPUT", "Invalid invoicer_mgt_key")
    return value


def _amount(value: Any, field_name: str) -> int:
    if isinstance(value, bool):
        raise PopbillError("POPBILL_INVALID_INPUT", f"Invalid {field_name}")
    try:
        amount = int(value)
    except (TypeError, ValueError, OverflowError):
        raise PopbillError("POPBILL_INVALID_INPUT", f"Invalid {field_name}") from None
    if amount < 0 or str(value).strip() not in {str(amount), f"+{amount}"}:
        raise PopbillError("POPBILL_INVALID_INPUT", f"Invalid {field_name}")
    return amount


def _attr(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _state_code(value: Any) -> int | None:
    # Accept only the documented integer and the canonical JSON digit-string
    # shape seen in SDK responses. Never coerce floats or Decimal values.
    if type(value) is int:
        return value
    if type(value) is str and re.fullmatch(r"(?:0|[1-9]\d*)", value):
        return int(value)
    return None


def _nts_accepted(info: Any) -> bool:
    # Popbill documents SUC001 at state 304 as NTS acceptance.
    return _attr(info, "ntsresult") == "SUC001" and _state_code(_attr(info, "stateCode")) == _NTS_ACCEPTED_STATE_CODE


def _sanitized_provider_scalar(value: Any, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or len(value) > limit or any(
        unicodedata.category(char).startswith("C") for char in value
    ):
        return None
    return value


def _provider_timestamp(value: Any) -> str | None:
    """Convert Popbill compact Korean-local time to unambiguous ISO 8601."""
    if not isinstance(value, str) or not re.fullmatch(r"\d{14}", value):
        return None
    try:
        parsed = datetime.strptime(value, "%Y%m%d%H%M%S").replace(
            tzinfo=ZoneInfo("Asia/Seoul")
        )
    except ValueError:
        return None
    return parsed.isoformat()


class PopbillService:
    def __init__(self, config: PopbillConfig, *, sdk_factory: SDKFactory = _default_sdk_factory) -> None:
        self._config = config
        if not all(
            isinstance(value, str) and value.strip()
            for value in (config.link_id, config.secret_key, config.user_id)
        ):
            raise PopbillError("POPBILL_NOT_CONFIGURED", "Popbill is not configured")
        self._corp_num = _corp_number(config.corp_num, "configured corp_num")
        try:
            self._sdk = sdk_factory(config.link_id, config.secret_key)
            self._sdk.IsTest = config.is_test
            self._sdk.IPRestrictOnOff = config.ip_restrict_on
            self._sdk.UseStaticIP = config.use_static_ip
            self._sdk.UseLocalTimeYN = config.use_local_time
        except PopbillError:
            raise
        except Exception as exc:
            raise self._safe_error(exc) from None

    def issue(
        self,
        tax_invoice: PersistedInvoiceInput | Mapping[str, Any],
        *,
        allow_delayed_issue: bool = False,
    ) -> PopbillIssueResult:
        key, payload = self._build_taxinvoice(tax_invoice)
        # popbill 1.64.2 accepts mapping payloads, but its forceIssue=True branch
        # performs attribute assignment (taxinvoice.forceIssue = True), which
        # raises AttributeError for a dict. Set the documented wire field on our
        # fresh payload copy and keep the SDK mutator branch disabled.
        if allow_delayed_issue:
            payload["forceIssue"] = True
        try:
            # Exact popbill 1.64.2 positional contract: specification, force, deal key,
            # memo, subject, then user ID.
            response = self._sdk.registIssue(
                self._corp_num, payload, False, False,
                None, None, None, self._config.user_id,
            )
        except PopbillException as exc:
            # Only an explicit issue exception is an authoritative rejection.
            raise self._safe_error(exc, operation="issue") from None
        except (TimeoutError, ConnectionError, OSError):
            # These failures may happen after the provider accepted the request.
            if self._reconcile_issued_key(key):
                return PopbillIssueResult(key, None, nts_accepted=False, reconciled=True)
            raise PopbillError(
                "POPBILL_RECONCILIATION_REQUIRED",
                "Popbill issue outcome requires reconciliation by management key",
            ) from None
        except Exception as exc:
            raise self._safe_error(exc, operation="issue") from None
        return PopbillIssueResult(
            management_key=key,
            provider_code=_attr(response, "code"),
            # registIssue success means issued at Popbill, never accepted by NTS.
            nts_accepted=False,
        )

    def certificate_readiness(self) -> PopbillCertificateReadiness:
        """Verify the configured account and certificate without creating a document."""
        try:
            # CertCheck uses HTTP success as its authoritative signal; the SDK raises for
            # every provider rejection. No document is registered by either call.
            self._sdk.checkCertValidation(self._corp_num, self._config.user_id)
            expires_at = self._sdk.getCertificateExpireDate(self._corp_num)
        except Exception as exc:
            raise self._safe_error(exc, operation="certificate") from None
        if not isinstance(expires_at, datetime):
            raise PopbillError(
                "POPBILL_INVALID_PROVIDER_RESPONSE",
                "Popbill returned an invalid certificate expiration",
            )
        return PopbillCertificateReadiness(
            certificate_verified=True,
            certificate_expires_on=expires_at.date().isoformat(),
        )

    def get_status(self, management_key: str) -> PopbillStatus:
        key = _management_key(management_key)
        try:
            info = self._sdk.getInfo(self._corp_num, "SELL", key)
        except Exception as exc:
            raise self._safe_error(exc, operation="status") from None

        if _attr(info, "invoicerMgtKey") != key:
            raise PopbillError(
                "POPBILL_INVALID_PROVIDER_RESPONSE", "Popbill returned a different document"
            )
        state_code = _state_code(_attr(info, "stateCode"))
        if state_code not in _ISSUED_STATE_CODES:
            raise PopbillError(
                "POPBILL_INVALID_PROVIDER_RESPONSE", "Popbill returned an invalid lifecycle state"
            )

        raw_issued = _attr(info, "issueDT")
        raw_sent = _attr(info, "ntssendDT")
        raw_result = _attr(info, "ntsresultDT")
        issued_at = _provider_timestamp(raw_issued)
        sent_at = _provider_timestamp(raw_sent)
        result_at = _provider_timestamp(raw_result)
        if issued_at is None or (raw_sent is not None and sent_at is None) or (
            raw_result is not None and result_at is None
        ):
            raise PopbillError(
                "POPBILL_INVALID_PROVIDER_RESPONSE", "Popbill returned an invalid timestamp"
            )
        if (sent_at is not None and sent_at < issued_at) or (
            result_at is not None and (sent_at is None or result_at < sent_at)
        ):
            raise PopbillError(
                "POPBILL_INVALID_PROVIDER_RESPONSE", "Popbill returned impossible chronology"
            )

        nts_result = _sanitized_provider_scalar(_attr(info, "ntsresult"), 80)
        accepted = nts_result == "SUC001" and state_code == _NTS_ACCEPTED_STATE_CODE
        if accepted and (sent_at is None or result_at is None):
            raise PopbillError(
                "POPBILL_INVALID_PROVIDER_RESPONSE", "Popbill omitted NTS acceptance timestamps"
            )
        return PopbillStatus(
            management_key=key,
            item_key=_attr(info, "itemKey"),
            provider_state_code=state_code,
            provider_state_memo=_attr(info, "stateMemo"),
            nts_result_code=nts_result,
            nts_accepted=accepted,
            nts_confirm_number=_sanitized_provider_scalar(_attr(info, "ntsconfirmNum"), 100),
            issued_at=issued_at,
            nts_sent_at=sent_at,
            nts_result_at=result_at,
        )

    def management_key_in_use(self, management_key: str) -> bool:
        """Expose only checkMgtKeyInUse's exact authoritative boolean."""
        key = _management_key(management_key)
        try:
            result = self._sdk.checkMgtKeyInUse(self._corp_num, "SELL", key)
        except Exception as exc:
            raise self._safe_error(exc, operation="check_management_key") from None
        if type(result) is not bool:
            raise PopbillError(
                "POPBILL_INVALID_PROVIDER_RESPONSE", "Popbill returned an invalid key status"
            )
        return result

    def get_view_url(self, management_key: str) -> PopbillURLResult:
        key = _management_key(management_key)
        try:
            url = self._sdk.getViewURL(self._corp_num, "SELL", key, self._config.user_id)
        except Exception as exc:
            raise self._safe_error(exc, operation="view") from None
        return PopbillURLResult(key, "view", url if isinstance(url, str) else "")

    def get_pdf_url(self, management_key: str) -> PopbillURLResult:
        key = _management_key(management_key)
        try:
            url = self._sdk.getPDFURL(self._corp_num, "SELL", key, self._config.user_id)
        except Exception as exc:
            raise self._safe_error(exc, operation="pdf") from None
        return PopbillURLResult(key, "pdf", url if isinstance(url, str) else "")

    def _reconcile_issued_key(self, key: str) -> bool:
        try:
            if self._sdk.checkMgtKeyInUse(self._corp_num, "SELL", key) is not True:
                return False
            info = self._sdk.getInfo(self._corp_num, "SELL", key)
        except Exception:
            return False
        return (
            _attr(info, "invoicerMgtKey") == key
            and _state_code(_attr(info, "stateCode")) in _ISSUED_STATE_CODES
        )

    @staticmethod
    def _safe_error(exc: Exception, *, operation: str = "transport") -> PopbillError:
        provider_code = getattr(exc, "code", None)
        if provider_code is not None and operation == "issue":
            return PopbillError(
                "POPBILL_ISSUE_REJECTED", "Popbill rejected the request", provider_code=provider_code
            )
        if provider_code is not None and operation == "certificate":
            return PopbillError(
                "POPBILL_CERTIFICATE_NOT_READY",
                "Popbill certificate is not ready",
                provider_code=provider_code,
            )
        return PopbillError(
            "POPBILL_TEMPORARILY_UNAVAILABLE", "Unable to communicate with Popbill",
            provider_code=provider_code,
        )

    def _build_taxinvoice(
        self, row: PersistedInvoiceInput | Mapping[str, Any]
    ) -> tuple[str, dict[str, Any]]:
        if not isinstance(row, Mapping):
            raise PopbillError("POPBILL_INVALID_INPUT", "Invalid persisted invoice")
        required = {
            "invoicer_mgt_key", "tax_type", "write_date", "supply_amount", "vat_amount",
            "total_amount", "supplier_snapshot", "recipient_snapshot",
        }
        if not required.issubset(row):
            raise PopbillError("POPBILL_INVALID_INPUT", "Incomplete persisted invoice")

        key = _management_key(row["invoicer_mgt_key"])
        tax_type = _TAX_TYPES.get(row["tax_type"] if isinstance(row["tax_type"], str) else "")
        if tax_type is None:
            raise PopbillError("POPBILL_INVALID_INPUT", "Invalid tax_type")
        write_date = _write_date(row["write_date"])
        supply = _amount(row["supply_amount"], "supply_amount")
        vat = _amount(row["vat_amount"], "vat_amount")
        total = _amount(row["total_amount"], "total_amount")
        if supply + vat != total or (tax_type == "면세" and vat != 0):
            raise PopbillError("POPBILL_INVALID_INPUT", "Invalid invoice totals")

        supplier = row["supplier_snapshot"]
        recipient = row["recipient_snapshot"]
        if not isinstance(supplier, Mapping) or not isinstance(recipient, Mapping):
            raise PopbillError("POPBILL_INVALID_INPUT", "Missing party snapshot")
        supplier_corp = _corp_number(supplier.get("registration_number"), "supplier registration_number")
        recipient_corp = _corp_number(recipient.get("registration_number"), "recipient registration_number")
        if supplier_corp != self._corp_num:
            raise PopbillError("POPBILL_INVALID_INPUT", "Supplier does not match configured corporation")

        payload: dict[str, Any] = {
            "invoicerMgtKey": key,
            "writeDate": write_date,
            "chargeDirection": "정과금",
            "issueType": "정발행",
            "purposeType": "청구",
            "taxType": tax_type,
            "supplyCostTotal": str(supply),
            "taxTotal": str(vat),
            "totalAmount": str(total),
            "invoicerCorpNum": supplier_corp,
            "invoicerCorpName": _party_text(supplier, "name"),
            "invoicerCEOName": _party_text(supplier, "representative"),
            "invoicerAddr": _party_text(supplier, "address"),
            "invoicerBizType": _party_text(supplier, "business_type"),
            "invoicerBizClass": _party_text(supplier, "business_item"),
            "invoicerEmail": _party_text(supplier, "tax_email"),
            "invoicerTEL": _party_text(supplier, "contact_phone"),
            "invoiceeType": "사업자",
            "invoiceeCorpNum": recipient_corp,
            "invoiceeCorpName": _party_text(recipient, "name"),
            "invoiceeCEOName": _party_text(recipient, "representative"),
            "invoiceeAddr": _party_text(recipient, "address"),
            "invoiceeBizType": _party_text(recipient, "business_type"),
            "invoiceeBizClass": _party_text(recipient, "business_item"),
            "invoiceeContactName1": _party_text(recipient, "contact_name"),
            "invoiceeTEL1": _party_text(recipient, "contact_phone"),
            "invoiceeEmail1": _party_text(recipient, "tax_email"),
            "detailList": [{
                "serialNum": 1,
                "purchaseDT": write_date,
                "itemName": "정산",
                "qty": "1",
                "unitCost": str(supply),
                "supplyCost": str(supply),
                "tax": str(vat),
            }],
        }
        return key, payload
