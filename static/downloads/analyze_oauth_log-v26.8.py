#!/usr/bin/env python3
"""
ReleasePlan SSO/OAuth 日志分析脚本

常用用法：
1. 在 ReleasePlan 安装目录运行：
   python3 analyze_oauth_log.py

2. 指定安装目录：
   python3 analyze_oauth_log.py --base-dir /path/to/ReleasePlan

3. 指定日志文件和输出报告：
   python3 analyze_oauth_log.py \
     --log-path /path/to/oauth_callback_debug.log \
     --report-path /path/to/oauth_sso_diagnosis_report.txt

默认行为：
- 优先读取 /app/data/oauth_callback_debug.log（适合 Docker 挂载卷场景）
- 如果不存在，再尝试环境变量 RELEASEPLAN_OAUTH_DEBUG_LOG_PATH
- 如果还未配置，再回退到自动探测的 <安装目录>/logs/oauth_callback_debug.log
- 默认输出到脚本运行时所在目录的 oauth_sso_diagnosis_report.txt
"""
import argparse
import json
import os
from collections import Counter
from pathlib import Path


def detect_base_dir(explicit_base=None):
    if explicit_base:
        return Path(explicit_base).resolve()

    script_path = Path(__file__).resolve()
    candidates = [Path.cwd(), script_path.parent, script_path.parent.parent]
    for candidate in candidates:
        if (candidate / 'src').exists() and (candidate / 'templates').exists():
            return candidate
        if candidate.name == 'scripts' and (candidate.parent / 'src').exists():
            return candidate.parent
    return Path.cwd().resolve()


def load_records(log_path):
    if not log_path.exists():
        return []
    records = []
    for line in log_path.read_text(encoding='utf-8', errors='ignore').splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except Exception:
            continue
    return records


def is_external_call_record(record):
    return any([
        record.get('authorize_url'),
        record.get('token_url'),
        record.get('userinfo_url'),
        record.get('query'),
        record.get('data'),
        record.get('headers'),
        record.get('params'),
        record.get('status_code') not in (None, ''),
    ])


def infer_success(record):
    if 'success' in record and record.get('success') not in (None, ''):
        return str(record.get('success'))
    status_code = str(record.get('status_code') or '')
    response_preview = (record.get('response_preview') or '').lower()
    if not status_code:
        return '已发起'
    if not status_code.startswith('2'):
        return '否'
    if any(keyword in response_preview for keyword in ['error', 'errorcode', 'failed', 'exception']):
        return '否'
    return '是'


