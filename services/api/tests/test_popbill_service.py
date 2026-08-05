from __future__ import annotations

import inspect
from decimal import Decimal
from copy import deepcopy
from datetime import date, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from popbill import PopbillException, TaxinvoiceService

from app.config import Settings, parse_env_bool
from app.services.popbill_service import (
    PopbillCertificateReadiness,
    PopbillConfig,
    PopbillError,
    PopbillIssueResult,
    PopbillService,
    PopbillStatus,
    PopbillURLResult,
)


class FakeTaxinvoiceSDK:
    """Fake whose signatures intentionally mirror popbill 1.64.2."""

    IsTest: bool
    IPRestrictOnOff: bool
    UseStaticIP: bool
    UseLocalTimeYN: bool

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.issue_response = SimpleNamespace(code=1, message="accepted", ntsConfirmNum=None)
        self.info = SimpleNamespace(
            invoicerMgtKey="GE_invoice-1",
            itemKey="provider-item-key-123",
            stateCode=300,
            stateMemo="발행완료",
            ntsresult=None,
            ntsconfirmNum=None,
            issueDT="20260727112233",
            ntssendDT=None,
            ntsresultDT=None,
        )
        self.raise_on: dict[str, Exception] = {}
        self.key_in_use = True
        self.view_url: Any = "https://provider.example/view/short-lived"
        self.pdf_url: Any = "https://provider.example/pdf/short-lived"
        self.certificate_expiration: Any = datetime(2027, 7, 27, 23, 59, 59)

    def _record(self, name: str, *args: Any, **kwargs: Any) -> None:
        self.calls.append((name, args, kwargs))
        if name in self.raise_on:
            raise self.raise_on[name]

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
    ) -> Any:
        self._record(
            "registIssue", CorpNum, taxinvoice, writeSpecification, forceIssue,
            dealInvoiceMgtKey, memo, emailSubject, UserID,
        )
        return self.issue_response

    def getInfo(self, CorpNum: str, MgtKeyType: str, MgtKey: str) -> Any:
        self._record("getInfo", CorpNum, MgtKeyType, MgtKey)
        return self.info

    def getViewURL(
        self, CorpNum: str, MgtKeyType: str, MgtKey: str, UserID: str | None = None
    ) -> Any:
        self._record("getViewURL", CorpNum, MgtKeyType, MgtKey, UserID)
        return self.view_url

    def getPDFURL(
        self, CorpNum: str, MgtKeyType: str, MgtKey: str, UserID: str | None = None
    ) -> Any:
        self._record("getPDFURL", CorpNum, MgtKeyType, MgtKey, UserID)
        return self.pdf_url

    def checkMgtKeyInUse(self, CorpNum: str, MgtKeyType: str, MgtKey: str) -> bool:
        self._record("checkMgtKeyInUse", CorpNum, MgtKeyType, MgtKey)
        return self.key_in_use

    def checkCertValidation(self, CorpNum: str, UserID: str | None = None) -> Any:
        self._record("checkCertValidation", CorpNum, UserID)
        return SimpleNamespace(code=1)

    def getCertificateExpireDate(self, CorpNum: str) -> datetime:
        self._record("getCertificateExpireDate", CorpNum)
        return self.certificate_expiration


@pytest.fixture
def config() -> PopbillConfig:
    return PopbillConfig(
        link_id="LINK-ID",
        secret_key="super-secret-value",
        corp_num="123-45-67890",
        user_id="api-user",
        is_test=True,
        ip_restrict_on=True,
        use_static_ip=False,
        use_local_time=True,
    )


@pytest.fixture
def invoice() -> dict[str, Any]:
    return {
        "invoicer_mgt_key": "GE_invoice-1",
        "tax_type": "taxable",
        "write_date": date(2026, 7, 27),
        "supply_amount": 10000,
        "vat_amount": 1000,
        "total_amount": 11000,
        "supplier_snapshot": {
            "registration_number": "123-45-67890",
            "name": "공급자 상호",
            "representative": "공급자 대표",
            "address": "서울 공급자 주소",
            "business_type": "음식점업",
            "business_item": "한식",
            "tax_email": "supplier@example.test",
            "contact_phone": "02-123-4567",
        },
        "recipient_snapshot": {
            "registration_number": "987-65-43210",
            "name": "공급받는자 상호",
            "representative": "수취인 대표",
            "address": "서울 수취인 주소",
            "business_type": "서비스업",
            "business_item": "소프트웨어",
            "tax_email": "recipient@example.test",
            "contact_name": "담당자",
            "contact_phone": "010-1234-5678",
        },
    }


