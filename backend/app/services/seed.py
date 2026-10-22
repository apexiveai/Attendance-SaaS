
from app.main import Base, SessionLocal, User, engine, hash_password


def seed():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    try:
        username = "APEXIVEADMIN"
        superadmin = (
            db.query(User)
            .filter(User.username == username)
            .first()
        )

        if superadmin:
            print("SUPERADMIN already exists.")
            return

        superadmin = User(
            username=username,
            email="admin@apexiveai.com",
            password_hash=hash_password("ChangeMe@2026!"),
            role="SUPERADMIN",
            is_active=True,
            company_id=None,
        )

        db.add(superadmin)
        db.commit()
        print("SUPERADMIN created: APEXIVEADMIN")

    finally:
        db.close()


if __name__ == "__main__":
    seed()
