
from getpass import getpass

from sqlalchemy import select

from app.main import Base, engine, SessionLocal, User, hash_password


def main():
    Base.metadata.create_all(bind=engine)

    username = input("Super Admin username: ").strip()
    email = input("Super Admin email: ").strip()
    password = getpass("Password (minimum 12 characters): ")
    confirm = getpass("Confirm password: ")

    if not username or not email:
        raise SystemExit("Username and email are required.")

    if password != confirm:
        raise SystemExit("Passwords do not match.")

    try:
        password_hash = hash_password(password)
    except ValueError as exc:
        raise SystemExit(str(exc))

    db = SessionLocal()
    try:
        existing = db.scalar(
            select(User).where(
                (User.username == username)
                | (User.email == email)
            )
        )

        if existing:
            raise SystemExit("Username or email already exists.")

        admin = User(
            username=username,
            email=email,
            password_hash=password_hash,
            role="SUPERADMIN",
            company_id=None,
            is_active=True,
        )

        db.add(admin)
        db.commit()

        print("Super Admin created successfully.")

    finally:
        db.close()


if __name__ == "__main__":
    main()