def make_service(config: PopbillConfig, sdk: FakeTaxinvoiceSDK) -> PopbillService:
    def factory(link_id: str, secret_key: str) -> FakeTaxinvoiceSDK:
        assert (link_id, secret_key) == ("LINK-ID", "super-secret-value")
        return sdk

    return PopbillService(config, sdk_factory=factory)


def test_strict_env_bool_accepts_only_exact_lowercase(monkeypatch: pytest.MonkeyPatch) -> None:
    for raw, expected in (("true", True), ("false", False)):
        monkeypatch.setenv("STRICT_BOOL", raw)
        assert parse_env_bool("STRICT_BOOL", not expected) is expected

    for malformed in (" TrUe ", "True", "FALSE", " false", "false\n", "1", "yes", ""):
        monkeypatch.setenv("STRICT_BOOL", malformed)
        with pytest.raises(RuntimeError, match="STRICT_BOOL"):
            parse_env_bool("STRICT_BOOL", False)

    monkeypatch.delenv("STRICT_BOOL")
    assert parse_env_bool("STRICT_BOOL", True) is True


def _required_settings_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service")


def test_settings_popbill_defaults_and_env(monkeypatch: pytest.MonkeyPatch) -> None:
    _required_settings_env(monkeypatch)
    monkeypatch.setenv("POPBILL_LINK_ID", " link ")
    monkeypatch.setenv("POPBILL_SECRET_KEY", " secret ")
    monkeypatch.setenv("POPBILL_CORP_NUM", "123-45-67890")
    monkeypatch.setenv("POPBILL_USER_ID", " user ")
    for key in ("POPBILL_IS_TEST", "POPBILL_IP_RESTRICT_ON", "POPBILL_USE_STATIC_IP", "POPBILL_USE_LOCAL_TIME"):
        monkeypatch.delenv(key, raising=False)

    settings = Settings.from_env()

    assert settings.popbill_link_id == "link"
    assert settings.popbill_secret_key == "secret"
    assert settings.popbill_corp_num == "123-45-67890"
    assert settings.popbill_user_id == "user"
    assert settings.popbill_is_test is True
    assert settings.popbill_ip_restrict_on is True
    assert settings.popbill_use_static_ip is False
    assert settings.popbill_use_local_time is True


@pytest.mark.parametrize("env_name", [
    "POPBILL_IS_TEST", "POPBILL_IP_RESTRICT_ON", "POPBILL_USE_STATIC_IP", "POPBILL_USE_LOCAL_TIME",
])
def test_malformed_optional_bool_intentionally_fails_startup(
    monkeypatch: pytest.MonkeyPatch, env_name: str
) -> None:
    _required_settings_env(monkeypatch)
    monkeypatch.setenv(env_name, "True")
    with pytest.raises(RuntimeError, match=env_name):
        Settings.from_env()


def test_sdk_runtime_signatures_match_pinned_popbill_1_64_2() -> None:
    expected = {
        "registIssue": "(self, CorpNum, taxinvoice, writeSpecification=False, forceIssue=False, dealInvoiceMgtKey=None, memo=None, emailSubject=None, UserID=None)",
        "getInfo": "(self, CorpNum, MgtKeyType, MgtKey)",
        "getViewURL": "(self, CorpNum, MgtKeyType, MgtKey, UserID=None)",
        "getPDFURL": "(self, CorpNum, MgtKeyType, MgtKey, UserID=None)",
        "checkMgtKeyInUse": "(self, CorpNum, MgtKeyType, MgtKey)",
        "checkCertValidation": "(self, CorpNum, UserID=None)",
        "getCertificateExpireDate": "(self, CorpNum)",
    }
    assert {name: str(inspect.signature(getattr(TaxinvoiceService, name))) for name in expected} == expected


