"""Validator errors that are safe to show for any field.

The validation-error handler swaps a secret-named field's validator message for
a generic one, since a validator's text can quote the value it rejected. A rule
whose message is fixed text never does, so it raises this instead and the
client still gets told which rule failed.
"""


class FixedRuleError(ValueError):
    """A validator rule whose message is fixed text and never holds the input.

    Only raise it with a literal message. Anything built from the value (an
    f-string, a repr) belongs in a plain ValueError, which stays scrubbed.
    """
