"""Who can change things in Nonna.

Two roles:
- attorney: can do everything (review, correct, make calls, write notes, fix uploads, draft).
- business: read-only. Can look things up in chat and the library, but can't change anything.

There's no login yet. The app says who's using it in the X-Nonna-User header, and this
roster says what that person can do. A missing or unknown name gets read-only access,
so the safe answer is the default. Every endpoint that changes data checks this on the
server, so hiding buttons in the app is a convenience, not the protection.
A real deployment would swap the header for the firm's single sign-on.
"""

from typing import Annotated, Literal

from fastapi import Depends, Header, HTTPException, status

Role = Literal["attorney", "business"]

# The demo roster (names only, no passwords or secrets)
USERS: dict[str, Role] = {
    "demo.attorney": "attorney",
    "demo.business": "business",
}

READ_ONLY = (
    "You have read-only access, so you can look things up but can't change anything. "
    "Ask someone on the legal team to make this change."
)


def role_for(user: str | None) -> Role:
    """The role for a user name. Unknown or missing names are read-only."""
    return USERS.get((user or "").strip(), "business")


def current_role(x_nonna_user: Annotated[str | None, Header()] = None) -> Role:
    """The role of whoever is making this request."""
    return role_for(x_nonna_user)


RoleDep = Annotated[Role, Depends(current_role)]


def attorney_only(role: RoleDep) -> None:
    """Stop anyone who isn't an attorney. Used on every endpoint that changes data."""
    if role != "attorney":
        raise HTTPException(status.HTTP_403_FORBIDDEN, READ_ONLY)


AttorneyOnly = [Depends(attorney_only)]