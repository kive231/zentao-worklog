from datetime import date as Date
from decimal import Decimal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator


class Profile(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    base_url: str
    account: str = Field(min_length=1, max_length=80)

    @field_validator('base_url')
    @classmethod
    def check_url(cls, value):
        parts = urlsplit(value.strip())
        if parts.scheme not in ('http', 'https') or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
            raise ValueError('请输入禅道根地址，不包含账号、查询参数或页面路径')
        return value.strip().rstrip('/')


class Login(BaseModel):
    profile_id: str
    password: str = Field(default='', max_length=1000)
    remember: bool = False


class Worklog(BaseModel):
    task_id: int = Field(gt=0)
    date: Date
    work: str = Field(min_length=1, max_length=10000)
    consumed: Decimal = Field(gt=0, le=24, max_digits=6, decimal_places=2)
    left: Decimal = Field(ge=0, le=99999, max_digits=7, decimal_places=2)

    @field_validator('work')
    @classmethod
    def clean_work(cls, value):
        if not value.strip():
            raise ValueError('工作内容不能为空')
        return value.strip()

    @field_validator('date')
    @classmethod
    def past_date(cls, value):
        if value > Date.today():
            raise ValueError('不能记录未来日期的工时')
        return value


class ParseRequest(BaseModel):
    text: str = Field(max_length=1_000_000)
    filename: str = Field(default='粘贴文本', max_length=255)


class ImportRow(BaseModel):
    id: str
    date: str
    work: str
    consumed: float | None = None
    left: float | None = None
    project_hint: str = ''
    task_hint: str = ''
    format_error: str = ''
    project_id: int = 0
    task_id: int = 0
    selected: bool = True
    original: str = ''


class ReviewRequest(BaseModel):
    rows: list[ImportRow] = Field(max_length=1000)


class CommitRequest(BaseModel):
    review_id: str


class EditRequest(Worklog):
    expected: str