def test_configured_corp_number_whitespace_is_not_normalized(monkeypatch: pytest.MonkeyPatch) -> None:
    _required_settings_env(monkeypatch)
    monkeypatch.setenv("POPBILL_LINK_ID", "link")
    monkeypatch.setenv("POPBILL_SECRET_KEY", "secret")
    monkeypatch.setenv("POPBILL_USER_ID", "user")
    monkeypatch.setenv("POPBILL_CORP_NUM", " 123-45-67890 ")
    settings = Settings.from_env()
    assert settings.popbill_corp_num == " 123-45-67890 "
    with pytest.raises(PopbillError) as exc:
        PopbillService(
            PopbillConfig.from_settings(settings), sdk_factory=lambda *_: FakeTaxinvoiceSDK()
        )
    assert exc.value.code == "POPBILL_INVALID_INPUT"


def test_sdk_configuration_uses_documented_flags(config: PopbillConfig) -> None:
    sdk = FakeTaxinvoiceSDK()
    make_service(config, sdk)
    assert (sdk.IsTest, sdk.IPRestrictOnOff, sdk.UseStaticIP, sdk.UseLocalTimeYN) == (True, True, False, True)
    assert not hasattr(sdk, "IPRestrictOnDemand")


def test_certificate_readiness_calls_provider_without_issuing(config: PopbillConfig) -> None:
    sdk = FakeTaxinvoiceSDK()

    result = make_service(config, sdk).certificate_readiness()

    assert result == PopbillCertificateReadiness(True, "2027-07-27")
    assert sdk.calls == [
        ("checkCertValidation", ("1234567890", "api-user"), {}),
        ("getCertificateExpireDate", ("1234567890",), {}),
    ]


def test_certificate_readiness_fails_closed_and_sanitizes_provider_errors(
    config: PopbillConfig,
) -> None:
    sdk = FakeTaxinvoiceSDK()
    sdk.raise_on["checkCertValidation"] = PopbillException(-999, "certificate secret")

    with pytest.raises(PopbillError) as exc:
        make_service(config, sdk).certificate_readiness()

    assert exc.value.code == "POPBILL_CERTIFICATE_NOT_READY"
    assert exc.value.provider_code == -999
    assert "certificate secret" not in str(exc.value)


def test_certificate_readiness_rejects_malformed_expiration(config: PopbillConfig) -> None:
    sdk = FakeTaxinvoiceSDK()
    sdk.certificate_expiration = "20270727235959"

    with pytest.raises(PopbillError) as exc:
        make_service(config, sdk).certificate_readiness()

    assert exc.value.code == "POPBILL_INVALID_PROVIDER_RESPONSE"


def test_issue_maps_persisted_snapshot_and_exact_sdk_call(config: PopbillConfig, invoice: dict[str, Any]) -> None:
    sdk = FakeTaxinvoiceSDK()
    original = deepcopy(invoice)
    result = make_service(config, sdk).issue(invoice)

    assert result == PopbillIssueResult("GE_invoice-1", 1, nts_accepted=False)
    assert invoice == original
    name, args, kwargs = sdk.calls[0]
    assert name == "registIssue" and kwargs == {}
    assert args[0] == "1234567890"
    payload = args[1]
    assert payload["invoicerMgtKey"] == "GE_invoice-1"
    assert payload["writeDate"] == "20260727"
    assert payload["taxType"] == "과세"
    assert payload["supplyCostTotal"] == "10000"
    assert payload["taxTotal"] == "1000"
    assert payload["totalAmount"] == "11000"
    assert payload["invoicerCorpNum"] == "1234567890"
    assert payload["invoiceeCorpNum"] == "9876543210"
    assert payload["invoicerCorpName"] == "공급자 상호"
    assert payload["invoiceeContactName1"] == "담당자"
    assert payload["invoicerBizType"] == "음식점업"
    assert payload["invoicerBizClass"] == "한식"
    assert payload["invoiceeBizType"] == "서비스업"
    assert payload["invoiceeBizClass"] == "소프트웨어"
    assert payload["detailList"][0]["itemName"] == "정산"
    assert args[2:] == (False, False, None, None, None, "api-user")


