"""Loopback-only model configuration. Secrets never appear in API responses."""
import hashlib
import hmac
import json
import os
import secrets
import tempfile
import threading
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request

from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

try:
    from . import ai
except ImportError:
    import ai


class ModelInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    base_url: str = Field(min_length=1, max_length=500)
    model: str = Field(min_length=1, max_length=120)
    api_key: SecretStr | None = None
    remember: bool = False
    verification_token: str = Field(default='', max_length=100)

    @field_validator('base_url', 'model', mode='before')
    @classmethod
    def strip_text(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator('base_url')
    @classmethod
    def validate_url(cls, value):
        try:
            parsed = urlsplit(value)
            _ = parsed.port
            valid = (parsed.scheme in {'https', 'http'} and parsed.hostname
                     and parsed.username is None and parsed.password is None and not parsed.query
                     and not parsed.fragment and not any(c.isspace() for c in value)
                     and not any(c in value for c in '\\<>'))
            if parsed.scheme == 'http' and parsed.hostname not in {'localhost', '127.0.0.1', '::1', 'host.docker.internal'}:
                valid = False
        except ValueError:
            valid = False
        if not valid:
            raise ValueError('请填写 HTTPS 接口地址；本机网关可使用 HTTP，不要在地址中填写密钥')
        return value.rstrip('/')

    @field_validator('model')
    @classmethod
    def validate_model(cls, value):
        if not value or any(ord(c) < 32 for c in value):
            raise ValueError('请填写有效的模型名称')
        return value


def test_connection(settings):
    """One short chat request; no retries, redirects, logs or database writes."""
    payload = {'model': settings.model, 'temperature': 0, 'max_tokens': 32,
               'messages': [{'role': 'user', 'content': 'Return only this JSON: {"ok":true}'}],
               'response_format': {'type': 'json_object'}}
    if 'deepseek' in settings.model.lower() or 'api.deepseek.com' in settings.base_url:
        payload['thinking'] = {'type': 'disabled'}
    request = Request(ai.OpenAICompatibleProvider._endpoint(settings.base_url),
                      data=json.dumps(payload).encode(), headers={
                          'Authorization': f'Bearer {settings.api_key}', 'Content-Type': 'application/json'}, method='POST')
    started = time.perf_counter()
    try:
        with ai.urlopen(request, timeout=12) as response:
            data = json.loads(response.read(256_000).decode('utf-8'))
        content = data['choices'][0]['message']['content']
        if not isinstance(content, str) or not content.strip():
            raise ValueError()
    except HTTPError as error:
        message = {401: 'API key 无效，请重新填写', 403: '没有访问该模型的权限',
                   404: '接口地址或模型不存在', 429: '额度不足或请求过于频繁，请稍后再试'}.get(error.code, '接口未通过测试，请核对地址、模型和服务状态')
        raise HTTPException(502, message) from None
    except (URLError, TimeoutError, OSError):
        raise HTTPException(502, '连接失败或超时，请检查接口服务与地址') from None
    except (ValueError, KeyError, IndexError, TypeError, UnicodeError):
        raise HTTPException(502, '接口未返回兼容的回答，请核对模型与接口类型') from None
    return round((time.perf_counter() - started) * 1000)


class ModelConfig:
    def __init__(self, path):
        self.path = Path(path) if path else None
        self.lock = threading.RLock()
        self.csrf_token = secrets.token_urlsafe(32)
        self.web = None
        self.remembered = False
        self.saved_enabled = False
        self.load_error = False
        self.verified = {}
        if self.path and self.path.exists():
            try:
                if self.path.is_symlink():
                    raise ValueError()
                data = json.loads(self.path.read_text(encoding='utf-8'))
                payload = ModelInput(base_url=data['base_url'], model=data['model'], api_key=data['api_key'])
                self.web = self.resolve(payload)
                self.remembered = True
                self.saved_enabled = data.get('enabled') is True
            except (OSError, ValueError, KeyError, TypeError, HTTPException):
                self.load_error = True

    def current(self):
        return self.web or ai.get_ai_settings()

    def resolve(self, payload):
        current = self.current()
        key = payload.api_key.get_secret_value().strip() if payload.api_key is not None else ''
        if not key:
            if payload.base_url != current.base_url.rstrip('/'):
                raise HTTPException(422, '更换接口地址时，请重新输入 API key')
            key = current.api_key
        if not key or len(key) > 4096 or any(c.isspace() for c in key):
            raise HTTPException(422, '请填写有效的 API key')
        return ai.AISettings(key, payload.base_url, payload.model)

    @staticmethod
    def fingerprint(settings):
        return hashlib.sha256(json.dumps([settings.base_url, settings.model, settings.api_key]).encode()).hexdigest()

    def verified_token(self, settings):
        with self.lock:
            self.verified = {k:v for k,v in self.verified.items() if v[1] > time.monotonic()}
            if len(self.verified) >= 16:
                self.verified.clear()
            token = secrets.token_urlsafe(24)
            self.verified[token] = (self.fingerprint(settings), time.monotonic() + 300)
            return token

    def write(self, settings, enabled):
        if self.path is None:
            raise OSError('Persistence unavailable')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            descriptor, temporary = tempfile.mkstemp(prefix='.model-settings-', dir=self.path.parent)
            with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
                json.dump({'api_key': settings.api_key, 'base_url': settings.base_url,
                           'model': settings.model, 'enabled': enabled}, handle, ensure_ascii=False)
            os.replace(temporary, self.path)
        finally:
            if temporary and Path(temporary).exists():
                Path(temporary).unlink()

    def apply(self, payload):
        settings = self.resolve(payload)
        verified = self.verified.get(payload.verification_token)
        if not verified or verified[1] < time.monotonic() or not hmac.compare_digest(verified[0], self.fingerprint(settings)):
            raise HTTPException(409, '配置未通过测试或已变更，请重新测试连接')
        # Disk failures leave the previous in-memory configuration untouched.
        if payload.remember:
            self.write(settings, True)
        elif self.path and self.path.exists():
            self.path.unlink()
        self.web, self.remembered, self.load_error = settings, payload.remember, False
        self.verified.clear()

    def public(self, offline):
        with self.lock:
            settings = self.current()
            return {'base_url': settings.base_url, 'model': settings.model,
                    'has_key': bool(settings.api_key), 'key_mask': '••••••••' if settings.api_key else '',
                    'remembered': self.remembered, 'source': 'web' if self.web else 'environment' if settings.configured else 'none',
                    'mode': 'offline' if offline else 'live', 'csrf_token': self.csrf_token,
                    'load_error': self.load_error}


def install_routes(app, config, activate, tester=None):
    @app.middleware('http')
    async def protect_model_settings(request, call_next):
        if not request.url.path.startswith('/api/model-settings'):
            return await call_next(request)
        allowed_origins = {str(request.base_url).rstrip('/'), 'http://localhost:5173', 'http://127.0.0.1:5173',
                           'http://localhost:3000', 'http://127.0.0.1:3000'}
        origin = request.headers.get('origin')
        host = request.url.hostname
        error = None
        allowed_hosts = {'localhost', '127.0.0.1', '::1'}
        if request.client and request.client.host == 'testclient':
            allowed_hosts.add('testserver')
        if host not in allowed_hosts or (origin and origin not in allowed_origins):
            error = '模型设置仅允许本机工作台访问'
        elif request.method not in {'GET', 'HEAD', 'OPTIONS'} and not hmac.compare_digest(request.headers.get('x-signal-settings-token', '').encode(), config.csrf_token.encode()):
            error = '设置会话已失效，请关闭窗口后重新打开'
        response = JSONResponse({'detail': error}, status_code=403) if error else await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.exception_handler(RequestValidationError)
    async def safe_validation_error(request, error):
        # FastAPI normally echoes invalid inputs, including secret fields.
        details = []
        for issue in error.errors():
            location = issue['loc']
            if request.url.path.startswith('/api/model-settings'):
                allowed = {'body', *ModelInput.model_fields}
                location = [part if part in allowed else '输入' for part in location]
            details.append({'loc': location, 'msg': issue['msg'], 'type': issue['type']})
        return JSONResponse({'detail': details}, status_code=422)

    @app.get('/api/model-settings')
    def status():
        return config.public(app.state.offline)

    @app.post('/api/model-settings/test')
    def probe(payload: ModelInput):
        with config.lock:
            settings = config.resolve(payload)
        try:
            elapsed = (tester or test_connection)(settings)
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(502, '测试未完成，请检查接口服务后重试') from None
        return {'ok': True, 'latency_ms': elapsed, 'verification_token': config.verified_token(settings)}

    @app.put('/api/model-settings')
    def save(payload: ModelInput):
        with config.lock:
            try:
                config.apply(payload)
            except OSError:
                raise HTTPException(503, '无法保存本机配置，请检查目录权限；原配置未更改') from None
            activate(False)
            return config.public(False)

    @app.post('/api/model-settings/offline')
    def use_offline():
        with config.lock:
            try:
                if config.remembered:
                    config.write(config.current(), False)
            except OSError:
                raise HTTPException(503, '无法保存离线模式，请检查目录权限') from None
            activate(True)
            return config.public(True)

    @app.delete('/api/model-settings')
    def clear():
        with config.lock:
            try:
                if config.path and config.path.exists():
                    config.path.unlink()
            except OSError:
                raise HTTPException(503, '无法删除本机配置，请检查目录权限') from None
            config.web, config.remembered, config.load_error = None, False, False
            config.verified.clear()
            activate(True)
            return config.public(True)
