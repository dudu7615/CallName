"""管理员密码：Argon2id 哈希、校验与强度规则。

密码只以 Argon2id 哈希串存进 `meta` 表，绝不落明文。定位是课堂场景的
**防误触 / 防随手改**，不是安全边界：能读写 `callname.db` 的人本来就能
直接改库，js_api 的本地 HTTP 桥也没有鉴权。

参数取 OWASP 建议的档位：m=64 MiB、t=3、p=1。p=1 避免低配教室机被核数
拖慢；参数调整后，`needs_rehash()` 会在下次成功校验时把旧哈希透明升级。
"""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

#: 密码长度限制。上限只是防止有人往 meta 里塞兆级字符串。
PASSWORD_MIN = 4
PASSWORD_MAX = 128

#: 单例即可：参数不可变，`verify` 自带线程安全。
_HASHER = PasswordHasher(
    time_cost=3,
    memory_cost=65536,
    parallelism=1,
    hash_len=32,
    salt_len=16,
)


class AuthError(Exception):
    """可直接映射成 ApiError 的认证错误。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"


def validate_password(password: str) -> str:
    """长度规则；不合法抛 AuthError，错误码给前端分支用。"""
    if len(password) < PASSWORD_MIN:
        raise AuthError("PASSWORD_TOO_SHORT", f"密码至少 {PASSWORD_MIN} 位")
    if len(password) > PASSWORD_MAX:
        raise AuthError("PASSWORD_TOO_LONG", f"密码最多 {PASSWORD_MAX} 位")
    return password


def hash_password(password: str) -> str:
    """生成带参数的 Argon2id 哈希串（每次 salt 随机）。"""
    return _HASHER.hash(validate_password(password))


def verify_password(password: str, stored: str) -> bool:
    """校验密码；坏哈希、空串一律当失败，不把异常抛给调用方。"""
    if not stored or not password:
        return False
    try:
        return _HASHER.verify(stored, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(stored: str) -> bool:
    """参数落后（或格式损坏）时返回 True；损坏的哈希不值得重写，返回 False。"""
    if not stored:
        return False
    try:
        return _HASHER.check_needs_rehash(stored)
    except InvalidHashError:
        return False
