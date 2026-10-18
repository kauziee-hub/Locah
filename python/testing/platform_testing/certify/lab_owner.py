"""A fresh local owner for the Owner Simulation Lab (tools/certify/owner-lab).

    uv run python -m platform_testing.certify.lab_owner <label>                -> {"id", "email"}
    uv run python -m platform_testing.certify.lab_owner script <scenario> <variant>  -> the owner's words

The second form hands the browser lab the same persona the API journeys use
(owners.py): what the owner opens with, answers per question, says when
unsure, and which tools they keep.

Plays the part of sign-up on the certification stack, which has no email or
password sign-in: the auth user row Supabase would create (the same
`ensure_auth_user` the API journeys use). Local database only.
"""

from __future__ import annotations

import asyncio
import json
import sys
import uuid

from platform_testing.certify.journey import DB


async def register(label: str, email: str = "") -> dict[str, str]:
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

    from platform_testing.db_helpers import ensure_auth_user

    user_id = uuid.uuid4()
    email = email or f"lab-{label}-{user_id.hex[:6]}@locah.test"
    if not email.endswith("@locah.test"):
        raise SystemExit("lab identities use @locah.test addresses only")
    engine = create_async_engine(f"postgresql+asyncpg://postgres@localhost:54329/{DB}")
    async with AsyncSession(engine) as session:
        await ensure_auth_user(session, user_id, email)
        await session.commit()
    await engine.dispose()
    return {"id": str(user_id), "email": email}


def script(scenario_key: str, variant: str) -> dict[str, object]:
    from platform_testing.certify.owners import scenario

    s = scenario(scenario_key)
    owner = s.variants[variant]
    return {"key": s.key, "business_name": s.business_name, "category_hint": s.category_hint,
            "business_type": s.business_type, "modules": list(s.modules), "place": s.place, "phone": s.phone,
            "kind": s.kind, "opening": owner.opening, "answers": owner.answers, "fallback": owner.fallback,
            "confirm_text": owner.confirm_text, "media": list(owner.media)}


if __name__ == "__main__":  # pragma: no cover — a tool
    if len(sys.argv) > 1 and sys.argv[1] == "script":
        print(json.dumps(script(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "normal"), ensure_ascii=False))
    else:
        print(json.dumps(asyncio.run(register(sys.argv[1] if len(sys.argv) > 1 else "owner",
                                              sys.argv[2] if len(sys.argv) > 2 else ""))))
