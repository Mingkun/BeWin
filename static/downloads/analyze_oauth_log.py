#!/usr/bin/env python3
import json
from collections import Counter
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
LOG_PATH = BASE_DIR / 'logs' / 'oauth_callback_debug.log'
REPORT_PATH = BASE_DIR / 'static' / 'downloads' / 'oauth_sso_diagnosis_report.txt'


def load_records():
    if not LOG_PATH.exists():
        return []
    records = []
    for line in LOG_PATH.read_text(encoding='utf-8', errors='ignore').splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except Exception:
            continue
    return records


def main():
    records = load_records()
    lines = []
    lines.append('ReleasePlan SSO/OAuth 日志诊断报告')
    lines.append('')
    lines.append(f'日志文件: {LOG_PATH}')
    lines.append(f'记录条数: {len(records)}')
    lines.append('')

    if not records:
        lines.append('未发现日志记录。')
        lines.append('建议：先实际走一遍 SSO 登录，再重新生成本报告。')
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        print(REPORT_PATH)
        return

    event_counter = Counter()
    userinfo_modes = Counter()
    userinfo_status = Counter()
    response_previews = []
    callback_missing_code = 0
    state_mismatch = 0
    duplicate_code = 0

    for record in records:
        event = record.get('event') or 'unknown'
        event_counter[event] += 1
        if event == 'callback_missing_code':
            callback_missing_code += 1
        if event == 'callback_state_mismatch':
            state_mismatch += 1
        if event == 'callback_duplicate_code':
            duplicate_code += 1
        if event == 'userinfo_attempt':
            mode = record.get('mode') or 'unknown'
            status = str(record.get('status_code') or 'unknown')
            preview = (record.get('response_preview') or '').strip()
            userinfo_modes[mode] += 1
            userinfo_status[status] += 1
            if preview:
                response_previews.append(preview)

    lines.append('一、事件统计')
    for key, count in event_counter.most_common():
        lines.append(f'- {key}: {count}')
    lines.append('')

    lines.append('二、初步判断')
    diagnosis = []
    suggestions = []

    preview_text = '\n'.join(response_previews[-10:])
    if 'access_token Parameter error' in preview_text or 'E_10011' in preview_text:
        diagnosis.append('userinfo 接口返回 access_token 参数错误，说明当前 access_token 传递方式或 token 字段不符合公司 SSO 要求。')
        suggestions.append('优先核对公司 SSO 的 userinfo 接口文档，确认 access_token 应放在 Header、Query 参数还是其他字段。')
        suggestions.append('如果已知规则，设置 RELEASEPLAN_OAUTH_USERINFO_TOKEN_MODE 为 bearer、query_access_token 或 query_token 之一，固定使用正确模式。')
    if state_mismatch:
        diagnosis.append('出现过 state 校验失败，可能存在回调地址不一致、重复打开登录页、浏览器会话丢失或反向代理前缀配置问题。')
        suggestions.append('检查 RELEASEPLAN_OAUTH_REDIRECT_URI、X-Forwarded-Proto、X-Forwarded-Prefix 是否与实际访问地址一致。')
    if duplicate_code:
        diagnosis.append('出现过重复 code，可能是回调被重复请求，或浏览器刷新了 OAuth 回调地址。')
        suggestions.append('避免重复刷新 callback 页面，确认是否有代理或前端逻辑重复触发回调。')
    if callback_missing_code:
        diagnosis.append('出现过缺少 code 的回调，说明 SSO 平台或中间跳转没有正确带回授权码。')
        suggestions.append('检查 authorize_url、redirect_uri 是否正确，确认 SSO 平台没有拦截或改写参数。')
    if not diagnosis and userinfo_modes:
        diagnosis.append('日志显示已尝试多种 userinfo 调用方式，但仍未明确成功，建议继续对照公司 SSO 文档核对 token 接口与 userinfo 接口规范。')
        suggestions.append('确认 token 接口返回的哪个字段才是真正用于 userinfo 的访问令牌。')
    if not diagnosis:
        diagnosis.append('当前日志不足以定位问题。')
        suggestions.append('先执行一次完整 SSO 登录，再重新生成报告。')

    for item in diagnosis:
        lines.append(f'- {item}')
    lines.append('')

    lines.append('三、userinfo 尝试情况')
    if userinfo_modes:
        lines.append('- 尝试模式统计:')
        for key, count in userinfo_modes.most_common():
            lines.append(f'  - {key}: {count}')
        lines.append('- 状态码统计:')
        for key, count in userinfo_status.most_common():
            lines.append(f'  - {key}: {count}')
    else:
        lines.append('- 暂无 userinfo_attempt 记录')
    lines.append('')

    if response_previews:
        lines.append('四、最近响应摘要')
        for item in response_previews[-5:]:
            lines.append(f'- {item}')
        lines.append('')

    lines.append('五、解决建议')
    for item in suggestions:
        lines.append(f'- {item}')
    lines.append('- 如需进一步定位，可让管理员在服务器本机执行本脚本后直接查看文本报告，无需导出原始日志。')
    lines.append('')

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(REPORT_PATH)


if __name__ == '__main__':
    main()
