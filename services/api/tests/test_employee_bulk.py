import csv
import io

import pytest
from openpyxl import Workbook

from app.services.employee_bulk import (
    BulkFileError,
    RawEmployeeRow,
    build_template,
    read_employee_file,
    validate_rows,
)


def csv_bytes(rows, header=("부서", "이름", "사번", "전화번호")):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(header)
    writer.writerows(rows)
    return output.getvalue().encode("utf-8-sig")


def test_csv_requires_exact_header_and_order():
    with pytest.raises(BulkFileError, match="헤더와 순서"):
        read_employee_file("employees.csv", csv_bytes([], ("이름", "부서", "사번", "전화번호")))


def test_rejects_more_than_500_nonempty_data_rows():
    rows = [["", f"직원{i}", "", f"010{i:08d}"] for i in range(501)]
    with pytest.raises(BulkFileError, match="최대 500행"):
        read_employee_file("employees.csv", csv_bytes(rows))


def test_missing_name_bad_phone_and_later_file_duplicate_are_errors():
    rows = read_employee_file("employees.csv", csv_bytes([
        ["개발", "", "A1", "010-1111-1111"],
        ["개발", "김하나", "A2", "010-abcd-1111"],
        ["개발", "김둘", "A3", "010-2222-2222"],
        ["개발", "김셋", "A4", "01022222222"],
    ]))
    result = validate_rows(rows, company_id="abc-company")
    assert [item["reason"] for item in result["errors"]] == ["이름 누락", "전화번호 형식 오류", "파일 내 중복"]
    assert [item["name"] for item in result["valid"]] == ["김둘"]
    assert result["valid"][0]["phone"] == "01022222222"


def test_existing_phone_and_manual_employee_numbers_are_checked():
    rows = read_employee_file("employees.csv", csv_bytes([
        ["", "기존번호", "NEW", "01033333333"],
        ["", "기존사번", "OLD", "01044444444"],
        ["", "파일사번1", "SAME", "01055555555"],
        ["", "파일사번2", "SAME", "01066666666"],
    ]))
    result = validate_rows(rows, company_id="abc-company", existing_phones={"01033333333"}, existing_employee_nos={"OLD"})
    assert [item["reason"] for item in result["errors"]] == ["이미 등록된 번호", "이미 등록된 사번", "파일 내 사번 중복"]
    assert result["valid"][0]["employee_no"] == "SAME"


def test_blank_numbers_are_stably_allocated_around_existing_values():
    rows = [
        RawEmployeeRow(2, None, "하나", None, "01011111111"),
        RawEmployeeRow(3, None, "둘", None, "01022222222"),
    ]
    result = validate_rows(rows, company_id="a-b-c-company", existing_employee_nos={"ABC-0001", "ABC-0003"})
    assert [row["employee_no"] for row in result["valid"]] == ["ABC-0002", "ABC-0004"]
    assert all(row["auto_generated"] for row in result["valid"])


def test_confirm_style_revalidation_ignores_preview_auto_number_and_reassigns():
    submitted = [RawEmployeeRow(2, "개발", "하나", "ABC-0001", "01011111111", auto_generated=True)]
    checked = validate_rows(submitted, company_id="abc-company", existing_employee_nos={"ABC-0001"})
    assert checked["errors"] == []
    assert checked["valid"][0]["employee_no"] == "ABC-0002"


def test_confirm_style_revalidation_rejects_phone_that_became_duplicate():
    submitted = [RawEmployeeRow(2, None, "하나", "A1", "01011111111")]
    checked = validate_rows(submitted, company_id="abc-company", existing_phones={"01011111111"})
    assert checked["valid"] == []
    assert checked["errors"][0]["reason"] == "이미 등록된 번호"


def test_template_is_a_real_xlsx_with_example_and_note_comment():
    rows = read_employee_file("template.xlsx", build_template())
    assert len(rows) == 1
    assert rows[0].department == "홍보팀"
    assert rows[0].name == "홍길동"
    assert rows[0].phone == "01012345678"


def test_xlsx_parsing_works():
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.append(["부서", "이름", "사번", "전화번호"])
    sheet.append(["영업", "김영업", "", "010-9876-5432"])
    output = io.BytesIO()
    workbook.save(output)
    rows = read_employee_file("employees.xlsx", output.getvalue())
    assert rows[0].phone == "01098765432"


def test_corrupt_xlsx_is_reported_as_invalid_file():
    with pytest.raises(BulkFileError, match="파일을 읽을 수 없어요"):
        read_employee_file("employees.xlsx", b"not-a-real-xlsx")