def test_issue_allows_delayed_issuance_only_when_explicitly_requested(
    config: PopbillConfig, invoice: dict[str, Any]
) -> None:
    sdk = FakeTaxinvoiceSDK()
    original = deepcopy(invoice)

    make_service(config, sdk).issue(invoice, allow_delayed_issue=True)

    assert invoice == original
    name, args, kwargs = sdk.calls[0]
    assert name == "registIssue" and kwargs == {}
    assert args[1]["forceIssue"] is True
    assert args[2:] == (False, False, None, None, None, "api-user")


def test_typed_persisted_boundary_validates_required_structure(config: PopbillConfig, invoice: dict[str, Any]) -> None:
    service = make_service(config, FakeTaxinvoiceSDK())
    del invoice["recipient_snapshot"]
    with pytest.raises(PopbillError, match="Incomplete persisted invoice") as exc:
        service.issue(invoice)
    assert exc.value.code == "POPBILL_INVALID_INPUT"

    invoice["recipient_snapshot"] = ["not", "a", "snapshot"]
    with pytest.raises(PopbillError, match="party snapshot"):
        service.issue(invoice)


@pytest.mark.parametrize("bad", [
    "123456789", "12345678901", "123-45-6789", "12-345-67890", "123 45 67890",
    " 1234567890", "1234567890 ", "12345A7890", "123‐45‐67890", "",
])
@pytest.mark.parametrize("location", ["config", "supplier", "recipient"])
def test_corp_number_rejects_everything_except_documented_forms(
    config: PopbillConfig, invoice: dict[str, Any], bad: str, location: str
) -> None:
    if location == "config":
        bad_config = PopbillConfig(**{**config.__dict__, "corp_num": bad})
        with pytest.raises(PopbillError) as exc:
            PopbillService(bad_config, sdk_factory=lambda *_: FakeTaxinvoiceSDK())
    else:
        invoice[f"{location}_snapshot"]["registration_number"] = bad
        with pytest.raises(PopbillError) as exc:
            make_service(config, FakeTaxinvoiceSDK()).issue(invoice)
    assert exc.value.code == "POPBILL_INVALID_INPUT"


def test_corp_number_accepts_plain_or_standard_hyphenated(config: PopbillConfig, invoice: dict[str, Any]) -> None:
    plain_config = PopbillConfig(**{**config.__dict__, "corp_num": "1234567890"})
    invoice["supplier_snapshot"]["registration_number"] = "1234567890"
    invoice["recipient_snapshot"]["registration_number"] = "9876543210"
    sdk = FakeTaxinvoiceSDK()
    PopbillService(plain_config, sdk_factory=lambda *_: sdk).issue(invoice)
    assert sdk.calls[0][1][0] == "1234567890"


def test_tax_free_mapping_and_management_key_boundaries(config: PopbillConfig, invoice: dict[str, Any]) -> None:
    invoice.update(tax_type="tax_free", vat_amount=0, total_amount=10000)
    make_service(config, FakeTaxinvoiceSDK()).issue(invoice)

    representative_key = "GE_AbCdEfGhIjKlMnOpQrStu"
    assert len(representative_key) == 24
    invoice["invoicer_mgt_key"] = representative_key
    result = make_service(config, FakeTaxinvoiceSDK()).issue(invoice)
    assert result.management_key == representative_key

    # This is the exact 35-character shape emitted by the current legacy
    # migration ("GE-" plus a UUID with its hyphens removed).
    legacy_key = "GE-123e4567e89b12d3a456426614174000"
    assert len(legacy_key) == 35
    for bad_key in ("", "spaces bad", "x" * 25, legacy_key, "한글", " GE_key"):
        invoice["invoicer_mgt_key"] = bad_key
        with pytest.raises(PopbillError) as exc:
            make_service(config, FakeTaxinvoiceSDK()).issue(invoice)
        assert exc.value.code == "POPBILL_INVALID_INPUT"


