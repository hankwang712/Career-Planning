import getpass
import sys
import time
from pathlib import Path

from werkzeug.security import generate_password_hash


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import db
from services.auth import AuthError, normalize_email, validate_password


def main():
    try:
        email = normalize_email(input("管理员邮箱：").strip())
        password = getpass.getpass("设置密码：")
        validate_password(password)
        if password != getpass.getpass("再次输入密码："):
            raise AuthError("两次输入的密码不一致。")
        db.init_db()
        with db._get_conn() as conn:
            conn.execute("""
                INSERT INTO users (username, password_hash, role, display_name, created_at)
                VALUES (?, ?, 'super_admin', ?, ?)
                ON CONFLICT(username) DO UPDATE SET
                    password_hash = excluded.password_hash, role = 'super_admin', disabled = 0
            """, (email, generate_password_hash(password), email.split("@")[0][:48], time.time()))
            conn.execute("DELETE FROM auth_sessions WHERE username = ?", (email,))
        print("管理员账户已保存，原有会话已撤销。")
    except (AuthError, EOFError, KeyboardInterrupt) as error:
        print(getattr(error, "message", "操作已取消。"), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
