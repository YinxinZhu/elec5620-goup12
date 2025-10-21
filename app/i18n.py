"""Lightweight internationalisation helpers for the learner portal."""

from __future__ import annotations

from functools import lru_cache
from typing import Iterable

DEFAULT_LANGUAGE = "ENGLISH"

SUPPORTED_LANGUAGES: dict[str, dict[str, str]] = {
    "ENGLISH": {"label": "English", "icon": "🇦🇺", "locale": "en"},
    "CHINESE": {"label": "简体中文", "icon": "🇨🇳", "locale": "zh-Hans"},
}


TRANSLATIONS: dict[str, dict[str, str]] = {
    "CHINESE": {
        "Portal Login": "门户登录",
        "Learner Practice Portal": "学员练习平台",
        "Dashboard": "仪表盘",
        "Profile": "个人资料",
        "Availability": "可用时间",
        "Appointments": "预约",
        "Students": "学员",
        "Personnel": "人员管理",
        "Sign in to the portal": "登录门户",
        "Use your registered mobile number and password to access the administrator, coach, or learner experience.": "使用注册的手机号码和密码访问管理员、教练或学员界面。",
        "Mobile number": "手机号",
        "Password": "密码",
        "Sign in": "登录",
        "Register learner account": "注册学员账户",
        "Register a learner account": "注册学员账户",
        "Close": "关闭",
        "Complete the form below to create a learner account. After registration we will sign you in automatically.": "填写以下表格创建学员账户。注册成功后我们会自动为您登录。",
        "Full name": "姓名",
        "Email": "电子邮箱",
        "(optional)": "（可选）",
        "State or territory": "州或领地",
        "Select your state": "选择所在州",
        "Preferred language": "首选语言",
        "Password": "密码",
        "Confirm password": "确认密码",
        "Submit registration": "提交注册",
        "English": "英语",
        "Chinese": "中文",
        "Dashboard Overview": "仪表盘概览",
        "Student Dashboard": "学员仪表盘",
        "Learner Dashboard": "学习者仪表盘",
        "Welcome back, {name}. Track your bookings and latest practice progress below.": "欢迎回来，{name}。在这里查看您的预约和最新练习进度。",
        "Upcoming sessions": "即将到来的课程",
        "Start": "开始时间",
        "Coach": "教练",
        "Location": "地点",
        "Status": "状态",
        "You have no upcoming sessions booked. Check with your coach to schedule one.": "您暂时没有预定课程，请联系教练安排。",
        "Recent practice summary": "近期练习概览",
        "Last mock exam score:": "最近一次模拟考试成绩：",
        "Attempted on {date}.": "完成于 {date}。",
        "Complete a mock exam in the learner app to see your progress here.": "在学员应用中完成一次模拟考试即可在此查看进度。",
        "Upcoming lessons": "即将到来的课程",
        "No upcoming lessons scheduled.": "没有安排即将到来的课程。",
        "Latest mock exam": "最近的模拟考试",
        "No mock exam history yet.": "尚无模拟考试记录。",
        "Update profile": "更新资料",
        "Student Profile": "学员资料",
        "Profile settings": "资料设置",
        "Update your learner profile details and password.": "更新您的学员资料和密码。",
        "Optional": "可选",
        "Update password": "更新密码",
        "Leave blank to keep your current password.": "留空则保持当前密码。",
        "New password": "新密码",
        "Save changes": "保存修改",
        "Name": "姓名",
        "Email address": "电子邮箱",
        "Current password": "当前密码",
        "New password": "新密码",
        "Confirm new password": "确认新密码",
        "Save changes": "保存修改",
        "Only student accounts may access the learner portal.": "只有学员账户才能访问学员门户。",
        "Please choose a valid state or territory.": "请选择有效的州或领地。",
        "Please choose a supported language.": "请选择支持的语言。",
        "Passwords do not match.": "两次密码输入不一致。",
        "Profile updated successfully!": "个人资料更新成功！",
        "Welcome back!": "欢迎回来！",
        "Invalid mobile number or password": "手机号或密码错误",
        "Hi": "你好",
        "Admin": "管理员",
        "Please choose a supported language.": "请选择支持的语言。",
        "Language switched to {label}.": "语言已切换为{label}。",
        "Language selection": "语言选择",
        "Logout": "退出登录",
    }
}


def normalise_language_code(language: str | None) -> str | None:
    """Return a canonical language code if supported."""

    if not language:
        return None
    code = language.strip().upper()
    if code in SUPPORTED_LANGUAGES:
        return code
    return None


def ensure_language_code(language: str | None) -> str:
    """Return a supported language code, defaulting when unknown."""

    normalised = normalise_language_code(language)
    return normalised or DEFAULT_LANGUAGE


def translate_text(text: str, language: str, **format_values: str) -> str:
    """Translate the given string for the requested language."""

    catalogue = TRANSLATIONS.get(language, {})
    translated = catalogue.get(text, text)
    if format_values:
        try:
            return translated.format(**format_values)
        except (KeyError, IndexError):
            return translated
    return translated


@lru_cache(maxsize=None)
def get_language_choices() -> list[dict[str, str]]:
    """Return metadata describing supported languages for presentation."""

    return [
        {"code": code, **meta}
        for code, meta in SUPPORTED_LANGUAGES.items()
    ]


def language_label(language: str) -> str:
    """Return a human readable label for the given language code."""

    code = ensure_language_code(language)
    meta = SUPPORTED_LANGUAGES.get(code, SUPPORTED_LANGUAGES[DEFAULT_LANGUAGE])
    icon = meta.get("icon", "")
    label = meta.get("label", code.title())
    return f"{icon} {label}".strip()


def translation_catalogue(language: str) -> dict[str, str]:
    """Expose the translation mapping for templates."""

    code = ensure_language_code(language)
    return TRANSLATIONS.get(code, {})


__all__: Iterable[str] = [
    "DEFAULT_LANGUAGE",
    "SUPPORTED_LANGUAGES",
    "TRANSLATIONS",
    "ensure_language_code",
    "get_language_choices",
    "language_label",
    "normalise_language_code",
    "translate_text",
    "translation_catalogue",
]
