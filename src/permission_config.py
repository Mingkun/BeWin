import json
import re
from pathlib import Path

FEATURE_KEYS = [
    'view_milestone',
    'view_requirements',
    'view_projects',
    'view_features',
    'view_service_resources',
    'view_resource_people',
    'view_investment',
    'view_system',
    'manage_permissions',
    'manage_backup',
    'submit_requirement',
    'manage_requirement_status',
    'manage_projects',
    'manage_features',
    'manage_service_resources',
    'import_export_data',
]

GUEST_FEATURES = {
    'view_milestone': True,
    'view_requirements': True,
    'view_projects': False,
    'view_features': False,
    'view_service_resources': False,
    'view_resource_people': False,
    'view_investment': False,
    'view_system': False,
    'manage_permissions': False,
    'manage_backup': False,
    'submit_requirement': True,
    'manage_requirement_status': False,
    'manage_projects': False,
    'manage_features': False,
    'manage_service_resources': False,
    'import_export_data': False,
}

PERMISSION_PRESETS = [
    {
        'key': 'super_admin',
        'label': '超级管理员',
        'group': 'system',
        'description': '系统配置、权限、备份、业务数据全部可管理。',
        'role': 'admin',
        'features': {key: True for key in FEATURE_KEYS},
    },
    {
        'key': 'system_admin',
        'label': '系统管理员',
        'group': 'system',
        'description': '可进入系统页，管理权限和备份，不负责业务数据维护。',
        'role': 'admin',
        'features': {
            'view_milestone': False,
            'view_requirements': False,
            'view_projects': False,
            'view_features': False,
            'view_service_resources': False,
            'view_resource_people': False,
            'view_investment': False,
            'view_system': True,
            'manage_permissions': True,
            'manage_backup': True,
            'submit_requirement': False,
            'manage_requirement_status': False,
            'manage_projects': False,
            'manage_features': False,
            'manage_service_resources': False,
            'import_export_data': False,
        },
    },
    {
        'key': 'guest',
        'label': 'Guest 访客',
        'group': 'business',
        'description': '只能查看关键突破信息卡片、提交/查看需求，并查看当前登录用户信息。',
        'role': 'guest',
        'features': GUEST_FEATURES,
    },
    {
        'key': 'readonly_user',
        'label': '只读用户',
        'group': 'business',
        'description': '只能查看页面，不可进入系统页，也不能提交和修改数据。',
        'role': 'user',
        'features': {
            'view_milestone': True,
            'view_requirements': True,
            'view_projects': True,
            'view_features': True,
            'view_service_resources': True,
            'view_resource_people': True,
            'view_investment': True,
            'view_system': False,
            'manage_permissions': False,
            'manage_backup': False,
            'submit_requirement': False,
            'manage_requirement_status': False,
            'manage_projects': False,
            'manage_features': False,
            'manage_service_resources': False,
            'import_export_data': False,
        },
    },
    {
        'key': 'requirement_submitter',
        'label': '需求提交人',
        'group': 'business',
        'description': '可提交需求，但不能改需求状态，也不能维护项目和系统配置。',
        'role': 'user',
        'features': {
            'view_milestone': True,
            'view_requirements': True,
            'view_projects': True,
            'view_features': True,
            'view_service_resources': True,
            'view_resource_people': True,
            'view_investment': True,
            'view_system': False,
            'manage_permissions': False,
            'manage_backup': False,
            'submit_requirement': True,
            'manage_requirement_status': False,
            'manage_projects': False,
            'manage_features': False,
            'manage_service_resources': False,
            'import_export_data': False,
        },
    },
    {
        'key': 'requirement_manager',
        'label': '需求管理员',
        'group': 'business',
        'description': '可提交需求并修改需求状态，但不改项目、云服务和系统配置。',
        'role': 'user',
        'features': {
            'view_milestone': True,
            'view_requirements': True,
            'view_projects': True,
            'view_features': True,
            'view_service_resources': True,
            'view_resource_people': True,
            'view_investment': True,
            'view_system': False,
            'manage_permissions': False,
            'manage_backup': False,
            'submit_requirement': True,
            'manage_requirement_status': True,
            'manage_projects': False,
            'manage_features': False,
            'manage_service_resources': False,
            'import_export_data': False,
        },
    },
    {
        'key': 'project_editor',
        'label': '项目维护人',
        'group': 'business',
        'description': '可维护项目、关键特性和导入导出。',
        'role': 'user',
        'features': {
            'view_milestone': True,
            'view_requirements': True,
            'view_projects': True,
            'view_features': True,
            'view_service_resources': True,
            'view_resource_people': True,
            'view_investment': True,
            'view_system': False,
            'manage_permissions': False,
            'manage_backup': False,
            'submit_requirement': True,
            'manage_requirement_status': False,
            'manage_projects': True,
            'manage_features': True,
            'manage_service_resources': False,
            'import_export_data': True,
        },
    },
    {
        'key': 'service_editor',
        'label': '云服务维护人',
        'group': 'business',
        'description': '可维护云服务资源和导入导出。',
        'role': 'user',
        'features': {
            'view_milestone': True,
            'view_requirements': True,
            'view_projects': True,
            'view_features': True,
            'view_service_resources': True,
            'view_resource_people': True,
            'view_investment': True,
            'view_system': False,
            'manage_permissions': False,
            'manage_backup': False,
            'submit_requirement': True,
            'manage_requirement_status': False,
            'manage_projects': False,
            'manage_features': False,
            'manage_service_resources': True,
            'import_export_data': True,
        },
    },
]


