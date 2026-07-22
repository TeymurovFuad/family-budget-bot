"""
states.py — integer constants for all ConversationHandler state machines.
Import from here in every handler module.
"""

(ADD_VALUE, ADD_CURRENCY, ADD_TYPE, ADD_CATEGORY,
 ADD_PERSON, ADD_DESC, ADD_RECURRING, ADD_CONFIRM) = range(8)
ADD_DATE    = 8

DELETE_PICK = 200
SET_CCY     = 99
EDIT_PICK   = 300
EDIT_FIELD  = 301
EDIT_VALUE  = 302
EDIT_CONFIRM = 303
BULK_RECEIVE = 400
BULK_CONFIRM = 401
QUICK_CONFIRM = 500
SET_BUDGET_PICK   = 600
SET_BUDGET_AMOUNT = 601
