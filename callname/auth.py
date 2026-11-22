"""管理员密码：Argon2id 哈希、校验与强度规则。

密码只以 Argon2id 哈希串存进 `meta` 表，绝不落明文。定位是课堂场景的
**防误触 / 防随手改**，不是安全边界：能读写 `callname.db` 的人本来就能
直接改库，js_api 的本地 HTTP 桥也没有鉴权。

参数取 OWASP 建议的档位：m=64 MiB、t=3、p=1。p=1 避免低配教室机被核数
拖慢；参数调整后，`needs_rehash()` 会在下次成功校验时把旧哈希透明升级。
"""

from argon2 import PasswordHasher, extract_parameters
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

#: 密码长度限制。上限只是防止有人往 meta 里塞兆级字符串。
PASSWORD_MIN = 4
PASSWORD_MAX = 128

#: 校验时接受的 Argon2 参数上限。
#:
#: `PasswordHasher.verify()` 按**哈希串自己写的参数**分配内存、跑时间成本，
#: 而 `meta.admin_password` 是用户可手工改的库行。若有人写进一个
#: `m=4294967295` 的合法哈希，verify 会在抛异常前先把管理窗口的内存吃光。
#: 所以我们只用上限以内的哈希；正常写入的参数（64 MiB / t=3 / p=1）远低于它。
#: 上限留足余量，是为了将来调高参数时旧哈希仍能校验。
_MAX_MEMORY_COST = 131072  # KiB = 128 MiB
_MAX_TIME_COST = 10
_MAX_PARALLELISM = 4
_MAX_HASH_LEN = 1024
_MAX_SALT_LEN = 1024
_MAX_STORED_LEN = 512

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


def _within_limits(stored: str) -> bool:
    """先解析参数再决定要不要 verify，避免被极端参数拖垮进程。"""
    if not stored or len(stored) > _MAX_STORED_LEN:
        return False
    try:
        params = extract_parameters(stored)
    except InvalidHashError:
        return False
    return (
        params.memory_cost <= _MAX_MEMORY_COST
        and params.time_cost <= _MAX_TIME_COST
        and params.parallelism <= _MAX_PARALLELISM
        and params.hash_len <= _MAX_HASH_LEN
        and params.salt_len <= _MAX_SALT_LEN
    )


def verify_password(password: str, stored: str) -> bool:
    """校验密码；坏哈希、超限参数、空串一律当失败，不把异常抛给调用方。"""
    if not _within_limits(stored):
        return False
    if not password or len(password) > PASSWORD_MAX:
        return False
    try:
        return _HASHER.verify(stored, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(stored: str) -> bool:
    """参数落后时返回 True；损坏或超出上限的哈希返回 False（不值得重写）。"""
    if not _within_limits(stored):
        return False
    try:
        return _HASHER.check_needs_rehash(stored)
    except InvalidHashError:
        return False