def get_permission_rules_path(base_dir):
    return Path(base_dir) / 'data' / 'permission_rules.json'


def load_permission_rules(base_dir):
    path = get_permission_rules_path(base_dir)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_permission_rules(base_dir, items):
    path = get_permission_rules_path(base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding='utf-8')


def normalize_permission_role(role_text):
    role = (role_text or '').strip().lower()
    if role == 'admin':
        return 'admin'
    if role == 'guest':
        return 'guest'
    return 'user'


def role_from_features(features, role_text=None):
    normalized = features if isinstance(features, dict) else {}
    admin_feature_keys = {'view_system', 'manage_permissions', 'manage_backup'}
    if any(bool(normalized.get(key)) for key in admin_feature_keys):
        return 'admin'
    return 'guest' if normalize_permission_role(role_text) == 'guest' else 'user'


def default_feature_flags(role):
    role = normalize_permission_role(role)
    if role == 'admin':
        return {key: True for key in FEATURE_KEYS}
    if role == 'guest':
        return GUEST_FEATURES.copy()
    return {
        'view_milestone': True,
        'view_requirements': True,
        'view_projects': True,
        'view_features': True,
        'view_service_resources': True,
        'view_resource_people': True,
        'view_investment': True,
        'view_system': False,
        'manage_permissions': False,
        'manage_backup': False,
        'submit_requirement': True,
        'manage_requirement_status': False,
        'manage_projects': False,
        'manage_features': False,
        'manage_service_resources': False,
        'import_export_data': True,
    }


def normalize_feature_flags(raw, role):
    defaults = default_feature_flags(role)
    if not isinstance(raw, dict):
        return defaults
    normalized = defaults.copy()
    for key in FEATURE_KEYS:
        if key in raw:
            normalized[key] = bool(raw[key])
    return normalized


def get_permission_presets():
    presets = []
    for item in PERMISSION_PRESETS:
        features = normalize_feature_flags(item.get('features'), item.get('role'))
        role = role_from_features(features, item.get('role'))
        presets.append({
            'key': item.get('key'),
            'label': item.get('label'),
            'group': item.get('group') or 'business',
            'description': item.get('description') or '',
            'role': role,
            'features': features,
        })
    return presets


def normalize_permission_source(source_text):
    source = (source_text or '').strip().lower()
    return source if source in {'local', 'sso'} else 'sso'


def normalize_permission_type(source, rule_type):
    source = normalize_permission_source(source)
    value = (rule_type or '').strip().lower()
    allowed = {'local': {'username', 'email'}, 'sso': {'email', 'employee_number'}}
    if value in allowed[source]:
        return value
    return 'username' if source == 'local' else 'email'


def split_permission_values(raw_rule_value):
    raw = str(raw_rule_value or '').strip()
    if not raw:
        return []
    return [part.strip().lower() for part in re.split(r'[;\/\s]+', raw) if part.strip()]


def merge_permission_matches(matches):
    if not matches:
        return None
    merged_features = {key: False for key in FEATURE_KEYS}
    matched_roles = []
    for item in matches:
        role = role_from_features(item.get('features'), item.get('role'))
        matched_roles.append(role)
        features = normalize_feature_flags(item.get('features'), role)
        for key in FEATURE_KEYS:
            merged_features[key] = bool(merged_features.get(key)) or bool(features.get(key))

    if any(bool(merged_features.get(key)) for key in {'view_system', 'manage_permissions', 'manage_backup'}):
        merged_role = 'admin'
    elif any(role != 'guest' for role in matched_roles):
        merged_role = 'user'
    else:
        merged_role = 'guest'
    return {
        'role': merged_role,
        'features': normalize_feature_flags(merged_features, merged_role),
        'matched_count': len(matches),
    }


def match_permission_rule(base_dir, source='sso', username='', email='', employee_number=''):
    source = normalize_permission_source(source)
    username = (username or '').strip().lower()
    email = (email or '').strip().lower()
    employee_number = str(employee_number or '').strip().lower()
    matches = []
    for item in load_permission_rules(base_dir):
        rule_source = normalize_permission_source(item.get('source'))
        if rule_source != source:
            continue
        rule_type = normalize_permission_type(rule_source, item.get('type'))
        raw_rule_value = (item.get('value') or '').strip()
        rule_values = split_permission_values(raw_rule_value)
        if not rule_values:
            continue
        matched = False
        if rule_source == 'local' and rule_type == 'username' and username and username in rule_values:
            matched = True
        if rule_type == 'email' and email and email in rule_values:
            matched = True
        if rule_source == 'sso' and rule_type == 'employee_number' and employee_number and employee_number in rule_values:
            matched = True
        if matched:
            matches.append(item)
    return merge_permission_matches(matches)