def test_party_text_is_scalar_control_free_bounded_and_korean_safe(
    config: PopbillConfig, invoice: dict[str, Any]
) -> None:
    invoice["recipient_snapshot"]["address"] = "서울특별시 중구 세종대로 대한민국 상가 101호"
    make_service(config, FakeTaxinvoiceSDK()).issue(invoice)
    valid_recipient = deepcopy(invoice["recipient_snapshot"])

    for field_name, bad in (("name", ["법인"]), ("representative", "대표\n이름"), ("address", "가" * 301)):
        invoice["recipient_snapshot"][field_name] = bad
        with pytest.raises(PopbillError) as exc:
            make_service(config, FakeTaxinvoiceSDK()).issue(invoice)
        assert exc.value.code == "POPBILL_INVALID_INPUT"
        invoice["recipient_snapshot"] = deepcopy(valid_recipient)


@pytest.mark.parametrize("party", ["supplier_snapshot", "recipient_snapshot"])
def test_contact_phone_has_sdk_twenty_character_limit(
    config: PopbillConfig, invoice: dict[str, Any], party: str
) -> None:
    invoice[party]["contact_phone"] = "1" * 20
    make_service(config, FakeTaxinvoiceSDK()).issue(invoice)

    invoice[party]["contact_phone"] = "1" * 21
    with pytest.raises(PopbillError) as exc:
        make_service(config, FakeTaxinvoiceSDK()).issue(invoice)
    assert exc.value.code == "POPBILL_INVALID_INPUT"


def test_config_and_exceptions_do_not_disclose_secrets_or_provider_pii(config: PopbillConfig) -> None:
    config_repr = repr(config)
    for sensitive in ("LINK-ID", "super-secret-value", "123-45-67890", "api-user"):
        assert sensitive not in config_repr
    assert config.link_id == "LINK-ID"
    assert config.secret_key == "super-secret-value"
    assert config.corp_num == "123-45-67890"
    assert config.user_id == "api-user"

    sdk = FakeTaxinvoiceSDK()
    sdk.raise_on["getInfo"] = PopbillException(-999, "supplier@example.test super-secret-value")
    with pytest.raises(PopbillError) as exc:
        make_service(config, sdk).get_status("GE_invoice-1")
    assert exc.value.code == "POPBILL_TEMPORARILY_UNAVAILABLE"
    assert exc.value.provider_code == -999
    assert "secret" not in str(exc.value).lower()
    assert "supplier@example.test" not in str(exc.value)
    assert exc.value.__cause__ is None


def test_status_repr_hides_provider_memo_confirmation_and_identifiers() -> None:
    status = PopbillStatus(
        management_key="GE_invoice-1",
        item_key="provider-item-key-123",
        provider_state_code=304,
        provider_state_memo="provider-private-memo",
        nts_accepted=True,
        nts_confirm_number="nts-confirm-987",
        issued_at="20260727112233",
        nts_sent_at="20260727112333",
        nts_result_at="20260727112433",
    )
    status_repr = repr(status)
    for sensitive in (
        "GE_invoice-1", "provider-item-key-123", "304", "provider-private-memo", "nts-confirm-987"
    ):
        assert sensitive not in status_repr
    assert status.management_key == "GE_invoice-1"
    assert status.item_key == "provider-item-key-123"
    assert status.provider_state_code == 304
    assert status.provider_state_memo == "provider-private-memo"
    assert status.nts_confirm_number == "nts-confirm-987"


def test_nts_acceptance_requires_suc001_and_corresponding_state(config: PopbillConfig) -> None:
    sdk = FakeTaxinvoiceSDK()
    sdk.info.ntssendDT = "20260727112333"
    sdk.info.ntsresultDT = "20260727112433"
    service = make_service(config, sdk)
    for nts_result, state_code, accepted in (
        ("SUC001", 303, False),
        ("SUC001", 304, True),
        ("SUC001", 300, False),
        ("success", 304, False),
        ("accepted", 304, False),
        (True, 304, False),
        (1, 304, False),
        ("suc001", 304, False),
    ):
        sdk.info.ntsresult = nts_result
        sdk.info.stateCode = state_code
        assert service.get_status("GE_invoice-1").nts_accepted is accepted


