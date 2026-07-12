import pytest
from pydantic import ValidationError

from app.schemas import EmployeePointAdjustRequest, EmployeePointChargeRequest, EmployeeProfileUpdateRequest


def test_employee_profile_update_normalizes_editable_fields():
    payload = EmployeeProfileUpdateRequest(
        department="  개발팀 ",
        display_name=" 홍길동 ",
        employee_no=" E-001 ",
        phone=" 010-1234-5678 ",
    )
    assert payload.model_dump() == {
        "department": "개발팀",
        "display_name": "홍길동",
        "employee_no": "E-001",
        "phone": "010-1234-5678",
    }


def test_employee_profile_update_rejects_blank_display_name():
    with pytest.raises(ValidationError):
        EmployeeProfileUpdateRequest(display_name="  ")


def test_point_changes_need_only_the_amount():
    assert EmployeePointChargeRequest(amount=1000).model_dump() == {"amount": 1000}
    assert EmployeePointAdjustRequest(target_balance=0).model_dump() == {"target_balance": 0}
