import json
import os

from flask import flash, redirect, render_template, request, url_for

from src.app import (
    BASE_DIR,
    app,
    build_auth_context,
    build_backup_archive,
    build_milestone_board,
    delete_backup_archive,
    ensure_backup_dir,
    get_backup_config,
    get_backup_dir,
    get_branding,
    get_home_cards,
    get_current_user_features,
    get_latest_download_package_info,
    list_backup_history,
    load_backup_manifest,
    load_permission_rules,
    load_milestone_condolence_items,
    login_required,
    permission_config_service,
    record_backup_history,
    require_feature,
    restore_backup_archive,
    save_backup_manifest,
    save_env_settings,
    save_permission_rules,
    write_auto_backup_crontab,
    normalize_feature_flags,
)


@app.route('/settings/general', methods=['GET', 'POST'])
@login_required
def settings_general_page():
    denied = require_feature('view_system', '当前账号不能访问系统页')
    if denied:
        return denied
    branding = get_branding()
    if request.method == 'POST':
        updates = {
            'RELEASEPLAN_BROWSER_TITLE': (request.form.get('browser_title') or '').strip(),
            'RELEASEPLAN_HOME_TITLE': (request.form.get('home_title') or '').strip(),
            'RELEASEPLAN_THEME': (request.form.get('theme') or '').strip(),
        }
        for index in range(1, 7):
            updates[f'RELEASEPLAN_CARD_{index}_TITLE'] = (request.form.get(f'card_{index}_title') or '').strip()
            updates[f'RELEASEPLAN_CARD_{index}_ORDER'] = (request.form.get(f'card_{index}_order') or '').strip()
        save_env_settings(updates)
        os.environ.update({k: v for k, v in updates.items() if v})
        flash('设置已保存')
        return redirect(url_for('settings_general_page'))
    return render_template(
        'settings_general.html',
        branding=branding,
        page_title='系统设置',
        page_desc='调整首页文案、浏览器标题、主题和首页卡片排序。',
        home_cards=get_home_cards(),
        **build_auth_context(),
    )


@app.route('/settings/permissions', methods=['GET', 'POST'])
@login_required
def settings_permissions_page():
    denied = require_feature('manage_permissions', '当前账号不能管理权限配置')
    if denied:
        return denied
    if request.method == 'POST':
        rule_sources = request.form.getlist('permission_source[]')
        rule_types = request.form.getlist('permission_type[]')
        rule_descriptions = request.form.getlist('permission_description[]')
        rule_values = request.form.getlist('permission_value[]')
        rules = []
        total = max(len(rule_sources), len(rule_types), len(rule_descriptions), len(rule_values))
        feature_keys = permission_config_service.FEATURE_KEYS
        truthy_values = {'1', 'true', 'on', 'yes'}
        for idx in range(total):
            rule_source = (rule_sources[idx] if idx < len(rule_sources) else 'sso').strip()
            rule_type = (rule_types[idx] if idx < len(rule_types) else '').strip()
            rule_description = (rule_descriptions[idx] if idx < len(rule_descriptions) else '').strip()
            rule_value = (rule_values[idx] if idx < len(rule_values) else '').strip()
            if not rule_value:
                continue
            features = {
                key: (request.form.get(f'permission_feature_{key}[{idx}]') or '').strip().lower() in truthy_values
                for key in feature_keys
            }
            role = permission_config_service.role_from_features(features)
            rules.append({
                'source': rule_source,
                'type': rule_type,
                'description': rule_description,
                'value': rule_value,
                'role': role,
                'features': normalize_feature_flags(features, role),
            })
        save_permission_rules(rules)
        flash('权限规则已保存')
        return redirect(url_for('settings_permissions_page'))
    return render_template(
        'settings_permissions.html',
        branding=get_branding(),
        page_title='权限配置',
        page_desc='配置本地用户和 SSO 用户的访问权限。',
        permission_rules=load_permission_rules(),
        permission_presets=permission_config_service.get_permission_presets(),
        feature_keys=permission_config_service.FEATURE_KEYS,
        **build_auth_context(),
    )


@app.route('/settings/backups', methods=['GET', 'POST'])
@login_required
def settings_backups_page():
    denied = require_feature('manage_backup', '当前账号不能管理备份')
    if denied:
        return denied
    ensure_backup_dir()
    if request.method == 'POST':
        action = (request.form.get('action') or '').strip()
        if action in {'save-settings', 'save_settings'}:
            auto_backup_enabled = (request.form.get('auto_backup_enabled') or '').strip().lower() in {'1', 'true', 'on', 'yes'}
            auto_backup_time = (request.form.get('auto_backup_time') or '').strip()
            updates = {
                'RELEASEPLAN_AUTO_BACKUP_ENABLED': 'true' if auto_backup_enabled else 'false',
                'RELEASEPLAN_AUTO_BACKUP_TIME': auto_backup_time,
            }
            try:
                save_env_settings(updates)
                os.environ.update(updates)
                write_auto_backup_crontab(auto_backup_enabled, auto_backup_time)
                flash('备份设置已保存')
            except ValueError:
                flash('备份时间格式不正确，请使用 HH:MM')
            except Exception as exc:
                flash(f'保存备份设置失败：{exc}')
            return redirect(url_for('settings_backups_page'))
        if action in {'backup-now', 'run_backup_now'}:
            archive_path = build_backup_archive('manual')
            record_backup_history(archive_path, 'manual')
            flash('备份已生成')
            return redirect(url_for('settings_backups_page'))
        if action in {'restore-backup', 'restore_backup'}:
            filename = (request.form.get('filename') or request.form.get('backup_filename') or '').strip()
            restore_backup_archive(filename)
            flash('备份已恢复')
            return redirect(url_for('settings_backups_page'))
        if action in {'delete-backup', 'delete_backup'}:
            filename = (request.form.get('filename') or request.form.get('backup_filename') or '').strip()
            delete_backup_archive(filename)
            flash('备份已删除')
            return redirect(url_for('settings_backups_page'))
        if action == 'save-manifest':
            raw = (request.form.get('manifest_json') or '[]').strip()
            try:
                items = json.loads(raw)
                if not isinstance(items, list):
                    raise ValueError('manifest must be list')
                save_backup_manifest(items)
                flash('备份清单已保存')
            except Exception as exc:
                flash(f'保存备份清单失败：{exc}')
            return redirect(url_for('settings_backups_page'))
    return render_template(
        'settings_backups.html',
        branding=get_branding(),
        page_title='备份管理',
        page_desc='管理自动备份、手动备份、安装包下载和备份恢复。',
        backup_dir=str(get_backup_dir()),
        backup_config=get_backup_config(),
        backup_history=list_backup_history(),
        backup_manifest=load_backup_manifest(),
        download_packages=get_latest_download_package_info(),
        milestone_board=build_milestone_board(load_milestone_condolence_items()),
        base_dir=str(BASE_DIR),
        **build_auth_context(),
    )