def main():
    parser = argparse.ArgumentParser(description='分析 ReleasePlan 的 OAuth/SSO 调试日志，并生成中文诊断报告。')
    parser.add_argument('--base-dir', default='', help='ReleasePlan 安装根目录，不传则自动探测')
    parser.add_argument('--log-path', default='', help='OAuth 调试日志路径，不传则默认使用 <base-dir>/logs/oauth_callback_debug.log')
    parser.add_argument('--report-path', default='', help='输出报告路径，不传则默认输出到 <base-dir>/oauth_sso_diagnosis_report.txt')
    args = parser.parse_args()

    base_dir = detect_base_dir(args.base_dir)
    configured_log_path = (os.getenv('RELEASEPLAN_OAUTH_DEBUG_LOG_PATH') or '').strip()
    docker_default_log_path = Path('/app/data/oauth_callback_debug.log')
    if args.log_path:
        log_path = Path(args.log_path).resolve()
    elif docker_default_log_path.exists() or base_dir == Path('/app') or str(base_dir).startswith('/app/'):
        log_path = docker_default_log_path
    elif configured_log_path:
        log_path = Path(configured_log_path).expanduser().resolve()
    else:
        log_path = base_dir / 'logs' / 'oauth_callback_debug.log'
    report_path = Path(args.report_path).resolve() if args.report_path else (Path.cwd() / 'oauth_sso_diagnosis_report.txt')

    records = load_records(log_path)
    lines = []
    lines.append('ReleasePlan SSO/OAuth 日志诊断报告')
    lines.append('')
    lines.append(f'项目目录: {base_dir}')
    lines.append(f'日志文件: {log_path}')
    lines.append(f'记录条数: {len(records)}')
    lines.append('')

    if not records:
        lines.append('未发现日志记录。')
        lines.append('建议：先实际走一遍 SSO 登录，再重新生成本报告。')
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        print(report_path)
        return

    event_counter = Counter()
    userinfo_modes = Counter()
    userinfo_status = Counter()
    response_previews = []
    source_locations = Counter()
    call_details = []
    callback_missing_code = 0
    state_mismatch = 0
    duplicate_code = 0

    for record in records:
        event = record.get('event') or 'unknown'
        event_counter[event] += 1
        source_file = record.get('source_file') or ''
        source_line = record.get('source_line') or ''
        source_func = record.get('source_func') or ''
        if source_file or source_line or source_func:
            source_locations[f'{source_file}:{source_line} ({source_func})'] += 1

        if event == 'callback_missing_code':
            callback_missing_code += 1
        if event == 'callback_state_mismatch':
            state_mismatch += 1
        if event == 'callback_duplicate_code':
            duplicate_code += 1

        if is_external_call_record(record):
            detail = {
                'event': event,
                'time': record.get('time') or '',
                'source_file': source_file,
                'source_line': source_line,
                'source_func': source_func,
                'authorize_url': record.get('authorize_url') or '',
                'token_url': record.get('token_url') or '',
                'userinfo_url': record.get('userinfo_url') or '',
                'mode': record.get('mode') or '',
                'query': record.get('query') or {},
                'data': record.get('data') or {},
                'headers': record.get('headers') or {},
                'params': record.get('params') or {},
                'status_code': record.get('status_code') or '',
                'response_preview': record.get('response_preview') or '',
                'success': infer_success(record),
            }
            call_details.append(detail)

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

    if source_locations:
        lines.append('二、源码定位统计')
        for key, count in source_locations.most_common(10):
            lines.append(f'- {key}: {count}')
        lines.append('')

    lines.append('三、初步判断')
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

    lines.append('四、userinfo 尝试情况')
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
        lines.append('五、最近响应摘要')
        for item in response_previews[-5:]:
            lines.append(f'- {item}')
        lines.append('')

    if call_details:
        lines.append('六、外部接口调用明细')
        for index, item in enumerate(call_details, 1):
            lines.append(f"- 第{index}次: {item['event']}")
            lines.append(f"  - 时间: {item['time']}")
            lines.append(f"  - 源码位置: {item['source_file']}:{item['source_line']} ({item['source_func']})")
            if item['authorize_url']:
                lines.append(f"  - authorize_url: {item['authorize_url']}")
            if item['token_url']:
                lines.append(f"  - token_url: {item['token_url']}")
            if item['userinfo_url']:
                lines.append(f"  - userinfo_url: {item['userinfo_url']}")
            if item['mode']:
                lines.append(f"  - mode: {item['mode']}")
            if item['query']:
                lines.append(f"  - query: {json.dumps(item['query'], ensure_ascii=False)}")
            if item['data']:
                lines.append(f"  - data: {json.dumps(item['data'], ensure_ascii=False)}")
            if item['headers']:
                lines.append(f"  - headers: {json.dumps(item['headers'], ensure_ascii=False)}")
            if item['params']:
                lines.append(f"  - params: {json.dumps(item['params'], ensure_ascii=False)}")
            if item['status_code'] != '':
                lines.append(f"  - status_code: {item['status_code']}")
            if item['response_preview']:
                lines.append(f"  - response_preview: {item['response_preview']}")
            lines.append(f"  - success: {item['success']}")
        lines.append('')

    lines.append('七、解决建议')
    for item in suggestions:
        lines.append(f'- {item}')
    lines.append('- 如需进一步定位，可让管理员在服务器本机执行本脚本后直接查看文本报告，无需导出原始日志。')
    lines.append('')

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(report_path)


if __name__ == '__main__':
    main()
