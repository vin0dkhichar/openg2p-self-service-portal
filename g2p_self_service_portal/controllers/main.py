import json
import logging
import random
from datetime import datetime

from werkzeug.datastructures import FileStorage
from werkzeug.exceptions import Forbidden, Unauthorized

from odoo import _, http
from odoo.http import request

from odoo.addons.auth_signup.controllers.main import AuthSignupHome
from odoo.addons.web.controllers.main import Home

from .auth_oidc import G2POpenIDLogin

_logger = logging.getLogger(__name__)


class SelfServiceController(http.Controller):
    @http.route(["/selfservice"], type="http", auth="public", website=True)
    def self_service_root(self, **kwargs):
        if request.session and request.session.uid:
            return request.redirect("/selfservice/home")
        else:
            return request.redirect("/selfservice/login")

    @http.route(["/selfservice/login"], type="http", auth="public", website=True)
    def self_service_login(self, **kwargs):
        if request.session and request.session.uid:
            return request.redirect("/selfservice/home")
        request.params["redirect"] = "/"
        context = {}

        context.update(
            dict(
                providers=G2POpenIDLogin().list_providers(
                    domain=[("g2p_self_service_allowed", "=", True)]
                )
            )
        )

        if request.httprequest.method == "POST":
            res = Home().web_login(**kwargs)

            if not request.params["login_success"]:
                context["error"] = "Wrong login/password"
                return request.render(
                    "g2p_self_service_portal.login_page", qcontext=context
                )

            return res

        return request.render("g2p_self_service_portal.login_page", qcontext=context)

    @http.route(["/selfservice/signup"], type="http", auth="public", website=True)
    def self_service_signup(self, **kwargs):

        if request.session and request.session.uid:
            return request.redirect("/selfservice/home")
        request.session["signup_form_filled"] = True

        if request.httprequest.method == "POST" and "otp" in kwargs:
            stored_otp = request.session["otp"]

            if stored_otp and int(kwargs["otp"]) and stored_otp == int(kwargs["otp"]):

                request.session.pop("otp")
                request.session.pop("signup_form_filled")

                # TODO: Check if user already present

                # TODO: Enable both email and phone login
                request.params["login"] = (
                    kwargs["email"] if kwargs["email"] else kwargs["phone"]
                )
                res = AuthSignupHome().web_auth_signup(**kwargs)

                current_partner = request.env.user.partner_id

                request.env["res.partner"].sudo().browse(current_partner.id).write(
                    {
                        "is_registrant": True,
                        "registration_date": datetime.today().date(),
                    }
                )

                # Adding data of the user
                for key in kwargs:
                    if key in current_partner:
                        current_partner[key] = kwargs[key]

                # Adding VID number
                config = request.env["ir.config_parameter"].sudo()
                reg_id_type_id = config.get_param(
                    "g2p_self_service_portal.self_service_signup_id_type", None
                )

                if kwargs["vid"] and reg_id_type_id:

                    (
                        request.env["g2p.reg.id"]
                        .sudo()
                        .create(
                            {
                                "partner_id": current_partner.id,
                                "id_type": reg_id_type_id,
                                "value": kwargs["vid"],
                            }
                        )
                    )

                # Adding phone number
                request.env["g2p.phone.number"].sudo().create(
                    {"phone_no": kwargs["phone"], "partner_id": current_partner.id}
                )
                current_partner.phone = kwargs["phone"]

                return res

            else:
                return request.render(
                    "g2p_self_service_portal.otp_authentication_page",
                    {
                        "error": "Incorrect OTP. Please try again.",
                        "values": kwargs,
                        "name": kwargs["name"],
                    },
                )

        return request.render("g2p_self_service_portal.signup_page")

    @http.route(
        ["/selfservice/signup/otp"],
        type="http",
        auth="public",
        website=True,
        csrf=False,
    )
    def self_service_signup_otp(self, **kw):

        if not request.session.get("signup_form_filled"):
            return request.redirect("/selfservice")

        request.session["otp"] = random.randint(100000, 999999)

        _logger.error(request.session["otp"])

        # TODO: Use G2P SMS Notification module to send otp

        if request.httprequest.method == "POST":
            kw["name"] = (
                kw["family_name"].title()
                + ", "
                + kw["given_name"].title()
                + " "
                + kw["addl_name"].title()
            )

            return request.render(
                "g2p_self_service_portal.otp_authentication_page",
                {"values": kw, "name": kw["name"]},
            )

    @http.route(["/selfservice/logo"], type="http", auth="public", website=True)
    def self_service_logo(self, **kwargs):
        config = request.env["ir.config_parameter"].sudo()
        attachment_id = config.get_param(
            "g2p_self_service_portal.self_service_logo_attachment"
        )
        return request.redirect("/web/content/%s" % attachment_id)

    @http.route(["/selfservice/myprofile"], type="http", auth="public", website=True)
    def self_service_profile(self, **kwargs):
        if request.session and request.session.uid:
            current_partner = request.env.user.partner_id
            return request.render(
                "g2p_self_service_portal.profile_page",
                {
                    "current_partner": current_partner,
                },
            )

    @http.route(["/selfservice/aboutus"], type="http", auth="public", website=True)
    def self_service_about_us(self, **kwargs):
        return request.render("g2p_self_service_portal.aboutus_page")

    @http.route(["/selfservice/contactus"], type="http", auth="public", website=True)
    def self_service_contact_us(self, **kwargs):
        return request.render("g2p_self_service_portal.contact_us")

    @http.route(["/selfservice/otherpage"], type="http", auth="public", website=True)
    def self_service_other_page(self, **kwargs):
        return request.render("g2p_self_service_portal.other_page")

    @http.route(["/selfservice/help"], type="http", auth="public", website=True)
    def self_service_help_page(self, **kwargs):
        return request.render("g2p_self_service_portal.help_page")

    @http.route(["/selfservice/home"], type="http", auth="user", website=True)
    def self_service_home(self, **kwargs):
        self.self_service_check_roles("REGISTRANT")
        query = request.params.get("query")
        domain = [("name", "ilike", query)]
        programs = request.env["g2p.program"].sudo().search(domain).sorted("id")
        partner_id = request.env.user.partner_id
        program_states = {
            "draft": "Applied",
            "not_eligible": "Not Eligible",
            "duplicated": "Not Eligible",
            "enrolled": "Enrolled",
        }
        application_states = {
            "active": "Applied",
            "inprogress": "Under Review",
            "completed": "Completed",
            "rejected": "Rejected",
            "closed": "Closed",
        }

        amount_received = 0
        myprograms = []
        for program in programs:
            membership = (
                request.env["g2p.program_membership"]
                .sudo()
                .search(
                    [
                        ("partner_id", "=", partner_id.id),
                        ("program_id", "=", program.id),
                    ]
                )
            )

            amount_issued = sum(
                ent.amount_issued
                for ent in request.env["g2p.payment"]
                .sudo()
                .search(
                    [
                        ("partner_id", "=", partner_id.id),
                        ("program_id", "=", program.id),
                    ]
                )
            )
            amount_received = sum(
                ent.amount_paid
                for ent in request.env["g2p.payment"]
                .sudo()
                .search(
                    [
                        ("partner_id", "=", partner_id.id),
                        ("program_id", "=", program.id),
                    ]
                )
            )
            if len(membership) > 0:
                for rec in membership.program_registrant_info_ids:
                    myprograms.append(
                        {
                            "id": program.id,
                            "name": program.name,
                            "has_applied": len(membership) > 0,
                            "single_submission": len(
                                membership.program_registrant_info_ids
                            )
                            == 1,
                            "program_status": program_states.get(
                                membership.state, "Error"
                            ),
                            "application_status": application_states.get(
                                rec.state, "Error"
                            )
                            if membership.state not in ("not_eligible", "duplicated")
                            else program_states.get(membership.state, "Error"),
                            "issued": "{:,.2f}".format(amount_issued),
                            "paid": "{:,.2f}".format(amount_received),
                            "enrollment_date": rec.create_date.strftime("%d-%b-%Y")
                            if rec.create_date
                            else None,
                            "is_latest": (datetime.today() - program.create_date).days
                            < 21,
                            "application_id": rec.application_id
                            if rec.application_id
                            else None,
                        }
                    )

        entitlement = sum(
            ent.amount_issued
            for ent in request.env["g2p.payment"]
            .sudo()
            .search([("partner_id", "=", partner_id.id)])
        )
        received = sum(
            ent.amount_paid
            for ent in request.env["g2p.payment"]
            .sudo()
            .search(
                [
                    ("partner_id", "=", partner_id.id),
                ]
            )
        )

        pending = entitlement - received
        labels = ["Received", "Pending"]
        values = [received, pending]
        data = json.dumps({"labels": labels, "values": values})

        return request.render(
            "g2p_self_service_portal.dashboard",
            {"programs": myprograms, "data": data},
        )

    @http.route(["/selfservice/programs"], type="http", auth="user", website=True)
    def self_service_all_programs(self, **kwargs):
        self.self_service_check_roles("REGISTRANT")

        programs = request.env["g2p.program"].sudo().search([])

        if programs.fields_get("is_reimbursement_program"):
            programs = programs.search([(("is_reimbursement_program", "=", False))])

        partner_id = request.env.user.partner_id
        states = {
            "draft": "Applied",
            "not_eligible": "Not Eligible",
            "duplicated": "Not Eligible",
            "enrolled": "Enrolled",
        }

        values = []
        for program in programs:
            membership = (
                request.env["g2p.program_membership"]
                .sudo()
                .search(
                    [
                        ("partner_id", "=", partner_id.id),
                        ("program_id", "=", program.id),
                    ]
                )
            )
            values.append(
                {
                    "id": program.id,
                    "name": program.name,
                    # "description": program.description,
                    "has_applied": len(membership) > 0,
                    "single_submission": len(membership.program_registrant_info_ids)
                    == 1,
                    "status": states.get(membership.state, "Error"),
                    "is_application_rejected": membership.latest_registrant_info_status
                    == "rejected"
                    if membership.latest_registrant_info_status
                    else False,
                    "is_latest": (datetime.today() - program.create_date).days < 21,
                    "is_form_mapped": True
                    if program.self_service_portal_form
                    else False,
                    "is_multiple_form_submission": True
                    if program.multiple_form_submission
                    else False,
                }
            )

        return request.render(
            "g2p_self_service_portal.allprograms",
            {
                "programs": values,
                # "pager": {
                #     "sel": page,
                #     "total": total,
                # },
            },
        )

    @http.route(
        ["/selfservice/submissions/<int:_id>"], type="http", auth="user", website=True
    )
    def self_service_all_submissions(self, _id):
        self.self_service_check_roles("REGISTRANT")
        program = request.env["g2p.program"].sudo().browse(_id)
        current_partner = request.env.user.partner_id

        all_submission = (
            request.env["g2p.program.registrant_info"]
            .sudo()
            .search(
                [
                    ("program_id", "=", program.id),
                    ("registrant_id", "=", current_partner.id),
                ]
            )
        )

        submission_records = []
        for detail in all_submission:
            submission_records.append(
                {
                    "applied_on": detail.create_date.strftime("%d-%b-%Y"),
                    "application_id": detail.application_id,
                    "status": detail.state
                    if detail.program_membership_id.state
                    not in ("duplicated", "not_eligible")
                    else detail.program_membership_id.state,
                }
            )

        re_apply = True
        for rec in submission_records:
            if rec["status"] in (
                "active",
                "inprogress",
            ):
                re_apply = False
                break

        return request.render(
            "g2p_self_service_portal.program_submission_info",
            {
                "program_id": program.id,
                "submission_records": submission_records,
                "re_apply": re_apply,
                "is_multiple_form_submission": True
                if program.multiple_form_submission
                else False,
            },
        )

    @http.route(
        ["/selfservice/apply/<int:_id>"], type="http", auth="user", website=True
    )
    def self_service_apply_programs(self, _id):
        self.self_service_check_roles("REGISTRANT")

        program = request.env["g2p.program"].sudo().browse(_id)
        multiple_form_submission = program.multiple_form_submission
        current_partner = request.env.user.partner_id

        for mem in current_partner.program_membership_ids:
            if mem.program_id.id == _id:
                if multiple_form_submission:
                    if mem.latest_registrant_info_status not in (
                        "completed",
                        "rejected",
                    ):
                        return request.redirect(f"/selfservice/submissions/{_id}")

                else:
                    return request.redirect(f"/selfservice/submitted/{_id}")

        config = request.env["ir.config_parameter"].sudo()
        file_size = config.get_param(
            "g2p_self_service_portal.self_service_file_upload_size", None
        )

        view = program.self_service_portal_form.view_id

        return request.render(
            view.id,
            {
                "program": program.name,
                "program_id": program.id,
                "file_size": file_size,
                "user": request.env.user.given_name,
            },
        )

    @http.route(
        ["/selfservice/submit/<int:_id>"],
        type="http",
        auth="user",
        website=True,
        csrf=False,
    )
    def self_service_form_submit(self, _id, **kwargs):
        self.self_service_check_roles("REGISTRANT")

        program = request.env["g2p.program"].sudo().browse(_id)
        current_partner = request.env.user.partner_id
        program_member = None

        prog_membs = (
            request.env["g2p.program_membership"]
            .sudo()
            .search(
                [
                    ("partner_id", "=", current_partner.id),
                    ("program_id", "=", program.id),
                ]
            )
        )
        if len(prog_membs) > 0:
            program_member = prog_membs[0]

        if request.httprequest.method == "POST":
            if len(prog_membs) == 0:
                program_member = (
                    request.env["g2p.program_membership"]
                    .sudo()
                    .create(
                        {
                            "partner_id": current_partner.id,
                            "program_id": program.id,
                        }
                    )
                )

            for key in kwargs:
                if isinstance(kwargs[key], FileStorage):
                    kwargs[key] = request.httprequest.files.getlist(key)

            form_data = kwargs

            delete_key = self.get_field_to_exclude(form_data)

            for item in delete_key:
                del form_data[item]

            # Hardcoding Account number from form data for now
            account_num = form_data.get("Account Number", None)
            if account_num:
                if len(current_partner.bank_ids) > 0:
                    # TODO: Fixing value of first account number for now, if more than one exists
                    current_partner.bank_ids[0].acc_number = account_num
                else:
                    current_partner.bank_ids = [(0, 0, {"acc_number": account_num})]

            (
                request.env["g2p.program.registrant_info"]
                .sudo()
                .create(
                    {
                        "state": "active",
                        "program_registrant_info": self.jsonize_form_data(
                            form_data, program, membership=program_member
                        ),
                        "program_id": program.id,
                        "registrant_id": current_partner.id,
                    }
                )
            )

        else:
            if not program_member:
                return request.redirect(f"/selfservice/apply/{_id}")

        return request.redirect(f"/selfservice/submitted/{_id}")

    @http.route(
        ["/selfservice/submitted/<int:_id>"],
        type="http",
        auth="user",
        website=True,
    )
    def self_service_form_details(self, _id, **kwargs):
        self.self_service_check_roles("REGISTRANT")

        program = request.env["g2p.program"].sudo().browse(_id)
        current_partner = request.env.user.partner_id

        program_reg_info = (
            request.env["g2p.program.registrant_info"]
            .sudo()
            .search(
                [
                    ("registrant_id", "=", current_partner.id),
                    ("program_id", "=", program.id),
                ]
            )
            .sorted("create_date", reverse=True)
        )

        if len(program_reg_info) > 1:
            program_reg_info = program_reg_info[0]

        return request.render(
            "g2p_self_service_portal.self_service_form_submitted",
            {
                "program": program.name,
                "submission_date": program_reg_info.create_date.strftime("%d-%b-%Y"),
                # TODO: Redirect to different page if application doesn't exist
                "application_id": program_reg_info.application_id
                if program_reg_info
                else None,
                "user": current_partner.given_name.capitalize()
                if current_partner.given_name
                else current_partner.name,
            },
        )

    def self_service_check_roles(self, role_to_check):
        # And add further role checks and return types
        if role_to_check == "REGISTRANT":
            if not request.session or not request.env.user:
                raise Unauthorized(_("User is not logged in"))
            if not request.env.user.partner_id.is_registrant:
                raise Forbidden(_("User is not allowed to access the portal"))

    def jsonize_form_data(self, data, program, membership=None):
        for key in data:
            value = data[key]
            if isinstance(value, list):
                if len(value) > 0 and isinstance(value[0], FileStorage):
                    if not program.supporting_documents_store:
                        _logger.error(
                            "Supporting Documents Store is not set in Program Configuration"
                        )
                        data[key] = None
                        continue

                    data[key] = self.add_file_to_store(
                        value,
                        program.supporting_documents_store,
                        program_membership=membership,
                    )
                    if not data.get(key, None):
                        _logger.warning("Empty/No File received for field %s", key)
                        continue

        return data

    @classmethod
    def add_file_to_store(cls, files, store, program_membership=None):
        if isinstance(files, FileStorage):
            files = [
                files,
            ]
        file_details = []
        for file in files:
            if store and file.filename:
                if len(file.filename.split(".")) > 1:
                    supporting_document_ext = "." + file.filename.split(".")[-1]
                else:
                    supporting_document_ext = None
                document_file = store.add_file(
                    file.stream.read(),
                    extension=supporting_document_ext,
                    program_membership=program_membership,
                )
                document_uuid = document_file.name.split(".")[0]
                file_details.append(
                    {
                        "document_id": document_file.id,
                        "document_uuid": document_uuid,
                        "document_name": document_file.name,
                        "document_slug": document_file.slug,
                        "document_url": document_file.url,
                    }
                )
        return file_details

    def get_field_to_exclude(self, data):
        current_partner = request.env.user.partner_id
        keys = []
        for key in data:
            if key in current_partner:
                current_partner[key] = data[key]
                keys.append(key)

        return keys
