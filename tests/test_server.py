import copy
import unittest

from backend.server import authorize_update, valid_state


def baseline():
    return {
        "M": {"flour": {"n": "Flour", "u": "kg", "s": 10, "r": 2}},
        "P": {
            "snack": {
                "n": "Snack",
                "pr": 5,
                "fg": 10,
                "lab": 0.1,
                "ovh": 0.2,
                "bom": {"flour": 1},
            }
        },
        "C": [{"id": 1, "n": "Shop", "st": "Tamil Nadu"}],
        "O": [],
        "I": [],
        "L": [
            {"d": "2026-01-01", "i": "Flour", "k": "Opening", "q": 10, "ref": "OB"},
            {"d": "2026-01-01", "i": "Snack", "k": "Opening", "q": 10, "ref": "OB"},
        ],
        "R": [],
        "PU": [],
        "LG": [{"t": "2026-01-01", "u": "System", "a": "Seed"}],
        "seq": 1,
    }


def add_log(state, actor, action):
    state["LG"].insert(0, {"u": actor, "a": action})


class RoleAuthorizationTests(unittest.TestCase):
    def test_seed_state_passes_business_validation(self):
        self.assertTrue(valid_state(baseline()))

    def test_business_validation_rejects_unbalanced_stock(self):
        invalid = baseline()
        invalid["M"]["flour"]["s"] = 9
        self.assertFalse(valid_state(invalid))

    def test_salesman_can_submit_own_order(self):
        old = baseline()
        new = copy.deepcopy(old)
        new["seq"] += 1
        new["O"].append(
            {"id": "SO-2", "c": 1, "l": {"snack": 2}, "by": "Ravi", "d": "2026-01-01", "st": "Submitted"}
        )
        add_log(new, "Ravi", "Placed SO-2")
        self.assertTrue(authorize_update(old, new, {"name": "Ravi", "role": "Salesman"}))

    def test_salesman_cannot_approve_order(self):
        old = baseline()
        old["O"].append(
            {"id": "SO-2", "c": 1, "l": {"snack": 2}, "by": "Ravi", "d": "2026-01-01", "st": "Submitted"}
        )
        new = copy.deepcopy(old)
        new["O"][0]["st"] = "Approved"
        add_log(new, "Ravi", "Approved SO-2")
        self.assertFalse(authorize_update(old, new, {"name": "Ravi", "role": "Salesman"}))

    def test_factory_admin_can_approve_order(self):
        old = baseline()
        old["O"].append(
            {"id": "SO-2", "c": 1, "l": {"snack": 2}, "by": "Ravi", "d": "2026-01-01", "st": "Submitted"}
        )
        new = copy.deepcopy(old)
        new["O"][0]["st"] = "Approved"
        add_log(new, "Factory admin", "Approved SO-2")
        self.assertTrue(authorize_update(old, new, {"name": "Meena", "role": "Factory admin"}))

    def test_factory_admin_invoice_updates_stock_and_gst(self):
        old = baseline()
        old["O"].append(
            {"id": "SO-2", "c": 1, "l": {"snack": 1}, "by": "Ravi", "d": "2026-01-01", "st": "Approved"}
        )
        new = copy.deepcopy(old)
        new["O"][0]["st"] = "Invoiced"
        new["P"]["snack"]["fg"] -= 1
        new["L"].append({"i": "Snack", "k": "Sale", "q": -1, "ref": "INV/1"})
        new["I"].append(
            {
                "no": "INV/1",
                "o": "SO-2",
                "d": "2026-01-01",
                "tx": 5,
                "cg": 0.13,
                "sg": 0.12,
                "ig": 0,
                "tot": 5.25,
                "pd": [],
                "disp": False,
                "aud": False,
            }
        )
        add_log(new, "Factory admin", "Invoice INV/1")
        self.assertTrue(authorize_update(old, new, {"name": "Meena", "role": "Factory admin"}))

    def test_supervisor_can_record_production(self):
        old = baseline()
        new = copy.deepcopy(old)
        new["M"]["flour"]["s"] -= 1
        new["P"]["snack"]["fg"] += 9
        new["R"].append({"id": "PR-1", "p": "snack", "good": 9})
        new["L"].extend(
            [
                {"i": "Flour", "k": "Consumed", "q": -1, "ref": "PR-1"},
                {"i": "Snack", "k": "Produced", "q": 9, "ref": "PR-1"},
            ]
        )
        add_log(new, "Supervisor", "PR-1 recorded")
        self.assertTrue(authorize_update(old, new, {"name": "Karthik", "role": "Supervisor"}))

    def test_auditor_can_verify_invoice_but_not_edit_order(self):
        old = baseline()
        old["I"].append({"no": "INV/1", "aud": False})
        new = copy.deepcopy(old)
        new["I"][0]["aud"] = True
        add_log(new, "Auditor", "Verified INV/1")
        self.assertTrue(authorize_update(old, new, {"name": "Lakshmi", "role": "Auditor"}))

        invalid = copy.deepcopy(new)
        invalid["O"].append({"id": "SO-1"})
        self.assertFalse(authorize_update(old, invalid, {"name": "Lakshmi", "role": "Auditor"}))

    def test_owner_cannot_mutate_business_data(self):
        old = baseline()
        new = copy.deepcopy(old)
        new["O"].append({"id": "SO-1"})
        self.assertFalse(authorize_update(old, new, {"name": "Subramani", "role": "Owner"}))


if __name__ == "__main__":
    unittest.main()
