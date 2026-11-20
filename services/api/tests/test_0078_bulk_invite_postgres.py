"""Migration 0078 on PostgreSQL 16: bulk-registered staff are linked by their proven phone number."""
import uuid

from tests.test_0073_exposure_generator_postgres import db0073, pg  # noqa: F401  (fixtures)
from tests.test_settlement_postgres import settlement_db  # noqa: F401  (fixture)


def _company(conn, name="테스트회사", status="active"):
    company = conn.execute("insert into companies(name) values (%s) returning id", (name + uuid.uuid4().hex[:6],)).fetchone()[0]
    conn.execute("update companies set status=%s where id=%s", (status, company))
    return company


def _phone():
    return "010" + str(uuid.uuid4().int)[:8]


def _customer(conn, phone, *, verified=True, age="0 minutes", status="active", name="김개인"):
    return conn.execute(
        """insert into app_users(id,display_name,phone,role,status,phone_verified_at,created_at)
           values (gen_random_uuid(),%s,%s,'customer',%s,case when %s then now() end, now() - %s::interval) returning id""",
        (name, phone, status, verified, age)).fetchone()[0]


def _invite(conn, company, phone, name="김직원", no=None):
    return conn.execute(
        """insert into employee_bulk_invites(company_id,department,display_name,employee_no,phone)
           values (%s,'개발팀',%s,%s,%s) returning id""",
        (company, name, no or "E-" + uuid.uuid4().hex[:6], phone)).fetchone()[0]


def _respond(conn, user, invite, accept, fresh=False):
    return conn.execute("select public.respond_employee_bulk_invite(%s,%s,%s,%s)", (user, invite, accept, fresh)).fetchone()[0]


def _user(conn, user):
    return conn.execute("select role,status,company_id,display_name,employee_no,department from app_users where id=%s", (user,)).fetchone()


def test_fresh_signup_is_linked_at_once_with_the_roster_details(pg):
    company, phone = _company(pg), _phone()
    invite = _invite(pg, company, phone, name="김직원", no="A-100")
    user = _customer(pg, phone)
    result = _respond(pg, user, None, True, fresh=True)
    assert (result["status"], result["invite_id"], result["company_id"]) == ("accepted", str(invite), str(company))
    assert _user(pg, user) == ("employee", "active", company, "김직원", "A-100", "개발팀")
    assert pg.execute("select status,claimed_by from employee_bulk_invites where id=%s", (invite,)).fetchone() == ("active", user)
    assert pg.execute("select action from employee_join_audit_logs where user_id=%s", (user,)).fetchone() == ("approved",)
    # Already an employee: nothing further to answer.
    assert _respond(pg, user, None, True)["status"] == "not_eligible"
    assert pg.execute("select public.employee_bulk_invite_offer(%s)", (user,)).fetchone()[0] is None


def test_existing_member_is_asked_first_and_keeps_everything_until_they_answer(pg):
    company, phone = _company(pg), _phone()
    invite = _invite(pg, company, phone)
    user = _customer(pg, phone, age="3 days")
    # The signup-time call never converts an account that already existed.
    assert _respond(pg, user, None, True, fresh=True)["status"] == "needs_confirmation"
    assert _user(pg, user)[0] == "customer"
    offer = pg.execute("select public.employee_bulk_invite_offer(%s)", (user,)).fetchone()[0]
    assert (offer["invite_id"], offer["display_name"], offer["department"]) == (str(invite), "김직원", "개발팀")
    assert offer["company_name"].startswith("테스트회사")
    assert _respond(pg, user, invite, True)["status"] == "accepted"
    assert _user(pg, user)[:3] == ("employee", "active", company)


def test_a_refusal_is_recorded_and_the_admin_can_offer_again(pg):
    company, other, phone = _company(pg), _company(pg, "다른회사"), _phone()
    invite = _invite(pg, company, phone)
    user = _customer(pg, phone, age="3 days")
    assert _respond(pg, user, invite, False)["status"] == "declined"
    row = pg.execute("select status,declined_by,declined_at is not null,claimed_by from employee_bulk_invites where id=%s", (invite,)).fetchone()
    assert row == ("declined", user, True, None)
    assert _user(pg, user)[:3] == ("customer", "active", None)
    # No longer offered, and cannot be accepted behind the admin's back.
    assert pg.execute("select public.employee_bulk_invite_offer(%s)", (user,)).fetchone()[0] is None
    assert _respond(pg, user, invite, True)["status"] == "not_found"
    # Only the owning company can re-invite.
    assert pg.execute("select public.reinvite_employee_bulk_invite(%s,%s)", (other, invite)).fetchone()[0] is False
    assert pg.execute("select public.reinvite_employee_bulk_invite(%s,%s)", (company, invite)).fetchone()[0] is True
    assert pg.execute("select status,declined_at,declined_by from employee_bulk_invites where id=%s", (invite,)).fetchone() == ("invited", None, None)
    assert pg.execute("select public.reinvite_employee_bulk_invite(%s,%s)", (company, invite)).fetchone()[0] is False
    assert _respond(pg, user, invite, True)["status"] == "accepted"