@pytest.mark.parametrize("identity", [None, "", "GE_another-document"])
def test_status_requires_exact_provider_identity(
    config: PopbillConfig, identity: str | None
) -> None:
    sdk = FakeTaxinvoiceSDK()
    sdk.info.invoicerMgtKey = identity
    with pytest.raises(PopbillError) as exc:
        make_service(config, sdk).get_status("GE_invoice-1")
    assert exc.value.code == "POPBILL_INVALID_PROVIDER_RESPONSE"


@pytest.mark.parametrize("state", [
    None, True, False, "", "unknown", " 300", "300 ", "0300", "300.0",
    299, 306, 300.0, 300.5, Decimal("300"), Decimal("300.5"),
])
def test_status_rejects_null_or_unknown_provider_state(
    config: PopbillConfig, state: Any
) -> None:
    sdk = FakeTaxinvoiceSDK()
    sdk.info.stateCode = state
    with pytest.raises(PopbillError) as exc:
        make_service(config, sdk).get_status("GE_invoice-1")
    assert exc.value.code == "POPBILL_INVALID_PROVIDER_RESPONSE"


@pytest.mark.parametrize("state", [300, 301, 302, 303, 304, 305, "300", "301", "302", "303", "304", "305"])
def test_status_accepts_only_canonical_issued_state_shapes(config: PopbillConfig, state: Any) -> None:
    sdk = FakeTaxinvoiceSDK()
    sdk.info.stateCode = state
    assert make_service(config, sdk).get_status("GE_invoice-1").provider_state_code == int(state)


def test_status_requires_issue_timestamp_and_rejects_impossible_chronology(
    config: PopbillConfig,
) -> None:
    sdk = FakeTaxinvoiceSDK()
    service = make_service(config, sdk)
    sdk.info.issueDT = None
    with pytest.raises(PopbillError, match="timestamp"):
        service.get_status("GE_invoice-1")

    sdk.info.issueDT = "20260727112233"
    sdk.info.ntssendDT = "20260727112133"
    with pytest.raises(PopbillError, match="chronology"):
        service.get_status("GE_invoice-1")

    sdk.info.ntssendDT = "20260727112333"
    sdk.info.ntsresultDT = "20260727112233"
    with pytest.raises(PopbillError, match="chronology"):
        service.get_status("GE_invoice-1")


def test_issue_success_never_claims_nts_acceptance(config: PopbillConfig, invoice: dict[str, Any]) -> None:
    sdk = FakeTaxinvoiceSDK()
    sdk.issue_response = SimpleNamespace(code=1, ntsresult="SUC001", stateCode=304)
    assert make_service(config, sdk).issue(invoice).nts_accepted is False


def test_view_and_pdf_results_expire_and_redact_url(config: PopbillConfig) -> None:
    sdk = FakeTaxinvoiceSDK()
    service = make_service(config, sdk)
    view = service.get_view_url("GE_invoice-1")
    pdf = service.get_pdf_url("GE_invoice-1")
    assert (view.kind, pdf.kind) == ("view", "pdf")
    assert view.expires_in == pdf.expires_in == 30
    assert view.url.startswith("https://") and pdf.url.startswith("https://")
    assert view.url not in repr(view) and pdf.url not in repr(pdf)
    assert sdk.calls[0][1] == ("1234567890", "SELL", "GE_invoice-1", "api-user")


@pytest.mark.parametrize("bad_url", [
    "", "http://provider.example/view", "javascript:alert(1)", "https:///missing-host",
    "https://user:pass@provider.example/view", "https:// /view", "https://provider.example/bad\npath",
])
def test_provider_urls_must_be_nonempty_https_without_credentials(
    config: PopbillConfig, bad_url: str
) -> None:
    sdk = FakeTaxinvoiceSDK()
    sdk.view_url = bad_url
    with pytest.raises(PopbillError) as exc:
        make_service(config, sdk).get_view_url("GE_invoice-1")
    assert exc.value.code == "POPBILL_INVALID_PROVIDER_RESPONSE"


def test_url_result_contract_always_uses_30_seconds() -> None:
    with pytest.raises(PopbillError):
        PopbillURLResult("GE_key", "view", "https://provider.example/view", expires_in=60)


