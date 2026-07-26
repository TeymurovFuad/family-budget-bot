"""
states.py — integer constants for all ConversationHandler state machines.
Import from here in every handler module.
"""

(ADD_VALUE, ADD_CURRENCY, ADD_TYPE, ADD_CATEGORY,
 ADD_PERSON,  # retired 2026-07-25 — person step removed; kept so numbering doesn't shift
 ADD_DESC, ADD_RECURRING, ADD_CONFIRM) = range(8)
ADD_DATE    = 8

DELETE_PICK = 200
SET_CCY     = 99
EDIT_PICK   = 300
EDIT_FIELD  = 301
EDIT_VALUE  = 302
EDIT_CONFIRM = 303
BULK_RECEIVE = 400
BULK_CONFIRM = 401
BULK_STATEMENT = 402        # user sent a CSV/XLSX — checking profile
BULK_PROFILE_CONFIRM = 403  # AI proposed mapping — awaiting user confirmation
BULK_PROFILE_NAME = 404     # user confirmed mapping — awaiting profile name
BULK_PROFILE_FIX_COL = 405  # user chose "Fix a column" — awaiting column pick
BULK_PROFILE_FIX_FIELD = 406  # user picked column — awaiting field assignment
BULK_PROFILE_FIX_SETTING = 407  # user chose "Fix settings" → date_format text input
QUICK_CONFIRM = 500
SET_BUDGET_PICK   = 600
SET_BUDGET_AMOUNT = 601
KW_PICK = 700
KW_ADD  = 701

# /setup onboarding conversation (800s — 600s and 700s are taken above)
(SETUP_WELCOME, SETUP_REVIEW, SETUP_RENAME, SETUP_ADD,
 SETUP_BUDGET, SETUP_CURRENCY, SETUP_SUMMARY) = range(800, 807)