def test_only_a_proven_number_of_an_active_personal_account_is_matched(pg):
    company = _company(pg)
    # Number typed in but never proven by SMS.
    phone = _phone(); invite = _invite(pg, company, phone)
    unverified = _customer(pg, phone, verified=False)
    assert pg.execute("select public.employee_bulk_invite_offer(%s)", (unverified,)).fetchone()[0] is None
    assert _respond(pg, unverified, invite, True)["status"] == "not_eligible"
    assert _respond(pg, unverified, None, True, fresh=True)["status"] == "not_eligible"
    # Someone else's invite id: matched by the caller's own number, so not found.
    stranger = _customer(pg, _phone())
    assert _respond(pg, stranger, invite, True)["status"] == "not_found"
    assert _respond(pg, stranger, invite, False)["status"] == "not_found"
    assert pg.execute("select status from employee_bulk_invites where id=%s", (invite,)).fetchone() == ("invited",)
    # Paused account, and a company that is not active.
    phone2 = _phone(); _invite(pg, company, phone2)
    assert _respond(pg, _customer(pg, phone2, status="paused"), None, True)["status"] == "not_eligible"
    phone3 = _phone(); _invite(pg, _company(pg, "중지회사", status="suspended"), phone3)
    closed = _customer(pg, phone3)
    assert pg.execute("select public.employee_bulk_invite_offer(%s)", (closed,)).fetchone()[0] is None
    assert _respond(pg, closed, None, True, fresh=True)["status"] == "not_found"


def test_a_fresh_account_that_already_owns_an_order_is_asked_instead(pg):
    company, phone = _company(pg), _phone()
    _invite(pg, company, phone)
    user = _customer(pg, phone)
    merchant = pg.execute("insert into merchants(name,qr_token,view_token) values ('m',%s,%s) returning id",
                          (str(uuid.uuid4()), str(uuid.uuid4()))).fetchone()[0]
    suffix = uuid.uuid4().hex[:10]
    product = pg.execute("""insert into voucher_products(merchant_id,name,voucher_count,bonus_count,unit_price,tax_type)
                            values (%s,'p',1,0,8000,'taxable') returning id""", (merchant,)).fetchone()[0]
    pg.execute("""insert into payment_orders(order_id,checkout_token,user_id,merchant_id,merchant_name,product_name,amount,status,
                                             pay_type,voucher_product_id,voucher_count,voucher_purchase_price,gross_amount,requested_point_amount)
                  values (%s,%s,%s,%s,'m','p',8000,'ready','voucher',%s,1,8000,8000,0)""",
               (f"o-{suffix}", f"t-{suffix}", user, merchant, product))
    assert _respond(pg, user, None, True, fresh=True)["status"] == "needs_confirmation"
    assert _user(pg, user)[0] == "customer"


def test_a_clash_with_an_existing_employee_changes_nothing(pg):
    company, phone = _company(pg), _phone()
    invite = _invite(pg, company, phone, no="DUP-1")
    pg.execute("""insert into app_users(id,company_id,display_name,role,status,employee_no)
                  values (gen_random_uuid(),%s,'기존직원','employee','active','DUP-1')""", (company,))
    user = _customer(pg, phone)
    assert _respond(pg, user, invite, True)["status"] == "conflict"
    assert _user(pg, user)[:3] == ("customer", "active", None)
    assert pg.execute("select status from employee_bulk_invites where id=%s", (invite,)).fetchone() == ("invited",)


def test_client_roles_cannot_call_the_functions(pg):
    for role in ("anon", "authenticated"):
        for signature in ("employee_bulk_invite_offer(uuid)", "respond_employee_bulk_invite(uuid,uuid,boolean,boolean)",
                          "reinvite_employee_bulk_invite(uuid,uuid)"):
            assert pg.execute(f"select has_function_privilege('{role}','public.{signature}','execute')").fetchone()[0] is False