def test_popbill_issue_failure_never_attempts_reconciliation(config: PopbillConfig, invoice: dict[str, Any]) -> None:
    sdk = FakeTaxinvoiceSDK()
    sdk.raise_on["registIssue"] = PopbillException(-999, "PII supplier@example.test")
    with pytest.raises(PopbillError) as exc:
        make_service(config, sdk).issue(invoice)
    assert exc.value.code == "POPBILL_ISSUE_REJECTED"
    assert [call[0] for call in sdk.calls] == ["registIssue"]


def test_ambiguous_issue_reconciles_only_with_key_and_authoritative_info(
    config: PopbillConfig, invoice: dict[str, Any]
) -> None:
    sdk = FakeTaxinvoiceSDK()
    sdk.raise_on["registIssue"] = TimeoutError("socket with PII and super-secret-value")
    sdk.info.invoicerMgtKey = "GE_invoice-1"
    sdk.info.itemKey = "unrelated-provider-item-key"
    sdk.info.stateCode = 300
    result = make_service(config, sdk).issue(invoice)
    assert result == PopbillIssueResult("GE_invoice-1", None, nts_accepted=False, reconciled=True)
    assert [call[0] for call in sdk.calls] == ["registIssue", "checkMgtKeyInUse", "getInfo"]


@pytest.mark.parametrize("failure", ["not_in_use", "management_key_mismatch", "not_issued", "check_error", "info_error"])
def test_ambiguous_issue_requires_reconciliation_unless_all_checks_pass(
    config: PopbillConfig, invoice: dict[str, Any], failure: str
) -> None:
    sdk = FakeTaxinvoiceSDK()
    sdk.raise_on["registIssue"] = ConnectionError("PII recipient@example.test")
    if failure == "not_in_use":
        sdk.key_in_use = False
    elif failure == "management_key_mismatch":
        sdk.info.invoicerMgtKey = "different-management-key"
    elif failure == "not_issued":
        sdk.info.stateCode = 100
    elif failure == "check_error":
        sdk.raise_on["checkMgtKeyInUse"] = TimeoutError("provider secret")
    else:
        sdk.raise_on["getInfo"] = TimeoutError("provider secret")

    with pytest.raises(PopbillError) as exc:
        make_service(config, sdk).issue(invoice)
    assert exc.value.code == "POPBILL_RECONCILIATION_REQUIRED"
    assert "recipient@example.test" not in str(exc.value)
    assert exc.value.__cause__ is None


@pytest.mark.parametrize("state_code", range(300, 306))
def test_ambiguous_issue_reconciles_for_documented_issued_lifecycle_states(
    config: PopbillConfig, invoice: dict[str, Any], state_code: int
) -> None:
    sdk = FakeTaxinvoiceSDK()
    sdk.raise_on["registIssue"] = TimeoutError("ambiguous")
    sdk.info.stateCode = state_code
    assert make_service(config, sdk).issue(invoice).reconciled is True


@pytest.mark.parametrize("state_code", [299, 306])
def test_ambiguous_issue_rejects_states_outside_issued_lifecycle(
    config: PopbillConfig, invoice: dict[str, Any], state_code: int
) -> None:
    sdk = FakeTaxinvoiceSDK()
    sdk.raise_on["registIssue"] = TimeoutError("ambiguous")
    sdk.info.stateCode = state_code
    with pytest.raises(PopbillError) as exc:
        make_service(config, sdk).issue(invoice)
    assert exc.value.code == "POPBILL_RECONCILIATION_REQUIRED"


def test_non_ambiguous_unknown_exception_does_not_reconcile(config: PopbillConfig, invoice: dict[str, Any]) -> None:
    sdk = FakeTaxinvoiceSDK()
    sdk.raise_on["registIssue"] = ValueError("bad local behavior with PII")
    with pytest.raises(PopbillError) as exc:
        make_service(config, sdk).issue(invoice)
    assert exc.value.code == "POPBILL_TEMPORARILY_UNAVAILABLE"
    assert [call[0] for call in sdk.calls] == ["registIssue"]
